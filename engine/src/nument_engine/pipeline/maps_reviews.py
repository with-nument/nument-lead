"""Google Maps review numbers and review pain for tonight's businesses without Places data (night, after the
batch submission).

Who: businesses queued or researched in the last day, with no Places data and no Maps lookup in the last 30 days,
the ones crawled tonight first. How many: `maps_reviews.lookups_per_day` a day (default 100) and at most
`maps_reviews.minutes_per_run` minutes (default 4, about 40 lookups), so the night job stays inside the free
Actions minutes (Step 14.6). The source itself (`sources/maps_reviews.py`) holds the rules for the pages.

What is stored, the way `pipeline/reviews.py` stores grounded numbers:
- a confirmed listing's rating and review count go to `businesses.rating` and `review_count`, never over Places
  data, with `extra.reviews_at` and `extra.reviews_src = 'maps_reviews'`; `reviews.expire_old` clears them after
  30 days, like Places content;
- one verified `google_reviews` fact (value `{count, rating, source: maps_reviews}`, the listing URL);
- `extra.maps_reviews` records every lookup (when, the listing URL, how it was confirmed, or why not), so the
  morning's grounded lookup skips a business Maps already covered;
- recent reviews that complain about calls, replies, booking, waits or the front desk become `review_pain` with
  one quoted sentence and the listing URL. Review texts are not stored.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final

from psycopg.types.json import Jsonb

from .. import db
from ..logging import get_logger
from ..sources import health, review_pain
from ..sources.base import AIRouter, SourceContext
from ..sources.maps_reviews import (
    DEFAULT_MINUTES,
    DEFAULT_PER_DAY,
    SETTING_MINUTES,
    SETTING_PER_DAY,
    Lookup,
    MapsReviewsAdapter,
)
from .runs import RunContext
from .selection import active_segments
from .signals import SignalSink

log = get_logger()

SOURCE: Final = "maps_reviews"
KEEP_DAYS: Final = 30
MAX_FAILURES: Final = 3

CANDIDATES_SQL: Final = """
select b.id::text as id, b.segment_id, b.name, b.city, b.locality, b.address, b.lat, b.lng, b.website,
       b.web_domain, b.extra
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.places_fetched_at is null
   and ((b.status = 'queued' and b.queued_at > now() - interval '1 day')
        or (b.status = 'researched' and b.researched_at > now() - interval '1 day'))
   and coalesce((b.extra #>> '{maps_reviews,at}')::timestamptz, 'epoch') < now() - make_interval(days => %(keep)s)
 order by coalesce((b.extra #>> '{crawl,at}')::timestamptz, 'epoch') > now() - interval '1 day' desc,
          b.queue_priority desc nulls last
 limit %(limit)s
"""

LOOKUPS_TODAY_SQL: Final = """
select count(*) from public.businesses
 where (extra #>> '{maps_reviews,at}')::timestamptz >= %(since)s
"""


def lookups_left(conn: Any = None) -> int:
    """Today's lookups still allowed (the day is the IST day, like every other daily cap)."""
    cap = health.setting_int(SETTING_PER_DAY, DEFAULT_PER_DAY, conn=conn)
    done = int(db.scalar(LOOKUPS_TODAY_SQL, {"since": health.ist_day_start()}, conn=conn) or 0)
    return max(0, cap - done)


def store(conn: Any, b: dict[str, Any], found: Lookup, now: datetime) -> None:
    """Numbers, fact and lookup record for one business, in the caller's transaction."""
    listing = found.listing
    record: dict[str, Any] = {"at": now.isoformat(), "matched": found.how is not None}
    if listing is not None:
        record["url"] = listing.url[:500]
    if found.how is None:
        record["why"] = found.why
    else:
        record |= {"how": found.how, "count": listing.review_count, "rating": listing.rating} if listing else {}
    extra = dict(b.get("extra") or {})
    extra["maps_reviews"] = record
    if found.how is not None and listing is not None and listing.review_count:
        extra["reviews_at"], extra["reviews_src"] = now.isoformat(), SOURCE
        conn.execute(
            "update public.businesses set review_count = %s, rating = coalesce(%s, rating), extra = %s "
            "where id = %s and places_fetched_at is null",
            [listing.review_count, listing.rating, Jsonb(extra), b["id"]],
        )
        stars = f"{listing.rating:.1f} stars, " if listing.rating else ""
        conn.execute(
            "insert into public.facts (business_id, field, value, quote, url, model, verified, verify_score, "
            "verified_at) values (%s, 'google_reviews', %s, %s, %s, 'rule', true, 100, %s)",
            [
                b["id"],
                Jsonb({"count": listing.review_count, "rating": listing.rating, "source": SOURCE}),
                f"{stars}{listing.review_count} reviews on Google Maps",
                listing.url[:500],
                now,
            ],
        )
    else:
        conn.execute("update public.businesses set extra = %s where id = %s", [Jsonb(extra), b["id"]])


async def lookup_all(
    ctx: SourceContext,
    rows: list[dict[str, Any]],
    segments: dict[str, Any],
    *,
    adapter: MapsReviewsAdapter | None = None,
    seconds: float | None = None,
) -> Counter[str]:
    """One lookup at a time until the rows, the time or the source (a block) run out."""
    stats: Counter[str] = Counter()
    sink = SignalSink(segments, ctx)
    maps = adapter or MapsReviewsAdapter(ctx)
    started = time.monotonic()
    failures = 0
    try:
        for b in rows:
            if seconds is not None and time.monotonic() - started > seconds:
                stats["stopped_time"] += 1
                break
            if not maps.enabled():
                stats["stopped_source"] += 1
                break
            try:
                found = await maps.safe_call(maps.lookup, b)
            except Exception as exc:  # a page that breaks (a timeout, a changed layout) skips one business
                stats["errors"] += 1
                failures += 1
                message = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.warning("maps_reviews.lookup_failed", error=message)
                if failures >= MAX_FAILURES:  # no browser, or Maps changed its page: stop and say so
                    health.mark_error(SOURCE, f"{failures} lookups in a row failed; last: {message}")
                    ctx.alert(f"maps_reviews stopped after {failures} failed lookups in a row ({message[:120]})")
                    break
                continue
            failures = 0
            if found is None:  # blocked: safe_call paused the source
                stats["blocked"] += 1
                break
            now = datetime.now(UTC)
            stats["looked_up"] += 1
            stats["matched" if found.how else "not_matched"] += 1
            if not ctx.dry_run:
                with db.tx("engine", {"run_id": ctx.run_id, "stage": SOURCE}) as conn:
                    store(conn, b, found, now)
            if found.how is None or found.listing is None:
                continue
            stats["with_count"] += bool(found.listing.review_count)
            seg = segments[b["segment_id"]]
            pain = review_pain.classify(ctx, found.listing.reviews, business_name=str(b["name"]), source=SOURCE)
            if pain is not None:
                sink.add(
                    review_pain.pain_signal(pain, source=SOURCE, business_id=b["id"], url=found.listing.url, seg=seg),
                    seg,
                )
                stats["review_pain"] += 1
    finally:
        await maps.aclose()
    sink.flush()
    return stats


def run(rc: RunContext, *, router: AIRouter | None = None, adapter: MapsReviewsAdapter | None = None) -> dict[str, Any]:
    """`nlead maps-reviews`: Google Maps numbers and review pain for tonight's businesses without Places data."""
    ctx = SourceContext.from_run(rc, router)
    stats: dict[str, Any] = {}
    usable, why = health.source_status(SOURCE)
    if not usable:
        stats["skipped"] = why
        rc.stats["maps_reviews"] = stats
        return stats
    segments = active_segments(rc.opts.segments)
    limit = lookups_left()
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "keep": KEEP_DAYS, "limit": limit})
    stats["candidates"] = len(rows)
    if not rows:
        rc.stats["maps_reviews"] = stats
        return stats
    minutes = health.setting_int(SETTING_MINUTES, DEFAULT_MINUTES)
    seconds = min(minutes * 60.0, max(0.0, rc.time_left() - 60.0))
    stats.update(asyncio.run(lookup_all(ctx, rows, segments, adapter=adapter, seconds=seconds)))
    stats.update({k: v for k, v in ctx.stats.items() if k not in stats and not isinstance(v, dict)})
    if ctx.alerts:
        rc.stats.setdefault("alerts", []).extend(ctx.alerts)
    rc.stats["maps_reviews"] = stats
    log.info("maps_reviews.done", **{k.replace(".", "_"): v for k, v in stats.items() if not isinstance(v, dict)})
    return stats
