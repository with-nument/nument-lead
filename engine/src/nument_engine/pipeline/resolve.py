"""Entity resolution: one real company is one `businesses` row, whatever the number of sources (Step 6.6).

`Resolver` is a unit of work for one segment. It loads the segment's businesses into memory once, matches each
candidate with the rules of Step 6.6.2 (first match wins), merges fields by source precedence (6.6.4), detects
branches (6.6.5) and statuses (6.6.6), and writes everything in a few batched statements on `flush()`. That keeps
a monthly Overture pull of thousands of places fast over a far-away database, and makes `--dry-run` exact: the
same decisions, nothing written.

Matching rules, in order:
1. the same (source, source_key) was seen before;
2. the same Google `place_id` or Overture id;
3. the same web domain (a point more than 300 m from every known point is another branch of that business);
4. the same published phone (shared numbers, used by 5 or more businesses, and toll-free numbers never match);
5. a similar name (92+) within 300 m in the same city, or 96+ and the same locality when a point is missing;
6. otherwise a new business with status `candidate`.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb
from rapidfuzz import fuzz, process

from .. import db
from ..models import SOURCE_NAMES
from ..normalize import compact_name, homepage, match_key, meters, norm_name, phone, web_domain
from ..segments import Segment
from ..sources.base import SourceRecord
from ..sources.places import listing_url

BRANCH_METERS = 300.0
NAME_RATIO = 92
NAME_RATIO_NO_POINT = 96
MIN_COMPACT_NAME = 8  # letters in a compact name before it may identify one business in a city
SHARED_PHONE_MIN = 5  # a number on this many businesses is a call centre, aggregator or franchise line
MAX_PHONE_HINTS = 5
MAX_POINTS = 50
GRID_DEG = 0.005  # about 550 m: neighbours of a point are found in the 3 x 3 cells around it
FLUSH_EVERY = 500
REGISTRY_SOURCES = frozenset({"art_registry"})
GEO_SOURCES = frozenset({"places", "overture", "osm"})
OPEN_SIGNAL_SOURCES = frozenset({"apna", "adzuna", "gdelt", "grounded_search", "careers_watch", "inbox"})

# Source precedence per field group (lower wins). Step 6.6.4.
RANK: dict[str, dict[str, int]] = {
    "name": {"places": 1, "website": 2, "overture": 3, "art_registry": 4, "osm": 5},
    "website": {"website": 1, "places": 2, "overture": 3, "art_registry": 4, "osm": 5},
    "geo": {"places": 1, "overture": 2, "osm": 3},
    "address": {"places": 1, "overture": 2, "art_registry": 3, "osm": 4},
    "category": {"overture": 1, "places": 2, "art_registry": 3, "osm": 4},
}
DEFAULT_RANK = 9

BUSINESS_COLUMNS = (
    "id",
    "segment_id",
    "name",
    "norm_name",
    "website",
    "web_domain",
    "country",
    "city",
    "locality",
    "address",
    "lat",
    "lng",
    "category",
    "subcategory",
    "place_id",
    "overture_id",
    "branches_count",
    "review_count",
    "rating",
    "places_fetched_at",
    "status",
    "extra",
    "first_seen_at",
    "last_seen_at",
)
UPDATE_COLUMNS = tuple(c for c in BUSINESS_COLUMNS if c not in ("id", "segment_id", "country", "first_seen_at"))


def rank(group: str, source: str | None) -> int:
    return RANK[group].get(source or "", DEFAULT_RANK)


@dataclass
class Candidate:
    """A normalised record from any source, ready to be matched (Step 6.6.1)."""

    source: str
    source_key: str
    segment_id: str
    name: str
    category: str | None = None
    subcategory: str | None = None
    website: str | None = None
    phone_hints: list[tuple[str, str]] = field(default_factory=list)  # (e164, kind), used only for matching
    contact_phones: list[tuple[str, str]] = field(default_factory=list)  # stored as contacts
    contact_emails: list[str] = field(default_factory=list)
    contact_source: str | None = None  # google_listing | registry | website | other
    contact_url: str | None = None
    address: str | None = None
    city: str | None = None
    locality: str | None = None
    lat: float | None = None
    lng: float | None = None
    place_id: str | None = None
    overture_id: str | None = None
    rating: float | None = None
    review_count: int | None = None
    closed: bool = False  # Places CLOSED_PERMANENTLY
    registry_ref: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def has_point(self) -> bool:
        return self.lat is not None and self.lng is not None

    @property
    def domain(self) -> str | None:
        return web_domain(self.website) if self.website else None


def candidate_from_record(rec: SourceRecord, seg: Segment) -> Candidate | None:
    """A source record as a candidate. Phones are hints unless the record says the source published them."""
    if not rec.name:
        return None
    region = seg.country.upper()
    phones = [(p[0], str(p[1])) for p in (phone(raw, region) for raw in rec.phones_raw) if p]
    listing = rec.phones_are_listing
    return Candidate(
        source=rec.source,
        source_key=rec.source_key,
        segment_id=seg.id,
        name=rec.name.strip(),
        category=rec.category,
        subcategory=rec.subcategory or seg.subcategory_for(rec.category, rec.name),
        website=homepage(rec.website) if rec.website else None,
        phone_hints=phones,
        contact_phones=phones if listing else [],
        contact_emails=list(rec.emails) if rec.emails_are_registry else [],
        contact_source="google_listing" if listing else "registry" if rec.emails_are_registry else None,
        contact_url=listing_url(rec.place_id) if listing and rec.place_id else rec.payload.get("certificate_url"),
        address=rec.address,
        city=rec.city,
        locality=rec.locality,
        lat=rec.lat,
        lng=rec.lng,
        place_id=rec.place_id,
        overture_id=rec.overture_id,
        rating=rec.rating,
        review_count=rec.review_count,
        closed=(rec.business_status or "") == "CLOSED_PERMANENTLY",
        registry_ref=rec.source_key if rec.source in REGISTRY_SOURCES else None,
        payload=dict(rec.payload),
    )


def candidate_from_hint(source: str, evidence_key: str, hint: dict[str, Any], seg: Segment) -> Candidate | None:
    """A candidate from a signal's business hint (Step 7.4.6). None when it cannot identify a business."""
    name = str(hint.get("name") or "").strip()
    if not name:
        return None
    region = seg.country.upper()
    parsed = phone(str(hint.get("phone")), region) if hint.get("phone") else None
    phones = [(parsed[0], str(parsed[1]))] if parsed else []
    return Candidate(
        source=source,
        source_key=evidence_key,
        segment_id=seg.id,
        name=name,
        website=homepage(hint["website"]) if hint.get("website") else None,
        phone_hints=phones,
        address=hint.get("address"),
        city=hint.get("city"),
        locality=hint.get("locality"),
        subcategory=seg.subcategory_for(None, name),
        payload={k: v for k, v in hint.items() if k in ("name", "city", "website") and v},
    )


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return math.floor(lat / GRID_DEG), math.floor(lng / GRID_DEG)


