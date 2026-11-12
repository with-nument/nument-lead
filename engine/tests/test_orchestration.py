"""Orchestrated runs (Step 14.4): essential vs optional phases, budget gates, deadlines, overlap, progress."""

from __future__ import annotations

import datetime as dt
import types
import uuid
from collections.abc import Mapping
from typing import Any

import pytest

from nument_engine import db
from nument_engine.pipeline import runs
from nument_engine.pipeline.runs import EssentialPhaseFailed, Options, Phase, RunContext, run_context


def _row(run_id: str) -> dict[str, Any]:
    row = db.fetch_one("select status, stats, error from public.runs where id = %s", [run_id])
    assert row is not None
    return row


def ok(stats: dict[str, Any] | None = None) -> runs.PhaseFn:
    def call(rc: RunContext) -> Mapping[str, Any] | None:
        return stats or {"done": 1}

    return call


def boom(exc: Exception) -> runs.PhaseFn:
    def call(rc: RunContext) -> Mapping[str, Any] | None:
        raise exc

    return call


@pytest.fixture
def clean_costs(engine_db: str) -> None:
    db.execute("delete from public.costs where task like 'orchestration-test%'")
    db.execute("update public.runs set status = 'failed' where status = 'running'")


def test_optional_phase_failure_makes_the_run_partial_and_continues(clean_costs: None) -> None:
    seen: list[str] = []

    def mark(rc: RunContext) -> dict[str, Any]:
        seen.append("after")
        return {"n": 2}

    with run_context("night", Options()) as rc:
        runs.execute(
            rc, [Phase("a", ok()), Phase("b", boom(ValueError("source down"))), Phase("c", mark, essential=True)]
        )
    row = _row(rc.run_id)
    assert row["status"] == "partial" and seen == ["after"]
    assert row["stats"]["failed_stages"] == ["b"]
    assert row["stats"]["phases"]["b"]["error"] == "ValueError: source down"
    assert row["stats"]["phases"]["c"]["n"] == 2 and "seconds" in row["stats"]["phases"]["c"]


def test_essential_phase_failure_stops_the_run(clean_costs: None) -> None:
    later: list[str] = []
    with pytest.raises(EssentialPhaseFailed, match="verify"), run_context("morning", Options()) as rc:
        runs.execute(
            rc,
            [
                Phase("verify", boom(RuntimeError("db gone")), essential=True),
                Phase("later", lambda rc: later.append("x")),
            ],
        )  # type: ignore[arg-type,func-returns-value]
    row = _row(rc.run_id)
    assert row["status"] == "failed" and later == []
    assert "RuntimeError: db gone" in row["error"] and row["stats"]["phases"]["verify"]["error"]


def test_unbuilt_optional_stage_is_skipped_and_unbuilt_essential_stage_stops(clean_costs: None) -> None:
    with run_context("night", Options()) as rc:
        runs.execute(rc, [Phase("signals", boom(NotImplementedError("Built in Step 7")))])
    assert _row(rc.run_id)["status"] == "partial"
    with pytest.raises(NotImplementedError), run_context("night", Options()) as rc2:
        runs.execute(rc2, [Phase("health", boom(NotImplementedError("Built in Step 22")), essential=True)])
    assert _row(rc2.run_id)["stats"]["phases"]["health"]["skipped"] == "not built"


def test_budget_gate_skips_paid_phases_by_priority(clean_costs: None) -> None:
    db.execute(
        "insert into public.costs (provider, task, usd, inr) values ('gemini', 'orchestration-test', 6.5, 600)"
    )  # 80% of the default ₹750 cap
    with run_context("night", Options()) as rc:
        runs.execute(
            rc,
            [
                Phase("fit_only", ok(), priority=1),  # stops at 60%
                Phase("signals", ok(), priority=3),  # stops at 85%: still runs
                Phase("free", ok()),
            ],
        )
    row = _row(rc.run_id)
    assert row["status"] == "partial"
    assert row["stats"]["phases"]["fit_only"]["skipped"] == "budget"
    assert row["stats"]["phases"]["signals"]["done"] == 1 and row["stats"]["phases"]["free"]["done"] == 1


def test_per_run_spend_cap(clean_costs: None) -> None:
    with run_context("night", Options(max_spend_inr=1)) as rc:
        db.execute(
            "insert into public.costs (run_id, provider, task, usd, inr) values (%s, 'gemini', 'orchestration-test-run', 0.02, 2)",
            [rc.run_id],
        )
        runs.execute(rc, [Phase("research", ok(), priority=4)])
    assert _row(rc.run_id)["stats"]["phases"]["research"]["skipped"] == "budget"


def test_budget_stop_inside_a_phase_is_clean(clean_costs: None, monkeypatch: pytest.MonkeyPatch) -> None:
    class BudgetStop(Exception):
        pass

    fake_budget = types.ModuleType("nument_engine.budget")
    fake_budget.BudgetStop = BudgetStop  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "nument_engine.budget", fake_budget)
    with run_context("morning", Options()) as rc:
        runs.execute(
            rc, [Phase("message", boom(BudgetStop("cap reached")), priority=5), Phase("summary", ok(), essential=True)]
        )
    row = _row(rc.run_id)
    assert row["status"] == "partial" and row["stats"]["phases"]["message"] == {
        "stopped": "budget",
        "detail": "cap reached",
    }
    assert row["stats"]["failed_stages"] == []


