"""The 60-day backlog: run the startup sources backwards once (nlead backlog --days 60).

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Build the backlog."""
    return {"skipped": "not built yet"}
