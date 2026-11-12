"""Review pain from public review texts (Practo stories, Google Maps reviews): recent reviews only, a quote that
is really in a review, the Places patterns when no AI answers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nument_engine.models import ReviewPainClassification
from nument_engine.sources import review_pain
from nument_engine.sources.review_pain import ReviewText

from .sources_helpers import FakeRouter, ctx, no_network, segment

__all__ = ["no_network"]

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
CALLS = ReviewText("Doctor is fine. Called four times to book and nobody picked up the phone. Walked in instead.", 20)
GOOD = ReviewText("Painless root canal, very kind doctor.", 40, 5.0)
OLD = ReviewText("Nobody picks up the phone here.", 400, 1.0)
UNDATED = ReviewText("Phone is always busy.", None)


def verdict(**over: object) -> ReviewPainClassification:
    values: dict[str, object] = {
        "has_pain": True,
        "flags": ["unanswered_calls"],
        "complaining_reviews": [1],
        "quote": "Called four times to book and nobody picked up the phone.",
    }
    values.update(over)
    return ReviewPainClassification.model_validate(values)


def test_only_dated_reviews_of_the_last_90_days_count_newest_first() -> None:
    assert review_pain.recent([GOOD, OLD, UNDATED, CALLS, ReviewText("  ", 1)]) == [CALLS, GOOD]


def test_the_ai_finding_keeps_the_sentence_as_written() -> None:
    router = FakeRouter({"classify_reviews": [verdict()]})
    c = ctx(router)
    pain = review_pain.classify(c, [GOOD, CALLS, OLD], business_name="Lotus", source="maps_reviews")
    assert pain is not None and pain.how == "ai" and pain.flags == ["unanswered_calls"]
    assert pain.quote == "Called four times to book and nobody picked up the phone."
    assert (pain.matching_reviews, pain.of_reviews, pain.newest_flag_age_days) == (1, 2, 20)
    task, inputs = router.calls[0]
    assert task == "classify_reviews" and inputs["source"] == "Google Maps reviews"
    assert [r["n"] for r in inputs["reviews"]] == [1, 2] and inputs["reviews"][0]["age"] == "2 weeks ago"
    assert all("Nobody picks up" not in r["text"] for r in inputs["reviews"])  # the old review is never sent


def test_a_quote_that_is_not_in_any_review_drops_the_finding() -> None:
    c = ctx(FakeRouter({"classify_reviews": [verdict(quote="Patients wait hours for a call back.")]}))
    assert review_pain.classify(c, [CALLS], business_name="Lotus", source="practo") is None
    assert c.stats["practo.reviews_quote_not_found"] == 1


def test_no_pain_and_unknown_flags_give_nothing() -> None:
    c = ctx(FakeRouter({"classify_reviews": [verdict(has_pain=False, flags=[], quote=None)]}))
    assert review_pain.classify(c, [CALLS], business_name="Lotus", source="practo") is None


def test_no_recent_review_means_no_ai_call() -> None:
    router = FakeRouter({"classify_reviews": []})
    assert review_pain.classify(ctx(router), [OLD, UNDATED], business_name="Lotus", source="practo") is None
    assert router.calls == []


def test_without_a_router_the_places_patterns_decide() -> None:
    c = ctx(None)
    pain = review_pain.classify(c, [GOOD, CALLS], business_name="Lotus", source="practo")
    assert pain is not None and pain.how == "rules" and pain.flags == ["unanswered_calls"]
    assert pain.quote == "Called four times to book and nobody picked up the phone."
    assert review_pain.by_rules([GOOD]) is None
    slow = review_pain.by_rules([ReviewText("Sent a WhatsApp message, no reply for days.", 5)])
    assert slow is not None and slow.flags == ["slow_replies"]


def test_the_signal_carries_the_quote_the_url_and_a_monthly_key() -> None:
    pain = review_pain.Pain(["long_wait", "unanswered_calls"], 2, 5, 12, "Nobody picked up.", "ai")
    sig = review_pain.pain_signal(
        pain, source="practo", business_id="b1", url="https://www.practo.com/pune/clinic/x", seg=segment(), now=NOW
    )
    assert sig.type == "review_pain" and sig.source == "practo" and sig.quote == "Nobody picked up."
    assert sig.observed_at == NOW - timedelta(days=12) and sig.evidence_key == "practo|b1|2026-11"
    assert sig.points == 7.0  # clinics-in gives review pain 7, already the most a second review can reach
    assert (
        sig.details["flags"] == ["long_wait", "unanswered_calls"] and sig.details["where"] == "Practo patient stories"
    )
    single = review_pain.pain_signal(
        review_pain.Pain(["slow_replies"], 1, 3, None, "No reply.", "rules"), source="maps_reviews", business_id="b2",
        url=None, now=NOW,
    )  # fmt: skip
    assert single.points == 6.0 and single.observed_at == NOW
    double = review_pain.pain_signal(
        review_pain.Pain(["slow_replies"], 2, 3, 1, "No reply.", "ai"), source="maps_reviews", business_id="b3",
        url=None, now=NOW,
    )  # fmt: skip
    assert double.points == 7.0  # the A.12.3 default 6, plus one for a second complaining review


def test_find_quote_tolerates_spacing_and_case() -> None:
    texts = ["Great doctor.\nBut   NOBODY picked up the phone for two days!"]
    assert review_pain.find_quote("nobody picked up the phone for two days", texts) == (
        0,
        "But   NOBODY picked up the phone for two days!",
    )
    assert review_pain.find_quote("short", texts) is None
