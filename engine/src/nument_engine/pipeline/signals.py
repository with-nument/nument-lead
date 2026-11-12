"""Signal watchers: dated evidence that a business needs help now (Step 7).

Every watcher returns `Signal` objects. This module turns them into `signals` rows: category and points from
A.12.3 (segment overrides first), `expires_at` from the freshness window, a stable `dedupe_key`, and a business:
the watcher's own `business_id`, or one found or created by entity resolution from the signal's hint (7.4.6).
Writing is an upsert on `dedupe_key`, so running the stage twice adds nothing.

Watchers, cheapest first: careers and locations pages, the founder's inbox, Google review pain, Apna jobs,
GDELT news, grounded search public asks, Adzuna (optional). Each runs behind its kill switch; a block pauses
only that source and the run goes on.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .. import db
from ..logging import get_logger
from ..models import SOURCE_NAMES
from ..normalize import canonical_url, city_for_text, clean_text
from ..segments import Segment
from ..sources import health
from ..sources.adzuna import AdzunaAdapter
from ..sources.apna import ApnaAdapter
from ..sources.base import (
    CATEGORY,
    DEFAULT_POINTS,
    QUOTE_MAX,
    WINDOW_DAYS,
    AIRouter,
    Signal,
    SourceContext,
    field_of,
)
from ..sources.careers_watch import CareersWatchAdapter
from ..sources.gdelt import GdeltAdapter
from ..sources.grounded_search import GroundedSearchAdapter
from ..sources.jobs import DOMAIN_MAP, MIN_CONFIDENCE
from ..sources.places import PlacesAdapter, QuotaReached, listing_url, review_flags
from .resolve import Candidate, Resolver, candidate_from_hint
from .runs import RunContext
from .selection import active_segments

__all__ = [
    "CATEGORY",
    "DEFAULT_POINTS",
    "WINDOW_DAYS",
    "Signal",
    "SignalSink",
    "canonical_url",
    "dedupe_key",
    "run",
    "to_row",
]

log = get_logger()

REVIEW_RECHECK_DAYS = 30
INBOX_BATCH = 50

UPSERT_SIGNAL_SQL = """
insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, url, quote,
                            details, dedupe_key)
values (%(business_id)s, %(type)s, %(category)s, %(points)s, %(observed_at)s, %(expires_at)s,
        %(source)s, %(url)s, %(quote)s, %(details)s, %(dedupe_key)s)
on conflict (dedupe_key) do update
   set observed_at = greatest(signals.observed_at, excluded.observed_at),
       expires_at  = greatest(signals.expires_at,  excluded.expires_at),
       details     = signals.details || excluded.details
