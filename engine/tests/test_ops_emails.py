"""The engine's emails: rendering with sample and empty data, money only for admins, the morning phase."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
import respx
from psycopg.rows import dict_row

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.ops import emails, health, notify
from nument_engine.pipeline.runs import Options, RunContext

DASHES = re.compile(r"[\u2013\u2014]")  # no en or em dashes in any copy


def configure(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings_module.get_settings.cache_clear()


def visible_text(html: str) -> str:
    body = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def assert_well_formed(email: notify.Email) -> None:
    assert email.subject and email.text.strip()
    assert email.html.startswith("<!doctype html>") and email.html.rstrip().endswith("</html>")
    for text in (email.subject, email.html, email.text):
        assert not DASHES.search(text)
        assert "Undefined" not in text and "{{" not in text and "{%" not in text and "None" not in visible_text(text)
    assert "/settings/email" in email.html


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", emails.SAMPLE_KINDS)
@pytest.mark.parametrize("admin", [True, False])
def test_every_sample_renders(kind: str, admin: bool) -> None:
    assert_well_formed(emails.sample(kind, admin=admin))


def test_morning_list_shows_the_best_leads_first() -> None:
    m = emails.sample_morning(day=date(2026, 11, 13))
    email = emails.render_morning(m, admin=True)
    text = visible_text(email.html)
    assert email.subject == "4 new leads for Friday, 13 Nov"
    assert "4 new leads are ready" in text and "Why now:" in text
    assert text.index("Sunrise Skin") < text.index("Kavya Fertility") < text.index("Smile Studio")
    assert "612 Google reviews, rated 4.7 · 6 doctors" in text
    assert "https://wa.me/919811012345?text=" in email.html  # mobiles get WhatsApp
    assert "tel:+912226301234" in email.html and "Call +91 22 2630 1234" in text  # landlines get a call link
    assert "Spend today ₹412 of ₹750" in text and "₹412" in email.text
    assert "Aarna Dental Care" in text and "Day 3 follow-up" in text
    assert "Open lead: https://nument-leads-web.onrender.com/leads" in email.text


def test_morning_list_shows_only_the_top_five() -> None:
    m = emails.sample_morning()
    m.leads = [replace(m.leads[0], id=str(i), name=f"Clinic {i}") for i in range(8)]
    email = emails.render_morning(m, admin=True)
    text = visible_text(email.html)
    assert "Clinic 4" in text and "Clinic 5" not in text
    assert "See all 8 in the app" in text and "See all 8 in the app" in email.text


def test_morning_list_without_new_leads_is_short_and_says_so() -> None:
    m = emails.sample_morning(empty=True, day=date(2026, 11, 13))
    email = emails.render_morning(m, admin=True)
    text = visible_text(email.html)
    assert email.subject == "No new leads for Friday, 13 Nov"
    assert "No new leads today" in text and "Open the app" in text
    assert "Why now" not in text and "Open lead" not in text and "New today" not in text
    assert "Aarna Dental Care" in text  # follow-ups still show
    m.followups = []
    quiet = emails.render_morning(m, admin=False)
    assert_well_formed(quiet)
    assert "Older leads are still in the app" in visible_text(quiet.html) and "Follow-ups due" not in quiet.html


def test_one_new_lead_reads_naturally() -> None:
    m = emails.sample_morning()
    m.leads = m.leads[:1]
    email = emails.render_morning(m, admin=True)
    assert "1 new lead is ready" in visible_text(email.html) and email.subject.startswith("1 new lead for ")


def test_team_members_never_see_money() -> None:
    morning = emails.render_morning(emails.sample_morning(), admin=False)
    alert = emails.sample("alert", admin=False)
    weekly = emails.sample("weekly", admin=False)
    for email in (morning, alert, weekly):
        assert "₹" not in email.html and "₹" not in email.text and "$" not in visible_text(email.html)
    assert "This week" in visible_text(morning.html) and "messages sent" in visible_text(morning.html)
    assert "Money won" not in weekly.html and ">Cost</div>" not in weekly.html
    admin_weekly = emails.sample("weekly", admin=True)
    assert "Money won" in admin_weekly.html and "₹85,000" in admin_weekly.html and ">Cost</div>" in admin_weekly.html


def test_weekly_report_renders_the_report_content() -> None:
    content, markdown = emails.sample_weekly()
    email = emails.render_weekly(content, markdown, admin=True)
    text = visible_text(email.html)
    assert email.subject == "Weekly report: 2 to 8 Nov 2026"
    assert "The week of 2 to 8 Nov 2026" in text and "Do this week" in text
    assert "17% reply rate" in text and "Lead quality" in text and "Exclusion idea" in text
    assert "<span" in email.html and "clinics-in:review_pain:v1" in text  # `code` styled, not raw backticks
    assert "`" not in text
    assert email.text.startswith(markdown.rstrip())


def test_weekly_report_escapes_text() -> None:
    content, markdown = emails.sample_weekly()
    content["actions"] = ["Check <script>alert(1)</script> & `x`"]
    html = emails.render_weekly(content, markdown, admin=True).html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_alerts_render_in_plain_words() -> None:
    item = emails.alert_item(
        "run.night", "alert", "failed, started 13 Nov 2026, 02:00 IST: failed (RuntimeError: boom)"
    )
    assert item.title == "The night run failed"
    assert item.detail == "Started 13 Nov 2026, 02:00 IST. Last error: RuntimeError: boom"
    single = emails.render_alerts([item], admin=True)
    assert single.subject == "Alert: The night run failed" and "The night run failed" in single.html
    near = emails.alert_item("spend", "warn", "₹650 of ₹750 today (87%): past the 80% alert line")
    cap = emails.alert_item("spend", "alert", "₹760 of ₹750 today: cap reached")
    assert near.title == "Spend is near the daily cap" and cap.title == "Spend reached the daily cap"
    both = emails.render_alerts([near, item], admin=True, run_url="https://github.com/x/y/actions/runs/1")
    text = visible_text(both.html)
    assert "2 things need attention" in text and text.index("night run") < text.index("near the daily cap")
    assert "See the run log" in text and "https://github.com/x/y/actions/runs/1" in both.text
    with pytest.raises(ValueError):
        emails.render_alerts([], admin=True)


def test_dev_runs_are_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RESEND_API_KEY="re_test_not_real")
    monkeypatch.setattr(notify, "recipients", lambda kind: [notify.Recipient("a@example.com", admin=True)])
    with respx.mock() as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        assert emails.deliver("morning", lambda admin: emails.sample("morning", admin=admin)) == 1
    assert json.loads(route.calls.last.request.content)["subject"].startswith("[dev] ")


def test_admins_and_the_team_get_their_own_version(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RESEND_API_KEY="re_test_not_real", APP_ENV="prod")
    team = [
        notify.Recipient("boss@example.com", admin=True),
        notify.Recipient("caller@example.com"),
        notify.Recipient("viewer@example.com"),
    ]
    monkeypatch.setattr(notify, "recipients", lambda kind: team)
    builds: list[bool] = []

    def build(admin: bool) -> notify.Email:
        builds.append(admin)
        return emails.sample("morning", admin=admin)

    with respx.mock() as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        assert emails.deliver("morning", build) == 3
    payloads = [json.loads(c.request.content) for c in route.calls]
    assert [p["to"] for p in payloads] == [["boss@example.com"], ["caller@example.com"], ["viewer@example.com"]]
    assert "₹412" in payloads[0]["html"] and "₹412" not in payloads[1]["html"]
    assert builds == [True, False]  # rendered once per audience
    assert not payloads[0]["subject"].startswith("[dev]")


def test_no_key_means_no_recipient_lookup_and_no_send(monkeypatch: pytest.MonkeyPatch) -> None:
    looked: list[str] = []
    monkeypatch.setattr(notify, "recipients", lambda kind: looked.append(kind) or [])
    assert emails.deliver("weekly", lambda admin: emails.sample("weekly", admin=admin)) == 0
    assert looked == []


def test_previews_are_written(tmp_path: Path) -> None:
    written = emails.write_previews(tmp_path / "out")
    names = {p.name for p in written}
    assert {"morning.html", "morning-team.txt", "alert.html", "weekly.html", "morning-empty.html"} <= names


# ---------------------------------------------------------------------------
# Morning list from the database, and the morning phase
# ---------------------------------------------------------------------------

TAG = uuid.uuid4().hex[:8]


@pytest.fixture
def morning_world(engine_db: str) -> Iterator[dict[str, str]]:
    """Four leads: an A and a B created today, a C today and an A from two days ago."""
    now = datetime.now(UTC)
    ids: dict[str, str] = {}
    with psycopg.connect(engine_db, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("delete from public.notify_recipients")
        for key, grade, total, created, extra in (
            ("best", "A", 81, now, {"review_count": 1234, "rating": 4.6, "staff_count": 7, "locality": "Baner"}),
            ("good", "B", 61, now, {}),
            ("weak", "C", 45, now, {}),
            ("old", "A", 90, now - timedelta(days=2), {}),
        ):
            cols = {"segment_id": "clinics-in", "name": f"Mail {key} {TAG}", "norm_name": f"mail {key} {TAG}",
                    "country": "in", "city": "Pune", "web_domain": f"mail-{key}-{TAG}.example.com",
                    "subcategory": "dermatology", **extra}  # fmt: skip
            biz = conn.execute(
                f"insert into public.businesses ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
                "returning id",
                list(cols.values()),
            ).fetchone()
            assert biz is not None
            score = conn.execute(
                "insert into public.scores (business_id, version, fit, total, grade, pitch_mode, judge_note) "
                "values (%s, 'v1', 3, %s, %s, 'visible_pain', 'Busy clinic with no booking.') returning id",
                [biz["id"], total, grade],
            ).fetchone()
            assert score is not None
            conn.execute(
                "insert into public.contacts (business_id, phone_e164, phone_type, source) "
                "values (%s, '+919800000077', 'mobile', 'website')",
                [biz["id"]],
            )
            lead = conn.execute(
                "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, message, created_at) "
                "values (%s, 'clinics-in', %s, %s, 'visible_pain', 'Hi there', %s) returning id",
                [biz["id"], score["id"], grade, created],
            ).fetchone()
            assert lead is not None
            ids[key] = str(lead["id"])
            ids[f"{key}_biz"] = str(biz["id"])
        conn.execute(
            "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, "
            "quote, details, dedupe_key) values (%s, 'hiring_frontdesk', 'visible_pain', 8, now() - interval '3 days', "
            "now() + interval '27 days', 'apna', 'Receptionist needed for busy clinic', %s, %s)",
            [ids["best_biz"], json.dumps({}), f"mail:{TAG}"],
        )
        yield ids
        conn.execute("delete from public.notify_recipients")
        conn.execute(
            "delete from public.leads where id = any(%s::uuid[])", [[ids[k] for k in ("best", "good", "weak", "old")]]
        )
        conn.execute(
            "delete from public.businesses where id = any(%s::uuid[])",
            [[ids[k] for k in ("best_biz", "good_biz", "weak_biz", "old_biz")]],
        )
    db.set_setting(emails.MORNING_SENT_KEY, {})


def ours(m: emails.Morning) -> list[emails.LeadCard]:
    return [lead for lead in m.leads if TAG in lead.name]


def test_load_morning_reads_todays_a_and_b_leads(morning_world: dict[str, str]) -> None:
    m = emails.load_morning()
    cards = ours(m)
    assert [c.id for c in cards] == [morning_world["best"], morning_world["good"]]  # best first, today only, A and B
    best = cards[0]
    assert best.grade == "A" and best.score == 81 and best.place == "Baner, Pune · Dermatology"
    assert best.why == 'Hiring front desk staff, seen 3 days ago: "Receptionist needed for busy clinic"'
    assert best.facts == "1,234 Google reviews, rated 4.6 · 7 doctors"
    assert best.url.endswith(f"/leads/{morning_world['best']}") and best.wa.startswith("https://wa.me/919800000077?")
    assert cards[1].why == "Busy clinic with no booking."  # no signal: the judge's note
    assert m.cap_inr > 0
    assert_well_formed(emails.render_morning(m, admin=True))


def test_morning_phase_sends_once_a_day(
    engine_db: str, morning_world: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    rc = RunContext(run_id=str(uuid.uuid4()), kind="morning", opts=Options(), started_at=datetime.now(UTC))
    assert emails.morning(rc)["skipped"] == "RESEND_API_KEY is not set"
    configure(monkeypatch, RESEND_API_KEY="re_test_not_real")
    db.set_setting(emails.MORNING_SENT_KEY, {})
    with psycopg.connect(engine_db, autocommit=True) as conn:
        conn.execute(
            "insert into public.notify_recipients (email, morning) values ('team@example.com', true), "
            "('quiet@example.com', false)"
        )
    with respx.mock() as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        first = emails.morning(rc)
        again = emails.morning(rc)
    assert first["sent"] == 1 and again["skipped"] == "already sent today"
    payloads = [json.loads(c.request.content) for c in route.calls]
    assert [p["to"] for p in payloads] == [["team@example.com"]]
    assert f"Mail best {TAG}" in payloads[0]["html"]
    dry = RunContext(run_id=str(uuid.uuid4()), kind="morning", opts=Options(dry_run=True), started_at=rc.started_at)
    assert emails.morning(dry)["skipped"] == "dry run"


# ---------------------------------------------------------------------------
# Alerts from health checks
# ---------------------------------------------------------------------------


def test_spend_near_the_cap_is_worth_an_email() -> None:
    checks = [
        health.Check("spend", "warn", "₹650 of ₹750"),
        health.Check("source.apna", "warn", "blocked"),
        health.Check("run.night", "alert", "failed"),
        health.Check("database", "ok", "fine"),
    ]
    assert [c.name for c in health.alert_checks(checks)] == ["spend", "run.night"]


def test_alerts_are_emailed_once_a_day(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    db.set_setting(health.ALERTS_KEY, {})
    checks = [health.Check("run.night", "alert", "failed"), health.Check("spend", "ok", "fine")]
    monkeypatch.setattr(health, "collect", lambda *a, **k: checks)
    quiet = health.notify_alerts()
    assert quiet["new"] == ["run.night: failed"] and quiet["emailed"] is False  # email not configured
    sent: list[list[str]] = []
    configure(monkeypatch, RESEND_API_KEY="re_test_not_real")
    monkeypatch.setattr(emails, "send_alerts", lambda items: sent.append([i.title for i in items]) or 1)
    assert health.notify_alerts()["emailed"] is True and sent == [["The night run failed"]]
    assert health.notify_alerts()["new"] == [] and len(sent) == 1  # same alert, same day: not sent again
    checks.append(health.Check("spend", "warn", "₹650 of ₹750 today"))
    assert health.notify_alerts()["new"] == ["spend: ₹650 of ₹750 today"] and sent[-1] == [
        "Spend is near the daily cap"
    ]
    db.set_setting(health.ALERTS_KEY, {})


def test_render_is_strict() -> None:
    with pytest.raises(Exception, match="undefined"):
        emails.render("morning.html", subject="x")


def test_inline_markup_is_escaped() -> None:
    assert str(emails.inline("a <b> `c` **d**")).startswith("a &lt;b&gt; <span")
    assert "<strong>d</strong>" in str(emails.inline("**d**"))


def test_key_facts_and_place_handle_missing_values() -> None:
    row: dict[str, Any] = {
        "segment_id": "education-in",
        "staff_count": 12,
        "branches_count": 1,
        "booking": {"value": "Call only"},
    }
    assert emails.key_facts(row) == "12 staff · booking: call only"
    assert emails.key_facts({}) == "" and emails.place_of({}) == ""
    assert emails.place_of({"city": "Dubai", "subcategory": "ivf_fertility"}) == "Dubai · IVF"
    assert (
        emails.why_now({"reasons": {"intent": ["Asked for a booking app"]}}, datetime.now(UTC))
        == "Asked for a booking app."
    )
