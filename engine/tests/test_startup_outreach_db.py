"""Offers, the startup email sequence with its thread, and plan pages against a throwaway Postgres
(contracts 4.5 to 4.7). The AI router is a fake; nothing is sent anywhere.

The tests own the `firms-sg` and `firms-ca` segments (both email-first; Canada is published-only).
"""

from __future__ import annotations

import random
import string
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.models import (
    Claim,
    EmailSequence,
    MessageCheck,
    OfferPick,
    PlanContent,
    PlanWeek,
    ScreenSection,
    ScreenSpec,
)
from nument_engine.pipeline import message, offers, plans

from . import pipeline_fakes as pf
from .pipeline_fakes import AllProvidersDown, FakeRouter, rc_for

SEGMENTS = ("firms-sg", "firms-ca")
SLUG = "e4-test-mvp-story"


@pytest.fixture
def startup_db(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("APP_URL", "https://lead.nument.in")
    settings_module.get_settings.cache_clear()
    with pf.connect(engine_db) as conn:
        for seg in SEGMENTS:
            conn.execute(
                "insert into public.segments (id, domain, country, display_name, enabled, daily_quota) "
                "values (%s, 'firms', %s, %s, true, 10) on conflict (id) do update set enabled = true",
                [seg, seg[-2:], seg],
            )
    _clean(engine_db)
    yield engine_db
    _clean(engine_db)


def _clean(dsn: str) -> None:
    for seg in SEGMENTS:
        pf.wipe_segment(dsn, seg)
    with pf.connect(dsn) as conn:
        conn.execute("delete from public.case_studies where slug like 'e4-test-%%'")
        conn.execute("delete from public.suppression where reason = 'e4_test'")
        conn.execute("update public.settings set value = '\"off\"'::jsonb where key = 'outreach.mode'")


def _tag() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=6))


def seed(
    dsn: str,
    *,
    segment: str = "firms-sg",
    domain: str | None = None,
    email: str | None = None,
    status: str = "verified",
    origin: str = "published",
    with_offer: bool = True,
) -> dict[str, str]:
    """A new A lead: a startup with a verified fact, an active funding signal and its founder's address."""
    tag = _tag()
    domain = domain or f"brightcart-{tag}.io"
    country = segment[-2:]
    with pf.connect(dsn) as conn:
        bid = pf.business(
            conn,
            segment_id=segment,
            name=f"Brightcart {tag.capitalize()}",
            norm_name=f"brightcart {tag}",
            website=f"https://{domain}/",
            web_domain=domain,
            country=country,
            city=None,
            category="startup",
            subcategory=None,
            review_count=None,
        )
        now = datetime.now(UTC)
        fact = pf.fact(
            conn, bid, "product", {"value": "grocer ordering app"}, "an ordering app for grocers",
            f"https://{domain}/", verified=True, verify_score=90, verified_at=now,
        )  # fmt: skip
        team = pf.fact(
            conn, bid, "tech_team", {"value": "no engineers yet"}, "no engineers yet", f"https://{domain}/about",
            verified=True, verify_score=90, verified_at=now,
        )  # fmt: skip
        signal = pf.signal(
            conn, bid, "funding", "growth", 5, 5, 60, source="funding_rss",
            quote="raised a pre-seed round", details={"round": "pre_seed"},
        )  # fmt: skip
        contact = pf.contact(
            conn, bid, name="Maya Chen", role="Founder", email=email or f"maya@{domain}", email_status=status,
            email_origin=origin, line="owner", is_decision_maker=True, phone_type="unknown",
        )  # fmt: skip
        score = pf.insert(
            conn,
            "scores",
            {"business_id": bid, "version": "s3.0", "fit": 3, "total": 82, "grade": "A", "pitch_mode": "fit_only"},
        )
        lead = pf.insert(
            conn,
            "leads",
            {
                "business_id": bid,
                "segment_id": segment,
                "score_id": score,
                "grade": "A",
                "pitch_mode": "fit_only",
                "channel": "email",
                "stage": "new",
            },
        )
        if with_offer:
            conn.execute(
                "insert into public.lead_offers (lead_id, rank, offer_key, why_now, cited_ids) values "
                "(%s, 1, 'mvp_sprint', 'Brightcart raised a pre-seed round and has no engineers yet.', %s), "
                "(%s, 2, 'launch_kit', null, %s)",
                [lead, [signal, team], lead, [signal, team]],
            )
    return {
        "business": bid,
        "lead": lead,
        "domain": domain,
        "fact": fact,
        "team": team,
        "signal": signal,
        "contact": contact,
        "email": email or f"maya@{domain}",
    }