"""


# ---------------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------------


def dedupe_key(sig: Signal, business_key: str) -> str:
    """sha1 of type | business | evidence (Step 7.4.3). Stable across runs, so re-runs upsert."""
    return hashlib.sha1(f"{sig.type}|{business_key}|{sig.evidence_key}".encode()).hexdigest()


def points_for(sig: Signal, seg: Segment) -> float:
    if sig.points is not None:
        return float(sig.points)
    return float(seg.signal_points.get(sig.type, DEFAULT_POINTS[sig.type]))  # type: ignore[call-overload]


def to_row(sig: Signal, business_id: str, seg: Segment, now: datetime | None = None) -> dict[str, Any] | None:
    """The `signals` row for a linked signal, or None when it is already expired (never stored, 7.4.2)."""
    now = now or datetime.now(UTC)
    observed = sig.observed_at if sig.observed_at.tzinfo else sig.observed_at.replace(tzinfo=UTC)
    if sig.type == "tender":
        if sig.deadline is None:
            return None
        expires = sig.deadline
    else:
        window = sig.window()
        assert window is not None
        expires = observed + window
    if expires <= now or expires <= observed:
        return None
    quote = clean_text(sig.quote, QUOTE_MAX) if sig.quote else None
    return {
        "business_id": business_id,
        "type": sig.type,
        "category": CATEGORY[sig.type],
        "points": points_for(sig, seg),
        "observed_at": observed,
        "expires_at": expires,
        "source": sig.source,
        "url": sig.url,
        "quote": quote if quote and len(quote) >= 5 else None,
        "details": Jsonb(sig.details),
        "dedupe_key": dedupe_key(sig, business_id),
    }


class SignalSink:
    """Collects signals, links them to businesses (one resolver per segment) and writes them in one go."""

    def __init__(self, segments: dict[str, Segment], ctx: SourceContext) -> None:
        self.segments = segments
        self.ctx = ctx
        self.resolvers: dict[str, Resolver] = {}
        self.pending: list[tuple[Signal, str, str]] = []  # (signal, segment id, business id)
        self.stats: dict[str, Counter[str]] = {}

    def resolver(self, seg: Segment) -> Resolver:
        if seg.id not in self.resolvers:
            self.resolvers[seg.id] = Resolver(seg, dry_run=self.ctx.dry_run)
        return self.resolvers[seg.id]

    def _count(self, seg_id: str, key: str) -> None:
        self.stats.setdefault(seg_id, Counter())[key] += 1

    def link(self, sig: Signal, seg: Segment) -> str | None:
        if sig.business_id:
            return sig.business_id
        hint = sig.business_hint
        city_ok = bool(hint.get("city")) and any(c.name == hint.get("city") for c in seg.cities)
        if not city_ok and not hint.get("website"):
            self._count(seg.id, "unlinked")  # Step 7.4.6 rule 3: no city in the segment and no website
            return None
        source = sig.source if sig.source in SOURCE_NAMES else "inbox"
        cand: Candidate | None = candidate_from_hint(source, sig.evidence_key, hint, seg)
        if cand is None:
            self._count(seg.id, "unlinked")
            return None
        result = self.resolver(seg).resolve(cand)
        if result is None:
            self._count(seg.id, "unlinked")
            return None
        bid, action = result
        if action == "created":
            self._count(seg.id, "businesses_created")
        return bid

    def add(self, sig: Signal, seg: Segment) -> None:
        target = self.segments.get(sig.segment_id or seg.id)
        if target is None:
            self._count(seg.id, "segment_disabled")
            return
        bid = self.link(sig, target)
        if bid is not None:
            self.pending.append((sig, target.id, bid))

    def flush(self) -> dict[str, dict[str, int]]:
        """Write businesses created by signals, then the signal rows. Returns counts per segment and type."""
        for resolver in self.resolvers.values():
            resolver.flush()
        rows: dict[str, dict[str, Any]] = {}
        now = datetime.now(UTC)
        for sig, seg_id, bid in self.pending:
            row = to_row(sig, bid, self.segments[seg_id], now)
            if row is None:
                self._count(seg_id, "expired_dropped")
                continue
            rows[row["dedupe_key"]] = row
            self._count(seg_id, sig.type)
        if rows and not self.ctx.dry_run:
            with db.tx() as conn, conn.cursor() as cur:
                cur.executemany(UPSERT_SIGNAL_SQL, list(rows.values()))
        self.pending.clear()
        return {k: dict(v) for k, v in self.stats.items()}


# ---------------------------------------------------------------------------------------------------
# Watchers
# ---------------------------------------------------------------------------------------------------


async def careers_watch_run(ctx: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
    async with CareersWatchAdapter(ctx) as adapter:
        sigs = await adapter.safe_call(adapter.watch, list(segments), limit=ctx.limit)
        for sig in sigs or []:
            seg_id = db.scalar("select segment_id from public.businesses where id = %s", [sig.business_id])
            if seg_id in segments:
                sink.add(sig, segments[seg_id])


def _inbox_segment(post: dict[str, Any], result: Any, segments: dict[str, Segment]) -> Segment | None:
    if post.get("segment_id") in segments:
        return segments[post["segment_id"]]
    domain = DOMAIN_MAP.get(str(field_of(result, "employer_domain") or ""))
    city_text = str(field_of(result, "city") or "")
    same_domain = [s for s in segments.values() if s.domain == domain]
    for seg in same_domain:
        if city_for_text(city_text, seg.cities):
            return seg
    return same_domain[0] if len(same_domain) == 1 else None


async def inbox_posts_watch(ctx: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
    """Posts the founder pasted into the app (LinkedIn, X): classified like public asks, never fetched."""
    posts = db.fetch_all(
        "select id::text as id, url, text, segment_id, created_at from public.inbox_posts "
        "where status = 'new' order by created_at limit %s",
        [ctx.limit or INBOX_BATCH],
    )
    for post in posts:
        default = segments.get(post.get("segment_id") or "") or next(iter(segments.values()), None)
        if default is None:
            return
        result = ctx.ai(
            "classify_signal",
            {
                "segment_id": default.id,
                "domain": default.domain,
                "country": default.country,
                "source": "inbox",
                "url": post.get("url"),
                "posted_date": post["created_at"].date().isoformat(),
                "title": "",
                "employer_name": None,
                "address": None,
                "mode": "public_ask",
                "text": post["text"][:3000],
            },
        )
        if result is None:
            if ctx.ai_stopped:
                return
            continue
        relevant = (
            bool(field_of(result, "is_relevant")) and float(field_of(result, "confidence") or 0) >= MIN_CONFIDENCE
        )
        relevant = relevant and field_of(result, "employer_domain") != "agency_or_staffing"
        seg = _inbox_segment(post, result, segments) if relevant else None
        status = "rejected"
        if seg is not None:
            text = clean_text(post["text"])
            quote = str(field_of(result, "evidence_quote") or "")
            sig = Signal(
                type="public_ask",
                source="inbox",
                observed_at=post["created_at"],
                url=post.get("url"),
                quote=quote if quote and quote.lower() in text.lower() else text[:QUOTE_MAX],
                evidence_key=canonical_url(post["url"]) if post.get("url") else f"inbox:{post['id']}",
                business_hint={
                    "name": field_of(result, "employer_name"),
                    "city": city_for_text(str(field_of(result, "city") or ""), seg.cities),
                    "website": field_of(result, "employer_website")
                    if field_of(result, "employer_website") and str(field_of(result, "employer_website")) in text
                    else None,
                },
                details={"inbox_post_id": post["id"], "pasted": True, "date_estimated": True},
            )
            sink.add(sig, seg)
            status = "processing"
        if not ctx.dry_run:
            db.execute("update public.inbox_posts set status = %s where id = %s", [status, post["id"]])
        ctx.add(f"inbox.{status}")


async def review_pain_watch(ctx: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
    """Google reviews of businesses being researched today and of open leads (Step 7.5.5). No text is kept."""
    async with PlacesAdapter(ctx) as places:
        usable, why = places.status()
        if not usable:
            if not places.has_key():
                places.report_missing_key()
            ctx.stats.setdefault("skip_reasons", {})["places_reviews"] = why
            return
        for seg in segments.values():
            rows = db.fetch_all(
                """select b.id::text as id, b.place_id from public.businesses b
                   where b.segment_id = %(seg)s and b.place_id is not null
                     and (b.status = 'queued'
                          or (b.status in ('researched', 'qualified')
                              and exists (select 1 from public.leads l where l.business_id = b.id
                                          and l.stage <> all(%(closed)s))))
                     and coalesce((b.extra->>'reviews_checked_at')::timestamptz, 'epoch') < %(since)s
                   order by b.queue_priority desc nulls last limit %(limit)s""",
                {
                    "seg": seg.id,
                    "closed": ["won", "retainer", "lost", "not_now", "not_a_fit", "wrong_contact"],
                    "since": datetime.now(UTC) - timedelta(days=REVIEW_RECHECK_DAYS),
                    "limit": min(seg.places.reviews_per_day, ctx.limit or seg.places.reviews_per_day),
                },
            )
            for row in rows:
                try:
                    reviews = await places.reviews(row["place_id"], seg)
                except QuotaReached:
                    ctx.add("places_reviews.quota_reached")
                    break
                found = review_flags(reviews)
                if not ctx.dry_run:
                    db.execute(
                        "update public.businesses set extra = jsonb_set(extra, '{reviews_checked_at}', to_jsonb(now())) "
                        "where id = %s",
                        [row["id"]],
                    )
                if found is None:
                    continue
                base = float(seg.signal_points.get("review_pain", DEFAULT_POINTS["review_pain"]))
                points = min(base + 1, max(base, 7.0)) if found["matching_reviews"] >= 2 else base
                newest = found.get("newest_flag_age_days")
                observed = datetime.now(UTC) - timedelta(days=int(newest or 0))
                sink.add(
                    Signal(
                        type="review_pain",
                        source="places",
                        observed_at=observed,
                        url=listing_url(row["place_id"]),
                        quote=None,  # Google terms: never store review text (A.4.4)
                        evidence_key=f"{row['place_id']}|{datetime.now(UTC):%Y-%m}",
                        business_id=row["id"],
                        details={**found, **({"date_estimated": True} if newest is None else {})},
                        points=points,
                    ),
                    seg,
                )
            places.health_ok()


async def apna_watch(ctx: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
    async with ApnaAdapter(ctx) as adapter:
        sigs = await adapter.safe_call(adapter.signals_for, segments, limit=ctx.limit)
        for sig in sigs or []:
            seg = segments.get(sig.segment_id or "")
            if seg is not None:
                sink.add(sig, seg)


async def adzuna_watch(ctx: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
    if not any(s.adzuna_enabled for s in segments.values()):
        return
    async with AdzunaAdapter(ctx) as adapter:
        sigs = await adapter.safe_call(adapter.signals_for, segments, limit=ctx.limit)
        for sig in sigs or []:
            if sig.segment_id in segments:
                sink.add(sig, segments[sig.segment_id or ""])


async def gdelt_watch(ctx: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
    async with GdeltAdapter(ctx) as adapter:
        left = adapter.queries_left(list(segments.values()))
        for seg in segments.values():
            if left <= 0 or adapter.rate_limited:
                break
            budget = min(left, len(seg.news_queries))
            sigs = await adapter.safe_call(adapter.signals_for, seg, budget=budget, limit=ctx.limit)
            left -= budget
            for sig in sigs or []:
                sink.add(sig, seg)


async def grounded_public_asks(ctx: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
    if ctx.dry_run:
        ctx.add("grounded_search.skipped_dry_run")  # paid search: never in a dry run (Step 14.4.3)
        return
    async with GroundedSearchAdapter(ctx) as adapter:
        for seg in segments.values():
            left = adapter.calls_left()
            if left <= 0 or ctx.ai_stopped:
                break
            sigs = await adapter.safe_call(adapter.signals_for, seg, budget=left, limit=ctx.limit)
            for sig in sigs or []:
                sink.add(sig, seg)


Watcher = Callable[[SourceContext, dict[str, Segment], SignalSink], Awaitable[None]]
WATCHERS: tuple[tuple[str, Watcher], ...] = (
    ("careers_watch", careers_watch_run),
    ("inbox", inbox_posts_watch),
    ("places", review_pain_watch),
    ("apna", apna_watch),
    ("gdelt", gdelt_watch),
    ("grounded_search", grounded_public_asks),
    ("adzuna", adzuna_watch),
)


async def run_watchers(
    ctx: SourceContext,
    segments: dict[str, Segment],
    sink: SignalSink,
    watchers: tuple[tuple[str, Watcher], ...] | None = None,
) -> None:
    for name, watcher in WATCHERS if watchers is None else watchers:
        try:
            await watcher(ctx, segments, sink)
        except Exception as exc:  # one broken watcher never stops the others (Step 7.7)
            ctx.add(f"errors.{name}")
            message = f"{type(exc).__name__}: {str(exc)[:300]}"
            if name in SOURCE_NAMES:
                health.mark_error(name, message)
            log.error("signals.watcher_failed", watcher=name, error=message)


def run(rc: RunContext, *, router: AIRouter | None = None) -> dict[str, Any]:
    """Run every enabled signal watcher for the run's segments and store the signals."""
    ctx = SourceContext.from_run(rc, router)
    segments = active_segments(rc.opts.segments)
    sink = SignalSink(segments, ctx)
    asyncio.run(run_watchers(ctx, segments, sink))
    counts = sink.flush()
    stats: dict[str, Any] = {"by_segment": counts, **ctx.stats}
    if ctx.alerts:
        rc.stats.setdefault("alerts", []).extend(ctx.alerts)
    if ctx.ai_stopped:
        rc.stats.setdefault("ai_stopped", {})["signals"] = ctx.ai_stopped
    rc.stats["signals"] = stats
    log.info("signals.done", **{k: v for k, v in stats.items() if k != "skip_reasons"})
    return stats
