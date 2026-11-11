"""Verification: re-check quotes, phones and websites (Step 10)."""

from __future__ import annotations

from typing import Any

from .runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Verify extracted facts against stored page text."""
    raise NotImplementedError("Built in Step 10")