# ---------------------------------------------------------------------------
# Fake answers
# ---------------------------------------------------------------------------


def good_pick(inputs: dict[str, Any]) -> OfferPick:
    signal = next(s["id"] for s in inputs["signals"] if s["type"] == "funding")
    team = next(f["id"] for f in inputs["facts"] if f["field"] == "tech_team")
    return OfferPick(
        offer_key="mvp_sprint",
        backup_offer_key="launch_kit",
        why_now=f"{inputs['company']} raised a pre-seed round and has no engineers yet.",
        cited_ids=[f"S{signal}", f"[F{team}]"],
        confidence=0.8,
    )


def sequence_answer(inputs: dict[str, Any], *, opener: str = "congrats on", extra: str = "") -> EmailSequence:
    company, hi = inputs["company"], inputs["greeting"]
    signal = next(s["id"] for s in inputs["signals"] if s["type"] == "funding")
    team = next(f["id"] for f in inputs["facts"] if f["field"] == "tech_team")
    return EmailSequence(
        subject="your pre-seed round",
        day0=f"{hi} {opener} {company}'s pre-seed round{extra}. We're Nument, a small AI-first studio that ships "
        "polished MVPs in weeks with a fixed scope. With no engineers on the team yet, we could build the first "
        f"version of the grocer ordering app while you hire. Want me to send a 1-page plan for {company}?",
        day0_alt=None,
        day3=f"{hi} here's the 1-page plan we put together for {company}: {{plan_link}} It starts with grocer "
        "ordering on the web, then the dashboard. Worth a 20-minute call to go through it?",
        day7=f"{hi} here's a similar first version we shipped for another early team: {{case_study}} A small "
        f"scope that went live fast. Would something like that fit {company}?",
        day12=f"{hi} I don't want to crowd your inbox. Should I close this out, or is later better?",
        claims=[Claim(text="pre-seed round", ids=[f"S{signal}"]), Claim(text="no engineers", ids=[team])],
    )


def plan_answer(inputs: dict[str, Any], *, headline: str | None = None) -> PlanContent:
    company = inputs["company"]
    return PlanContent(
        headline=headline or f"{company} ordering app, first version in 5 weeks",
        their_goal="Let grocers take orders online.",
        scope_now=["Shop page", "Cart and checkout", "Grocer dashboard"],
        scope_later=["Delivery tracking"],
        timeline=[PlanWeek(week=1, deliverable="Design"), PlanWeek(week=5, deliverable="Launch")],
        typical_range="set by Nument",
        first_screen=ScreenSpec(
            app_name=company,
            title="Today's orders",
            sections=[ScreenSection(kind="list", label="Orders", items=["Order 1042, ready"])],
        ),
        next_step="Book a 20-minute call to go through it.",
    )


def ok_router(**extra: Any) -> FakeRouter:
    answers: dict[str, Any] = {
        "write_email_sequence": sequence_answer,
        "check_message": lambda _i: MessageCheck(score=9, issues=[]),
        **extra,
    }
    return FakeRouter(answers)


def rc(**kw: Any) -> Any:
    return rc_for(segments=list(SEGMENTS), **kw)


def thread_of(lead_id: str) -> dict[str, Any] | None:
    return db.fetch_one("select * from public.email_threads where lead_id = %s", [lead_id])


def steps_of(thread_id: str) -> list[dict[str, Any]]:
    return db.fetch_all(
        "select step, subject, body, status, scheduled_for from public.email_messages "
        "where thread_id = %s and direction = 'out' order by step",
        [thread_id],
    )


