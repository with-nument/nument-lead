"""Universe builder: every business in a segment that could become a client, before any signal (Step 6.7).

Daily part (inside the night run):
1. Google listing data older than 30 days is cleared (Places terms, A.4.4).
2. Free ID-only Places searches for today's slice of localities (every locality about once in 14 days).
3. A targeted Places lookup for businesses that a signal created (a job post or news names a business we did
   not know): their listing usually gives the website and phone the research step needs.
4. Places Details, inside the daily caps, for new places and for listings older than 30 days.

Monthly part (`--monthly`): Overture places for every city box, the registries (ART for clinics in India), OSM
gaps, `new_place` signals for places new in this Overture release, and the dormant sweep.

Without `GOOGLE_MAPS_API_KEY` the daily part is skipped with a clear message; the monthly part needs no key.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from .. import db
from ..logging import get_logger
from ..normalize import city_for, match_key
from ..segments import City, Segment
from ..sources.art_registry import REGISTRY_KEY, ArtRegistryAdapter
from ..sources.base import AIRouter, Signal, SourceContext
from ..sources.osm import OsmAdapter
from ..sources.overture import NEW_PLACE_MIN_CONFIDENCE, OvertureAdapter, release_date
from ..sources.places import PlacesAdapter, PlacesApiError, QuotaReached, cleanup_expired
from .resolve import Resolver, candidate_from_record, name_score
from .runs import RunContext
from .selection import active_segments
from .signals import SignalSink

log = get_logger()

ROTATION_DAYS = 14  # every locality searched about once every 14 days (Step 6.7.2)
STALE_DAYS = 30
LOOKUP_PER_SEGMENT = 20  # targeted lookups of signal-born businesses per segment and night
LOOKUP_MIN_NAME = 85
DORMANT_AFTER_DAYS = 60


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------


def locality_slice(seg: Segment, day: int | None = None) -> list[tuple[City, str]]:
    """Today's (city, locality) pairs: ceil(n / 14) pairs, rotating through all of them every 14 days."""
    pairs = [(city, loc) for city in seg.cities for loc in city.localities]
    if not pairs:
        return []
    size = math.ceil(len(pairs) / ROTATION_DAYS)
    day = datetime.now(UTC).toordinal() if day is None else day
    start = (day % ROTATION_DAYS) * size
    return pairs[start : start + size]


def search_queries(seg: Segment, pairs: list[tuple[City, str]]) -> list[tuple[str, City]]:
    """Query strings for today's slice. City-wide templates (no {locality}) run on the day the city's first
    locality is in the slice, so they are not repeated every day."""
    out: dict[str, City] = {}
    for city, loc in pairs:
        for template in seg.places.queries:
            if "{locality}" not in template and loc != city.localities[0]:
                continue
            out.setdefault(template.format(locality=loc, city=city.name), city)
    return list(out.items())


def stale_place_ids(seg: Segment, limit: int) -> list[str]:
    """Listings to refresh: businesses in play whose Places data is older than 30 days (A.4.4)."""
    rows = db.fetch_all(
        """select place_id from public.businesses
           where segment_id = %s and place_id is not null and status in ('queued', 'researched', 'qualified')
             and (places_fetched_at is null or places_fetched_at < now() - make_interval(days => %s))
           order by places_fetched_at nulls first limit %s""",
        [seg.id, STALE_DAYS, limit],
    )
    return [r["place_id"] for r in rows]


def signal_born(seg: Segment, limit: int) -> list[dict[str, Any]]:
    """Businesses created from a signal that have no listing yet and were never looked up."""
    return db.fetch_all(
        """select id::text as id, name, city, locality from public.businesses
           where segment_id = %s and place_id is null and extra ? 'born_from'
             and not extra ? 'places_lookup_at' and status in ('candidate', 'queued')
           order by created_at desc limit %s""",
        [seg.id, limit],
    )


def dormant_sweep(seg: Segment, previous_release: str) -> int:
    """Step 6.6.6: missing from two consecutive Overture releases and unseen by any source for 60 days."""
    return db.execute(
        """update public.businesses b set status = 'dormant'
           where b.segment_id = %(seg)s and b.status in ('candidate', 'queued', 'researched', 'rejected')
             and b.last_seen_at < now() - make_interval(days => %(days)s)
             and exists (select 1 from public.source_records s where s.business_id = b.id and s.source = 'overture')
             and not exists (select 1 from public.source_records s where s.business_id = b.id
                             and s.source = 'overture' and s.payload->>'release' >= %(prev)s)""",
        {"seg": seg.id, "days": DORMANT_AFTER_DAYS, "prev": previous_release},
    )


def segment_has_release(seg: Segment, release: str) -> bool:
    return bool(
        db.scalar(
            """select exists (select 1 from public.source_records s join public.businesses b on b.id = s.business_id
                              where s.source = 'overture' and s.payload->>'release' = %s and b.segment_id = %s)""",
            [release, seg.id],
        )
    )


