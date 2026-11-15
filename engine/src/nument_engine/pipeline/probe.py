"""Cheap public probes per startup site: tech-stack fingerprint (no-code builders, payments, AI), domain age (RDAP, crt.sh, Wayback), DNS TXT/MX, GitHub org activity, app-store links.

Contract stub (task 0, 15 Nov 2026): registered in the run phases so parallel work can fill it in. Until it is
built it reports "not built yet" and changes nothing.
"""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Probe the startups researched tonight."""
    return {"skipped": "not built yet"}
