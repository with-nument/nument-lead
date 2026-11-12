"""Practo clinic profiles: size, price and review evidence for clinics in India (Step 5.7, Step 9.10).

Founder approved (12 Nov 2026), switched on by migration 0010. Public pages only, one request every 5 seconds,
at most `practo.pages_per_day` page requests a day, robots.txt checked for every URL, stop on any block.

1. The index. robots.txt lists `profiles-sitemap.xml`, a sitemap index whose `titan-india-clinic-profiles-N`
   files (gzipped, about 22 of them) list every clinic profile in India. Only the profile roots
   (`/<city>/clinic/<slug>`) of the segment cities are kept, in `.cache/practo/clinic-profiles.json.gz`,
   rebuilt after 30 days (the night workflow caches the folder for the month). Built only when a clinic needs it.
2. The match (never a guess). Candidates are the city's profiles whose slug holds every word of the name (small
   spelling differences allowed, or the whole name written as one word); at most 3 are opened, closest first.
   A profile counts only when its page confirms it: the same website, or Practo's name holding the business
   name plus a point within 1 km or Practo's locality in the business's address. A different website rejects it.
3. What is kept. The profile page is stored as one of the business's pages, so the AI extraction quotes doctors,
   fees and services from it. Code also reads the page data: rating and patient stories, the number of doctors,
   consultation fees and whether the clinic claimed its profile, written as facts with the Practo URL. Practo
   shows masked or virtual numbers, so no phone is ever taken.
4. Recent stories. The profile's `recent` tab lists the newest stories; those with text from the last 90 days
   (and any dated helpful story on the profile) go to `review_pain.classify`.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from rapidfuzz import fuzz

from ..http import FetchResult
from ..logging import get_logger
from ..normalize import match_key, meters, norm_name, web_domain
from ..segments import Segment
from ..settings import get_settings
from . import health
from .base import SourceAdapter
from .review_pain import ReviewText

log = get_logger()

ROBOTS: Final = "https://www.practo.com/robots.txt"
BASE: Final = "https://www.practo.com"
PROFILE = re.compile(r"^https://www\.practo\.com/(?P<city>[a-z-]+)/clinic/(?P<slug>[a-z0-9-]+)/?$")
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
INDEX_SITEMAP = re.compile(r"/profiles-sitemap\.xml$")
CLINIC_SITEMAP = re.compile(r"-india-clinic-profiles-\d+-sitemap\.xml(?:\.gz)?$")
DOCTORS = re.compile(r"\bDoctors?\s*\(\s*(\d{1,3})\s*\)", re.I)
JSONLD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
REDUX = re.compile(r"window\.__REDUX_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)
TRAILING_NUMBER = re.compile(r"-\d+$")
MIN_SQUASHED: Final = 8  # a squashed name shorter than this ("drali") matches too many slugs
MAX_CANDIDATES: Final = 3
FILLER_WORDS: Final = frozenset({"and", "of", "the", "for", "dr", "s", "by"})  # often missing from a slug
NEAR_M: Final = 1000.0
INDEX_MAX_AGE: Final = timedelta(days=30)
MAX_XML_BYTES: Final = 80_000_000  # one unzipped clinic sitemap is about 12 MB
DEFAULT_PAGES_PER_DAY: Final = 150
SETTING_PAGES: Final = "practo.pages_per_day"


# ---------------------------------------------------------------------------------------------------
# Names and slugs
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Profile:
    url: str
    city_slug: str
    slug: str


def parse_profile(url: str) -> Profile | None:
    m = PROFILE.match(url.strip())
    return Profile(url.strip().rstrip("/"), m.group("city"), m.group("slug")) if m else None


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm_name(text)).strip("-")


def city_slugs(seg: Segment, city: str) -> set[str]:
    """Practo city slugs for one segment city: its name and aliases (Bengaluru also as bangalore)."""
    for c in seg.cities:
        if c.name.lower() == city.lower() or city.lower() in (a.lower() for a in c.aliases):
            return {slugify(n) for n in (c.name, *c.aliases)}
    return {slugify(city)}


def all_city_slugs(seg: Segment) -> set[str]:
    return {s for c in seg.cities for s in city_slugs(seg, c.name)}


@lru_cache(maxsize=200_000)
def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm_name(text))


@lru_cache(maxsize=200_000)
def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match_key(text).split())


def covers(name: str, other: str, ignore: Iterable[str] = ()) -> bool:
    """True when every word of the business name (generic words and `ignore` aside) is in `other`, allowing
    small spelling differences, or when the whole name written as one word ("Dralisdentacare") is inside it."""
    squashed = _squash(name)
    if len(squashed) >= MIN_SQUASHED and squashed in _squash(other):
        return True
    skip = {t for w in ignore for t in _tokens(w)} | FILLER_WORDS
    want = [t for t in _tokens(name) if t not in skip]
    have = _tokens(other)
    if not want or not have:
        return False
    return all(any(t == h or (min(len(t), len(h)) >= 4 and fuzz.ratio(t, h) >= 85) for h in have) for t in want)


def candidates(
    name: str, locality: str | None, profiles: Sequence[Profile], *, limit: int = MAX_CANDIDATES
) -> list[Profile]:
    """Profiles whose slug holds every word of the name, closest first (a slug naming the business's
    locality wins a tie). The slug also holds Practo's locality, so extra slug words are expected."""
    key = match_key(name)
    if not key or (len(key.split()) == 1 and len(_squash(name)) < MIN_SQUASHED):
        return []  # one short word ("smile") matches hundreds of clinics
    loc = slugify(locality or "")
    scored: list[tuple[bool, float, Profile]] = []
    for prof in profiles:
        words = TRAILING_NUMBER.sub("", prof.slug).replace("-", " ")
        if not covers(name, words):
            continue
        closeness = float(fuzz.token_sort_ratio(key, match_key(words)))
        scored.append((bool(loc) and loc in prof.slug, closeness, prof))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in scored[:limit]]


