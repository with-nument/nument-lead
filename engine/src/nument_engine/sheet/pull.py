"""Google Sheet to database: stages, dates and notes people typed (Step 13)."""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Read people's edits back into the database."""
    raise NotImplementedError("Built in Step 13")