def lead_row(lead_id: str) -> dict[str, Any]:
    row = db.fetch_one("select * from public.leads where id = %s", [lead_id])
    assert row is not None
    return row


# ---------------------------------------------------------------------------
# Offers (contract 4.5)
# ---------------------------------------------------------------------------


def test_offers_store_rank_one_and_two_with_ids_that_exist(startup_db: str) -> None:
    ids = seed(startup_db, with_offer=False)
    router = FakeRouter({"pick_offer": good_pick})
    stats = offers.run(rc(), router=router)
    assert stats["stored"] == 1 and stats["offer.mvp_sprint"] == 1 and router.tasks() == ["pick_offer"]
    inputs = router.calls[0].inputs
    assert [o["key"] for o in inputs["offers"]][:2] == ["launch_kit", "mvp_sprint"] and len(inputs["offers"]) == 8
    assert "@" not in str(inputs)
    rows = db.fetch_all("select * from public.lead_offers where lead_id = %s order by rank", [ids["lead"]])
    assert [(r["rank"], r["offer_key"]) for r in rows] == [(1, "mvp_sprint"), (2, "launch_kit")]
    assert rows[0]["why_now"].endswith("raised a pre-seed round and has no engineers yet.")
    assert sorted(rows[0]["cited_ids"]) == sorted([ids["signal"], ids["team"]])  # canonical ids, all real
    assert rows[1]["why_now"] is None and rows[0]["model"] == "gemini:gemini-3-flash#pick_offer.v1"
    picked = db.fetch_one(
        "select payload from public.activities where lead_id = %s and payload ->> 'kind' = 'offer_picked'",
        [ids["lead"]],
    )
    assert picked is not None and picked["payload"]["offer_key"] == "mvp_sprint"
    assert offers.run(rc(), router=FakeRouter({}))["selected"] == 0


def test_a_bad_pick_gets_one_rewrite(startup_db: str) -> None:
    seed(startup_db, with_offer=False)

    def bad_then_good(inputs: dict[str, Any]) -> OfferPick:
        if inputs["feedback"]:
            return good_pick(inputs)
        return good_pick(inputs).model_copy(update={"offer_key": "website_redo"})

    router = FakeRouter({"pick_offer": bad_then_good})
    stats = offers.run(rc(), router=router)
    assert stats["stored"] == 1 and stats["rewrites"] == 1
    assert "not one of the listed offer keys" in router.calls[1].inputs["feedback"][0]


def test_two_bad_picks_store_nothing_and_the_lead_waits(startup_db: str) -> None:
    ids = seed(startup_db, with_offer=False)

    def invented(inputs: dict[str, Any]) -> OfferPick:
        return good_pick(inputs).model_copy(update={"why_now": "They raised $2M from Sequoia."})

    for _ in range(2):
        stats = offers.run(rc(), router=FakeRouter({"pick_offer": invented}))
        assert stats["failed"] == 1
    assert db.scalar("select count(*) from public.lead_offers where lead_id = %s", [ids["lead"]]) == 0
    failed = db.fetch_all(
        "select payload from public.activities where lead_id = %s and payload ->> 'kind' = 'offer_failed'",
        [ids["lead"]],
    )
    assert len(failed) == 2 and any("Sequoia" in i for i in failed[0]["payload"]["issues"])
    assert offers.run(rc(), router=FakeRouter({}))["selected"] == 0


def test_offers_survive_a_down_ai(startup_db: str) -> None:
    seed(startup_db, with_offer=False)
    stats = offers.run(rc(), router=FakeRouter({"pick_offer": [AllProvidersDown("down")]}))
    assert stats["ai.failed"] == 1 and "stored" not in stats


# ---------------------------------------------------------------------------
# The sequence and its thread (contract 4.6)
# ---------------------------------------------------------------------------


