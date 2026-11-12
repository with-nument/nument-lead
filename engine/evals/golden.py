"""The golden set on disk (Step 17.3): labels, hand-checked facts, the fixed CI subset and frozen pages.

engine/evals/golden/
  labels.jsonl        one label per business: business_id, segment, label (good or bad), reasons, labeled_at
  facts_truth.yaml    hand-checked facts for 30 businesses (5 per segment), checked against their own pages
  subset20.txt        the fixed, stratified 20 used by CI (seed 42), one business id per line
  pages/<id>.json     the business's pages frozen at export time, so evals never re-crawl

The database (`golden_labels`, labelled in the app) is the source; `nlead eval --export-golden` writes these
files and the repository copy is what CI uses.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nument_engine import db
from nument_engine.settings import ENGINE_DIR

GOLDEN_DIR: Final[Path] = ENGINE_DIR / "evals" / "golden"
LABELS_FILE, TRUTH_FILE, SUBSET_FILE, PAGES_DIR = "labels.jsonl", "facts_truth.yaml", "subset20.txt", "pages"
WAVE1_QUOTA: Final[dict[str, int]] = {
    "clinics-in": 4,
    "realestate-in": 3,
    "education-in": 3,
    "clinics-ae": 3,
    "realestate-ae": 3,
    "education-ae": 3,
}
SUBSET_SIZE, SUBSET_SEED, SUBSET_MIN_TRUTH = 20, 42, 6
REASONS: Final[frozenset[str]] = frozenset(
    {"wrong_segment", "too_small", "too_big_or_corporate", "agency_or_vendor", "no_real_need", "cannot_reach",
     "already_has_solution", "bad_message", "great_lead", "other"}
)  # fmt: skip
SEGMENT_ID = re.compile(r"^[a-z0-9]+-[a-z]{2}$")


class GoldenError(ValueError):
    """A golden file is missing or invalid; the message names the file and the line."""


class Label(BaseModel):
    """One labelled business."""

    model_config = ConfigDict(extra="forbid")

    business_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    segment: str
    label: Literal["good", "bad"]
    reasons: list[str] = Field(default_factory=list)
    labeled_at: date
    name: str | None = None  # for people reading the file; not used by the eval

    @field_validator("segment")
    @classmethod
    def _segment(cls, v: str) -> str:
        if not SEGMENT_ID.match(v):
            raise ValueError(f"{v!r} is not a segment id like clinics-in")
        return v

    @field_validator("reasons")
    @classmethod
    def _reasons(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - REASONS)
        if unknown:
            raise ValueError(f"unknown reasons {unknown}; use the fixed list in Step 16.5")
        return v


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    role: str | None = None


class TruthPhone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    e164: str = Field(pattern=r"^\+[1-9][0-9]{6,14}$")
    type: Literal["mobile", "landline", "tollfree", "unknown"] = "unknown"


class TruthFacts(BaseModel):
    """Hand-checked values. A missing value means "not checked", never "false" (17.3.3)."""

    model_config = ConfigDict(extra="forbid")

    decision_maker: Person | None = None
    phones: list[TruthPhone] = Field(default_factory=list)
    branches_count: int | None = Field(default=None, ge=0)
    staff_count_min: int | None = Field(default=None, ge=0)
    booking_method: str | None = None  # words from: online_widget, phone, whatsapp, form, none
    whatsapp_present: bool | None = None
    chat_widget: bool | None = None
    has_in_house_tech: Literal["yes", "no", "unknown"] | None = None
    is_agency_or_vendor: bool | None = None
    services_include: list[str] = Field(default_factory=list)


class Truth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    segment: str
    checked_by: str
    checked_at: date
    facts: TruthFacts


def load_labels(directory: Path = GOLDEN_DIR) -> list[Label]:
    """labels.jsonl, validated; an empty list when the file does not exist yet."""
    path = directory / LABELS_FILE
    if not path.is_file():
        return []
    labels: list[Label] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            label = Label.model_validate_json(line)
        except ValidationError as exc:
            raise GoldenError(f"{path.name} line {n}: {exc.errors()[0]['msg']} ({exc.errors()[0]['loc']})") from exc
        if label.business_id in seen:
            raise GoldenError(f"{path.name} line {n}: business {label.business_id} is labelled twice")
        seen.add(label.business_id)
        labels.append(label)
    return labels


def load_truth(directory: Path = GOLDEN_DIR) -> dict[str, Truth]:
    """facts_truth.yaml by business id; empty when the file does not exist yet."""
    path = directory / TRUTH_FILE
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise GoldenError(f"{path.name} must be a list of businesses")
    out: dict[str, Truth] = {}
    for i, item in enumerate(data, start=1):
        try:
            truth = Truth.model_validate(item)
        except ValidationError as exc:
            raise GoldenError(f"{path.name} entry {i}: {exc.errors()[0]['msg']} ({exc.errors()[0]['loc']})") from exc
        out[truth.business_id] = truth
    return out


def load_pages(business_id: str, directory: Path = GOLDEN_DIR) -> list[dict[str, Any]]:
    """Frozen pages of one business ([] when none were exported)."""
    path = directory / PAGES_DIR / f"{business_id}.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [p for p in data.get("pages", []) if p.get("text")]


def select_subset(
    labels: Sequence[Label],
    truth_ids: Iterable[str] = (),
    *,
    size: int = SUBSET_SIZE,
    seed: int = SUBSET_SEED,
    quota: Mapping[str, int] = WAVE1_QUOTA,
) -> list[str]:
    """A fixed, stratified subset (17.4.3): per-segment quotas, half good and half bad, and at least
    SUBSET_MIN_TRUTH hand-checked businesses. Deterministic for the same labels and seed."""
    rng = random.Random(seed)
    truth = set(truth_ids)
    pools: dict[tuple[str, str], list[str]] = {}
    for lab in sorted(labels, key=lambda x: x.business_id):
        pools.setdefault((lab.segment, lab.label), []).append(lab.business_id)
    for key in sorted(pools):
        rng.shuffle(pools[key])
        pools[key].sort(key=lambda bid: bid not in truth)  # stable: hand-checked first, shuffled within

    segments = sorted(
        {lab.segment for lab in labels}, key=lambda s: (s not in quota, list(quota).index(s) if s in quota else 0, s)
    )
    chosen: list[str] = []
    counts = {"good": 0, "bad": 0}

    def pick(segment: str) -> bool:
        order = ["good", "bad"] if counts["good"] <= counts["bad"] else ["bad", "good"]
        for lab in order:
            pool = pools.get((segment, lab), [])
            if pool:
                chosen.append(pool.pop(0))
                counts[lab] += 1
                return True
        return False

    for segment in segments:
        for _ in range(quota.get(segment, 0)):
            if len(chosen) >= size or not pick(segment):
                break
    while len(chosen) < size and any(pools.values()):
        for segment in segments:
            if len(chosen) >= size:
                break
            pick(segment)

    have = sum(bid in truth for bid in chosen)
    if have < SUBSET_MIN_TRUTH:  # swap in hand-checked businesses of the same segment and label
        by_id = {lab.business_id: lab for lab in labels}
        for i, bid in enumerate(list(chosen)):
            if have >= SUBSET_MIN_TRUTH:
                break
            if bid in truth:
                continue
            lab = by_id[bid]
            spare = [x for x in pools.get((lab.segment, lab.label), []) if x in truth]
            if spare:
                pools[(lab.segment, lab.label)].remove(spare[0])
                chosen[i] = spare[0]
                have += 1
    return chosen


def read_subset(directory: Path = GOLDEN_DIR) -> list[str]:
    path = directory / SUBSET_FILE
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def write_subset(ids: Sequence[str], directory: Path = GOLDEN_DIR) -> Path:
    path = directory / SUBSET_FILE
    header = f"# Fixed CI subset (Step 17.4.3): {len(ids)} businesses, seed {SUBSET_SEED}. Regenerate with nlead eval --export-golden.\n"
    path.write_text(header + "".join(f"{i}\n" for i in ids), encoding="utf-8")
    return path


def _reasons(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        tokens = [str(t) for t in parsed] if isinstance(parsed, list) else []
    except ValueError:
        tokens = []
    tokens = tokens or re.findall(r"[a-z_]+", raw.lower())
    return sorted({t for t in tokens if t in REASONS})


def export_golden(directory: Path = GOLDEN_DIR, *, conn: Any = None) -> dict[str, int]:
    """Write labels.jsonl, frozen pages and (re)select subset20.txt from the database."""
    rows = db.fetch_all(
        """
        select distinct on (g.business_id) g.business_id::text as business_id, b.segment_id, b.name, g.label,
               g.reasons, g.at
        from public.golden_labels g
        join public.businesses b on b.id = g.business_id
        order by g.business_id, g.at desc
        """,
        conn=conn,
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / PAGES_DIR).mkdir(exist_ok=True)
    labels = [
        Label(business_id=r["business_id"], segment=r["segment_id"], label=r["label"], reasons=_reasons(r["reasons"]),
              labeled_at=r["at"].date(), name=r["name"])
        for r in sorted(rows, key=lambda r: (r["segment_id"], r["business_id"]))
    ]  # fmt: skip
    (directory / LABELS_FILE).write_text(
        "".join(lab.model_dump_json(exclude_none=True) + "\n" for lab in labels), encoding="utf-8"
    )
    frozen = 0
    for lab in labels:
        pages = db.fetch_all(
            "select url, title, fetched_at, text_hash, text from public.pages "
            "where business_id = %s and text is not null order by fetched_at",
            [lab.business_id],
            conn=conn,
        )
        if not pages:
            continue
        doc = {
            "business_id": lab.business_id,
            "segment": lab.segment,
            "name": lab.name,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "pages": [{**p, "fetched_at": p["fetched_at"].isoformat()} for p in pages],
        }
        (directory / PAGES_DIR / f"{lab.business_id}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        frozen += 1
    subset = select_subset(labels, load_truth(directory))
    write_subset(subset, directory)
    return {"labels": len(labels), "frozen_pages": frozen, "subset": len(subset)}
