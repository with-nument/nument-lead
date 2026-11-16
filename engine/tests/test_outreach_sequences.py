"""The send phase against the test database: routing, every gate, threading, follow-ups, errors, crash
recovery (lane E5a). Gmail is a FakeMailbox on the test clock; nothing leaves the machine."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from nument_engine import settings as settings_module
from nument_engine.outreach import sequences as seq
from nument_engine.outreach.gmail import MailboxError, Outgoing

from .outreach_seed import ME, POSTAL, T0, ClockedMailbox, FakeClock, World, rc


@pytest.fixture
def world(engine_db: str) -> Iterator[World]:
    w = World(engine_db)
    snapshot = w.snapshot()
    try:
        yield w
    finally:
        w.restore(snapshot)


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch, engine_db: str) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("APP_URL", "https://lead.nument.in")
    settings_module.get_settings.cache_clear()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def gmail(clock: FakeClock) -> ClockedMailbox:
    return ClockedMailbox(clock)


def send(clock: FakeClock, gmail: ClockedMailbox, **kw: Any) -> dict[str, Any]:
    return seq.run(rc(**kw), mailbox=gmail, clock=seq.Clock(now=clock.now, sleep=clock.sleep))


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------


def test_off_by_default_does_nothing(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.mailbox()
    t = world.thread(world.lead())
    assert send(clock, gmail) == {"skipped": "outreach off"}
    assert world.msg(t["steps"][0])["status"] == "approved" and gmail.sent == []


def test_paused_sends_nothing(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on(paused=True)
    world.mailbox()
    world.thread(world.lead())
    out = send(clock, gmail)
    assert out["stopped"] == "paused" and gmail.sent == []


@pytest.mark.parametrize("status", ["paused", "error", "disconnected"])
def test_mailbox_must_be_warming_or_active(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox, status: str
) -> None:
    world.outreach_on()
    world.mailbox(status=status)
    world.thread(world.lead())
    assert send(clock, gmail)["stopped"] == f"mailbox {status}" and gmail.sent == []


def test_no_mailbox(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.thread(world.lead())
    assert send(clock, gmail)["stopped"] == "no mailbox"


def test_no_postal_address_no_send(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.setting("outreach.postal_address", None)
    world.mailbox()
    world.thread(world.lead())
    assert send(clock, gmail)["stopped"].startswith("no postal address") and gmail.sent == []


def test_dev_without_sandbox_sends_nothing(world: World, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead())
    assert send(clock, gmail, env="dev")["stopped"] == "dev without outreach.sandbox_to" and gmail.sent == []


def test_prod_flag_alone_is_not_production(world: World, clock: FakeClock, gmail: ClockedMailbox) -> None:
    """--env prod with APP_ENV=dev settings still counts as dev: both must say prod."""
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead())
    assert send(clock, gmail, env="prod")["stopped"] == "dev without outreach.sandbox_to"


def test_dev_rewrites_the_recipient_to_the_sandbox(world: World, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on(sandbox_to="founder.sandbox@example.com")
    world.mailbox()
    t = world.thread(world.lead())
    out = send(clock, gmail, env="dev")
    assert out["sent"] == 1 and gmail.sent[0].to == "founder.sandbox@example.com"
    activity = world.one(
        "select payload from public.activities where lead_id = %s and type = 'email_sent'", [t["lead"]]
    )
    assert activity["payload"]["sandbox"] is True


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def test_auto_bar_met_queues_and_sends(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on("auto")
    world.mailbox()
    t = world.thread(world.lead(), day0="draft")
    out = send(clock, gmail)
    assert out["enqueued"]["queued"] == 1
    assert world.thread_row(t["id"])["mode"] == "auto"
    assert world.msg(t["steps"][0])["status"] == "sent" and len(gmail.sent) == 1
    # auto mode: the follow-ups are queued at their times
    assert {world.msg(t["steps"][s])["status"] for s in (3, 7, 12)} == {"queued"}


@pytest.mark.parametrize(
    ("lead", "flag", "body", "mode"),
    [
        ({"score": 74}, False, None, "auto"),
        ({"critic": 8.5}, False, None, "auto"),
        ({"critic": None}, False, None, "auto"),
        ({"email_status": "likely"}, False, None, "auto"),
        ({}, True, None, "auto"),
        ({}, False, "Hi Maya, see acme.app/demo", "auto"),
        ({}, False, None, "manual"),
    ],
)
def test_everything_else_goes_to_review(
    world: World,
    prod: None,
    clock: FakeClock,
    gmail: ClockedMailbox,
    lead: dict[str, Any],
    flag: bool,
    body: str | None,
    mode: str,
) -> None:
    world.outreach_on(mode)
    world.mailbox()
    t = world.thread(world.lead(**lead), day0="draft", day0_body=body, created=T0 - timedelta(hours=1))
    if flag:
        world.update(
            "insert into public.activities (lead_id, source, type, at) values (%s, 'engine', 'message_flagged', %s)",
            [t["lead"], T0 - timedelta(minutes=30)],
        )
    out = send(clock, gmail)
    assert out["enqueued"]["review"] == 1 and out["enqueued"]["queued"] == 0
    assert world.msg(t["steps"][0])["status"] == "review" and world.thread_row(t["id"])["mode"] == "review"
    assert gmail.sent == []


def test_an_old_flag_does_not_block_a_new_draft(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on("auto")
    world.mailbox()
    lead = world.lead()
    world.update(
        "insert into public.activities (lead_id, source, type, at) values (%s, 'engine', 'message_flagged', %s)",
        [lead["lead"], T0 - timedelta(days=2)],
    )
    t = world.thread(lead, day0="draft", created=T0 - timedelta(hours=1))
    assert send(clock, gmail)["enqueued"]["queued"] == 1
    assert world.msg(t["steps"][0])["status"] == "sent"


def test_enqueue_stops_conversations_that_may_never_be_mailed(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on("auto")
    world.mailbox()
    german = world.thread(world.lead(country="de", city="Berlin"), day0="draft")
    guessed = world.thread(world.lead(country="ca", city="Toronto", origin="guess"), day0="draft")
    out = send(clock, gmail)
    assert out["enqueued"]["stopped"] == {"blocked_country": 1, "guess_in_published_only": 1}
    for t, reason in ((german, "blocked_country"), (guessed, "guess_in_published_only")):
        row = world.thread_row(t["id"])
        assert (row["status"], row["stop_reason"]) == ("stopped", reason)
        assert {world.msg(i)["status"] for i in t["steps"].values()} == {"cancelled"}
    assert gmail.sent == []


def test_manual_mode_sends_only_what_a_person_approved(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on("manual")
    world.mailbox()
    queued = world.thread(world.lead(), day0="queued", mode="auto")
    approved = world.thread(world.lead())
    out = send(clock, gmail)
    assert out["enqueued"]["back_to_review"] == 1
    assert world.msg(queued["steps"][0])["status"] == "review"
    assert world.msg(approved["steps"][0])["status"] == "sent" and len(gmail.sent) == 1
    # manual mode: every follow-up waits for a person
    assert {world.msg(approved["steps"][s])["status"] for s in (3, 7, 12)} == {"review"}


# ---------------------------------------------------------------------------
# A send and everything recorded with it
# ---------------------------------------------------------------------------


def test_day0_send_records_everything(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    box = world.mailbox()
    t = world.thread(world.lead())
    out = send(clock, gmail)
    assert out["sent"] == 1 and out["cap_24h"] == 10 and out["sent_24h"] == 0
    email: Outgoing = gmail.sent[0]
    assert email.to == t["email"] and email.subject == "Quick question about Acme"
    assert email.body.endswith(
        f"Team Nument\n{POSTAL}\nIf you'd rather not hear from us, you can opt out here: "
        f"https://lead.nument.in/u/{t['id']}\n"
    )
    assert email.unsubscribe_url == f"https://lead.nument.in/u/{t['id']}"
    assert email.unsubscribe_mailto == f"mailto:{ME}?subject=unsubscribe"
    assert email.in_reply_to is None and email.references == () and email.gmail_thread_id is None
    msg = world.msg(t["steps"][0])
    assert msg["status"] == "sent" and msg["sent_at"] == T0 and msg["gmail_message_id"] == "m1"
    assert msg["rfc_message_id"] == email.rfc_message_id and msg["rfc_message_id"].endswith("@nument.in>")
    thread = world.thread_row(t["id"])
    assert thread["gmail_thread_id"] == "t1" and str(thread["mailbox_id"]) == box
    lead = world.one("select stage from public.leads where id = %s", [t["lead"]])
    assert lead["stage"] == "contacted"
    activity = world.one(
        "select payload, at from public.activities where lead_id = %s and type = 'email_sent'", [t["lead"]]
    )
    assert activity["payload"] == {"thread_id": t["id"], "message_id": t["steps"][0], "step": 0, "sandbox": False}
    mailbox = world.one("select sent_today, sent_day, warmup_started_on from public.mailboxes where id = %s", [box])
    assert mailbox == {"sent_today": 1, "sent_day": date(2026, 11, 17), "warmup_started_on": date(2026, 11, 17)}


def test_followups_are_scheduled_in_the_recipients_windows(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())  # New York; sent Tuesday 17 Nov 10:00 EST
    send(clock, gmail)
    scheduled = {s: world.msg(t["steps"][s])["scheduled_for"] for s in (3, 7, 12)}
    assert scheduled == {
        3: utc(2026, 11, 20, 15, 0),  # Friday 10:00 EST
        7: utc(2026, 11, 24, 15, 0),  # Tuesday 10:00 EST
        12: utc(2026, 11, 30, 13, 30),  # Sunday 29th moves to Monday 08:30 EST
    }


def test_a_followup_threads_into_the_same_conversation(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on("auto")
    world.mailbox()
    t = world.thread(world.lead(), followups="draft")
    send(clock, gmail)
    world.update(
        "update public.email_messages set body = 'Hi Maya, the plan: https://lead.nument.in/p/abc' where id = %s",
        [t["steps"][3]],
    )
    clock.at = utc(2026, 11, 20, 15, 5)  # Friday, day 3 is due
    out = send(clock, gmail)
    assert out["sent"] == 1
    first, follow = gmail.sent
    assert follow.subject == "Re: Quick question about Acme"
    assert follow.in_reply_to == first.rfc_message_id and follow.references == (first.rfc_message_id,)
    assert follow.gmail_thread_id == "t1"
    assert "https://lead.nument.in/p/abc" in follow.body  # follow-ups may carry links
    assert world.msg(t["steps"][3])["status"] == "sent"


def test_a_reply_answers_the_latest_message_they_sent(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    lead = world.lead(stage="talking")
    t = world.thread(lead, day0="sent", followups="cancelled", status="stopped")
    world.update(
        "update public.email_messages set rfc_message_id = '<d0@nument.in>', sent_at = %s, gmail_message_id = 'g0' "
        "where id = %s",
        [T0 - timedelta(days=2), t["steps"][0]],
    )
    world.update("update public.email_threads set gmail_thread_id = 'gt' where id = %s", [t["id"]])
    world.message(
        t["id"],
        direction="in",
        subject="Re: Quick question about Acme",
        body="Tell me more",
        status="received",
        rfc_message_id="<in1@acme.example>",
        created_at=T0 - timedelta(days=1),
    )
    world.message(
        t["id"],
        direction="in",
        subject="Re: Quick question about Acme",
        body="Also, price?",
        status="received",
        rfc_message_id="<in2@acme.example>",
        created_at=T0 - timedelta(hours=2),
    )
    reply = world.message(t["id"], step=None, body="Hi Maya, happy to walk you through it.", status="approved")
    out = send(clock, gmail)
    assert out["sent"] == 1
    email = gmail.sent[0]
    assert email.in_reply_to == "<in2@acme.example>"
    assert email.references == ("<d0@nument.in>", "<in1@acme.example>", "<in2@acme.example>")
    assert email.subject == "Re: Quick question about Acme" and email.gmail_thread_id == "gt"
    assert world.msg(reply)["status"] == "sent"
    assert world.one("select stage from public.leads where id = %s", [lead["lead"]])["stage"] == "talking"


def test_a_reply_is_never_sent_on_a_done_thread(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead(), day0="sent", followups="cancelled", status="done")
    world.message(t["id"], step=None, body="Hi Maya, thanks!", status="approved")
    assert send(clock, gmail).get("sent") is None and gmail.sent == []


def test_gmail_replacing_the_message_id_is_recorded(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())
    gmail.replace_id = "<CA-replaced@mail.gmail.com>"
    send(clock, gmail)
    assert world.msg(t["steps"][0])["rfc_message_id"] == "<CA-replaced@mail.gmail.com>"


# ---------------------------------------------------------------------------
# Gates that stop a conversation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lead", "reason", "status"),
    [
        ({"country": "de", "city": "Berlin"}, "blocked_country", "stopped"),
        ({"country": "no", "city": "Oslo"}, "blocked_country", "stopped"),  # YAML reads `no` as false
        ({"country": "jp", "city": "Tokyo"}, "country_not_allowed", "stopped"),
        ({"country": "ca", "city": "Toronto", "origin": "guess"}, "guess_in_published_only", "stopped"),
        ({"country": "au", "city": "Sydney", "origin": None}, "guess_in_published_only", "stopped"),
        ({"email_status": "invalid"}, "email_invalid", "stopped"),
        ({"stage": "talking"}, "stage_changed", "stopped"),
        ({"do_not_contact": True}, "do_not_contact", "done"),
    ],
)
def test_hard_gates_stop_the_conversation(
    world: World,
    prod: None,
    clock: FakeClock,
    gmail: ClockedMailbox,
    lead: dict[str, Any],
    reason: str,
    status: str,
) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead(**lead))
    out = send(clock, gmail)
    assert out["conversations_stopped"] == {reason: 1} and gmail.sent == []
    row = world.thread_row(t["id"])
    assert (row["status"], row["stop_reason"]) == (status, reason)
    assert {world.msg(i)["status"] for i in t["steps"].values()} == {"cancelled"}
    stopped = world.one(
        "select payload from public.activities where lead_id = %s and type = 'sequence_stopped'", [t["lead"]]
    )
    assert stopped["payload"]["reason"] == reason


def test_published_address_in_a_published_only_country_is_fine(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead(country="ca", city="Toronto", origin="published"))
    assert send(clock, gmail)["sent"] == 1


@pytest.mark.parametrize("by", ["email", "domain"])
def test_suppression_ends_the_conversation(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox, by: str
) -> None:
    world.outreach_on()
    world.mailbox()
    lead = world.lead()
    t = world.thread(lead)
    if by == "email":
        world.suppress(email=lead["email"].upper())
    else:
        world.suppress(domain=lead["domain"])
    out = send(clock, gmail)
    assert out["conversations_stopped"] == {"suppressed": 1} and gmail.sent == []
    assert world.thread_row(t["id"])["status"] == "done"


def test_a_changed_contact_address_is_not_mailed(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    lead = world.lead()
    t = world.thread(lead)
    world.update("update public.contacts set email = 'new@elsewhere.example.com' where id = %s", [lead["contact"]])
    assert send(clock, gmail)["conversations_stopped"] == {"address_changed": 1}
    assert world.thread_row(t["id"])["status"] == "stopped"


def test_domain_cooldown_blocks_a_second_conversation(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    first = world.thread(world.lead(domain="shared.example.com"), day0="sent", followups="cancelled", status="stopped")
    world.update(
        "update public.email_messages set sent_at = %s where id = %s", [T0 - timedelta(days=89), first["steps"][0]]
    )
    second = world.thread(world.lead(domain="shared.example.com"))
    out = send(clock, gmail)
    assert out["conversations_stopped"] == {"domain_cooldown": 1} and gmail.sent == []
    assert world.thread_row(second["id"])["stop_reason"] == "domain_cooldown"


def test_domain_cooldown_ends_after_the_window(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    first = world.thread(world.lead(domain="old.example.com"), day0="sent", followups="cancelled", status="done")
    world.update(
        "update public.email_messages set sent_at = %s where id = %s", [T0 - timedelta(days=91), first["steps"][0]]
    )
    world.thread(world.lead(domain="old.example.com"))
    assert send(clock, gmail)["sent"] == 1


def test_two_new_conversations_with_one_domain_in_one_run(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead(domain="twice.example.com"))
    world.thread(world.lead(domain="twice.example.com"))
    out = send(clock, gmail)
    assert out["sent"] == 1 and out["conversations_stopped"] == {"domain_cooldown": 1}


# ---------------------------------------------------------------------------
# Gates that wait
# ---------------------------------------------------------------------------


def test_outside_the_recipients_window_waits(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead(country="in", city="Pune"))  # 20:30 in India
    out = send(clock, gmail)
    assert out["held"] == {"outside_window": 1} and gmail.sent == []
    assert world.msg(t["steps"][0])["status"] == "approved"
    clock.at = utc(2026, 11, 18, 4, 0)  # Wednesday 09:30 IST
    assert send(clock, gmail)["sent"] == 1


def test_weekends_wait(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead())
    clock.at = utc(2026, 11, 21, 15, 0)  # Saturday 10:00 in New York
    assert send(clock, gmail)["held"] == {"outside_window": 1}


def test_unknown_email_status_waits(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead(email_status="unknown"))
    assert send(clock, gmail)["held"] == {"email_unknown": 1}


@pytest.mark.parametrize(("status", "outcome"), [("invalid", "stopped"), ("unknown", "held")])
def test_a_recheck_after_the_thread_was_made_refuses_the_followup(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox, status: str, outcome: str
) -> None:
    """Lane E3's verifier can turn an address invalid or unknown once the sequence has started."""
    world.outreach_on("auto")
    world.mailbox()
    lead = world.lead()
    t = world.thread(lead, day0="draft")
    send(clock, gmail)
    assert world.msg(t["steps"][0])["status"] == "sent"
    world.update("update public.contacts set email_status = %s where id = %s", [status, lead["contact"]])
    clock.at = utc(2026, 11, 20, 15, 5)  # day 3 is due
    world.update("update public.email_messages set body = 'Hi Maya, the plan is ready.' where id = %s", [t["steps"][3]])
    out = send(clock, gmail)
    assert len(gmail.sent) == 1  # day 0 only
    if outcome == "stopped":
        assert out["conversations_stopped"] == {"email_invalid": 1}
        assert world.thread_row(t["id"])["stop_reason"] == "email_invalid"
        assert {world.msg(t["steps"][s])["status"] for s in (3, 7, 12)} == {"cancelled"}
    else:
        assert out["held"] == {"email_unknown": 1}
        assert world.msg(t["steps"][3])["status"] == "queued"


