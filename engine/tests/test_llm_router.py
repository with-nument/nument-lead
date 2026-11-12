"""AI router (Step 4.10, 4.13): parsing, repair, retries, cache, costs, activities, limits and grounded search."""

from __future__ import annotations

import pytest

from nument_engine import db
from nument_engine.budget import BudgetExceeded, llm_cost_usd
from nument_engine.llm.config import ModelRef, load_registry
from nument_engine.llm.health import SMOKE_INPUTS
from nument_engine.llm.router import REPAIR_NOTE, TRUNCATED_NOTE, Router
from nument_engine.models import MessageCheck, PublicAskResults, SignalClassification

from .llm_fakes import FakeClock, FakeProvider, err, llm_db_fixture, make_router, new_lead, reply  # noqa: F401
from .llm_outputs import OUTPUTS

LITE = ModelRef(provider="gemini", model="gemini-3.5-flash-lite")
FLASH = ModelRef(provider="gemini", model="gemini-3.8-flash")
ARGON = ModelRef(provider="gemini", model="gemini-4-argon")


def _costs(clock: FakeClock) -> list[dict[str, object]]:
    return db.fetch_all("select * from public.costs where at = %s order by provider, model, task", [clock()])


def _inputs(task: str, **extra: object) -> dict[str, object]:
    return {**SMOKE_INPUTS[task], **extra}


def test_happy_path_validates_logs_one_cost_row_and_tags(llm_db: str) -> None:
    clock = FakeClock()
    gemini = FakeProvider("gemini", [reply(OUTPUTS["classify_signal"], input_tokens=1200, output_tokens=150)])
    router = make_router({"gemini": gemini}, clock=clock)
    res = router.run("classify_signal", _inputs("classify_signal"))

    assert isinstance(res.output, SignalClassification) and res.output.role_category == "frontdesk"
    assert (res.provider, res.model, res.fallback_from, res.cached) == ("gemini", "gemini-3.5-flash-lite", None, False)
    assert res.tag == "gemini:gemini-3.5-flash-lite#classify_signal.v1"
    usd = llm_cost_usd("gemini-3.5-flash-lite", 1200, 150, on=router.budget.clock().date())
    rows = _costs(clock)
    assert len(rows) == 1
    assert rows[0]["provider"] == "gemini" and rows[0]["task"] == "classify_signal"
    assert float(rows[0]["usd"]) == pytest.approx(usd, abs=1e-6)
    assert float(rows[0]["inr"]) == pytest.approx(round(usd * 88, 2))  # costs.inr keeps 2 decimals
    assert res.inr == pytest.approx(usd * 88, abs=1e-3)

    req = gemini.calls[0]
    assert req.schema is SignalClassification
    assert req.thinking == "minimal"  # "off" maps to the lowest level this model accepts
    assert req.temperature is None  # Gemini 3.5 and newer ignore sampling parameters
    assert req.max_output_tokens == 500 + 512
    assert "Sunrise Dental Clinic" in req.user and "Rules that always apply" in req.system


def test_invalid_answer_gets_one_repair_on_the_same_model(llm_db: str) -> None:
    clock = FakeClock()
    gemini = FakeProvider("gemini", [reply('{"is_relevant": "maybe"}'), reply(OUTPUTS["classify_signal"])])
    router = make_router({"gemini": gemini}, clock=clock)
    res = router.run("classify_signal", _inputs("classify_signal"))
    assert res.model == "gemini-3.5-flash-lite"
    assert len(gemini.calls) == 2
    assert REPAIR_NOTE.split("{")[0].strip() in gemini.calls[1].user
    assert "is_relevant" in gemini.calls[1].user  # the validation errors are quoted back
    assert len(_costs(clock)) == 2  # both calls cost money


