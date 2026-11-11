"""Encrypted dump of the public schema, uploaded to the private backups bucket (Step 2.14, Step 14.5.6, A.13.5 rule 12)."""

from __future__ import annotations

from typing import Any

from ..pipeline.runs import RunContext


def run(rc: RunContext) -> dict[str, Any]:
    """Dump, compress and encrypt the database."""
    raise NotImplementedError("Built in Step 14")
