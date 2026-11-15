"""Proposal drafts (contract 4.8): filling content from call notes, the promises code keeps, and never overwriting."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import ProposalDraft, ProposalMilestone
from nument_engine.outreach import proposals

from .outreach_world import World, add_offer, add_plan_page, make_world, rc_for
from .pipeline_fakes import AllProvidersDown, BudgetExceeded, FakeRouter

EN, EM = chr(0x2013), chr(0x2014)  # written as code points: no dash ever sits in a source file

DRAFT = ProposalDraft(
    title=f"Brightcart ordering app {EM} first version",
    problem="Grocers cannot order online; the Bubble app is slow.",
    scope_must=["Ordering", "Grocer dashboard"],
    scope_later=["Delivery tracking"],
    milestones=[
        ProposalMilestone(name="Design and setup", weeks=1, deliverables=["Clickable design"], price_usd=1500),
        ProposalMilestone(name="Build", weeks=4, deliverables=["Ordering", "Dashboard"], price_usd=4500),
    ],
    total_range=f"$5,000{EN}$7,000",
    guarantee="We guarantee you'll love it.",
    retainer="Monthly product care after launch.",
    next_step="Reply yes and we start milestone 1 on Monday.",
)


@pytest.fixture
def outreach_on(engine_db: str) -> Iterator[str]:
    before = db.get_setting("outreach.mode")
    db.set_setting("outreach.mode", "manual")
    # The session database is shared: proposals other tests left empty must not be drafted here.
    db.execute("update public.proposals set content = '{\"left_by\": \"another test\"}' where content = '{}'::jsonb")
    yield engine_db
    db.set_setting("outreach.mode", before if before is not None else "off")


def proposal(world: World, notes: str | None, **over: Any) -> str:
    row = world.one(
        "insert into public.proposals (lead_id, call_notes, status, content) values (%s, %s, %s, %s::jsonb) "
        "returning id::text as id",
        [world.lead_id, notes, over.get("status", "draft"), over.get("content", "{}")],
    )
    return str(row["id"])


def content(world: World, pid: str) -> dict[str, Any]:
    return dict(world.one("select content, model from public.proposals where id = %s", [pid]))


def test_a_proposal_is_drafted_from_the_call_notes(outreach_on: str) -> None:
    world = make_world(outreach_on)
    add_offer(world)
    add_plan_page(world)
    pid = proposal(world, "Wants ordering plus a grocer dashboard in 6 weeks. Budget about $6k. Maya decides.")
    seen: list[dict[str, Any]] = []

    def write(inputs: dict[str, Any]) -> ProposalDraft:
        seen.append(inputs)
        return DRAFT

    stats = proposals.run(rc_for(), router=FakeRouter({"write_proposal": write}))
    assert stats == {"drafted": 1, "waiting": 1}
    row = content(world, pid)
    c = row["content"]
    assert c["guarantee"] == proposals.GUARANTEE
    assert [m["price_usd"] for m in c["milestones"]] == [1500, 4500]  # the notes name a budget
    assert c["title"] == "Brightcart ordering app, first version" and c["total_range"] == "$5,000 to $7,000"
    assert row["model"].startswith("gemini:gemini-3-flash#write_proposal.v")
    inputs = seen[0]
    assert inputs["offer"].startswith("No-code to real app:") and inputs["typical_range"] == "usually $4,000 to $15,000"
    assert inputs["plan"] == {"headline": "Brightcart app rebuild in 5 weeks"} and inputs["founder_name"] == "Maya Chen"
    [act] = [a for a in world.activities("ai_output") if a["payload"].get("kind") == "proposal_drafted"]
    assert act["payload"]["proposal_id"] == pid


def test_no_budget_in_the_notes_means_no_prices(outreach_on: str) -> None:
    world = make_world(outreach_on)
    pid = proposal(world, "Wants ordering plus a dashboard. Timeline 6 weeks for 10k users.")
    proposals.run(rc_for(), router=FakeRouter({"write_proposal": [DRAFT]}))
    assert [m["price_usd"] for m in content(world, pid)["content"]["milestones"]] == [None, None]


def test_filled_moved_or_empty_proposals_are_left_alone(outreach_on: str) -> None:
    world = make_world(outreach_on)
    filled = proposal(world, "Budget $5k.", content='{"title": "Written by hand"}')
    sent = proposal(world, "Budget $5k.", status="sent")
    empty = proposal(world, "   ")
    router = FakeRouter({"write_proposal": [DRAFT]})
    stats = proposals.run(rc_for(), router=router)
    assert stats["waiting"] == 0 and router.calls == []
    assert content(world, filled)["content"] == {"title": "Written by hand"}
    assert content(world, sent)["content"] == {} and content(world, empty)["content"] == {}


def test_failures_leave_the_proposal_for_the_next_run(outreach_on: str) -> None:
    world = make_world(outreach_on)
    pid = proposal(world, "Budget $5k.")
    assert proposals.run(rc_for(), router=FakeRouter({"write_proposal": [AllProvidersDown("x")]}))["ai.failed"] == 1
    assert (
        proposals.run(rc_for(), router=FakeRouter({"write_proposal": [BudgetExceeded("cap")]}))["stopped.budget"] == 1
    )
    assert content(world, pid)["content"] == {}
    assert proposals.run(rc_for(dry_run=True), router=FakeRouter({}))["skipped"] == "dry run"
    db.set_setting("outreach.mode", "off")
    assert proposals.run(rc_for(), router=FakeRouter({})) == {"skipped": "outreach off"}


@pytest.mark.parametrize(
    ("notes", "budget"),
    [
        ("Budget about $6k", True),
        ("They can spend 5 lakh", True),
        ("USD 8000 for the first version", True),
        ("budget is around 7000", True),
        ("₹4,00,000 approved", True),
        ("Timeline 6 weeks for 10k users", False),
        ("No budget discussed yet", False),
        ("", False),
    ],
)
def test_has_budget(notes: str, budget: bool) -> None:
    assert proposals.has_budget(notes) is budget


def test_plain_text_has_no_dashes() -> None:
    assert proposals.plain(f"$4,000{EN}$8,000") == "$4,000 to $8,000"
    assert proposals.plain(f"Fast {EM} and simple") == "Fast, and simple"
    assert proposals.plain(f"2{EN}3 weeks") == "2 to 3 weeks"
