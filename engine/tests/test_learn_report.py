"""The weekly report (Step 16.6): the week it covers, its sections, the caller view without money, storage."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from nument_engine import db
from nument_engine.learn import report

from . import seed
from .helpers import Conn

DASHES = (chr(0x2013), chr(0x2014))
WEEK = report.week_of(date(2026, 12, 7))  # Monday 7 to Sunday 13 Dec 2026


# ---------------------------------------------------------------------------
# Periods and formatting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("today", [date(2026, 12, 14), date(2026, 12, 16), date(2026, 12, 20)])
def test_report_week_is_the_last_full_monday_to_sunday(today: date) -> None:
    p = report.report_week(today)
    assert (p.start, p.end) == (date(2026, 12, 7), date(2026, 12, 13))
    assert p.start_at == datetime(2026, 12, 6, 18, 30, tzinfo=UTC)  # midnight IST
    assert p.end_at - p.start_at == timedelta(days=7)
    with pytest.raises(ValueError, match="not a Monday"):
        report.week_of(date(2026, 12, 8))


def test_feedback_reasons_are_parsed_from_lists_or_text() -> None:
    assert report.parse_reasons('["too_small", "agency_or_vendor"]') == ["agency_or_vendor", "too_small"]
    assert report.parse_reasons("bad_message, cannot_reach") == ["bad_message", "cannot_reach"]
    assert report.parse_reasons("they were rude") == ["other"]
    assert report.parse_reasons(None) == []


def test_exclusion_suggestions_need_three_thumbs_and_skip_known_names() -> None:
    rows = [{"reason": "agency_or_vendor", "web_domain": "growfast.in", "norm_name": "growfast digital"}] * 3
    rows += [
        {"reason": "too_big_or_corporate", "web_domain": "apollohospitals.com", "norm_name": "apollo hospitals"}
    ] * 4
    rows += [{"reason": "too_small", "web_domain": "tiny.in", "norm_name": "tiny clinic"}] * 5
    found = report.exclusion_suggestions(rows)
    assert {"kind": "domain", "value": "growfast.in", "count": 3} in found
    assert {"kind": "name", "value": "growfast digital", "count": 3} in found
    assert not any("apollo" in s["value"] for s in found)  # already in exclusions.yaml
    assert not any("tiny" in s["value"] for s in found)  # wrong reason


def test_suggested_actions_are_capped_and_ordered() -> None:
    tg = {
        "label": "scale",
        "key": "clinics-ae:visible_pain:missed_calls",
        "meeting_rate": 0.11,
        "meeting": {"trials": 64},
    }
    content = {
        "cuts": {
            "test_group": [tg, {**tg, "key": "x:y:z", "label": "cut", "meeting_rate": 0.01, "meeting": {"trials": 120}}]
        },
        "quality": {"wrong_contact": {"rate": 0.09, "tried": 40}, "exclusion_suggestions": [{"value": "a"}]},
        "health": {
            "failed": [{"kind": "night"}],
            "sources": [{"source": "apna", "health": "blocked", "blocked_until": "2026-12-20T00:00:00+00:00"}],
        },
        "cost": {"avg_per_day_inr": 700, "daily_cap_inr": 750},
        "eval_audit": {"eval": None, "audit": None},
    }
    actions = report.suggested_actions(content)
    assert len(actions) == 5
    assert actions[0].startswith("Raise the daily quota for clinics-ae") and "11%" in actions[0]
    assert actions[1].startswith("Consider pausing `x:y:z`")
    quiet = {
        **content,
        "cuts": {"test_group": []},
        "quality": {"wrong_contact": {"rate": None, "tried": 0}, "exclusion_suggestions": []},
        "health": {"failed": [], "sources": []},
        "cost": None,
        "eval_audit": {"eval": {"summary": {"passed": True}}, "audit": None},
    }
    assert report.suggested_actions(quiet) == ["Nothing needs action this week."]


# ---------------------------------------------------------------------------
# Building from the database
# ---------------------------------------------------------------------------


def _seed_week(conn: Conn) -> dict[str, str]:
    at = WEEK.start_at
    ids = {
        "replied": seed.contacted(
            conn, 3, reached=[("talking", 1)], as_of=at + timedelta(days=6), signals=["review_pain"]
        ),
        "won": seed.contacted(
            conn,
            100,
            reached=[("talking", 2), ("discovery_booked", 10), ("proposal_sent", 30), ("won", 97)],
            as_of=at + timedelta(days=4),
            deal_value_inr=150000,
        ),
    }
    ids["new"], _ = seed.lead(conn, created=at + timedelta(days=2), grade="A")
    conn.execute(
        "insert into public.costs (provider, model, task, calls, usd, inr, at) values "
        "('gemini', 'gemini-3-flash', 'extract_facts', 40, 1.2, 105.6, %s), ('gemini', 'gemini-3.1-pro', 'judge_lead', 8, 0.4, 35.2, %s)",
        [at + timedelta(days=1), at + timedelta(days=2)],
    )
    conn.execute(
        "insert into public.runs (kind, started_at, finished_at, status, error) values "
        "('night', %s, %s, 'ok', null), ('morning', %s, %s, 'failed', 'Traceback\nValueError: boom')",
        [at + timedelta(hours=2), at + timedelta(hours=3), at + timedelta(days=1), at + timedelta(days=1, hours=1)],
    )
    conn.execute("update public.source_health set blocked_until = now() + interval '3 days' where source = 'apna'")
    conn.execute(
        "insert into public.feedback (lead_id, rating, reason, at) values (%s, -1, %s, %s), (%s, 1, 'great_lead', %s)",
        [
            ids["new"],
            json.dumps(["bad_message", "too_small"]),
            at + timedelta(days=3),
            ids["replied"],
            at + timedelta(days=3),
        ],
    )
    return ids


def test_build_weekly_sections_and_numbers(db_conn: Conn) -> None:
    _seed_week(db_conn)
    content, admin_md, caller_md = report.build_weekly(WEEK, conn=db_conn)
    h = content["headline"]
    assert (h["leads_added"], h["contacted"], h["replied"], h["won"]) == (2, 1, 1, 1)  # replied lead was new this week
    assert h["money_won_inr"] == 150000
    assert content["period"]["label"] == "7 to 13 Dec 2026"
    assert {r["key"] for r in content["cuts"]["segment_id"]} == {"clinics-in"}
    assert content["cost"]["inr"] == pytest.approx(140.8) and content["cost"]["by_task"][0]["task"] == "extract_facts"
    assert any("Failed: morning" in line and "ValueError: boom" in line for line in content["health"]["lines"])
    assert any(line.startswith("Blocked: apna") for line in content["health"]["lines"])
    assert content["quality"]["thumbs"] == {
        "up": 1,
        "down": 1,
        "top_down_reasons": {"clinics-in": {"bad_message": 1, "too_small": 1}},
    }
    assert content["quality"]["bad_messages"] and 1 <= len(content["actions"]) <= 5

    for heading in (
        "# Weekly report: 7 to 13 Dec 2026",
        "## 1. Funnel by segment and country",
        "## 2. By signal type and source",
        "## 4. Test groups to scale or cut",
        "## 5. Lost and not now",
        "## 6. Lead quality",
        "## 7. Cost",
        "## 8. Engine health",
        "## 9. What the engine changed",
        "## 10. Last eval and audit",
        "## 11. Suggested actions",
    ):
        assert heading in admin_md, heading
    assert "**Money won** ₹1,50,000" in admin_md and "New retainers" not in admin_md  # none this week
    assert "| Source |" in admin_md and {r["key"] for r in content["cuts"]["source"]} == {"fit_only"}
    assert "- No leads closed as lost or not now this week." in admin_md
    assert not any(d in admin_md + caller_md for d in DASHES)


def test_caller_view_has_no_money(db_conn: Conn) -> None:
    _seed_week(db_conn)
    content, _, caller_md = report.build_weekly(WEEK, conn=db_conn)
    caller = content["caller"]
    assert "cost" not in caller and "money_won_inr" not in caller["headline"]
    assert "Money won" not in caller_md and ". Cost" not in caller_md and "₹" not in caller_md
    assert "## 7. Engine health" in caller_md and content["caller_markdown"] == caller_md


def test_save_stores_a_weekly_row(db_conn: Conn) -> None:
    content, admin_md, _ = report.build_weekly(WEEK, conn=db_conn)
    report_id = report.save(WEEK, content, admin_md, conn=db_conn)
    row = db.fetch_one(
        "select kind, period_start, period_end, markdown from public.reports where id = %s", [report_id], conn=db_conn
    )
    assert row is not None and row["kind"] == "weekly" and row["period_start"] == WEEK.start
    assert row["markdown"].startswith("# Weekly report")


def test_changes_section_reports_rejected_proposals(db_conn: Conn) -> None:
    reweight = {
        "status": "rejected_by_eval",
        "gate": {"detail": "precision at 50: 62%"},
        "changes": [],
        "model_cards": [],
    }
    _, admin_md, _ = report.build_weekly(WEEK, reweight=reweight, conn=db_conn)
    assert "Weights proposal rejected by eval: precision at 50: 62%" in admin_md


def test_lost_reasons_and_new_retainers(db_conn: Conn) -> None:
    at = WEEK.start_at
    week_end = at + timedelta(days=5)
    price = seed.contacted(db_conn, 4, reached=[("talking", 1), ("lost", 3)], as_of=week_end)
    no_reply = seed.contacted(db_conn, 4, reached=[("lost", 2)], as_of=week_end)
    seed.contacted(db_conn, 4, reached=[("not_now", 2)], as_of=week_end)  # no reason recorded
    seed.contacted(db_conn, 60, reached=[("lost", 10)], as_of=week_end)  # closed weeks ago, no reason
    reopened = seed.contacted(db_conn, 4, reached=[("lost", 1), ("talking", 2)], as_of=week_end)
    for lead_id, reason in ((price, "price"), (no_reply, "no_reply"), (reopened, "price")):
        db_conn.execute("update public.leads set lost_reason = %s where id = %s", [reason, lead_id])
    rupees = seed.contacted(
        db_conn, 100, reached=[("talking", 2), ("discovery_booked", 10), ("retainer", 97)], as_of=week_end
    )
    dollars = seed.contacted(db_conn, 50, reached=[("talking", 2), ("won", 48)], as_of=week_end)
    upgraded = seed.contacted(db_conn, 90, reached=[("won", 30), ("retainer", 88)], as_of=week_end)
    old = seed.contacted(db_conn, 200, reached=[("retainer", 100)], as_of=week_end)  # signed long ago
    for lead_id, value, currency in (
        (rupees, 40000, "INR"),
        (dollars, 1500, "USD"),
        (upgraded, 25000, "INR"),
        (old, 99999, "INR"),
    ):
        db_conn.execute(
            "update public.leads set retainer_monthly_value = %s, deal_currency = %s where id = %s",
            [value, currency, lead_id],
        )

    content, admin_md, caller_md = report.build_weekly(WEEK, conn=db_conn)
    out = content["outcomes"]
    assert out["week"] == {"lost": {"no_reply": 1, "price": 1}, "not_now": {"not_recorded": 1}}
    assert out["window"]["lost"] == {"no_reply": 1, "price": 1, "not_recorded": 1}
    assert "- This week: lost 2 (no reply 1, price 1); not now 1 (not recorded 1)." in admin_md
    assert "- Last 180 days: lost 3 (no reply 1, price 1, not recorded 1); not now 1 (not recorded 1)." in admin_md
    assert "Closed without a reason: 2." in admin_md and "lost 2 (no reply 1, price 1)" in caller_md

    assert content["headline"]["retainer_monthly"] == {"INR": 65000.0, "USD": 1500.0}
    assert "**New retainers** ₹65,000 + USD 1,500 a month" in admin_md
    caller = content["caller"]
    assert "retainer_monthly" not in caller["headline"] and "New retainers" not in caller_md
    assert "headline.retainer_monthly" in content["admin_only"]
