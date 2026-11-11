"""Scoring: fit, can-pay, intent, reach, total and grade (Step 11)."""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Compute scores and grades for researched businesses."""
    raise NotImplementedError("Built in Step 11")