def test_deadline_skips_optional_phases_but_not_essential_ones(clean_costs: None) -> None:
    with run_context("night", Options()) as rc:
        rc.started_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
        runs.execute(rc, [Phase("research", ok(), priority=4), Phase("prefilter", ok(), essential=True)])
    row = _row(rc.run_id)
    assert row["stats"]["phases"]["research"] == {"skipped": "deadline"}
    assert row["stats"]["phases"]["prefilter"]["done"] == 1


def test_a_second_run_of_the_same_kind_steps_aside(clean_costs: None) -> None:
    first = str(uuid.uuid4())
    db.execute(
        "insert into public.runs (id, kind, started_at, status) values (%s, 'night', now() - interval '5 minutes', 'running')",
        [first],
    )
    called: list[str] = []
    with run_context("night", Options()) as rc:
        runs.execute(rc, [Phase("health", lambda rc: called.append("x"), essential=True)])  # type: ignore[arg-type,func-returns-value]
    assert called == [] and first in _row(rc.run_id)["stats"]["skipped"]


def test_abandoned_runs_are_closed(clean_costs: None) -> None:
    stale = str(uuid.uuid4())
    db.execute(
        "insert into public.runs (id, kind, started_at, status) values (%s, 'morning', now() - interval '3 hours', 'running')",
        [stale],
    )
    with run_context("morning", Options()) as rc:
        runs.execute(rc, [Phase("summary", ok(), essential=True)])
    row = _row(stale)
    assert row["status"] == "failed" and "abandoned" in row["error"]
    assert _row(rc.run_id)["status"] == "ok"


def test_progress_is_saved_after_every_phase(clean_costs: None) -> None:
    snapshots: list[dict[str, Any]] = []

    def peek(rc: RunContext) -> dict[str, Any]:
        snapshots.append(_row(rc.run_id)["stats"])
        return {}

    with run_context("weekly", Options()) as rc:
        runs.execute(rc, [Phase("learn", ok({"weights": 3})), Phase("peek", peek)])
    assert snapshots[0]["phases"]["learn"]["weights"] == 3


def test_dry_run_defaults_to_a_small_limit(clean_costs: None) -> None:
    with run_context("night", Options(dry_run=True)) as rc:
        runs.execute(rc, [Phase("a", ok())])
    assert rc.opts.limit == runs.DRY_RUN_LIMIT


def test_phase_tables_follow_the_plan() -> None:
    names = {k: [p.name for p in f()] for k, f in {
        "night": runs.night_phases, "morning": runs.morning_phases, "weekly": runs.weekly_phases, "monthly": runs.monthly_phases,
    }.items()}  # fmt: skip
    assert names["night"] == [
        "health",
        "housekeeping",
        "universe",
        "signals",
        "prefilter",
        "research",
        "extract_submit",
    ]
    assert names["morning"] == [
        "health",
        "extract_collect",
        "verify",
        "score",
        "judge",
        "message",
        "sheet_sync",
        "summary",
    ]
    essential = {p.name for p in runs.morning_phases() if p.essential}
    assert essential == {"health", "verify", "score", "sheet_sync", "summary"}
    assert [p.name for p in runs.sheet_phases(light=True)] == ["catch_up", "sheet_sync"]
    for phases in (runs.night_phases(), runs.morning_phases()):
        assert all(p.priority is None or 1 <= p.priority <= 5 for p in phases)


def test_housekeeping_and_page_retention(clean_costs: None) -> None:
    with db.tx() as conn:
        conn.execute(
            "insert into public.llm_cache (key, task, model, response, expires_at) values (%s, 't', 'm', '{}', now() - interval '1 day')",
            [f"orch-{uuid.uuid4()}"],
        )
        biz = conn.execute(
            "insert into public.businesses (segment_id, name, norm_name, country) values ('clinics-in', 'Prune Test', 'prune test', 'in') "
            "returning id"
        ).fetchone()["id"]  # type: ignore[index]
        conn.execute(
            "insert into public.pages (business_id, url, fetched_at, text, text_hash) values "
            "(%s, %s, now() - interval '40 days', 'old text', 'h1'), (%s, %s, now() - interval '5 days', 'new text', 'h2')",
            [biz, f"https://prune.example/{uuid.uuid4()}", biz, f"https://prune.example/{uuid.uuid4()}"],
        )
    rc = RunContext(
        run_id=str(uuid.uuid4()), kind="weekly", opts=Options(dry_run=True), started_at=dt.datetime.now(dt.UTC)
    )
    assert runs.prune_pages(rc)["pages_to_trim"] >= 1
    assert runs.housekeeping(rc)["expired_cache_rows"] >= 1
    rc.opts.dry_run = False
    assert runs.prune_pages(rc)["pages_trimmed"] >= 1
    assert runs.housekeeping(rc)["expired_cache_rows_deleted"] >= 1
    texts = {r["text"] for r in db.fetch_all("select text from public.pages where business_id = %s", [biz])}
    assert texts == {None, "new text"}  # url and hash stay; only old raw text goes (A.13.5 rule 13)


def test_daily_summary(clean_costs: None) -> None:
    rc = RunContext(run_id=str(uuid.uuid4()), kind="morning", opts=Options(), started_at=dt.datetime.now(dt.UTC))
    summary = runs.daily_summary(rc)
    assert {"spend_today_inr", "leads_created_today", "new_ab_waiting", "sheet_state"} <= set(summary)
    assert rc.stats["summary"] is summary
