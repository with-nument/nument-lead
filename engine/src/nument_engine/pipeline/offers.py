"""Offer matching: one offer per startup plus a backup and why now (pick_offer), stored in lead_offers.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Pick offers for new leads."""
    return {"skipped": "not built yet"}