def test_a_sequence_opens_one_thread_with_four_drafts(startup_db: str) -> None:
    ids = seed(startup_db)
    router = ok_router()
    stats = message.run(rc(), router=router)
    assert stats["sequence.stored"] == 1 and stats["sequence.threads"] == 1, stats
    assert router.tasks() == ["write_email_sequence", "check_message"]
    assert router.calls[1].exclude_model == "gemini-3-flash" and router.calls[1].inputs["kind"] == "email"
    inputs = router.calls[0].inputs
    assert inputs["greeting"] == "Hi Maya," and inputs["offer"] == "MVP sprint"
    assert inputs["why_now"].startswith("Brightcart raised") and "@" not in str(inputs)
    t = thread_of(ids["lead"])
    assert t is not None
    assert (t["status"], t["mode"], t["to_email"], t["to_domain"]) == ("open", "review", ids["email"], ids["domain"])
    assert str(t["contact_id"]) == ids["contact"] and t["mailbox_id"] is None
    steps = steps_of(str(t["id"]))
    assert [s["step"] for s in steps] == [0, 3, 7, 12]
    assert all(s["status"] == "draft" and s["scheduled_for"] is None for s in steps)
    assert steps[0]["subject"] == "your pre-seed round" and all(s["subject"] is None for s in steps[1:])
    assert "{plan_link}" in steps[1]["body"] and "{case_study}" in steps[2]["body"]
    assert "{" not in steps[0]["body"] and "http" not in steps[0]["body"]
    assert not any("Team Nument" in s["body"] or "unsubscribe" in s["body"].lower() for s in steps)
    lead = lead_row(ids["lead"])
    assert lead["message"] == steps[0]["body"] and lead["email_subject"] == "your pre-seed round"
    assert float(lead["message_check_score"]) == 9 and lead["email_body"] is None
    assert lead["message_model"] == "gemini:gemini-3-flash#write_email_sequence.v1"
    stored = db.fetch_one(
        "select payload from public.activities where lead_id = %s and payload ->> 'kind' = 'message_stored'",
        [ids["lead"]],
    )
    assert stored is not None and stored["payload"]["thread_id"] == str(t["id"])
    assert sorted(stored["payload"]["cited_ids"]) == sorted([ids["signal"], ids["team"]])
    again = message.run(rc(), router=FakeRouter({}))
    assert again.get("sequence.selected", 0) == 0
    assert db.scalar("select count(*) from public.email_threads where lead_id = %s", [ids["lead"]]) == 1


def test_no_thread_and_no_ai_without_a_sendable_address(startup_db: str) -> None:
    ids = seed(startup_db, status="unknown")
    router = FakeRouter({})
    stats = message.run(rc(), router=router)
    assert stats["sequence.skipped.no_sendable_email"] == 1 and router.calls == []
    assert thread_of(ids["lead"]) is None and lead_row(ids["lead"])["message"] is None


def test_no_sequence_without_an_offer(startup_db: str) -> None:
    ids = seed(startup_db, with_offer=False)
    router = FakeRouter({})
    assert message.run(rc(), router=router)["sequence.skipped.no_offer"] == 1 and router.calls == []
    assert thread_of(ids["lead"]) is None


def test_a_guessed_address_is_never_used_in_a_published_only_country(startup_db: str) -> None:
    guessed = seed(startup_db, segment="firms-ca", origin="guess")
    router = FakeRouter({})
    stats = message.run(rc(), router=router)
    assert stats["sequence.skipped.guess_in_published_only_country"] == 1 and router.calls == []
    assert thread_of(guessed["lead"]) is None
    with pf.connect(startup_db) as conn:
        conn.execute("update public.contacts set email_origin = 'published' where id = %s", [guessed["contact"]])
    assert message.run(rc(), router=ok_router())["sequence.threads"] == 1


