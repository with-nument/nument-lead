"""The signals stage (Step 7): rows, points, expiry, dedupe, linking, the inbox and watcher isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import SignalClassification
from nument_engine.pipeline import signals as stage
from nument_engine.pipeline.signals import Signal, SignalSink, dedupe_key, to_row
from nument_engine.segments import Segment
from nument_engine.sources.base import SourceContext

from .sources_helpers import FakeRouter, clean_db, ctx, insert_business, no_network, run_context, segment

__all__ = ["clean_db", "no_network"]

SEG = segment()
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


def sig(kind: str = "hiring_frontdesk", **kw: Any) -> Signal:
    base: dict[str, Any] = {
        "type": kind,
        "source": "apna",
        "observed_at": NOW - timedelta(days=2),
        "url": "https://apna.co/job/pune/receptionist-1",
        "quote": "Clinic receptionist for our Baner branch",
        "evidence_key": "apna:1",
    }
    return Signal(**{**base, **kw})


def test_rows_take_category_points_and_window_from_the_contract() -> None:
    row = to_row(sig(), "b-1", SEG, NOW)
    assert row is not None
    assert row["category"] == "visible_pain" and row["points"] == 8.0
    assert row["expires_at"] - row["observed_at"] == timedelta(days=30)
    review = to_row(sig("review_pain", quote=None, evidence_key="pl|2026-11"), "b-1", SEG, NOW)
    assert review is not None and review["points"] == 7.0 and review["quote"] is None  # clinics-in override
    assert review["expires_at"] - review["observed_at"] == timedelta(days=90)
    funding = to_row(sig("funding", evidence_key="https://n/1"), "b-1", SEG, NOW)
    assert funding is not None and funding["category"] == "money" and funding["points"] == 0.0
    snippet = to_row(sig("public_ask", points=6.0), "b-1", SEG, NOW)
    assert snippet is not None and snippet["points"] == 6.0


def test_expired_and_deadline_rules() -> None:
    assert to_row(sig(observed_at=NOW - timedelta(days=31)), "b-1", SEG, NOW) is None
    assert to_row(sig("tender", evidence_key="t1"), "b-1", SEG, NOW) is None  # a tender needs its deadline
    tender = to_row(sig("tender", evidence_key="t1", deadline=NOW + timedelta(days=9)), "b-1", SEG, NOW)
    assert tender is not None and tender["expires_at"] == NOW + timedelta(days=9)


def test_dedupe_keys_are_stable_and_specific() -> None:
    a, b = sig(), sig()
    assert dedupe_key(a, "b-1") == dedupe_key(b, "b-1")
    assert dedupe_key(a, "b-1") != dedupe_key(a, "b-2")
    assert dedupe_key(a, "b-1") != dedupe_key(sig(evidence_key="apna:2"), "b-1")
    assert dedupe_key(a, "b-1") != dedupe_key(sig("hiring_builder"), "b-1")


def test_quotes_are_trimmed_to_300_characters() -> None:
    row = to_row(sig(quote="word " * 200), "b-1", SEG, NOW)
    assert row is not None and len(row["quote"]) <= 300


def _signals_for(bid: str) -> list[dict[str, Any]]:
    return db.fetch_all("select type, quote, points, details from public.signals where business_id = %s", [bid])


def test_sink_links_hints_creates_businesses_and_upserts_once(clean_db: str) -> None:
    segments = {SEG.id: SEG}
    now = datetime.now(UTC)
    hinted = sig(observed_at=now, business_hint={"name": "Glow Aesthetics", "city": "Pune"}, evidence_key="apna:hint-1")
    for _ in range(2):  # the same evidence twice: one business, one signal
        sink = SignalSink(segments, ctx())
        sink.add(hinted, SEG)
        counts = sink.flush()
    assert counts["clinics-in"]["hiring_frontdesk"] == 1
    bid = db.scalar("select id::text from public.businesses where name = 'Glow Aesthetics'")
    assert bid and len(_signals_for(bid)) == 1
    assert db.scalar("select count(*) from public.businesses where name = 'Glow Aesthetics'") == 1
    assert db.scalar("select business_id::text from public.source_records where source_key = 'apna:hint-1'") == bid


def test_signals_without_a_segment_city_or_website_stay_unlinked(clean_db: str) -> None:
    sink = SignalSink({SEG.id: SEG}, ctx())
    sink.add(sig(business_hint={"name": "Far Away Clinic", "city": "Lucknow"}, evidence_key="apna:far"), SEG)
    counts = sink.flush()
    assert counts["clinics-in"]["unlinked"] == 1
    assert db.scalar("select count(*) from public.businesses where name = 'Far Away Clinic'") == 0


def test_review_pain_never_stores_text(clean_db: str) -> None:
    bid = insert_business(name="Review Pain Clinic", place_id="ChIJreview-1")
    sink = SignalSink({SEG.id: SEG}, ctx())
    sink.add(
        sig(
            "review_pain",
            source="places",
            quote=None,
            url="https://www.google.com/maps/place/?q=place_id:ChIJreview-1",
            evidence_key="ChIJreview-1|2026-11",
            business_id=bid,
            observed_at=datetime.now(UTC),
            details={"flags": ["unanswered_calls"], "matching_reviews": 2},
        ),
        SEG,
    )
    sink.flush()
    rows = _signals_for(bid)
    assert len(rows) == 1 and rows[0]["quote"] is None and rows[0]["details"]["flags"] == ["unanswered_calls"]
    assert db.scalar("select count(*) from public.signals where type = 'review_pain' and quote is not null") == 0


def test_dry_run_writes_no_signals(clean_db: str) -> None:
    bid = insert_business(name="Dry Signal Clinic")
    sink = SignalSink({SEG.id: SEG}, ctx(dry_run=True))
    sink.add(sig(business_id=bid, observed_at=datetime.now(UTC)), SEG)
    assert sink.flush()["clinics-in"]["hiring_frontdesk"] == 1
    assert _signals_for(bid) == []


def classification(**over: Any) -> SignalClassification:
    base: dict[str, Any] = {
        "is_relevant": True,
        "role_category": "builder",
        "employer_name": "Skin Theory Clinic",
        "employer_website": None,
        "employer_domain": "clinics",
        "city": "Pune",
        "evidence_quote": "need someone to build a WhatsApp bot",
        "confidence": 0.9,
    }
    return SignalClassification(**{**base, **over})


async def test_inbox_posts_become_public_asks(clean_db: str) -> None:
    good = db.scalar(
        "insert into public.inbox_posts (url, text, segment_id) values (%s, %s, 'clinics-in') returning id::text",
        [
            "https://www.linkedin.com/posts/skin-theory_123",
            "Our clinic in Pune is looking for an agency, we need someone to build a WhatsApp bot for bookings.",
        ],
    )
    bad = db.scalar(
        "insert into public.inbox_posts (url, text) values (%s, %s) returning id::text",
        ["https://x.com/someone/status/1", "I am a freelancer offering WhatsApp bots."],
    )
    router = FakeRouter({"classify_signal": [classification(), classification(is_relevant=False)]})
    context = ctx(router)
    sink = SignalSink({SEG.id: SEG}, context)
    await stage.inbox_posts_watch(context, {SEG.id: SEG}, sink)
    sink.flush()
    statuses = {r["id"]: r["status"] for r in db.fetch_all("select id::text, status from public.inbox_posts")}
    assert statuses[good] == "processing" and statuses[bad] == "rejected"
    row = db.fetch_one(
        "select s.type, s.quote, s.url from public.signals s join public.businesses b on b.id = s.business_id "
        "where b.name = 'Skin Theory Clinic'"
    )
    assert row is not None and row["type"] == "public_ask"
    assert row["quote"] == "need someone to build a WhatsApp bot"
    assert row["url"] == "https://www.linkedin.com/posts/skin-theory_123"  # stored as evidence, never fetched


async def test_a_failing_watcher_does_not_stop_the_others(clean_db: str) -> None:
    ran: list[str] = []

    async def broken(c: SourceContext, s: dict[str, Segment], k: SignalSink) -> None:
        ran.append("broken")
        raise RuntimeError("source changed its page")

    async def fine(c: SourceContext, s: dict[str, Segment], k: SignalSink) -> None:
        ran.append("fine")

    context = ctx()
    await stage.run_watchers(
        context, {SEG.id: SEG}, SignalSink({SEG.id: SEG}, context), (("gdelt", broken), ("apna", fine))
    )
    assert ran == ["broken", "fine"] and context.stats["errors.gdelt"] == 1
    assert "source changed its page" in str(
        db.scalar("select last_error from public.source_health where source = 'gdelt'")
    )


def test_the_stage_runs_every_watcher_and_records_stats(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    bid = insert_business(name="Stage Clinic")

    async def watcher(c: SourceContext, segments: dict[str, Segment], sink: SignalSink) -> None:
        sink.add(sig(business_id=bid, observed_at=datetime.now(UTC), evidence_key="stage-1"), segments["clinics-in"])

    monkeypatch.setattr(stage, "WATCHERS", (("apna", watcher),))
    rc = run_context()
    stats = stage.run(rc)
    assert stats["by_segment"]["clinics-in"]["hiring_frontdesk"] == 1
    assert rc.stats["signals"] is stats and len(_signals_for(bid)) == 1