# ---------------------------------------------------------------------------------------------------
# Daily part (Places)
# ---------------------------------------------------------------------------------------------------


async def daily_part(
    seg: Segment, places: PlacesAdapter, resolver: Resolver, sink: SignalSink, ctx: SourceContext, s: Counter[str]
) -> None:
    usable, why = places.status()
    if not usable:
        if not places.has_key():
            places.report_missing_key()
        s["places_skipped"] += 1
        ctx.stats.setdefault("skip_reasons", {})["places"] = why
        return
    resolver.load()
    try:
        await _daily_places(seg, places, resolver, sink, ctx, s)
    except PlacesApiError as err:
        places.handle_api_error(err)
        s["places_api_errors"] += 1
        return
    places.health_ok()


async def _daily_places(
    seg: Segment, places: PlacesAdapter, resolver: Resolver, sink: SignalSink, ctx: SourceContext, s: Counter[str]
) -> None:
    new_ids: list[str] = []
    seen: set[str] = set()
    for query, city in search_queries(seg, locality_slice(seg)):
        for pid in await places.search_ids(query, seg, city.bbox):
            if pid in seen:
                continue
            seen.add(pid)
            known = resolver.records.get(("places", pid)) or resolver.by_place.get(pid)
            if known:
                resolver.touch([known])
                s["places_seen_again"] += 1
            else:
                new_ids.append(pid)
        if ctx.limit and len(new_ids) >= ctx.limit:
            break
    s["places_new_ids"] += len(new_ids)

    # Targeted lookups for signal-born businesses (they carry a need, so they come first).
    for biz in signal_born(seg, LOOKUP_PER_SEGMENT):
        home_city = next((c for c in seg.cities if c.name == biz["city"]), None)
        if home_city is None:
            continue
        query = f"{biz['name']} {biz.get('locality') or ''} {home_city.name}".strip()
        ids = await places.search_ids(query, seg, home_city.bbox)
        resolver.set_extra(biz["id"], "places_lookup_at", resolver.now.isoformat())
        if not ids or ids[0] in resolver.by_place:
            continue
        try:
            data = await places.details(ids[0], seg)
        except QuotaReached:
            s["places_quota_reached"] += 1
            return
        s["places_details"] += 1
        rec = places.to_record(data, seg, home_city.name)
        cand = candidate_from_record(rec, seg) if rec else None
        if cand and name_score(match_key(biz["name"]), match_key(cand.name)) >= LOOKUP_MIN_NAME:
            resolver.attach(biz["id"], cand)
            s["signal_born_found"] += 1

    queue = list(dict.fromkeys(new_ids + stale_place_ids(seg, seg.places.details_per_day)))
    for pid in queue:
        try:
            data = await places.details(pid, seg)
        except QuotaReached:
            s["places_quota_reached"] += 1
            break
        s["places_details"] += 1
        loc = data.get("location") or {}
        city_name = city_for(loc.get("latitude"), loc.get("longitude"), data.get("formattedAddress"), seg.cities)
        rec = places.to_record(data, seg, city_name)
        cand = candidate_from_record(rec, seg) if rec else None
        if cand is None:
            continue
        result = resolver.resolve(cand)
        if result and result[1] == "branch":
            # A new listing whose website belongs to a business we know: a new branch (Step 7.5.8).
            sink.add(
                Signal(
                    type="new_branch",
                    source="places",
                    observed_at=datetime.now(UTC),
                    url=None,
                    quote=f"New Google listing: {cand.name}, {cand.locality or cand.city or ''}".strip(" ,"),
                    evidence_key=pid,
                    business_id=result[0],
                    details={"date_estimated": True, "event_key": f"growth:{datetime.now(UTC):%Y-%m}"},
                ),
                seg,
            )


# ---------------------------------------------------------------------------------------------------
# Monthly part (Overture, registries, OSM)
# ---------------------------------------------------------------------------------------------------


