"""US SEC Form D and Form C filings (daily index): small raises, founders as related persons.

Contract stub (task 0, 15 Nov 2026). Until it is built the watcher reports "not built" and adds nothing.
"""

from __future__ import annotations

from typing import Any

NAME = "sec_edgar"


async def watch(ctx: Any, segments: dict[str, Any], sink: Any) -> None:
    """Add this source's signals for the enabled segments to the sink."""
    ctx.add(f"{NAME}.not_built")
