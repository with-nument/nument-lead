"""Personal 1-page plans (write_plan) served at /p/<token>, created just before the day-3 email is due.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Write the plans due within 24 hours."""
    return {"skipped": "not built yet"}
