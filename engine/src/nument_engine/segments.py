"""Segment configuration: one YAML file per domain x country (Step 3).

load_segments()         validated Segment objects, keyed by id
sync_segments_to_db()   upsert into public.segments
scoring_config(seg)     config/scoring.yaml with the segment's `scoring` overrides applied
load_yaml_config(name)  engine/config/<name>.yaml

Adding a market means adding a file, not changing code (A.6.3.5). The key names are fixed (Step 3.3):
Steps 5 to 12 read them. `docs/segments-guide.md` explains how to add a segment.
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .models import Domain, SignalType
from .settings import ENGINE_DIR

SEGMENTS_DIR = ENGINE_DIR / "segments"
CONFIG_DIR = ENGINE_DIR / "config"

Op = Literal[">=", "<=", "==", "!=", "in", "not_in", "exists"]

PACKAGED_OUTCOME: dict[str, str] = {  # A.2.2; must match
    "clinics": "AI front desk",
    "realestate": "AI lead qualifier and site-visit booking",
    "education": "AI admissions counsellor",
    "d2c": "AI support, order and cash-on-delivery confirmations",
    "hospitality": "AI enquiry to quote",
    "auto": "AI lead follow-up and service booking",
    "finance": "AI renewals and document chasing",
    "wellness": "AI bookings and renewals",
    "firms": "Custom AI workflows",
}
# Angle codes Step 11 picks by signal type (11.8.2). Every segment must define all of them.
REQUIRED_ANGLES = frozenset(
    {"build_what_they_asked", "frontdesk_load", "missed_calls", "ad_leads_cold", "no_online_booking", "slow_site"}
)
GROWTH_SIGNALS = frozenset({"new_place", "new_branch", "news"})

BBox = tuple[float, float, float, float]


class SegmentConfigError(SystemExit):
    """A segment or config file is invalid. Stops the run with one clear message (Step 3.2)."""


class City(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    bbox: BBox  # min_lng, min_lat, max_lng, max_lat
    localities: list[str] = Field(min_length=1)

    @field_validator("bbox")
    @classmethod
    def _bbox_ok(cls, v: BBox) -> BBox:
        min_lng, min_lat, max_lng, max_lat = v
        if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError(f"bad bbox {v}: use [min_lng, min_lat, max_lng, max_lat]")
        if max_lng - min_lng > 2 or max_lat - min_lat > 2:
            raise ValueError(f"bbox {v} is wider than 2 degrees: split the city")
        return v


class Quota(BaseModel):
    daily_research: int = Field(ge=0, le=300)


class Overture(BaseModel):
    categories: list[str] = Field(default_factory=list)  # required for a map universe (Segment._consistency)


class Places(BaseModel):
    queries: list[str] = Field(default_factory=list)  # required for a map universe
    details_per_day: int = Field(ge=0, le=230)
    reviews_per_day: int = Field(ge=0, le=230)

    @field_validator("queries")
    @classmethod
    def _has_city(cls, v: list[str]) -> list[str]:
        bad = [q for q in v if "{city}" not in q]
        if bad:
            raise ValueError(f"every query needs {{city}}: {bad}")
        return v


class Registry(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    url: str
    status: Literal["ready", "verify_at_build"]
    subcategory: str | None = None
    notes: str | None = None


class Osm(BaseModel):
    enabled: bool = False


class Apna(BaseModel):
    pages_per_day: int = Field(0, ge=0, le=2000)


class JobKeywords(BaseModel):
    frontdesk: list[str] = Field(min_length=1)
    builder: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    """business: a businesses column. fact: a verified fact (`field` = the number inside its value).
    signal: an active signal of type `key`. registry: a source record from registry `key` ('*' = any)."""

    source: Literal["business", "fact", "signal", "registry"]
    key: str
    field: str | None = None
    op: Op
    value: Any = None


class SizeRules(BaseModel):
    any_of: list[Rule] = Field(min_length=1)


class Fit(BaseModel):
    categories: list[str] = Field(min_length=1)
    service_keywords: list[str] = Field(default_factory=list)
    min_reviews: int = Field(100, ge=0)
    min_staff: int = Field(2, ge=0)
    # Words in a business name that mark a type the segment does not target, for example "spoken english" in
    # education (low ticket). Matched as whole words, case-insensitive; such a business is rejected.
    exclude_names: list[str] = Field(default_factory=list)

    def excludes_name(self, name: str | None) -> str | None:
        text = " ".join(re.findall(r"[a-z0-9]+", str(name or "").lower()))
        return next(
            (w for w in self.exclude_names if re.search(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])", text)),
            None,
        )


class TicketClass(BaseModel):
    match: list[str] = Field(min_length=1)
    points: int = Field(ge=0, le=6)


class PremiumPrice(BaseModel):
    consultation: float | None = Field(None, gt=0)
    other: float = Field(gt=0)


class CanPay(BaseModel):
    premium_price: PremiumPrice


class Angle(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    signals: list[SignalType | Literal["fit_only"]] = Field(min_length=1)
    idea: str


class Segment(BaseModel):
    """One market: a domain in a country (Step 3.3)."""

    id: str
    domain: Domain
    country: str = Field(pattern=r"^[a-z]{2}$")
    display_name: str
    enabled: bool = True
    timezone: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    quota: Quota
    cities: list[City] = Field(min_length=1)
    overture: Overture
    places: Places
    registries: list[Registry] = Field(default_factory=list)
    osm: Osm = Field(default_factory=Osm)
    apna: Apna = Field(default_factory=Apna)
    adzuna_enabled: bool = False
    job_keywords: JobKeywords
    public_ask_queries: list[str] = Field(default_factory=list)
    news_queries: list[str] = Field(default_factory=list)
    size_rules: SizeRules
    signal_points: dict[SignalType, float] = Field(default_factory=dict)
    fit: Fit
    ticket_class: dict[str, TicketClass] = Field(min_length=1)
    can_pay: CanPay
    scoring: dict[str, Any] = Field(default_factory=dict)
    packaged_outcome: str
    angles: list[Angle] = Field(min_length=8)
    # "map": businesses come from Overture, Places, OSM and registries. "signals_only" (the need-first track,
    # 13 Nov 2026): a business exists only because it said it needs a build (a job post or a public ask).
    universe: Literal["map", "signals_only"] = "map"

    @model_validator(mode="after")
    def _consistency(self) -> Segment:
        if self.id != f"{self.domain}-{self.country}":
            raise ValueError(f"id must be {self.domain}-{self.country}")
        if self.packaged_outcome != PACKAGED_OUTCOME[self.domain]:
            raise ValueError(f"packaged_outcome must be '{PACKAGED_OUTCOME[self.domain]}' (A.2.2)")
        keys = [a.key for a in self.angles]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate angle keys")
        missing = REQUIRED_ANGLES - set(keys)
        if missing:
            raise ValueError(f"missing angles that Step 11 picks: {sorted(missing)}")
        if sum("fit_only" in a.signals for a in self.angles) != 1:
            raise ValueError("exactly one angle must list fit_only")
        if not any(GROWTH_SIGNALS & set(a.signals) for a in self.angles):
            raise ValueError("one angle must list a growth signal (new_place, new_branch or news)")
        if self.country != "in" and self.apna.pages_per_day:
            raise ValueError("apna is India only")
        if self.universe == "map" and not (self.overture.categories and self.places.queries):
            raise ValueError("a map universe needs overture.categories and places.queries")
        for sub in self.ticket_class:
            if not re.fullmatch(r"[a-z0-9_]+", sub):
                raise ValueError(f"ticket_class key {sub} must be lowercase snake_case")
        return self

    # ---- helpers for Steps 5, 6, 8 and 11 -------------------------------------
    def subcategory_for(self, category: str | None, name: str = "") -> str | None:
        """Our subcategory from a source category code or the business name.
        The first ticket class in file order with a matching entry wins."""
        cat, text = (category or "").lower(), name.lower()
        for sub, tc in self.ticket_class.items():
            for m in tc.match:
                if m == cat or re.search(rf"\b{re.escape(m)}\b", text):
                    return sub
        return None

    def is_type_match(self, category: str | None, subcategory: str | None) -> bool:
        """Rule R2 (Step 8) and the first half of the Step 11 type point."""
        return (category or "") in self.fit.categories or (subcategory or "") in self.ticket_class

    def ticket_points(self, subcategory: str | None) -> int:
        """Can-pay points for the ticket size of a subcategory (0 when unknown)."""
        tc = self.ticket_class.get(subcategory or "")
        return tc.points if tc else 0

    def premium_threshold(self, item: str) -> float:
        """A verified price_point at or above this, in the segment currency, is premium evidence."""
        pp = self.can_pay.premium_price
        if pp.consultation is not None and "consult" in item.lower():
            return pp.consultation
        return pp.other

    def angle(self, key: str) -> Angle:
        """The angle with this key; KeyError when the segment has none."""
        return {a.key: a for a in self.angles}[key]

    def fit_only_angle(self) -> str:
        """The segment's default angle for leads without a signal."""
        return next(a.key for a in self.angles if "fit_only" in a.signals)

    def growth_angle(self) -> str:
        """The first angle that answers a growth signal (new_place, new_branch, news)."""
        return next(a.key for a in self.angles if GROWTH_SIGNALS & set(a.signals))


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SegmentConfigError(f"{path.name} is not valid YAML: {exc}") from exc


