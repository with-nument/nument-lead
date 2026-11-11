"""Apply `supabase/migrations` to a database and record them the way the Supabase CLI does.

`supabase db push` keeps its history in `supabase_migrations.schema_migrations` (version, name, statements).
This module writes the same table, so the CLI and `nlead db migrate` always agree on what is applied. The test
harness uses it too, so tests run exactly the files that production runs.

Rules (Step 2.11.2): files are `NNNN_description.sql`, applied in file-name order, each in its own transaction.
Never edit a migration that has been applied; add the next number instead.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import Connection

from ..logging import get_logger
from ..settings import REPO_DIR, get_settings

log = get_logger()

MIGRATIONS_DIR = REPO_DIR / "supabase" / "migrations"
FILE_PATTERN = re.compile(r"^(?P<version>[0-9]+)_(?P<name>[A-Za-z0-9_]+)\.sql$")
LOCK_KEY = 7_331_001  # session advisory lock: one migration run at a time per database

HISTORY_DDL = """
create schema if not exists supabase_migrations;
create table if not exists supabase_migrations.schema_migrations (version text not null primary key);
alter table supabase_migrations.schema_migrations add column if not exists statements text[];
alter table supabase_migrations.schema_migrations add column if not exists name text;
"""


class MigrationError(RuntimeError):
    """A migration file is invalid, or applying it failed (the failed file is rolled back)."""


@dataclass(frozen=True)
class Migration:
    """One file in supabase/migrations."""

    version: str
    name: str
    path: Path

    @property
    def filename(self) -> str:
        return self.path.name

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Every migration file, in the order the Supabase CLI applies them (file name order)."""
    if not directory.is_dir():
        raise MigrationError(f"migrations folder not found: {directory}")
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql"), key=lambda p: p.name):
        match = FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: migration files must be named NNNN_description.sql")
        found.append(Migration(match["version"], match["name"], path))
    seen: set[str] = set()
    for m in found:
        if m.version in seen:
            raise MigrationError(f"two migration files share version {m.version}")
        seen.add(m.version)
    return found


def ensure_history(conn: Connection[Any]) -> None:
    """Create the Supabase CLI history table if it is missing (same DDL as the CLI)."""
    conn.execute(HISTORY_DDL)


def applied_versions(conn: Connection[Any]) -> set[str]:
    """Versions recorded in supabase_migrations.schema_migrations (none when the table does not exist yet)."""
    with conn.cursor() as cur:
        cur.execute("select to_regclass('supabase_migrations.schema_migrations') is not null")
        row = cur.fetchone()
        if not row or not (row[0] if isinstance(row, tuple) else next(iter(row.values()))):
            return set()
        cur.execute("select version from supabase_migrations.schema_migrations")
        return {row[0] if isinstance(row, tuple) else row["version"] for row in cur.fetchall()}


def pending(conn: Connection[Any], migrations: Iterable[Migration]) -> list[Migration]:
    """Migrations not yet recorded as applied."""
    done = applied_versions(conn)
    return [m for m in migrations if m.version not in done]


def apply(
    conn: Connection[Any], migrations: Iterable[Migration] | None = None, *, dry_run: bool = False
) -> list[Migration]:
    """Apply pending migrations, each in its own transaction, and record them. Returns what was (or would be) applied.

    Needs an autocommit connection, so that each file commits on its own and a failure rolls back only that file.
    """
    if not conn.autocommit:
        raise MigrationError("apply() needs an autocommit connection (each migration runs in its own transaction)")
    todo_all = discover() if migrations is None else list(migrations)
    conn.execute("select pg_advisory_lock(%s)", [LOCK_KEY])
    try:
        todo = pending(conn, todo_all)
        if dry_run:  # read only: nothing is created, not even the history table
            return todo
        ensure_history(conn)
        for m in todo:
            sql_text = m.read()
            try:
                with conn.transaction():
                    conn.execute("set local lock_timeout = '10s'")  # never queue behind a long lock on a live table
                    conn.execute(sql_text)  # no parameters: sent as one simple query, so many statements are fine
                    conn.execute(
                        "insert into supabase_migrations.schema_migrations (version, name, statements) "
                        "values (%s, %s, %s)",
                        [m.version, m.name, [sql_text]],
                    )
            except psycopg.Error as exc:
                raise MigrationError(f"{m.filename} failed and was rolled back: {exc}") from exc
            log.info("db.migration.applied", file=m.filename)
        return todo
    finally:
        conn.execute("select pg_advisory_unlock(%s)", [LOCK_KEY])


def status(conn: Connection[Any], migrations: Iterable[Migration] | None = None) -> list[tuple[Migration, bool]]:
    """Each migration with True when it is applied."""
    done = applied_versions(conn)
    return [(m, m.version in done) for m in (discover() if migrations is None else migrations)]


def connect(conninfo: str | None = None) -> Connection[Any]:
    """An autocommit connection to DATABASE_URL (or the given conninfo) for migrations."""
    dsn = conninfo or get_settings().database_url.get_secret_value()
    return psycopg.connect(dsn, autocommit=True, connect_timeout=15, application_name="nlead-migrate")
