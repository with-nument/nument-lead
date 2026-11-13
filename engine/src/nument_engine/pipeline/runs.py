"""Runs: one `runs` row per execution, and the orchestrated runs GitHub Actions starts (Step 14.4).

A run is a list of phases. Each phase calls one stage entry point (`module.run(rc)` and friends), reads only
work that is still pending, and returns a small stats dict, so re-running a crashed run simply continues.

- Essential phases (health, prefilter, verify, score, sheet sync, summary, report) cost nothing. If one fails,
  the run is `failed` and stops; `nlead` exits 1. Health stops a run only on a FAIL (`check_all(fail_fast=True)`).
- Other phases that fail are recorded and the run goes on; it ends `partial` and `nlead` exits 0.
- Paid phases name a budget phase (Step 19.6): one starts only while today's committed spend is under that
  phase's share of the daily cap (`budget.Budget.allow_phase`). A cap reached inside a phase
  (`budget.BudgetExceeded`) stops it cleanly; the run is `partial`.
- Progress is written to `runs.stats` after every phase, so the app's Engine page shows a live run.
- One run of each kind at a time: the GitHub concurrency group, plus the check in `_another_run` here.
"""

from __future__ import annotations

import importlib
import time
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Final

from .. import db
from ..logging import bind_run, get_logger
from ..models import RUN_KINDS

log = get_logger()

ERROR_TAIL_CHARS = 4000  # runs.error keeps the end of the traceback, where the cause is
IST: Final = timezone(timedelta(hours=5, minutes=30))
DRY_RUN_LIMIT: Final = 5  # items per stage in a dry run when --limit is not given (14.4.3)
# Minutes a run may take before non-essential phases are skipped: each workflow's timeout minus a margin, so
# the run closes its row itself instead of being killed with the row left 'running'.
DEADLINE_MIN: Final[dict[str, int]] = {
    "night": 80,
    "morning": 40,
    "midday": 30,
    "sheet_sync": 8,
    "weekly": 26,
    "monthly": 55,
}
# A 'running' row older than this was killed (timeout or cancel) and is closed as failed by the next run.
STALE_MIN: Final[dict[str, int]] = {
    "night": 50,
    "morning": 50,
    "midday": 40,
    "sheet_sync": 15,
    "weekly": 35,
    "monthly": 65,
    "manual": 180,
}


@dataclass
class Options:
    """Global CLI flags, passed to every stage."""

    env: str = "dev"
    segments: list[str] = field(default_factory=list)  # empty = all enabled segments
    limit: int | None = None
    dry_run: bool = False
    max_spend_inr: float | None = None  # hard cap on paid calls for this run (Step 4 budget guard)


@dataclass
class RunContext:
    """What a stage needs to know about the run it belongs to."""

    run_id: str
    kind: str
    opts: Options
    started_at: datetime
    stats: dict[str, Any] = field(default_factory=dict)
    failed_stages: list[str] = field(default_factory=list)
    skipped_stages: list[str] = field(default_factory=list)  # skipped by the budget or the deadline
    deadline: datetime | None = None  # long stages (research) stop starting new work after this

    def add(self, key: str, n: int = 1) -> None:
        """Increment a counter in the run stats."""
        self.stats[key] = self.stats.get(key, 0) + n

    def time_left(self) -> float:
        """Seconds until the deadline (infinite when there is none)."""
        if self.deadline is None:
            return float("inf")
        return (self.deadline - datetime.now(UTC)).total_seconds()


def _opts_json(opts: Options) -> dict[str, Any]:
    return {
        "dry_run": opts.dry_run,
        "limit": opts.limit,
        "segments": opts.segments,
        "max_spend_inr": opts.max_spend_inr,
    }


def _stats_json(rc: RunContext) -> dict[str, Any]:
    return {
        **_opts_json(rc.opts),
        **rc.stats,
        "failed_stages": rc.failed_stages,
        "skipped_stages": rc.skipped_stages,
    }


