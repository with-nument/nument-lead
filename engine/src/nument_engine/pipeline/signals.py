"""Signal watchers: jobs, careers pages, news, public asks, reviews (Step 7)."""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Run every enabled signal watcher."""
    raise NotImplementedError("Built in Step 7")
