"""Postgres access through the Supabase session pooler (psycopg 3 + psycopg_pool).

The engine connects as the database owner through the session pooler (port 5432, IPv4), so it bypasses
Row Level Security. App users never come through here: the web app reads through RLS (Step 2.8).

Every helper takes an optional `conn`. Without it, the helper borrows a pooled connection and runs in its
own transaction. With it, the helper runs inside the caller's transaction (see `tx`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Literal

import psycopg
from psycopg import Connection, sql
from psycopg.abc import QueryNoTemplate as Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb, set_json_dumps
from psycopg.types.string import StrBinaryDumper, StrDumperUnknown
from psycopg_pool import ConnectionPool

from .settings import get_settings


# PostgreSQL text and jsonb refuse NUL (0x00) characters. Live, 13 Nov 2026: a stray NUL in one website failed
# the morning batch of 60 businesses, and one in Overture data stopped a universe load. Every text value and
# every JSON value is cleaned on its way to the database, for every connection this process opens.
def without_nul(value: Any) -> Any:
    """The value with NUL characters removed from every string in it (dict keys too)."""
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {without_nul(k): without_nul(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [without_nul(v) for v in value]
    return value


class _TextNoNul(StrDumperUnknown):
    def dump(self, obj: str) -> Any:
        return super().dump(obj.replace("\x00", "") if "\x00" in obj else obj)


class _BinaryNoNul(StrBinaryDumper):
    def dump(self, obj: str) -> Any:
        return super().dump(obj.replace("\x00", "") if "\x00" in obj else obj)


psycopg.adapters.register_dumper(str, _BinaryNoNul)
psycopg.adapters.register_dumper(str, _TextNoNul)  # registered last, so it stays the default (AUTO) as before
set_json_dumps(lambda obj: json.dumps(without_nul(obj)))

__all__ = [
    "Jsonb",
    "close_pool",
    "execute",
    "fetch_all",
    "fetch_one",
    "get_setting",
    "pool",
    "scalar",
    "set_setting",
    "tx",
    "upsert",
]

Params = Sequence[Any] | dict[str, Any] | None
Row = dict[str, Any]
# Who caused a write. The lead triggers copy it into activities.source (0001_core.sql, leads_after_write).
WriteSource = Literal["engine", "sheet"]

POOL_MAX_SIZE = 4  # the free plan's pooler allows few connections; 4 is enough for one job
CONNECT_TIMEOUT_S = 15
POOL_TIMEOUT_S = 30.0  # how long a command waits for a pooled connection before giving up

_pool: ConnectionPool | None = None


def _configure(conn: Connection[Any]) -> None:
    """Session settings for each new pooled connection.

    Set with SET rather than startup options, because the pooler does not forward every startup option.
    """
    conn.execute("set statement_timeout = '120s'")
    conn.execute("set timezone = 'UTC'")
    conn.commit()


def pool() -> ConnectionPool:
    """One small pool per process. GitHub Actions jobs are single process, so a few connections are plenty."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=settings.database_url.get_secret_value(),
            min_size=1,
            max_size=POOL_MAX_SIZE,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": CONNECT_TIMEOUT_S,
                "application_name": f"nlead-{settings.app_env}",
            },
            timeout=POOL_TIMEOUT_S,
            configure=_configure,
            check=ConnectionPool.check_connection,
            name="nlead",
            open=True,
        )
    return _pool


