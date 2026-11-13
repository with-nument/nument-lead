"""Schema behaviour: seeds, triggers, constraints and read views (Step 2 'done when' list, Step 17.2.3).

Every test works inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from psycopg import errors, sql

from .helpers import Conn

IST = ZoneInfo("Asia/Kolkata")
WAVE1 = {"clinics-in", "realestate-in", "education-in", "clinics-ae", "realestate-ae", "education-ae"}
A12_TABLES = {
    "settings", "segments", "businesses", "source_records", "signals", "pages", "facts", "contacts", "scores",
    "leads", "activities", "feedback", "suppression", "runs", "costs", "llm_batches", "source_health",
    "sheet_snapshots", "golden_labels", "profiles", "custom_queries", "inbox_posts",
}  # fmt: skip


def _insert(conn: Conn, table: str, values: dict[str, Any]) -> str:
    query = sql.SQL("insert into public.{} ({}) values ({}) returning id").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join([sql.Placeholder()] * len(values)),
    )
    row = conn.execute(query, list(values.values())).fetchone()
    assert row is not None
    return str(row["id"])


def _business(conn: Conn, segment: str = "clinics-in", **cols: Any) -> str:
    tag = uuid.uuid4().hex[:8]
    return _insert(conn, "businesses", {"segment_id": segment, "name": f"Test Clinic {tag}", "norm_name": f"test clinic {tag}",
                                        "country": segment[-2:], "city": "Pune", **cols})  # fmt: skip


def _lead(conn: Conn, business_id: str, **cols: Any) -> str:
    return _insert(conn, "leads", {"business_id": business_id, "segment_id": "clinics-in", "grade": "A",
                                   "pitch_mode": "visible_pain", **cols})  # fmt: skip


def _activities(conn: Conn, lead_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        "select type, source, user_id, payload from public.activities where lead_id = %s order by type", [lead_id]
    ).fetchall()


def _scored_lead(conn: Conn, grade: str = "A", total: float = 78, **lead_cols: Any) -> tuple[str, str]:
    """A business with a name-only decision maker, a reception mobile, an active signal and a scored lead."""
    biz = _business(conn, web_domain=f"{uuid.uuid4().hex[:8]}.example.com")
    conn.execute(
        "insert into public.contacts (business_id, name, source, is_decision_maker) values (%s, 'Dr. Name Only', 'website', true)",
        [biz],
    )
    conn.execute("insert into public.contacts (business_id, name, phone_e164, phone_type, source) "
                 "values (%s, 'Reception', '+919811111111', 'mobile', 'website')", [biz])  # fmt: skip
    score = _insert(conn, "scores", {"business_id": biz, "version": "s1.0", "fit": 3, "total": total, "grade": grade,
                                     "pitch_mode": "visible_pain"})  # fmt: skip
    conn.execute(
        "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, quote, dedupe_key) "
        "values (%s, 'hiring_frontdesk', 'visible_pain', 8, now() - interval '2 days', now() + interval '28 days', "
        "'apna', 'Hiring a front desk executive', %s)",
        [biz, f"apna:test:{biz}"],
    )
    return biz, _lead(conn, biz, grade=grade, score_id=score, **lead_cols)


# ---------------------------------------------------------------------------
# Tables, extensions and seed (0001, 0004)
# ---------------------------------------------------------------------------


def test_every_contract_table_exists(db_conn: Conn) -> None:
    rows = db_conn.execute("select tablename from pg_tables where schemaname = 'public'").fetchall()
    assert A12_TABLES | {"llm_cache", "llm_batch_reservations", "saved_views", "weight_versions", "reports"} <= {
        r["tablename"] for r in rows
    }
    extensions = {r["extname"] for r in db_conn.execute("select extname from pg_extension").fetchall()}
    assert {"pgcrypto", "pg_trgm", "unaccent"} <= extensions


def test_seed_segments_and_quotas(db_conn: Conn) -> None:
    rows = db_conn.execute("select id, daily_quota, enabled from public.segments").fetchall()
    seeded = [r for r in rows if r["id"] in WAVE1]
    # A segment sync (test_cli runs one) may add newer segments such as firms-in and apply the YAML switches
    # (real estate is off since 12 Nov 2026); the seed itself is the six wave-1 rows with quotas adding to 300.
    newer = {f"firms-{cc}" for cc in ("in", "ae", "us", "gb", "au", "ca", "sg")}
    newer |= {f"partners-{cc}" for cc in ("in", "us", "gb", "au", "ae")}
    newer |= {f"{d}-{cc}" for d in ("clinics", "professional") for cc in ("us", "gb", "au")}
    assert {r["id"] for r in seeded} == WAVE1 and {r["id"] for r in rows} <= WAVE1 | newer
    assert sum(r["daily_quota"] for r in seeded) == 300
    assert all(r["enabled"] for r in seeded if not r["id"].startswith("realestate"))


def test_seed_settings_with_openai_off_and_review_sources_on(db_conn: Conn) -> None:
    settings = {r["key"]: r["value"] for r in db_conn.execute("select key, value from public.settings").fetchall()}
    assert settings["daily_cap_inr"] == 750 and settings["research_per_day"] == 800  # 0014: 50 to 60 leads a day
    assert settings["providers_enabled"] == {"gemini": True, "openai": False}
    assert settings["sources_enabled"]["adzuna"] is False
    assert settings["sources_enabled"]["practo"] is True and settings["sources_enabled"]["maps_reviews"] is True
    assert settings["practo.pages_per_day"] == 150 and settings["maps_reviews.lookups_per_day"] == 100
    assert set(settings["segment_weights"]) == set(settings["segments_enabled"]) == WAVE1
    assert settings["places_details_cap_in"] == 230 and settings["places_details_cap_global"] == 30
    assert settings["sheet_state"] == {
        "master": {"state": "ok"},
        "caller": {"state": "ok"},
        "staging_master": {"state": "ok"},
        "staging_caller": {"state": "ok"},
    }
    assert (settings["send_per_day"], settings["today_rows_max"], settings["weekly_contact_target"]) == (50, 60, 150)
    for key in ("overture_release", "budget_alert_day", "score_weights", "score_weights_frozen"):
        assert key in settings, key


def test_seed_source_health(db_conn: Conn) -> None:
    rows = {
        r["source"]: r["enabled"]
        for r in db_conn.execute("select source, enabled from public.source_health").fetchall()
    }
    assert len(rows) == 15
    assert {s for s, on in rows.items() if not on} == {"adzuna", "llm:openai"}


# ---------------------------------------------------------------------------
# Triggers own lead_created, stage_change, grade_change and message_edited (2.5 rule 9)
# ---------------------------------------------------------------------------


def test_new_auth_user_gets_a_viewer_profile_even_when_created_by_the_auth_server(db_conn: Conn) -> None:
    """The auth server inserts users as its own role, which has no EXECUTE grant on our functions."""
    db_conn.execute("set local role supabase_auth_admin")
    row = db_conn.execute(
        "insert into auth.users (email, raw_user_meta_data) values ('new.user@example.com', %s) returning id",
        [json.dumps({"must_change_password": True})],
    ).fetchone()
    db_conn.execute("reset role")
    assert row is not None
    profile = db_conn.execute("select role, full_name from public.profiles where user_id = %s", [row["id"]]).fetchone()
    assert profile == {"role": "viewer", "full_name": "new.user"}


def test_lead_insert_logs_lead_created_from_the_engine(db_conn: Conn) -> None:
    lead = _lead(db_conn, _business(db_conn), test_group="clinics-in:visible_pain:missed_calls")
    assert _activities(db_conn, lead) == [
        {"type": "lead_created", "source": "engine", "user_id": None,
         "payload": {"grade": "A", "pitch_mode": "visible_pain", "channel": "whatsapp",
                     "test_group": "clinics-in:visible_pain:missed_calls"}},
    ]  # fmt: skip


def test_sheet_context_labels_stage_and_grade_changes(db_conn: Conn) -> None:
    lead = _lead(db_conn, _business(db_conn))
    db_conn.execute("select set_config('app.source', 'sheet', true), set_config('app.context', %s, true)",
                    [json.dumps({"sheet": "master"})])  # fmt: skip
    db_conn.execute("update public.leads set stage = 'contacted', grade = 'B' where id = %s", [lead])
    row = db_conn.execute("select wa_at from public.leads where id = %s", [lead]).fetchone()
    assert row is not None and row["wa_at"] in {
        datetime.now(IST).date(),
        (datetime.now(IST) - timedelta(minutes=1)).date(),
    }
    by_type = {a["type"]: a for a in _activities(db_conn, lead)}
    assert by_type["stage_change"]["source"] == "sheet"
    assert by_type["stage_change"]["payload"] == {"from": "new", "to": "contacted", "sheet": "master"}
    assert by_type["grade_change"]["payload"] == {"from": "A", "to": "B", "sheet": "master"}


def test_contacted_keeps_a_given_date(db_conn: Conn) -> None:
    lead = _lead(db_conn, _business(db_conn))
    db_conn.execute("update public.leads set stage = 'contacted', wa_at = '2026-11-01' where id = %s", [lead])
    assert db_conn.execute("select wa_at from public.leads where id = %s", [lead]).fetchone() == {
        "wa_at": date(2026, 11, 1)
    }


def test_message_edits_are_logged_only_for_app_users(db_conn: Conn) -> None:
    lead = _lead(db_conn, _business(db_conn), message="first draft")
    db_conn.execute("update public.leads set message = 'engine rewrite' where id = %s", [lead])
    assert "message_edited" not in {a["type"] for a in _activities(db_conn, lead)}


def test_updated_at_is_maintained(db_conn: Conn) -> None:
    biz = _business(db_conn, updated_at=datetime(2026, 1, 1, tzinfo=IST))
    db_conn.execute("update public.businesses set city = 'Mumbai' where id = %s", [biz])
    assert db_conn.execute(
        "select updated_at = now() as fresh from public.businesses where id = %s", [biz]
    ).fetchone() == {"fresh": True}


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def test_one_open_lead_per_business(db_conn: Conn) -> None:
    biz = _business(db_conn)
    first = _lead(db_conn, biz)
    with pytest.raises(errors.UniqueViolation, match="leads_one_open_per_business"), db_conn.transaction():
        _lead(db_conn, biz)
    db_conn.execute("update public.leads set stage = 'not_now' where id = %s", [first])
    _lead(db_conn, biz)  # a closed lead allows a new cycle


@pytest.mark.parametrize(
    "statement",
    [
        "insert into public.contacts (business_id, phone_e164, source) values (%s, '9800000000', 'website')",
        "insert into public.contacts (business_id, source) values (%s, 'website')",
        "insert into public.signals (business_id, type, category, observed_at, expires_at, source, dedupe_key) "
        "values (%s, 'hiring_frontdesk', 'visible_pain', now(), now() - interval '1 day', 'apna', 'x')",
        "insert into public.scores (business_id, version, fit, total, grade, pitch_mode) values (%s, 's1', 4, 50, 'C', 'fit_only')",
        "insert into public.activities (lead_id, source, type) select id, 'engine', 'not_a_type' from public.leads where business_id = %s",
        "insert into public.source_records (source, source_key, business_id) select 'rera_maharashtra', 'x', %s",
        "insert into public.costs (provider, task) select 'google_maps', 'places' where %s::uuid is not null",
    ],
)
def test_check_constraints_reject_bad_rows(db_conn: Conn, statement: str) -> None:
    biz = _business(db_conn)
    _lead(db_conn, biz)
    with pytest.raises(errors.CheckViolation), db_conn.transaction():
        db_conn.execute(statement, [biz])


def test_known_values_are_accepted(db_conn: Conn) -> None:
    for source in ("overture", "places", "art_registry", "legacy", "legacy_skip"):
        db_conn.execute(
            "insert into public.source_records (source, source_key) values (%s, %s)", [source, uuid.uuid4().hex]
        )
    for provider in ("gemini", "openai", "cache", "google_places", "google_search", "pagespeed", "other"):
        db_conn.execute(
            "insert into public.costs (provider, task, fallback_from) values (%s, 'probe', 'openai:gpt-6.1-terra')",
            [provider],
        )
    for status in ("new", "processing", "processed", "researched", "lead_created", "rejected"):
        db_conn.execute("insert into public.inbox_posts (text, status) values ('post', %s)", [status])
    for status in ("new", "processing", "researched", "lead_created", "rejected", "running", "done", "failed"):
        db_conn.execute(
            "insert into public.custom_queries (segment_id, query, status) values ('clinics-in', 'q', %s)", [status]
        )


def test_segment_ids_must_match_domain_and_country(db_conn: Conn) -> None:
    with pytest.raises(errors.CheckViolation), db_conn.transaction():
        db_conn.execute("update public.segments set country = 'in' where id = 'clinics-ae'")


# ---------------------------------------------------------------------------
# Views (0002, 0005 to 0007)
# ---------------------------------------------------------------------------


def test_v_today_lists_new_reachable_a_and_b_leads(db_conn: Conn) -> None:
    _, a_lead = _scored_lead(db_conn)
    _, c_lead = _scored_lead(db_conn, grade="C", total=45)
    _, skipped = _scored_lead(db_conn, skipped_until=datetime.now(IST) + timedelta(days=1))
    biz, suppressed = _scored_lead(db_conn)
    domain = db_conn.execute("select web_domain from public.businesses where id = %s", [biz]).fetchone()
    assert domain is not None
    db_conn.execute(
        "insert into public.suppression (web_domain, reason) values (%s, 'founder_skip')", [domain["web_domain"]]
    )
    rows = {
        r["lead_id"]: r
        for r in db_conn.execute(
            "select lead_id::text, company, phone_e164, top_signal_type from public.v_today"
        ).fetchall()
    }
    assert a_lead in rows and c_lead not in rows and skipped not in rows and suppressed not in rows
    assert rows[a_lead]["phone_e164"] == "+919811111111" and rows[a_lead]["top_signal_type"] == "hiring_frontdesk"


def test_primary_contact_prefers_a_phone_and_skips_suppressed_numbers(db_conn: Conn) -> None:
    biz, lead = _scored_lead(db_conn)
    row = db_conn.execute("select phone_e164, contact_name from public.v_leads_caller where id = %s", [lead]).fetchone()
    assert row == {"phone_e164": "+919811111111", "contact_name": "Reception"}
    db_conn.execute("insert into public.suppression (phone_e164, reason) values ('+919811111111', 'opt_out')")
    assert db_conn.execute(
        "select count(*) as n from public.v_primary_contact where business_id = %s", [biz]
    ).fetchone() == {"n": 0}


def test_v_followups_due_day_3_then_day_7(db_conn: Conn) -> None:
    today = datetime.now(IST).date()
    _, d3 = _scored_lead(db_conn, stage="contacted", wa_at=today - timedelta(days=3), followup_d3="day 3 text")
    _, early = _scored_lead(db_conn, stage="contacted", wa_at=today - timedelta(days=1))
    _, d7 = _scored_lead(db_conn, stage="contacted", wa_at=today - timedelta(days=8), d3_at=today - timedelta(days=4))
    _, replied = _scored_lead(db_conn, stage="talking", wa_at=today - timedelta(days=9))
    rows = {
        (r["lead_id"], r["which"])
        for r in db_conn.execute("select lead_id::text, which from public.v_followups_due").fetchall()
    }
    assert (d3, "d3") in rows and (d7, "d7") in rows
    assert not {(early, "d3"), (d3, "d7"), (d7, "d3"), (replied, "d3"), (replied, "d7")} & rows


def test_v_funnel_keeps_the_furthest_stage(db_conn: Conn) -> None:
    _, lead = _scored_lead(db_conn)
    for stage in ("contacted", "talking", "lost"):
        db_conn.execute("update public.leads set stage = %s where id = %s", [stage, lead])
    row = db_conn.execute(
        "select reached_contacted, reached_talking, reached_discovery from public.v_funnel where lead_id = %s", [lead]
    ).fetchone()
    assert row == {"reached_contacted": True, "reached_talking": True, "reached_discovery": False}
    learn = db_conn.execute(
        "select max_rank, contacted_at is not null as contacted from public.v_lead_funnel where lead_id = %s", [lead]
    ).fetchone()
    assert learn == {"max_rank": 2, "contacted": True}


def test_v_sheet_leads_hides_new_c_leads_but_keeps_worked_ones(db_conn: Conn) -> None:
    _, c_new = _scored_lead(db_conn, grade="C", total=45)
    _, c_worked = _scored_lead(db_conn, grade="C", total=45, stage="talking")
    _, a_lead = _scored_lead(db_conn, deal_value_inr=90000)
    rows = {r["lead_id"]: r for r in db_conn.execute(
        "select lead_id::text, deal_value_inr, phone_e164, top_signal_quote from public.v_sheet_leads").fetchall()}  # fmt: skip
    assert c_new not in rows and c_worked in rows
    assert float(rows[a_lead]["deal_value_inr"]) == 90000
    assert (
        rows[a_lead]["phone_e164"] == "+919811111111"
        and rows[a_lead]["top_signal_quote"] == "Hiring a front desk executive"
    )


def test_v_verified_facts_keeps_the_latest_verified_value(db_conn: Conn) -> None:
    biz = _business(db_conn)
    for value, verified, age in (("2", True, "2 days"), ("3", True, "1 day"), ("9", False, "1 hour")):
        db_conn.execute(
            "insert into public.facts (business_id, field, value, verified, created_at) values (%s, 'branches', %s, %s, now() - %s::interval)",
            [biz, value, verified, age],
        )
    assert db_conn.execute("select value from public.v_verified_facts where business_id = %s", [biz]).fetchall() == [
        {"value": 3}
    ]


def test_spend_and_quota_views_count_today_in_ist(db_conn: Conn) -> None:
    before = db_conn.execute("select inr from public.v_spend_today").fetchone()
    assert before is not None
    db_conn.execute(
        "insert into public.costs (provider, model, task, calls, usd, inr) values "
        "('gemini', 'gemini-3-flash', 'quota_probe', 2, 0.5, 44), ('gemini', 'gemini-3-flash', 'quota_probe', 1, 0.1, 8.8)"
    )
    db_conn.execute(
        "insert into public.costs (provider, task, calls, inr, at) values ('google_places', 'quota_probe', 5, 0, now() - interval '40 days')"
    )
    after = db_conn.execute("select inr from public.v_spend_today").fetchone()
    assert after is not None and float(after["inr"]) - float(before["inr"]) == pytest.approx(52.8)
    assert db_conn.execute("select calls from public.v_quota_today where task = 'quota_probe'").fetchall() == [
        {"calls": 3}
    ]
    assert db_conn.execute(
        "select provider, calls from public.v_quota_month where task = 'quota_probe'"
    ).fetchall() == [{"provider": "gemini", "calls": 3}]
    daily = db_conn.execute(
        "select calls, inr from public.v_costs_daily where task = 'quota_probe' and provider = 'gemini'"
    ).fetchall()
    assert [(r["calls"], float(r["inr"])) for r in daily] == [(3, pytest.approx(52.8))]


def test_kpis_and_source_health_views(db_conn: Conn) -> None:
    kpis = db_conn.execute("select * from public.v_kpis_week").fetchone()
    assert kpis is not None and {"contacted_this_week", "overdue", "new_waiting"} <= set(kpis)
    health = {
        r["source"]: r["health"]
        for r in db_conn.execute("select source, health from public.v_source_health").fetchall()
    }
    assert health["adzuna"] == "disabled" and health["overture"] == "stale"


def test_db_size_mb(db_conn: Conn) -> None:
    row = db_conn.execute("select public.db_size_mb() as mb").fetchone()
    assert row is not None and float(row["mb"]) > 0
