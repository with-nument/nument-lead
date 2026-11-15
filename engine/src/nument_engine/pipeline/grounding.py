"""Grounded search shared out per use (15 Nov 2026): about 145 of the free 5,000 queries a month each day.

| use            | setting                              | default | AI tasks that spend it   |
|----------------|--------------------------------------|---------|--------------------------|
| asks           | grounding.asks_per_day               | 60      | grounded_search          |
| lookup         | grounding.lookup_per_day             | 40      | find_website             |
| people         | grounding.people_per_day             | 30      | find_decision_maker      |
| email_snippets | grounding.email_snippets_per_day     | 15      | find_founder_email       |

Contract (task 0): stages call `allowance(use, budget)` before spending and stop at zero. Until the per-use
count and the month pacing are built (lane E1b), `allowance` is the use's daily setting capped by the day's
total grounded queries left.
"""

from __future__ import annotations

from typing import Any

from .. import db

USES: dict[str, int] = {"asks": 60, "lookup": 40, "people": 30, "email_snippets": 15}
USE_TASKS: dict[str, tuple[str, ...]] = {
    "asks": ("grounded_search",),
    "lookup": ("find_website",),
    "people": ("find_decision_maker",),
    "email_snippets": ("find_founder_email",),
}


def per_day(use: str) -> int:
    """The use's daily share (settings grounding.<use>_per_day)."""
    if use not in USES:
        raise ValueError(f"unknown grounding use {use!r}; one of {', '.join(USES)}")
    return int(db.get_setting(f"grounding.{use}_per_day", USES[use]))


def allowance(use: str, budget: Any | None = None) -> int:
    """Grounded searches this use may still make today (0 = stop)."""
    left = per_day(use)
    if budget is not None and hasattr(budget, "grounding_quota_left"):
        left = min(left, int(budget.grounding_quota_left()))
    return max(left, 0)