@pytest.mark.parametrize(("status", "key"), [("invalid", "conversations_stopped"), ("unknown", "held")])
def test_a_reply_to_an_invalid_or_unknown_address_is_refused(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox, status: str, key: str
) -> None:
    world.outreach_on()
    world.mailbox()
    lead = world.lead(stage="talking", email_status=status)
    t = world.thread(lead, day0="sent", followups="cancelled", status="stopped")
    reply = world.message(t["id"], step=None, body="Hi Maya, happy to help.", status="approved")
    out = send(clock, gmail)
    assert gmail.sent == [] and out[key] == {f"email_{status}": 1}
    assert world.msg(reply)["status"] == ("cancelled" if status == "invalid" else "approved")


def test_future_and_paused_messages_are_not_due(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    later = world.thread(world.lead())
    world.update(
        "update public.email_messages set scheduled_for = %s where id = %s",
        [T0 + timedelta(hours=1), later["steps"][0]],
    )
    world.thread(world.lead(), paused_until=T0 + timedelta(days=3))
    out = send(clock, gmail)
    assert gmail.sent == [] and "held" not in out


def test_followups_wait_for_earlier_steps(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on("auto")
    world.mailbox()
    lead = world.lead(stage="contacted")
    no_day0 = world.thread(lead, day0="review", followups="queued")
    out = send(clock, gmail)
    assert out["held"] == {"day0_not_sent": 3}
    world.update(
        "update public.email_messages set status = 'sent', sent_at = %s, rfc_message_id = '<x@nument.in>' "
        "where id = %s",
        [T0 - timedelta(days=8), no_day0["steps"][0]],
    )
    world.update("update public.email_messages set status = 'review' where id = %s", [no_day0["steps"][3]])
    out = send(clock, gmail)
    assert out["held"] == {"earlier_step_pending": 2} and gmail.sent == []


def test_placeholders(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on("auto")
    world.mailbox()
    waiting = world.thread(world.lead(stage="contacted"), day0="sent", followups="queued", steps=(0, 3))
    world.update(
        "update public.email_messages set sent_at = %s, rfc_message_id = '<w@nument.in>' where id = %s",
        [T0 - timedelta(days=3), waiting["steps"][0]],
    )
    broken = world.thread(world.lead(), day0_body="Hi {first_name}, quick one about Acme.")
    out = send(clock, gmail)
    assert out["held"] == {"waiting_for_link": 1}  # the plans phase fills {plan_link} later
    assert out["to_review"] == {"placeholder": 1}
    assert world.msg(broken["steps"][0])["status"] == "review"
    assert world.msg(broken["steps"][0])["error"] == "placeholder"
    assert world.msg(waiting["steps"][3])["status"] == "queued" and gmail.sent == []


def test_a_link_in_day0_goes_back_to_review(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead(), day0_body="Hi Maya, have a look at www.nument.in first.")
    assert send(clock, gmail)["to_review"] == {"link_in_day0": 1}
    assert world.msg(t["steps"][0])["status"] == "review" and gmail.sent == []


# ---------------------------------------------------------------------------
# Caps and pacing
# ---------------------------------------------------------------------------


def _sent_before(world: World, n: int, at: datetime) -> None:
    for _ in range(n):
        t = world.thread(world.lead(), day0="sent", followups="cancelled", status="stopped", steps=(0,))
        world.update("update public.email_messages set sent_at = %s where id = %s", [at, t["steps"][0]])


def test_warmup_cap_counts_the_last_24_hours(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox(started=date(2026, 11, 16))  # week 1: 10 a day
    _sent_before(world, 9, T0 - timedelta(hours=23))
    world.thread(world.lead())
    world.thread(world.lead())
    out = send(clock, gmail)
    assert out["sent"] == 1 and out["stopped"] == "warmup_cap" and out["cap_24h"] == 10


def test_warmup_cap_grows_by_week(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox(started=date(2026, 11, 3))  # 14 days ago: week 3, 20 a day
    _sent_before(world, 19, T0 - timedelta(hours=2))
    world.thread(world.lead())
    out = send(clock, gmail)
    assert out["cap_24h"] == 20 and out["sent"] == 1


def test_sends_older_than_24_hours_do_not_count(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox(started=date(2026, 11, 16))
    _sent_before(world, 10, T0 - timedelta(hours=25))
    world.thread(world.lead())
    assert send(clock, gmail)["sent"] == 1


def test_per_run_cap_and_spacing(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    for _ in range(5):
        world.thread(world.lead())
    out = send(clock, gmail)
    assert out["sent"] == 3 and out["stopped"] == "per_run_cap"
    assert clock.slept == [90.0, 90.0]


def test_limit_option_caps_the_run(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead())
    world.thread(world.lead())
    assert send(clock, gmail, limit=1)["sent"] == 1


def test_spacing_since_the_previous_run(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    _sent_before(world, 1, T0 - timedelta(seconds=30))
    world.thread(world.lead())
    assert send(clock, gmail)["sent"] == 1
    assert clock.slept == [60.0]


def test_a_pause_during_the_wait_stops_the_run(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead())
    world.thread(world.lead())

    def pause_while_waiting(seconds: float) -> None:
        clock.sleep(seconds)
        world.setting("outreach.paused", True)

    out = seq.run(rc(), mailbox=gmail, clock=seq.Clock(now=clock.now, sleep=pause_while_waiting))
    assert out["sent"] == 1 and out["stopped"] == "paused" and len(gmail.sent) == 1


def test_bounce_rate_over_the_limit_pauses_before_sending(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    _sent_before(world, 20, T0 - timedelta(days=2))
    world.update(
        "update public.email_messages set error = 'bounced' where id in (select id from "
        "public.email_messages where status = 'sent' limit 1)",
        [],
    )
    world.thread(world.lead())
    out = send(clock, gmail)
    assert out["stopped"] == "bounce rate" and gmail.sent == []
    assert world.one("select value from public.settings where key = 'outreach.paused'")["value"] is True


# ---------------------------------------------------------------------------
# Gmail errors and double sends
# ---------------------------------------------------------------------------


def test_rate_limit_puts_the_message_back_and_pauses(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    box = world.mailbox()
    t = world.thread(world.lead())
    gmail.fail_next = MailboxError("rate_limit", "Too many requests: User-rate limit exceeded (Mail sending)")
    out = send(clock, gmail)
    assert out["stopped"] == "gmail_rate_limit"
    msg = world.msg(t["steps"][0])
    assert msg["status"] == "approved" and msg["rfc_message_id"]  # the id is kept for the next attempt
    mailbox = world.one("select status, paused_reason from public.mailboxes where id = %s", [box])
    assert mailbox == {"status": "paused", "paused_reason": "gmail_rate_limit"}
    assert world.one("select value from public.settings where key = 'outreach.paused'")["value"] is True


def test_auth_error_marks_the_mailbox(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    box = world.mailbox()
    t = world.thread(world.lead())
    gmail.fail_next = MailboxError("auth", "oauth 400: invalid_grant")
    assert send(clock, gmail)["stopped"] == "gmail_auth"
    assert world.msg(t["steps"][0])["status"] == "approved"
    assert world.one("select status from public.mailboxes where id = %s", [box])["status"] == "error"


def test_an_invalid_message_fails_and_the_run_goes_on(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    bad = world.thread(world.lead())
    good = world.thread(world.lead())
    gmail.fail_next = MailboxError("invalid", "gmail 400: Invalid To header", status=400)
    out = send(clock, gmail)
    assert out["failed"] == 1 and out["sent"] == 1
    statuses = {world.msg(bad["steps"][0])["status"], world.msg(good["steps"][0])["status"]}
    assert statuses == {"failed", "sent"}


def test_an_unclear_send_stays_claimed(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())
    gmail.fail_next = MailboxError("transient", "Gmail did not answer: ReadTimeout", maybe_sent=True)
    out = send(clock, gmail)
    assert out["stopped"] == "gmail_unclear"
    msg = world.msg(t["steps"][0])
    assert msg["status"] == "sending" and msg["rfc_message_id"]


def test_never_sent_twice(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    world.thread(world.lead())
    send(clock, gmail)
    clock.advance(minutes=15)
    send(clock, gmail)
    assert len(gmail.sent) == 1


def test_claim_refuses_a_message_changed_since_it_was_read(world: World, prod: None) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())
    row = world.one(seq.MESSAGE_SQL + " and m.id = %s", [t["steps"][0]])
    world.update("update public.email_messages set body = 'edited by a person' where id = %s", [t["steps"][0]])
    assert seq.claim(row, "<c1@nument.in>", T0) is None
    row = world.one(seq.MESSAGE_SQL + " and m.id = %s", [t["steps"][0]])
    world.update("update public.email_messages set status = 'cancelled' where id = %s", [t["steps"][0]])
    assert seq.claim(row, "<c1@nument.in>", T0) is None
    world.update("update public.email_messages set status = 'approved' where id = %s", [t["steps"][0]])
    world.update("update public.email_threads set status = 'stopped' where id = %s", [t["id"]])
    assert seq.claim(row, "<c1@nument.in>", T0) is None
    world.update("update public.email_threads set status = 'open' where id = %s", [t["id"]])
    assert seq.claim(row, "<c1@nument.in>", T0) == "<c1@nument.in>"
    assert world.msg(t["steps"][0])["status"] == "sending"


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


def _stuck(world: World, t: dict[str, Any], minutes: int, rfc: str = "<stuck@nument.in>") -> None:
    world.update(
        "update public.email_messages set status = 'sending', rfc_message_id = %s, updated_at = %s where id = %s",
        [rfc, T0 - timedelta(minutes=minutes), t["steps"][0]],
    )


def test_recovery_records_a_message_gmail_has(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox
) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())
    _stuck(world, t, 11)
    gmail.sent.append(Outgoing(to=t["email"], subject="s", body="b", rfc_message_id="<stuck@nument.in>"))
    out = send(clock, gmail)
    assert out["recovered"] == {"sent": 1}
    assert gmail.lookups == [("<stuck@nument.in>", t["email"])]
    msg = world.msg(t["steps"][0])
    assert msg["status"] == "sent" and msg["gmail_message_id"] == "m1"
    assert world.one("select stage from public.leads where id = %s", [t["lead"]])["stage"] == "contacted"
    assert world.msg(t["steps"][3])["scheduled_for"] is not None
    assert len(gmail.sent) == 1  # recorded, not sent again


def test_recovery_requeues_what_never_left(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())
    _stuck(world, t, 11)
    out = send(clock, gmail)
    assert out["recovered"] == {"requeued": 1}
    assert out["sent"] == 1  # back in the queue and sent in the same run, with the same Message-ID
    assert gmail.sent[0].rfc_message_id == "<stuck@nument.in>"
    assert world.msg(t["steps"][0])["status"] == "sent"


def test_a_fresh_claim_is_left_alone(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())
    _stuck(world, t, 5)
    out = send(clock, gmail)
    assert "recovered" not in out and gmail.lookups == [] and gmail.sent == []
    assert world.msg(t["steps"][0])["status"] == "sending"


def test_a_crash_after_gmail_took_it_is_recovered_without_a_second_send(
    world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.outreach_on()
    world.mailbox()
    t = world.thread(world.lead())
    real = seq.record_sent

    def crash(*args: Any, **kw: Any) -> None:
        raise ConnectionError("database went away")

    monkeypatch.setattr(seq, "record_sent", crash)
    with pytest.raises(ConnectionError):
        send(clock, gmail)
    assert world.msg(t["steps"][0])["status"] == "sending" and len(gmail.sent) == 1
    monkeypatch.setattr(seq, "record_sent", real)
    clock.advance(minutes=15)
    out = send(clock, gmail)
    assert out["recovered"] == {"sent": 1} and len(gmail.sent) == 1
    assert world.msg(t["steps"][0])["status"] == "sent"


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_writes_and_sends_nothing(world: World, prod: None, clock: FakeClock, gmail: ClockedMailbox) -> None:
    world.outreach_on("auto")
    world.mailbox()
    draft = world.thread(world.lead(), day0="draft")
    ready = world.thread(world.lead())
    blocked = world.thread(world.lead(country="de", city="Berlin"))
    out = send(clock, gmail, dry_run=True)
    assert out["dry_run"] is True and out["would_send"] == 1
    assert out["enqueued"]["queued"] == 1 and out["conversations_stopped"] == {"blocked_country": 1}
    assert world.msg(draft["steps"][0])["status"] == "draft"
    assert world.msg(ready["steps"][0])["status"] == "approved"
    assert world.thread_row(blocked["id"])["status"] == "open"
    assert gmail.sent == []
