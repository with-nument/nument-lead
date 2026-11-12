"""`nlead health --models` and `--llm-smoke` (Step 4.4.3, 4.12) with fake providers, plus the CLI wiring."""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from nument_engine import db
from nument_engine.cli import app
from nument_engine.llm import health
from nument_engine.llm.types import LLMRequest, LLMResponse

from .llm_fakes import FakeClock, FakeProvider, llm_db_fixture, make_router, reply  # noqa: F401
from .llm_outputs import OUTPUTS

CONFIGURED_GEMINI = [
    "gemini-4-carbon",
    "gemini-4-argon",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]


def test_model_check_passes_when_every_gemini_model_exists(llm_db: str) -> None:
    router = make_router({"gemini": FakeProvider("gemini", models=CONFIGURED_GEMINI)})
    checks = health.check_models(router.registry, router, tiers=("balanced", "best", "lean"))
    levels = {c.level for c in checks}
    assert "FAIL" not in levels
    lines = "\n".join(c.line for c in checks)
    assert "OK    gemini: 5 models listed" in lines
    assert "WARN  openai: skipped (providers_enabled.openai = false)" in lines
    assert "WARN  write_message primary openai:gpt-5-mini skipped. Will use gemini:gemini-3.8-flash" in lines


def test_model_check_fails_on_a_missing_gemini_model(llm_db: str) -> None:
    listed = [m for m in CONFIGURED_GEMINI if m != "gemini-3.8-flash"] + ["gemini-3.8-flash-preview-11-2026"]
    router = make_router({"gemini": FakeProvider("gemini", models=listed)})
    checks = health.check_models(router.registry, router)
    fails = [c.line for c in checks if c.level == "FAIL"]
    assert fails and all("gemini-3.8-flash not found" in line for line in fails)
    assert "Closest: gemini-3.8-flash-preview-11-2026" in fails[0]


def test_model_check_fails_without_a_gemini_key(llm_db: str) -> None:
    router = make_router({})
    checks = health.check_models(router.registry, router)
    assert checks[0].line == "FAIL  gemini: skipped (no gemini API key)"


def _answer(req: LLMRequest) -> LLMResponse:
    if req.task == "grounded_search" and req.schema is None:
        grounding = {"queries": ["q1"], "sources": [{"uri": "https://r.example/1", "title": "x"}], "supports": []}
        return reply("1. Smile Care Clinic asks for a bot. https://forum.example.com/t/1", grounding=grounding)
    return reply(OUTPUTS[req.task], model=req.model)


def test_smoke_runs_every_task_on_gemini_and_skips_openai(llm_db: str) -> None:
    clock = FakeClock()
    gemini = FakeProvider("gemini", [_answer] * 60)
    router = make_router({"gemini": gemini}, clock=clock)
    report = health.llm_smoke(router)
    ok = [r for r in report.rows if r.ok]
    skipped = [r for r in report.rows if r.ok is None]
    assert report.failures == 0
    assert {r.task for r in ok} == set(router.registry.tasks)  # every task ran on Gemini
    assert all(r.provider == "openai" and "providers_enabled.openai = false" in r.detail for r in skipped)
    first_fallback = next(i for i, r in enumerate(report.rows) if r.role == "fallback")
    assert all(r.role == "primary" for r in report.rows[:first_fallback])
    assert report.total_inr > 0
    search = next(r for r in report.rows if r.task == "grounded_search" and r.ok)
    assert search.detail == "ok q=1 sources=1"
    lines = health.format_smoke(report)
    assert lines[0].startswith("task") and lines[-1].startswith("total")


def test_smoke_stops_paid_calls_at_the_run_cap(llm_db: str) -> None:
    gemini = FakeProvider("gemini", [_answer] * 60)
    router = make_router({"gemini": gemini}, max_spend_inr=0.05, run_id=_run())
    report = health.llm_smoke(router)
    assert any("budget" in r.detail for r in report.rows)
    assert router.budget.spent_this_run_inr() <= 0.05 + 0.5  # one call may be in flight when the cap is reached


def _run() -> str:
    row = db.fetch_one("insert into public.runs (kind) values ('manual') returning id::text as id")
    assert row is not None
    return str(row["id"])


def test_cli_health_models_without_keys_fails_clearly(llm_db: str) -> None:
    result = CliRunner().invoke(app, ["health", "--models"])
    assert result.exit_code == 1
    assert "FAIL  gemini: skipped (no gemini API key)" in result.output
    row: dict[str, Any] | None = db.fetch_one(
        "select status, stats from public.runs where kind = 'manual' order by started_at desc limit 1"
    )
    assert row is not None and row["status"] == "ok" and row["stats"]["model_check_failures"] >= 1


def test_cli_health_help_lists_the_router_flags() -> None:
    result = CliRunner().invoke(app, ["health", "--help"])
    assert result.exit_code == 0
    for flag in ("--models", "--llm-smoke", "--providers"):
        assert flag in result.output
