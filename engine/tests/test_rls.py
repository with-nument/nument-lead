"""Row Level Security, grants and storage rules (Step 2.8 access matrix, Step 17.2.4).

Runs against the throwaway test database with the committed `rls_world` (admin, caller, viewer, one lead with
a deal value). Every check impersonates an API role the way PostgREST does: `set local role` plus the JWT
claims. Each test's work is rolled back.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
from typing import Any

import psycopg
import pytest
from psycopg import errors

from .helpers import Conn, RlsWorld, act_as, find_psql

SQL_FILE = pathlib.Path(__file__).parents[2] / "supabase" / "tests" / "rls_test.sql"

# Executable by anyone on purpose: auth_role() returns 'none' for visitors; trigger functions cannot be
# called directly. Any other function in public must be locked down (2.8.4 rule 4).
ANON_CALLABLE_OK = {"auth_role()"}


def _denied(conn: Conn, query: str, params: list[Any] | None = None) -> None:
    """The statement must fail with permission denied (and must not poison the outer transaction)."""
    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
        conn.execute(query, params)


def _count(conn: Conn, query: str, params: list[Any] | None = None) -> int:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return int(next(iter(row.values())))


def _flag(conn: Conn, query: str, params: list[Any]) -> bool:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return bool(next(iter(row.values())))


# ---------------------------------------------------------------------------
# The plan's SQL test file (2.10.2), run with psql like on the dev project
# ---------------------------------------------------------------------------


def _run_sql_file(
    psql: pathlib.Path, dsn: str, admin: str, caller: str, viewer: str
) -> subprocess.CompletedProcess[str]:
    cmd = [str(psql), dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", f"admin={admin}", "-v", f"caller={caller}",
           "-v", f"viewer={viewer}", "-f", str(SQL_FILE)]  # fmt: skip
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)


def test_rls_sql_file_passes(migrated_dsn: str, rls_world: RlsWorld, pg_bin: pathlib.Path | None) -> None:
    psql = find_psql(pg_bin)
    if psql is None:
        pytest.skip("psql not found")
    out = _run_sql_file(psql, migrated_dsn, rls_world.admin, rls_world.caller, rls_world.viewer)
    assert out.returncode == 0, out.stderr


def test_rls_sql_file_catches_a_broken_rule(
    migrated_dsn: str, rls_world: RlsWorld, pg_bin: pathlib.Path | None
) -> None:
    """Prove the file fails when a rule is broken: give app users the money column for a moment."""
    psql = find_psql(pg_bin)
    if psql is None:
        pytest.skip("psql not found")
    with psycopg.connect(migrated_dsn, autocommit=True) as conn:
        conn.execute("grant select (deal_value_inr) on public.leads to authenticated")
        try:
            out = _run_sql_file(psql, migrated_dsn, rls_world.admin, rls_world.caller, rls_world.viewer)
        finally:
            conn.execute("revoke select (deal_value_inr) on public.leads from authenticated")
    assert out.returncode != 0
    assert "FAIL: caller can read leads.deal_value_inr" in out.stderr


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("DATABASE_URL_DEV"), reason="needs the dev database and its RLS test users (2.10.1)")
def test_rls_rules(pg_bin: pathlib.Path | None) -> None:
    """Step 2.10.3: the same file against the dev project."""
    psql = find_psql(pg_bin)
    assert psql is not None, "psql not found"
    env = os.environ
    out = _run_sql_file(psql, env["DATABASE_URL_DEV"], env["RLS_ADMIN_ID"], env["RLS_CALLER_ID"], env["RLS_VIEWER_ID"])
    assert out.returncode == 0, out.stderr


# ---------------------------------------------------------------------------
# Money: deal_value_inr
# ---------------------------------------------------------------------------


def test_caller_cannot_read_or_write_money(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    _denied(db_conn, "select deal_value_inr from public.leads")
    _denied(db_conn, "select * from public.leads")
    _denied(db_conn, "update public.leads set deal_value_inr = 1 where id = %s", [rls_world.lead_id])
    _denied(db_conn, "select * from public.v_pipeline")
    _denied(db_conn, "select * from public.v_sheet_leads")
    assert _count(db_conn, "select count(*) from public.v_leads_admin") == 0
    assert _count(db_conn, "select count(*) from public.v_leads_caller where id = %s", [rls_world.lead_id]) == 1


def test_admin_reads_money_only_through_v_leads_admin(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.admin)
    _denied(db_conn, "select deal_value_inr from public.leads")
    row = db_conn.execute(
        "select deal_value_inr, name from public.v_leads_admin where id = %s", [rls_world.lead_id]
    ).fetchone()
    assert row is not None and float(row["deal_value_inr"]) == 150000.0


def test_money_column_is_never_granted_to_app_roles(db_conn: Conn) -> None:
    for role in ("anon", "authenticated"):
        for priv in ("SELECT", "INSERT", "UPDATE"):
            assert not _flag(
                db_conn, "select has_column_privilege(%s, 'public.leads', 'deal_value_inr', %s)", [role, priv]
            )


def test_caller_view_has_no_money_column(db_conn: Conn) -> None:
    cols = {
        r["column_name"]
        for r in db_conn.execute(
            "select column_name from information_schema.columns where table_schema = 'public' and table_name = 'v_leads_caller'"
        ).fetchall()
    }
    assert "deal_value_inr" not in cols and {"id", "stage", "phone_e164", "top_signal_quote"} <= cols


# ---------------------------------------------------------------------------
# Lead edits and the timeline
# ---------------------------------------------------------------------------


def test_caller_edits_allowed_columns_and_the_trigger_logs_it(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    assert (
        db_conn.execute(
            "update public.leads set stage = 'contacted', notes = 'sent on WhatsApp' where id = %s", [rls_world.lead_id]
        ).rowcount
        == 1
    )
    _denied(db_conn, "update public.leads set grade = 'D' where id = %s", [rls_world.lead_id])
    _denied(db_conn, "insert into public.leads (business_id, segment_id, grade, pitch_mode) values (%s, 'clinics-in', 'A', 'fit_only')",
            [rls_world.business_id])  # fmt: skip
    _denied(db_conn, "delete from public.leads where id = %s", [rls_world.lead_id])
    db_conn.execute("reset role")
    activity = db_conn.execute(
        "select source, user_id::text as user_id, payload from public.activities "
        "where lead_id = %s and type = 'stage_change'",
        [rls_world.lead_id],
    ).fetchall()
    assert activity == [{"source": "app", "user_id": rls_world.caller, "payload": {"from": "new", "to": "contacted"}}]


def test_viewer_cannot_edit_a_lead(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.viewer)
    assert db_conn.execute("update public.leads set notes = 'x' where id = %s", [rls_world.lead_id]).rowcount == 0
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute(
            "insert into public.activities (lead_id, source, type) values (%s, 'app', 'note')", [rls_world.lead_id]
        )


def test_caller_adds_own_activity_but_cannot_spoof_it(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    row = db_conn.execute(
        "insert into public.activities (lead_id, source, type) values (%s, 'app', 'note') returning user_id::text",
        [rls_world.lead_id],
    ).fetchone()
    assert row == {"user_id": rls_world.caller}  # user columns default to auth.uid()
    spoofs = ((rls_world.admin, "app"), (rls_world.caller, "engine"))
    for user_id, source in spoofs:
        with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
            db_conn.execute(
                "insert into public.activities (lead_id, user_id, source, type) values (%s, %s, %s, 'note')",
                [rls_world.lead_id, user_id, source],
            )


# ---------------------------------------------------------------------------
# Contacts, manual signals, pages
# ---------------------------------------------------------------------------


def test_contacts_flag_only(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    assert db_conn.execute("update public.contacts set do_not_contact = true where business_id = %s",
                           [rls_world.business_id]).rowcount == 1  # fmt: skip
    _denied(
        db_conn,
        "update public.contacts set phone_e164 = '+919800000002' where business_id = %s",
        [rls_world.business_id],
    )
    act_as(db_conn, "authenticated", rls_world.viewer)
    assert db_conn.execute("update public.contacts set do_not_contact = false where business_id = %s",
                           [rls_world.business_id]).rowcount == 0  # fmt: skip


def test_manual_ads_signal(db_conn: Conn, rls_world: RlsWorld) -> None:
    insert = (
        "insert into public.signals (business_id, type, category, observed_at, expires_at, source, dedupe_key) "
        "values (%s, %s, 'visible_pain', now(), now() + interval '30 days', %s, %s)"
    )
    act_as(db_conn, "authenticated", rls_world.caller)
    db_conn.execute(insert, [rls_world.business_id, "ads_running", "manual", f"manual:ads:{rls_world.business_id}"])
    for signal_type, source in (("hiring_frontdesk", "manual"), ("ads_running", "apna")):
        with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
            db_conn.execute(insert, [rls_world.business_id, signal_type, source, f"x:{signal_type}:{source}"])
    act_as(db_conn, "authenticated", rls_world.viewer)
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute(insert, [rls_world.business_id, "ads_running", "manual", "viewer:ads"])


def test_pages_show_titles_but_never_text(db_conn: Conn, rls_world: RlsWorld) -> None:
    db_conn.execute(
        "insert into public.pages (business_id, url, title, text) values (%s, %s, 'Home', 'raw page text')",
        [rls_world.business_id, f"https://{rls_world.business_id}.example.com/"],
    )
    act_as(db_conn, "authenticated", rls_world.viewer)
    assert _count(db_conn, "select count(title) from public.pages where business_id = %s", [rls_world.business_id]) == 1
    _denied(db_conn, "select text from public.pages")
    _denied(db_conn, "select * from public.pages")


# ---------------------------------------------------------------------------
# Admin-only data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["caller", "viewer"])
def test_operations_data_is_admin_only(db_conn: Conn, rls_world: RlsWorld, role: str) -> None:
    act_as(db_conn, "authenticated", getattr(rls_world, role))
    hidden = ("costs", "runs", "settings", "llm_batches", "source_health", "source_records", "golden_labels",
              "custom_queries", "inbox_posts", "reports", "weight_versions", "v_costs_daily", "v_source_health",
              "llm_cache", "llm_batch_reservations", "sheet_snapshots")  # fmt: skip
    for table in hidden:
        assert _count(db_conn, f"select count(*) from public.{table}") == 0, table
    for engine_only in ("v_spend_today", "v_quota_today", "v_quota_month", "v_lead_funnel"):
        _denied(db_conn, f"select * from public.{engine_only}")


def test_admin_reads_operations_data(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.admin)
    assert _count(db_conn, "select count(*) from public.costs where task = 'rls_world'") == 1
    assert _count(db_conn, "select count(*) from public.settings") >= 23
    assert _count(db_conn, "select count(*) from public.source_health") == 13
    assert _count(db_conn, "select count(*) from public.v_costs_daily where task = 'rls_world'") == 1
    assert db_conn.execute("update public.source_health set enabled = false where source = 'gdelt'").rowcount == 1


def test_suppression_rules(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    db_conn.execute("insert into public.suppression (phone_e164, reason) values ('+919800000099', 'opt_out')")
    assert db_conn.execute("delete from public.suppression where phone_e164 = '+919800000099'").rowcount == 0
    act_as(db_conn, "authenticated", rls_world.viewer)
    assert _count(db_conn, "select count(*) from public.suppression") == 0
    act_as(db_conn, "authenticated", rls_world.admin)
    assert db_conn.execute("delete from public.suppression where phone_e164 = '+919800000099'").rowcount == 1


def test_profiles(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    assert _count(db_conn, "select count(*) from public.profiles") == 1  # only their own
    assert (
        db_conn.execute(
            "update public.profiles set full_name = 'Aditya' where user_id = %s", [rls_world.caller]
        ).rowcount
        == 1
    )
    _denied(db_conn, "update public.profiles set role = 'admin' where user_id = %s", [rls_world.caller])
    _denied(db_conn, "insert into public.profiles (user_id, role) values (gen_random_uuid(), 'admin')")
    act_as(db_conn, "authenticated", rls_world.admin)
    assert _count(db_conn, "select count(*) from public.profiles") >= 3


def test_saved_views_own_and_shared(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    db_conn.execute("insert into public.saved_views (name) values ('mine')")
    db_conn.execute("insert into public.saved_views (name, shared) values ('team', true)")
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("insert into public.saved_views (user_id, name) values (%s, 'spoof')", [rls_world.viewer])
    act_as(db_conn, "authenticated", rls_world.viewer)
    assert [r["name"] for r in db_conn.execute("select name from public.saved_views").fetchall()] == ["team"]


def test_email_recipients_are_admin_only(db_conn: Conn, rls_world: RlsWorld) -> None:
    """Settings > Email recipients: admins read and write the list; callers, viewers and visitors get nothing."""
    act_as(db_conn, "authenticated", rls_world.admin)
    db_conn.execute("insert into public.notify_recipients (email, name) values ('team@example.com', 'Team')")
    assert _count(db_conn, "select count(*) from public.notify_recipients") == 1
    assert db_conn.execute("update public.notify_recipients set morning = false").rowcount == 1
    with pytest.raises(errors.UniqueViolation), db_conn.transaction():
        db_conn.execute("insert into public.notify_recipients (email) values ('team@example.com')")
    with pytest.raises(errors.CheckViolation), db_conn.transaction():
        db_conn.execute("insert into public.notify_recipients (email) values ('Team@Example.com')")
    for user in (rls_world.caller, rls_world.viewer):
        act_as(db_conn, "authenticated", user)
        assert _count(db_conn, "select count(*) from public.notify_recipients") == 0
        assert db_conn.execute("update public.notify_recipients set active = false").rowcount == 0
        assert db_conn.execute("delete from public.notify_recipients").rowcount == 0
        _denied(db_conn, "insert into public.notify_recipients (email) values ('spoof@example.com')")
    act_as(db_conn, "anon")
    _denied(db_conn, "select * from public.notify_recipients")


# ---------------------------------------------------------------------------
# Storage: private proposals and backups buckets
# ---------------------------------------------------------------------------


def test_buckets_are_private_with_limits(db_conn: Conn) -> None:
    rows = {
        r["id"]: r
        for r in db_conn.execute(
            "select id, public, file_size_limit, allowed_mime_types from storage.buckets"
        ).fetchall()
    }
    assert rows["proposals"]["public"] is False and rows["proposals"]["file_size_limit"] == 20 * 1024 * 1024
    assert "application/pdf" in rows["proposals"]["allowed_mime_types"]
    assert rows["backups"]["public"] is False and rows["backups"]["file_size_limit"] == 50 * 1024 * 1024


def test_proposals_upload_rules_and_backups_stay_closed(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    db_conn.execute("insert into storage.objects (bucket_id, name) values ('proposals', 'lead/a.pdf')")
    assert db_conn.execute("delete from storage.objects where name = 'lead/a.pdf'").rowcount == 0  # admin only
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("insert into storage.objects (bucket_id, name) values ('backups', 'dump.gpg')")
    act_as(db_conn, "authenticated", rls_world.viewer)
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("insert into storage.objects (bucket_id, name) values ('proposals', 'lead/b.pdf')")
    assert _count(db_conn, "select count(*) from storage.objects") == 0
    act_as(db_conn, "authenticated", rls_world.admin)
    assert db_conn.execute("delete from storage.objects where name = 'lead/a.pdf'").rowcount == 1


# ---------------------------------------------------------------------------
# Anonymous visitors and schema-wide guarantees
# ---------------------------------------------------------------------------


def _public_relations(conn: Conn) -> list[tuple[str, str]]:
    return [
        (r["relname"], r["relkind"])
        for r in conn.execute(
            "select c.relname, c.relkind from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relkind in ('r', 'v', 'm', 'p', 'S') order by 1"
        ).fetchall()
    ]


def test_anon_has_no_privilege_on_any_relation(db_conn: Conn) -> None:
    leaks = []
    for name, kind in _public_relations(db_conn):
        if kind == "S":
            checks = [("select has_sequence_privilege('anon', %s, %s)", p) for p in ("USAGE", "SELECT", "UPDATE")]
        else:
            checks = [
                ("select has_table_privilege('anon', %s, %s)", p) for p in ("SELECT", "INSERT", "UPDATE", "DELETE")
            ]
        leaks += [f"{name} ({priv})" for query, priv in checks if _flag(db_conn, query, [f"public.{name}", priv])]
    assert leaks == []


def test_anon_cannot_execute_functions_that_matter(db_conn: Conn) -> None:
    rows = db_conn.execute(
        "select p.oid::regprocedure::text as fn from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'public' and p.prorettype <> 'trigger'::regtype "
        "and has_function_privilege('anon', p.oid, 'EXECUTE')"
    ).fetchall()
    assert {r["fn"] for r in rows} <= ANON_CALLABLE_OK


def test_anon_reads_nothing(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "anon")
    for relation in ("leads", "v_leads_caller", "v_today", "businesses", "activities"):
        _denied(db_conn, f"select * from public.{relation}")
    _denied(db_conn, "select public.db_size_mb()")
    assert db_conn.execute("select public.auth_role() as role").fetchone() == {"role": "none"}
    assert _count(db_conn, "select count(*) from storage.objects") == 0


def test_every_table_has_rls_enabled(db_conn: Conn) -> None:
    rows = db_conn.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity"
    ).fetchall()
    assert [r["relname"] for r in rows] == []


def test_every_view_runs_as_the_caller_except_v_leads_admin(db_conn: Conn) -> None:
    rows = db_conn.execute(
        "select c.relname, coalesce(c.reloptions, '{}') as opts from pg_class c "
        "join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind = 'v'"
    ).fetchall()
    assert sorted(r["relname"] for r in rows if "security_invoker=true" not in r["opts"]) == ["v_leads_admin"]
    assert len(rows) >= 17


def test_objects_created_after_0003_are_private_unless_granted(db_conn: Conn) -> None:
    """2.5 rule 10: a later table or view is invisible to app users until its migration grants it."""
    later = (
        "v_sheet_leads",
        "v_spend_today",
        "v_quota_today",
        "v_quota_month",
        "v_lead_funnel",
        "weight_versions",
        "reports",
    )
    query = "select has_table_privilege('authenticated', %s, 'SELECT')"
    granted = {name for name in later if _flag(db_conn, query, [f"public.{name}"])}
    assert granted == {"weight_versions", "reports"}
