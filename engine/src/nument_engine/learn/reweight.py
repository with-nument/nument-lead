"""Weekly re-weighting of signal and can-pay points (Step 16.4)."""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Propose and apply the weekly weight update."""
    raise NotImplementedError("Built in Step 16")