def test_answer_cut_off_at_the_cap_is_retried_with_more_room(llm_db: str) -> None:
    gemini = FakeProvider(
        "gemini", [reply('{"is_relevant": true, "role_cat', finish="max_tokens"), reply(OUTPUTS["classify_signal"])]
    )
    router = make_router({"gemini": gemini})
    router.run("classify_signal", _inputs("classify_signal"))
    first, second = gemini.calls
    assert second.max_output_tokens == first.max_output_tokens * 2
    assert TRUNCATED_NOTE.strip()[:40] in second.user


def test_transient_error_is_retried_then_succeeds(llm_db: str) -> None:
    clock = FakeClock()
    gemini = FakeProvider("gemini", [err("transient", "503 overloaded", status=503), reply(OUTPUTS["classify_signal"])])
    router = make_router({"gemini": gemini}, clock=clock)
    res = router.run("classify_signal", _inputs("classify_signal"))
    assert res.model == "gemini-3.5-flash-lite" and len(gemini.calls) == 2
    assert len(_costs(clock)) == 1
    assert router.availability.usable("gemini")


def test_bad_request_is_not_retried_and_the_next_model_answers(llm_db: str) -> None:
    clock = FakeClock()
    stats: dict[str, object] = {}
    gemini = FakeProvider(
        "gemini", [err("bad_request", "schema too complex", status=400), reply(OUTPUTS["classify_signal"])]
    )
    router = make_router({"gemini": gemini}, clock=clock, stats=stats)
    res = router.run("classify_signal", _inputs("classify_signal"))
    assert [c.model for c in gemini.calls] == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert res.model == "gemini-3.8-flash" and res.fallback_from == "gemini:gemini-3.5-flash-lite"
    assert gemini.calls[1].thinking == "low"  # 3.8 Flash refuses "minimal"
    assert stats["fallbacks"] == {"classify_signal": 1}
    assert stats["ai_errors"] == {"classify_signal:bad_request": 1}
    assert _costs(clock)[0]["fallback_from"] == "gemini:gemini-3.5-flash-lite"


def test_still_invalid_after_repair_moves_to_the_next_model(llm_db: str) -> None:
    clock = FakeClock()
    gemini = FakeProvider("gemini", [reply("nope"), reply("still nope"), reply(OUTPUTS["classify_signal"])])
    router = make_router({"gemini": gemini}, clock=clock)
    res = router.run("classify_signal", _inputs("classify_signal"))
    assert res.model == "gemini-3.8-flash"
    assert len(_costs(clock)) == 3


def test_cache_hit_logs_a_free_cache_row_and_makes_no_call(llm_db: str) -> None:
    clock = FakeClock()
    gemini = FakeProvider("gemini", [reply(OUTPUTS["classify_signal"])])
    router = make_router({"gemini": gemini}, clock=clock)
    first = router.run("classify_signal", _inputs("classify_signal"))
    second = router.run("classify_signal", _inputs("classify_signal"))
    assert len(gemini.calls) == 1
    assert second.cached and second.output == first.output and second.inr == 0
    assert second.model == "gemini-3.5-flash-lite" and second.tag == first.tag
    rows = _costs(clock)
    cache_rows = [r for r in rows if r["provider"] == "cache"]
    assert len(cache_rows) == 1 and float(cache_rows[0]["usd"]) == 0 and cache_rows[0]["calls"] == 1
    assert router.stats["cache_hits"] == {"classify_signal": 1}


def test_cache_is_skipped_when_disabled_or_ttl_is_zero(llm_db: str) -> None:
    out = OUTPUTS["classify_page_change"]
    gemini = FakeProvider(
        "gemini", [reply(out), reply(out), reply(OUTPUTS["classify_signal"]), reply(OUTPUTS["classify_signal"])]
    )
    router = make_router({"gemini": gemini})
    router.run("classify_page_change", _inputs("classify_page_change"))  # cache_ttl_days: 0
    router.run("classify_page_change", _inputs("classify_page_change"))
    router.run("classify_signal", _inputs("classify_signal"), use_cache=False)
    router.run("classify_signal", _inputs("classify_signal"), use_cache=False)
    assert len(gemini.calls) == 4


