"""Health check of every service, source and quota (Step 22)."""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Check the database, AI providers, sheets and sources."""
    raise NotImplementedError("Built in Step 22")