# ---------------------------------------------------------------------------------------------------
# The profile page
# ---------------------------------------------------------------------------------------------------


@dataclass
class PractoPage:
    """What code reads from one clinic profile page."""

    url: str
    name: str | None = None
    locality: str | None = None
    city: str | None = None
    lat: float | None = None
    lng: float | None = None
    website: str | None = None
    rating: float | None = None
    stories: int | None = None
    doctors: int | None = None
    fee_min: int | None = None
    fee_max: int | None = None
    claimed: bool | None = None
    reviews: list[ReviewText] = field(default_factory=list)


def _jsonld(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in JSONLD.findall(html):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                out.append(item)
    return out


def redux_state(html: str) -> dict[str, Any]:
    m = REDUX.search(html)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _float(raw: Any) -> float | None:
    try:
        return float(raw) if raw is not None and str(raw).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _int(raw: Any) -> int | None:
    value = _float(raw)
    return int(value) if value is not None else None


def _parse_time(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def stories_from_state(state: dict[str, Any], now: datetime | None = None) -> list[ReviewText]:
    """Patient stories with text in the page data, with their age in days. Votes without text are skipped."""
    now = now or datetime.now(UTC)
    out: list[ReviewText] = []
    for item in ((state.get("feedback_reducer") or {}).get("reviews")) or []:
        if not isinstance(item, dict):
            continue
        review = item.get("review") or {}
        text = str(((review.get("survey_response") or {}).get("review_text")) or "").strip()
        if not text:
            continue
        when = _parse_time(item.get("answered_at")) or _parse_time(review.get("status_modified_at"))
        age = max(0, (now - when).days) if when else None
        out.append(ReviewText(text, age))
    return out


def parse_page(html: str, url: str, now: datetime | None = None) -> PractoPage:
    """Rating, stories, doctors, fees, claim, place and stories from one profile page (JSON-LD and page data)."""
    page = PractoPage(url=url)
    fees: list[int] = []
    for item in _jsonld(html):
        kind = item.get("@type")
        if kind == "MedicalClinic":
            page.name = str(item.get("name") or "").strip() or None
            agg = item.get("aggregateRating") or {}
            page.rating = _float(agg.get("ratingValue")) or None  # 0 means no rating yet
            page.stories = _int(agg.get("ratingCount") or agg.get("reviewCount"))
            addr = item.get("address") or {}
            page.locality = str(addr.get("addressLocality") or "").strip() or None
            page.city = str(addr.get("addressRegion") or "").strip() or None
            geo = item.get("geo") or {}
            page.lat, page.lng = _float(geo.get("latitude")), _float(geo.get("longitude"))
        elif kind == "Physician":
            fee = _int(item.get("priceRange"))
            if fee:
                fees.append(fee)
    if fees:
        page.fee_min, page.fee_max = min(fees), max(fees)
    state = redux_state(html)
    profile = state.get("profile_reducer") or {}
    if isinstance(profile, dict):
        claim = (profile.get("external_data") or {}).get("claim_info") or profile.get("claim_info")
        if isinstance(claim, dict) and isinstance(claim.get("is_already_claimed"), bool):
            page.claimed = claim["is_already_claimed"]
        page.website = str(profile.get("website") or "").strip() or None
        page.doctors = _int(profile.get("doctors_count"))
        addr = profile.get("address") or {}
        if page.lat is None and isinstance(addr, dict):
            page.lat, page.lng = _float(addr.get("latitude")), _float(addr.get("longitude"))
        if page.locality is None and isinstance(addr, dict):
            page.locality = str((addr.get("locality") or {}).get("name") or "").strip() or None
        rating = profile.get("rating") or {}
        if page.rating is None and isinstance(rating, dict):
            page.rating = _float(rating.get("clinic_rating")) or None
    if page.doctors is None:
        m = DOCTORS.search(re.sub(r"<[^>]+>", " ", html))
        page.doctors = int(m.group(1)) if m else None
    page.reviews = stories_from_state(state, now)
    return page


def confirms(business: dict[str, Any], page: PractoPage) -> str | None:
    """Why this profile is the business ("website", "distance", "locality"), or None when nothing confirms it.
    The same website settles it and two different websites reject it. Otherwise Practo's name must hold every
    word of the business name (its locality and city aside) and the place must agree: within 1 km, or Practo's
    locality named in the business's address."""
    own = business.get("web_domain") or web_domain(business.get("website"))
    theirs = web_domain(page.website) if page.website else None
    if own and theirs:
        return "website" if own == theirs else None
    ignore = [page.locality or "", page.city or "", str(business.get("city") or "")]
    if not page.name or not covers(str(business.get("name") or ""), page.name, ignore):
        return None
    lat, lng = business.get("lat"), business.get("lng")
    if lat is not None and lng is not None and page.lat is not None and page.lng is not None:
        return "distance" if meters(float(lat), float(lng), page.lat, page.lng) <= NEAR_M else None
    loc = norm_name(page.locality or "")
    if len(loc) >= 4:
        where = norm_name(" ".join(str(business.get(k) or "") for k in ("address", "locality")))
        if re.search(rf"(?<!\w){re.escape(loc)}(?!\w)", where):
            return "locality"
    return None


def facts(page: PractoPage) -> list[tuple[str, dict[str, Any], str]]:
    """(field, value, quote) facts code writes from a matched profile, each with the profile URL."""
    out: list[tuple[str, dict[str, Any], str]] = []
    if page.stories:
        quote = (
            f"{page.rating:.1f} ({page.stories} patient stories)" if page.rating else f"{page.stories} patient stories"
        )
        out.append(("practo_reviews", {"stories": page.stories, "rating": page.rating, "source": "practo"}, quote))
    if page.doctors:
        out.append(("staff_or_doctors", {"count": page.doctors, "source": "practo"}, f"Doctors ({page.doctors})"))
    if page.fee_min:
        quote = f"₹{page.fee_min}" if page.fee_min == page.fee_max else f"₹{page.fee_min} - ₹{page.fee_max}"
        out.append(("practo_fees", {"min": page.fee_min, "max": page.fee_max, "currency": "INR"}, quote))
    if page.claimed:
        out.append(
            ("practo_claimed", {"claimed": True}, "Practo profile is claimed (is_already_claimed in the page data)")
        )
    return out


# ---------------------------------------------------------------------------------------------------
# The index of clinic profiles
# ---------------------------------------------------------------------------------------------------


def index_path() -> Path:
    return get_settings().cache_dir / "practo" / "clinic-profiles.json.gz"


def load_index(path: Path, now: datetime | None = None) -> dict[str, list[str]] | None:
    """{city slug: [profile slugs]} from the cached file, or None when missing, unreadable or too old."""
    try:
        data = json.loads(gzip.decompress(path.read_bytes()))
        built = datetime.fromisoformat(str(data["built_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if (now or datetime.now(UTC)) - built > INDEX_MAX_AGE:
        return None
    urls = data.get("profiles")
    return urls if isinstance(urls, dict) else None


def save_index(path: Path, profiles: dict[str, list[str]], now: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"built_at": (now or datetime.now(UTC)).isoformat(), "profiles": profiles}
    path.write_bytes(gzip.compress(json.dumps(body, separators=(",", ":")).encode("utf-8")))


def profile_roots(urls: Iterable[str], wanted: set[str]) -> dict[str, list[str]]:
    """Clinic profile roots of the wanted cities, by city slug (sub-pages such as /services are dropped)."""
    out: dict[str, set[str]] = {}
    for url in urls:
        prof = parse_profile(url)
        if prof is not None and prof.city_slug in wanted:
            out.setdefault(prof.city_slug, set()).add(prof.slug)
    return {city: sorted(slugs) for city, slugs in out.items()}


def _xml_text(res: FetchResult) -> str:
    raw = res.content or res.text.encode("utf-8")
    if raw[:2] == b"\x1f\x8b":
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as fh:
            raw = fh.read(MAX_XML_BYTES)
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------------------------------


@dataclass
class PractoMatch:
    """A confirmed profile: the page to store, what code read from it, and recent stories with text."""

    result: FetchResult
    page: PractoPage
    how: str
    stories: list[ReviewText] = field(default_factory=list)


class PractoAdapter(SourceAdapter):
    name = "practo"
    policy = "public"
    min_gap_s = 5.0
    max_bytes = 3_000_000  # a gzipped sitemap is about 1 MB, a profile page about 0.7 MB

    def __init__(self, *args: Any, time_left: Callable[[], float] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._index: dict[str, list[str]] | None = None
        self._lock = asyncio.Lock()
        self.pages = 0
        self.time_left = time_left  # the run's deadline: no new page once it has passed

    # ---- the index ------------------------------------------------------------------------------------
    async def sitemaps(self) -> list[str]:
        res = await self.http.get(ROBOTS, check_robots=False)
        if not res.ok:
            return []
        return [line.split(":", 1)[1].strip() for line in res.text.splitlines() if line.lower().startswith("sitemap:")]

    async def build_index(self, wanted: set[str]) -> dict[str, list[str]]:
        """Read the clinic profile sitemaps (about 22 files) and keep the wanted cities' profile roots."""
        urls: list[str] = []
        for sitemap in await self.sitemaps():
            if not INDEX_SITEMAP.search(sitemap):
                continue
            res = await self.http.get(sitemap)
            children = [u for u in LOC.findall(_xml_text(res)) if CLINIC_SITEMAP.search(u)] if res.ok else []
            for child in children:
                child_res = await self.http.get(child)
                if child_res.ok:
                    urls += LOC.findall(_xml_text(child_res))
                else:
                    self.ctx.add("practo.sitemap_failed")
        profiles = profile_roots(urls, wanted)
        self.ctx.add("practo.index_profiles", sum(len(v) for v in profiles.values()))
        return profiles

    async def index(self, seg: Segment) -> dict[str, list[str]]:
        """The cached index, or a fresh one (built once per run, kept 30 days)."""
        async with self._lock:
            if self._index is None:
                path = index_path()
                cached = load_index(path)
                if cached is not None:
                    self._index = cached
                else:
                    self._index = await self.build_index(all_city_slugs(seg))
                    if self._index:
                        save_index(path, self._index)
                        self.ctx.add("practo.index_built")
            return self._index

    async def profiles_for(self, seg: Segment, city: str) -> list[Profile]:
        index = await self.index(seg)
        return [
            Profile(f"{BASE}/{c}/clinic/{slug}", c, slug)
            for c in sorted(city_slugs(seg, city))
            for slug in index.get(c, [])
        ]

    # ---- one clinic -----------------------------------------------------------------------------------
    def pages_left(self) -> int:
        cap = health.setting_int(SETTING_PAGES, DEFAULT_PAGES_PER_DAY)
        return cap - self.pages

    async def _page(self, url: str) -> FetchResult | None:
        if self.pages_left() <= 0:
            self.ctx.add("practo.cap_reached")
            return None
        if self.time_left is not None and self.time_left() <= 0:
            self.ctx.add("practo.deadline")
            return None
        self.pages += 1
        self.ctx.add("practo.pages")
        res = await self.http.get(url)
        return res if res.ok else None

    async def match(self, business: dict[str, Any], seg: Segment) -> PractoMatch | None:
        """The confirmed Practo profile of one clinic, with its recent stories, or None."""
        if seg.id != "clinics-in" or not business.get("city") or not business.get("name"):
            return None
        found = candidates(business["name"], business.get("locality"), await self.profiles_for(seg, business["city"]))
        if not found:
            self.ctx.add("practo.no_candidate")
            return None
        for prof in found:
            res = await self._page(prof.url)
            if res is None:
                if self.pages_left() <= 0:
                    return None
                continue
            page = parse_page(res.text, prof.url)
            how = confirms(business, page)
            if how is None:
                self.ctx.add("practo.not_confirmed")
                continue
            self.ctx.add(f"practo.matched_{how}")
            stories = list(page.reviews)
            recent = await self._page(f"{prof.url}/recent")
            if recent is not None:
                seen = {s.text for s in stories}
                stories += [s for s in stories_from_state(redux_state(recent.text)) if s.text not in seen]
            return PractoMatch(res, page, how, stories)
        self.ctx.add("practo.no_match")
        return None
