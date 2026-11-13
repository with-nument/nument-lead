"""Step 11.11 lead rules, the fit-only cap and the phone freshness check (no database)."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from nument_engine.pipeline.leads import (
    Candidate,
    LeadState,
    ProofChecker,
    decide,
    fit_only_allowed,
    in_cool_down,
    plan_all,
)

from .pipeline_fakes import NOW

BASE = Candidate(
    business_id="b1",
    segment_id="clinics-in",
    score_id="s1",
    grade="B",
    total=60,
    pitch_mode="visible_pain",
    angle="missed_calls",
    test_group="clinics-in:visible_pain:missed_calls",
    reach_kind="business_mobile",
    best_contact={"id": "c1", "phone_e164": "+919876543210", "source": "website", "verified_at": NOW},
    region="in",
    evidence_ids=frozenset({"f1", "s9"}),
)


def lead(stage: str = "new", **over: Any) -> dict[str, Any]:
    return {"id": "L1", "stage": stage, "grade": "B", "angle": "missed_calls", "message": "Hi, ...", **over}


@pytest.mark.parametrize(
    ("state", "grade", "action"),
    [
        (LeadState(), "A", "create"),
        (LeadState(), "C", "keep"),
        (LeadState(open_lead=lead()), "A", "update"),
        (LeadState(open_lead=lead("contacted")), "A", "keep"),
        (LeadState(open_lead=lead("talking")), "D", "keep"),
        (LeadState(open_lead=lead()), "C", "lower"),
        (LeadState(open_lead=lead()), "D", "lower"),
        (LeadState(open_lead=lead(grade="D")), "D", "not_a_fit"),
        (LeadState(is_client=True), "A", "keep"),
    ],
)
def test_decide_table(state: LeadState, grade: str, action: str) -> None:
    assert decide(replace(BASE, grade=grade), state, NOW).action == action


@pytest.mark.parametrize(
    ("stage", "days_ago", "blocked"),
    [
        ("not_now", 10, True),
        ("not_now", 31, False),
        ("lost", 89, True),
        ("lost", 91, False),
        ("not_a_fit", 179, True),
        ("not_a_fit", 181, False),
    ],
)
def test_cool_downs(stage: str, days_ago: int, blocked: bool) -> None:
    state = LeadState(last_closed={"stage": stage, "last_activity_at": NOW - timedelta(days=days_ago)})
    assert (in_cool_down(state, NOW) is not None) is blocked
    assert decide(BASE, state, NOW).action == ("keep" if blocked else "create")


def test_wrong_contact_waits_for_a_new_verified_contact() -> None:
    closed = {"stage": "wrong_contact", "last_activity_at": NOW - timedelta(days=200)}
    assert in_cool_down(LeadState(last_closed=closed), NOW) == "wrong_contact_until_new_contact"
    fresh = LeadState(last_closed=closed, newest_contact_at=NOW - timedelta(days=1))
    assert in_cool_down(fresh, NOW) is None


def test_message_is_cleared_when_angle_or_cited_facts_change_but_never_after_a_person_edit() -> None:
    same = decide(BASE, LeadState(open_lead=lead(), cited_ids=frozenset({"f1"})), NOW)
    assert not same.clear_message
    new_angle = decide(replace(BASE, angle="frontdesk_load"), LeadState(open_lead=lead()), NOW)
    assert new_angle.clear_message
    gone_fact = decide(BASE, LeadState(open_lead=lead(), cited_ids=frozenset({"f-old"})), NOW)
    assert gone_fact.clear_message
    edited = decide(replace(BASE, angle="frontdesk_load"), LeadState(open_lead=lead(), message_edited=True), NOW)
    assert not edited.clear_message


@pytest.mark.parametrize(
    ("other", "today", "allowed"), [(0, 0, 1), (9, 0, 1), (10, 0, 1), (11, 0, 2), (25, 1, 2), (20, 2, 0)]
)
def test_fit_only_allowed(other: int, today: int, allowed: int) -> None:
    assert fit_only_allowed(10, other, today) == allowed


def test_fit_only_cap_keeps_the_best_and_marks_the_rest() -> None:
    cands = [replace(BASE, business_id=f"n{i}", pitch_mode="visible_pain") for i in range(12)]
    cands += [replace(BASE, business_id=f"f{i}", pitch_mode="fit_only", total=50 + i) for i in range(5)]
    stats: Counter[str] = Counter()
    plans = plan_all(cands, {}, {"clinics-in": 10}, NOW, fetch=lambda url: None, stats=stats, today={})
    created = [p.business_id for p in plans.items if p.action == "create" and p.business_id.startswith("f")]
    assert sorted(created) == ["f3", "f4"]
    assert plans.capped("f0") and not plans.capped("n0")
    assert stats["leads.fit_only_capped"] == 3


def test_phone_proof_is_rechecked_after_14_days() -> None:
    contact = {
        "id": "c1",
        "phone_e164": "+919876543210",
        "source": "website",
        "source_url": "https://x.in/contact",
        "verified_at": NOW - timedelta(days=20),
    }
    stale = replace(BASE, best_contact=contact)
    assert ProofChecker(lambda url: "Call us on +91 98765 43210").check(stale, NOW) == "refreshed"
    assert ProofChecker(lambda url: "New number: +91 90000 00000").check(stale, NOW) == "gone"
    assert ProofChecker(lambda url: None).check(stale, NOW) == "stale"
    assert ProofChecker(lambda url: None).check(BASE, NOW) == "ok"
    plans = plan_all([stale], {}, {"clinics-in": 10}, NOW, fetch=lambda url: "nothing here", today={})
    assert plans.items[0].action == "keep" and plans.proof_gone == ["c1"]


def test_channel_follows_the_best_contact() -> None:
    assert BASE.channel == "whatsapp"
    assert replace(BASE, reach_kind="landline", has_email=True).channel == "email"
    assert replace(BASE, reach_kind="landline").channel == "whatsapp"
    assert replace(BASE, reach_kind="email").channel == "email"
    assert replace(BASE, reach_kind="form").channel == "form"
    assert replace(BASE, reach_kind="decision_maker_email").channel == "email"  # email-first countries
