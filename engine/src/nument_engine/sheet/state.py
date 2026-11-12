"""Sync bookkeeping in the database: the `sheet_state` marker, snapshots and the sync lock (Step 13.6, 13.7.4).

- `sheet_state` (a settings key) says, per target, whether the last push finished (`ok`) or stopped half way
  (`writing`). Pull only reads sheets marked `ok`, so a crashed push is never read back as edits.
- `sheet_snapshots` holds, per target and lead, the editable values exactly as the last full write left them.
  A cell that differs from its own sheet's snapshot is an edit (D-045).
- The lock keeps two syncs of one environment from writing at the same time (a scheduled sync and the morning
  run, or a laptop and CI).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection

from .. import db

ROW_KEY = "_row"  # snapshot-only key: the row position of the lead at the last push (not an editable value)


def states(conn: Connection[Any] | None = None) -> dict[str, dict[str, Any]]:
    """Every target's marker, for example {"master": {"state": "ok", "spreadsheet_id": "...", ...}}."""
    value = db.get_setting("sheet_state", {}, conn=conn) or {}
    return {k: dict(v) for k, v in value.items() if isinstance(v, dict)}


def set_state(key: str, value: dict[str, Any], *, conn: Connection[Any]) -> None:
    """Replace one target's marker, leaving the others as they are."""
    db.execute(
        "insert into public.settings (key, value) values ('sheet_state', jsonb_build_object(%s::text, %s::jsonb)) "
        "on conflict (key) do update set value = coalesce(public.settings.value, '{}'::jsonb) "
        "|| jsonb_build_object(%s::text, %s::jsonb)",
        [key, db.Jsonb(value), key, db.Jsonb(value)],
        conn=conn,
    )


def load_snapshot(
    key: str, conn: Connection[Any] | None = None
) -> tuple[dict[str, dict[str, Any]], dt.datetime | None]:
    """({lead_id: values}, written_at of the snapshot) for one target; ({}, None) when there is none."""
    rows = db.fetch_all(
        "select lead_id::text as lead_id, values, written_at from public.sheet_snapshots where sheet = %s",
        [key],
        conn=conn,
    )
    snap = {r["lead_id"]: dict(r["values"]) for r in rows}
    written = max((r["written_at"] for r in rows), default=None)
    return snap, written


def save_snapshot(key: str, values: dict[str, dict[str, Any]], *, conn: Connection[Any]) -> int:
    """Replace a target's snapshot inside the caller's transaction. Returns the number of rows written."""
    db.execute("delete from public.sheet_snapshots where sheet = %s", [key], conn=conn)
    if not values:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "insert into public.sheet_snapshots (sheet, lead_id, values, written_at) values (%s, %s, %s, now())",
            [(key, lead_id, db.Jsonb(v)) for lead_id, v in values.items()],
        )
    return len(values)


def editable(values: dict[str, Any]) -> dict[str, Any]:
    """Snapshot values without the bookkeeping keys."""
    return {k: v for k, v in values.items() if not k.startswith("_")}


@contextmanager
def sheet_lock(env: str) -> Iterator[bool]:
    """Try to take this environment's sync lock; yields False when another sync holds it.

    A transaction-level advisory lock on a dedicated pooled connection: it is released when the block ends,
    and also if the process dies (the server rolls the transaction back), so a crash can never leave it stuck.
    The session pooler (port 5432) keeps the connection's transaction for us.
    """
    with db.pool().connection() as conn, conn.transaction():
        yield bool(db.scalar("select pg_try_advisory_xact_lock(hashtext(%s))", [f"nument-sheet-{env}"], conn=conn))
