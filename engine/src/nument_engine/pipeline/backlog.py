"""The startup backlog (15 Nov 2026): the startup sources read backwards once (`nlead run backlog`, backlog.yml).

The backlog only finds startups and links them to businesses, with their signals; research, probes and scoring
happen in the nightly runs, within their usual quotas. Each source runs its own `backlog(ctx, segments, sink,
run)` pass with a `sources.rss.Pass` of `backlog.days` (60) days and `backlog.items_per_source` (500) AI items,
outside the nightly allowances:

- funding_rss: older pages of the feeds that allow it, and GDELT week by week;
- hn_launches, betalist, startup_lists: their last 30 days (a launch is news for 30 days, so older items would
  only add businesses without a live signal);
- a source without a `backlog` pass (sec_edgar and ats_jobs until they add one) is skipped and named in the stats.

Stops: no new work after the run's deadline (280 minutes, `runs.DEADLINE_MIN`), less a margin to write what was
found; AI work stops when the day's spend reaches the `low_priority_research` share of the daily cap. Signals are
written after each source, so a run that ends early keeps what the finished sources found.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from types import ModuleType
from typing import Any

from .. import db
from ..logging import get_logger
from ..sources import health
from ..sources.base import AIRouter, SourceContext
from ..sources.rss import BACKLOG_BUDGET_PHASE, Pass
from .runs import RunContext
from .selection import active_segments
from .signals import SignalSink

log = get_logger()

SOURCES: tuple[str, ...] = ("funding_rss", "hn_launches", "betalist", "startup_lists", "sec_edgar", "ats_jobs")
DEFAULT_DAYS = 60
DEFAULT_ITEMS = 500
WRITE_MARGIN_S = 300.0  # the last five minutes before the deadline are kept for writing


def load(name: str) -> ModuleType:
    """The source module `sources/<name>.py`."""
    return importlib.import_module(f"nument_engine.sources.{name}")


def _stop_at(rc: RunContext) -> float | None:
    left = rc.time_left()
    return None if left == float("inf") else time.monotonic() + left - WRITE_MARGIN_S


async def _run_sources(rc: RunContext, ctx: SourceContext, days: int, items: int) -> dict[str, Any]:
    segments = active_segments(rc.opts.segments)
    stop_at = _stop_at(rc)
    out: dict[str, Any] = {}
    for name in SOURCES:
        if stop_at is not None and time.monotonic() >= stop_at:
            out[name] = {"skipped": "deadline"}
            continue
        if not ctx.budget.allow_phase(BACKLOG_BUDGET_PHASE):
            out[name] = {"skipped": "budget"}
            continue
        usable, why = health.source_status(name)
        if not usable:
            out[name] = {"skipped": why}
            continue
        backlog = getattr(load(name), "backlog", None)
        if backlog is None:
            out[name] = {"skipped": "no backlog pass"}
            continue
        cap = min(items, ctx.limit) if ctx.limit else items
        sink = SignalSink(segments, ctx)
        started = time.monotonic()
        try:
            await backlog(ctx, segments, sink, Pass(days=days, cap=cap, backlog=True, stop_at=stop_at))
        except Exception as exc:  # one broken source never stops the others
            message = f"{type(exc).__name__}: {str(exc)[:300]}"
            ctx.add(f"errors.{name}")
            health.mark_error(name, message)
            log.error("backlog.source_failed", source=name, error=message)
            out[name] = {"error": message}
        else:
            out[name] = {"seconds": round(time.monotonic() - started, 1)}
        out[name]["by_segment"] = sink.flush()  # what was found is written even after an error
    return out


def run(rc: RunContext, *, router: AIRouter | None = None) -> dict[str, Any]:
    """Run every startup source's backlog pass and store the businesses and signals they find."""
    days = max(1, int(db.get_setting("backlog.days", DEFAULT_DAYS) or DEFAULT_DAYS))
    items = max(0, int(db.get_setting("backlog.items_per_source", DEFAULT_ITEMS) or 0))
    ctx = SourceContext.from_run(rc, router)
    sources = asyncio.run(_run_sources(rc, ctx, days, items))
    stats: dict[str, Any] = {"days": days, "items_per_source": items, "sources": sources, **ctx.stats}
    if ctx.alerts:
        rc.stats.setdefault("alerts", []).extend(ctx.alerts)
    if ctx.ai_stopped:
        rc.stats.setdefault("ai_stopped", {})["backlog"] = ctx.ai_stopped
    rc.stats["backlog"] = stats
    log.info("backlog.done", days=days, sources={k: v.get("skipped", "ran") for k, v in sources.items()})
    return stats
