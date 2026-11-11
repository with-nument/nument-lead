"""Funnel metrics per cut and the weekly audit (Steps 16.2 and 17.6)."""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def audit(rc: RunContext) -> dict[str, Any]:
    """Re-check 20 recent leads and store an audit report."""
    raise NotImplementedError("Built in Step 17")