def load_yaml_config(name: str, directory: Path = CONFIG_DIR) -> dict[str, Any]:
    """engine/config/<name>.yaml (scoring, exclusions) as a dict."""
    path = directory / f"{name}.yaml"
    if not path.is_file():
        raise SegmentConfigError(f"Config file not found: {path}")
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise SegmentConfigError(f"{path.name} must contain a mapping at the top level")
    return data


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` wins; nested mappings merge, lists and scalars are replaced."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def scoring_config(seg: Segment) -> dict[str, Any]:
    """Default scoring numbers with this segment's overrides applied (Step 11 reads this)."""
    return _deep_merge(load_yaml_config("scoring"), seg.scoring)


def file_hash(path: Path) -> str:
    """Short content hash of a segment file, stored as segments.config_version."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_segments(directory: Path = SEGMENTS_DIR, research_per_day: int = 300) -> dict[str, Segment]:
    """Read and validate every `*.yaml` in `directory`. Stops with SegmentConfigError on any problem."""
    segments: dict[str, Segment] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            seg = Segment.model_validate(_read_yaml(path))
        except ValidationError as exc:  # every problem in one message
            raise SegmentConfigError(f"Invalid segment file {path.name}: {exc}") from exc
        if path.stem != seg.id:
            raise SegmentConfigError(f"File {path.name} must be named {seg.id}.yaml")
        if seg.id in segments:
            raise SegmentConfigError(f"Duplicate segment id {seg.id}")
        segments[seg.id] = seg
    total = sum(s.quota.daily_research for s in segments.values() if s.enabled)
    if total > research_per_day:
        raise SegmentConfigError(f"Segment quotas add up to {total}, more than research_per_day={research_per_day}")
    return segments


def sync_segments_to_db(conn: Connection[Any], segments: dict[str, Segment], directory: Path = SEGMENTS_DIR) -> int:
    """Upsert every segment inside the caller's transaction; returns how many were written.

    - `config` and `config_version` are written every run.
    - `enabled` = the file's `enabled` and `settings.segments_enabled[id]`, every run.
    - `daily_quota` comes from the YAML on the first insert only; after that the app owns it (A.13.5 rule 11).
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select value from public.settings where key = 'segments_enabled'")
        row = cur.fetchone()
        switches: dict[str, Any] = (row or {}).get("value") or {}
        for seg in segments.values():
            enabled = seg.enabled and bool(switches.get(seg.id, True))
            cur.execute(
                """
                insert into public.segments (id, domain, country, display_name, enabled, daily_quota,
                                             config, config_version)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do update set
                  domain = excluded.domain, country = excluded.country,
                  display_name = excluded.display_name, enabled = excluded.enabled,
                  config = excluded.config, config_version = excluded.config_version
                """,
                (
                    seg.id,
                    seg.domain,
                    seg.country,
                    seg.display_name,
                    enabled,
                    seg.quota.daily_research,
                    Jsonb(seg.model_dump(mode="json")),
                    file_hash(directory / f"{seg.id}.yaml"),
                ),
            )
    return len(segments)
