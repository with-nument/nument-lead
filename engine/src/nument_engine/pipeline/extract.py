"""AI fact extraction as a batch job (Step 9)."""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def submit(rc: RunContext) -> dict[str, Any]:
    """Submit the night's extraction batch."""
    raise NotImplementedError("Built in Step 9")


def collect(rc: RunContext) -> dict[str, Any]:
    """Collect finished batch results and store facts."""
    raise NotImplementedError("Built in Step 9")
