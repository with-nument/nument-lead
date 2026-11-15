"""Grounded search per use and month pacing (lane E1b, 15 Nov 2026): every query is logged under the AI task that
made it, each use spends only its daily share, and each day gets the month's remaining free queries divided by
the days left, so the free 5,000 a month last until the last day."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from nument_engine import db
from nument_engine.budget import Budget, month_pace
from nument_engine.pipeline import grounding

from .llm_fakes import FakeClock, llm_db_fixture  # noqa: F401


def at(day: str, hour_utc: int = 6) -> datetime:
    """A moment on that day (06:00 UTC is 11:30 IST: the same IST day)."""
    return datetime.fromisoformat(day).replace(hour=hour_utc, minute=30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("left", "now", "expected"),
    [
        (5000, at("2040-11-01"), 167),  # 30 days left, rounded up
        (5000, at("2040-12-01"), 162),  # 31 days in December
        (300, at("2040-11-25"), 50),  # 6 days left
        (157, at("2040-11-30"), 157),  # the last day takes what is left
        (40, at("2040-02-29"), 40),  # leap year: the 29th is the last day
        (5000, datetime(2040, 11, 30, 19, 0, tzinfo=UTC), 162),  # 00:30 IST on 1 December: a new month
        (0, at("2040-11-10"), 0),
        (-25, at("2040-11-10"), 0),  # over the allowance already
    ],
)
def test_month_pace(left: int, now: datetime, expected: int) -> None:
    assert month_pace(left, now) == expected


def spend(budget: Budget, clock: FakeClock, when: datetime, queries: int, task: str | None = None) -> None:
    """Log queries at another moment, then put the clock back."""
    now = clock.now
    clock.now = when
    budget.record_search("gemini", "gemini-3.8-flash", queries, task=task)
    clock.now = now


def test_the_day_gets_its_share_of_what_the_month_has_left(llm_db: str) -> None:
    clock = FakeClock(at("2040-11-25"))
    budget = Budget(clock=clock)
    assert budget.grounding_quota_left() == 160  # nothing spent: the daily cap is the smallest room
    spend(budget, clock, at("2040-11-03"), 4_700)
    assert budget.grounding_quota_left() == 50  # 300 left at the start of today, 6 days to go
    budget.record_search("gemini", "gemini-3.8-flash", 20, task="find_website")
    assert budget.grounding_quota_left() == 30  # today's pace is fixed when the day starts


def test_month_end_and_the_first_day_of_the_next_month(llm_db: str) -> None:
    clock = FakeClock(at("2040-11-30"))
    budget = Budget(clock=clock)
    spend(budget, clock, at("2040-11-10"), 4_900)
    assert budget.grounding_quota_left() == 100  # the last day: everything still free
    budget.record_search("gemini", "gemini-3.8-flash", 100)
    assert budget.grounding_quota_left() == 0
    clock.now = at("2040-12-01")
    assert budget.grounding_quota_left() == 160  # a new month: 5,000 / 31 = 162, the daily cap is lower


def test_nothing_is_left_once_the_free_allowance_is_spent(llm_db: str) -> None:
    clock = FakeClock(at("2040-11-20"))
    budget = Budget(clock=clock)
    spend(budget, clock, at("2040-11-05"), 5_000)
    assert budget.grounding_quota_left() == 0
    spend(budget, clock, at("2040-11-06"), 40)  # an overrun (another process) never makes the room negative
    assert budget.grounding_quota_left() == 0


def test_each_search_is_logged_under_its_task_and_counted_per_use(llm_db: str) -> None:
    clock = FakeClock(at("2040-11-20"))
    budget = Budget(clock=clock)
    budget.record_search("gemini", "gemini-3.8-flash", 7, task="find_website")
    budget.record_search("gemini", "gemini-3.8-flash", 2)  # no task: the asks task, as before
    rows = db.fetch_all("select task, calls from public.costs where at = %s order by task", [clock.now])
    assert [(r["task"], r["calls"]) for r in rows] == [("find_website", 7), ("grounded_search", 2)]
    assert budget.searches_today() == 9 and budget.searches_today(["find_website"]) == 7
    assert grounding.used_today("lookup", budget) == 7
    assert grounding.allowance("lookup", budget) == 33
    assert grounding.allowance("asks", budget) == 58
    assert grounding.allowance("people", budget) == 30  # other uses keep their whole share
    db.set_setting("grounding_daily_cap", 12)
    budget.reload_settings()
    assert grounding.allowance("people", budget) == 3  # the day's total is the hard limit


def test_a_search_beyond_the_free_allowance_is_priced(llm_db: str) -> None:
    clock = FakeClock(at("2040-11-20"))
    budget = Budget(clock=clock)
    spend(budget, clock, at("2040-11-02"), 4_999, task="find_decision_maker")
    inr = budget.record_search("gemini", "gemini-3.8-flash", 3, task="grounded_search")
    assert inr == pytest.approx(budget.usd_to_inr(2 * 14 / 1000))  # every task shares the free 5,000


class _CountingBudget:
    def __init__(self, used: dict[str, int], left: int) -> None:
        self.used = used
        self.left = left

    def searches_today(self, tasks: Any) -> int:
        return sum(self.used.get(t, 0) for t in tasks)

    def grounding_quota_left(self) -> int:
        return self.left


def test_allowance_with_a_budget_that_counts_per_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "get_setting", lambda key, default=None, **_: default)
    budget = _CountingBudget({"find_website": 38, "grounded_search": 70}, left=100)
    assert grounding.allowance("lookup", budget) == 2
    assert grounding.allowance("asks", budget) == 0  # over its share (set lower during the day): stop
    assert grounding.allowance("email_snippets", budget) == 15
    assert grounding.allowance("email_snippets", _CountingBudget({}, left=4)) == 4
