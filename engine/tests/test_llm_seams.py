"""The two router seams on main use the real router: pipeline/ai.py (Steps 10 to 12) and ops/bindings.py
(learning, audit and evals). Providers are fakes; everything else (registry, prompts, budget, cache, costs,
breakers) is the production code."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from nument_engine import db
from nument_engine.budget import BudgetExceeded
from nument_engine.llm import router as router_module
from nument_engine.llm.health import SMOKE_INPUTS
from nument_engine.llm.types import AllProvidersDown
from nument_engine.models import LeadJudgement, MessageCheck, MessageDraft
from nument_engine.ops import bindings
from nument_engine.pipeline import ai
from nument_engine.pipeline.runs import Options, RunContext

from .llm_fakes import FakeProvider, llm_db_fixture, new_run, reply  # noqa: F401
from .llm_outputs import OUTPUTS


@pytest.fixture
def run_ctx(llm_db: str) -> Iterator[RunContext]:
    rc = RunContext(run_id=new_run(), kind="manual", opts=Options(), started_at=datetime.now(UTC))
    yield rc
    db.execute("delete from public.costs where run_id = %s", [rc.run_id])  # real-clock rows: keep "today" clean


def _fake_gemini(monkeypatch: pytest.MonkeyPatch, replies: list[object]) -> FakeProvider:
    gemini = FakeProvider("gemini", replies)  # type: ignore[arg-type]
    monkeypatch.setattr(router_module, "build_providers", lambda settings: {"gemini": gemini})
    return gemini


def test_pipeline_seam_calls_the_router_and_reads_who_answered(
    run_ctx: RunContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    gemini = _fake_gemini(
        monkeypatch,
        [reply(OUTPUTS["judge_lead"]), reply(OUTPUTS["write_message"]), reply(OUTPUTS["check_message"])],
    )
    router = ai.router_for(run_ctx)
    assert isinstance(router, router_module.Router) and router.run_id == run_ctx.run_id

    judged = ai.call(router, "judge_lead", SMOKE_INPUTS["judge_lead"], LeadJudgement, run_id=run_ctx.run_id)
    assert judged.output == OUTPUTS["judge_lead"]
    assert judged.tag == "gemini:gemini-4-argon#judge_lead.v1"

    draft = ai.call(router, "write_message", SMOKE_INPUTS["write_message"], MessageDraft, run_id=run_ctx.run_id)
    assert draft.model == "gemini-3.8-flash" and draft.fallback_from == "openai:gpt-5-mini"

    critic = ai.call(
        router, "check_message", SMOKE_INPUTS["check_message"], MessageCheck, run_id=run_ctx.run_id,
        exclude_model=draft.model,
    )  # fmt: skip
    assert critic.model == "gemini-4-argon"  # never the writer's model
    assert [c.model for c in gemini.calls] == ["gemini-4-argon", "gemini-3.8-flash", "gemini-4-argon"]
    rows = db.fetch_all("select task, model from public.costs where run_id = %s order by at", [run_ctx.run_id])
    assert [r["task"] for r in rows] == ["judge_lead", "write_message", "check_message"]


def test_pipeline_seam_maps_router_failures(run_ctx: RunContext, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_gemini(monkeypatch, [])
    router = ai.router_for(run_ctx)
    with pytest.raises(ai.AIUnavailable):
        ai.call(router, "check_message", SMOKE_INPUTS["check_message"], MessageCheck, exclude_model="gemini-3.8-flash",
                run_id=run_ctx.run_id)  # fmt: skip
    db.set_setting("daily_cap_inr", 0.0001)
    router = ai.router_for(run_ctx)
    with pytest.raises(ai.AIBudgetStop):
        ai.call(router, "judge_lead", SMOKE_INPUTS["judge_lead"], LeadJudgement, run_id=run_ctx.run_id)


def test_ops_bindings_task_runner_uses_the_router(run_ctx: RunContext, monkeypatch: pytest.MonkeyPatch) -> None:
    gemini = _fake_gemini(monkeypatch, [reply(OUTPUTS["weekly_audit"])])
    run = bindings.task_runner(run_ctx)
    result = run("weekly_audit", SMOKE_INPUTS["weekly_audit"], lead_id=None)
    assert result == OUTPUTS["weekly_audit"] and gemini.calls[0].model == "gemini-4-argon"
    assert set(bindings.stop_errors()) == {BudgetExceeded, AllProvidersDown}
