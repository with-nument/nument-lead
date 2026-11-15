"""Mailbox health: daily caps, warm-up progress, auto-pause on bounces or Gmail errors.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Check the mailbox."""
    return {"skipped": "not built yet"}
