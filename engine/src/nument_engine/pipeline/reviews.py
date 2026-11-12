"""Public review numbers for businesses without Google Places data (the Places fallback, no billing account).

The official Places API needs a Google Cloud billing account. Without one, one Gemini call with Google Search
grounding per business reads the Google rating and review count (and, for clinics in India, Practo's numbers)
that public search results show. Code accepts a number only when a grounding support (a sentence of the answer
that the search results back) contains it; any other number is dropped, never guessed.

Stored the way Places data is: `businesses.review_count` and `rating` (never over Places numbers), the date in
`extra.reviews_at`, and one fact per source whose quote is the supported sentence. Grounded results are kept at
most 30 days, like Places content (A.4.4): older numbers are cleared and looked up again.

Runs in the morning between verify and score, so the businesses researched overnight are scored with them.

Cheaper sources first: a business whose Google numbers the night's Maps lookup confirmed (`extra.maps_reviews`,
kept 30 days) is skipped, and one whose Practo profile research matched (`extra.practo`) is asked for its Google
numbers only. Maps numbers expire after 30 days exactly like grounded ones.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final

from .. import db
from ..logging import get_logger
from ..segments import Segment
from . import ai, score
from .runs import RunContext

log = get_logger()

TASK: Final = "lookup_reviews"
SETTING: Final = "reviews.lookups_per_day"
DEFAULT_PER_DAY: Final = 120
MAX_DOWN_STREAK: Final = 3  # consecutive "no usable provider" answers before the stage stops
KEEP_DAYS: Final = 30
SOURCE: Final = "grounded_search"
EXPIRING_SOURCES: Final = (SOURCE, "maps_reviews")  # review numbers kept 30 days like Places content
COUNTRY_NAMES: Final[dict[str, str]] = {"in": "India", "ae": "the UAE", "sa": "Saudi Arabia", "qa": "Qatar"}
KINDS: Final[dict[str, str]] = {
    "clinics": "clinic",
    "realestate": "real estate business",
    "education": "coaching or education",
}

CANDIDATES_SQL: Final = """
select b.id, b.name, b.city, b.country, b.website, b.segment_id, b.extra
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.status in ('researched', 'qualified', 'dormant')
   and b.places_fetched_at is null
   and coalesce((b.extra->>'reviews_lookup_at')::timestamptz, 'epoch') < now() - make_interval(days => %(keep)s)
   and not (coalesce((b.extra #>> '{maps_reviews,matched}')::boolean, false)
            and (b.extra #>> '{maps_reviews,at}')::timestamptz > now() - make_interval(days => %(keep)s)
            and b.review_count is not null)
 order by (b.status = 'researched') desc,
          exists (select 1 from public.signals s where s.business_id = b.id and s.expires_at > now()) desc,
          coalesce(b.branches_count, 1) desc,
          b.researched_at desc nulls last
 limit %(limit)s
"""


def number_supported(value: float | int, texts: list[str]) -> bool:
    """True when the number appears, as a whole number, in a sentence the search results back."""
    variants = {f"{value:g}"}
    if float(value).is_integer():
        n = int(value)
        variants |= {str(n), f"{n:,}", _indian(n)}
    else:
        variants.add(f"{value:.1f}")
    for v in variants:
        pattern = re.compile(rf"(?<![\d.,]){re.escape(v)}(?![\d]|[.,]\d)")
        if any(pattern.search(t) for t in texts):
            return True
    return False


def _indian(n: int) -> str:
    """12,34,567 style grouping (Indian sites write counts this way)."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def supporting_sentence(value: float | int, texts: list[str]) -> str | None:
    for t in texts:
        if number_supported(value, [t]):
            return t.strip()[:300]
    return None


def accepted(output: Any, grounding: dict[str, Any] | None) -> dict[str, Any]:
    """The numbers code can stand behind: in range and backed by a grounding support."""
    texts = [str(s.get("text") or "") for s in (grounding or {}).get("supports") or [] if s.get("text")]
    if not texts or not (grounding or {}).get("sources"):
        return {}
    out: dict[str, Any] = {}
    count, rating = output.google_review_count, output.google_rating
    if count is not None and count >= 1 and number_supported(count, texts):
        out["google"] = {"count": int(count), "quote": supporting_sentence(count, texts)}
        if rating is not None and 1.0 <= rating <= 5.0 and number_supported(rating, texts):
            out["google"]["rating"] = round(float(rating), 1)
    stories, p_rating = output.practo_story_count, output.practo_rating
    if stories is not None and stories >= 1 and number_supported(stories, texts):
        out["practo"] = {"stories": int(stories), "quote": supporting_sentence(stories, texts)}
        if p_rating is not None and 0 < p_rating <= 100 and number_supported(p_rating, texts):
            out["practo"]["rating"] = float(p_rating)
    return out


def expire_old(conn: Any) -> int:
    """Grounded and Maps review numbers older than KEEP_DAYS are cleared, like Places content (A.4.4)."""
    n = conn.execute(
        """update public.businesses
              set review_count = null, rating = null, extra = extra - 'reviews_at' - 'reviews_src'
            where extra->>'reviews_src' = any(%s)
              and places_fetched_at is null
              and (extra->>'reviews_at')::timestamptz < now() - make_interval(days => %s)""",
        [list(EXPIRING_SOURCES), KEEP_DAYS],
    ).rowcount
    conn.execute(
        "delete from public.facts where field in ('google_reviews', 'practo_reviews') "
        "and (model like %s or value->>'source' = 'maps_reviews') "
        "and created_at < now() - make_interval(days => %s)",
        [f"%#{TASK}.%", KEEP_DAYS],
    )
    return int(n or 0)


def practo_covered(b: dict[str, Any], now: datetime) -> bool:
    """Research matched the clinic's Practo profile in the last KEEP_DAYS days (its numbers are facts already)."""
    at = ((b.get("extra") or {}).get("practo") or {}).get("at")
    try:
        return at is not None and (now - datetime.fromisoformat(str(at))).days < KEEP_DAYS
    except ValueError:
        return False


def _inputs(b: dict[str, Any], seg: Segment, now: datetime | None = None) -> dict[str, Any]:
    practo = seg.domain == "clinics" and seg.country == "in" and not practo_covered(b, now or datetime.now(UTC))
    return {
        "name": b["name"],
        "city": b.get("city") or "",
        "country": COUNTRY_NAMES.get(seg.country, seg.country.upper()),
        "kind": KINDS.get(seg.domain, seg.domain),
        "website": b.get("website") or "",
        "practo": practo,
    }


def store(conn: Any, b: dict[str, Any], found: dict[str, Any], tag: str, url: str | None, now: datetime) -> None:
    extra = dict(b.get("extra") or {})
    extra["reviews_lookup_at"] = now.isoformat()
    google = found.get("google")
    if google:
        extra["reviews_at"], extra["reviews_src"] = now.isoformat(), SOURCE
        conn.execute(
            "update public.businesses set review_count = %s, rating = coalesce(%s, rating), extra = %s "
            "where id = %s and places_fetched_at is null",
            [google["count"], google.get("rating"), db.Jsonb(extra), b["id"]],
        )
    else:
        conn.execute("update public.businesses set extra = %s where id = %s", [db.Jsonb(extra), b["id"]])
    for field, data in (("google_reviews", google), ("practo_reviews", found.get("practo"))):
        if not data:
            continue
        value = {k: v for k, v in data.items() if k != "quote"} | {"source": SOURCE}
        conn.execute(
            "insert into public.facts (business_id, field, value, quote, url, model, verified, verify_score, verified_at) "
            "values (%s, %s, %s, %s, %s, %s, true, 100, %s)",
            [b["id"], field, db.Jsonb(value), data.get("quote"), url, tag, now],
        )


def run(rc: RunContext, router: Any = None) -> dict[str, Any]:
    """`nlead reviews`: look up public review numbers for researched businesses without Places data."""
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    segments = score.enabled_segments(rc)
    per_day = db.get_setting(SETTING, DEFAULT_PER_DAY)
    limit = int(per_day) if isinstance(per_day, int | float) else DEFAULT_PER_DAY
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "keep": KEEP_DAYS, "limit": limit})
    stats["candidates"] = len(rows)
    if not rc.opts.dry_run:  # every morning, also when nothing needs a lookup (Maps numbers expire here too)
        with db.tx("engine", {"run_id": rc.run_id, "stage": "reviews"}) as conn:
            stats["expired"] = expire_old(conn)
    if rc.opts.dry_run or not rows:
        rc.stats["reviews"] = dict(stats)
        return dict(stats)
    router = router or ai.router_for(rc)
    run_result = getattr(router, "run_result", None) if router is not None else None
    if run_result is None:
        stats["skipped_no_router"] = len(rows)
        rc.stats["reviews"] = dict(stats)
        return dict(stats)
    budget = getattr(router, "budget", None)
    spent = 0.0
    down_streak = 0
    for b in rows:
        quota = budget.grounding_quota_left() if budget is not None and hasattr(budget, "grounding_quota_left") else 1
        if quota is not None and quota <= 0:
            stats["stopped_quota"] += 1
            break
        seg = segments[b["segment_id"]]
        try:
            inputs = _inputs(b, seg, now)
            stats["practo_covered"] += seg.domain == "clinics" and seg.country == "in" and not inputs["practo"]
            res = run_result(TASK, inputs)
        except Exception as exc:  # typed router errors: stop on budget, skip one stubborn business
            name = type(exc).__name__
            stats[f"error.{name}"] += 1
            down_streak += name == "AllProvidersDown"
            # One business whose answers never cite a search must not stop the stage (live run 12 Nov); three
            # in a row look like a real outage.
            if name in ("BudgetExceeded", "BudgetStop") or down_streak >= MAX_DOWN_STREAK:
                log.warning("reviews.stopped", reason=f"{name}: {str(exc)[:200]}")
                break
            continue
        down_streak = 0
        found = accepted(res.output, res.grounding)
        sources = (res.grounding or {}).get("sources") or []
        url = str(sources[0].get("uri")) if sources else None
        with db.tx("engine", {"run_id": rc.run_id, "stage": "reviews"}) as conn:
            store(conn, b, found, res.tag, url, now)
        stats["looked_up"] += 1
        stats["google_found"] += "google" in found
        stats["practo_found"] += "practo" in found
        spent += float(getattr(res, "inr", 0) or 0)
    result: dict[str, Any] = {**stats, "inr": round(spent, 2)}
    rc.stats["reviews"] = result
    log.info("reviews.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
