"""Pre-filter: rules that build today's research queue (Step 8)."""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Apply size, fit and exclusion rules and queue businesses for research."""
    raise NotImplementedError("Built in Step 8")
