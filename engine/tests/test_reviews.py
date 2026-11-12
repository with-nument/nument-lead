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
