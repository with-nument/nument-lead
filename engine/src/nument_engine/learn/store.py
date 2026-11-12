"""Storage of reports (Step 16.6.1): the weekly report, the audit, evals and monthly costs share one table."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Final

from .. import db

REPORT_KINDS: Final[tuple[str, ...]] = ("weekly", "audit", "eval", "monthly_cost")


def store_report(
    kind: str, start: date | None, end: date | None, content: Mapping[str, Any], markdown: str, *, conn: Any = None
) -> int:
    """Insert one `reports` row and return its id. `content` holds the numbers the app renders."""
    if kind not in REPORT_KINDS:
        raise ValueError(f"unknown report kind {kind!r}; expected one of {', '.join(REPORT_KINDS)}")
    query = (
        "insert into public.reports (kind, period_start, period_end, content, markdown) "
        "values (%s, %s, %s, %s, %s) returning id"
    )
    params = [kind, start, end, db.Jsonb(dict(content)), markdown]
    if conn is not None:
        row = db.fetch_one(query, params, conn=conn)
    else:
        with db.tx() as txc:
            row = db.fetch_one(query, params, conn=txc)
    assert row is not None
    return int(row["id"])
