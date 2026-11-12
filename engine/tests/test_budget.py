"""Budget guard (Steps 4.11 and 19): cost maths, the degradation ladder, caps, alerts, reservations and quotas."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from nument_engine import db
from nument_engine.budget import (
    PHASE_STOP_AT,
    PRIORITY_STOP_AT,
    Budget,
    BudgetExceeded,
    estimate_tokens,
    ist_day_start,
    ist_today,
    llm_cost_usd,
    load_prices,
    places_cost_usd,
    places_task,
    search_cost_usd,
)

from .llm_fakes import FakeClock, llm_db_fixture, new_run  # noqa: F401

# ---------------------------------------------------------------------------
# Prices and cost maths (no database)
# ---------------------------------------------------------------------------


def test_prices_file_is_valid_and_dated() -> None:
    prices = load_prices()
    assert prices.verified_on >= date(2026, 11, 12)
    assert prices.batch_discount == 0.5
    for name in ("gemini-4-argon", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gpt-5-mini"):
        assert name in prices.models


def test_cost_formula_tokens_batch_and_cache() -> None:
    day = date(2026, 11, 20)
    # gemini-3.5-flash-lite: $0.30 in, $2.50 out, $0.03 cached input per 1M
    assert llm_cost_usd("gemini-3.5-flash-lite", 1_000_000, 0, on=day) == pytest.approx(0.30)
    assert llm_cost_usd("gemini-3.5-flash-lite", 0, 1_000_000, on=day) == pytest.approx(2.50)
    sync = llm_cost_usd("gemini-3.8-flash", 16_000, 2_000, on=day)
    assert llm_cost_usd("gemini-3.8-flash", 16_000, 2_000, batch=True, on=day) == pytest.approx(sync / 2)
    assert llm_cost_usd("gemini-3.8-flash", 16_000, 2_000, flex=True, on=day) == pytest.approx(sync / 2)
    cached = llm_cost_usd("gemini-3.5-flash-lite", 10_000, 0, cached_tokens=8_000, on=day)
    assert cached == pytest.approx((2_000 * 0.30 + 8_000 * 0.03) / 1e6)


def test_thinking_tokens_are_billed_as_output() -> None:
    """The router passes output = answer + thinking; the formula prices all of it at the output rate."""
    day = date(2026, 11, 20)
    answer, thinking = 300, 900
    assert llm_cost_usd("gemini-4-argon", 0, answer + thinking, on=day) == pytest.approx(1_200 * 10.0 / 1e6)


def test_announced_price_changes_apply_from_their_date() -> None:
    assert llm_cost_usd("gemini-4-argon", 1_000_000, 0, on=date(2026, 11, 30)) == pytest.approx(2.0)
    assert llm_cost_usd("gemini-4-argon", 1_000_000, 0, on=date(2026, 12, 1)) == pytest.approx(4.0)
    assert llm_cost_usd("gemini-3.8-flash", 0, 1_000_000, on=date(2026, 12, 31)) == pytest.approx(3.75)
    assert llm_cost_usd("gemini-3.8-flash", 0, 1_000_000, on=date(2027, 1, 1)) == pytest.approx(7.50)


def test_unknown_model_price_is_an_error() -> None:
    with pytest.raises(KeyError, match="no price"):
        llm_cost_usd("gemini-9-imaginary", 10, 10)


def test_search_cost_only_beyond_the_monthly_free_allowance() -> None:
    assert search_cost_usd("gemini", 3, used_this_month=100) == 0.0
    assert search_cost_usd("gemini", 3, used_this_month=4_999) == pytest.approx(2 * 14 / 1000)
    assert search_cost_usd("gemini", 3, used_this_month=6_000) == pytest.approx(3 * 14 / 1000)
    assert search_cost_usd("openai", 2) == pytest.approx(2 * 10 / 1000)


def test_places_cost_inside_and_beyond_free_calls() -> None:
    assert places_cost_usd("text_search_ids_only", 500) == 0.0
    assert places_cost_usd("place_details_enterprise", 10, used_this_month=100) == 0.0
    assert places_cost_usd("place_details_enterprise", 10, used_this_month=6_995) == pytest.approx(5 * 6.0 / 1000)
    assert places_cost_usd("place_details_enterprise", 1, used_this_month=2_000, region="global") == pytest.approx(
        20.0 / 1000
    )
    assert places_task("details", "in") == "places_details"
    assert places_task("details", "ae") == "places_details_global"


def test_estimate_tokens() -> None:
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("x" * 400, script="devanagari") == 200


def test_ist_day_boundaries() -> None:
    late_utc = datetime(2026, 11, 12, 19, 0, tzinfo=UTC)  # 00:30 IST on the 13th
    assert ist_today(late_utc) == date(2026, 11, 13)
    assert ist_day_start(late_utc).isoformat() == "2026-11-13T00:00:00+05:30"


# ---------------------------------------------------------------------------
# The ladder (Step 19.6, 19.10 test_threshold_ladder)
# ---------------------------------------------------------------------------


def _spend(budget: Budget, inr: float) -> None:
    budget.record("other", "test", "spend_fixture", usd=inr / budget.fx)


def _blocked(budget: Budget, priority: int, est: float = 0.01) -> bool:
    try:
        budget.check("t", priority, est)
    except BudgetExceeded:
        return True
    return False


@pytest.mark.parametrize(
    ("priority", "stop_at"),
    sorted(PRIORITY_STOP_AT.items()),
)
def test_each_priority_stops_exactly_at_its_threshold(llm_db: str, priority: int, stop_at: float) -> None:
    db.set_setting("daily_cap_inr", 100)
    budget = Budget(clock=FakeClock())
    _spend(budget, stop_at * 100 - 1)
    assert not _blocked(budget, priority, est=0.5)
    _spend(budget, 1)
    assert _blocked(budget, priority, est=0.01)


def test_plan_examples_for_80_95_and_100_percent(llm_db: str) -> None:
    """Step 4.13 test 14 with the ladder of Step 19.6: at 79% a priority 5 task runs; at 81% audits stop;
    at 86% grounded search stops; at 96% only messages run; at the cap nothing paid runs."""
    db.set_setting("daily_cap_inr", 100)
    budget = Budget(clock=FakeClock())
    _spend(budget, 79)
    assert not _blocked(budget, 5) and not _blocked(budget, 6)
    _spend(budget, 2)  # 81
    assert _blocked(budget, 6) and not _blocked(budget, 5)
    _spend(budget, 5)  # 86
    assert _blocked(budget, 5) and not _blocked(budget, 4)
    _spend(budget, 10)  # 96
    assert all(_blocked(budget, p) for p in (2, 3, 4)) and not _blocked(budget, 1)
    _spend(budget, 4)  # 100
    assert _blocked(budget, 1)


def test_priority_one_reserve_is_opt_in(llm_db: str) -> None:
    db.set_setting("daily_cap_inr", 100)
    db.set_setting("budget_p1_reserve_inr", 50)
    budget = Budget(clock=FakeClock())
    _spend(budget, 100)
    assert not _blocked(budget, 1, est=10)  # inside the ₹50 reserve
    assert _blocked(budget, 2)
    _spend(budget, 45)
    assert _blocked(budget, 1, est=10)  # 145 + 10 > 150


def test_a_call_that_would_cross_the_limit_is_refused(llm_db: str) -> None:
    db.set_setting("daily_cap_inr", 100)
    budget = Budget(clock=FakeClock())
    _spend(budget, 90)
    with pytest.raises(BudgetExceeded, match="priority 2"):
        budget.check("judge_lead", 2, est_inr=6)  # 96 > 95
    budget.check("judge_lead", 2, est_inr=4)


def test_phases_follow_the_ladder(llm_db: str) -> None:
    db.set_setting("daily_cap_inr", 100)
    budget = Budget(clock=FakeClock())
    assert all(budget.allow_phase(p) for p in PHASE_STOP_AT)
    _spend(budget, 61)
    assert not budget.allow_phase("fit_only_research") and budget.allow_phase("low_priority_research")
    _spend(budget, 15)  # 76
    assert not budget.allow_phase("low_priority_research") and budget.allow_phase("grounded_search")
    _spend(budget, 10)  # 86
    assert not budget.allow_phase("grounded_search") and budget.allow_phase("judge")
    _spend(budget, 10)  # 96
    assert not budget.allow_phase("research") and budget.allow_phase("message")
    with pytest.raises(BudgetExceeded):
        budget.check_phase("extract")
    with pytest.raises(ValueError, match="unknown budget phase"):
        budget.allow_phase("lunch")


def test_per_run_cap_stops_every_paid_call(llm_db: str) -> None:
    """Step 4.13 test 15: with --max-spend-inr 5 the call that would pass ₹5 is refused, whatever the cap."""
    run_id = new_run()
    budget = Budget(run_id, max_spend_inr=5, clock=FakeClock())
    budget.record("gemini", "gemini-3.8-flash", "judge_lead", usd=4.0 / budget.fx)
    budget.check("write_message", 1, est_inr=0.9)
    with pytest.raises(BudgetExceeded, match="max-spend-inr 5"):
        budget.check("write_message", 1, est_inr=1.1)
    other_run = Budget(new_run(), max_spend_inr=5, clock=budget.clock)
    other_run.check("write_message", 1, est_inr=1.1)  # another run has its own allowance


def test_snapshot_sees_spend_from_other_processes_after_refresh(llm_db: str) -> None:
    db.set_setting("daily_cap_inr", 100)
    clock = FakeClock()
    budget = Budget(clock=clock, refresh_s=3600)
    budget.check("t", 2, est_inr=1)
    other = Budget(clock=clock)
    _spend(other, 99)
    budget.check("t", 2, est_inr=1)  # cached snapshot: does not see it yet
    budget.refresh()
    assert _blocked(budget, 2)


# ---------------------------------------------------------------------------
# Alerts (19.10 test_alert_once)
# ---------------------------------------------------------------------------


def test_alert_fires_once_per_ist_day(llm_db: str) -> None:
    db.set_setting("daily_cap_inr", 100)
    clock = FakeClock()
    stats: dict[str, object] = {}
    budget = Budget(clock=clock, stats=stats)
    _spend(budget, 70)
    budget.check("t", 1, est_inr=1)
    assert "alerts" not in stats
    _spend(budget, 15)
    budget.check("t", 1, est_inr=1)
    budget.check("t", 1, est_inr=1)
    assert len(stats["alerts"]) == 1  # type: ignore[arg-type]
    assert "86%" in stats["alerts"][0]  # type: ignore[index]  (85 spent plus the 1 being checked)
    assert db.get_setting("budget_alert_day") == ist_today(clock()).isoformat()
    second = Budget(clock=clock, stats=stats)  # a second process the same day
    second.check("t", 1, est_inr=1)
    assert len(stats["alerts"]) == 1  # type: ignore[arg-type]
    clock.advance(days=1)
    _spend(budget, 85)
    third = Budget(clock=clock, stats=stats)
    third.check("t", 1, est_inr=1)
    assert len(stats["alerts"]) == 2  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Batch reservations (Step 4.13 test 16)
# ---------------------------------------------------------------------------


def _batch_row() -> str:
    row = db.fetch_one(
        "insert into public.llm_batches (provider, provider_batch_id, task, item_count) "
        "values ('gemini', gen_random_uuid()::text, 'extract_facts', 300) returning id::text as id"
    )
    assert row is not None
    return str(row["id"])


def test_reservations_hold_money_until_released(llm_db: str) -> None:
    db.set_setting("daily_cap_inr", 100)
    budget = Budget(clock=FakeClock())
    first = _batch_row()
    budget.reserve(first, 60)
    assert budget.reserved_inr() == pytest.approx(60)
    assert budget.committed_inr() == pytest.approx(60)
    with pytest.raises(BudgetExceeded):
        budget.check("extract_facts", 3, est_inr=40)  # a second 300-item batch would cross the limit
    assert budget.affordable("extract_facts", 3, [10, 10, 10, 10]) == 3  # 60 + 30 <= 95
    assert budget.release(first) == pytest.approx(60)
    assert budget.reserved_inr() == 0
    assert budget.release(first) == 0  # releasing twice is harmless
    budget.refresh()
    assert budget.reserved_inr() == 0


def test_affordable_respects_the_run_cap(llm_db: str) -> None:
    budget = Budget(new_run(), max_spend_inr=3, clock=FakeClock())
    assert budget.affordable("extract_facts", 3, [1.0, 1.0, 1.0, 1.0]) == 3
    assert budget.affordable("extract_facts", 3, []) == 0


# ---------------------------------------------------------------------------
# Logging and quotas (19.10 test_quota_left)
# ---------------------------------------------------------------------------


def test_record_writes_usd_inr_and_fallback(llm_db: str) -> None:
    run_id = new_run()
    budget = Budget(run_id, clock=FakeClock())
    inr = budget.record(
        "gemini", "gemini-3.8-flash", "write_message", input_tokens=10, output_tokens=5, usd=0.01,
        fallback_from="openai:gpt-5-mini",
    )  # fmt: skip
    assert inr == pytest.approx(0.88)
    row = db.fetch_one("select * from public.costs where run_id = %s", [run_id])
    assert row is not None
    assert (row["provider"], row["task"], row["fallback_from"]) == ("gemini", "write_message", "openai:gpt-5-mini")
    assert float(row["usd"]) == pytest.approx(0.01) and float(row["inr"]) == pytest.approx(0.88)
    assert row["at"] == budget.clock()


def test_quota_left_takes_the_smaller_of_day_and_month(llm_db: str) -> None:
    clock = FakeClock()
    budget = Budget(clock=clock)
    budget.record("google_search", "m", "grounded_search", calls=40)
    assert budget.quota_left("google_search", "grounded_search", per_day=160, per_month=5000) == 120
    assert budget.quota_left("google_search", "grounded_search", per_day=160, per_month=100) == 60
    clock.advance(days=1)
    assert budget.quota_left("google_search", "grounded_search", per_day=160, per_month=100) == 60
    assert budget.quota_left("google_search", "grounded_search", per_day=10, per_month=None) == 10
    assert budget.quota_left("google_search", "grounded_search", per_day=None, per_month=None) > 10**8


def test_grounding_quota_uses_settings_and_the_free_allowance(llm_db: str) -> None:
    budget = Budget(clock=FakeClock())
    assert budget.grounding_quota_left() == 160
    db.set_setting("grounding_daily_cap", 50)
    budget.reload_settings()
    budget.record_search("gemini", "gemini-3.8-flash", 3)
    assert budget.grounding_quota_left() == 47
    row = db.fetch_one("select provider, task, calls, usd from public.costs where at = %s", [budget.clock()])
    assert row is not None and (row["provider"], row["task"], row["calls"]) == ("google_search", "grounded_search", 3)
    assert float(row["usd"]) == 0.0


def test_places_quota_daily_cap_and_monthly_free_calls(llm_db: str) -> None:
    clock = FakeClock()
    budget = Budget(clock=clock)
    assert budget.places_quota_left("details", "in") == 230
    assert budget.places_quota_left("details", "ae") == 30
    assert budget.record_places("details", "in", calls=200) == 0.0
    assert budget.places_quota_left("details", "in") == 30
    assert budget.places_quota_left("details", "ae") == 30  # separate daily cap abroad
    clock.advance(days=-5)  # earlier this month
    budget.record("google_places", "place_details_enterprise", "places_details", calls=6_790)
    clock.advance(days=5)
    assert budget.places_quota_left("details", "ae") == 10  # 7,000 free a month, shared by every country
    inr = budget.record_places("details", "ae", calls=20)
    assert inr == pytest.approx(10 * 6.0 / 1000 * 88)  # 10 of the 20 calls are past the free allowance


def test_pagespeed_quota(llm_db: str) -> None:
    budget = Budget(clock=FakeClock())
    assert budget.pagespeed_quota_left() == 600
    budget.record_pagespeed(calls=5)
    assert budget.pagespeed_quota_left() == 595