@contextmanager
def run_context(kind: str, opts: Options) -> Iterator[RunContext]:
    """Open a `runs` row, bind the run id to every log line, and close the row as ok, partial or failed."""
    if kind not in RUN_KINDS:
        raise ValueError(f"unknown run kind {kind!r}; expected one of {', '.join(RUN_KINDS)}")
    run_id = str(uuid.uuid4())
    bind_run(run_id, kind, opts.env)
    rc = RunContext(run_id=run_id, kind=kind, opts=opts, started_at=datetime.now(UTC))
    db.execute(
        "insert into public.runs (id, kind, started_at, status, stats) values (%s, %s, %s, 'running', %s)",
        [run_id, kind, rc.started_at, db.Jsonb(_opts_json(opts))],
    )
    log.info("run.start", **_opts_json(opts))
    try:
        yield rc
    except BaseException as exc:
        error = "".join(traceback.format_exception(exc))[-ERROR_TAIL_CHARS:]
        db.execute(
            "update public.runs set status = 'failed', finished_at = now(), stats = %s, error = %s where id = %s",
            [db.Jsonb(_stats_json(rc)), error, run_id],
        )
        log.error("run.failed", error=f"{type(exc).__name__}: {exc}")
        raise
    else:
        status = "partial" if (rc.failed_stages or rc.skipped_stages) else "ok"
        db.execute(
            "update public.runs set status = %s, finished_at = now(), stats = %s where id = %s",
            [status, db.Jsonb(_stats_json(rc)), run_id],
        )
        log.info("run.finish", status=status, failed_stages=rc.failed_stages, skipped_stages=rc.skipped_stages)


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------
PhaseFn = Callable[["RunContext"], Mapping[str, Any] | None]


@dataclass(frozen=True)
class Phase:
    name: str
    fn: PhaseFn
    essential: bool = False
    budget: str | None = None  # a budget.PHASE_STOP_AT key (Step 19.6); None = free, never gated
    after_deadline: bool = False  # runs even past the deadline: a few seconds and the point of the run


class EssentialPhaseFailed(RuntimeError):
    """An essential phase failed: the run is `failed` and stops (exit code 1)."""

    def __init__(self, phase: str, cause: BaseException) -> None:
        super().__init__(f"essential phase {phase!r} failed: {type(cause).__name__}: {cause}")
        self.phase = phase


def stage(module: str, func: str = "run", **kwargs: Any) -> PhaseFn:
    """A stage entry point, imported when the phase runs (keeps `nlead --help` fast; one broken stage cannot
    stop the others from importing)."""

    def call(rc: RunContext) -> Mapping[str, Any] | None:
        entry = getattr(importlib.import_module(f"nument_engine.{module}"), func)
        result: Mapping[str, Any] | None = entry(rc, **kwargs)
        return result

    call.__qualname__ = f"{module}.{func}"
    return call


def phase_allowed(rc: RunContext, phase: str) -> tuple[bool, str]:
    """May a paid phase start now? Asks the budget guard (Step 19.6), which also honours --max-spend-inr."""
    from ..budget import PHASE_STOP_AT, Budget

    guard = Budget(rc.run_id, max_spend_inr=rc.opts.max_spend_inr, stats=rc.stats)
    if guard.allow_phase(phase):
        return True, ""
    return False, (
        f"{phase} stops at {PHASE_STOP_AT[phase]:.0%} of the ₹{guard.cap_inr:.0f} daily cap "
        f"(₹{guard.committed_inr():.0f} committed, ₹{guard.spent_this_run_inr():.0f} this run)"
    )


def save_progress(rc: RunContext) -> None:
    """Write the stats so far to the run row (the Engine page shows live progress)."""
    db.execute("update public.runs set stats = %s where id = %s", [db.Jsonb(_stats_json(rc)), rc.run_id])


