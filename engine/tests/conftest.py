"""Shared test fixtures.

Database tests run against a throwaway Postgres, never against Supabase (A.13.4):

- `NLEAD_TEST_DATABASE_URL` set (the CI service container): a fresh database is created on that server for the
  session and dropped afterwards.
- Otherwise a temporary cluster is started from the installed Postgres binaries (initdb + pg_ctl) in a temp
  folder on a free localhost port, and deleted afterwards. Homebrew services are never started or touched.
  `NLEAD_PG_BIN` picks the binaries folder; by default the newest installed major version is used.

Either way `tests/sql/auth_stub.sql` (the bits of Supabase the schema needs) and every file in
`supabase/migrations` are applied, through the same code path as `nlead db migrate`.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.ops import migrate

from .helpers import RlsWorld, TempCluster, find_pg_bin

TESTS_DIR = Path(__file__).resolve().parent
AUTH_STUB = TESTS_DIR / "sql" / "auth_stub.sql"

# Unroutable on purpose: a test that reaches for the database without a fixture fails fast instead of
# touching a real project.
GUARD_DSN = "postgresql://nlead-test-guard@127.0.0.1:9/never?connect_timeout=2"

ENGINE_ENV_VARS = (
    "DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_BACKUP",
    "OPENAI_API_KEY",
    "GOOGLE_MAPS_API_KEY",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "SHEET_MASTER_ID",
    "SHEET_CALLER_ID",
    "SHEET_STAGING_ID",
    "BACKUP_PASSPHRASE",
    "ALERT_EMAIL",
    "ALERT_EMAIL_FROM",
    "ALERT_REPLY_TO",
    "APP_URL",
    "RESEND_API_KEY",
    "GITHUB_STEP_SUMMARY",
    "ASSOCIATE_NAME",
    "USER_AGENT",
)


# ---------------------------------------------------------------------------
# Isolation: tests never read engine/.env.* and never see real credentials
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    monkeypatch.setattr(settings_module, "ENV_FILE_DIR", tmp_path_factory.getbasetemp() / "no-env-files")
    for name in ENGINE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", GUARD_DSN)
    settings_module.get_settings.cache_clear()
    yield
    db.close_pool()
    settings_module.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Throwaway Postgres
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_bin() -> Path | None:
    return find_pg_bin()


@pytest.fixture(scope="session")
def pg_server_dsn(tmp_path_factory: pytest.TempPathFactory, pg_bin: Path | None) -> Iterator[str]:
    """An empty database for this test session."""
    external = os.environ.get("NLEAD_TEST_DATABASE_URL")
    if external:
        name = f"nlead_test_{uuid.uuid4().hex[:10]}"
        with psycopg.connect(external, autocommit=True) as conn:
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        try:
            yield make_conninfo(external, dbname=name)
        finally:
            with psycopg.connect(external, autocommit=True) as conn:
                conn.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))
        return
    if pg_bin is None:
        pytest.skip("No Postgres binaries found: install PostgreSQL, or set NLEAD_PG_BIN or NLEAD_TEST_DATABASE_URL")
    root = tmp_path_factory.mktemp("pg")
    cluster = TempCluster(bin_dir=pg_bin, root=root)
    cluster.start()
    try:
        yield cluster.dsn
    finally:
        cluster.stop()
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def migrated_dsn(pg_server_dsn: str) -> str:
    """The session database with the Supabase stub and every migration applied."""
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        conn.execute(AUTH_STUB.read_text(encoding="utf-8"))
        migrate.apply(conn, migrate.discover())
    return pg_server_dsn


@pytest.fixture
def db_conn(migrated_dsn: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """A connection whose work is always rolled back at the end of the test."""
    conn = psycopg.connect(migrated_dsn, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def engine_db(migrated_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point the engine's settings and connection pool at the test database. Writes are committed."""
    monkeypatch.setenv("DATABASE_URL", migrated_dsn)
    settings_module.get_settings.cache_clear()
    db.close_pool()
    yield migrated_dsn
    db.close_pool()
    settings_module.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# A small committed world for RLS tests: three users, one lead with money, one cost row
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rls_world(migrated_dsn: str) -> RlsWorld:
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(migrated_dsn, row_factory=dict_row) as conn, conn.transaction():
        ids: dict[str, str] = {}
        for role in ("admin", "caller", "viewer"):
            row = conn.execute(
                "insert into auth.users (email, raw_user_meta_data) values (%s, %s) returning id",
                [f"rls-{role}-{tag}@example.com", json.dumps({"full_name": f"RLS {role}"})],
            ).fetchone()
            assert row is not None
            ids[role] = str(row["id"])
            conn.execute("update public.profiles set role = %s where user_id = %s", [role, row["id"]])
        biz = conn.execute(
            "insert into public.businesses (segment_id, name, norm_name, country, city, web_domain) "
            "values ('clinics-in', %s, %s, 'in', 'Pune', %s) returning id",
            [f"RLS Clinic {tag}", f"rls clinic {tag}", f"rls-{tag}.example.com"],
        ).fetchone()
        assert biz is not None
        conn.execute(
            "insert into public.contacts (business_id, name, phone_e164, phone_type, source, is_decision_maker) "
            "values (%s, 'Dr. Test', '+919800000001', 'mobile', 'website', true)",
            [biz["id"]],
        )
        score = conn.execute(
            "insert into public.scores (business_id, version, fit, total, grade, pitch_mode) "
            "values (%s, 'v1.0', 3, 78, 'A', 'visible_pain') returning id",
            [biz["id"]],
        ).fetchone()
        assert score is not None
        lead = conn.execute(
            "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, message, deal_value_inr) "
            "values (%s, 'clinics-in', %s, 'A', 'visible_pain', 'Hi Dr. Test', 150000) returning id",
            [biz["id"], score["id"]],
        ).fetchone()
        assert lead is not None
        conn.execute(
            "insert into public.costs (provider, model, task, usd, inr) values ('gemini', 'test', 'rls_world', 0.01, 0.88)"
        )
    return RlsWorld(
        admin=ids["admin"],
        caller=ids["caller"],
        viewer=ids["viewer"],
        business_id=str(biz["id"]),
        lead_id=str(lead["id"]),
    )