def test_cache_extra_separates_answers(llm_db: str) -> None:
    gemini = FakeProvider("gemini", [reply(OUTPUTS["classify_signal"]), reply(OUTPUTS["classify_signal"])])
    router = make_router({"gemini": gemini})
    router.run("classify_signal", _inputs("classify_signal"), cache_extra="hash-1")
    router.run("classify_signal", _inputs("classify_signal"), cache_extra="hash-2")
    assert len(gemini.calls) == 2


def test_lead_outputs_record_an_ai_output_activity(llm_db: str) -> None:
    lead_id = new_lead()
    gemini = FakeProvider("gemini", [reply(OUTPUTS["write_message"])])
    router = make_router({"gemini": gemini})
    res = router.run("write_message", _inputs("write_message"), lead_id=lead_id)
    row = db.fetch_one(
        "select source, type, payload from public.activities where lead_id = %s and type = 'ai_output'", [lead_id]
    )
    assert row is not None and row["source"] == "engine"
    assert row["payload"] == {
        "task": "write_message",
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "fallback_from": "openai:gpt-5-mini",
        "prompt_version": 1,
        "tag": res.tag,
    }


def test_classification_does_not_write_activities(llm_db: str) -> None:
    lead_id = new_lead()
    gemini = FakeProvider("gemini", [reply(OUTPUTS["classify_signal"])])
    make_router({"gemini": gemini}).run("classify_signal", _inputs("classify_signal"), lead_id=lead_id)
    assert db.scalar("select count(*) from public.activities where lead_id = %s and type = 'ai_output'", [lead_id]) == 0


def test_exclude_models_picks_a_different_critic(llm_db: str) -> None:
    """Step 12.9: the critic must not be the writer's model when another model can do it."""
    gemini = FakeProvider("gemini", [reply(OUTPUTS["check_message"])])
    router = make_router({"gemini": gemini})
    res = router.run("check_message", _inputs("check_message"), exclude_models={"gemini-3.8-flash"})
    assert isinstance(res.output, MessageCheck)
    assert res.model == "gemini-4-argon" and not res.preferred_model_excluded


def test_exclude_models_falls_back_to_the_writer_and_says_so(llm_db: str) -> None:
    gemini = FakeProvider("gemini", [reply(OUTPUTS["check_message"])])
    router = make_router({"gemini": gemini})
    res = router.run("check_message", _inputs("check_message"), models=[FLASH], exclude_models={"gemini-3.8-flash"})
    assert res.model == "gemini-3.8-flash" and res.preferred_model_excluded


def test_models_override_forces_a_model(llm_db: str) -> None:
    gemini = FakeProvider("gemini", [reply(OUTPUTS["judge_lead"])])
    router = make_router({"gemini": gemini})
    res = router.run("judge_lead", _inputs("judge_lead"), models=[FLASH])
    assert res.model == "gemini-3.8-flash" and res.fallback_from == "gemini:gemini-4-argon"
    with pytest.raises(KeyError, match="not declared"):
        router.run("judge_lead", _inputs("judge_lead"), models=[ModelRef(provider="gemini", model="gemini-9")])


def test_daily_limit_is_shared_by_the_classify_tasks(llm_db: str) -> None:
    db.set_setting("ai.classify_per_day", 2)
    gemini = FakeProvider("gemini", [reply(OUTPUTS["classify_signal"]), reply(OUTPUTS["classify_news"])])
    router = make_router({"gemini": gemini})
    router.run("classify_signal", _inputs("classify_signal"), use_cache=False)
    router.run("classify_news", _inputs("classify_news"), use_cache=False)
    with pytest.raises(BudgetExceeded, match=r"ai\.classify_per_day = 2"):
        router.run("classify_page_change", _inputs("classify_page_change"))
    assert len(gemini.calls) == 2