def close_pool() -> None:
    """Close the pool (end of a command, or between tests that switch databases)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def tx(source: WriteSource = "engine", context: dict[str, Any] | None = None) -> Iterator[Connection[Any]]:
    """A transaction: commits on success, rolls back on any exception (Step 2.3.1).

    source   'engine' or 'sheet'. Becomes activities.source when a lead trigger logs something.
    context  Extra keys merged into the activity payload, for example {"sheet": "master"}.

    The lead triggers own four activity types (lead_created, stage_change, grade_change, message_edited);
    code never inserts those, it only labels the transaction here (A.13.5 rule 1).
    """
    with pool().connection() as conn, conn.transaction():
        conn.execute(
            "select set_config('app.source', %s, true), set_config('app.context', %s, true)",
            (source, json.dumps(context or {})),
        )
        yield conn


def fetch_all(query: Query, params: Params = None, *, conn: Connection[Any] | None = None) -> list[Row]:
    """All rows as dicts."""
    if conn is not None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return cur.fetchall()
    with pool().connection() as pooled, pooled.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fetch_one(query: Query, params: Params = None, *, conn: Connection[Any] | None = None) -> Row | None:
    """The first row as a dict, or None."""
    rows = fetch_all(query, params, conn=conn)
    return rows[0] if rows else None


def scalar(query: Query, params: Params = None, *, conn: Connection[Any] | None = None) -> Any:
    """The first column of the first row, or None when there is no row."""
    row = fetch_one(query, params, conn=conn)
    return next(iter(row.values())) if row else None


def execute(
    query: Query,
    params: Params = None,
    *,
    conn: Connection[Any] | None = None,
    source: WriteSource = "engine",
    context: dict[str, Any] | None = None,
) -> int:
    """Run one statement and return the number of affected rows."""
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount
    with tx(source, context) as txc, txc.cursor() as cur:
        cur.execute(query, params)
        return cur.rowcount


def _table(name: str) -> sql.Identifier:
    """`settings` or `public.settings` as a safely quoted identifier."""
    parts = name.split(".")
    if not 1 <= len(parts) <= 2 or not all(parts):
        raise ValueError(f"bad table name {name!r}")
    return sql.Identifier(*parts)


def _adapt(value: Any) -> Any:
    """dict and list values are sent as JSONB."""
    return Jsonb(value) if isinstance(value, dict | list) else value


def upsert(
    table: str,
    rows: Iterable[dict[str, Any]],
    conflict: Sequence[str],
    update: Sequence[str] | None = None,
    returning: str | None = None,
    *,
    conn: Connection[Any] | None = None,
    source: WriteSource = "engine",
    context: dict[str, Any] | None = None,
) -> list[Row]:
    """INSERT ... ON CONFLICT (conflict) DO UPDATE SET col = EXCLUDED.col for each update column.

    - `update=None` updates every column that is not part of the conflict key; `update=[]` means DO NOTHING.
    - dict and list values are wrapped as JSONB automatically.
    - `returning` is a code-supplied SQL fragment (for example "id"); never pass user input.
    Every row must have the same keys. Fine up to a few thousand rows; bigger loads use COPY (Step 6).
    """
    rows = list(rows)
    if not rows:
        return []
    cols = list(rows[0])
    for row in rows[1:]:
        if set(row) != set(cols):
            raise ValueError(f"upsert into {table}: every row needs the same keys ({sorted(cols)})")
    if not conflict:
        raise ValueError("upsert needs at least one conflict column")
    update_cols = list(update) if update is not None else [c for c in cols if c not in conflict]
    action = (
        sql.SQL("DO UPDATE SET ")
        + sql.SQL(", ").join(sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in update_cols)
        if update_cols
        else sql.SQL("DO NOTHING")
    )
    query = sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) ON CONFLICT ({k}) {action}{ret}").format(
        t=_table(table),
        c=sql.SQL(", ").join(map(sql.Identifier, cols)),
        v=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        k=sql.SQL(", ").join(map(sql.Identifier, conflict)),
        action=action,
        ret=sql.SQL(" RETURNING ") + sql.SQL(returning) if returning else sql.SQL(""),
    )
    values = [[_adapt(row[c]) for c in cols] for row in rows]

    def _run(c: Connection[Any]) -> list[Row]:
        with c.cursor(row_factory=dict_row) as cur:
            if not returning:
                cur.executemany(query, values)
                return []
            out: list[Row] = []
            for params in values:
                cur.execute(query, params)
                out.extend(cur.fetchall())
            return out

    if conn is not None:
        return _run(conn)
    with tx(source, context) as txc:
        return _run(txc)


def get_setting(key: str, default: Any = None, *, conn: Connection[Any] | None = None) -> Any:
    """A value from public.settings (already decoded from JSON), or `default`."""
    row = fetch_one("select value from public.settings where key = %s", [key], conn=conn)
    return row["value"] if row else default


def set_setting(key: str, value: Any, *, conn: Connection[Any] | None = None) -> None:
    """Insert or replace a value in public.settings."""
    execute(
        "insert into public.settings (key, value) values (%s, %s) "
        "on conflict (key) do update set value = excluded.value",
        [key, Jsonb(value)],
        conn=conn,
    )