def test_suppressed_addresses_and_domains_get_no_thread(startup_db: str) -> None:
    by_email = seed(startup_db)
    by_domain = seed(startup_db, segment="firms-ca")
    with pf.connect(startup_db) as conn:
        conn.execute("insert into public.suppression (email, reason) values (%s, 'e4_test')", [by_email["email"]])
        conn.execute(
            "insert into public.suppression (web_domain, reason) values (%s, 'e4_test')", [by_domain["domain"]]
        )
    router = FakeRouter({})
    stats = message.run(rc(), router=router)
    assert stats["sequence.skipped.no_sendable_email"] == 1 and stats["sequence.skipped.suppressed_domain"] == 1
    assert router.calls == [] and thread_of(by_email["lead"]) is None and thread_of(by_domain["lead"]) is None


def test_one_open_thread_per_domain_and_the_90_day_cooldown(startup_db: str) -> None:
    first = seed(startup_db)
    twin = seed(startup_db, segment="firms-ca", domain=first["domain"])  # the same company found twice
    stats = message.run(rc(), router=ok_router())
    assert stats["sequence.threads"] == 1 and stats["sequence.skipped.domain_open_thread"] == 1
    made = [x for x in (first, twin) if thread_of(x["lead"]) is not None]
    assert len(made) == 1
    t = thread_of(made[0]["lead"])
    assert t is not None
    with pf.connect(startup_db) as conn:  # step 0 went out ten days ago, then the founder said no
        conn.execute(
            "update public.email_messages set status = 'sent', sent_at = now() - interval '10 days' "
            "where thread_id = %s and step = 0",
            [t["id"]],
        )
        conn.execute("update public.email_threads set status = 'done' where id = %s", [t["id"]])
    other = twin if made[0] is first else first
    stats = message.run(rc(), router=ok_router())
    assert stats["sequence.skipped.domain_cooldown"] == 1 and thread_of(other["lead"]) is None


def test_claim_problems_are_never_stored_and_the_lead_waits(startup_db: str) -> None:
    ids = seed(startup_db)

    def invented(inputs: dict[str, Any]) -> EmailSequence:
        return sequence_answer(inputs, extra=" led by Sequoia")

    for _ in range(2):
        router = FakeRouter({"write_email_sequence": invented, "check_message": []})
        stats = message.run(rc(), router=router)
        assert stats["sequence.flagged.not_stored"] == 1 and router.tasks() == ["write_email_sequence"] * 2
    assert thread_of(ids["lead"]) is None and lead_row(ids["lead"])["message"] is None
    flag = db.fetch_one(
        "select payload from public.activities where lead_id = %s and type = 'message_flagged'", [ids["lead"]]
    )
    assert flag is not None and flag["payload"]["stored"] is False
    assert any("Sequoia" in i for i in flag["payload"]["issues"])
    assert message.run(rc(), router=FakeRouter({}))["sequence.skipped.failed_recently"] == 1


def test_a_low_critic_score_gets_one_rewrite_then_a_flag(startup_db: str) -> None:
    ids = seed(startup_db)
    scores = [MessageCheck(score=6, issues=["day 0: too generic"]), MessageCheck(score=8, issues=["still generic"])]
    router = FakeRouter({"write_email_sequence": sequence_answer, "check_message": scores})
    stats = message.run(rc(), router=router)
    assert router.tasks() == ["write_email_sequence", "check_message"] * 2
    assert router.calls[2].inputs["feedback"] == ["day 0: too generic"]
    assert stats["sequence.flagged.needs_edit"] == 1 and stats["sequence.threads"] == 1
    assert float(lead_row(ids["lead"])["message_check_score"]) == 8
    flag = db.fetch_one(
        "select payload, at from public.activities where lead_id = %s and type = 'message_flagged'", [ids["lead"]]
    )
    t = thread_of(ids["lead"])
    assert flag is not None and t is not None and "reviewer score 8 of 10" in flag["payload"]["issues"]
    created = db.scalar("select max(created_at) from public.email_messages where thread_id = %s", [t["id"]])
    assert flag["at"] > created  # newer than the drafts, so the auto-send bar holds them back


