"""BetaList pre-launch startups (public feed).

Contract stub (task 0, 15 Nov 2026). Until it is built the watcher reports "not built" and adds nothing.
"""

from __future__ import annotations

from typing import Any

NAME = "betalist"


async def watch(ctx: Any, segments: dict[str, Any], sink: Any) -> None:
    """Add this source's signals for the enabled segments to the sink."""
    ctx.add(f"{NAME}.not_built")
