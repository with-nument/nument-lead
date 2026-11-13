"""The founder or owner of an A or B lead from Google Search (plan 5.11.4, 13 Nov 2026): kept only when the
search backs it, the role is in charge and the line names this business."""

from __future__ import annotations

from typing import Any

from nument_engine.models import DecisionMakerLookup
from nument_engine.pipeline import people
from nument_engine.pipeline.message import greeting_contact, greeting_for


def grounding(text: str) -> dict[str, Any]:
    return {"sources": [{"uri": "https://www.linkedin.com/in/maya", "title": "LinkedIn"}],
            "supports": [{"text": text, "chunks": [0]}]}  # fmt: skip


LINE = "Decision maker: Maya Chen, Co-founder and CEO at Brightcart"
BACKED = grounding("Maya Chen - Co-founder and CEO - Brightcart | LinkedIn")


def out(**kw: Any) -> DecisionMakerLookup:
    return DecisionMakerLookup(**{"name": "Maya Chen", "role": "Co-founder and CEO", "line": LINE, **kw})


def test_a_backed_founder_of_this_business_is_kept() -> None:
    got = people.accepted(out(), BACKED, "Brightcart Inc")
    assert got is not None and got["name"] == "Maya Chen" and got["role"] == "Co-founder and CEO"
    assert "Maya Chen" in got["quote"] and got["url"] == "https://www.linkedin.com/in/maya"


def test_guesses_staff_and_other_businesses_are_dropped() -> None:
    assert people.accepted(out(), grounding("Brightcart raises seed round"), "Brightcart") is None  # not backed
    assert people.accepted(out(role="Software Engineer"), BACKED, "Brightcart") is None  # not in charge
    assert people.accepted(out(name="Maya"), BACKED, "Brightcart") is None  # a first name alone
    assert people.accepted(out(line="Decision maker: Maya Chen, CEO at Leafcart"), BACKED, "Brightcart") is None
    assert people.accepted(out(name="unknown", role=None, line="Decision maker: unknown"), BACKED, "X") is None


def test_a_searched_founder_is_greeted_by_first_name() -> None:
    searched = {"name": "Maya Chen", "role": "Co-founder and CEO", "is_decision_maker": True, "verified": True,
                "source": "other", "quote": "Maya Chen - Co-founder and CEO - Brightcart"}  # fmt: skip
    assert greeting_for(greeting_contact([searched]))[0] == "Hi Maya,"
    assert greeting_contact([{**searched, "quote": None}]) is None  # an unbacked name is never used