def execute(rc: RunContext, phases: list[Phase]) -> None:
    """Run phases in order with the rules in the module docstring."""
    if rc.opts.dry_run and rc.opts.limit is None:
        rc.opts.limit = DRY_RUN_LIMIT
    if rc.kind in DEADLINE_MIN:
        rc.deadline = rc.started_at + timedelta(minutes=DEADLINE_MIN[rc.kind])
    _close_abandoned(rc.kind)
    other = _another_run(rc)
    if other:
        log.warning("run.skipped_overlap", other_run=other)
        rc.stats["skipped"] = f"run {other} of this kind is still running"
        return
    from ..budget import BudgetExceeded

    phase_stats: dict[str, Any] = rc.stats.setdefault("phases", {})
    for ph in phases:
        if not ph.essential and not ph.after_deadline and rc.time_left() <= 0:
            phase_stats[ph.name] = {"skipped": "deadline"}
            rc.skipped_stages.append(ph.name)
            save_progress(rc)
            continue
        if ph.budget is not None:
            ok, why = phase_allowed(rc, ph.budget)
            if not ok:
                phase_stats[ph.name] = {"skipped": "budget", "detail": why}
                rc.skipped_stages.append(ph.name)
                save_progress(rc)
                continue
        t0 = time.monotonic()
        log.info("phase.start", phase=ph.name)
        try:
            result = ph.fn(rc)
            phase_stats[ph.name] = {**(dict(result) if result else {}), "seconds": round(time.monotonic() - t0, 1)}
            log.info("phase.finish", phase=ph.name, seconds=phase_stats[ph.name]["seconds"])
        except NotImplementedError as exc:
            phase_stats[ph.name] = {"skipped": "not built", "detail": str(exc)}
            if ph.essential:
                save_progress(rc)
                raise
            rc.skipped_stages.append(ph.name)
        except BudgetExceeded as exc:
            phase_stats[ph.name] = {"stopped": "budget", "detail": str(exc)}
            rc.skipped_stages.append(ph.name)
        except Exception as exc:
            phase_stats[ph.name] = {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
            log.error("phase.failed", phase=ph.name, error=f"{type(exc).__name__}: {exc}")
            if ph.essential:
                save_progress(rc)
                raise EssentialPhaseFailed(ph.name, exc) from exc
            rc.failed_stages.append(ph.name)
        save_progress(rc)


def _close_abandoned(kind: str) -> None:
    """Close runs of this kind that were killed (job timeout or cancel) and never closed their row."""
    minutes = STALE_MIN.get(kind, 180)
    n = db.execute(
        "update public.runs set status = 'failed', finished_at = now(), "
        "error = coalesce(error, 'abandoned: the job ended without closing this run (timeout or cancel)') "
        "where kind = %s and status = 'running' and started_at < now() - make_interval(mins => %s)",
        [kind, minutes],
    )
    if n:
        log.warning("run.closed_abandoned", kind=kind, count=n)


def _another_run(rc: RunContext) -> str | None:
    """Id of an earlier run of the same kind that is still running (ties go to the smaller id)."""
    row = db.fetch_one(
        "select id::text as id from public.runs where kind = %s and status = 'running' and id <> %s "
        "and (started_at, id::text) < (%s, %s) and started_at > now() - make_interval(mins => %s) "
        "order by started_at limit 1",
        [rc.kind, rc.run_id, rc.started_at, rc.run_id, STALE_MIN.get(rc.kind, 180)],
    )
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Phases owned by the orchestration
# ---------------------------------------------------------------------------
def summary(rc: RunContext) -> Mapping[str, Any]:
    """The morning report (19.8): health plus today's numbers; the markdown goes to the job summary."""
    from ..ops import health

    markdown = health.daily_summary(rc)
    rc.stats.setdefault("summary", {})["markdown_lines"] = markdown.count("\n")
    return dict(rc.stats["summary"])


def sheet_sync(light: bool) -> PhaseFn:
    def call(rc: RunContext) -> Mapping[str, Any]:
        from ..sheet import sync

        return sync.run(rc, light=light)

    return call


CATCH_UP_STAGES: Final[tuple[tuple[str, str], ...]] = (
    ("pipeline.extract", "collect"),
    ("pipeline.verify", "run"),
    ("pipeline.score", "run"),
    ("pipeline.judge", "run"),
    ("pipeline.message", "run"),
)


def catch_up(rc: RunContext) -> dict[str, Any]:
    """09:00 IST: collect batch items that finished after the morning run and finish only those (14.4.4).

    Every stage picks only pending work, so when nothing finished late this costs seconds.
    """
    from ..budget import BudgetExceeded

    if datetime.now(IST).hour >= 11:
        return {"skipped": "only the first daytime sync catches up"}
    out: dict[str, Any] = {}
    for module, func in CATCH_UP_STAGES:
        name = module.rsplit(".", 1)[1]
        try:
            out[name] = dict(stage(module, func)(rc) or {})
        except NotImplementedError as exc:
            out[name] = {"skipped": "not built", "detail": str(exc)}
        except BudgetExceeded as exc:
            out[name] = {"stopped": "budget", "detail": str(exc)}
            break
    return out


# ---------------------------------------------------------------------------
# The runs (14.4.2)
# ---------------------------------------------------------------------------
def night_phases() -> list[Phase]:
    return [
        Phase("health", stage("ops.health", "check_all", fail_fast=True), essential=True),  # only a FAIL stops it
        Phase("universe", stage("pipeline.universe"), budget="low_priority_research"),
        Phase("signals", stage("pipeline.signals"), budget="grounded_search"),
        # websites of businesses born from a job post or an ask (no Places key), before the pre-filter
        Phase("lookup", stage("pipeline.lookup"), budget="grounded_search"),
        Phase("prefilter", stage("pipeline.prefilter"), essential=True),
        Phase("research", stage("pipeline.research"), budget="research"),
        Phase("extract_submit", stage("pipeline.extract", "submit"), budget="extract"),
        # Google Maps numbers and review pain for tonight's businesses without Places data (uses the research
        # Chromium, so it runs in the night job; after the batch submission, which must not wait for it).
        Phase("maps_reviews", stage("pipeline.maps_reviews"), budget="low_priority_research"),
    ]


def morning_phases() -> list[Phase]:
    return [
        Phase("health", stage("ops.health", "check_all", fail_fast=True), essential=True),
        Phase("extract_collect", stage("pipeline.extract", "collect")),  # already paid at submission
        Phase("verify", stage("pipeline.verify"), essential=True),
        Phase("reviews", stage("pipeline.reviews"), budget="grounded_search"),  # Places fallback before scoring
        Phase("score", stage("pipeline.score"), essential=True),
        Phase("judge", stage("pipeline.judge"), budget="judge"),
        # the founder or owner of A and B leads without a named decision maker, so messages greet a person
        Phase("people", stage("pipeline.people"), budget="grounded_search"),
        Phase("message", stage("pipeline.message"), budget="message"),
        Phase("sheet_sync", sheet_sync(light=False), essential=True),
        Phase("prune", stage("ops.health", "prune_run")),  # daily, so 30-day Places content never overstays
        Phase("summary", summary, essential=True),
        # the morning list by email; never fails the run, and a late run still sends it (13 Nov 2026)
        Phase("email", stage("ops.emails", "morning"), after_deadline=True),
    ]


def midday_phases() -> list[Phase]:
    """13:00 IST (13 Nov 2026): a job post or a public ask is worth most on its first day. The day's new signals
    (businesses already researched are scored now, new ones are researched tonight), late batch items, then
    the lead stages and an email with the A and B leads made since the morning email."""
    return [
        Phase("health", stage("ops.health", "check_all", fail_fast=True), essential=True),
        Phase("signals", stage("pipeline.signals"), budget="grounded_search"),
        Phase("lookup", stage("pipeline.lookup"), budget="grounded_search"),
        Phase("extract_collect", stage("pipeline.extract", "collect")),
        Phase("verify", stage("pipeline.verify"), essential=True),
        Phase("score", stage("pipeline.score"), essential=True),
        Phase("judge", stage("pipeline.judge"), budget="judge"),
        # the founder or owner of A and B leads without a named decision maker, so messages greet a person
        Phase("people", stage("pipeline.people"), budget="grounded_search"),
        Phase("message", stage("pipeline.message"), budget="message"),
        Phase("hot_email", stage("ops.emails", "hot"), after_deadline=True),
    ]


def sheet_phases(light: bool) -> list[Phase]:
    return [
        Phase("catch_up", catch_up, budget="message"),
        Phase("sheet_sync", sheet_sync(light=light), essential=True),
    ]


def weekly_phases() -> list[Phase]:
    """Learning, then the audit, then the report, so the report includes this week's audit (16.6.2)."""
    return [
        Phase("learn", stage("learn.reweight")),
        Phase("audit", stage("ops.audit", "weekly"), budget="judge"),
        Phase("report", stage("learn.report", "weekly"), essential=True),
    ]


def monthly_phases() -> list[Phase]:
    return [
        Phase("universe", stage("pipeline.universe", monthly=True), budget="low_priority_research"),
        Phase("prune", stage("ops.health", "prune_run"), essential=True),
    ]


def night(rc: RunContext) -> None:
    """02:00 IST pipeline part 1: universe top-up, signals, pre-filter, research, extract submit, Maps reviews."""
    execute(rc, night_phases())


def morning(rc: RunContext) -> None:
    """06:00 IST pipeline part 2: extract collect, verify, score, judge, message, sheet sync, prune, summary, email."""
    execute(rc, morning_phases())


def midday(rc: RunContext) -> None:
    """13:00 IST: the day's new signals, late batch items, lead stages and the hot-lead email."""
    execute(rc, midday_phases())


def sheet(rc: RunContext, *, light: bool = False) -> None:
    """Daytime: late batch items (09:00 only), then the two-way sheet sync."""
    execute(rc, sheet_phases(light))


def weekly(rc: RunContext) -> None:
    """Monday: learning, the audit, then the weekly report."""
    execute(rc, weekly_phases())


def monthly(rc: RunContext) -> None:
    """1st of the month: universe refresh from the new release, then the retention rules."""
    execute(rc, monthly_phases())