def name_score(a: str, b: str) -> float:
    """Similarity of two match keys (0 to 100). One-word keys must be near identical: `token_set_ratio` gives
    100 for "dental" against "city dental", which would merge unrelated clinics."""
    if not a or not b:
        return 0.0
    score = float(fuzz.token_set_ratio(a, b))
    if min(len(a.split()), len(b.split())) <= 1:
        score = min(score, float(fuzz.ratio(a, b)))
    return score


class Resolver:
    """Match and merge candidates for one segment. Call `flush()` (or use `with`) to write the result."""

    def __init__(self, seg: Segment, *, dry_run: bool = False, now: datetime | None = None) -> None:
        self.seg = seg
        self.dry_run = dry_run
        self.now = now or datetime.now(UTC)
        self.stats: Counter[str] = Counter()
        self._loaded = False
        self.rows: dict[str, dict[str, Any]] = {}
        self.by_place: dict[str, str] = {}
        self.by_overture: dict[str, str] = {}
        self.by_domain: dict[str, str] = {}
        self.by_phone: dict[str, set[str]] = {}
        self.city_keys: dict[str | None, dict[str, str]] = {}
        self.city_compact: dict[str | None, dict[str, set[str]]] = {}
        self.grid: dict[tuple[int, int], set[str]] = {}
        self.records: dict[tuple[str, str], str | None] = {}
        self._sources_loaded: set[str] = set()
        self.foreign_places: set[str] = set()
        self.foreign_overture: set[str] = set()
        self.shared_phones: set[str] = set()
        self.phone_owners: Counter[str] = Counter()
        self.new_ids: set[str] = set()
        self.dirty: set[str] = set()
        self.pending_records: dict[tuple[str, str], dict[str, Any]] = {}
        self.pending_contacts: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.existing_contacts: set[tuple[str, str, str]] = set()
        self._since_flush = 0

    # ---- loading ------------------------------------------------------------------------------------------
    def _index(self, row: dict[str, Any]) -> None:
        bid = row["id"]
        self.rows[bid] = row
        if row.get("place_id"):
            self.by_place[row["place_id"]] = bid
        if row.get("overture_id"):
            self.by_overture[row["overture_id"]] = bid
        if row.get("web_domain"):
            self.by_domain[row["web_domain"]] = bid
        key = match_key(row["name"])
        if key:
            self.city_keys.setdefault(row.get("city"), {})[bid] = key
        self._index_compact(row.get("city"), row["name"], bid)
        for lat, lng in self._points(row):
            self.grid.setdefault(_cell(lat, lng), set()).add(bid)
        for e164 in (row.get("extra") or {}).get("phone_hints", []):
            self._add_phone(e164, bid)

    def _add_phone(self, e164: str, bid: str) -> None:
        owners = self.by_phone.setdefault(e164, set())
        if bid not in owners:
            owners.add(bid)
            self.phone_owners[e164] += 1
            if self.phone_owners[e164] >= SHARED_PHONE_MIN:
                self.shared_phones.add(e164)

    @staticmethod
    def _points(row: dict[str, Any]) -> list[tuple[float, float]]:
        pts = [(float(p[0]), float(p[1])) for p in (row.get("extra") or {}).get("points", [])]
        if not pts and row.get("lat") is not None and row.get("lng") is not None:
            pts = [(float(row["lat"]), float(row["lng"]))]
        return pts

    def load(self) -> None:
        if self._loaded:
            return
        cols = ", ".join(BUSINESS_COLUMNS)
        for row in db.fetch_all(f"select {cols} from public.businesses where segment_id = %s", [self.seg.id]):
            row["id"] = str(row["id"])
            row["extra"] = row.get("extra") or {}
            self._index(row)
        for row in db.fetch_all(
            """select c.business_id::text as bid, c.phone_e164, c.email from public.contacts c
               join public.businesses b on b.id = c.business_id where b.segment_id = %s""",
            [self.seg.id],
        ):
            if row["phone_e164"]:
                self.existing_contacts.add((row["bid"], "phone", row["phone_e164"]))
                self._add_phone(row["phone_e164"], row["bid"])
            if row["email"]:
                self.existing_contacts.add((row["bid"], "email", row["email"].lower()))
        for row in db.fetch_all(
            "select phone_e164 from public.contacts where phone_e164 is not null "
            "group by phone_e164 having count(distinct business_id) >= %s",
            [SHARED_PHONE_MIN],
        ):
            self.shared_phones.add(row["phone_e164"])
        for row in db.fetch_all(
            "select place_id, overture_id from public.businesses where segment_id <> %s "
            "and (place_id is not null or overture_id is not null)",
            [self.seg.id],
        ):
            if row["place_id"]:
                self.foreign_places.add(row["place_id"])
            if row["overture_id"]:
                self.foreign_overture.add(row["overture_id"])
        self._loaded = True

    def _load_source(self, source: str) -> None:
        if source in self._sources_loaded:
            return
        for row in db.fetch_all(
            "select source_key, business_id::text as bid from public.source_records where source = %s", [source]
        ):
            self.records[(source, row["source_key"])] = row["bid"]
        self._sources_loaded.add(source)

    # ---- matching -----------------------------------------------------------------------------------------
    def _by_phone(self, c: Candidate) -> str | None:
        for e164, kind in [*c.contact_phones, *c.phone_hints]:
            if kind == "tollfree" or e164 in self.shared_phones:
                continue
            owners = self.by_phone.get(e164) or set()
            if len(owners) == 1:
                return next(iter(owners))
        return None

    def _by_name(self, c: Candidate) -> str | None:
        key = match_key(c.name)
        if not key:
            return None
        if c.has_point:
            assert c.lat is not None and c.lng is not None
            r, k = _cell(c.lat, c.lng)
            near = {b for dr in (-1, 0, 1) for dk in (-1, 0, 1) for b in self.grid.get((r + dr, k + dk), set())}
            best: tuple[float, str] | None = None
            for bid in near:
                row = self.rows[bid]
                if row.get("city") != c.city:
                    continue
                if not any(meters(c.lat, c.lng, la, ln) <= BRANCH_METERS for la, ln in self._points(row)):
                    continue
                score = name_score(key, self.city_keys.get(row.get("city"), {}).get(bid, ""))
                if score >= NAME_RATIO and (best is None or score > best[0]):
                    best = (score, bid)
            if best:
                return best[1]
        # No point on one side: a stronger name match and the same locality.
        choices = self.city_keys.get(c.city, {})
        if not choices or not c.locality:
            return None
        for _, _, bid in process.extract(
            key, choices, scorer=fuzz.token_set_ratio, score_cutoff=NAME_RATIO_NO_POINT, limit=10
        ):
            row = self.rows[bid]
            if c.has_point and row.get("lat") is not None:
                continue  # both have points: rule 5 already decided by distance
            same_locality = (row.get("locality") or "").strip().lower() == c.locality.strip().lower()
            if same_locality and name_score(key, choices[bid]) >= NAME_RATIO_NO_POINT:
                return str(bid)
        return None

    def _index_compact(self, city: str | None, name: str | None, bid: str) -> None:
        compact = compact_name(name)
        if len(compact) >= MIN_COMPACT_NAME:
            self.city_compact.setdefault(city, {}).setdefault(compact, set()).add(bid)

    def _by_compact_name(self, c: Candidate) -> str | None:
        """A candidate without a map point (a job post, a public ask): the same name once spaces, punctuation,
        "&"/"and" and generic words are ignored, held by exactly one business in the same city. Live check
        12 Nov: "Dr. Ali's Dentacare" (Apna) is "Dralisdentacare" (Overture, with its website)."""
        if c.has_point or not c.city:
            return None
        compact = compact_name(c.name)
        if len(compact) < MIN_COMPACT_NAME:
            return None  # "Dental Clinic" is "dental": too common to identify one business
        owners = self.city_compact.get(c.city, {}).get(compact, set())
        return next(iter(owners)) if len(owners) == 1 else None

    def match(self, c: Candidate) -> tuple[str | None, str]:
        """(business_id, rule) for rules 2 to 5, or (None, "")."""
        if c.place_id and c.place_id in self.by_place:
            return self.by_place[c.place_id], "place_id"
        if c.overture_id and c.overture_id in self.by_overture:
            return self.by_overture[c.overture_id], "overture_id"
        dom = c.domain
        if dom and dom in self.by_domain:
            return self.by_domain[dom], "domain"
        bid = self._by_phone(c)
        if bid:
            return bid, "phone"
        bid = self._by_name(c)
        if bid:
            return bid, "name"
        bid = self._by_compact_name(c)
        if bid:
            return bid, "compact_name"
        return None, ""

    def _far_branch(self, bid: str, c: Candidate) -> bool:
        if not c.has_point or c.source not in GEO_SOURCES:
            return False
        assert c.lat is not None and c.lng is not None
        pts = self._points(self.rows[bid])
        return bool(pts) and all(meters(c.lat, c.lng, la, ln) > BRANCH_METERS for la, ln in pts)

    # ---- merging ------------------------------------------------------------------------------------------
    def _set(self, row: dict[str, Any], column: str, value: Any) -> None:
        if row.get(column) != value:
            row[column] = value
            self.dirty.add(row["id"])

    def _better(self, row: dict[str, Any], group: str, source: str) -> bool:
        current = (row.get("extra") or {}).get("src", {}).get(group)
        return rank(group, source) <= rank(group, current)

    def _claim(self, row: dict[str, Any], group: str, source: str) -> None:
        src = row.setdefault("extra", {}).setdefault("src", {})
        if src.get(group) != source:
            src[group] = source
            self.dirty.add(row["id"])

    def _note_city(self, bid: str, city: str, action: str) -> None:
        """Count the business's places per city (`extra.city_counts`). A chain merged by its website spans
        cities: its `city` follows the city with the most places, so a Mumbai chain first seen through one
        Delhi branch is not filed as a Delhi clinic. Messages name a city only when there is one (Step 12)."""
        row = self.rows[bid]
        extra = row.setdefault("extra", {})
        counts: dict[str, int] = dict(extra.get("city_counts") or {})
        if action in ("created", "branch") or city not in counts:
            counts[city] = counts.get(city, 0) + 1
        if counts != extra.get("city_counts"):
            extra["city_counts"] = counts
            top = max(counts.items(), key=lambda kv: (kv[1], kv[0] == row.get("city")))[0]
            if top != row.get("city"):
                self._set(row, "city", top)
            self.dirty.add(bid)

    def _add_point(self, row: dict[str, Any], lat: float, lng: float) -> bool:
        """Add a branch point when it is more than 300 m from every known one; True if it was added."""
        pts = self._points(row)
        if any(meters(lat, lng, la, ln) <= BRANCH_METERS for la, ln in pts):
            return False
        pts.append((lat, lng))
        row.setdefault("extra", {})["points"] = [[round(la, 6), round(ln, 6)] for la, ln in pts[:MAX_POINTS]]
        self.grid.setdefault(_cell(lat, lng), set()).add(row["id"])
        self._set(row, "branches_count", len(pts))
        self.dirty.add(row["id"])
        return True

    def _merge(self, bid: str, c: Candidate) -> None:
        row = self.rows[bid]
        src = c.source
        if c.name and self._better(row, "name", src):
            self._set(row, "name", c.name)
            self._set(row, "norm_name", norm_name(c.name))
            self._claim(row, "name", src)
            key = match_key(c.name)
            if key:
                self.city_keys.setdefault(row.get("city"), {})[bid] = key
            self._index_compact(row.get("city"), c.name, bid)
        dom = c.domain
        if c.website and dom and (row.get("web_domain") in (None, dom)) and self._better(row, "website", src):
            if row.get("web_domain") is None and dom in self.by_domain and self.by_domain[dom] != bid:
                pass  # another business owns this domain: leave it to merge_businesses()
            else:
                self._set(row, "website", c.website)
                self._set(row, "web_domain", dom)
                self.by_domain[dom] = bid
                self._claim(row, "website", src)
        if c.has_point and src in GEO_SOURCES:
            assert c.lat is not None and c.lng is not None
            self._add_point(row, c.lat, c.lng)
            if self._better(row, "geo", src) or row.get("lat") is None:
                self._set(row, "lat", c.lat)
                self._set(row, "lng", c.lng)
                self._claim(row, "geo", src)
        if (c.address or c.locality) and self._better(row, "address", src):
            if c.address:
                self._set(row, "address", c.address)
            if c.locality:
                self._set(row, "locality", c.locality)
            self._claim(row, "address", src)
        if row.get("city") is None and c.city:
            self._set(row, "city", c.city)
        if c.category and self._better(row, "category", src):
            self._set(row, "category", c.category)
            if c.subcategory:
                self._set(row, "subcategory", c.subcategory)
            self._claim(row, "category", src)
        elif row.get("subcategory") is None and c.subcategory:
            self._set(row, "subcategory", c.subcategory)
        if c.place_id and row.get("place_id") is None and c.place_id not in self.foreign_places:
            self._set(row, "place_id", c.place_id)
            self.by_place[c.place_id] = bid
        if c.overture_id and row.get("overture_id") is None and c.overture_id not in self.foreign_overture:
            self._set(row, "overture_id", c.overture_id)
            self.by_overture[c.overture_id] = bid
        if src == "places":
            self._set(row, "rating", c.rating)
            self._set(row, "review_count", c.review_count)
            self._set(row, "places_fetched_at", self.now)
        extra = row.setdefault("extra", {})
        if c.registry_ref:
            regs = extra.setdefault("registries", {})
            if regs.get(src) != c.registry_ref:
                regs[src] = c.registry_ref
                self.dirty.add(bid)
        hints = list(extra.get("phone_hints", []))
        for e164, _ in c.phone_hints:
            if e164 not in hints and len(hints) < MAX_PHONE_HINTS:
                hints.append(e164)
                self._add_phone(e164, bid)
        if hints != extra.get("phone_hints", []):
            extra["phone_hints"] = hints
            self.dirty.add(bid)
        # Statuses (Step 6.6.6). A business closed for good is dormant; a dormant one seen open comes back.
        if c.closed and row.get("status") != "dormant":
            self._set(row, "status", "dormant")
        elif row.get("status") == "dormant" and not c.closed and src in GEO_SOURCES | REGISTRY_SOURCES:
            self._set(row, "status", "candidate")
        self._set(row, "last_seen_at", self.now)

    def _create(self, c: Candidate) -> str:
        bid = str(uuid.uuid4())
        dom = c.domain
        if dom and dom in self.by_domain:
            dom = None  # cannot happen through match(); kept as a guard for the unique index
        row: dict[str, Any] = {
            "id": bid,
            "segment_id": self.seg.id,
            "name": c.name,
            "norm_name": norm_name(c.name),
            "website": c.website if dom else None,
            "web_domain": dom,
            "country": self.seg.country,
            "city": c.city,
            "locality": c.locality,
            "address": c.address,
            "lat": c.lat if c.source in GEO_SOURCES else None,
            "lng": c.lng if c.source in GEO_SOURCES else None,
            "category": c.category,
            "subcategory": c.subcategory,
            "place_id": c.place_id if c.place_id not in self.foreign_places else None,
            "overture_id": c.overture_id if c.overture_id not in self.foreign_overture else None,
            "branches_count": 1 if c.has_point and c.source in GEO_SOURCES else None,
            "review_count": c.review_count if c.source == "places" else None,
            "rating": c.rating if c.source == "places" else None,
            "places_fetched_at": self.now if c.source == "places" else None,
            "status": "dormant" if c.closed else "candidate",
            "extra": {"src": {}},
            "first_seen_at": self.now,
            "last_seen_at": self.now,
        }
        src = row["extra"]["src"]
        src["name"] = c.source
        if dom:
            src["website"] = c.source
        if row["lat"] is not None:
            src["geo"] = c.source
            row["extra"]["points"] = [[round(float(c.lat or 0), 6), round(float(c.lng or 0), 6)]]
        if c.address or c.locality:
            src["address"] = c.source
        if c.category:
            src["category"] = c.source
        if c.registry_ref:
            row["extra"]["registries"] = {c.source: c.registry_ref}
        hints = [e for e, _ in c.phone_hints][:MAX_PHONE_HINTS]
        if hints:
            row["extra"]["phone_hints"] = hints
        if c.source in OPEN_SIGNAL_SOURCES:
            row["extra"]["born_from"] = c.source  # a signal came first (Step 7.4.6): look the business up
        self._index(row)
        for e164 in hints:
            self._add_phone(e164, bid)
        self.new_ids.add(bid)
        return bid

    def _record(self, bid: str, c: Candidate) -> None:
        self.records[(c.source, c.source_key)] = bid
        if c.source not in SOURCE_NAMES:
            return  # e.g. the founder's inbox: matched through rules 2 to 6, no raw record to keep
        payload = dict(c.payload)
        if c.has_point and "lat" not in payload:
            payload.update(lat=c.lat, lng=c.lng)
        self.records[(c.source, c.source_key)] = bid
        self.pending_records[(c.source, c.source_key)] = {
            "source": c.source,
            "source_key": c.source_key,
            "business_id": bid,
            "payload": payload,
            "fetched_at": self.now,
        }

    def _contacts(self, bid: str, c: Candidate) -> None:
        if not c.contact_source:
            return
        for e164, kind in c.contact_phones:
            key = (bid, "phone", e164)
            self.pending_contacts[key] = {
                "business_id": bid,
                "phone_e164": e164,
                "phone_type": kind,
                "email": None,
                "source": c.contact_source,
                "source_url": c.contact_url,
                "verified": c.contact_source == "google_listing",
                "verified_at": self.now,
            }
            self._add_phone(e164, bid)
        for email in c.contact_emails:
            key = (bid, "email", email.lower())
            if key in self.existing_contacts:
                continue
            self.pending_contacts[key] = {
                "business_id": bid,
                "phone_e164": None,
                "phone_type": "unknown",
                "email": email.lower(),
                "source": c.contact_source,
                "source_url": c.contact_url,
                "verified": False,
                "verified_at": None,
            }

    # ---- public API ---------------------------------------------------------------------------------------
    def resolve(self, c: Candidate) -> tuple[str, str] | None:
        """(business_id, action) with action linked | matched | branch | created, or None when the candidate
        belongs to another segment (its place or Overture id is already used there)."""
        if c.segment_id != self.seg.id:
            raise ValueError(f"candidate for {c.segment_id} given to the {self.seg.id} resolver")
        self.load()
        self._load_source(c.source)
        known = self.records.get((c.source, c.source_key))
        if known and known in self.rows:
            bid, action = known, "linked"
        else:
            bid_or_none, rule = self.match(c)
            if bid_or_none is not None:
                bid = bid_or_none
                action = "branch" if rule == "domain" and self._far_branch(bid, c) else "matched"
                self.stats[f"rule.{rule}"] += 1
            elif (c.place_id and c.place_id in self.foreign_places) or (
                c.overture_id and c.overture_id in self.foreign_overture
            ):
                self.stats["other_segment"] += 1
                return None
            else:
                bid, action = self._create(c), "created"
        if action != "created":
            self._merge(bid, c)
        if c.city:
            self._note_city(bid, c.city, action)
        self._record(bid, c)
        self._contacts(bid, c)
        self.stats[action] += 1
        self._since_flush += 1
        if self._since_flush >= FLUSH_EVERY:
            self.flush()
        return bid, action

    def attach(self, bid: str, c: Candidate) -> str:
        """Merge a candidate into a known business (a targeted lookup found it). Returns the action."""
        self.load()
        if bid not in self.rows:
            raise KeyError(bid)
        self._merge(bid, c)
        self._record(bid, c)
        self._contacts(bid, c)
        self.stats["attached"] += 1
        return "attached"

    def set_extra(self, bid: str, key: str, value: Any) -> None:
        """Set one `businesses.extra` key through the resolver, so its next flush keeps it."""
        self.load()
        row = self.rows[bid]
        row.setdefault("extra", {})[key] = value
        self.dirty.add(bid)

    def touch(self, bids: Iterable[str]) -> None:
        """Mark businesses as seen now (a source mentioned them without new data)."""
        self.load()
        for bid in bids:
            if bid in self.rows:
                self._set(self.rows[bid], "last_seen_at", self.now)

    def flush(self, conn: Connection[Any] | None = None) -> None:
        """Write pending inserts and updates in one transaction. In a dry run nothing is written."""
        self._since_flush = 0
        if self.dry_run:
            self.new_ids.clear()
            self.dirty.clear()
            self.pending_records.clear()
            self.pending_contacts.clear()
            return
        if not (self.new_ids or self.dirty or self.pending_records or self.pending_contacts):
            return
        if conn is None:
            with db.tx() as txc:
                self._write(txc)
        else:
            self._write(conn)
        self.new_ids.clear()
        self.dirty.clear()
        self.pending_records.clear()
        for key in self.pending_contacts:
            self.existing_contacts.add(key)
        self.pending_contacts.clear()

    def _values(self, row: dict[str, Any], columns: Iterable[str]) -> list[Any]:
        return [Jsonb(row[c]) if c == "extra" else row.get(c) for c in columns]

    def _write(self, conn: Connection[Any]) -> None:
        with conn.cursor() as cur:
            if self.new_ids:
                cols = ", ".join(BUSINESS_COLUMNS)
                marks = ", ".join(["%s"] * len(BUSINESS_COLUMNS))
                cur.executemany(
                    f"insert into public.businesses ({cols}) values ({marks})",
                    [self._values(self.rows[b], BUSINESS_COLUMNS) for b in sorted(self.new_ids)],
                )
            updates = sorted(self.dirty - self.new_ids)
            if updates:
                # extra is merged, not replaced: keys other stages added meanwhile (crawl, review checks) survive.
                sets = ", ".join(
                    "extra = public.businesses.extra || %s" if c == "extra" else f"{c} = %s" for c in UPDATE_COLUMNS
                )
                cur.executemany(
                    f"update public.businesses set {sets} where id = %s",
                    [[*self._values(self.rows[b], UPDATE_COLUMNS), b] for b in updates],
                )
            if self.pending_records:
                cur.executemany(
                    """insert into public.source_records (source, source_key, business_id, payload, fetched_at)
                       values (%s, %s, %s, %s, %s)
                       on conflict (source, source_key) do update set business_id = excluded.business_id,
                         payload = excluded.payload, fetched_at = excluded.fetched_at""",
                    [
                        [r["source"], r["source_key"], r["business_id"], Jsonb(r["payload"]), r["fetched_at"]]
                        for r in self.pending_records.values()
                    ],
                )
            phones = [r for r in self.pending_contacts.values() if r["phone_e164"]]
            if phones:
                cur.executemany(
                    """insert into public.contacts (business_id, phone_e164, phone_type, source, source_url,
                                                    verified, verified_at)
                       values (%s, %s, %s, %s, %s, %s, %s)
                       on conflict (business_id, phone_e164) where phone_e164 is not null do update
                         set verified_at = excluded.verified_at, source_url = excluded.source_url
                         where contacts.source = excluded.source""",
                    [
                        [
                            r["business_id"],
                            r["phone_e164"],
                            r["phone_type"],
                            r["source"],
                            r["source_url"],
                            r["verified"],
                            r["verified_at"],
                        ]
                        for r in phones
                    ],
                )
            emails = [r for r in self.pending_contacts.values() if r["email"]]
            if emails:
                cur.executemany(
                    """insert into public.contacts (business_id, email, source, source_url, verified)
                       values (%s, %s, %s, %s, %s)
                       on conflict (business_id, lower(email)) where email is not null do nothing""",
                    [[r["business_id"], r["email"], r["source"], r["source_url"], r["verified"]] for r in emails],
                )

    def __enter__(self) -> Resolver:
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        if exc_type is None:
            self.flush()


