"""The 12-day sequence: who is eligible, auto or review routing, warm-up caps, time windows, stop rules, and the send loop.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Queue and send what is due."""
    return {"skipped": "not built yet"}
