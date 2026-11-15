"""The replies phase (contract 4.6): classification, what each category does, drafts, links, times and alerts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from nument_engine import db
from nument_engine.models import ReplyClassification, ReplyDraft
from nument_engine.ops import emails, notify
from nument_engine.outreach import inbox, replies
from nument_engine.outreach.replies import BOOKING_URL, DraftContext

from .outreach_world import World, add_offer, add_plan_page, make_world, rc_for
from .pipeline_fakes import AllProvidersDown, BudgetExceeded, FakeRouter

NY = ZoneInfo("America/New_York")
MONDAY = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)  # 07:00 in New York, 17:30 in India


# ---------------------------------------------------------------------------
# Links, zones and times (no database)
# ---------------------------------------------------------------------------


def test_booking_link_is_prefilled_and_url_encoded() -> None:
    link = replies.booking_link(BOOKING_URL, email="Maya@Brightcart.example", name="Maya Chen")
    assert link == f"{BOOKING_URL}?name=Maya%20Chen&email=maya%40brightcart.example"
    assert replies.booking_link(BOOKING_URL, email=None, name=None) == BOOKING_URL
    assert (
        replies.booking_link(f"{BOOKING_URL}?x=1", email="a@b.example", name="")
        == f"{BOOKING_URL}?x=1&email=a%40b.example"
    )


@pytest.mark.parametrize(
    ("country", "city", "zone"),
    [
        ("us", "San Francisco", "America/Los_Angeles"),
        ("us", "Austin", "America/Chicago"),
        ("us", None, "America/New_York"),
        ("ca", "Vancouver", "America/Vancouver"),
        ("au", "Perth", "Australia/Perth"),
        ("au", "", "Australia/Sydney"),
        ("gb", "Leeds", "Europe/London"),
        ("in", "Pune", "Asia/Kolkata"),
        (None, None, "UTC"),
    ],
)
def test_recipient_zone(country: str | None, city: str | None, zone: str) -> None:
    assert replies.recipient_zone(country, city).key == zone


def test_zone_labels() -> None:
    assert replies.zone_label(ZoneInfo("America/New_York")) == "New York time"
    assert replies.zone_label(ZoneInfo("Asia/Kolkata")) == "India time"
    assert replies.zone_label(ZoneInfo("America/Sao_Paulo")) == "Sao Paulo time"


def _times(zone: str, now: datetime = MONDAY) -> list[str]:
    z = ZoneInfo(zone)
    return [replies.time_text(t, z) for t in replies.suggest_times(now, z, replies.call_hours())]


def test_three_times_in_their_zone_inside_both_working_days() -> None:
    # New York 09:00 is 19:30 in India: inside the founder's evening window.
    assert _times("America/New_York") == ["Tue 17 Nov, 9:00 am", "Wed 18 Nov, 9:00 am", "Thu 19 Nov, 9:00 am"]
    assert _times("Europe/London") == ["Tue 17 Nov, 12:30 pm", "Wed 18 Nov, 12:30 pm", "Thu 19 Nov, 12:30 pm"]
    assert _times("America/Los_Angeles") == ["Tue 17 Nov, 9:00 am", "Wed 18 Nov, 9:00 am", "Thu 19 Nov, 9:00 am"]
    # Sydney and Singapore get the founder's morning window instead.
    assert _times("Australia/Sydney") == ["Wed 18 Nov, 1:30 pm", "Thu 19 Nov, 1:30 pm", "Fri 20 Nov, 1:30 pm"]
    assert _times("Asia/Singapore") == ["Wed 18 Nov, 10:30 am", "Thu 19 Nov, 10:30 am", "Fri 20 Nov, 10:30 am"]


def test_times_respect_the_lead_time_weekends_and_both_windows() -> None:
    friday = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    hours = replies.call_hours()
    picks = replies.suggest_times(friday, NY, hours)
    assert len(picks) == 3
    for t in picks:
        local, india = t.astimezone(NY), t.astimezone(ZoneInfo("Asia/Kolkata"))
        assert t >= friday + timedelta(hours=18)
        assert local.weekday() < 5 and time(9) <= local.time() and (local + timedelta(minutes=30)).time() <= time(18)
        assert hours.open_at(t, timedelta(minutes=30)) and india.weekday() < 5
    assert len({t.astimezone(NY).date() for t in picks}) == 3


def test_call_hours_setting_falls_back_when_malformed() -> None:
    default = replies.call_hours()
    assert replies.call_hours({"zone": "Not/AZone", "windows": [["25:00", "x"]], "days": ["mon"]}) == default
    custom = replies.call_hours({"zone": "Europe/London", "days": [5, 6], "windows": [["10:00", "12:00"]]})
    assert custom.zone.key == "Europe/London" and custom.days == frozenset({5, 6})
    assert custom.windows == ((time(10), time(12)),)
    overnight = replies.call_hours({"zone": "UTC", "days": [0, 1, 2, 3, 4], "windows": [["22:00", "01:00"]]})
    assert overnight.open_at(datetime(2026, 11, 16, 23, 0, tzinfo=UTC), timedelta(minutes=30))
    assert not overnight.open_at(datetime(2026, 11, 16, 12, 0, tzinfo=UTC), timedelta(minutes=30))


@pytest.mark.parametrize(
    ("name", "first"),
    [("Maya Chen", "Maya"), ("maya", "Maya"), ("MAYA CHEN", "Maya"), ("maya@x.example", ""), ("J", ""), (None, "")],
)
def test_first_name(name: str | None, first: str) -> None:
    assert replies.first_name(name) == first


@pytest.mark.parametrize(
    ("text", "opt_out"),
    [
        ("Please remove me from your mailing list.", True),
        ("Unsubscribe", True),
        ("Take me off this list please", True),
        ("Stop emailing me.", True),
        ("Please don't contact us again.", True),
        ("Not interested right now, maybe after our raise.", False),
        ("Don't email my personal address, use maya@brightcart.example instead.", False),
        ("Can you send the plan?", False),
        ("Unsubscribe " + "and also here is a very long story about our product. " * 20, False),
        ("Thanks!\n\nOn Mon, Nument wrote:\n> Not relevant? Unsubscribe here", False),
    ],
)
def test_opt_out_rule(text: str, opt_out: bool) -> None:
    assert replies.opt_out_rule(text) is opt_out


def test_classification_keeps_only_what_the_reply_says() -> None:
    raw = ReplyClassification(
        category="wrong_person",
        confidence=1.4 / 1.4,
        summary="Points to Leo.",
        return_date="next week",
        referral_name="Leo Park",
        referral_email="leo@quillpad.example",
    )
    kept = replies.tidy_classification(raw, "Talk to Leo Park, leo@quillpad.example", set())
    assert (kept.referral_name, kept.referral_email, kept.return_date) == ("Leo Park", "leo@quillpad.example", None)
    invented = replies.tidy_classification(raw, "Talk to our CTO.", set())
    assert invented.referral_name is None and invented.referral_email is None
    ooo = ReplyClassification(category="out_of_office", confidence=0.9, summary="Away.", return_date="2026-11-30")
    assert replies.tidy_classification(ooo, "Back on 30 Nov", set()).return_date == "2026-11-30"


def _ctx(**over: Any) -> DraftContext:
    values: dict[str, Any] = {
        "category": "interested",
        "first": "Maya",
        "company": "Brightcart",
        "link": replies.booking_link(BOOKING_URL, email="maya@brightcart.example", name="Maya Chen"),
        "base_link": BOOKING_URL,
        "times": ["Tue 17 Nov, 9:00 am", "Wed 18 Nov, 9:00 am", "Thu 19 Nov, 9:00 am"],
        "zone_label": "New York time",
    }
    values.update(over)
    return DraftContext(**values)


def test_finish_adds_the_link_times_and_one_sign_off() -> None:
    ctx = _ctx()
    body = replies.finish("Hi Maya,\n\nGreat to hear from you — happy to help.\n\nBest,\nTeam Nument", ctx)
    assert "—" not in body and "you, happy to help" in body
    assert ctx.link in body and "Tue 17 Nov, 9:00 am, Wed 18 Nov, 9:00 am or Thu 19 Nov, 9:00 am" in body
    assert body.endswith("\n\nTeam Nument") and body.count("Team Nument") == 1 and "Best," not in body
    bare = replies.finish(f"Hi Maya,\n\nBook here: {BOOKING_URL}\nTimes: Tue 17 Nov, 9:00 am", ctx)
    assert f"Book here: {ctx.link}" in bare and bare.count(BOOKING_URL) == 1
    assert "A few times" not in bare  # one of the times is already written


def test_draft_problems() -> None:
    ctx = _ctx()
    assert replies.draft_problems(replies.finish("Hi Maya,\n\nThanks.", ctx), ctx) == []
    word = ctx.private_words[0]
    assert word and word not in ("nument", "numentai")
    named = replies.finish(f"Hi Maya,\n\nThanks.\n\nCheers, {word.title()}", ctx)
    assert any("never name a person" in p for p in replies.draft_problems(named, ctx))
    linked = replies.finish("Hi Maya, see https://evil.example/x and {case_study}", ctx)
    problems = replies.draft_problems(linked, ctx)
    assert any("evil.example" in p for p in problems) and any("{case_study}" in p for p in problems)
    pending = _ctx(category="send_plan", plan_pending=True)
    assert replies.draft_problems(replies.finish("Hi Maya, here it is: {plan_link}", pending), pending) == []


def test_fallbacks_are_safe_for_every_category() -> None:
    for category in replies.DRAFT_CATEGORIES:
        link = category in ("interested", "send_plan", "question")
        ctx = _ctx(category=category, link=_ctx().link if link else "", times=_ctx().times if link else [])
        body = replies.finish(replies.fallback(ctx), ctx)
        assert body.startswith("Hi Maya,") and body.endswith("Team Nument")
        assert replies.draft_problems(body, ctx) == [], category
        assert (bool(ctx.link) and ctx.link in body) is link
    referral = _ctx(category="wrong_person", link="", times=[], referral_name="Leo Park")
    assert "Leo Park" in replies.fallback(referral)


def test_templates_fill_or_refuse() -> None:
    ctx = _ctx(category="send_plan", plan_link="https://lead.nument.in/p/abc")
    text = "Hi {first_name}, here's the plan for {company}: {plan_link}\n\nTeam Nument"
    assert replies.from_template(text, ctx) == (
        "Hi Maya, here's the plan for Brightcart: https://lead.nument.in/p/abc\n\nTeam Nument"
    )
    assert replies.from_template(text, _ctx(category="send_plan")) is None  # no plan page yet
    assert replies.from_template("Hi {nickname}", ctx) is None


# ---------------------------------------------------------------------------
# The phase (throwaway database, fake router)
# ---------------------------------------------------------------------------


@pytest.fixture
def outreach_on(engine_db: str) -> Iterator[str]:
    keys = ("outreach.mode", "outreach.auto_replies", "outreach.reply_templates")
    before = {k: db.get_setting(k) for k in keys}
    db.set_setting("outreach.mode", "manual")
    yield engine_db
    for key, value in before.items():
        if value is None:
            db.execute("delete from public.settings where key = %s", [key])
        else:
            db.set_setting(key, value)


@pytest.fixture
def sent_alerts(monkeypatch: pytest.MonkeyPatch) -> list[notify.Email]:
    sent: list[notify.Email] = []

    def deliver(kind: str, build: Callable[[bool], notify.Email]) -> int:
        assert kind == "alerts"
        sent.append(build(True))
        return 1

    monkeypatch.setattr(notify, "email_configured", lambda: True)
    monkeypatch.setattr(emails, "deliver", deliver)
    return sent


def _receive(world: World, *bodies: str, **kw: Any) -> None:
    box = world.box()
    box.incoming += [world.reply(b, n=i + 1, **kw) for i, b in enumerate(bodies)]
    inbox.run(rc_for(), mailbox=box)


def _classified(category: str, confidence: float = 0.93, **over: Any) -> ReplyClassification:
    return ReplyClassification(category=category, confidence=confidence, summary=f"A {category} reply.", **over)


def _drafter(seen: list[dict[str, Any]], body: str | None = None) -> Callable[[dict[str, Any]], ReplyDraft]:
    def write(inputs: dict[str, Any]) -> ReplyDraft:
        seen.append(inputs)
        times = "; ".join(inputs.get("suggested_times") or [])
        text = body or (
            f"Hi {inputs['first_name']},\n\nThanks, glad this is useful. Would any of these work: {times}? "
            f"Or grab a slot here: {inputs['booking_link']}\n\nTeam Nument"
        )
        return ReplyDraft(body=text)

    return write


def _run(router: Any = None, **kw: Any) -> dict[str, Any]:
    return replies.run(rc_for(), router=router, now=datetime.now(UTC), **kw)


def _last_activity(world: World, kind: str) -> dict[str, Any]:
    rows = [a for a in world.activities("ai_output") if a["payload"].get("kind") == kind]
    assert rows, kind
    return dict(rows[-1]["payload"])


def test_an_interested_reply_gets_a_draft_with_link_and_times_and_an_alert(
    outreach_on: str, sent_alerts: list[notify.Email]
) -> None:
    world = make_world(outreach_on, city="San Francisco")
    add_offer(world)
    _receive(world, "This sounds great. Can we talk this week?")
    seen: list[dict[str, Any]] = []
    router = FakeRouter({"classify_reply": [_classified("interested")], "draft_reply": _drafter(seen)})
    stats = _run(router)
    assert stats["classified.interested"] == 1 and stats["drafted.review"] == 1 and stats["alert.sent"] == 1
    [msg] = world.incoming()
    assert msg["classification"] == "interested" and float(msg["classification_confidence"]) == 0.93
    assert world.lead()["stage"] == "talking"
    [draft] = world.replies()
    assert (draft["status"], draft["step"], draft["subject"]) == ("review", None, None)
    assert draft["body"] == msg["suggested_reply"] and draft["body"].endswith("Team Nument")
    link = replies.booking_link(BOOKING_URL, email=world.email, name="Maya Chen")
    assert link in draft["body"] and "%40" in link
    inputs = seen[0]
    assert inputs["booking_link"] == link and inputs["time_zone"] == "Los Angeles time"
    assert len(inputs["suggested_times"]) == 3 and all(t in draft["body"] for t in inputs["suggested_times"])
    assert inputs["offer"] == "No-code to real app" and inputs["typical_range"] == "usually $4,000 to $15,000"
    assert router.tasks() == ["classify_reply", "draft_reply"]
    [alert] = sent_alerts
    assert alert.subject == "Maya at Brightcart replied: interested"
    assert "Can we talk this week?" in alert.text and draft["body"] in alert.text
    assert f"/leads/{world.lead_id}" in alert.html and "Review and send" in alert.html
    assert _last_activity(world, "reply_alert")["sent"] == 1


def test_send_plan_uses_the_plan_page_or_waits_for_it(outreach_on: str, sent_alerts: list[notify.Email]) -> None:
    world = make_world(outreach_on)
    _receive(world, "Yes, send the plan please.")
    seen: list[dict[str, Any]] = []
    body = "Hi Maya,\n\nHere's the 1-page plan: {plan_link}\n\nTeam Nument"
    router = FakeRouter({"classify_reply": [_classified("send_plan")], "draft_reply": _drafter(seen, body)})
    stats = _run(router)
    assert stats["drafted.review"] == 1 and seen[0]["plan_link"] == "{plan_link}"
    [draft] = world.replies()
    assert "{plan_link}" in draft["body"]  # the sender refuses placeholders, so this waits for the plan page
    assert _last_activity(world, "reply_drafted")["plan_pending"] is True
    token = add_plan_page(world)
    assert _run(FakeRouter({}))["plan_links_filled"] == 1
    [draft] = world.replies()
    assert "{plan_link}" not in draft["body"] and f"/p/{token}" in draft["body"]
    assert len(sent_alerts) == 1 and sent_alerts[0].subject.endswith("replied: wants the plan")


def test_send_plan_with_a_live_plan_page(outreach_on: str, sent_alerts: list[notify.Email]) -> None:
    world = make_world(outreach_on)
    token = add_plan_page(world)
    _receive(world, "Sure, send it over.")
    seen: list[dict[str, Any]] = []
    router = FakeRouter({"classify_reply": [_classified("send_plan")], "draft_reply": _drafter(seen)})
    _run(router)
    assert seen[0]["plan_link"].endswith(f"/p/{token}")
    [draft] = world.replies()
    assert f"/p/{token}" in draft["body"]  # the code adds it when the writer forgot


def test_an_unsubscribe_reply_is_honoured_and_closes_the_lead(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Not for us, thanks. Please don't follow up.")
    router = FakeRouter({"classify_reply": [_classified("unsubscribe", 0.6)]})
    stats = _run(router)
    assert stats["classified.unsubscribe"] == 1 and stats["unsubscribed"] == 1
    thread = world.thread()
    assert (thread["status"], thread["stop_reason"]) == ("done", "unsubscribe")
    lead = world.lead()
    assert (lead["stage"], lead["lost_reason"]) == ("lost", "other")
    assert world.contact()["do_not_contact"] is True and world.replies() == []
    assert world.all("select 1 from public.suppression where lower(email) = %s", [world.email]) != []
    moves = {(a["payload"]["from"], a["payload"]["to"]) for a in world.activities("stage_change")}
    assert {("contacted", "talking"), ("talking", "lost")} <= moves  # it counts as a reply, then closes


def test_clear_opt_out_words_need_no_ai(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Please remove me from your mailing list.")
    stats = _run(router=None)  # no router in tests: the rule decides alone
    assert stats["rule.unsubscribe"] == 1 and stats["unsubscribed"] == 1
    assert world.thread()["status"] == "done"
    assert _last_activity(world, "reply_classified")["model"] == "rule"


def test_out_of_office_puts_the_sequence_back_after_the_return_date(outreach_on: str) -> None:
    world = make_world(outreach_on)
    before = {
        r["step"]: r["scheduled_for"]
        for r in world.all(
            "select step, scheduled_for from public.email_messages where thread_id = %s", [world.thread_id]
        )
    }
    _receive(world, "I'm out of the office until 30 November with limited access to email.")
    assert world.thread()["status"] == "stopped"
    back = (datetime.now(UTC) + timedelta(days=14)).date().isoformat()
    router = FakeRouter({"classify_reply": [_classified("out_of_office", 0.97, return_date=back)]})
    stats = _run(router)
    assert stats["classified.out_of_office"] == 1 and stats["resumed"] == 1
    thread = world.thread()
    until = datetime.combine(date.fromisoformat(back) + timedelta(days=1), time(9), tzinfo=NY)
    assert (thread["status"], thread["stop_reason"]) == ("open", None)
    assert thread["paused_until"] == until
    assert world.statuses() == {0: "sent", 3: "queued", 7: "queued", 12: "review"}
    after = {
        r["step"]: r["scheduled_for"]
        for r in world.all(
            "select step, scheduled_for from public.email_messages where thread_id = %s", [world.thread_id]
        )
    }
    assert after[3] == until and after[7] - after[3] == before[7] - before[3]  # the spacing is kept
    assert world.replies() == [] and world.lead()["stage"] == "contacted"


def test_an_auto_reply_does_not_reopen_when_a_person_also_answered(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Out of office until Monday.", "Back now. Yes, let's talk.")
    seen: list[dict[str, Any]] = []
    router = FakeRouter(
        {
            "classify_reply": [_classified("out_of_office", 0.95), _classified("interested")],
            "draft_reply": _drafter(seen),
        }
    )
    stats = _run(router)
    assert stats["classified.out_of_office"] == 1 and "resumed" not in stats
    assert world.thread()["status"] == "stopped"
    assert world.statuses()[3] == "cancelled"


def test_an_unsure_auto_reply_leaves_the_thread_stopped(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Thanks for your note.")
    _run(FakeRouter({"classify_reply": [_classified("out_of_office", 0.6)]}))
    assert world.thread()["status"] == "stopped"


def test_not_now_closes_for_sixty_days_with_a_polite_draft(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Not the right time, we're heads down until Q2. Maybe reach out then.")
    seen: list[dict[str, Any]] = []
    body = "Hi Maya,\n\nNo problem at all. We'll check back in a couple of months.\n\nTeam Nument"
    _run(FakeRouter({"classify_reply": [_classified("not_now", 0.9)], "draft_reply": _drafter(seen, body)}))
    lead = world.lead()
    back = (datetime.now(UTC) + timedelta(days=60)).date()
    assert (lead["stage"], lead["lost_reason"], lead["due_at"]) == ("not_now", "no_need_now", back)
    assert world.thread()["paused_until"].date() == back and world.thread()["status"] == "stopped"
    [draft] = world.replies()
    assert draft["status"] == "review" and BOOKING_URL not in draft["body"]
    assert seen[0]["booking_link"] == "" and seen[0]["suggested_times"] == []


def test_wrong_person_with_a_referral(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "I'm not the right person. Please talk to Leo Park, our CTO: leo@quillpad.example")
    seen: list[dict[str, Any]] = []
    out = _classified("wrong_person", referral_name="Leo Park", referral_email="leo@quillpad.example")
    body = "Hi Maya,\n\nThanks for pointing us to Leo. We'll reach out to him directly.\n\nTeam Nument"
    _run(FakeRouter({"classify_reply": [out], "draft_reply": _drafter(seen, body)}))
    meta = _last_activity(world, "reply_classified")
    assert (meta["referral_name"], meta["referral_email"]) == ("Leo Park", "leo@quillpad.example")
    assert seen[0]["referral_email"] == "leo@quillpad.example" and seen[0]["booking_link"] == ""
    assert world.lead()["stage"] == "talking" and world.replies()[0]["status"] == "review"


def test_a_draft_that_names_a_person_is_rewritten_then_replaced(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "How much would something like this cost?")
    word = DraftContext("question", "", "", "", BOOKING_URL).private_words[0].title()
    bad = ReplyDraft(body=f"Hi Maya,\n\nIt depends on scope.\n\nCheers, {word}")
    router = FakeRouter({"classify_reply": [_classified("question")], "draft_reply": [bad, bad]})
    stats = _run(router)
    assert stats["draft.rewrite.1"] == 1 and stats["draft.rewrite.2"] == 1
    assert router.tasks() == ["classify_reply", "draft_reply", "draft_reply"]
    assert any("never name a person" in f for f in router.calls[-1].inputs["feedback"])
    [draft] = world.replies()
    assert word.lower() not in draft["body"].replace(BOOKING_URL, "").lower()
    assert _last_activity(world, "reply_drafted")["how"] == "fallback"


def test_a_question_without_a_call_keeps_no_link(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Are you based in the US?")
    answer = ReplyDraft(
        body="Hi Maya,\n\nWe work remotely with founders across time zones.\n\nTeam Nument", include_booking_link=False
    )
    _run(FakeRouter({"classify_reply": [_classified("question")], "draft_reply": [answer]}))
    [draft] = world.replies()
    assert BOOKING_URL not in draft["body"]


def test_when_ai_is_down_replies_wait_and_nothing_is_lost(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Interesting, tell me more.", "Also, who are you?")
    down = FakeRouter({"classify_reply": [AllProvidersDown("x"), AllProvidersDown("x"), AllProvidersDown("x")]})
    stats = _run(down)
    assert stats["waiting"] == 2 and stats["ai.failed"] == 2
    assert all(m["classification"] is None for m in world.incoming())
    budget = FakeRouter({"classify_reply": [BudgetExceeded("cap")]})
    assert _run(budget)["stopped.budget"] == 1
    seen: list[dict[str, Any]] = []
    ok = FakeRouter(
        {"classify_reply": [_classified("interested"), _classified("question")], "draft_reply": _drafter(seen)}
    )
    stats = _run(ok)
    assert stats["classified.interested"] == 1 and stats["classified.question"] == 1
    assert len(world.replies()) == 2


def test_a_founder_template_goes_out_only_in_auto_mode(outreach_on: str) -> None:
    template = "Hi {first_name},\n\nNo problem, we'll check back in a couple of months.\n\nTeam Nument"
    db.set_setting("outreach.auto_replies", True)
    db.set_setting("outreach.reply_templates", {"not_now": template})
    world = make_world(outreach_on)
    _receive(world, "Not now, maybe next year.")
    _run(FakeRouter({"classify_reply": [_classified("not_now", 0.95)], "draft_reply": [AllProvidersDown("x")]}))
    [draft] = world.replies()
    assert draft["status"] == "review"  # manual mode: a person approves every send
    db.set_setting("outreach.mode", "auto")
    auto = make_world(outreach_on)
    _receive(auto, "Not now, maybe next year.")
    router = FakeRouter({"classify_reply": [_classified("not_now", 0.95)]})
    _run(router)
    [sent] = auto.replies()
    assert sent["status"] == "approved" and sent["body"].startswith("Hi Maya,")
    assert router.tasks() == ["classify_reply"]
    unsure = make_world(outreach_on)
    _receive(unsure, "Hmm, maybe later?")
    _run(FakeRouter({"classify_reply": [_classified("not_now", 0.7)], "draft_reply": [AllProvidersDown("x")]}))
    assert unsure.replies()[0]["status"] == "review"


def test_outreach_off_and_dry_run(outreach_on: str) -> None:
    world = make_world(outreach_on)
    _receive(world, "Tell me more.")
    assert replies.run(rc_for(dry_run=True), router=FakeRouter({}))["skipped"] == "dry run"
    assert world.incoming()[0]["classification"] is None
    db.set_setting("outreach.mode", "off")
    assert replies.run(rc_for(), router=FakeRouter({})) == {"skipped": "outreach off"}
