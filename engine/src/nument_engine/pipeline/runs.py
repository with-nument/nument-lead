"""Run bookkeeping: one row in `runs` per execution, plus orchestration of night/morning runs (filled in Step 14)."""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .. import db
from ..logging import bind_run, get_logger
from ..models import RUN_KINDS

log = get_logger()

ERROR_TAIL_CHARS = 4000  # runs.error keeps the end of the traceback, where the cause is


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

    def add(self, key: str, n: int = 1) -> None:
        """Increment a counter in the run stats."""
        self.stats[key] = self.stats.get(key, 0) + n


def _opts_json(opts: Options) -> dict[str, Any]:
    return {
        "dry_run": opts.dry_run,
        "limit": opts.limit,
        "segments": opts.segments,
        "max_spend_inr": opts.max_spend_inr,
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
            [db.Jsonb({**_opts_json(opts), **rc.stats, "failed_stages": rc.failed_stages}), error, run_id],
        )
        log.error("run.failed", error=f"{type(exc).__name__}: {exc}")
        raise
    else:
        status = "partial" if rc.failed_stages else "ok"
        db.execute(
            "update public.runs set status = %s, finished_at = now(), stats = %s where id = %s",
            [status, db.Jsonb({**_opts_json(opts), **rc.stats, "failed_stages": rc.failed_stages}), run_id],
        )
        log.info("run.finish", status=status, stats=rc.stats, failed_stages=rc.failed_stages)


def night(rc: RunContext) -> None:
    """02:00 IST pipeline part 1: universe top-up, signals, pre-filter, research, extract submit."""
    raise NotImplementedError("Built in Step 14")


def morning(rc: RunContext) -> None:
    """06:00 IST pipeline part 2: extract collect, verify, score, judge, message, sheet push, prune."""
    raise NotImplementedError("Built in Step 14")
