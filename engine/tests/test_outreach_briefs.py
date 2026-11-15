"""Pre-call briefs (contract 4.8): timing, once per booking, a reschedule, failures and what the writer sees."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from nument_engine import db
from nument_engine.models import PrecallBrief
from nument_engine.ops import emails, notify
from nument_engine.outreach import briefs, inbox

from .outreach_world import World, add_offer, make_world, rc_for
from .pipeline_fakes import AllProvidersDown, FakeRouter

BRIEF = PrecallBrief(
    summary="Brightcart, two founders, pre-seed, ordering app on Bubble.",
    why_now="Raised a pre-seed and the Bubble app is slowing them down.",
    what_they_need=["Rebuild the ordering app before the next raise"],
    questions=["What must the first version do?", "When is the raise?", "Who decides on budget?"],
    offer_key="nocode_to_app",
    risks=["No budget mentioned yet"],
)


@pytest.fixture
def outreach_on(engine_db: str) -> Iterator[str]:
    before = db.get_setting("outreach.mode")
    db.set_setting("outreach.mode", "manual")
    # The session database is shared: calls booked by other tests must not be due in this one.
    db.execute("update public.leads set meeting_at = null where meeting_at is not null")
    yield engine_db
    db.set_setting("outreach.mode", before if before is not None else "off")


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch) -> list[notify.Email]:
    sent: list[notify.Email] = []

    def deliver(kind: str, build: Callable[[bool], notify.Email]) -> int:
        assert kind == "alerts"
        sent.append(build(True))
        return 1

    monkeypatch.setattr(notify, "email_configured", lambda: True)
    monkeypatch.setattr(emails, "deliver", deliver)
    return sent


def book(
    world: World, minutes: float, *, uid: str = "u-1", notes: str | None = "Rebuild before the next raise."
) -> datetime:
    at = (datetime.now(UTC) + timedelta(minutes=minutes)).replace(microsecond=0)
    world.run_sql(
        "update public.leads set meeting_at = %s, stage = 'discovery_booked' where id = %s", [at, world.lead_id]
    )
    world.run_sql(
        "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'booking', %s)",
        [
            world.lead_id,
            Jsonb(
                {
                    "kind": "booked",
                    "uid": uid,
                    "start": at.isoformat(),
                    "notes": notes,
                    "location": "https://app.cal.com/video/u-1",
                }
            ),
        ],
    )
    return at


def _brief_router(seen: list[dict[str, Any]] | None = None, output: PrecallBrief = BRIEF) -> FakeRouter:
    def write(inputs: dict[str, Any]) -> PrecallBrief:
        if seen is not None:
            seen.append(inputs)
        return output

    return FakeRouter({"write_precall_brief": write})


def _briefs(world: World) -> list[dict[str, Any]]:
    return [a["payload"] for a in world.activities("brief")]


def test_a_brief_goes_out_once_about_an_hour_before(outreach_on: str, mailer: list[notify.Email]) -> None:
    world = make_world(outreach_on)
    add_offer(world)
    at = book(world, 70)
    seen: list[dict[str, Any]] = []
    stats = briefs.run(rc_for(), router=_brief_router(seen))
    assert stats["sent"] == 1
    [email] = mailer
    assert email.subject.startswith("Call brief: Brightcart, Maya Chen, ") and email.subject.endswith("India time")
    assert "Ask them" in email.text and "When is the raise?" in email.text
    assert "What they wrote when booking:\nRebuild before the next raise." in email.text
    assert f"/leads/{world.lead_id}" in email.html and "Join the call" in email.html
    [logged] = _briefs(world)
    assert logged["sent"] == 1 and logged["meeting_at"] == at.astimezone(UTC).isoformat()
    assert logged["content"]["offer_key"] == "nocode_to_app" and logged["uid"] == "u-1"
    inputs = seen[0]
    assert inputs["offer"].startswith("nocode_to_app: No-code to real app.")
    assert inputs["booking_notes"] == "Rebuild before the next raise."
    assert "India time" in inputs["meeting_time"] and "New York time" in inputs["meeting_time"]
    assert "Us (day 0)" in inputs["thread"]
    again = briefs.run(rc_for(), router=_brief_router())
    assert again["already_sent"] == 1 and len(mailer) == 1


def test_the_window(outreach_on: str, mailer: list[notify.Email]) -> None:
    early, late, gone = make_world(outreach_on), make_world(outreach_on), make_world(outreach_on)
    book(early, 90)
    book(late, 30)  # a late run still sends it
    book(gone, 5)  # too close: never at the last minute
    stats = briefs.run(rc_for(), router=_brief_router())
    assert _briefs(early) == [] and _briefs(gone) == []
    assert len(_briefs(late)) == 1 and stats["sent"] >= 1


def test_a_reschedule_gets_a_new_brief(outreach_on: str, mailer: list[notify.Email]) -> None:
    world = make_world(outreach_on)
    book(world, 70)
    briefs.run(rc_for(), router=_brief_router())
    book(world, 65, uid="u-1")  # moved by five minutes: a new call time
    briefs.run(rc_for(), router=_brief_router())
    assert [b["sent"] for b in _briefs(world)] == [1, 1]
    assert len({b["meeting_at"] for b in _briefs(world)}) == 2


def test_without_email_nothing_is_written_or_spent(outreach_on: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "email_configured", lambda: False)
    world = make_world(outreach_on)
    book(world, 70)
    router = _brief_router()
    stats = briefs.run(rc_for(), router=router)
    assert stats["skipped"] == "email is not set up" and router.calls == [] and _briefs(world) == []


def test_a_failed_send_is_retried_with_the_same_brief(outreach_on: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "email_configured", lambda: True)
    results = [0, 1]
    monkeypatch.setattr(emails, "deliver", lambda kind, build: results.pop(0))
    world = make_world(outreach_on)
    book(world, 70)
    router = _brief_router()
    assert briefs.run(rc_for(), router=router)["send_failed"] == 1
    stats = briefs.run(rc_for(), router=router)
    assert stats["reused"] == 1 and stats["sent"] == 1
    assert router.tasks() == ["write_precall_brief"]  # written once
    assert [b["sent"] for b in _briefs(world)] == [0, 1]


def test_an_unknown_offer_key_becomes_the_leads_offer(outreach_on: str, mailer: list[notify.Email]) -> None:
    world = make_world(outreach_on)
    add_offer(world, "mvp_sprint")
    book(world, 70)
    briefs.run(rc_for(), router=_brief_router(output=BRIEF.model_copy(update={"offer_key": "magic_package"})))
    assert _briefs(world)[0]["content"]["offer_key"] == "mvp_sprint"


def test_ai_down_and_switches(outreach_on: str, mailer: list[notify.Email]) -> None:
    world = make_world(outreach_on)
    book(world, 70)
    down = FakeRouter({"write_precall_brief": [AllProvidersDown("x")]})
    stats = briefs.run(rc_for(), router=down)
    assert stats["ai.failed"] == 1 and _briefs(world) == [] and mailer == []
    assert briefs.run(rc_for(dry_run=True), router=down)["skipped"] == "dry run"
    db.set_setting("outreach.mode", "off")
    assert briefs.run(rc_for(), router=down) == {"skipped": "outreach off"}


def test_thread_text_has_both_sides_without_quotes(outreach_on: str) -> None:
    world = make_world(outreach_on)
    box = world.box()
    box.incoming.append(world.reply("Yes, let's talk.\n\nOn Mon, Nument wrote:\n> Hi Maya"))
    inbox.run(rc_for(), mailbox=box)
    text = briefs.thread_text(None, world.lead_id)
    assert text.index("Us (day 0)") < text.index("Them")
    assert "Yes, let's talk." in text and "> Hi Maya" not in text
    assert "{plan_link}" not in text  # unsent steps are not part of the conversation


def test_meeting_text() -> None:
    from zoneinfo import ZoneInfo

    at = datetime(2026, 11, 18, 14, 30, tzinfo=UTC)
    assert briefs.meeting_text(at, ZoneInfo("America/New_York")) == (
        "Wed 18 Nov, 8:00 pm India time (Wed 18 Nov, 9:30 am New York time)"
    )
    assert briefs.meeting_text(at, ZoneInfo("Asia/Kolkata")) == "Wed 18 Nov, 8:00 pm India time"
