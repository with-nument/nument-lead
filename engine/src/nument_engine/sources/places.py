"""Google Places API (New): ID-only text search, capped details and reviews (Step 5.5).

Terms (A.4.4, Step 5.5.5) enforced here and in `cleanup_expired()`:
- `place_id` is the only Places field stored for good.
- rating, review count, coordinates and the listing phone are refreshed within 30 days or removed.
- Review text is never stored or logged: reviews are read in memory, turned into derived flags, and dropped.

Without `GOOGLE_MAPS_API_KEY` the adapter does nothing and says so once in `source_health` (the key is being set
up by the founder). Quotas: every call is logged in `costs` (provider `google_places`, the region in `model`), and
the daily and monthly free allowances are counted from there before each Details call.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .. import db
from ..http import FetchResult
from ..normalize import homepage, is_ignored_host
from ..segments import Segment
from ..settings import get_settings
from . import health
from .base import SourceAdapter, SourceRecord

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
SEARCH_MASK = "places.id,nextPageToken"
DETAILS_MASK = (
    "id,displayName,formattedAddress,addressComponents,location,rating,userRatingCount,websiteUri,"
    "nationalPhoneNumber,internationalPhoneNumber,businessStatus,primaryType,types"
)
REVIEWS_MASK = "id,reviews"
MAX_PAGES = 3  # 20 results a page, about 60 a query

# Free allowances per SKU and month, and our daily caps (A.10.2, Step 19.7). India and abroad differ a lot.
FREE_PER_MONTH = {"in": 7000, "global": 1000}
DAILY_CAP_SETTING = {"in": "places_details_cap_in", "global": "places_details_cap_global"}
DAILY_CAP_DEFAULT = {"in": 230, "global": 30}
COST_PROVIDER = "google_places"
TASK_SEARCH = "places_text_search"
TASK_DETAILS = "places_details"
TASK_REVIEWS = "places_details_reviews"


class QuotaReached(Exception):
    """A daily or monthly Places allowance is used up. Stop calling that SKU until tomorrow."""

    def __init__(self, task: str, detail: str) -> None:
        super().__init__(f"{task}: {detail}")
        self.task = task


class PlacesApiError(Exception):
    """A Places API error with Google's status (PERMISSION_DENIED, RESOURCE_EXHAUSTED, INVALID_ARGUMENT, ...)."""

    def __init__(self, status_code: int | None, status: str, message: str) -> None:
        super().__init__(f"Places API {status_code} {status}: {message[:200]}")
        self.status_code = status_code
        self.status = status


def region_of(country: str) -> str:
    """Billing region: India has its own free allowances, everything else is `global`."""
    return "in" if country.lower() == "in" else "global"


def listing_url(place_id: str) -> str:
    """Link to the Google listing, used as evidence for review signals and listing phones (Step 7.4.4)."""
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


@dataclass
class Review:
    """One review held in memory only. Never stored, never logged (A.4.4)."""

    text: str
    rating: float | None
    published: datetime | None


