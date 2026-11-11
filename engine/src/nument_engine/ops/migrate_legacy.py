"""One-time import from the old lead-engine folder (Step 20)."""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Import legacy leads, stages and decisions."""
    raise NotImplementedError("Built in Step 20")
