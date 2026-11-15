"""Startup qualification: real startup, 2 to 10 people, no tech team (2 signals), can pay, product status, freshness; every answer quote-backed or 'unknown', stored in startup_profiles.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Qualify the researched startups of this run."""
    return {"skipped": "not built yet"}