class PlacesAdapter(SourceAdapter):
    name = "places"
    policy = "official_api"
    min_gap_s = 0.2  # 5 requests per second

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        key = get_settings().google_maps_api_key
        self._key = key.get_secret_value() if key else ""
        self._used: dict[tuple[str, str], int] = {}  # (task, segment) -> calls this run

    # ---- availability -------------------------------------------------------------------------------
    def has_key(self) -> bool:
        return bool(self._key)

    def status(self) -> tuple[bool, str]:
        if not self.has_key():
            return False, "GOOGLE_MAPS_API_KEY is not set: Places search, details and reviews are skipped"
        return super().status()

    def report_missing_key(self) -> None:
        """Write the 'no key' message to source_health once per run, so the Engine page explains the gap."""
        if self.ctx.stats.get("places.no_key_reported"):
            return
        self.ctx.stats["places.no_key_reported"] = True
        health.mark_error(self.name, self.status()[1])

    # ---- low level ------------------------------------------------------------------------------------
    def _headers(self, mask: str) -> dict[str, str]:
        return {"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": mask}

    @staticmethod
    def _error(res: FetchResult) -> PlacesApiError:
        status, message = "UNKNOWN", res.reason
        try:
            err = res.json().get("error", {})
            status, message = str(err.get("status") or status), str(err.get("message") or message)
        except ValueError:
            pass
        return PlacesApiError(res.status, status, message)

    async def _call(self, url: str, mask: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if body is None:
            res = await self.http.get(url, headers=self._headers(mask), check_robots=False, raise_on_block=False)
        else:
            res = await self.http.post_json(url, body, headers=self._headers(mask))
        if res.status is not None and 200 <= res.status < 300:
            data: dict[str, Any] = res.json()
            return data
        raise self._error(res)

    def handle_api_error(self, err: PlacesApiError) -> None:
        """Step 5.5.6: permission problems pause the adapter and alert; quota errors stop it for the day;
        a bad request is a bug and is raised."""
        if err.status_code == 400 or err.status == "INVALID_ARGUMENT":
            raise err
        if err.status_code == 429 or err.status == "RESOURCE_EXHAUSTED":
            until = health.next_ist_midnight()
            health.mark_error(self.name, str(err), blocked_until=until, requests=self.new_requests())
            self.ctx.alert(f"Places quota reached ({err.status}); paused until midnight IST")
            return
        if err.status_code in (401, 403) or err.status in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
            until = health.now_utc() + health.BACKOFF[0]
            health.mark_error(self.name, str(err), blocked_until=until, requests=self.new_requests())
            self.ctx.alert(f"Places API refused the key ({err.status}): check the key and that the API is enabled")
            return
        health.mark_error(self.name, str(err), requests=self.new_requests())

    # ---- quotas ---------------------------------------------------------------------------------------
    def details_left(self, seg: Segment, task: str = TASK_DETAILS) -> int:
        """Details calls still allowed now for this segment: the smallest of the segment's daily cap, the
        region's daily cap and the region's free monthly allowance."""
        region = region_of(seg.country)
        seg_cap = seg.places.details_per_day if task == TASK_DETAILS else seg.places.reviews_per_day
        seg_left = seg_cap - self._used.get((task, seg.id), 0)
        day_cap = health.setting_int(DAILY_CAP_SETTING[region], DAILY_CAP_DEFAULT[region])
        day_left = day_cap - health.calls_today(COST_PROVIDER, task, model=region)
        month_left = FREE_PER_MONTH[region] - health.calls_this_month(COST_PROVIDER, task, model=region)
        return max(0, min(seg_left, day_left, month_left))

    def _take(self, seg: Segment, task: str) -> None:
        left = self.details_left(seg, task)
        if left <= 0:
            raise QuotaReached(task, f"no {task} calls left today for {seg.id} ({region_of(seg.country)})")
        self._used[(task, seg.id)] = self._used.get((task, seg.id), 0) + 1

    def _log(self, task: str, seg: Segment) -> None:
        health.log_cost(self.ctx.run_id, COST_PROVIDER, task, model=region_of(seg.country))

    # ---- API ------------------------------------------------------------------------------------------
    async def search_ids(self, text_query: str, seg: Segment, rect: Sequence[float]) -> list[str]:
        """Text Search, IDs only (free and unlimited): at most 3 pages, about 60 ids per query."""
        min_lng, min_lat, max_lng, max_lat = rect
        ids: list[str] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            body: dict[str, Any] = {
                "textQuery": text_query,
                "pageSize": 20,
                "regionCode": seg.country.upper(),
                "languageCode": "en",
                "locationRestriction": {
                    "rectangle": {
                        "low": {"latitude": min_lat, "longitude": min_lng},
                        "high": {"latitude": max_lat, "longitude": max_lng},
                    }
                },
            }
            if token:
                body["pageToken"] = token
            data = await self._call(SEARCH_URL, SEARCH_MASK, body=body)
            self._log(TASK_SEARCH, seg)
            ids += [str(p["id"]) for p in data.get("places", []) if p.get("id")]
            token = data.get("nextPageToken")
            if not token:
                break
        return list(dict.fromkeys(ids))

    async def details(self, place_id: str, seg: Segment) -> dict[str, Any]:
        """Place Details (Enterprise SKU) inside the caps. Raises QuotaReached when none are left."""
        self._take(seg, TASK_DETAILS)
        data = await self._call(DETAILS_URL.format(place_id=place_id), DETAILS_MASK)
        self._log(TASK_DETAILS, seg)
        return data

    async def reviews(self, place_id: str, seg: Segment) -> list[Review]:
        """Up to 5 reviews (Enterprise + Atmosphere SKU), in memory only."""
        self._take(seg, TASK_REVIEWS)
        data = await self._call(DETAILS_URL.format(place_id=place_id), REVIEWS_MASK)
        self._log(TASK_REVIEWS, seg)
        out = []
        for r in data.get("reviews", [])[:5]:
            text = (r.get("text") or {}).get("text") or (r.get("originalText") or {}).get("text") or ""
            published = None
            if r.get("publishTime"):
                try:
                    published = datetime.fromisoformat(str(r["publishTime"]).replace("Z", "+00:00"))
                except ValueError:
                    published = None
            out.append(Review(text=text, rating=r.get("rating"), published=published))
        return out

    # ---- mapping ---------------------------------------------------------------------------------------
    @staticmethod
    def locality_from(components: list[dict[str, Any]] | None) -> str | None:
        for wanted in ("sublocality_level_1", "neighborhood", "sublocality"):
            for comp in components or []:
                if wanted in (comp.get("types") or []):
                    return str(comp.get("longText") or comp.get("shortText") or "") or None
        return None

    @classmethod
    def to_record(cls, data: dict[str, Any], seg: Segment, city: str | None) -> SourceRecord | None:
        place_id = data.get("id")
        name = ((data.get("displayName") or {}).get("text") or "").strip()
        if not place_id or not name:
            return None
        website = data.get("websiteUri")
        loc = data.get("location") or {}
        primary = data.get("primaryType")
        subcategory = seg.subcategory_for(primary, name)
        if subcategory is None:
            for t in data.get("types") or []:
                subcategory = seg.subcategory_for(t, "")
                if subcategory:
                    break
        phones = [p for p in (data.get("internationalPhoneNumber"), data.get("nationalPhoneNumber")) if p]
        return SourceRecord(
            source="places",
            source_key=str(place_id),
            segment_id=seg.id,
            name=name,
            website=homepage(website) if website and not is_ignored_host(website) else None,
            phones_raw=phones[:1],
            address=data.get("formattedAddress"),
            city=city,
            locality=cls.locality_from(data.get("addressComponents")),
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
            category=primary,
            subcategory=subcategory,
            place_id=str(place_id),
            rating=data.get("rating"),
            review_count=data.get("userRatingCount"),
            business_status=data.get("businessStatus"),
            phones_are_listing=True,
            # The listing phone is Places content: kept 30 days at most, stripped by cleanup_expired().
            payload={
                "primary_type": primary,
                "business_status": data.get("businessStatus"),
                "internationalPhoneNumber": data.get("internationalPhoneNumber"),
                "nationalPhoneNumber": data.get("nationalPhoneNumber"),
            },
        )


def cleanup_expired(days: int = 30, conn: Any = None) -> dict[str, int]:
    """Google terms (A.4.4): 30 days after `places_fetched_at`, unless refreshed, null rating and review count
    (and coordinates that came from Places), and delete listing phones. `place_id` is kept for good."""
    biz = db.execute(
        """
        update public.businesses
           set rating = null,
               review_count = null,
               lat = case when extra #>> '{src,geo}' = 'places' then null else lat end,
               lng = case when extra #>> '{src,geo}' = 'places' then null else lng end,
               extra = case when extra #>> '{src,geo}' = 'places' then extra #- '{src,geo}' else extra end
         where places_fetched_at < now() - make_interval(days => %s)
           and (rating is not null or review_count is not null or extra #>> '{src,geo}' = 'places')
        """,
        [days],
        conn=conn,
    )
    phones = db.execute(
        """
        delete from public.contacts
         where source = 'google_listing'
           and coalesce(verified_at, updated_at) < now() - make_interval(days => %s)
        """,
        [days],
        conn=conn,
    )
    payloads = db.execute(
        """
        update public.source_records
           set payload = payload - 'internationalPhoneNumber' - 'nationalPhoneNumber'
         where source = 'places' and fetched_at < now() - make_interval(days => %s)
           and (payload ? 'internationalPhoneNumber' or payload ? 'nationalPhoneNumber')
        """,
        [days],
        conn=conn,
    )
    return {"places_content_cleared": biz, "listing_phones_deleted": phones, "listing_payloads_cleared": payloads}


# ---------------------------------------------------------------------------------------------------
# Review pain (Step 7.5.5): derived flags only, computed in memory
# ---------------------------------------------------------------------------------------------------

REVIEW_FLAGS: dict[str, tuple[str, ...]] = {
    "unanswered_calls": (
        r"(?:no ?one|nobody|never|did ?n[o']?t|does ?n[o']?t|do ?n[o']?t|not)\s+(?:even\s+)?(?:pick|answer|receive)",
        r"call(?:s)?\s+(?:went\s+)?(?:un ?answered|not\s+(?:answered|picked|received|connected))",
        r"phone\s+(?:is\s+)?(?:always\s+)?(?:busy|switched off|not reachable|unreachable|not answered)",
        r"(?:could|can)\s?n[o']?t\s+(?:reach|get through|connect)",
        r"no response (?:on|to) (?:the )?(?:call|phone|calls)",
        r"(?:phone|call)\s+(?:nahi|nhi)\s+(?:uthate|uthaya|uthati|lagta)",
    ),
    "slow_whatsapp": (
        r"whats ?app[^.]{0,60}(?:no reply|no response|not respond|didn'?t reply|never replied|ignored|late reply)",
        r"(?:no reply|no response|never replied)[^.]{0,40}whats ?app",
    ),
    "booking_trouble": (
        r"appointment[^.]{0,60}(?:cancel+ed|not confirmed|never confirmed|messed up|no slot|resched)",
        r"(?:could|can)\s?n[o']?t\s+(?:book|get an appointment|schedule)",
        r"(?:booking|appointment) (?:system|process) (?:is )?(?:bad|poor|terrible|confusing)",
    ),
    "long_wait": (
        r"wait(?:ed|ing)\s+(?:for\s+)?(?:more than\s+|over\s+)?(?:\d+|two|three|an?)\s*(?:\+\s*)?(?:hours?|hrs?)",
        r"long wait(?:ing)?(?: time)?",
        r"kept (?:us |me )?waiting",
    ),
    "rude_front_desk": (
        r"(?:rude|unprofessional|arrogant|careless)\s+(?:reception|receptionist|front desk|staff)",
        r"(?:reception|receptionist|front desk|staff)\s+(?:is|was|were|are)\s+(?:very\s+)?(?:rude|unprofessional)",
    ),
}
_REVIEW_PATTERNS = {flag: [re.compile(p, re.I) for p in pats] for flag, pats in REVIEW_FLAGS.items()}
REVIEW_MAX_AGE_DAYS = 90


def review_flags(reviews: Sequence[Review], now: datetime | None = None) -> dict[str, Any] | None:
    """Derived review pain for up to 5 reviews: {flags, matching_reviews, of_reviews, newest_flag_age_days},
    or None when no recent review mentions a flag. Review text never leaves this function."""
    now = now or datetime.now(UTC)
    flags: set[str] = set()
    matching = 0
    newest: int | None = None
    for review in reviews:
        hit = {flag for flag, pats in _REVIEW_PATTERNS.items() if any(p.search(review.text or "") for p in pats)}
        if not hit:
            continue
        age = (now - review.published).days if review.published else None
        if age is not None and age > REVIEW_MAX_AGE_DAYS:
            continue
        matching += 1
        flags |= hit
        if age is not None and (newest is None or age < newest):
            newest = age
    if not matching:
        return None
    return {
        "flags": sorted(flags),
        "matching_reviews": matching,
        "of_reviews": len(reviews),
        "newest_flag_age_days": newest,
    }
