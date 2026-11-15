"""Grounded search is shared out per use; stages ask for their allowance before spending."""

from __future__ import annotations

from typing import Any

import pytest

from nument_engine import db
from nument_engine.pipeline import grounding


class _Budget:
    def __init__(self, left: int) -> None:
        self.left = left

    def grounding_quota_left(self) -> int:
        return self.left


def test_uses_add_up_to_the_daily_plan() -> None:
    assert sum(grounding.USES.values()) == 145 and set(grounding.USES) == set(grounding.USE_TASKS)


def test_allowance_is_the_share_capped_by_the_day(monkeypatch: pytest.MonkeyPatch) -> None:
    settings: dict[str, Any] = {"grounding.lookup_per_day": 25}
    monkeypatch.setattr(db, "get_setting", lambda key, default=None, **_: settings.get(key, default))
    assert grounding.allowance("lookup") == 25
    assert grounding.allowance("people") == 30  # the default when the setting is missing
    assert grounding.allowance("lookup", _Budget(7)) == 7
    assert grounding.allowance("lookup", _Budget(-3)) == 0
    with pytest.raises(ValueError, match="unknown grounding use"):
        grounding.allowance("reviews")