async def guarded(adapter: Any, s: Counter[str], fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run one adapter call; an unexpected error is recorded on the source and the stage goes on."""
    try:
        return await adapter.safe_call(fn, *args, **kwargs)
    except Exception as exc:  # a broken source must not stop the other sources of the month
        s[f"{adapter.name}_errors"] += 1
        adapter.health_error(f"{type(exc).__name__}: {str(exc)[:300]}")
        log.error("universe.source_failed", source=adapter.name, error=f"{type(exc).__name__}: {str(exc)[:300]}")
        return None


async def monthly_part(
    seg: Segment,
    adapters: dict[str, Any],
    resolver: Resolver,
    sink: SignalSink,
    ctx: SourceContext,
    s: Counter[str],
    release: str | None,
    previous: str | None,
) -> None:
    overture: OvertureAdapter = adapters["overture"]
    if release and segment_has_release(seg, release):
        s["overture_already_done"] += 1
    elif release:
        records = await guarded(overture, s, overture.pull, seg, release, limit=ctx.limit)
        prev_ids = None
        if records and previous and previous != release:
            prev_ids = await guarded(overture, s, overture.ids, seg, previous)
        for rec in records or []:
            cand = candidate_from_record(rec, seg)
            result = resolver.resolve(cand) if cand else None
            if result is None:
                continue
            s[f"overture_{result[1]}"] += 1
            confidence = float(rec.payload.get("confidence") or 0)
            if (
                result[1] == "created"
                and prev_ids is not None
                and rec.overture_id not in prev_ids
                and confidence >= NEW_PLACE_MIN_CONFIDENCE
            ):
                sink.add(
                    Signal(
                        type="new_place",
                        source="overture",
                        observed_at=release_date(release),
                        url=rec.website,
                        quote=f"New in Overture release {release}: {rec.name}, {rec.locality or rec.city}",
                        evidence_key=str(rec.overture_id),
                        business_id=result[0],
                        details={"release": release, "confidence": confidence, "event_key": f"growth:{release[:7]}"},
                    ),
                    seg,
                )
                s["new_place"] += 1
        if previous and not ctx.dry_run:
            resolver.flush()
            s["dormant"] += dormant_sweep(seg, previous)

    for entry in seg.registries:
        if entry.key != REGISTRY_KEY or entry.status != "ready":
            continue
        art: ArtRegistryAdapter = adapters["art_registry"]
        for rec in await guarded(art, s, art.pull, seg, limit=ctx.limit) or []:
            cand = candidate_from_record(rec, seg)
            result = resolver.resolve(cand) if cand else None
            if result:
                s[f"registry_{result[1]}"] += 1

    if seg.osm.enabled:
        osm: OsmAdapter = adapters["osm"]
        for rec in await guarded(osm, s, osm.pull, seg, limit=ctx.limit) or []:
            cand = candidate_from_record(rec, seg)
            result = resolver.resolve(cand) if cand else None
            if result:
                s[f"osm_{result[1]}"] += 1


# ---------------------------------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------------------------------


async def build(ctx: SourceContext, segments: dict[str, Segment], monthly: bool) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    if not ctx.dry_run:
        stats["places_cleanup"] = cleanup_expired()
    sink = SignalSink(segments, ctx)
    adapters: dict[str, Any] = {
        "places": PlacesAdapter(ctx),
        "overture": OvertureAdapter(ctx),
        "art_registry": ArtRegistryAdapter(ctx),
        "osm": OsmAdapter(ctx),
    }
    release: str | None = None
    previous: str | None = None
    try:
        if monthly:
            overture: OvertureAdapter = adapters["overture"]
            if overture.enabled():
                boot: Counter[str] = Counter()
                release = await guarded(overture, boot, overture.latest_release)
                processed = db.get_setting("overture_release")
                available = await guarded(overture, boot, overture.releases) or []
                previous = processed if isinstance(processed, str) and processed in available else None
                stats["overture_release"] = release
        for seg in segments.values():
            s: Counter[str] = Counter()
            resolver = Resolver(seg, dry_run=ctx.dry_run)
            if monthly:
                await monthly_part(seg, adapters, resolver, sink, ctx, s, release, previous)
            await daily_part(seg, adapters["places"], resolver, sink, ctx, s)
            resolver.flush()
            s.update({f"resolve.{k}": v for k, v in resolver.stats.items()})
            stats[seg.id] = dict(s)
        stats["signals"] = sink.flush()
        if monthly and release and not ctx.dry_run:
            db.set_setting("overture_release", release)
    finally:
        for adapter in adapters.values():
            await adapter.aclose()
    return stats


def run(rc: RunContext, monthly: bool = False, *, router: AIRouter | None = None) -> dict[str, Any]:
    """Build or refresh the universe; `monthly` adds Overture, registries, OSM and the release diff."""
    ctx = SourceContext.from_run(rc, router)
    segments = active_segments(rc.opts.segments)
    stats = asyncio.run(build(ctx, segments, monthly))
    stats.update({k: v for k, v in ctx.stats.items() if k not in stats})
    if ctx.alerts:
        rc.stats.setdefault("alerts", []).extend(ctx.alerts)
    rc.stats["universe"] = stats
    log.info("universe.done", monthly=monthly, segments=list(segments))
    return stats


def incremental(rc: RunContext, **kwargs: Any) -> dict[str, Any]:
    """The night run's daily part (the name Step 14.4.2 uses)."""
    return run(rc, monthly=False, **kwargs)


def refresh(rc: RunContext, monthly: bool = True, **kwargs: Any) -> dict[str, Any]:
    """The monthly full refresh (the name Step 14.4.2 uses)."""
    return run(rc, monthly=monthly, **kwargs)
