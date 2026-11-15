"""Startup funding news feeds (TechCrunch, EU-Startups, Inc42, e27, BetaKit, Startup Daily, YourStory, TechCabal, Disrupt Africa, LatamList, Tech Funding News, Crunchbase News, AlleyWatch, Silicon Republic) plus GDELT.

Contract stub (task 0, 15 Nov 2026). Until it is built the watcher reports "not built" and adds nothing.
"""

from __future__ import annotations

from typing import Any

NAME = "funding_rss"


async def watch(ctx: Any, segments: dict[str, Any], sink: Any) -> None:
    """Add this source's signals for the enabled segments to the sink."""
    ctx.add(f"{NAME}.not_built")
