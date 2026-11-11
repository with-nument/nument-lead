"""Database to Google Sheet: Today, Pipeline and Lead details tabs (Step 13)."""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Write leads to the sheets this environment targets."""
    raise NotImplementedError("Built in Step 13")