# ---------------------------------------------------------------------------------------------------
# Merging two rows that turn out to be one company (Step 6.6.7)
# ---------------------------------------------------------------------------------------------------

CLOSED = ("won", "retainer", "lost", "not_now", "not_a_fit", "wrong_contact")


def merge_businesses(keep_id: str, drop_id: str, *, conn: Connection[Any] | None = None) -> dict[str, Any]:
    """Move everything from `drop_id` to `keep_id` and delete `drop_id`, in one transaction.

    When both have an open lead, the one with more activities stays; the other is closed as `not_a_fit` (the
    stage-change trigger logs it) with a `merge` activity naming the surviving business.
    """
    if keep_id == drop_id:
        raise ValueError("keep_id and drop_id are the same business")

    def run(c: Connection[Any]) -> dict[str, Any]:
        rows = {
            str(r["id"]): r
            for r in db.fetch_all(
                "select * from public.businesses where id = any(%s) for update", [[keep_id, drop_id]], conn=c
            )
        }
        if keep_id not in rows or drop_id not in rows:
            raise KeyError("both businesses must exist")
        keep, drop = rows[keep_id], rows[drop_id]
        out: dict[str, Any] = {}
        for table in ("source_records", "signals", "facts", "scores"):
            out[table] = db.execute(
                f"update public.{table} set business_id = %s where business_id = %s", [keep_id, drop_id], conn=c
            )
        out["pages"] = db.execute(
            "update public.pages set business_id = %s where business_id = %s", [keep_id, drop_id], conn=c
        )
        db.execute(
            """delete from public.contacts d using public.contacts k
               where d.business_id = %(drop)s and k.business_id = %(keep)s
                 and ((d.phone_e164 is not null and d.phone_e164 = k.phone_e164)
                      or (d.email is not null and lower(d.email) = lower(k.email)))""",
            {"drop": drop_id, "keep": keep_id},
            conn=c,
        )
        out["contacts"] = db.execute(
            "update public.contacts set business_id = %s where business_id = %s", [keep_id, drop_id], conn=c
        )
        db.execute(
            """delete from public.golden_labels d using public.golden_labels k
               where d.business_id = %(drop)s and k.business_id = %(keep)s and d.labeled_by = k.labeled_by""",
            {"drop": drop_id, "keep": keep_id},
            conn=c,
        )
        db.execute(
            "update public.golden_labels set business_id = %s where business_id = %s", [keep_id, drop_id], conn=c
        )
        open_leads = db.fetch_all(
            """select l.id, l.business_id, (select count(*) from public.activities a where a.lead_id = l.id) as n
               from public.leads l where l.business_id = any(%s) and l.stage <> all(%s)""",
            [[keep_id, drop_id], list(CLOSED)],
            conn=c,
        )
        survivor: str | None = None
        if len(open_leads) == 2:
            open_leads.sort(key=lambda r: (-int(r["n"]), str(r["business_id"]) != keep_id))
            survivor, loser = str(open_leads[0]["id"]), str(open_leads[1]["id"])
            db.execute("update public.leads set stage = 'not_a_fit' where id = %s", [loser], conn=c)
            db.execute(
                "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'merge', %s)",
                [loser, Jsonb({"merged_into": keep_id, "kept_lead": survivor})],
                conn=c,
            )
        elif len(open_leads) == 1:
            survivor = str(open_leads[0]["id"])
        out["leads"] = db.execute(
            "update public.leads set business_id = %s where business_id = %s", [keep_id, drop_id], conn=c
        )
        # Better values from the dropped row win by source precedence (6.6.4).
        keep_src = (keep.get("extra") or {}).get("src", {})
        drop_src = (drop.get("extra") or {}).get("src", {})
        updates: dict[str, Any] = {}
        groups = {
            "name": ("name", "norm_name"),
            "geo": ("lat", "lng"),
            "address": ("address", "locality"),
            "category": ("category", "subcategory"),
        }
        for group, cols in groups.items():
            if drop.get(cols[0]) is not None and rank(group, drop_src.get(group)) < rank(group, keep_src.get(group)):
                updates.update({col: drop.get(col) for col in cols})
                keep_src[group] = drop_src.get(group)
        for col in ("website", "web_domain", "place_id", "overture_id", "city", "review_count", "rating"):
            if keep.get(col) is None and drop.get(col) is not None:
                updates[col] = drop[col]
        branches = max(int(keep.get("branches_count") or 0), int(drop.get("branches_count") or 0)) or None
        extra = {**(drop.get("extra") or {}), **(keep.get("extra") or {}), "src": keep_src}
        extra["merged_from"] = [*extra.get("merged_from", []), drop_id][-10:]
        db.execute(
            "update public.businesses set place_id = null, overture_id = null, web_domain = null where id = %s",
            [drop_id],
            conn=c,
        )
        db.execute("delete from public.businesses where id = %s", [drop_id], conn=c)
        updates["branches_count"] = branches
        updates["extra"] = Jsonb(extra)
        sets = ", ".join(f"{k} = %({k})s" for k in updates)
        db.execute(f"update public.businesses set {sets} where id = %(id)s", {**updates, "id": keep_id}, conn=c)
        if survivor:
            db.execute(
                "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'merge', %s)",
                [survivor, Jsonb({"merged_business": drop_id})],
                conn=c,
            )
        out["survivor_lead"] = survivor
        return out

    if conn is not None:
        return run(conn)
    with db.tx("engine", {"reason": "merge_businesses"}) as txc:
        return run(txc)