def test_regenerate_rewrites_unsent_drafts_in_place(startup_db: str) -> None:
    ids = seed(startup_db)
    message.run(rc(), router=ok_router())
    t = thread_of(ids["lead"])
    assert t is not None
    with pf.connect(startup_db) as conn:
        conn.execute("update public.email_messages set status = 'review' where thread_id = %s and step = 0", [t["id"]])
        conn.execute(
            "update public.leads set regen_requested_at = now() + interval '1 second' where id = %s", [ids["lead"]]
        )
    router = FakeRouter(
        {
            "write_email_sequence": lambda i: sequence_answer(i, opener="saw the news about"),
            "check_message": [MessageCheck(score=10, issues=[])],
        }
    )
    stats = message.run(rc(), router=router)
    assert stats["sequence.rewritten"] == 1, stats
    assert db.scalar("select count(*) from public.email_threads where lead_id = %s", [ids["lead"]]) == 1
    steps = steps_of(str(t["id"]))
    assert "saw the news about" in steps[0]["body"] and all(s["status"] == "draft" for s in steps)
    lead = lead_row(ids["lead"])
    assert lead["regen_requested_at"] is None and "saw the news about" in lead["message"]


def test_nothing_is_rewritten_once_day_0_went_out(startup_db: str) -> None:
    ids = seed(startup_db)
    message.run(rc(), router=ok_router())
    t = thread_of(ids["lead"])
    assert t is not None
    before = steps_of(str(t["id"]))
    with pf.connect(startup_db) as conn:
        conn.execute(
            "update public.email_messages set status = 'sent', sent_at = now() where thread_id = %s and step = 0",
            [t["id"]],
        )
        conn.execute("update public.leads set regen_requested_at = now() where id = %s", [ids["lead"]])
    router = FakeRouter({})
    assert message.run(rc(), router=router)["sequence.skipped.thread_in_progress"] == 1 and router.calls == []
    assert [s["body"] for s in steps_of(str(t["id"]))] == [s["body"] for s in before]


# ---------------------------------------------------------------------------
# Plan pages and links (contract 4.7)
# ---------------------------------------------------------------------------


def _sent_thread(dsn: str, *, due_in: timedelta = timedelta(hours=2), **seed_kw: Any) -> dict[str, Any]:
    """A lead whose day-0 email went out three days ago (what the sender does), follow-ups queued."""
    ids = seed(dsn, **seed_kw)
    message.run(rc(), router=ok_router())
    t = thread_of(ids["lead"])
    assert t is not None
    with pf.connect(dsn) as conn:
        conn.execute(
            "update public.email_messages set status = 'sent', sent_at = now() - interval '3 days' "
            "where thread_id = %s and step = 0",
            [t["id"]],
        )
        conn.execute(
            "update public.email_messages set status = 'queued', scheduled_for = now() + %s "
            "where thread_id = %s and step = 3",
            [due_in, t["id"]],
        )
        conn.execute(
            "update public.email_messages set status = 'queued', scheduled_for = now() + interval '4 days' "
            "where thread_id = %s and step = 7",
            [t["id"]],
        )
        conn.execute("update public.settings set value = '\"manual\"'::jsonb where key = 'outreach.mode'")
    return {**ids, "thread": str(t["id"])}


def test_plans_do_nothing_while_outreach_is_off(startup_db: str) -> None:
    router = FakeRouter({})
    assert plans.run(rc(), router=router) == {"skipped": "outreach off"} and router.calls == []


