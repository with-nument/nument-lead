"""Universe builder: Overture, Places and registries into businesses (Step 6)."""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext, monthly: bool = False) -> dict[str, Any]:
    """Build or refresh the universe; `monthly` runs the full release diff."""
    raise NotImplementedError("Built in Step 6")
