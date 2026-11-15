"""Pre-call briefs (write_precall_brief), emailed an hour before each booked call.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Send the briefs due."""
    return {"skipped": "not built yet"}
