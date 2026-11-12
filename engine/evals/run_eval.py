"""`nlead eval`: the golden-set evaluation (Step 17.4).

    nlead eval                    every golden business
    nlead eval --subset 20        the fixed CI subset in golden/subset20.txt (other sizes: a stratified pick)
    nlead eval --segment X        only that segment (repeatable, the global flag)
    nlead eval --export-golden    write labels, frozen pages and the subset from the database
    nlead eval --replay FILE      re-check metrics on outcomes saved with --save-outcomes (no AI, free)
    nlead eval --dry-run          validate the golden files and show the selection; no AI calls

Runs production code on frozen pages with the working tree's prompts, tasks.yaml, segment files and
weights, prints the metric table, stores a `reports` row (kind 'eval') and returns passed or failed. The
command exits 1 when a threshold fails, 2 when the eval cannot run yet (no golden set, or a stage not
built), and 3 when today's budget cannot cover it ("eval skipped: budget", which also blocks a merge).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from nument_engine import db
from nument_engine.learn.store import store_report
from nument_engine.logging import get_logger
from nument_engine.ops import bindings
from nument_engine.pipeline.runs import RunContext

from .golden import GOLDEN_DIR, Label, export_golden, load_labels, load_truth, read_subset, select_subset
from .measures import EvalReport, Outcome, evaluate
from .pipeline import EvalNotReady, EvalPipeline, LivePipeline, ReplayPipeline

log = get_logger()

EST_INR_PER_ITEM: Final[float] = 3.0  # the 20-item subset costs about ₹60, the full set about ₹300 (17.4.4)
CI_SUBSET: Final[int] = 20


def choose(
    labels: list[Label], truth_ids: set[str], subset: int | None, segments: list[str], golden_dir: Path
) -> list[Label]:
    """The labels to evaluate: a segment filter, then the fixed CI subset or a stratified pick of N."""
    pool = [lab for lab in labels if not segments or lab.segment in segments]
    if subset is None or subset >= len(pool):
        return pool
    by_id = {lab.business_id: lab for lab in pool}
    fixed = [by_id[i] for i in read_subset(golden_dir) if i in by_id] if subset == CI_SUBSET and not segments else []
    if len(fixed) == subset:
        return fixed
    return [by_id[i] for i in select_subset(pool, truth_ids, size=subset)]


def budget_check(items: int) -> tuple[bool, str]:
    """Will today's spend plus this eval stay under the daily cap? (17.4.4)"""
    cap = float(db.get_setting("daily_cap_inr", 750))
    spent = float(db.scalar("select inr from public.v_spend_today") or 0)
    estimate = items * EST_INR_PER_ITEM
    if spent + estimate > cap:
        return False, f"today's spend ₹{spent:.0f} plus about ₹{estimate:.0f} for this eval passes the ₹{cap:.0f} cap"
    return True, f"about ₹{estimate:.0f} (spent ₹{spent:.0f} of ₹{cap:.0f} today)"


def render(report: EvalReport, items: list[Label]) -> str:
    segs = Counter(lab.segment for lab in items)
    lines = [
        f"# Eval: {'passed' if report.passed else 'failed'} on {report.items} businesses",
        "",
        f"{'Subset' if report.subset else 'Full set'}; segments: "
        + ", ".join(f"{s} {n}" for s, n in sorted(segs.items())),
        "",
        "| Metric | Value | Threshold | n | Result |",
        "|---|---|---|---|---|",
    ]
    for m in report.metrics:
        result = "not measured" if m.passed is None else ("pass" if m.passed else "**fail**")
        lines.append(f"| {m.label} | {m.display or 'n/a'} | {m.threshold_display} | {m.n} | {result} |")
    return "\n".join(lines) + "\n"


def run(
    rc: RunContext,
    subset: int | None = None,
    *,
    export: bool = False,
    replay: Path | None = None,
    save_outcomes: Path | None = None,
    pipeline: EvalPipeline | None = None,
    golden_dir: Path | None = None,
) -> dict[str, Any]:
    """Evaluate (or export the golden set). Returns status: passed, failed, skipped_budget, dry_run or exported."""
    golden_dir = golden_dir or GOLDEN_DIR
    if export:
        counts = export_golden(golden_dir)
        print(
            f"Exported {counts['labels']} labels, {counts['frozen_pages']} frozen page sets, subset of {counts['subset']}."
        )
        rc.stats["eval"] = {"status": "exported", **counts}
        return {"status": "exported", "passed": True, **counts}

    labels = load_labels(golden_dir)
    if not labels:
        raise EvalNotReady(
            f"golden set: {golden_dir / 'labels.jsonl'} has no labels yet; label businesses in the app (Step 17.3), "
            "then run nlead eval --export-golden"
        )
    truth = load_truth(golden_dir)
    items = choose(labels, set(truth), subset, rc.opts.segments, golden_dir)
    if not items:
        raise EvalNotReady(f"no golden labels for segment(s) {', '.join(rc.opts.segments)}")
    if rc.opts.dry_run and replay is None:
        good = sum(lab.label == "good" for lab in items)
        print(f"{len(items)} businesses ({good} good, {len(items) - good} bad), {sum(lab.business_id in truth for lab in items)} "
              "with hand-checked facts. Dry run: no AI calls.")  # fmt: skip
        rc.stats["eval"] = {"status": "dry_run", "items": len(items)}
        return {"status": "dry_run", "passed": True, "items": len(items)}

    if pipeline is None and replay is not None:
        pipeline = ReplayPipeline(replay)
    if pipeline is None:
        ok, detail = budget_check(len(items))
        if not ok:
            rc.stats["eval"] = {"status": "skipped_budget", "detail": detail}
            return {"status": "skipped_budget", "passed": False, "detail": detail}
        pipeline = LivePipeline.from_production(rc, golden_dir)

    stop = bindings.stop_errors()
    outcomes: list[Outcome] = []
    for lab in items:
        try:
            outcomes.append(pipeline.run(lab))
        except stop as exc:  # the cap was reached mid-run: a partial eval would be misleading
            detail = f"stopped after {len(outcomes)} of {len(items)}: {type(exc).__name__}"
            rc.stats["eval"] = {"status": "skipped_budget", "detail": detail}
            return {"status": "skipped_budget", "passed": False, "detail": detail}
        except EvalNotReady:
            raise
        except Exception as exc:  # one business failing is measured (item_errors), not fatal
            log.warning("eval.item_failed", business_id=lab.business_id, error=type(exc).__name__)
            outcomes.append(Outcome(lab.business_id, lab.segment, error=f"{type(exc).__name__}: {str(exc)[:200]}"))

    report = evaluate(outcomes, {lab.business_id: lab for lab in labels}, truth, subset=subset is not None)
    print(report.table())
    if save_outcomes is not None:
        save_outcomes.write_text(
            "".join(json.dumps(o.as_dict(), default=str) + "\n" for o in outcomes), encoding="utf-8"
        )
    report_id = None
    if not rc.opts.dry_run:
        today = datetime.now(UTC).date()
        content = {"kind": "eval", "summary": report.summary(), "segments": rc.opts.segments,
                   "business_ids": [lab.business_id for lab in items], "replay": replay is not None}  # fmt: skip
        report_id = store_report("eval", today, today, content, render(report, items))
    status = "passed" if report.passed else "failed"
    rc.stats["eval"] = {"status": status, "items": report.items, "report_id": report_id}
    return {"status": status, "passed": report.passed, "report_id": report_id, "summary": report.summary()}
