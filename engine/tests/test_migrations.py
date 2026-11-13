"""The migration runner and the migration files themselves."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from nument_engine.ops import migrate

EXPECTED_FILES = [
    "0001_core.sql",
    "0002_views.sql",
    "0003_rls.sql",
    "0004_seed.sql",
    "0005_sheet_views.sql",
    "0006_cost_views.sql",
    "0007_learning.sql",
    "0008_llm.sql",
    "0009_sheet_targets.sql",
    "0010_review_sources.sql",
    "0011_notify_recipients.sql",
    "0012_read_performance.sql",
    "0013_scheduler.sql",
]


def test_discover_lists_every_file_in_order() -> None:
    assert [m.filename for m in migrate.discover()] == EXPECTED_FILES
    first = migrate.discover()[0]
    assert (first.version, first.name) == ("0001", "core")


def test_discover_rejects_bad_names(tmp_path: Path) -> None:
    (tmp_path / "core.sql").write_text("select 1;")
    with pytest.raises(migrate.MigrationError, match="NNNN_description"):
        migrate.discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("select 1;")
    (tmp_path / "0001_b.sql").write_text("select 1;")
    with pytest.raises(migrate.MigrationError, match="share version 0001"):
        migrate.discover(tmp_path)


def test_discover_needs_the_folder(tmp_path: Path) -> None:
    with pytest.raises(migrate.MigrationError, match="not found"):
        migrate.discover(tmp_path / "missing")


def test_every_migration_is_recorded_like_the_supabase_cli(migrated_dsn: str) -> None:
    with psycopg.connect(migrated_dsn, autocommit=True) as conn:
        rows = conn.execute(
            "select version, name, cardinality(statements) as n from supabase_migrations.schema_migrations "
            "order by version"
        ).fetchall()
        assert [(v, name) for v, name, _ in rows] == [(f.split("_", 1)[0], f[5:-4]) for f in EXPECTED_FILES]
        assert all(n == 1 for _, _, n in rows)
        # A second run finds nothing to do (idempotent).
        assert migrate.apply(conn) == []
        assert all(applied for _, applied in migrate.status(conn))


def test_apply_runs_new_files_and_rolls_back_a_failing_one(migrated_dsn: str, tmp_path: Path) -> None:
    good = tmp_path / "9001_ok.sql"
    good.write_text("create table public.migration_probe (id int); revoke all on public.migration_probe from anon;")
    bad = tmp_path / "9002_broken.sql"
    bad.write_text("create table public.migration_probe_2 (id int); select * from no_such_table;")
    with psycopg.connect(migrated_dsn, autocommit=True) as conn:
        try:
            todo = migrate.discover(tmp_path)
            assert [m.filename for m in migrate.apply(conn, todo, dry_run=True)] == ["9001_ok.sql", "9002_broken.sql"]
            with pytest.raises(migrate.MigrationError, match=r"9002_broken\.sql failed and was rolled back"):
                migrate.apply(conn, todo)
            versions = {r[0] for r in conn.execute("select version from supabase_migrations.schema_migrations")}
            assert "9001" in versions and "9002" not in versions
            assert conn.execute("select to_regclass('public.migration_probe_2')").fetchone() == (None,)
        finally:
            conn.execute("drop table if exists public.migration_probe")
            conn.execute("delete from supabase_migrations.schema_migrations where version in ('9001', '9002')")


def test_apply_needs_autocommit(migrated_dsn: str) -> None:
    with psycopg.connect(migrated_dsn) as conn, pytest.raises(migrate.MigrationError, match="autocommit"):
        migrate.apply(conn)


def test_dry_run_on_an_empty_database_creates_nothing(pg_server_dsn: str) -> None:
    name = f"nlead_dry_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_server_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(make_conninfo(pg_server_dsn, dbname=name), autocommit=True) as conn:
            assert [m.filename for m in migrate.apply(conn, dry_run=True)] == EXPECTED_FILES
            assert conn.execute("select to_regclass('supabase_migrations.schema_migrations')").fetchone() == (None,)
            assert migrate.status(conn)[0][1] is False
    finally:
        with psycopg.connect(pg_server_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))
