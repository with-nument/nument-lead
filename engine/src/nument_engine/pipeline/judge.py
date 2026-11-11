"""Top-model judgement for the best half of scored leads (Step 11.10)."""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Ask the judge model for a second opinion on the top half."""
    raise NotImplementedError("Built in Step 11")
