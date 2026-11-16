"""Score s3.0 (lane E2b, 15 Nov 2026): golden startup leads a sceptical founder would grade the same way, the email
ladder, the grade caps and the routing that keeps s2.0 for every other segment (no database)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest

from nument_engine.pipeline import score_startup
from nument_engine.pipeline.score import ScoringConfig, score_business
from nument_engine.pipeline.verify import Exclusions, Suppression
from nument_engine.segments import load_segments

from .pipeline_fakes import NOW
from .sources_helpers import clean_db
from .startup_fakes import business, company_email, fact, firms_us, founder_email, member, probe, signal

__all__ = ["clean_db", "firms_us"]

SEGMENTS = load_segments()
FIRMS = SEGMENTS["firms-us"]
CFG = ScoringConfig.for_segment(FIRMS, {})
EXCL = Exclusions.load()

FOUNDERS = [
    member("f-maya", "Maya Chen", "Co-founder and CEO", founder=True),
    member("f-tom", "Tom Price", "Co-founder and COO", founder=True),
]
CTO = member("f-raj", "Raj Patel", "Co-founder and CTO", founder=True, engineer=True)
PRE_SEED = signal("s-fund", "funding", age_days=10, points=5, round="pre_seed", amount_usd=400_000)
HIRE = signal("s-hire", "hiring_builder", age_days=4, window_days=30, points=8, source="ats_jobs",
              role="Founding Engineer")  # fmt: skip
ASK = signal("s-ask", "public_ask", age_days=2, window_days=14, points=10, source="grounded_search",
             need="an agency to build our MVP")  # fmt: skip
BUBBLE = probe("f-tech", "tech", {"technologies": [], "no_code_platform": "bubble", "ai_vendors": []})
LIVE = fact("f-live", "website_status", {"status": "live"}, "HTTP 200", model="rule")
YOUNG = probe("f-rdap", "domain_created", {"date": "2025-02-01", "registrar": "x"})


@dataclass
class Lead:
    name: str
    grade: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    contacts: list[dict[str, Any]] = field(default_factory=list)
    total: tuple[int, int] = (0, 100)  # the total falls in this range (inclusive)
    reasons: dict[str, Any] = field(default_factory=dict)  # reasons keys that must equal these values


TARGET = [*FOUNDERS, LIVE, YOUNG]
NO_PROOF = "at most B: no proof of a missing tech team (one sign, or a lone CTO who can build) and no ask of their own"
LEADS = [
    Lead(
        "pre-seed, business founders, hiring a founding engineer, verified founder email",
        "A",
        TARGET,
        [PRE_SEED, HIRE],
        [founder_email()],
        (90, 100),
        {"reach_rung": "verified_owner_email", "disqualified": [], "caps": []},
    ),
    Lead(
        "the same with a likely founder email",
        "A",
        TARGET,
        [PRE_SEED, HIRE],
        [founder_email(status="likely")],
        (85, 97),
        {"reach_rung": "likely_owner_email"},
    ),
    Lead(
        "the same before the founder email is found: B until then",
        "B",
        TARGET,
        [PRE_SEED, HIRE],
        [],
        (75, 84),
        {"reach_rung": "none", "caps": ["at most B: nobody to email yet"]},
    ),
    Lead(
        "funding alone, nothing about the team: not an A",
        "C",
        [LIVE],
        [PRE_SEED],
        [company_email()],
        (55, 65),
        {"reach_rung": "company_email", "caps": ["at most C: nothing yet about the tech team and no ask of their own"]},
    ),
    Lead(
        "funding and a lone CTO: a B",
        "B",
        [FOUNDERS[0], CTO, LIVE, YOUNG],
        [PRE_SEED],
        [founder_email()],
        (75, 85),
        {"angle": "extra_hands", "caps": [NO_PROOF]},
    ),
    Lead(
        "a CTO and two engineers",
        "D",
        [*TARGET, CTO, member("f-ana", "Ana Ruiz", "Software Engineer", engineer=True)],
        [PRE_SEED, HIRE],
        [founder_email()],
        reasons={"fit_gate_failed": True, "disqualified": ["a team with engineers"]},
    ),
    Lead(
        "14 people on an accelerator list",
        "D",
        TARGET,
        [signal("s-yc", "launch", points=4, source="startup_lists", batch="W26", team_size=14)],
        [founder_email()],
        reasons={"disqualified": ["14 people (more than 10)"]},
    ),
    Lead(
        "a Series A",
        "D",
        TARGET,
        [signal("s-a", "funding", points=5, round="series_a", amount_usd=1_200_000)],
        [founder_email()],
        reasons={"disqualified": ["late stage funding: Series A"]},
    ),
    Lead(
        "a $3.5M seed",
        "D",
        TARGET,
        [signal("s-big", "funding", points=5, round="seed", amount_usd=3_500_000)],
        [founder_email()],
        reasons={"disqualified": ["raised about $3.5M (more than $2.0M)"]},
    ),
    Lead(
        "a development agency",
        "D",
        [fact("f-ag", "is_agency_or_vendor", {"value": True}, "We build apps for clients")],
        [],
        [founder_email()],
        reasons={"disqualified": ["not a startup, sells services to other businesses (fact fag)"]},
    ),
    Lead(
        "equity only and no money seen: never above C",
        "C",
        [
            *TARGET,
            fact("f-eq", "revenue_hint", {"kind": "no_budget", "value": "equity only"}, "CTO wanted, equity only"),
        ],
        [ASK],
        [founder_email()],
        reasons={"caps": ["at most C: equity only or unpaid, and no money seen"]},
    ),
    Lead(
        "their own ask and business founders, money unknown: a B",
        "B",
        TARGET,
        [ASK],
        [founder_email()],
        (55, 74),
        {"angle": "build_what_they_asked"},
    ),
    Lead(
        "an accelerator startup on Bubble, non-technical founders in their own words",
        "A",
        [
            LIVE,
            YOUNG,
            BUBBLE,
            fact("f-w", "tech_statement", {"kind": "no_technical_team"}, "We are two non-technical founders"),
        ],
        [
            signal(
                "s-yc", "launch", age_days=6, window_days=30, points=4, source="startup_lists", batch="W26", team_size=2
            )
        ],
        [founder_email()],
        (75, 100),
        {"angle": "beyond_no_code"},
    ),
    Lead(
        "a team page without a technical person and nothing else: one sign is a B at most",
        "B",
        [*TARGET, fact("f-price", "revenue_hint", {"kind": "revenue", "value": "$40K MRR"}, "We hit $40K MRR")],
        [PRE_SEED],
        [founder_email()],
        reasons={"caps": [NO_PROOF]},
    ),
]


def run(lead: Lead, **over: Any) -> Any:
    return score_business(business(**over), lead.facts, lead.signals, lead.contacts, FIRMS, CFG, EXCL, NOW)


@pytest.mark.parametrize("lead", LEADS, ids=[x.name for x in LEADS])
def test_golden_s3(lead: Lead) -> None:
    r = run(lead)
    assert r.version == "s3.0" and r.grade == lead.grade, (r.total, r.reasons)
    assert lead.total[0] <= r.total <= lead.total[1], (r.total, r.reasons["parts"])
    for key, value in lead.reasons.items():
        assert r.reasons[key] == value, (key, r.reasons)
    parts = r.reasons["parts"]
    assert abs(sum(parts.values()) - r.total) <= 1  # the parts add up to the number
    assert 0 <= r.fit <= 3 and 0 <= r.can_pay <= 30 and 0 <= r.intent <= 40 and 0 <= r.reach <= 1  # db checks
    assert len(r.note) <= 280 and not re.search("[\u2013\u2014]", r.note) and r.note.count(". ") <= 1


def test_there_are_enough_golden_leads() -> None:
    assert len(LEADS) >= 12


def test_the_target_lead_explains_itself() -> None:
    r = run(LEADS[0])
    assert (r.pitch_mode, r.angle, r.reach_kind) == ("stated_need", "build_what_they_asked", "decision_maker_email")
    assert r.fit == 3 and r.reasons["gates"] == {"startup": True, "no_tech_team": True, "can_pay": True}
    assert r.reasons["profile"]["tech_team"] == "none" and "raised_250k" in r.reasons["can_pay_proxies"]
    assert r.note.startswith("Hiring a Founding Engineer") and "Nobody technical on a team of 2" in r.note
    assert {"s-fund", "s-hire", "f-maya", "f-tom"} <= r.evidence_ids
    assert r.test_group == "firms-us:stated_need:build_what_they_asked"


def test_the_email_ladder() -> None:
    lead = LEADS[0]
    w = score_startup.Weights.parse(CFG.startup)

    def rung(*contacts: dict[str, Any]) -> tuple[str, float]:
        reach, name = score_startup.reach_of(list(contacts), [], w, NOW, None)
        return name, reach.value

    assert rung(founder_email()) == ("verified_owner_email", 1.0)
    assert rung(founder_email(status="likely")) == ("likely_owner_email", 0.85)
    assert rung(founder_email(status="unknown")) == ("likely_owner_email", 0.85)  # published by the person
    assert rung(founder_email(status="unknown", email_origin="guess")) == ("none", 0.0)  # an unchecked guess
    assert rung(founder_email(status="invalid")) == ("none", 0.0)
    assert rung(company_email(), founder_email(status="likely")) == ("likely_owner_email", 0.85)
    assert rung(company_email()) == ("company_email", 0.7)
    phone = {**company_email("c-ph"), "email": None, "phone_e164": "+14155550100", "phone_type": "mobile"}
    assert rung(phone) == ("phone", 0.4)
    assert rung({**founder_email(), "do_not_contact": True}) == ("none", 0.0)
    form = [fact("f-form", "contact_form_url", {"url": "https://brightcart.io/contact"})]
    assert score_startup.reach_of([], form, w, NOW, None)[1] == "form"
    suppressed = Suppression(frozenset(), frozenset({"maya@brightcart.io"}), frozenset())
    assert score_startup.reach_of([founder_email()], [], w, NOW, suppressed)[1] == "none"
    # a guessed address the checker passed counts even when it was never seen on a page
    checked = {**founder_email(status="verified", email_origin="guess"), "verified": False}
    assert rung(checked) == ("verified_owner_email", 1.0)
    assert run(lead).has_email


def test_other_segments_keep_s2() -> None:
    clinic = {"id": "b1", "name": "Glow Skin", "category": "dermatologist", "review_count": 300, "web_domain": "g.in"}
    seg = SEGMENTS["clinics-in"]
    r = score_business(clinic, [], [], [], seg, ScoringConfig.for_segment(seg, {}), EXCL, NOW)
    assert r.version == "s2.0" and "profile" not in r.reasons


def test_settings_limits_reach_the_score() -> None:
    lead = LEADS[6]  # 14 people
    looser = ScoringConfig.for_segment(FIRMS, {}, (20, 2_000_000))
    r = score_business(business(), lead.facts, lead.signals, lead.contacts, FIRMS, looser, EXCL, NOW)
    assert r.grade != "D" and not r.reasons["disqualified"]


def test_a_rescore_with_the_same_evidence_is_the_same_result() -> None:
    from nument_engine.pipeline.score import same_result

    r = run(LEADS[0])
    row = {"version": "s3.0", "reasons": r.reasons, "pitch_mode": r.pitch_mode, "fit": r.fit, "can_pay": r.can_pay,
           "intent": r.intent, "reach": r.reach, "total": r.total}  # fmt: skip
    assert same_result(row, r) and not same_result({**row, "version": "s2.0"}, r)


# ---- the stage on a test database --------------------------------------------------------------------------


def test_score_run_stores_s3_and_creates_an_email_lead(firms_us: str) -> None:
    from nument_engine import db
    from nument_engine.pipeline import score

    from .sources_helpers import insert_business, run_context

    bid = insert_business(
        segment_id="firms-us", country="us", city="San Francisco", name="BrightCart", status="researched",
        website="https://brightcart-s.io/", web_domain="brightcart-s.io",
    )  # fmt: skip
    for name, role in (("Maya Chen", "Co-founder and CEO"), ("Tom Price", "Co-founder and COO")):
        db.execute(
            "insert into public.facts (business_id, field, value, quote, url, model, verified, verify_score, "
            "verified_at) values (%s, 'team_member', %s, %s, 'https://brightcart-s.io/team', 'm', true, 100, now())",
            [bid, db.Jsonb({"name": name, "role": role, "is_founder": True, "is_engineer": False}), f"{name}, {role}"],
        )
    for kind, cat, details in (
        ("funding", "money", {"round": "pre_seed", "amount_usd": 400000}),
        ("hiring_builder", "stated_need", {"role": "Founding Engineer"}),
    ):
        db.execute(
            "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, url, "
            "quote, dedupe_key, details) values (%s, %s, %s, 0, now() - interval '2 days', now() + interval '28 days', "
            "'ats_jobs', 'https://x.example.com', %s, %s, %s)",
            [bid, kind, cat, kind, f"test:{kind}:{bid}", db.Jsonb(details)],
        )
    db.execute(
        "insert into public.contacts (business_id, name, role, email, source, verified, verified_at, is_decision_maker, "
        "line, email_status, email_origin) values (%s, 'Maya Chen', 'Co-founder and CEO', 'maya@brightcart-s.io', "
        "'website', true, now(), true, 'owner', 'verified', 'published')",
        [bid],
    )
    stats = score.run(run_context(segments=["firms-us"]))
    row = db.fetch_one("select * from public.scores where business_id = %s", [bid])
    assert row is not None and row["version"] == "s3.0" and row["grade"] == "A", row
    assert row["reasons"]["reach_rung"] == "verified_owner_email" and row["fit"] == 3
    lead = db.fetch_one("select grade, channel, pitch_mode, angle from public.leads where business_id = %s", [bid])
    assert lead == {"grade": "A", "channel": "email", "pitch_mode": "stated_need", "angle": "build_what_they_asked"}
    assert stats["leads.create"] == 1
    again = score.run(run_context(segments=["firms-us"]))
    assert again["scores.unchanged"] == 1 and again.get("scores.new_rows", 0) == 0
