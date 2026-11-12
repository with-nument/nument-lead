"""Step 11 scoring: the four worked examples, decay, stacking, pitch mode, angle, reach (no database)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from nument_engine.pipeline.score import (
    ScoringConfig,
    decay,
    intent_score,
    pick_angle,
    pitch_mode_of,
    reach_of,
    round_half_up,
    rule_note,
    score_business,
)
from nument_engine.pipeline.verify import Exclusions
from nument_engine.segments import load_segments

from .pipeline_fakes import NOW

SEGMENTS = load_segments()
EXCL = Exclusions.load()


def cfg(segment_id: str, weights: dict[str, Any] | None = None) -> ScoringConfig:
    return ScoringConfig.for_segment(SEGMENTS[segment_id], weights or {})


def sig(sid: str, kind: str, points: float, age_days: float, window_days: float, **details: Any) -> dict[str, Any]:
    from nument_engine.models import SIGNAL_CATEGORY

    observed = NOW - timedelta(days=age_days)
    return {
        "id": sid,
        "type": kind,
        "category": SIGNAL_CATEGORY[kind],
        "points": points,
        "observed_at": observed,
        "expires_at": observed + timedelta(days=window_days),
        "details": details,
        "source": "apna",
    }


def fact(fid: str, field: str, value: Any, url: str = "https://example.in/") -> dict[str, Any]:
    return {"id": fid, "field": field, "value": value, "quote": "q", "url": url, "model": "m"}


def mobile(dm: bool = False, source: str = "website") -> dict[str, Any]:
    return {
        "id": "c1",
        "phone_e164": "+919876543210",
        "phone_type": "mobile",
        "source": source,
        "verified": True,
        "do_not_contact": False,
        "is_decision_maker": dm,
        "verified_at": NOW,
        "name": "Owner" if dm else None,
    }


LANDLINE = {
    "id": "c2",
    "phone_e164": "+918041234567",
    "phone_type": "landline",
    "source": "website",
    "verified": True,
    "do_not_contact": False,
    "is_decision_maker": False,
    "verified_at": NOW,
}
LIVE = fact("w", "website_status", {"status": "live"})


# ---------------------------------------------------------------------------
# 11.7 worked examples
# ---------------------------------------------------------------------------


def test_example_1_ivf_clinic_pune_is_b() -> None:
    b = {
        "id": "b1",
        "name": "Pune Fertility Centre",
        "category": "fertility_clinic",
        "subcategory": "ivf_fertility",
        "review_count": 420,
        "branches_count": 2,
        "staff_count": 5,
        "web_domain": "punefertility.in",
    }
    facts = [
        fact("f1", "price_point", {"item": "IVF package", "amount": 160000, "currency": "INR"}),
        fact("f2", "booking_method", {"value": "Practo"}, "https://www.practo.com/pune/clinic/pune-fertility"),
        {
            **fact("f3", "sales_note", {"value": "Profile is claimed"}, "https://www.practo.com/pune/clinic/x"),
            "quote": "Profile is claimed",
        },
        LIVE,
    ]
    signals = [sig("s1", "hiring_frontdesk", 8, 5, 30), sig("s2", "review_pain", 6, 40, 90)]
    r = score_business(b, facts, signals, [mobile()], SEGMENTS["clinics-in"], cfg("clinics-in"), EXCL, NOW)
    assert (r.fit, r.can_pay, r.intent, r.reach) == (3, 30, 14.2, 0.85)
    assert (r.total, r.grade) == (58, "B")
    assert (r.pitch_mode, r.angle, r.test_group) == (
        "visible_pain",
        "frontdesk_load",
        "clinics-in:visible_pain:frontdesk_load",
    )


def test_example_2_developer_with_a_public_ask_is_a() -> None:
    b = {
        "id": "b2",
        "name": "Skyline Developers",
        "category": "real_estate_developer",
        "subcategory": "developer",
        "review_count": 90,
        "branches_count": 4,
        "staff_count": 12,
        "web_domain": "skylinedevelopers.in",
    }
    facts = [
        fact("f1", "price_point", {"item": "3 BHK apartments", "amount": 12000000, "currency": "INR"}),
        fact("f2", "tech_stack", [{"tool": "Sell.do", "kind": "CRM", "page_url": "x"}]),
        LIVE,
    ]
    signals = [
        sig("s1", "public_ask", 10, 3, 14),
        sig("s2", "hiring_frontdesk", 8, 12, 30),
        sig("s3", "ads_running", 4, 2, 30),
    ]
    r = score_business(b, facts, signals, [mobile(dm=True)], SEGMENTS["realestate-in"], cfg("realestate-in"), EXCL, NOW)
    assert (r.fit, r.can_pay, r.intent, r.reach) == (3, 30, 23.6, 1.0)
    assert (r.total, r.grade) == (80, "A")
    assert (r.pitch_mode, r.angle) == ("stated_need", "build_what_they_asked")


def test_example_3_coaching_institute_fit_only_is_d() -> None:
    b = {
        "id": "b3",
        "name": "Bengaluru Achievers Academy",
        "category": "education",
        "subcategory": "coaching_institute",
        "review_count": 150,
        "web_domain": "achievers.in",
    }
    facts = [
        fact("f1", "price_point", {"item": "JEE course fee", "amount": 65000, "currency": "INR"}),
        fact("f2", "in_house_tech", {"value": True}),
    ]
    r = score_business(b, facts, [], [LANDLINE], SEGMENTS["education-in"], cfg("education-in"), EXCL, NOW)
    assert (r.fit, r.can_pay, r.intent, r.reach) == (2, 13, 0, 0.65)
    assert (r.total, r.grade, r.pitch_mode) == (15, "D", "fit_only")


DENTAL_DUBAI = {
    "id": "b4",
    "name": "Smile Studio Dental",
    "category": "dental_clinic",
    "subcategory": "dental",
    "review_count": 610,
    "branches_count": 3,
    "staff_count": 9,
    "web_domain": "smilestudio.ae",
}
DENTAL_FACTS = [
    fact("f1", "price_point", {"item": "Dental implants", "amount": 5000, "currency": "AED"}),
    fact("f2", "tech_stack", {"tools": [{"tool": "Setmore", "kind": "booking"}]}),
    LIVE,
]


@pytest.mark.parametrize(
    ("signals", "intent", "total", "grade"),
    [
        ([], 0, 43, "C"),
        ([sig("s1", "review_pain", 6, 5, 90)], 6, 49, "C"),
        ([sig("s1", "review_pain", 6, 5, 90), sig("s2", "hiring_frontdesk", 8, 2, 30)], 16, 60, "B"),
    ],
)
def test_example_4_dubai_dental_chain_needs_a_reason_to_buy(
    signals: list[dict[str, Any]], intent: float, total: int, grade: str
) -> None:
    r = score_business(
        DENTAL_DUBAI, DENTAL_FACTS, signals, [mobile()], SEGMENTS["clinics-ae"], cfg("clinics-ae"), EXCL, NOW
    )
    assert (r.fit, r.can_pay, r.intent, r.reach) == (3, 30, intent, 0.85)
    assert (r.total, r.grade) == (total, grade)


def test_round_half_up_matches_the_plan() -> None:
    assert [round_half_up(x) for x in (42.5, 57.5875, 79.5, 14.625, 59.5, 0.4)] == [43, 58, 80, 15, 60, 0]


# ---------------------------------------------------------------------------
# 11.4 decay and stacking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("share", "expected"), [(0.29, 1.0), (0.31, 0.7), (0.59, 0.7), (0.61, 0.4), (0.99, 0.4), (1.01, 0.0)]
)
def test_decay_steps(share: float, expected: float) -> None:
    observed = NOW - timedelta(days=100 * share)
    assert decay(observed, observed + timedelta(days=100), NOW) == expected


def test_decay_handles_bad_windows() -> None:
    assert decay(NOW, NOW, NOW) == 0.0


def test_stacking_bonus() -> None:
    c = cfg("clinics-in")
    one, _ = intent_score([sig("a", "hiring_frontdesk", 8, 1, 30), sig("b", "hiring_frontdesk", 8, 2, 30)], NOW, c)
    two, _ = intent_score([sig("a", "hiring_frontdesk", 8, 1, 30), sig("b", "review_pain", 6, 1, 90)], NOW, c)
    three, _ = intent_score(
        [sig("a", "hiring_frontdesk", 8, 1, 30), sig("b", "review_pain", 6, 1, 90), sig("c", "slow_site", 2, 1, 60)],
        NOW,
        c,
    )
    four, _ = intent_score(
        [
            sig("a", "hiring_frontdesk", 8, 1, 30),
            sig("b", "review_pain", 6, 1, 90),
            sig("c", "slow_site", 2, 1, 60),
            sig("d", "news", 3, 1, 30),
        ],
        NOW,
        c,
    )
    assert (one, two, three, four) == (8, 16, 20, 23)


def test_same_event_counts_once() -> None:
    signals = [
        sig("a", "news", 3, 1, 30, event_key="branch:baner"),
        sig("b", "new_branch", 5, 1, 60, event_key="branch:baner"),
    ]
    value, kept = intent_score(signals, NOW, cfg("clinics-in"))
    assert value == 5 and [s["id"] for s in kept] == ["b"]


def test_intent_is_capped_at_40() -> None:
    signals = [
        sig(str(i), t, 10, 1, 30)
        for i, t in enumerate(["public_ask", "tender", "hiring_builder", "hiring_frontdesk", "review_pain"])
    ]
    assert intent_score(signals, NOW, cfg("clinics-in"))[0] == 40


def test_learned_signal_points_win() -> None:
    c = cfg("clinics-in", {"signal_points": {"clinics-in": {"hiring_frontdesk": 9.5}}})
    value, _ = intent_score([sig("a", "hiring_frontdesk", 8, 1, 30)], NOW, c, SEGMENTS["clinics-in"])
    assert value == 9.5


def test_learned_can_pay_points_and_fit_only_share() -> None:
    c = cfg(
        "clinics-in",
        {"can_pay_points": {"clinics-in": {"branches_2plus": 7, "pays_for_software": 4}}, "fit_only_share": 0.05},
    )
    assert [t.points for t in c.branches] == [8, 7] and c.pays_for_software == 4 and c.fit_only_max_pct == 5


# ---------------------------------------------------------------------------
# 11.5 reach, 11.8 pitch mode and angle
# ---------------------------------------------------------------------------


def test_reach_ladder() -> None:
    c = cfg("clinics-in")
    email = {"id": "c3", "email": "hi@x.in", "source": "website", "verified": True, "do_not_contact": False}
    form = [fact("f9", "contact_form_url", {"url": "https://x.in/contact"})]
    assert reach_of([mobile(dm=True)], [], c, NOW).value == 1.0
    assert reach_of([mobile(dm=True, source="google_listing")], [], c, NOW).value == 0.85
    assert reach_of([LANDLINE], [], c, NOW).value == 0.65
    assert reach_of([email], [], c, NOW).value == 0.45
    assert reach_of([], form, c, NOW).value == 0.30
    assert reach_of([{**mobile(), "do_not_contact": True}], [], c, NOW).value == 0.0
    old_listing = {**mobile(source="google_listing"), "verified_at": NOW - timedelta(days=31)}
    assert reach_of([old_listing], [], c, NOW).kind == "none"


def test_pitch_mode_order() -> None:
    assert pitch_mode_of([sig("a", "review_pain", 6, 1, 90), sig("b", "public_ask", 10, 1, 14)]) == "stated_need"
    assert pitch_mode_of([sig("a", "news", 3, 1, 30), sig("b", "slow_site", 2, 1, 60)]) == "visible_pain"
    assert pitch_mode_of([sig("a", "news", 3, 1, 30)]) == "fit_only"


def test_angles() -> None:
    seg = SEGMENTS["clinics-in"]
    ads = [sig("a", "no_booking", 4, 1, 60), sig("b", "ads_running", 4, 5, 30)]
    assert pick_angle("visible_pain", ads, seg) == "ad_leads_cold"
    assert pick_angle("visible_pain", [sig("a", "review_pain", 6, 1, 90)], seg) == "missed_calls"
    growth_first = [sig("a", "new_branch", 5, 1, 60), sig("b", "slow_site", 2, 1, 60)]
    assert pick_angle("visible_pain", growth_first, seg) == "new_branch_setup"
    assert pick_angle("fit_only", [], seg) == "after_hours_enquiries"
    assert pick_angle("stated_need", [sig("a", "hiring_builder", 8, 1, 30)], seg) == "build_what_they_asked"


def test_fit_gate_failure_is_grade_d_whatever_the_total() -> None:
    b = {"id": "b9", "name": "Generic Trading Co", "category": "shop", "review_count": 5, "web_domain": "x.in"}
    signals = [sig("a", "public_ask", 10, 1, 14), sig("b", "hiring_frontdesk", 8, 1, 30)]
    r = score_business(b, [], signals, [mobile(dm=True)], SEGMENTS["clinics-in"], cfg("clinics-in"), EXCL, NOW)
    assert r.fit < 2 and r.grade == "D" and r.reasons["fit_gate_failed"] is True


def test_reasons_and_rule_note_are_readable_and_dash_free() -> None:
    b = {
        "id": "b1",
        "name": "Pune Fertility Centre",
        "category": "fertility_clinic",
        "subcategory": "ivf_fertility",
        "review_count": 420,
        "branches_count": 2,
        "web_domain": "punefertility.in",
    }
    r = score_business(
        b,
        [LIVE],
        [sig("s1", "hiring_frontdesk", 8, 5, 30, role="front desk executives")],
        [mobile()],
        SEGMENTS["clinics-in"],
        cfg("clinics-in"),
        EXCL,
        NOW,
    )
    assert r.note == "Hiring front desk executives on Apna 5 days ago, and 420 Google reviews and 2 branches."
    assert "\u2013" not in r.note and "\u2014" not in r.note and len(r.note) <= 280
    assert r.reasons["intent"] == [{"signal_id": "s1", "type": "hiring_frontdesk", "value": 8.0}]
    assert any("ticket class ivf_fertility" in why for why in r.reasons["can_pay"])
    fit_only = score_business(b, [LIVE], [], [mobile()], SEGMENTS["clinics-in"], cfg("clinics-in"), EXCL, NOW)
    assert rule_note(fit_only, b, [LIVE], NOW).startswith("No buying signal yet, but a strong fit: 420 Google reviews")
