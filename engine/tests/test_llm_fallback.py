"""Provider fallback and circuit breakers (Step 4.5, 4.13 tests 6 to 11)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from nument_engine import db
from nument_engine.llm.availability import Availability
from nument_engine.llm.health import SMOKE_INPUTS
from nument_engine.llm.types import AllProvidersDown

from .llm_fakes import FakeClock, FakeProvider, err, llm_db_fixture, make_router, reply  # noqa: F401
from .llm_outputs import OUTPUTS


def _health(provider: str) -> dict[str, object]:
    row = db.fetch_one("select * from public.source_health where source = %s", [f"llm:{provider}"])
    assert row is not None
    return row


def test_openai_switched_off_write_message_is_answered_by_gemini(llm_db: str) -> None:
    """Test 6: providers_enabled.openai = false, the key exists, OpenAI is never called."""
    clock = FakeClock()
    openai = FakeProvider("openai", [])
    gemini = FakeProvider("gemini", [reply(OUTPUTS["write_message"])])
    router = make_router({"gemini": gemini, "openai": openai}, clock=clock, enabled={"gemini": True, "openai": False})
    res = router.run("write_message", SMOKE_INPUTS["write_message"])
    assert openai.calls == []
    assert (res.provider, res.model, res.fallback_from) == ("gemini", "gemini-3.8-flash", "openai:gpt-5-mini")
    row = db.fetch_one("select provider, model, fallback_from from public.costs where at = %s", [clock()])
    assert row == {"provider": "gemini", "model": "gemini-3.8-flash", "fallback_from": "openai:gpt-5-mini"}


def test_openai_key_missing_gives_the_same_result(llm_db: str) -> None:
    """Test 7: OpenAI switched on but no key."""
    gemini = FakeProvider("gemini", [reply(OUTPUTS["write_message"])])
    router = make_router({"gemini": gemini}, enabled={"gemini": True, "openai": True})
    res = router.run("write_message", SMOKE_INPUTS["write_message"])
    assert (res.model, res.fallback_from) == ("gemini-3.8-flash", "openai:gpt-5-mini")


def test_openai_is_used_when_switched_on_and_working(llm_db: str) -> None:
    openai = FakeProvider("openai", [reply(OUTPUTS["write_message"], provider="openai")])
    router = make_router({"gemini": FakeProvider("gemini"), "openai": openai}, enabled={"gemini": True, "openai": True})
    res = router.run("write_message", SMOKE_INPUTS["write_message"])
    assert (res.provider, res.model, res.fallback_from) == ("openai", "gpt-5-mini", None)
    assert openai.calls[0].thinking == "low" and openai.calls[0].temperature is None


def test_primary_failing_after_retries_moves_to_the_next_model(llm_db: str) -> None:
    """Test 8: three 503s (after retries) on the primary, then the next model in the chain answers."""
    stats: dict[str, object] = {}
    failures = [err("transient", "503", status=503)] * 4  # max_retries 3 means 4 attempts
    gemini = FakeProvider("gemini", [*failures, reply(OUTPUTS["classify_signal"])])
    router = make_router({"gemini": gemini}, stats=stats)
    res = router.run("classify_signal", SMOKE_INPUTS["classify_signal"])
    assert [c.model for c in gemini.calls] == ["gemini-3.5-flash-lite"] * 4 + ["gemini-3.8-flash"]
    assert res.model == "gemini-3.8-flash"
    assert stats["ai_errors"] == {"classify_signal:transient": 1}
    assert router.availability.usable("gemini")  # the provider answered, so its breaker stays closed


def test_breaker_opens_after_three_failures_and_closes_after_a_good_trial(llm_db: str) -> None:
    """Test 9 with a fake clock: 3 failed calls open OpenAI for 15 minutes, then a trial call closes it."""
    clock = FakeClock()
    transient = err("transient", "503", provider="openai", status=503)
    openai = FakeProvider("openai", [transient] * 9)  # 3 calls x 3 attempts (max_retries 2)
    gemini = FakeProvider("gemini", [reply(OUTPUTS["write_message"])] * 4)
    router = make_router({"gemini": gemini, "openai": openai}, clock=clock, enabled={"gemini": True, "openai": True})
    for _ in range(3):
        assert router.run("write_message", SMOKE_INPUTS["write_message"]).model == "gemini-3.8-flash"
    assert len(openai.calls) == 9
    assert not router.availability.usable("openai")
    blocked = _health("openai")["blocked_until"]
    assert blocked is not None and blocked > clock()

    router.run("write_message", SMOKE_INPUTS["write_message"])  # breaker open: OpenAI is skipped
    assert len(openai.calls) == 9

    clock.advance(minutes=16)
    openai.replies = [reply(OUTPUTS["write_message"], provider="openai")]
    res = router.run("write_message", SMOKE_INPUTS["write_message"])
    assert res.provider == "openai" and router.availability.usable("openai")
    assert _health("openai")["blocked_until"] is None


def test_failed_trial_reopens_for_twice_as_long(llm_db: str) -> None:
    clock = FakeClock()
    transient = err("transient", "503", provider="openai", status=503)
    openai = FakeProvider("openai", [transient] * 12)
    gemini = FakeProvider("gemini", [reply(OUTPUTS["write_message"])] * 4)
    router = make_router({"gemini": gemini, "openai": openai}, clock=clock, enabled={"gemini": True, "openai": True})
    for _ in range(3):
        router.run("write_message", SMOKE_INPUTS["write_message"])
    clock.advance(minutes=16)
    router.run("write_message", SMOKE_INPUTS["write_message"])  # failed trial
    breaker = router.availability.breakers["openai"]
    assert breaker.open_until is not None and breaker.open_until - clock() == timedelta(minutes=30)


def test_auth_error_opens_the_breaker_for_six_hours_and_persists(llm_db: str) -> None:
    """Test 10: a 401 opens at once for 6 hours, stored in source_health, respected by the next run."""
    clock = FakeClock()
    openai = FakeProvider("openai", [err("auth", "401 Incorrect API key", provider="openai", status=401)])
    gemini = FakeProvider("gemini", [reply(OUTPUTS["write_message"])])
    router = make_router({"gemini": gemini, "openai": openai}, clock=clock, enabled={"gemini": True, "openai": True})
    router.run("write_message", SMOKE_INPUTS["write_message"])
    assert len(openai.calls) == 1  # auth errors are not retried
    row = _health("openai")
    assert row["blocked_until"] == clock() + timedelta(hours=6)
    assert "auth" in str(row["last_error"])

    db.set_setting("providers_enabled", {"gemini": True, "openai": True})
    next_run = Availability.load(has_key={"gemini": True, "openai": True}, app_env="dev", clock=clock)
    assert not next_run.usable("openai") and next_run.usable("gemini")
    clock.advance(hours=6, minutes=1)
    assert next_run.usable("openai")


def test_every_model_failing_raises_all_providers_down(llm_db: str) -> None:
    """Test 11: the step gets AllProvidersDown with what was tried, and the run stat is counted."""
    stats: dict[str, object] = {}
    gemini = FakeProvider("gemini", [err("bad_request", "no"), err("bad_request", "no")])
    router = make_router({"gemini": gemini}, stats=stats)
    with pytest.raises(AllProvidersDown) as caught:
        router.run("classify_signal", SMOKE_INPUTS["classify_signal"])
    text = str(caught.value)
    assert "gemini:gemini-3.5-flash-lite bad_request" in text
    assert "openai:gpt-5-nano skipped (providers_enabled.openai = false)" in text
    assert stats["all_providers_down"] == {"classify_signal": 1}


def test_missing_model_is_skipped_for_the_run_without_tripping_the_provider(llm_db: str) -> None:
    gemini = FakeProvider(
        "gemini",
        [err("not_found", "404 models/gemini-3.5-flash-lite is not found"), reply(OUTPUTS["classify_signal"]),
         reply(OUTPUTS["classify_news"])],
    )  # fmt: skip
    router = make_router({"gemini": gemini})
    router.run("classify_signal", SMOKE_INPUTS["classify_signal"])
    router.run("classify_news", SMOKE_INPUTS["classify_news"])
    assert [c.model for c in gemini.calls] == ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.8-flash"]
    assert router.availability.usable("gemini")


def test_one_overloaded_model_is_paused_while_the_provider_keeps_working(llm_db: str) -> None:
    clock = FakeClock()
    slow = err("transient", "503 model overloaded", status=503)
    script = []
    for _ in range(3):
        script += [slow] * 4 + [reply(OUTPUTS["classify_signal"])]
    script.append(reply(OUTPUTS["classify_signal"]))
    gemini = FakeProvider("gemini", script)
    router = make_router({"gemini": gemini}, clock=clock)
    for n in range(4):
        router.run("classify_signal", {**SMOKE_INPUTS["classify_signal"], "url": f"https://example.com/jobs/{n}"})
    lite_calls = [c for c in gemini.calls if c.model == "gemini-3.5-flash-lite"]
    assert len(lite_calls) == 12  # the 4th call skipped the paused model
    assert router.availability.usable("gemini")
    assert "paused" in str(router.availability.model_reason("gemini", "gemini-3.5-flash-lite"))
    clock.advance(minutes=16)
    assert router.availability.model_reason("gemini", "gemini-3.5-flash-lite") is None


def test_settings_switch_mirrors_into_source_health(llm_db: str) -> None:
    db.set_setting("providers_enabled", {"gemini": True, "openai": False})
    Availability.load(has_key={"gemini": True, "openai": True}, app_env="prod")
    assert _health("openai")["enabled"] is False and _health("gemini")["enabled"] is True
