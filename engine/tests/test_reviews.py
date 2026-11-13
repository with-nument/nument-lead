"""Public review numbers through search grounding (the Places fallback): only backed numbers are stored."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import ReviewLookup
from nument_engine.pipeline import reviews
from nument_engine.pipeline.prefilter import eval_size_rule
from nument_engine.segments import load_segments

from . import pipeline_fakes as pf

GROUNDING = {
    "queries": ["Yogiraj Centre for Dermatology Bengaluru google reviews"],
    "sources": [{"uri": "https://vertexaisearch.example/redirect/1", "title": "google.com"}],
    "supports": [{"text": "Google: 4.6 stars from 874 reviews", "chunks": [0]}],
}


def lookup(**over: Any) -> ReviewLookup:
    values: dict[str, Any] = {
        "google_rating": 4.6,
        "google_review_count": 874,
        "google_quote": "Google: 4.6 stars from 874 reviews",
        "practo_rating": None,
        "practo_story_count": None,
        "practo_quote": None,
        "complaint": None,
    }
    values.update(over)
    return ReviewLookup(**values)


@dataclass
class Result:
    output: ReviewLookup
    grounding: dict[str, Any] | None
    tag: str = "gemini:gemini-3.8-flash#lookup_reviews.v1"
    inr: float = 0.25


@dataclass
class Budget:
    left: int = 10

    def grounding_quota_left(self) -> int:
        return self.left


@dataclass
class FakeRouter:
    answers: list[Result]
    budget: Budget = field(default_factory=Budget)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run_result(self, task: str, inputs: dict[str, Any], **_: Any) -> Result:
        assert task == "lookup_reviews"
        self.calls.append(inputs)
        return self.answers.pop(0)


@pytest.mark.parametrize(
    ("value", "text", "expected"),
    [
        (874, "Google: 4.6 stars from 874 reviews", True),
        (1234, "4.8 from 1,234 reviews", True),
        (123456, "rated 4.9 by 1,23,456 patients", True),  # Indian grouping
        (4.6, "Google: 4.6 stars from 874 reviews", True),
        (874, "from 8741 reviews", False),  # never part of a longer number
        (874, "from 1874 reviews", False),
        (4.6, "rated 4.65 overall", False),
    ],
)
def test_a_number_counts_only_as_a_whole_number(value: float, text: str, expected: bool) -> None:
    assert reviews.number_supported(value, [text]) is expected


def test_only_numbers_backed_by_the_search_are_accepted() -> None:
    found = reviews.accepted(lookup(), GROUNDING)
    assert found["google"] == {"count": 874, "quote": "Google: 4.6 stars from 874 reviews", "rating": 4.6}
    assert reviews.accepted(lookup(google_review_count=900), GROUNDING) == {}  # not in what the search backed
    assert reviews.accepted(lookup(), {**GROUNDING, "sources": []}) == {}  # no source, no number
    assert reviews.accepted(lookup(), None) == {}


@pytest.fixture
def seg_db(engine_db: str) -> Iterator[str]:
    pf.wipe_segment(engine_db)
    yield engine_db
    pf.wipe_segment(engine_db)


def test_the_stage_stores_backed_numbers_once_and_keeps_places_data(seg_db: str) -> None:
    with pf.connect(seg_db) as conn:
        bid = pf.business(conn, review_count=None, rating=None)
        places_bid = pf.business(conn, review_count=40, places_fetched_at=datetime.now(UTC))
    router = FakeRouter([Result(lookup(), GROUNDING)])
    stats = reviews.run(pf.rc_for(), router=router)
    assert stats["looked_up"] == 1 and stats["google_found"] == 1 and stats["inr"] == 0.25
    assert len(router.calls) == 1 and router.calls[0]["country"] == "the UAE"  # the Places business was skipped
    row = db.fetch_one("select review_count, rating, extra from public.businesses where id = %s", [bid])
    assert row is not None and row["review_count"] == 874 and float(row["rating"]) == 4.6
    assert row["extra"]["reviews_src"] == "grounded_search" and row["extra"]["reviews_at"]
    fact = db.fetch_one("select * from public.facts where business_id = %s and field = 'google_reviews'", [bid])
    assert fact is not None and fact["verified"] and fact["quote"] == "Google: 4.6 stars from 874 reviews"
    places = db.fetch_one("select review_count from public.businesses where id = %s", [places_bid])
    assert places is not None and places["review_count"] == 40
    again = reviews.run(pf.rc_for(), router=FakeRouter([]))
    assert again["candidates"] == 0  # looked up today: not again for 30 days


def test_an_unbacked_answer_is_remembered_but_stores_no_number(seg_db: str) -> None:
    with pf.connect(seg_db) as conn:
        bid = pf.business(conn, review_count=None, rating=None)
    reviews.run(pf.rc_for(), router=FakeRouter([Result(lookup(google_review_count=5000), GROUNDING)]))
    row = db.fetch_one("select review_count, extra from public.businesses where id = %s", [bid])
    assert row is not None and row["review_count"] is None and row["extra"]["reviews_lookup_at"]


def test_the_stage_stops_when_the_search_quota_is_used(seg_db: str) -> None:
    with pf.connect(seg_db) as conn:
        pf.business(conn, review_count=None)
    router = FakeRouter([], budget=Budget(left=0))
    assert reviews.run(pf.rc_for(), router=router)["stopped_quota"] == 1 and router.calls == []


def test_a_fresh_grounded_review_count_passes_the_size_rule() -> None:
    from nument_engine.pipeline.prefilter import World

    seg = load_segments()["clinics-in"]
    rule = next(r for r in seg.size_rules.any_of if r.key == "review_count")
    now = datetime(2026, 11, 12, tzinfo=UTC)
    fresh = {"id": "b1", "review_count": 874, "extra": {"reviews_at": (now - timedelta(days=2)).isoformat()}}
    stale = {"id": "b1", "review_count": 874, "extra": {"reviews_at": (now - timedelta(days=40)).isoformat()}}
    assert eval_size_rule(rule, fresh, World(), now) is True
    assert eval_size_rule(rule, stale, World(), now) is None


class Down(Exception):
    pass


Down.__name__ = "AllProvidersDown"


def test_one_business_without_a_cited_answer_is_skipped_not_the_stage(seg_db: str) -> None:
    with pf.connect(seg_db) as conn:
        first, second = pf.business(conn, review_count=None), pf.business(conn, review_count=None)

    class Flaky(FakeRouter):
        def run_result(self, task: str, inputs: dict[str, Any], **_: Any) -> Result:
            self.calls.append(inputs)
            if len(self.calls) == 1:
                raise Down("lookup_reviews: no usable provider (answered without using web search)")
            return Result(lookup(), GROUNDING)

    stats = reviews.run(pf.rc_for(), router=Flaky([]))
    assert stats["error.AllProvidersDown"] == 1 and stats["looked_up"] == 1
    counts = {
        r["id"]: r["review_count"]
        for r in db.fetch_all(
            "select id::text as id, review_count from public.businesses where id in (%s, %s)", [first, second]
        )
    }
    assert sorted(v for v in counts.values() if v is not None) == [874]


def test_the_stage_leaves_the_end_of_the_run_to_messages_and_email(seg_db: str) -> None:
    """13 Nov 2026: 25 lookups took 16 minutes and the morning run skipped its messages and email."""
    with pf.connect(seg_db) as conn:
        pf.business(conn, review_count=None)
        pf.business(conn, review_count=None)
    rc = pf.rc_for()
    rc.deadline = datetime.now(UTC) + timedelta(seconds=reviews.RESERVE_S - 1)  # less than the reserve left
    router = FakeRouter([Result(lookup(), GROUNDING)] * 2)
    stats = reviews.run(rc, router=router)
    assert stats["stopped_time"] == 2 and router.calls == []


# ---------------------------------------------------------------------------
# The intent hunt: dated signs of need from the same grounded call (13 Nov 2026)
# ---------------------------------------------------------------------------

NOW_H = datetime(2026, 11, 13, tzinfo=UTC)
HUNT = {
    "sources": [{"uri": "https://www.naukri.com/job-listings-receptionist-1", "title": "naukri.com"}],
    "supports": [
        {"text": "Hiring: Receptionist posted 2 November 2026 on Naukri", "chunks": [0]},
        {"text": "Complaint: patients say calls are not answered and booking takes days", "chunks": [0]},
        {"text": "New branch: second centre opened in Marina on 20 October 2026", "chunks": [0]},
    ],
}
SEG_AE = load_segments()["clinics-ae"]
BIZ = {"id": "b1", "web_domain": "smile.ae"}


def hunt(**over: Any) -> ReviewLookup:
    values: dict[str, Any] = {
        "hiring_role": "Receptionist",
        "hiring_posted": "2 November 2026",
        "hiring_line": "Hiring: Receptionist posted 2 November 2026 on Naukri",
        "complaint_line": "Complaint: patients say calls are not answered and booking takes days",
        "branch_line": "New branch: second centre opened in Marina on 20 October 2026",
    }
    return lookup(**{**values, **over})


def test_backed_lines_become_snippet_signals_with_their_dates() -> None:
    sigs = reviews.intent_signals(hunt(), HUNT, BIZ, SEG_AE, NOW_H)
    by_type = {s.type: s for s in sigs}
    assert set(by_type) == {"hiring_frontdesk", "review_pain", "new_branch"}
    hire = by_type["hiring_frontdesk"]
    assert hire.points == 6.0 and hire.details["snippet_only"] and hire.details["role"] == "Receptionist"
    assert hire.observed_at == datetime(2026, 11, 2, tzinfo=UTC) and hire.url == HUNT["sources"][0]["uri"]
    assert by_type["review_pain"].details["flags"] == ["unanswered_calls", "booking_trouble"]
    assert by_type["new_branch"].observed_at == datetime(2026, 10, 20, tzinfo=UTC)


def test_unbacked_old_or_off_target_lines_make_no_signal() -> None:
    unbacked = {**HUNT, "supports": []}
    assert reviews.intent_signals(hunt(), unbacked, BIZ, SEG_AE, NOW_H) == []
    old = reviews.intent_signals(hunt(hiring_posted="2 June 2026"), HUNT, BIZ, SEG_AE, NOW_H)
    assert "hiring_frontdesk" not in {s.type for s in old}
    other_role = reviews.intent_signals(hunt(hiring_role="Dentist"), HUNT, BIZ, SEG_AE, NOW_H)
    assert "hiring_frontdesk" not in {s.type for s in other_role}
    nothing = lookup(hiring_line="Hiring: none", complaint_line="Complaint: none", branch_line="New branch: none")
    assert reviews.intent_signals(nothing, HUNT, BIZ, SEG_AE, NOW_H) == []


def test_the_stage_stores_the_hunted_signals(seg_db: str) -> None:
    with pf.connect(seg_db) as conn:
        bid = pf.business(conn, review_count=None, rating=None)
    posted = (datetime.now(UTC) - timedelta(days=5)).strftime("%d %B %Y")  # always recent, whatever today is
    lines = {
        "hiring_line": f"Hiring: Receptionist posted {posted} on Naukri",
        "branch_line": f"New branch: second centre opened in Marina on {posted}",
        "complaint_line": "Complaint: patients say calls are not answered and booking takes days",
    }
    supports = [{"text": v, "chunks": [0]} for v in lines.values()] + GROUNDING["supports"]
    hunted = {**HUNT, "supports": supports}
    stats = reviews.run(pf.rc_for(), router=FakeRouter([Result(hunt(hiring_posted=posted, **lines), hunted)]))
    assert stats["signal.hiring_frontdesk"] == 1 and stats["looked_up"] == 1
    rows = db.fetch_all("select type, points, url from public.signals where business_id = %s order by type", [bid])
    assert [r["type"] for r in rows] == ["hiring_frontdesk", "new_branch", "review_pain"]
    assert [float(r["points"]) for r in rows] == [6.0, 4.0, 5.0]  # snippet evidence counts less than a page we read
    assert all(r["url"] == HUNT["sources"][0]["uri"] for r in rows)
