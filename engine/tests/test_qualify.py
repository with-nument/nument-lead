"""Startup qualification (lane E2b, 15 Nov 2026): golden cases a sceptical founder would sign off, the two-evidence
rule for "no tech team", traceable answers, and the phase that stores `startup_profiles`."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import pytest

from nument_engine import db
from nument_engine.pipeline import qualify
from nument_engine.pipeline.qualify import Profile, Rules, assess

from .pipeline_fakes import NOW
from .sources_helpers import clean_db, insert_business, run_context
from .startup_fakes import business, fact, firms_us, member, probe, signal

__all__ = ["clean_db", "firms_us"]

RULES = Rules.defaults()


@dataclass
class Case:
    name: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    biz: dict[str, Any] = field(default_factory=dict)
    expect: dict[str, Any] = field(default_factory=dict)
    disqualified: tuple[str, ...] = ()  # words each disqualification reason must contain, in order
    currency: str = "USD"


FOUNDERS = [
    member("f-maya", "Maya Chen", "Co-founder and CEO", founder=True),
    member("f-tom", "Tom Price", "Co-founder and COO", founder=True),
]
PRE_SEED = signal("s-fund", "funding", age_days=20, round="pre_seed", amount_usd=400_000)
FIRST_ENGINEER = signal(
    "s-hire", "hiring_builder", age_days=4, window_days=30, source="ats_jobs", role="Founding Engineer"
)
ASK = signal("s-ask", "public_ask", age_days=3, window_days=14, source="grounded_search", need="an MVP build")
BUBBLE = probe("f-tech", "tech", {"technologies": [{"name": "Bubble"}], "no_code_platform": "bubble", "ai_vendors": []})

CASES = [
    Case(
        "pre-seed, two business founders, hiring their first engineer: the target",
        facts=[*FOUNDERS],
        signals=[PRE_SEED, FIRST_ENGINEER],
        expect={
            "is_startup": True,
            "team_size": 2,
            "team_size_source": "team_page",
            "tech_team": "none",
            "can_pay": "yes",
            "funding_round": "pre_seed",
            "funding_usd": 400_000,
        },
    ),
    Case(
        "a CEO and a CTO: one technical person is a lone CTO, still a lead",
        facts=[FOUNDERS[0], member("f-raj", "Raj Patel", "Co-founder and CTO", founder=True, engineer=True)],
        signals=[PRE_SEED],
        expect={"tech_team": "lone_cto", "team_size": 2, "is_startup": True},
    ),
    Case(
        "a CTO and two engineers: a team with engineers is not our client",
        facts=[
            FOUNDERS[0],
            member("f-raj", "Raj Patel", "CTO", engineer=True),
            member("f-ana", "Ana Ruiz", "Senior Software Engineer", engineer=True),
            member("f-li", "Li Wei", "Backend Developer", engineer=True),
        ],
        expect={"tech_team": "has_engineers", "team_size": 4},
        disqualified=("engineers",),
    ),
    Case(
        "only the team page says nobody is technical: one sign is not enough",
        facts=[*FOUNDERS],
        expect={"tech_team": "unknown", "is_startup": None},
    ),
    Case(
        "an accelerator list says 14 people: too big",
        facts=[*FOUNDERS],
        signals=[signal("s-yc", "launch", source="startup_lists", batch="W26", team_size=14, team_size_source="list")],
        expect={"team_size": 14, "team_size_source": "list", "is_startup": True},
        disqualified=("14 people",),
    ),
    Case(
        "a Series A: a funded tech team, not our client",
        signals=[signal("s-a", "funding", round="series_a", amount_usd=1_500_000)],
        expect={"funding_round": "series_a"},
        disqualified=("late stage funding: Series A",),
    ),
    Case(
        "a $3.5M seed: more than a small seed",
        facts=[*FOUNDERS],
        signals=[signal("s-big", "funding", round="seed", amount_usd=3_500_000)],
        expect={"funding_usd": 3_500_000, "can_pay": "yes"},
        disqualified=("raised about $3.5M",),
    ),
    Case(
        "a development agency: not a startup",
        facts=[fact("f-agency", "is_agency_or_vendor", {"value": True}, "We build custom apps for our clients")],
        expect={"is_startup": False},
        disqualified=("not a startup, sells services",),
    ),
    Case(
        "founded in 2009 with no startup sign: an established business",
        facts=[fact("f-year", "founded_year", {"year": 2009}, "Serving clients since 2009")],
        expect={"is_startup": False},
        disqualified=("established business",),
    ),
    Case(
        "a Bubble product and non-technical founders in their own words: no tech team",
        facts=[
            BUBBLE,
            fact(
                "f-words",
                "tech_statement",
                {"kind": "no_technical_team"},
                "We are two non-technical founders who built our MVP ourselves",
            ),
        ],
        expect={"tech_team": "none", "product_status": "no_code", "no_code_platform": "bubble"},
    ),
    Case(
        "recent code on GitHub: someone technical is there, so never 'none'",
        facts=[
            *FOUNDERS,
            probe(
                "f-gh",
                "github",
                {"org": "brightcart", "public_repos": 3, "last_push": "2026-11-01", "members_public": 1},
            ),
        ],
        signals=[ASK],
        expect={"tech_team": "unknown"},
    ),
    Case(
        "an equity-only offer and no money seen: cannot pay",
        facts=[
            *FOUNDERS,
            fact(
                "f-eq",
                "revenue_hint",
                {"kind": "no_budget", "value": "equity only"},
                "Technical co-founder wanted, equity only",
            ),
        ],
        expect={"can_pay": "no"},
    ),
    Case(
        "an accelerator batch and a list team size",
        signals=[signal("s-yc", "launch", source="startup_lists", batch="W26", team_size=3)],
        expect={
            "is_startup": True,
            "team_size": 3,
            "team_size_source": "list",
            "can_pay": "yes",
            "funding_round": "accelerator",
        },
    ),
    Case(
        "the team page names more people than an old stated size",
        facts=[
            *FOUNDERS,
            member("f-sam", "Sam Lee", "Head of Growth"),
            member("f-kim", "Kim Ito", "Designer"),
            member("f-joe", "Joe Diaz", "Operations"),
            fact("f-size", "team_size", {"count": 3}, "We are a team of 3"),
        ],
        expect={"team_size": 5, "team_size_source": "team_page"},
    ),
    Case(
        "advisors and investors are not the team, even technical ones",
        facts=[
            *FOUNDERS,
            member("f-adv", "Dr. Ken Mori", "Technical Advisor, ex-Google engineer"),
            member("f-inv", "Lisa Park", "Angel Investor"),
        ],
        signals=[FIRST_ENGINEER],
        expect={"team_size": 2, "tech_team": "none"},
    ),
    Case(
        "an app in the store makes it a mobile app",
        facts=[
            probe(
                "f-store",
                "app_store",
                {
                    "name": "BrightCart",
                    "seller": "BrightCart Inc",
                    "url": "https://apps.apple.com/app/id1",
                    "released": "2026-03-01",
                },
            )
        ],
        expect={"product_status": "mobile_app"},
    ),
    Case(
        "a seed of 2 crore rupees on their own site: about $240,000, can pay",
        facts=[
            fact(
                "f-inr",
                "funding_mention",
                {"round": "seed", "amount": 20_000_000, "currency": "INR"},
                "We raised ₹2 crore in seed funding",
            )
        ],
        expect={"funding_usd": 240_000, "can_pay": "yes", "is_startup": True, "funding_round": "seed"},
        currency="INR",
    ),
    Case(
        "nothing known: every answer stays unknown",
        expect={
            "is_startup": None,
            "team_size": None,
            "tech_team": "unknown",
            "can_pay": "unknown",
            "product_status": "unknown",
            "uses_ai": None,
            "funding_round": None,
        },
    ),
    Case(
        "a careers board with five engineering roles: they are building a team",
        facts=[*FOUNDERS],
        signals=[signal("s-ats", "hiring_builder", source="ats_jobs", role="Senior Engineer", engineering_roles=5)],
        expect={"tech_team": "has_engineers"},
        disqualified=("engineers",),
    ),
    Case(
        "two public asks are one kind of sign, not two",
        signals=[ASK, {**ASK, "id": "s-ask-2"}],
        expect={"tech_team": "unknown"},
    ),
    Case(
        "launched on Hacker News with a waitlist and AI in the product",
        facts=[
            fact("f-wait", "product_status", {"value": "waitlist", "platform": None}, "Join the waitlist"),
            fact("f-ai", "uses_ai", {"value": True}, "An AI agent that books your freight"),
        ],
        signals=[signal("s-hn", "launch", source="hn_launches")],
        expect={"is_startup": True, "product_status": "waitlist", "uses_ai": True},
    ),
]


def run_case(case: Case) -> Profile:
    return assess(business(**case.biz), case.facts, case.signals, NOW, RULES, currency=case.currency)


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_golden_qualification(case: Case) -> None:
    p = run_case(case)
    got = {k: getattr(p, k) for k in case.expect}
    assert got == case.expect, p.evidence
    assert len(p.disqualified) == len(case.disqualified), p.disqualified
    for reason, words in zip(p.disqualified, case.disqualified, strict=True):
        assert words in reason, p.disqualified


def test_there_are_enough_golden_cases() -> None:
    assert len(CASES) >= 12


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_every_answer_is_traceable_to_known_evidence(case: Case) -> None:
    """Contract 4.3: every answer comes with fact or signal ids, or stays unknown."""
    p = run_case(case)
    known = {str(r["id"]) for r in [*case.facts, *case.signals]}
    assert p.all_ids <= known
    answered = {
        "is_startup": p.is_startup is not None,
        "team_size": p.team_size is not None,
        "tech_team": p.tech_team != "unknown",
        "can_pay": p.can_pay != "unknown",
        "product_status": p.product_status != "unknown",
        "uses_ai": p.uses_ai is not None,
        "no_code_platform": p.no_code_platform is not None,
        "funding": p.funding_round is not None,
    }
    for answer, given in answered.items():
        if given:
            assert p.ids(answer), (answer, p.evidence)
            assert p.evidence[answer]["why"], answer
    assert not re.search("[\u2013\u2014]", p.is_startup_why)


# ---- the two-evidence rule for "no tech team" ---------------------------------------------------------

SIGNS: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {
    "team_page": ([*FOUNDERS], []),
    "own_words": ([fact("f-w", "tech_statement", {"kind": "no_technical_team"}, "Looking for a technical co-founder")], []),
    "outsourced": ([fact("f-o", "tech_statement", {"kind": "outsourced"}, "Our app was built by an agency")], []),
    "no_code": ([BUBBLE], []),
    "first_builder": ([], [FIRST_ENGINEER]),
    "asked": ([], [ASK]),
}  # fmt: skip


@pytest.mark.parametrize("kind", sorted(SIGNS))
def test_one_sign_alone_never_makes_no_tech_team(kind: str) -> None:
    facts, signals = SIGNS[kind]
    p = assess(business(), facts, signals, NOW, RULES)
    assert p.tech_team == "unknown" and [s.kind for s in p.no_tech_signs] == [kind]
    assert p.ids("tech_team")  # the one sign is still traceable


@pytest.mark.parametrize(("a", "b"), list(combinations(sorted(SIGNS), 2)))
def test_any_two_independent_signs_make_no_tech_team(a: str, b: str) -> None:
    facts = SIGNS[a][0] + SIGNS[b][0]
    signals = SIGNS[a][1] + SIGNS[b][1]
    p = assess(business(), facts, signals, NOW, RULES)
    assert p.tech_team == "none"
    assert {s.kind for s in p.no_tech_signs} == {a, b}
    assert set(p.ids("tech_team")) == {str(r["id"]) for r in facts + signals}


def test_a_technical_person_overrules_the_signs() -> None:
    facts = [FOUNDERS[0], member("f-raj", "Raj Patel", "Co-founder and CTO", founder=True), BUBBLE]
    p = assess(business(), facts, [ASK, FIRST_ENGINEER], NOW, RULES)
    assert p.tech_team == "lone_cto" and not p.disqualified


def test_old_job_posts_and_asks_are_not_signs() -> None:
    old_ask = {**ASK, "observed_at": NOW.replace(year=2025, month=1)}
    p = assess(business(), [*FOUNDERS], [old_ask], NOW, RULES)
    assert [s.kind for s in p.no_tech_signs] == ["team_page"] and p.tech_team == "unknown"


def test_settings_change_the_limits() -> None:
    case = CASES[4]  # 14 people
    looser = Rules.from_config({"can_pay": {}}, max_team=20)
    assert not assess(business(), case.facts, case.signals, NOW, looser).disqualified


# ---- the phase: startup_profiles -----------------------------------------------------------------------


def seed_startup(**over: Any) -> str:
    bid = insert_business(
        segment_id="firms-us", country="us", city="San Francisco", name="BrightCart", status="researched",
        website="https://brightcart-q.io/", web_domain="brightcart-q.io", **over,
    )  # fmt: skip
    for name, role in (("Maya Chen", "Co-founder and CEO"), ("Tom Price", "Co-founder and COO")):
        db.execute(
            "insert into public.facts (business_id, field, value, quote, url, model, verified, verify_score, "
            "verified_at) values (%s, 'team_member', %s, %s, 'https://brightcart-q.io/team', 'm', true, 100, now())",
            [bid, db.Jsonb({"name": name, "role": role, "is_founder": True, "is_engineer": False}), f"{name}, {role}"],
        )
    db.execute(
        "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, url, "
        "quote, dedupe_key, details) values (%s, 'funding', 'money', 5, now() - interval '10 days', "
        "now() + interval '50 days', 'funding_rss', 'https://news.example.com/x', 'BrightCart raises $400K', %s, %s)",
        [bid, f"test:{bid}", db.Jsonb({"round": "pre_seed", "amount_usd": 400000})],
    )
    return bid


def profile_row(bid: str) -> dict[str, Any] | None:
    return db.fetch_one("select * from public.startup_profiles where business_id = %s", [bid])


def test_run_stores_profiles_with_evidence_and_is_idempotent(firms_us: str) -> None:
    bid = seed_startup()
    other = insert_business(name="Glow Clinic", status="researched")  # clinics-in: not a startup segment
    rc = run_context(segments=["firms-us", "clinics-in"])
    stats = qualify.run(rc)
    assert stats["profiles.new"] == 1 and stats["businesses"] == 1 and rc.stats["qualify"] == stats
    row = profile_row(bid)
    assert row is not None and profile_row(other) is None
    assert (row["is_startup"], row["team_size"], row["tech_team"], row["can_pay"]) == (True, 2, "unknown", "yes")
    assert row["funding_round"] == "pre_seed" and int(row["funding_usd"]) == 400_000
    assert row["is_startup_why"].startswith("Startup: raised a pre-seed round of $400,000")
    assert len(row["team_size_evidence"]) == 2 and row["can_pay_evidence"]
    assert set(row["evidence"]) >= {"is_startup", "team_size", "can_pay", "funding", "tech_team"}
    assert row["evidence"]["tech_team"]["why"].startswith("unknown, one sign so far: the team page lists 2 people")
    again = qualify.run(run_context(segments=["firms-us"]))
    assert again.get("businesses", 0) == 0  # nothing new since the profile was worked out
    db.execute(
        "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, url, "
        "quote, dedupe_key, details) values (%s, 'hiring_builder', 'stated_need', 8, now(), now() + interval '30 days', "
        "'ats_jobs', 'https://jobs.example.com/1', 'Founding Engineer', %s, %s)",
        [bid, f"test:hire:{bid}", db.Jsonb({"role": "Founding Engineer"})],
    )
    third = qualify.run(run_context(segments=["firms-us"]))
    assert third["profiles.changed"] == 1
    row = profile_row(bid)
    assert row is not None and row["tech_team"] == "none" and len(row["tech_team_evidence"]) == 3


def test_dry_run_writes_nothing_and_unverified_facts_wait(firms_us: str) -> None:
    bid = seed_startup()
    qualify.run(run_context(segments=["firms-us"], dry_run=True))
    assert profile_row(bid) is None
    db.execute(
        "insert into public.facts (business_id, field, value, quote, url, model) "
        "values (%s, 'team_size', '{\"count\": 3}', 'a team of 3', 'https://brightcart-q.io/', 'm')",
        [bid],
    )
    assert qualify.run(run_context(segments=["firms-us"])).get("businesses", 0) == 0  # verify comes first
    assert profile_row(bid) is None


def test_no_startup_segment_means_nothing_to_do(clean_db: str) -> None:
    out = qualify.run(run_context(segments=["clinics-in"]))
    assert out == {"skipped": "no startup segment enabled"}
