"""Night phase `probes` (15 Nov 2026): cheap public probes for the startups researched in the last week.

Which businesses: those in startup segments (`research.pages.is_startup_segment`) with a website, crawled in the
last 7 days, not rejected or suppressed, whose probes are due (`extra.probes.next_at`): never probed, a probe
that answered more than 30 days ago, or one that failed or was not asked more than 20 hours ago. Never-probed
businesses go first, then by queue priority; at most `probes.per_run` (250) a run, and the phase stops starting
work after `probes.max_minutes` (15) or the run's deadline, whichever comes first. A probe still waiting then is
simply due again the next night.

What is written, per business as soon as its probes finish (contract 4.2):
- a probe that answered writes one `facts` row `probe.<name>` (model 'rule', verified, the public URL that
  answered, a short raw excerpt as the quote), replacing the business's previous row for that probe;
- a probe whose source answered that there is nothing (no such organisation, no app) removes the old row;
- a probe that failed writes nothing and keeps the old row (counted as `probes.<name>.error`);
- `extra.probes` keeps, per probe, when it last ran and how it ended, plus `next_at` for the selection.

The tech fingerprint (`probe.tech`) is written by the research stage, which still has the homepage HTML.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .. import db
from ..logging import get_logger
from ..research import pages as pagelib
from ..research import probes as pr
from ..sources import health
from .runs import RunContext
from .selection import active_segments

log = get_logger()

DEFAULT_PER_RUN = 250  # settings probes.per_run (contract 4.9)
DEFAULT_MINUTES = 15  # settings probes.max_minutes
CONCURRENCY = 8  # startups probed side by side; each source keeps its own pace across them
RESEARCHED_WITHIN_DAYS = 7
REPROBE_AFTER = timedelta(days=30)  # an answer (or robots.txt saying no) is asked again after this
RETRY_AFTER = timedelta(hours=20)  # a failure or a probe that was not asked: the next night
ANSWERED = frozenset({"ok", "none", "robots"})
REASON_CHARS = 120

QUEUE_SQL = """
select b.id::text as id, b.segment_id, b.name, b.website, b.web_domain, b.country, b.extra
from public.businesses b
where b.segment_id = any(%(segments)s)
  and b.website is not null
  and b.status not in ('rejected', 'suppressed')
  and (b.extra #>> '{crawl,at}')::timestamptz > now() - make_interval(days => %(days)s)
  and coalesce((b.extra #>> '{probes,next_at}')::timestamptz, 'epoch') <= now()
order by (b.extra ? 'probes'), b.queue_priority desc nulls last, b.id
limit %(limit)s
"""


def _when(entry: Any) -> datetime | None:
    if not isinstance(entry, dict):
        return None
    try:
        at = datetime.fromisoformat(str(entry.get("at")))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _due_at(entry: Any, now: datetime) -> datetime:
    at = _when(entry)
    if at is None:
        return now
    return at + (REPROBE_AFTER if entry.get("state") in ANSWERED else RETRY_AFTER)


def due_probes(state: dict[str, Any], now: datetime) -> set[str]:
    """The probes of one business that are due now, from its `extra.probes`."""
    return {name for name in pr.PROBES if _due_at(state.get(name), now) <= now}


def next_at(state: dict[str, Any], now: datetime) -> datetime:
    """When the first of this business's probes is due again (now, when one never ran)."""
    return min(_due_at(state.get(name), now) for name in pr.PROBES)


def record(state: dict[str, Any], outcomes: dict[str, pr.Outcome], now: datetime) -> dict[str, Any]:
    """The new `extra.probes`: each probe that ran with its time and ending, then `next_at`."""
    out = {k: v for k, v in state.items() if k in pr.PROBES}
    for name, outcome in outcomes.items():
        entry: dict[str, Any] = {"at": now.isoformat(), "state": outcome.state}
        if outcome.state != "ok" and outcome.reason:
            entry["reason"] = outcome.reason[:REASON_CHARS]
        out[name] = entry
    out["next_at"] = next_at(out, now).isoformat()
    return out


def save(business_id: str, state: dict[str, Any], outcomes: dict[str, pr.Outcome]) -> int:
    """Write one business's probe facts and `extra.probes` in one transaction. Returns facts written."""
    written = 0
    with db.tx() as conn:
        for name, outcome in outcomes.items():
            field = pr.FIELDS[name]
            if outcome.state in ("ok", "none"):
                conn.execute(
                    "delete from public.facts where business_id = %s and field = %s and model = 'rule'",
                    [business_id, field],
                )
            if outcome.state == "ok" and outcome.value is not None:
                conn.execute(
                    """insert into public.facts (business_id, field, value, quote, url, model, verified,
                                                 verify_score, verified_at)
                       values (%s, %s, %s, %s, %s, 'rule', true, 100, now())""",
                    [business_id, field, Jsonb(outcome.value), outcome.quote[: pr.QUOTE_CHARS], outcome.url],
                )
                written += 1
        conn.execute(
            "update public.businesses set extra = jsonb_set(extra, '{probes}', %s) where id = %s",
            [Jsonb(state), business_id],
        )
    return written


async def probe_all(
    rows: list[dict[str, Any]],
    *,
    budget_s: float,
    run_left: Callable[[], float],
    dry_run: bool = False,
    make_probes: Callable[[], pr.Probes] = pr.Probes,
) -> Counter[str]:
    """Probe the selected businesses until the work, the phase budget or the run's deadline runs out."""
    stats: Counter[str] = Counter({"probed": 0, "facts": 0})
    stop_at = time.monotonic() + budget_s

    def left() -> float:
        return min(stop_at - time.monotonic(), run_left())

    sem = asyncio.Semaphore(CONCURRENCY)
    async with make_probes() as probes:

        async def one(row: dict[str, Any]) -> None:
            target = pr.target_of(row)
            if target is None:
                stats["no_usable_host"] += 1
                return
            state = dict((row.get("extra") or {}).get("probes") or {})
            due = due_probes(state, datetime.now(UTC))
            if not due:  # an out-of-date next_at: schedule again, probe nothing (30 days between answers)
                if not dry_run:
                    save(target.business_id, record(state, {}, datetime.now(UTC)), {})
                stats["rescheduled"] += 1
                return
            async with sem:
                if left() <= 0:
                    stats["time_skipped"] += 1
                    return
                outcomes = await probes.probe(target, due, left)
            if not outcomes:
                stats["time_skipped"] += 1
                return
            for name, outcome in outcomes.items():
                stats[f"probes.{name}.{outcome.state}"] += 1
            stats["probed"] += 1
            if dry_run:
                return
            stats["facts"] += save(target.business_id, record(state, outcomes, datetime.now(UTC)), outcomes)

        results = await asyncio.gather(*(one(r) for r in rows), return_exceptions=True)
        for res in results:
            if isinstance(res, BaseException):
                stats["errors"] += 1
                log.error("probes.business_failed", error=f"{type(res).__name__}: {str(res)[:300]}")
        stats["requests"] = probes.requests
    return stats


def run(
    rc: RunContext,
    *,
    make_probes: Callable[[], pr.Probes] | None = None,
    budget_s: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Probe the startups researched in the last week whose probes are due."""
    segments = [seg_id for seg_id, seg in active_segments(rc.opts.segments).items() if pagelib.is_startup_segment(seg)]
    if not segments:
        skipped: dict[str, Any] = {"skipped": "no startup segment is on"}
        rc.stats["probes"] = skipped
        return skipped
    per_run = max(0, health.setting_int("probes.per_run", DEFAULT_PER_RUN))
    minutes = max(0, health.setting_int("probes.max_minutes", DEFAULT_MINUTES))
    github_cap = max(0, health.setting_int("probes.github_per_run", pr.GITHUB_REQUESTS))
    rows = db.fetch_all(
        QUEUE_SQL,
        {"segments": segments, "days": RESEARCHED_WITHIN_DAYS, "limit": min(rc.opts.limit or per_run, per_run)},
    )
    factory = make_probes or (lambda: pr.Probes(github_requests=github_cap))
    counts = asyncio.run(
        probe_all(
            rows,
            budget_s=minutes * 60.0 if budget_s is None else budget_s,
            run_left=rc.time_left,
            dry_run=rc.opts.dry_run,
            make_probes=factory,
        )
    )
    stats: dict[str, Any] = {"selected": len(rows), **dict(sorted(counts.items()))}
    rc.stats["probes"] = stats
    log.info("probes.done", selected=len(rows), probed=counts["probed"], facts=counts["facts"])
    return stats
