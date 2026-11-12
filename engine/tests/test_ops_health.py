"""`nlead health`: each check, the overall status, the summary, alerts and retention pruning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.ops import health

from . import seed
from .helpers import Conn


def by_name(checks: list[health.Check]) -> dict[str, health.Check]:
    return {c.name: c for c in checks}


@pytest.fixture
def gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    settings_module.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def test_database_size_levels(db_conn: Conn, monkeypatch: pytest.MonkeyPatch) -> None:
    assert health.check_database(db_conn).status == "ok"
    for size, status in ((349.9, "ok"), (350, "warn"), (400, "alert")):
        monkeypatch.setattr(db, "scalar", lambda *a, size=size, **k: size)
        check = health.check_database(db_conn)
        assert check.status == status and f"{size:.1f} MB of 500 MB" in check.detail


def test_migrations_are_all_applied(db_conn: Conn) -> None:
    check = health.check_migrations(db_conn)
    assert check.status == "ok" and check.data["applied"] >= 8


def test_gemini_must_be_on_and_have_a_key(db_conn: Conn, monkeypatch: pytest.MonkeyPatch) -> None:
    assert by_name(health.check_providers(db_conn))["ai.gemini"].status == "fail"  # no key in tests
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    settings_module.get_settings.cache_clear()
    checks = by_name(health.check_providers(db_conn))
    assert checks["ai.gemini"].status == "ok" and checks["ai.openai"].status == "info"
    db.set_setting("providers_enabled", {"gemini": False, "openai": True}, conn=db_conn)
    checks = by_name(health.check_providers(db_conn))
    assert checks["ai.gemini"].status == "fail" and checks["ai.openai"].status == "warn"


def test_open_breakers_are_reported(db_conn: Conn, gemini_key: None) -> None:
    db_conn.execute(
        "update public.source_health set blocked_until = now() + interval '2 hours', last_error = '429 quota' "
        "where source = 'llm:gemini'"
    )
    check = by_name(health.check_providers(db_conn))["ai.gemini.breaker"]
    assert check.status == "alert" and "429 quota" in check.detail


@pytest.mark.parametrize(("inr", "status"), [(100, "ok"), (610, "warn"), (760, "alert")])
def test_spend_against_the_cap(db_conn: Conn, inr: float, status: str) -> None:
    db_conn.execute("insert into public.costs (provider, task, inr) values ('gemini', 'health_test', %s)", [inr])
    assert health.check_spend(db_conn).status == status


def test_quotas_warn_near_the_daily_cap(db_conn: Conn) -> None:
    db_conn.execute("insert into public.costs (provider, task, calls) values ('google_search', 'grounded_search', 150)")
    checks = by_name(health.check_quotas(db_conn))
    assert checks["quota.grounded_search"].status == "warn" and checks["quota.grounded_search"].data["day"] >= 150
    assert checks["quota.places_details"].data["day_cap"] == 230


def test_sources_blocked_disabled_and_stale(db_conn: Conn) -> None:
    db_conn.execute("update public.source_health set blocked_until = now() + interval '7 days' where source = 'apna'")
    checks = by_name(health.check_sources(db_conn, "prod"))
    assert checks["source.apna"].status == "warn" and "never work around" in checks["source.apna"].detail
    assert checks["source.adzuna"].status == "info"
    assert checks["source.gdelt"].status == "warn"  # never ran: stale in prod
    assert by_name(health.check_sources(db_conn, "dev"))["source.gdelt"].status == "info"
    assert not any(name.startswith("source.llm") for name in checks)


def test_runs_failed_stuck_and_old(db_conn: Conn) -> None:
    now = datetime.now(UTC) + timedelta(days=30)  # later than any run other tests wrote
    db_conn.execute(
        "insert into public.runs (kind, started_at, status, error) values "
        "('night', %s, 'failed', 'Traceback\nRuntimeError: database went away'), ('morning', %s, 'running', null), "
        "('weekly', %s, 'ok', null)",
        [now - timedelta(hours=4), now - timedelta(hours=5), now - timedelta(days=10)],
    )
    checks = by_name(health.check_runs(db_conn, "prod", now))
    assert checks["run.night"].status == "alert" and "database went away" in checks["run.night"].detail
    assert checks["run.morning"].status == "warn" and "stuck" in checks["run.morning"].detail
    assert checks["run.weekly"].status == "warn"  # older than 8 days in prod


def test_stuck_batches(db_conn: Conn) -> None:
    db_conn.execute(
        "insert into public.llm_batches (provider, provider_batch_id, task, status, submitted_at) "
        "values ('gemini', 'batch-health-test', 'extract_facts', 'running', now() - interval '30 hours')"
    )
    assert health.check_batches(db_conn).status == "warn"


def test_overall_status_and_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = [health.Check("a", "ok", ""), health.Check("b", "warn", ""), health.Check("c", "info", "")]
    assert health.worst(checks) == "warn" and health.worst([]) == "ok"
    text = health.render_text(checks)
    assert text.splitlines()[0].startswith("check") and "overall: WARN" in text
    monkeypatch.setattr(health, "collect", lambda *a, **k: [*checks, health.Check("ai.gemini", "fail", "no key")])
    assert health.check_all()["status"] == "fail"
    with pytest.raises(health.HealthCheckFailed, match="no key"):
        health.check_all(fail_fast=True)


def test_collect_and_daily_summary_on_a_real_database(engine_db: str, gemini_key: None) -> None:
    checks = health.collect()
    names = {c.name for c in checks}
    assert {"database", "migrations", "ai.gemini", "spend", "quota.grounded_search", "run.night", "ai.batches"} <= names
    summary = health.daily_summary()
    first = summary.splitlines()[0]
    assert first.startswith("### Nument Leads health,") and "**Today:** spend" in summary
    assert "| Check | Status | Detail |" in summary and "{" not in first


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


# Alert emails: tests/test_ops_emails.py


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def _page(conn: Conn, business_id: str, url: str, days_old: int, text: str = "Clinic page text") -> None:
    conn.execute(
        "insert into public.pages (business_id, url, fetched_at, text, text_hash) values (%s, %s, %s, %s, 'h')",
        [business_id, url, datetime.now(UTC) - timedelta(days=days_old), text],
    )


def _seed_retention(conn: Conn) -> dict[str, Any]:
    now = datetime.now(UTC)
    old_places = seed.business(
        conn, rating=4.6, review_count=410, place_id=f"p-{now.timestamp()}", places_fetched_at=now - timedelta(days=31)
    )
    fresh_places = seed.business(conn, rating=4.1, review_count=120, places_fetched_at=now - timedelta(days=5))
    plain = seed.business(conn)
    lead_id, lead_biz = seed.lead(conn)
    golden = seed.business(conn)
    conn.execute("insert into public.golden_labels (business_id, label) values (%s, 'good')", [golden])
    tag = uuid_tag()
    _page(conn, plain, f"https://{tag}.example.com/young", 10)
    _page(conn, plain, f"https://{tag}.example.com/month", 40)
    _page(conn, plain, f"https://{tag}.example.com/old", 100)
    _page(conn, plain, f"https://{tag}.example.com/long", 1, "x" * 25_000)
    _page(conn, lead_biz, f"https://{tag}.example.com/lead-month", 40)
    _page(conn, lead_biz, f"https://{tag}.example.com/lead-old", 100)
    _page(conn, golden, f"https://{tag}.example.com/golden", 100)
    conn.execute(
        "insert into public.contacts (business_id, phone_e164, phone_type, source, verified_at, do_not_contact) values "
        "(%s, '+919811100001', 'mobile', 'google_listing', now() - interval '40 days', false), "
        "(%s, '+919811100002', 'mobile', 'google_listing', now() - interval '40 days', true), "
        "(%s, '+919811100003', 'mobile', 'google_listing', now() - interval '3 days', false), "
        "(%s, '+919811100004', 'mobile', 'website', now() - interval '400 days', false)",
        [plain, plain, plain, plain],
    )
    conn.execute(
        "insert into public.costs (provider, task, at) values ('gemini', 'prune_test', now() - interval '400 days')"
    )
    conn.execute(
        "insert into public.llm_cache (key, task, model, response, expires_at) "
        "values (%s, 't', 'm', '{}', now() - interval '1 day')",
        [f"prune-test-{tag}"],
    )
    return {
        "old_places": old_places,
        "fresh_places": fresh_places,
        "plain": plain,
        "lead": lead_id,
        "lead_biz": lead_biz,
        "golden": golden,
        "tag": tag,
    }


def uuid_tag() -> str:
    import uuid

    return uuid.uuid4().hex[:10]


def test_prune_applies_the_retention_rules(db_conn: Conn) -> None:
    s = _seed_retention(db_conn)
    counts = health.prune(db_conn)
    assert (
        counts["places_content"] >= 1
        and counts["google_listing_contacts"] >= 1
        and counts["costs_older_than_a_year"] >= 1
    )

    def biz(bid: str) -> dict[str, Any]:
        row = db.fetch_one(
            "select rating, review_count, place_id from public.businesses where id = %s", [bid], conn=db_conn
        )
        assert row is not None
        return row

    assert biz(s["old_places"])["rating"] is None and biz(s["old_places"])["place_id"]  # place_id stays forever
    assert biz(s["fresh_places"])["review_count"] == 120
    phones = {
        r["phone_e164"]
        for r in db.fetch_all(
            "select phone_e164 from public.contacts where business_id = %s", [s["plain"]], conn=db_conn
        )
    }
    assert phones == {"+919811100002", "+919811100003", "+919811100004"}  # old listing phone gone; opt-out kept

    pages = {
        r["url"].rsplit("/", 1)[1]: r
        for r in db.fetch_all(
            "select url, text, text_hash from public.pages where url like %s",
            [f"https://{s['tag']}.example.com/%"],
            conn=db_conn,
        )
    }
    assert pages["young"]["text"] and pages["month"]["text"] is None and pages["month"]["text_hash"] == "h"
    assert "old" not in pages  # a non-lead page row goes after 90 days
    assert len(pages["long"]["text"]) == health.PAGE_TEXT_MAX
    assert pages["lead-month"]["text"] and pages["lead-old"]["text"] is None  # leads keep text for 90 days, and the row
    assert pages["golden"]["text"]  # golden businesses are never pruned
    assert db.scalar("select count(*) from public.costs where task = 'prune_test'", conn=db_conn) == 0


def test_prune_dry_run_counts_and_keeps_everything(db_conn: Conn) -> None:
    s = _seed_retention(db_conn)
    counts = health.prune(db_conn, dry_run=True)
    assert counts["page_rows_not_leads"] >= 1 and counts["places_content"] >= 1
    assert (
        float(db.scalar("select rating from public.businesses where id = %s", [s["old_places"]], conn=db_conn)) == 4.6
    )
    assert (
        db.scalar(
            "select count(*) from public.pages where url like %s", [f"https://{s['tag']}.example.com/%"], conn=db_conn
        )
        == 7
    )


@pytest.mark.parametrize(
    ("probe", "start", "end", "switched"),
    [
        (True, False, True, True),
        (False, True, False, True),
        (None, False, False, False),  # unsure (network): leave it as it is
        (True, True, True, False),  # already on: nothing to do
    ],
)
def test_openai_switches_itself_on_and_off(
    db_conn: Conn, probe: bool | None, start: bool, end: bool, switched: bool
) -> None:
    db.set_setting("providers_enabled", {"gemini": True, "openai": start}, conn=db_conn)
    check = health.auto_switch_openai(db_conn, probe=lambda: probe)
    assert (check is not None) is switched
    assert db.get_setting("providers_enabled", {}, conn=db_conn)["openai"] is end


def test_openai_auto_switch_can_be_turned_off(db_conn: Conn) -> None:
    db.set_setting("providers_enabled", {"gemini": True, "openai": False}, conn=db_conn)
    db.set_setting(health.AUTO_OPENAI_KEY, False, conn=db_conn)
    assert health.auto_switch_openai(db_conn, probe=lambda: True) is None
    assert db.get_setting("providers_enabled", {}, conn=db_conn)["openai"] is False
    db.set_setting(health.AUTO_OPENAI_KEY, True, conn=db_conn)
