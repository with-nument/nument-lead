"""The inbox phase (contract 4.6): matching, stopping the sequence, bounces, opt-outs, duplicates and the cursor."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from nument_engine import db
from nument_engine.outreach import inbox
from nument_engine.outreach.gmail import FakeMailbox, Incoming, MailboxError

from .outreach_world import World, make_world, rc_for


@pytest.fixture
def outreach_on(engine_db: str) -> Iterator[str]:
    before = db.get_setting("outreach.mode")
    db.set_setting("outreach.mode", "manual")
    yield engine_db
    db.set_setting("outreach.mode", before if before is not None else "off")


def _run(box: FakeMailbox, **kw: Any) -> dict[str, Any]:
    return inbox.run(rc_for(**kw), mailbox=box)


def _cursor(world: World) -> Any:
    return db.get_setting(inbox.CURSOR_KEY.format(address=world.mailbox))


@dataclass(frozen=True)
class WithReferences(Incoming):
    """An Incoming that also carries References, as a fuller Gmail client may hand it over."""

    references: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------


def test_a_reply_is_stored_and_stops_the_sequence_at_once(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(world.reply("Sounds interesting, tell me more.\n\nOn Mon, Nument wrote:\n> Hi Maya"))
    stats = _run(box)
    assert stats == {"fetched": 1, "reply": 1}
    [msg] = world.incoming()
    assert (msg["direction"], msg["status"], msg["step"]) == ("in", "received", None)
    assert msg["rfc_message_id"] == f"<in-{world.tag}-1@mail.brightcart.example>"
    assert msg["gmail_message_id"] == f"in-{world.tag}-1" and msg["classification"] is None
    thread = world.thread()
    assert (thread["status"], thread["stop_reason"]) == ("stopped", "reply")
    assert world.statuses() == {0: "sent", 3: "cancelled", 7: "cancelled", 12: "cancelled"}
    [stopped] = world.activities("sequence_stopped")
    assert stopped["payload"]["reason"] == "reply" and stopped["payload"]["message_id"] == str(msg["id"])
    assert [(c["step"], c["status"]) for c in stopped["payload"]["cancelled"]] == [
        (3, "queued"),
        (7, "queued"),
        (12, "review"),
    ]
    [received] = world.activities("email_received")
    assert received["payload"]["from_email"] == world.email and received["payload"]["matched_by"] == "gmail_thread"
    assert received["payload"]["from_name"] == "Maya Chen"
    assert box.read == set()  # replies stay unread for the founder
    assert _cursor(world) == "1"


def test_reading_the_same_mail_again_stores_nothing_twice(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(world.reply("Yes please, send the plan."))
    _run(box)
    db.set_setting(inbox.CURSOR_KEY.format(address=world.mailbox), "0")  # a crashed run left the old cursor
    again = world.box()
    again.incoming = list(box.incoming)
    assert _run(again) == {"fetched": 1, "duplicate": 1}
    assert len(world.incoming()) == 1 and len(world.activities("sequence_stopped")) == 1


def test_match_by_in_reply_to_when_gmail_threads_differ(outreach_on: str) -> None:
    world = make_world(outreach_on)
    world.run_sql("update public.email_threads set gmail_thread_id = null where id = %s", [world.thread_id])
    box = world.box()
    box.incoming.append(world.reply("Happy to chat.", gmail_thread="new-gmail-thread"))
    assert _run(box)["reply"] == 1
    assert world.activities("email_received")[0]["payload"]["matched_by"] == "in_reply_to"
    assert world.thread()["gmail_thread_id"] == "new-gmail-thread"  # learned for next time


def test_match_by_references(outreach_on: str) -> None:
    world = make_world(outreach_on)
    base = world.reply("Forwarding to my co-founder, she will reply.", gmail_thread="fwd", in_reply_to="<x@y>")
    msg = WithReferences(**{f: getattr(base, f) for f in base.__dataclass_fields__}, references=(world.rfc[0],))
    assert inbox.message_ids(msg) == ["<x@y>", world.rfc[0]]
    box = world.box()
    box.incoming.append(msg)
    assert _run(box)["reply"] == 1
    assert world.activities("email_received")[0]["payload"]["matched_by"] == "in_reply_to"


def test_match_by_sender_when_they_write_a_new_email(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(world.reply("Hi, saw your note last week. Free Thursday?", gmail_thread=None, in_reply_to=None))
    assert _run(box)["reply"] == 1
    assert world.activities("email_received")[0]["payload"]["matched_by"] == "sender"


def test_match_by_company_domain_but_never_free_mail(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(
        world.reply("I'm Leo, Maya's co-founder.", sender=f"leo@{world.domain}", gmail_thread=None, in_reply_to=None)
    )
    assert _run(box)["reply"] == 1
    assert world.activities("email_received")[0]["payload"]["matched_by"] == "sender_domain"
    gmail_world = make_world(outreach_on)
    gmail_world.run_sql(
        "update public.email_threads set to_domain = 'gmail.com', to_email = 'maya.chen.test@gmail.com' where id = %s",
        [gmail_world.thread_id],
    )
    box = gmail_world.box()
    box.incoming.append(
        gmail_world.reply("Who is this?", sender="stranger.test@gmail.com", gmail_thread=None, in_reply_to=None, n=2)
    )
    assert _run(box)["unmatched"] == 1
    assert gmail_world.incoming() == []


def test_unmatched_mail_stays_unread_and_is_counted(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(world.reply("Newsletter", sender="news@unrelated.example", gmail_thread=None, in_reply_to=None))
    stats = _run(box)
    assert stats == {"fetched": 1, "unmatched": 1}
    assert box.read == set() and world.incoming() == [] and world.thread()["status"] == "open"
    assert _cursor(world) == "1"


def test_our_own_mail_is_skipped(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming += [
        world.reply("Following up by hand.", sender=world.mailbox, n=1),
        world.reply("A copy of what we sent.", sender="someone@else.example", n=2, labels=("SENT",)),
    ]
    assert _run(box) == {"fetched": 2, "own": 2}
    assert world.incoming() == [] and world.thread()["status"] == "open"


def test_a_reply_to_a_done_thread_is_kept_but_changes_nothing(outreach_on: str) -> None:
    world = make_world(outreach_on)
    world.run_sql(
        "update public.email_threads set status = 'done', stop_reason = 'closed' where id = %s", [world.thread_id]
    )
    box = world.box()
    box.incoming.append(world.reply("Actually, can we talk now?"))
    assert _run(box)["reply"] == 1
    assert len(world.incoming()) == 1
    assert (world.thread()["status"], world.thread()["stop_reason"]) == ("done", "closed")
    assert world.activities("sequence_stopped") == []


def test_a_second_reply_keeps_the_first_stop(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming += [world.reply("Interested.", n=1), world.reply("Also, what does it cost?", n=2)]
    assert _run(box)["reply"] == 2
    assert len(world.incoming()) == 2 and len(world.activities("sequence_stopped")) == 1


# ---------------------------------------------------------------------------
# Opt-outs and bounces
# ---------------------------------------------------------------------------


def test_the_unsubscribe_mailto_is_honoured_without_ai(outreach_on: str) -> None:
    world = make_world(outreach_on)
    world.run_sql(
        "insert into public.email_messages (thread_id, direction, step, body, status) "
        "values (%s, 'out', null, 'A drafted answer', 'review')",
        [world.thread_id],
    )
    box = world.box()
    box.incoming.append(
        world.reply(
            "This message was automatically generated by Gmail.",
            subject="unsubscribe",
            gmail_thread=None,
            in_reply_to=None,
        )
    )
    assert _run(box)["unsubscribed"] == 1
    thread = world.thread()
    assert (thread["status"], thread["stop_reason"]) == ("done", "unsubscribe")
    [msg] = world.incoming()
    assert msg["classification"] == "unsubscribe" and float(msg["classification_confidence"]) == 1.0
    assert world.contact()["do_not_contact"] is True
    assert [r["status"] for r in world.replies()] == ["cancelled"]  # replies are cancelled too
    suppressed = world.all(
        "select email, web_domain, reason from public.suppression where lower(email) = %s or web_domain = %s",
        [world.email, world.domain],
    )
    assert {(r["email"], r["web_domain"], r["reason"]) for r in suppressed} == {
        (world.email, None, "opt_out"),
        (None, world.domain, "opt_out"),
    }


def test_a_free_mail_opt_out_never_suppresses_the_whole_domain(outreach_on: str) -> None:
    world = make_world(outreach_on)
    address = f"maya.{world.tag}@gmail.com"
    world.run_sql(
        "update public.email_threads set to_email = %s, to_domain = 'gmail.com' where id = %s",
        [address, world.thread_id],
    )
    box = world.box()
    box.incoming.append(world.reply("", subject="Unsubscribe", sender=address, gmail_thread=None, in_reply_to=None))
    assert _run(box)["unsubscribed"] == 1
    assert world.all("select 1 from public.suppression where web_domain = 'gmail.com'") == []
    assert world.all("select 1 from public.suppression where lower(email) = %s", [address]) != []


def _bounce(world: World, n: int = 1, *, rfc: str | None = "step0", thread: str | None = None) -> Incoming:
    return Incoming(
        gmail_message_id=f"bounce-{world.tag}-{n}",
        gmail_thread_id=thread or f"bounce-thread-{world.tag}-{n}",
        rfc_message_id=f"<bounce-{world.tag}-{n}@mx.google.example>",
        in_reply_to=None,
        from_email="mailer-daemon@googlemail.com",
        from_name="Mail Delivery Subsystem",
        subject="Delivery Status Notification (Failure)",
        body_text="Address not found. Your message wasn't delivered.",
        received_at=datetime.now(UTC),
        is_bounce=True,
        bounced_rfc_id=world.rfc[0] if rfc == "step0" else rfc,
    )


def test_a_bounce_marks_the_address_invalid_and_stops_the_thread(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming += [_bounce(world, 1), _bounce(world, 2)]
    stats = _run(box)
    assert stats["bounced"] == 1 and stats["bounce_duplicate"] == 1
    sent = world.one("select status, error from public.email_messages where id = %s", [world.steps[0]])
    assert (sent["status"], sent["error"]) == ("sent", "bounced")
    assert world.contact()["email_status"] == "invalid"
    thread = world.thread()
    assert (thread["status"], thread["stop_reason"]) == ("stopped", "bounce")
    assert world.statuses()[3] == "cancelled"
    [bounced] = world.activities("email_bounced")
    assert bounced["payload"]["step"] == 0
    assert box.read == {f"bounce-{world.tag}-1", f"bounce-{world.tag}-2"}
    assert world.incoming() == []  # a delivery notice is not a reply


def test_a_bounce_without_a_message_id_matches_by_gmail_thread(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(_bounce(world, rfc=None, thread=world.gmail_thread_id))
    assert _run(box)["bounced"] == 1
    assert world.contact()["email_status"] == "invalid"


def test_an_unknown_bounce_stays_unread(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(_bounce(world, rfc="<not-ours@elsewhere.example>"))
    assert _run(box)["bounce_unmatched"] == 1
    assert box.read == set() and world.contact()["email_status"] == "verified"


# ---------------------------------------------------------------------------
# The run: cursor, failures, switches
# ---------------------------------------------------------------------------


def test_a_failing_message_keeps_the_cursor_and_the_rest_go_on(
    outreach_on: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = make_world(outreach_on)
    real = inbox.handle

    def flaky(conn: Any, msg: Incoming, ours: set[str]) -> str:
        if msg.gmail_message_id.endswith("-1"):
            raise RuntimeError("boom")
        return real(conn, msg, ours)

    monkeypatch.setattr(inbox, "handle", flaky)
    box = world.box()
    box.incoming += [world.reply("first", n=1), world.reply("second", n=2)]
    stats = _run(box)
    assert stats["error"] == 1 and stats["reply"] == 1 and stats["cursor"] == "kept"
    assert _cursor(world) is None
    monkeypatch.setattr(inbox, "handle", real)
    again = world.box()
    again.incoming = list(box.incoming)
    stats = _run(again)
    assert stats == {"fetched": 2, "reply": 1, "duplicate": 1}  # nothing lost, nothing doubled
    assert len(world.incoming()) == 2 and _cursor(world) == "2"


def test_outreach_off_reads_nothing(engine_db: str) -> None:
    db.set_setting("outreach.mode", "off")
    box = FakeMailbox("off-test@nument.example")
    box.incoming.append(
        Incoming("g1", "t1", "<r1@x.example>", None, "a@b.example", None, "hi", "hello", datetime.now(UTC))
    )
    assert inbox.run(rc_for(), mailbox=box) == {"skipped": "outreach off"}


def test_without_a_mailbox_or_on_a_gmail_error_nothing_moves(outreach_on: str) -> None:
    assert inbox.run(rc_for()) == {"skipped": "no mailbox connected"}
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(world.reply("hello"))

    def refuse(since: str | None) -> tuple[list[Incoming], str]:
        raise MailboxError("auth", "token revoked")

    box.fetch_new = refuse  # type: ignore[method-assign]
    assert _run(box) == {"skipped": "mailbox error: auth"}
    assert _cursor(world) is None and world.incoming() == []


def test_a_dry_run_only_counts(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(world.reply("hello"))
    assert _run(box, dry_run=True) == {"fetched": 1, "skipped": "dry run"}
    assert world.incoming() == [] and _cursor(world) is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Yes, send it.\n\nOn Mon, 16 Nov 2026 at 10:00, Nument <hello@nument.example> wrote:\n> Hi", "Yes, send it."),
        ("Sure!\n> quoted\n> more", "Sure!"),
        ("Sounds good\n\nOn Mon, 16 Nov 2026 at 10:00 Nument <\nhello@nument.example> wrote:\n> Hi", "Sounds good"),
        ("Ok\n-----Original Message-----\nFrom: Nument", "Ok"),
        ("Thanks\n\nSent from my iPhone", "Thanks"),
        ("Line one\nline two", "Line one\nline two"),
        ("", ""),
    ],
)
def test_new_text_drops_the_quoted_history(body: str, expected: str) -> None:
    assert inbox.new_text(body) == expected


def test_opt_out_subjects() -> None:
    def msg(subject: str) -> Incoming:
        return Incoming("g", "t", None, None, "a@b.example", None, subject, "", datetime.now(UTC))

    assert inbox.is_opt_out_email(msg("unsubscribe")) and inbox.is_opt_out_email(msg("Unsubscribe."))
    assert inbox.is_opt_out_email(msg("Re: unsubscribe me"))
    assert not inbox.is_opt_out_email(msg("Re: your seed round")) and not inbox.is_opt_out_email(msg(""))


def test_message_ids_normalise_brackets() -> None:
    base = Incoming("g", "t", None, "abc@host.example", "a@b.example", None, "s", "", datetime.now(UTC))
    assert inbox.message_ids(base) == ["<abc@host.example>"]
    assert inbox.message_ids(replace(base, in_reply_to=None)) == []
