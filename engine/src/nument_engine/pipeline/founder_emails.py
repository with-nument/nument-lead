"""Founder emails: published sources first (site, old copies, search snippets, app stores, filings), then a name-pattern guess checked without sending (free verification APIs). Labels verified, likely, unknown.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Find and check founder emails for new A and B startups."""
    return {"skipped": "not built yet"}