def test_a_plan_is_written_after_day_0_and_both_links_are_filled(startup_db: str) -> None:
    ids = _sent_thread(startup_db)
    with pf.connect(startup_db) as conn:
        conn.execute(
            "insert into public.case_studies (slug, title, offer_key, summary, published) "
            "values (%s, 'A grocer MVP', 'mvp_sprint', 'Shipped in five weeks.', true)",
            [SLUG],
        )
    day0 = steps_of(ids["thread"])[0]["body"]
    router = FakeRouter({"write_plan": plan_answer})
    stats = plans.run(rc(), router=router)
    assert stats["plans.written"] == 1 and stats["links.plan"] == 1 and stats["links.case_study"] == 1, stats
    assert "@" not in str(router.calls[0].inputs) and router.calls[0].inputs["offer"] == "MVP sprint"
    page = db.fetch_one("select * from public.plan_pages where lead_id = %s", [ids["lead"]])
    assert page is not None and len(page["token"]) == 22 and (page["kind"], page["status"]) == ("plan", "live")
    content = PlanContent.model_validate(page["content"])  # the page reads it as data, never HTML
    assert content.typical_range == "Projects like this usually run $3,000 to $12,000, paid in milestones."
    steps = steps_of(ids["thread"])
    assert steps[0]["body"] == day0
    assert f"https://lead.nument.in/p/{page['token']}" in steps[1]["body"] and "{plan_link}" not in steps[1]["body"]
    assert f"https://lead.nument.in/c/{SLUG}" in steps[2]["body"] and "{case_study}" not in steps[2]["body"]
    again = FakeRouter({})
    assert plans.run(rc(), router=again)["plans.due"] == 0 and again.calls == []
    assert db.scalar("select count(*) from public.plan_pages where lead_id = %s", [ids["lead"]]) == 1


def test_no_plan_before_day_0_is_sent_and_no_link_in_a_draft(startup_db: str) -> None:
    ids = seed(startup_db)
    message.run(rc(), router=ok_router())
    with pf.connect(startup_db) as conn:
        conn.execute("update public.settings set value = '\"manual\"'::jsonb where key = 'outreach.mode'")
    router = FakeRouter({})
    stats = plans.run(rc(), router=router)
    assert stats["plans.due"] == 0 and router.calls == [] and "links.case_study" not in stats
    t = thread_of(ids["lead"])
    assert t is not None and "{case_study}" in steps_of(str(t["id"]))[2]["body"]


def test_the_case_study_link_falls_back_to_nument_in(startup_db: str) -> None:
    ids = _sent_thread(startup_db, due_in=timedelta(days=2))  # day 3 not due yet: no plan, links only
    router = FakeRouter({})
    stats = plans.run(rc(), router=router)
    assert stats["plans.due"] == 0 and router.calls == []
    assert stats["links.case_study_fallback"] == 1
    steps = steps_of(ids["thread"])
    assert "https://nument.in" in steps[2]["body"] and "{plan_link}" in steps[1]["body"]


def test_a_bad_plan_is_never_published_and_waits_before_a_retry(startup_db: str) -> None:
    ids = _sent_thread(startup_db)
    router = FakeRouter({"write_plan": lambda i: plan_answer(i, headline="<b>Big</b> plan at https://x.example")})
    stats = plans.run(rc(), router=router)
    assert stats["plans.failed"] == 1 and stats["plans.rewrites"] == 1 and router.tasks() == ["write_plan"] * 2
    assert db.scalar("select count(*) from public.plan_pages where lead_id = %s", [ids["lead"]]) == 0
    assert "{plan_link}" in steps_of(ids["thread"])[1]["body"]
    later = FakeRouter({})
    assert plans.run(rc(), router=later)["plans.skipped.retry_later"] == 1 and later.calls == []


def test_a_founder_who_asks_for_the_plan_gets_one(startup_db: str) -> None:
    ids = _sent_thread(startup_db, due_in=timedelta(days=2))
    with pf.connect(startup_db) as conn:  # the reply side stopped the thread and sorted the reply
        conn.execute(
            "update public.email_threads set status = 'stopped', stop_reason = 'reply' where id = %s", [ids["thread"]]
        )
        conn.execute(
            "update public.email_messages set status = 'cancelled' where thread_id = %s and step > 0", [ids["thread"]]
        )
        conn.execute(
            "insert into public.email_messages (thread_id, direction, body, status, classification) "
            "values (%s, 'in', 'Sure, send the plan over.', 'received', 'send_plan')",
            [ids["thread"]],
        )
    stats = plans.run(rc(), router=FakeRouter({"write_plan": plan_answer}))
    assert stats["plans.written"] == 1 and "links.plan" not in stats  # cancelled steps are never touched
    assert db.scalar("select count(*) from public.plan_pages where lead_id = %s", [ids["lead"]]) == 1
