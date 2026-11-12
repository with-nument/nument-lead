"""Funnel metrics (Step 16.1 and 16.2): stage ranks, windows, maturity, rates, intervals and decision labels."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nument_engine.learn import metrics as m
from nument_engine.learn.metrics import FunnelRow, Rate

from . import seed
from .helpers import Conn

AS_OF = datetime(2026, 12, 14, tzinfo=UTC)


def row(days_ago: int | None, reached: dict[int, int] | None = None, **kw: object) -> FunnelRow:
    """A contacted lead `days_ago` days before AS_OF reaching rank k after reached[k] days."""
    contacted_at = None if days_ago is None else AS_OF - timedelta(days=days_ago)
    reached = reached or {}
    max_rank = max([1, *reached]) if contacted_at else 0
    defaults: dict[str, object] = {
        "lead_id": f"lead-{id(reached)}-{days_ago}",
        "segment_id": "clinics-in",
        "country": "in",
        "pitch_mode": "visible_pain",
        "angle": "frontdesk_load",
        "test_group": "clinics-in:visible_pain:frontdesk_load",
        "grade": "A",
        "stage": "contacted",
        "max_rank": max_rank,
        "is_wrong_contact": False,
        "contacted_at": contacted_at,
        "attempted_at": contacted_at or AS_OF,
        "reached_at": {k: contacted_at + timedelta(days=d) for k, d in reached.items()} if contacted_at else {},
    }
    defaults.update(kw)
    return FunnelRow(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Events, windows and maturity
# ---------------------------------------------------------------------------


def test_highest_rank_counts_even_after_closing() -> None:
    r = row(60, {2: 3}, stage="lost")
    assert r.had("contacted") and r.had("replied")
    assert not r.had("meeting")


def test_events_count_only_inside_their_windows() -> None:
    late_reply = row(100, {2: 22})
    assert not late_reply.had("replied")
    on_time = row(100, {2: 21, 3: 45, 4: 60, 5: 120})
    assert all(on_time.had(e) for e in ("replied", "meeting", "proposal", "won"))
    late = row(200, {2: 1, 3: 46, 4: 61, 5: 121})
    assert late.had("replied") and not late.had("meeting") and not late.had("proposal") and not late.had("won")


def test_wrong_contact_never_counts_as_contacted() -> None:
    r = row(10, {2: 1}, is_wrong_contact=True, stage="wrong_contact")
    assert not r.contacted and not r.had("contacted") and not r.had("replied")


def test_maturity_follows_each_window() -> None:
    r = row(30)
    assert r.mature("replied", AS_OF) and not r.mature("meeting", AS_OF)
    assert row(45).mature("meeting", AS_OF) and not row(59).mature("proposal", AS_OF)


def test_signal_type_cut_counts_a_lead_in_every_row() -> None:
    r = row(50, signal_types=("hiring_frontdesk", "review_pain"))
    assert r.key("signal_type") == ["hiring_frontdesk", "review_pain"]
    assert row(50).key("signal_type") == ["none"] and row(50, angle=None).key("angle") == ["none"]


# ---------------------------------------------------------------------------
# Rates and intervals
# ---------------------------------------------------------------------------


def test_rates_use_mature_leads_only_and_report_open_ones() -> None:
    rows = [row(60, {2: 2, 3: 10}), row(60), row(60), row(30, {2: 1}), row(10, {2: 1})]
    (cut,) = m.rates_by_cut(rows, "segment_id", AS_OF)
    assert (cut.contacted, cut.replied, cut.meetings, cut.open_leads) == (5, 3, 1, 2)
    assert (cut.reply.successes, cut.reply.trials) == (2, 4)  # the 10-day lead is still inside 21 days
    assert (cut.meeting.successes, cut.meeting.trials) == (1, 3)
    assert cut.meeting_rate == pytest.approx(1 / 3)
    assert not cut.mature


def test_credible_interval_is_wide_for_small_samples_and_narrow_for_big_ones() -> None:
    low, high = m.credible_interval(1, 10)
    assert 0 < low < 0.1 < high < 0.5
    low2, high2 = m.credible_interval(100, 1000)
    assert high2 - low2 < 0.05 and low2 < 0.1 < high2
    assert Rate(0, 0).value is None and Rate(0, 0).ci90 is None


def test_cut_rows_are_sorted_and_reject_unknown_cuts() -> None:
    rows = [row(60, segment_id="clinics-ae"), row(60), row(60)]
    assert [c.key for c in m.rates_by_cut(rows, "segment_id", AS_OF)] == ["clinics-in", "clinics-ae"]
    with pytest.raises(ValueError, match="unknown cut"):
        m.rates_by_cut(rows, "colour", AS_OF)


# ---------------------------------------------------------------------------
# Decision labels (16.2.4)
# ---------------------------------------------------------------------------


def cut_with(contacted: int, meetings: int, proposals: int, replies: int | None = None) -> m.CutRow:
    replies = meetings if replies is None else replies
    return m.CutRow(
        "test_group",
        "g",
        contacted,
        replies,
        meetings,
        proposals,
        0,
        0,
        0,
        Rate(replies, contacted),
        Rate(meetings, contacted),
        Rate(proposals, contacted),
        Rate(0, contacted),
    )


@pytest.mark.parametrize(
    ("contacted", "meetings", "proposals", "replies", "expected"),
    [
        (64, 7, 4, None, ("scale", None)),  # 11% meetings, 1.25 proposals per 20
        (64, 7, 2, None, ("keep", None)),  # good meetings, too few proposals for scale
        (60, 3, 0, None, ("keep", None)),  # 5%
        (120, 2, 0, None, ("cut", None)),  # under 3% on 100+
        (80, 1, 0, None, ("watch", None)),  # under 3% but fewer than 100
        (40, 0, 0, 5, ("early_signal", "green")),  # replies 12.5% before meetings can be judged
        (40, 0, 0, 1, ("early_signal", "red")),
        (40, 0, 0, 2, ("watch", None)),  # 5%: neither
        (20, 5, 5, 10, ("watch", None)),  # too few for anything
    ],
)
def test_decision_labels(
    contacted: int, meetings: int, proposals: int, replies: int | None, expected: tuple[str, str | None]
) -> None:
    assert m.decision_label(cut_with(contacted, meetings, proposals, replies)) == expected


# ---------------------------------------------------------------------------
# Attribution helpers
# ---------------------------------------------------------------------------


def test_reach_type() -> None:
    assert m.reach_type_of("mobile", True, True, True) == "mobile"
    assert m.reach_type_of("tollfree", True, False, False) == "landline"
    assert m.reach_type_of(None, False, True, True) == "email"
    assert m.reach_type_of(None, False, False, True) == "form"
    assert m.reach_type_of(None, False, False, False) == "none"


def test_signal_types_from_reasons_or_fallback() -> None:
    assert m.signal_types_from({"signals": [{"type": "review_pain"}]}, ["news"]) == ("review_pain",)
    assert m.signal_types_from({"intent": [{"type": "hiring_frontdesk", "value": 8}]}, None) == ("hiring_frontdesk",)
    assert m.signal_types_from({}, ["news", "made_up"]) == ("news",)


def test_can_pay_proxies_from_list_strings_or_columns() -> None:
    tiers = {
        "branches": [(4.0, "branches_4plus"), (2.0, "branches_2plus")],
        "staff": [(8.0, "staff_8plus"), (3.0, "staff_3plus")],
        "reviews": [(300.0, "reviews_300plus"), (100.0, "reviews_100plus")],
    }
    listed = {"can_pay_proxies": ["reviews_100plus"]}
    assert m.can_pay_proxies_from(listed, tiers, branches=9, staff=None, reviews=None) == ("reviews_100plus",)
    strings = {"can_pay": ["branches_count=3 (fact 8f2c)", "review_count=410 (places)", "premium price_point (fact 1)"]}
    assert m.can_pay_proxies_from(strings, tiers, branches=None, staff=None, reviews=None) == (
        "branches_2plus",
        "premium_price",
        "reviews_300plus",
    )
    assert m.can_pay_proxies_from(None, tiers, branches=5, staff=3, reviews=None) == ("branches_4plus", "staff_3plus")


# ---------------------------------------------------------------------------
# Loading from the database
# ---------------------------------------------------------------------------


def test_load_funnel_reads_history_windows_and_attribution(db_conn: Conn) -> None:
    now = seed.NOW
    replied = seed.contacted(
        db_conn, 60, reached=[("talking", 3), ("lost", 9)], signals=["hiring_frontdesk"], proxies=["branches_2plus"]
    )
    met = seed.contacted(
        db_conn,
        50,
        reached=[("talking", 2), ("discovery_booked", 10)],
        segment="clinics-ae",
        phone=("+971501234567", "landline", "google_listing"),
    )
    wrong, _ = seed.lead(
        db_conn, created=now - timedelta(days=20), history=[("wrong_contact", now - timedelta(days=12))]
    )
    never, _ = seed.lead(db_conn, created=now - timedelta(days=20))  # never contacted: not in the funnel
    sent_only, _ = seed.lead(db_conn, created=now - timedelta(days=15), wa_on=(now - timedelta(days=14)).date())

    rows = {r.lead_id: r for r in m.load_funnel(db_conn, as_of=now, since_days=120)}
    assert never not in rows
    a = rows[replied]
    assert a.max_rank == 2 and a.stage == "lost" and a.had("replied") and not a.had("meeting")
    assert a.signal_types == ("hiring_frontdesk",) and a.can_pay_proxies == ("branches_2plus",)
    assert a.reach_type == "mobile" and a.phone_source == "website" and a.writer and a.score_total == 72
    b = rows[met]
    assert b.had("meeting") and b.reach_type == "landline" and b.phone_source == "google_listing"
    w = rows[wrong]
    assert w.is_wrong_contact and not w.contacted and w.attempted_at == now - timedelta(days=12)
    s = rows[sent_only]
    assert s.contacted and s.max_rank == 1 and s.stage == "new"  # wa_at set but stage still new counts (16.1.1)


def test_load_funnel_window_bounds(db_conn: Conn) -> None:
    old = seed.contacted(db_conn, 400)
    recent = seed.contacted(db_conn, 30)
    ids = {r.lead_id for r in m.load_funnel(db_conn, as_of=seed.NOW, since_days=180)}
    assert recent in ids and old not in ids