def test_budget_refusal_happens_before_any_call(llm_db: str) -> None:
    db.set_setting("daily_cap_inr", 0.0001)
    gemini = FakeProvider("gemini", [])
    router = make_router({"gemini": gemini})
    with pytest.raises(BudgetExceeded):
        router.run("judge_lead", _inputs("judge_lead"))
    assert gemini.calls == []


def test_missing_prompt_input_is_a_clear_error(llm_db: str) -> None:
    router = make_router({"gemini": FakeProvider("gemini")})
    with pytest.raises(KeyError, match="missing inputs text"):
        router.run("classify_signal", {k: v for k, v in _inputs("classify_signal").items() if k != "text"})


def test_grounded_search_makes_a_search_call_then_a_structuring_call(llm_db: str) -> None:
    clock = FakeClock()
    grounding = {
        "queries": ["clinic whatsapp bot developer pune", "dentist booking software india"],
        "sources": [
            {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "forum.example.com"}
        ],
        "supports": [],
    }
    answer = "1. Smile Care Clinic, Pune: looking for someone to build a WhatsApp booking bot. https://forum.example.com/t/123"
    gemini = FakeProvider(
        "gemini",
        [reply(answer, input_tokens=300, output_tokens=900, grounding=grounding), reply(OUTPUTS["grounded_search"])],
    )
    router = make_router({"gemini": gemini}, clock=clock)
    res = router.run("grounded_search", _inputs("grounded_search"))

    assert isinstance(res.output, PublicAskResults) and res.output.items[0].url == "https://forum.example.com/t/123"
    assert res.model == "gemini-3.8-flash" and res.grounding == grounding
    search, structure = gemini.calls
    assert (search.model, search.tools, search.schema) == ("gemini-3.8-flash", ["web_search"], None)
    assert (structure.model, structure.tools, structure.schema) == ("gemini-3.5-flash-lite", [], PublicAskResults)
    assert structure.thinking == "minimal"
    assert answer in structure.user and "forum.example.com" in structure.user
    rows = _costs(clock)
    by_provider = {(r["provider"], r["model"]): r for r in rows}
    assert by_provider[("google_search", "gemini-3.8-flash")]["calls"] == 2
    assert by_provider[("google_search", "gemini-3.8-flash")]["task"] == "grounded_search"
    assert {("gemini", "gemini-3.8-flash"), ("gemini", "gemini-3.5-flash-lite")} <= set(by_provider)
    assert all(r["task"] == "grounded_search" for r in rows)


def test_grounded_search_stops_when_the_query_quota_is_used(llm_db: str) -> None:
    db.set_setting("grounding_daily_cap", 0)
    gemini = FakeProvider("gemini", [])
    with pytest.raises(BudgetExceeded, match="quota"):
        make_router({"gemini": gemini}).run("grounded_search", _inputs("grounded_search"))
    assert gemini.calls == []


def test_request_building_maps_thinking_sampling_and_headroom() -> None:
    registry = load_registry("balanced")
    router = Router(registry=registry, providers={}, availability=object(), budget=object())  # type: ignore[arg-type]
    judge = registry.task("judge_lead")
    req = router.request(judge, registry.spec(ARGON), "s", "u", None)
    assert (req.thinking, req.max_output_tokens, req.temperature) == ("low", 1200 + 2048, None)
    audit = registry.task("weekly_audit")
    assert router.request(audit, registry.spec(ARGON), "s", "u", None).thinking == "medium"
    classify = registry.task("classify_signal")
    assert router.request(classify, registry.spec(FLASH), "s", "u", None).thinking == "low"
    assert router.request(classify, registry.spec(LITE), "s", "u", None).thinking == "minimal"


def test_unknown_task_is_a_key_error(llm_db: str) -> None:
    with pytest.raises(KeyError, match="unknown AI task"):
        make_router({"gemini": FakeProvider("gemini")}).run("summarise_universe", {})
