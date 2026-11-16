"""The startup email path without a database: sequence lint and claims, who a thread may go to, the cooldown,
offer picks and plan checks (contracts 4.5 to 4.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine.models import Claim, EmailSequence, OfferPick, PlanContent, PlanWeek, ScreenSection, ScreenSpec
from nument_engine.pipeline import leads, offers, plans
from nument_engine.pipeline import message as m
from nument_engine.pipeline.lint import ClaimContext
from nument_engine.pipeline.verify import Suppression
from nument_engine.segments import load_segments

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
NONE_SUPPRESSED = Suppression(frozenset(), frozenset(), frozenset())

DAY0 = (
    "Hi Maya, congrats on Brightcart's pre-seed round. We're Nument, a small AI-first studio that ships "
    "polished MVPs in weeks with a fixed scope. With no engineers on the team yet, we could build the first "
    "version of the grocer ordering app while you hire. Want me to send a 1-page plan for Brightcart?"
)
ALT = (
    "Hi Maya, saw the news about Brightcart's pre-seed round and the grocer ordering app. We're Nument, a small "
    "AI-first studio, and we ship working first versions in 4 to 6 weeks, fixed scope. Happy to sketch how "
    "we'd build yours. Want me to send a 1-page plan for Brightcart?"
)
DAY3 = (
    "Hi Maya, here's the 1-page plan we put together for Brightcart: {plan_link} It starts with grocer "
    "ordering on the web, then the dashboard. Worth a 20-minute call to go through it?"
)
DAY7 = (
    "Hi Maya, here's a similar first version we shipped for another early team: {case_study} Same idea, a "
    "small scope that went live fast. Would something like that fit Brightcart?"
)
DAY12 = "Hi Maya, I don't want to crowd your inbox. Should I close this out, or is later better?"


def sequence(**over: Any) -> EmailSequence:
    values: dict[str, Any] = {
        "subject": "your pre-seed round",
        "day0": DAY0,
        "day0_alt": ALT,
        "day3": DAY3,
        "day7": DAY7,
        "day12": DAY12,
        "claims": [Claim(text="pre-seed round", ids=["S1"]), Claim(text="no engineers", ids=["F1"])],
    }
    values.update(over)
    return EmailSequence(**values)


def seq_input(**over: Any) -> m.SequenceInput:
    seg = load_segments()["firms-us"]
    business = {"id": "b1", "name": "Brightcart Inc.", "web_domain": "brightcart.io", "country": "us"}
    contact = {"id": "c1", "name": "Maya Chen", "role": "Founder", "email": "maya@brightcart.io", "line": "owner"}
    offer = {
        "offer_key": "mvp_sprint",
        "name": "MVP sprint",
        "best_for": "Pre-seed, non-technical founders",
        "promise": "A polished, working first version of the product, built with AI speed and fixed scope",
        "timeline": "4 to 6 weeks",
        "why_now": "Brightcart raised a pre-seed round and has no engineers yet.",
    }
    facts = [
        {"id": "F1", "field": "tech_team", "value": {"value": "no engineers yet"}, "quote": "no engineers yet"},
        {"id": "F2", "field": "product", "value": {"value": "grocer ordering app"}, "quote": "an ordering app"},
        {"id": "F3", "field": "probe.dns", "value": {"mx_provider": "google"}, "quote": ""},
        {"id": "F4", "field": "email", "value": {"email": "maya@brightcart.io"}, "quote": ""},
    ]
    signals = [
        {
            "id": "S1",
            "type": "funding",
            "category": "growth",
            "points": 5,
            "source": "funding_rss",
            "observed_at": NOW - timedelta(days=5),
            "expires_at": NOW + timedelta(days=55),
            "quote": "Brightcart raised a pre-seed round",
            "details": {"round": "pre_seed", "amount_usd": 600000},
        }
    ]
    si = m.build_sequence_input({"id": "l1"}, business, seg, contact, offer, None, facts, signals, None, NOW)
    for k, v in over.items():
        setattr(si, k, v)
    return si


# ---------------------------------------------------------------------------
# Lint of each part
# ---------------------------------------------------------------------------


def test_a_good_sequence_passes_every_check() -> None:
    si = seq_input()
    checked = m.check_sequence(sequence(), si, m.DayLog())
    assert checked.problems == [], checked.problems
    assert not checked.drop_alt and set(checked.cited) == {"S1", "F1"}


@pytest.mark.parametrize(
    ("part", "text", "expected"),
    [
        ("day0", DAY0.replace("Want me", "See nument.in. Want me"), "contains a link"),
        ("day0", DAY0.replace("Brightcart?", "Brightcart? {plan_link}"), "placeholder {plan_link} does not belong"),
        ("day0", DAY0.replace("round.", "round \u2013 nice."), "contains a dash"),
        ("day0", DAY0.replace("pre-seed round", "$600K pre-seed round"), "mentions money"),
        ("day0", DAY0.replace("We're Nument,", "We're a studio,"), "must name Nument once"),
        ("day0", DAY0.replace("Want me", "Busy? Want me"), "2 question marks"),
        ("day0", DAY0 + "\n\nBest,", "ends with a sign-off"),
        ("day0", DAY0 + "\n\nTeam Nument", "names Nument more than once"),
        ("day0", DAY0.replace(" With no", "\n- With no"), "a list in the first email"),
        ("day0", DAY0.replace("congrats", "just checking in and congrats"), "banned phrase 'just checking in'"),
        ("day0", DAY0.replace("Hi Maya,", "Hi Leo,"), "must start with the greeting 'Hi Maya,'"),
        ("day0", DAY0.replace("Maya,", "[Name],"), "unfilled template slot"),
        ("day3", DAY3.replace("{plan_link}", "here"), "must contain {plan_link} exactly once"),
        ("day3", DAY3.replace("{plan_link}", "{plan_link} {plan_link}"), "must contain {plan_link} exactly once"),
        ("day3", DAY3.replace("{plan_link}", "{plan_link} https://x.example"), "a link other than {plan_link}"),
        ("day7", DAY7.replace("{case_study}", "{plan_link}"), "must contain {case_study} exactly once"),
        ("day12", "Hi Maya, close this out?", "words (want 8 to 60)"),
        ("subject", "quick question?", "subject asks a question"),
        ("subject", "Re: your round", "subject pretends to be a reply"),
    ],
)
def test_lint_catches_each_rule(part: str, text: str, expected: str) -> None:
    problems = " | ".join(m.lint_part(text, part, "Hi Maya," if part != "subject" else ""))
    assert expected in problems, problems


def test_the_alternative_first_email_is_dropped_not_fatal() -> None:
    checked = m.check_sequence(sequence(day0_alt="Hi Maya, too short?"), seq_input(), m.DayLog())
    assert checked.hard == [] and checked.drop_alt and checked.optional
    assert checked.rank > m.check_sequence(sequence(day12="Hi Maya, ok"), seq_input(), m.DayLog()).rank


def test_claims_catch_invented_details_but_not_our_own_offer() -> None:
    si = seq_input()
    invented = sequence(day0=DAY0.replace("pre-seed round", "pre-seed round led by Sequoia"))
    checked = m.check_sequence(invented, si, m.DayLog())
    assert "name 'Sequoia' is not in the cited facts" in checked.claims
    unknown = m.check_sequence(sequence(claims=[Claim(text="x", ids=["S999"])]), si, m.DayLog())
    assert "cites unknown id 'S999'" in unknown.claims
    # "1-page plan", "20-minute call" and the offer's "4 to 6 weeks" are ours: no claim problem
    assert m.check_sequence(sequence(), si, m.DayLog()).claims == []
    overpromise = m.check_sequence(sequence(day0=DAY0.replace("in weeks", "in 2 weeks")), si, m.DayLog())
    assert "number '2' is not in the cited facts" in overpromise.claims


def test_the_writer_never_sees_addresses_or_private_probes() -> None:
    si = seq_input()
    fields = {f["field"] for f in si.inputs["facts"]}
    assert fields == {"tech_team", "product"}
    assert si.inputs["greeting"] == "Hi Maya," and si.inputs["seen_where"] == "the news about your round"
    assert "@" not in str(si.inputs) and si.to_domain == "brightcart.io"
    assert "amount usd: $600,000" in si.inputs["signals"][0]["summary"]


# ---------------------------------------------------------------------------
# Who a thread may go to (contract 4.6)
# ---------------------------------------------------------------------------


def contact(**over: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": "c1",
        "name": "Maya Chen",
        "email": "maya@brightcart.io",
        "email_status": "verified",
        "email_origin": "published",
        "line": "owner",
        "is_decision_maker": True,
        "do_not_contact": False,
        "created_at": NOW,
    }
    values.update(over)
    return values


def test_the_founder_s_verified_address_comes_first() -> None:
    company = contact(id="c2", name=None, email="hello@brightcart.io", line="other", is_decision_maker=False)
    likely = contact(id="c3", email="maya.chen@brightcart.io", email_status="likely")
    assert m.sendable_contact([company, likely, contact()], NONE_SUPPRESSED)["id"] == "c1"  # type: ignore[index]
    assert m.sendable_contact([company, likely], NONE_SUPPRESSED)["id"] == "c3"  # type: ignore[index]
    for bad in (
        contact(email_status="unknown"),
        contact(email_status="invalid"),
        contact(do_not_contact=True),
        contact(line="bot"),
        contact(email="not-an-address"),
    ):
        assert m.sendable_contact([bad], NONE_SUPPRESSED) is None
    suppressed = Suppression(frozenset(), frozenset({"maya@brightcart.io"}), frozenset())
    assert m.sendable_contact([contact()], suppressed) is None


def test_country_rules_come_from_outreach_yaml() -> None:
    rules = m.OutreachRules.load()
    assert rules.cooldown_days == 90
    assert rules.country_block("us", "guess") is None
    assert rules.country_block("de", "published") == "country_blocked"
    assert rules.country_block("jp", "published") == "country_not_allowed"
    assert rules.country_block("ca", "guess") == "guess_in_published_only_country"
    assert rules.country_block("ca", "published") is None


def test_free_mail_counts_as_the_company_domain() -> None:
    assert m.thread_domains("maya@brightcart.io", {"web_domain": "www.brightcart.io"}) == (
        "brightcart.io",
        ["brightcart.io"],
    )
    assert m.thread_domains("maya@acmehq.com", {"web_domain": "acme.ai"}) == ("acmehq.com", ["acmehq.com", "acme.ai"])
    assert m.thread_domains("maya.chen@gmail.com", {"web_domain": "brightcart.io"}) == (
        "brightcart.io",
        ["brightcart.io"],
    )
    assert m.thread_domains("maya.chen@gmail.com", {}) == (None, [])


def thread(**over: Any) -> m.DomainThread:
    values: dict[str, Any] = {
        "id": "t1",
        "lead_id": "other",
        "status": "done",
        "created_at": NOW - timedelta(days=200),
        "last_sent_at": None,
        "sending": False,
    }
    values.update(over)
    return m.DomainThread(**values)


@pytest.mark.parametrize(
    ("t", "want"),
    [
        (thread(status="open"), "domain_open_thread"),
        (thread(status="open", lead_id="l1"), "open_thread"),
        (thread(last_sent_at=NOW - timedelta(days=30)), "domain_cooldown"),
        (thread(sending=True), "domain_cooldown"),
        (thread(created_at=NOW - timedelta(days=10)), "domain_cooldown"),  # another lead's thread, nothing sent
        (thread(last_sent_at=NOW - timedelta(days=100)), None),
        (thread(lead_id="l1", status="stopped", created_at=NOW - timedelta(days=5)), None),  # own, never sent
        (thread(lead_id="l1", status="stopped", last_sent_at=NOW - timedelta(days=5)), "domain_cooldown"),
    ],
)
def test_cooldown_rules(t: m.DomainThread, want: str | None) -> None:
    assert m.cooldown_block([t], "l1", NOW, 90) == want


def test_a_rewrite_ignores_its_own_open_thread() -> None:
    own = thread(id="t9", lead_id="l1", status="open", created_at=NOW)
    assert m.cooldown_block([own], "l1", NOW, 90) == "open_thread"
    assert m.cooldown_block([own], "l1", NOW, 90, own_thread_id="t9") is None


# ---------------------------------------------------------------------------
# What the stage does with a selected lead
# ---------------------------------------------------------------------------


def test_sequence_actions() -> None:
    plain = leads.MessageHistory()
    edited = leads.MessageHistory(edited=True, edited_at=NOW)
    new = {"message": None, "regen_requested_at": None}
    regen = {"message": "Hi", "regen_requested_at": NOW + timedelta(minutes=1)}
    t = {"id": "t1"}
    drafts = [{"status": "draft"}] * 4
    review = [{"status": "review"}, *[{"status": "draft"}] * 3]
    sent = [{"status": "sent"}, *[{"status": "queued"}] * 3]
    assert m.sequence_action(new, plain, None, []) == "write"
    assert m.sequence_action({"message": "Hi", "regen_requested_at": None}, plain, None, []) == "write"  # old path
    assert m.sequence_action({"message": "Hi", "regen_requested_at": None}, edited, None, []) == "skip:edited_by_person"
    assert m.sequence_action(regen, edited, None, []) == "write"
    assert m.sequence_action(regen, plain, t, review) == "rewrite"
    assert m.sequence_action(regen, plain, t, sent) == "skip:thread_in_progress"
    assert m.sequence_action(new, plain, t, drafts) == "rewrite"  # a rescore cleared it before anyone looked
    assert m.sequence_action(new, plain, t, review) == "restore"
    assert m.sequence_action({"message": "Hi", "regen_requested_at": None}, plain, t, drafts) == "skip:has_thread"


def test_profile_lines_leave_unknowns_out_and_keep_evidence_ids() -> None:
    profile = {
        "team_size": 3,
        "team_size_evidence": ["F1"],
        "tech_team": "none",
        "tech_team_evidence": ["F1", "S1"],
        "can_pay": "unknown",
        "product_status": "waitlist",
        "no_code_platform": None,
        "uses_ai": False,
        "funding_round": "pre_seed",
        "funding_usd": 600000,
        "funding_at": "2026-11-10",
    }
    assert m.profile_lines(profile) == [
        "team size: 3 (evidence F1)",
        "tech team: none (evidence F1, S1)",
        "product status: waitlist",
        "uses AI: no",
        "funding: pre seed, 2026-11-10",
    ]
    assert m.profile_lines(profile, amounts=True)[-1] == "funding: pre seed, about $600,000, 2026-11-10"
    assert m.profile_lines(None) == []


# ---------------------------------------------------------------------------
# Offer picks (contract 4.5)
# ---------------------------------------------------------------------------

OFFERS = {
    "mvp_sprint": {"key": "mvp_sprint", "name": "MVP sprint", "best_for": "Pre-seed, non-technical founders"},
    "launch_kit": {"key": "launch_kit", "name": "Launch kit", "best_for": "Idea stage, no product yet"},
}
CTX = ClaimContext(
    known_ids={"f1": "F1", "s1": "S1"},
    evidence_text={"F1": "tech team no engineers yet", "S1": "funding pre seed round 5 days ago"},
    trusted_words={"brightcart"},
)


def pick(**over: Any) -> OfferPick:
    values: dict[str, Any] = {
        "offer_key": "mvp_sprint",
        "backup_offer_key": "launch_kit",
        "why_now": "Brightcart just raised a pre-seed round and has no engineers yet.",
        "cited_ids": ["S1", "[F1]"],
        "confidence": 0.8,
    }
    values.update(over)
    return OfferPick(**values)


def test_a_good_pick_keeps_known_ids_in_canonical_form() -> None:
    p = offers.review_pick(pick(), OFFERS, CTX)
    assert (p.offer_key, p.backup_key, p.cited, p.problems, p.fatal) == (
        "mvp_sprint",
        "launch_kit",
        ["S1", "F1"],
        [],
        False,
    )


@pytest.mark.parametrize(
    ("over", "fatal", "problem"),
    [
        ({"offer_key": "website_redo"}, True, "not one of the listed offer keys"),
        ({"backup_offer_key": "mvp_sprint"}, False, "must be another key"),
        ({"cited_ids": ["S1", "F-made-up"]}, False, "not listed: F-made-up"),
        ({"cited_ids": ["F-made-up"]}, True, "cites no listed fact or signal"),
        ({"why_now": "Brightcart raised $2M from Sequoia."}, True, "is not in the cited facts"),
        ({"why_now": "One. Two. Three sentences here."}, True, "one short plain sentence"),
    ],
)
def test_bad_picks(over: dict[str, Any], fatal: bool, problem: str) -> None:
    p = offers.review_pick(pick(**over), OFFERS, CTX)
    assert p.fatal is fatal and any(problem in x for x in p.problems), p.problems
    if "backup_offer_key" in over:
        assert p.backup_key is None


def test_dashes_in_why_now_become_commas_and_the_rewrite_wins() -> None:
    first = offers.review_pick(pick(why_now="Brightcart raised a pre-seed round \u2014 no engineers yet."), OFFERS, CTX)
    assert first.why_now == "Brightcart raised a pre-seed round, no engineers yet." and not first.fatal
    bad = offers.review_pick(pick(offer_key="nope"), OFFERS, CTX)
    assert offers.choose(bad, first) is first
    assert offers.choose(first, bad) is first
    assert offers.choose(bad, bad) is None


# ---------------------------------------------------------------------------
# Plans (contract 4.7)
# ---------------------------------------------------------------------------

MVP = {
    "offer_key": "mvp_sprint",
    "name": "MVP sprint",
    "timeline": "4 to 6 weeks",
    "typical_range": {"usd": [3000, 12000], "inr": [150000, 600000]},
}


def plan(**over: Any) -> PlanContent:
    values: dict[str, Any] = {
        "headline": "Brightcart ordering app, first version in 5 weeks",
        "their_goal": "Let grocers take orders online.",
        "scope_now": ["Shop page", "Cart and checkout", "Grocer dashboard"],
        "scope_later": ["Delivery tracking"],
        "timeline": [PlanWeek(week=1, deliverable="Design"), PlanWeek(week=5, deliverable="Launch")],
        "typical_range": "set by Nument",
        "first_screen": ScreenSpec(
            app_name="Brightcart",
            title="Today's orders",
            sections=[ScreenSection(kind="list", label="Orders", items=["Order 1042, ready"])],
        ),
        "next_step": "Book a 20-minute call to go through it.",
    }
    values.update(over)
    return PlanContent(**values)


PLAN_CTX = ClaimContext(
    known_ids={"f2": "F2"},
    evidence_text={"F2": "product grocer ordering app"},
    trusted_words={"brightcart"},
    trusted_numbers={"4", "6"},
)


def test_money_ranges_come_from_the_offer_table() -> None:
    assert plans.money_range(MVP, "us") == "Projects like this usually run $3,000 to $12,000, paid in milestones."
    assert plans.money_range(MVP, "in") == ("Projects like this usually run ₹1.5 lakh to ₹6 lakh, paid in milestones.")
    monthly = {"typical_range": {"usd_month": [1500, 6000], "inr_month": [80000, 300000]}}
    assert plans.money_range(monthly, "gb") == "Work like this usually runs $1,500 to $6,000 a month."
    assert plans.money_range(monthly, "in") == "Work like this usually runs ₹80,000 to ₹3 lakh a month."
    assert plans.money_range({"typical_range": {}}, "us") == ""
    assert plans.offer_weeks(MVP) == 6 and plans.offer_weeks({"timeline": "Monthly"}) is None


def test_a_good_plan_passes_and_gets_our_price_range() -> None:
    assert plans.plan_problems(plan(), PLAN_CTX, MVP) == []
    done = plans.finished_plan(plan(their_goal="Let grocers \u2013 small ones \u2013 order online."), MVP, "us")
    assert done.typical_range.startswith("Projects like this usually run $3,000")
    assert done.their_goal == "Let grocers, small ones, order online."


@pytest.mark.parametrize(
    ("over", "problem"),
    [
        ({"headline": "<b>Brightcart</b> app"}, "contains markup"),
        ({"next_step": "Book at https://cal.com/x"}, "contains a link"),
        ({"scope_now": ["Checkout for $9 plans"]}, "mentions money"),
        ({"scope_later": ["Lorem ipsum"]}, "placeholder text"),
        ({"timeline": [PlanWeek(week=1, deliverable="a"), PlanWeek(week=9, deliverable="b")]}, "past the offer"),
        ({"timeline": [PlanWeek(week=3, deliverable="a"), PlanWeek(week=2, deliverable="b")]}, "go up one by one"),
        ({"headline": "Brightcart app for Walmart"}, "name 'Walmart' is not in the cited facts"),
    ],
)
def test_plan_problems(over: dict[str, Any], problem: str) -> None:
    problems = plans.plan_problems(plan(**over), PLAN_CTX, MVP)
    assert any(problem in p for p in problems), problems


def test_the_app_on_the_first_screen_is_theirs() -> None:
    bad = plan(
        first_screen=ScreenSpec(app_name="Nument", title="Home", sections=[ScreenSection(kind="nav", label="x")])
    )
    assert any("not Nument" in p for p in plans.plan_problems(bad, PLAN_CTX, MVP))


def test_case_study_links(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_URL", "https://lead.nument.in")
    from nument_engine import settings

    settings.get_settings.cache_clear()
    studies = [
        {"slug": "newest-any", "offer_key": "ai_ops"},
        {"slug": "mvp-story", "offer_key": "mvp_sprint"},
        {"slug": "launch story", "offer_key": "launch_kit"},
    ]
    assert plans.case_study_url(studies, ["mvp_sprint", "launch_kit"]) == "https://lead.nument.in/c/mvp-story"
    assert plans.case_study_url(studies, ["tech_team", "launch_kit"]) == "https://lead.nument.in/c/launch%20story"
    assert plans.case_study_url(studies, ["tech_team", None]) == "https://lead.nument.in/c/newest-any"
    assert plans.case_study_url([], ["mvp_sprint"]) == "https://nument.in"
    assert plans.plan_url("abc") == "https://lead.nument.in/p/abc"


def test_week_counts_in_a_plan_stay_inside_the_offer() -> None:
    assert plans.plan_problems(plan(headline="Brightcart ordering app in 6 weeks"), PLAN_CTX, MVP) == []
    late = plans.plan_problems(plan(headline="Brightcart ordering app in 10 weeks"), PLAN_CTX, MVP)
    assert any("promises 10 weeks" in p for p in late), late


def test_an_invented_detail_in_the_alternative_only_drops_the_alternative() -> None:
    checked = m.check_sequence(
        sequence(day0_alt=ALT.replace("grocer ordering app", "Walmart app")), seq_input(), m.DayLog()
    )
    assert checked.claims == [] and checked.hard == [] and checked.drop_alt
    assert any("Walmart" in p for p in checked.optional)
    checked.score = 9
    assert m.sequence_flags(checked) == []  # the alternative is never sent: no flag holds day 0 back
    assert m.flags_for(checked) != []
