"""Cal.com booking invites (RFC 5545): parsing, and booking, reschedule and cancel through the inbox."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.outreach import bookings, inbox
from nument_engine.outreach.bookings import CalendarEvent, Current, Party
from nument_engine.outreach.gmail import FakeMailbox, Incoming

from . import outreach_world
from .outreach_world import World, fixture, make_world, rc_for

# ---------------------------------------------------------------------------
# Parsing (no database)
# ---------------------------------------------------------------------------


def test_calcom_booking_parses() -> None:
    [ev] = bookings.parse_ics(fixture("calcom_booking.ics"))
    assert ev.uid == "4qJ2tYkWmQ8rZp1sN7vX3c"
    assert (ev.method, ev.status, ev.sequence, ev.cancelled) == ("REQUEST", "CONFIRMED", 0, False)
    assert ev.start == datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
    assert ev.end == datetime(2026, 11, 18, 15, 0, tzinfo=UTC)
    assert ev.organizer == Party("calls@nument.example", "Nument")
    assert ev.attendees == (Party("maya@brightcart.example", "Maya Chen"),)
    # folded lines are joined, and escaped commas and newlines are text again
    assert "Bubble app before the next raise, ideally in 6 weeks." in ev.description
    assert "Invitee Time Zone:\nAmerica/New_York" in ev.description
    assert ev.parties()[0].email == "maya@brightcart.example"


def test_reschedule_and_cancel_parse() -> None:
    [moved] = bookings.parse_ics(fixture("calcom_reschedule.ics"))
    assert moved.uid == "4qJ2tYkWmQ8rZp1sN7vX3c" and moved.sequence == 1
    assert moved.start == datetime(2026, 11, 19, 16, 0, tzinfo=UTC)
    [gone] = bookings.parse_ics(fixture("calcom_cancel.ics"))
    assert (gone.method, gone.status, gone.cancelled) == ("CANCEL", "CANCELLED", True)


def test_google_invite_with_tzid_quoted_names_and_folding() -> None:
    [ev] = bookings.parse_ics(fixture("google_invite_tzid.ics"))
    assert ev.tzid == "America/Los_Angeles"
    assert ev.start == datetime(2026, 11, 20, 17, 0, tzinfo=UTC)  # 09:00 PST
    assert ev.end == datetime(2026, 11, 20, 17, 30, tzinfo=UTC)
    assert ev.organizer == Party("leo@quillpad.example", "Leo Park")
    assert Party("hello.nument@gmail.com", "Nument, Team") in ev.attendees
    assert ev.parties()[-1] == ev.organizer


def test_all_day_and_garbage_are_not_bookings() -> None:
    [allday] = bookings.parse_ics(fixture("all_day_event.ics"))
    assert allday.start is None
    assert bookings.bookable([allday]) == []
    assert bookings.parse_ics("") == [] and bookings.parse_ics("not a calendar at all") == []
    no_uid = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20261118T143000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    assert bookings.parse_ics(no_uid) == []


def test_parse_line_handles_quoted_parameters() -> None:
    name, params, value = bookings.parse_line('ATTENDEE;CN="Chen; Maya: CEO";ROLE=REQ-PARTICIPANT:mailto:m@x.example')
    assert name == "ATTENDEE" and value == "mailto:m@x.example"
    assert params == {"CN": "Chen; Maya: CEO", "ROLE": "REQ-PARTICIPANT"}
    assert bookings.parse_line("DTSTART;TZID=Europe/London:20261118T090000") == (
        "DTSTART",
        {"TZID": "Europe/London"},
        "20261118T090000",
    )


@pytest.mark.parametrize(
    ("value", "params", "expected"),
    [
        ("20261118T143000Z", {}, datetime(2026, 11, 18, 14, 30, tzinfo=UTC)),
        ("20261118T090000", {"TZID": "Europe/London"}, datetime(2026, 11, 18, 9, 0, tzinfo=UTC)),
        ("20260718T090000", {"TZID": "Europe/London"}, datetime(2026, 7, 18, 8, 0, tzinfo=UTC)),  # summer time
        ("20261118T090000", {"TZID": "Eastern Standard Time"}, datetime(2026, 11, 18, 14, 0, tzinfo=UTC)),
        ("20261118T090000", {"TZID": "Mars/Olympus"}, None),  # unknown zone: never guess
        ("20261118T090000", {}, None),  # floating time without a calendar zone
        ("20261118", {"VALUE": "DATE"}, None),
        ("2026-11-18", {}, None),
    ],
)
def test_parse_datetime(value: str, params: dict[str, str], expected: datetime | None) -> None:
    assert bookings.parse_datetime(value, params) == expected


def test_parse_duration() -> None:
    assert bookings.parse_duration("PT30M") == timedelta(minutes=30)
    assert bookings.parse_duration("P1DT2H") == timedelta(days=1, hours=2)
    assert bookings.parse_duration("-PT15M") == timedelta(minutes=-15)
    assert bookings.parse_duration("P") is None and bookings.parse_duration("soon") is None
    ics = fixture("calcom_booking.ics").replace("DTEND:20261118T150000Z", "DURATION:PT45M")
    [ev] = bookings.parse_ics(ics)
    assert ev.end == datetime(2026, 11, 18, 15, 15, tzinfo=UTC)


def _ev(uid: str = "u1", seq: int = 0, start: datetime | None = None, method: str = "REQUEST") -> CalendarEvent:
    return CalendarEvent(
        uid=uid,
        method=method,
        status="CANCELLED" if method == "CANCEL" else "CONFIRMED",
        sequence=seq,
        start=start or datetime(2026, 11, 18, 14, 30, tzinfo=UTC),
        end=None,
        tzid=None,
        organizer=None,
    )


T1 = datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
T2 = datetime(2026, 11, 19, 16, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("event", "current", "expected"),
    [
        (_ev(), None, "booked"),
        (_ev(), Current("u1", 0, T1, False), "duplicate"),
        (_ev(seq=1, start=T2), Current("u1", 0, T1, False), "rescheduled"),
        (_ev(seq=0, start=T1), Current("u1", 1, T2, False), "stale"),  # an older copy arriving late
        (_ev(uid="u2", start=T2), Current("u1", 0, T1, False), "rescheduled"),  # a reschedule with a new UID
        (_ev(uid="u2", start=T1), Current("u1", 0, T1, False), "duplicate"),  # a second calendar's copy
        (_ev(method="CANCEL", seq=2), Current("u1", 1, T2, False), "cancelled"),
        (_ev(method="CANCEL", seq=2), Current("u1", 2, None, True), "duplicate"),
        (_ev(uid="u1", method="CANCEL", seq=1), Current("u2", 0, T2, False), "stale"),  # the replaced booking
        (_ev(method="CANCEL"), None, "stale"),
        (_ev(uid="u3", start=T2), Current("u1", 2, None, True), "booked"),  # a new booking after a cancel
        (_ev(seq=3, start=T2), Current("u1", 2, None, True), "booked"),  # the same booking made again
    ],
)
def test_decide(event: CalendarEvent, current: Current | None, expected: str) -> None:
    assert bookings.decide(event, current) == expected


# ---------------------------------------------------------------------------
# Through the inbox (throwaway database)
# ---------------------------------------------------------------------------


@pytest.fixture
def outreach_on(engine_db: str) -> Iterator[str]:
    before = db.get_setting("outreach.mode")
    db.set_setting("outreach.mode", "manual")
    yield engine_db
    outreach_world.cleanup()
    db.set_setting("outreach.mode", before if before is not None else "off")


def _invite(world: World, name: str, n: int, *, sender: str = "notifications@cal.example") -> Incoming:
    return Incoming(
        gmail_message_id=f"cal-{world.tag}-{n}",
        gmail_thread_id=f"calthread-{world.tag}-{n}",
        rfc_message_id=f"<cal-{world.tag}-{n}@cal.example>",
        in_reply_to=None,
        from_email=sender,
        from_name="Cal.com",
        subject="New event: Intro call between Nument and Maya Chen",
        body_text="A new event has been scheduled.",
        received_at=datetime.now(UTC) - timedelta(minutes=30 - n),
        calendar_ics=fixture(name).replace("maya@brightcart.example", world.email),
    )


def _run(box: FakeMailbox) -> dict[str, Any]:
    return inbox.run(rc_for(), mailbox=box)


def _reread(world: World, box: FakeMailbox) -> dict[str, Any]:
    """Read the same mail again from an old cursor (a re-run after a crash)."""
    db.set_setting(inbox.CURSOR_KEY.format(address=world.mailbox), "0")
    again = world.box()
    again.incoming = list(box.incoming)
    return inbox.run(rc_for(), mailbox=again)


def _bookings(world: World) -> list[dict[str, Any]]:
    return [a["payload"] for a in world.activities("booking")]


def test_booking_books_the_call_and_stops_the_sequence(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(_invite(world, "calcom_booking.ics", 1))
    stats = _run(box)
    assert stats["booking.booked"] == 1
    lead = world.lead()
    assert lead["stage"] == "discovery_booked" and lead["meeting_at"] == T1
    thread = world.thread()
    assert (thread["status"], thread["stop_reason"]) == ("stopped", "booking")
    assert world.statuses() == {0: "sent", 3: "cancelled", 7: "cancelled", 12: "cancelled"}
    [booking] = _bookings(world)
    assert booking["kind"] == "booked" and booking["uid"] == "4qJ2tYkWmQ8rZp1sN7vX3c"
    assert booking["matched_by"] == "attendee_thread" and booking["start"] == T1.isoformat()
    assert box.read == {f"cal-{world.tag}-1"}  # machine mail the engine handled is marked read
    assert world.incoming() == []  # a booking notice is not a reply


def test_booking_copies_reschedule_and_cancel(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming += [_invite(world, "calcom_booking.ics", 1), _invite(world, "calcom_booking.ics", 2)]
    stats = _run(box)
    assert stats["booking.booked"] == 1 and stats["booking.duplicate"] == 1
    assert len(_bookings(world)) == 1  # the second copy changed nothing
    box.incoming.append(_invite(world, "calcom_reschedule.ics", 3))
    assert _run(box)["booking.rescheduled"] == 1
    assert world.lead()["meeting_at"] == T2 and world.lead()["stage"] == "discovery_booked"
    assert _bookings(world)[-1]["previous_start"] == T1.isoformat()
    box.incoming.append(_invite(world, "calcom_cancel.ics", 4))
    assert _run(box)["booking.cancelled"] == 1
    lead = world.lead()
    assert lead["meeting_at"] is None and lead["stage"] == "talking"
    assert [b["kind"] for b in _bookings(world)] == ["booked", "rescheduled", "cancelled"]
    # Reading the same mail again (a crashed run) changes nothing.
    again = _reread(world, box)
    assert again["fetched"] == 4 and "booking.booked" not in again and "booking.rescheduled" not in again
    assert len(_bookings(world)) == 3 and world.lead()["meeting_at"] is None


def test_reschedule_with_a_new_uid_ignores_the_old_cancel(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming += [
        _invite(world, "calcom_booking.ics", 1),
        _invite(world, "calcom_reschedule_new_uid.ics", 2),
        _invite(world, "calcom_cancel_old_uid.ics", 3),
    ]
    stats = _run(box)
    assert stats["booking.booked"] == 1 and stats["booking.rescheduled"] == 1 and stats["booking.stale"] == 1
    lead = world.lead()
    assert lead["meeting_at"] == datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
    assert lead["stage"] == "discovery_booked"


def test_invite_from_the_founder_with_our_mailbox_as_attendee(outreach_on: str) -> None:
    world = make_world(outreach_on, stage="talking")
    box = world.box()
    ics = (
        fixture("google_invite_tzid.ics")
        .replace("leo@quillpad.example", world.email)
        .replace("hello.nument@gmail.com", world.mailbox)
    )
    box.incoming.append(replace(_invite(world, "calcom_booking.ics", 1, sender=world.email), calendar_ics=ics))
    stats = _run(box)
    assert stats["booking.booked"] == 1
    assert world.lead()["meeting_at"] == datetime(2026, 11, 20, 17, 0, tzinfo=UTC)
    [booking] = _bookings(world)
    assert booking["tz"] == "America/Los_Angeles" and booking["matched_by"] == "attendee_thread"


def test_booking_by_another_address_at_the_company_domain(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    msg = _invite(world, "calcom_booking.ics", 1)
    other = f"leo@{world.domain}"
    box.incoming.append(replace(msg, calendar_ics=(msg.calendar_ics or "").replace(world.email, other)))
    assert _run(box)["booking.booked"] == 1
    assert _bookings(world)[0]["matched_by"] == "attendee_domain"


def test_unmatched_invite_is_left_for_the_founder(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    msg = _invite(world, "calcom_booking.ics", 1)
    stranger = (msg.calendar_ics or "").replace(world.email, "someone@unknown-startup.example")
    box.incoming.append(replace(msg, calendar_ics=stranger))
    stats = _run(box)
    assert stats["unmatched"] == 1 and box.read == set()
    assert world.lead()["meeting_at"] is None and _bookings(world) == []


def test_a_closed_lead_whose_business_has_another_open_lead_keeps_its_stage(outreach_on: str) -> None:
    world = make_world(outreach_on, stage="not_now")
    score = world.one("select score_id from public.leads where id = %s", [world.lead_id])["score_id"]
    world.run_sql(
        "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, channel) "
        "values (%s, 'firms-us', %s, 'A', 'stated_need', 'email')",
        [world.business_id, score],
    )
    box = world.box()
    box.incoming.append(_invite(world, "calcom_booking.ics", 1))
    assert _run(box)["booking.booked"] == 1  # no error: the call is recorded, the stage stays
    lead = world.lead()
    assert lead["stage"] == "not_now" and lead["meeting_at"] == T1
    assert _bookings(world)[0]["stage_kept"] is True


def test_a_lead_past_discovery_keeps_its_stage(outreach_on: str) -> None:
    world = make_world(outreach_on, stage="proposal_sent")
    box = world.box()
    box.incoming.append(_invite(world, "calcom_booking.ics", 1))
    assert _run(box)["booking.booked"] == 1
    lead = world.lead()
    assert lead["stage"] == "proposal_sent" and lead["meeting_at"] == T1
