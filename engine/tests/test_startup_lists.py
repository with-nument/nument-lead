"""Accelerator lists (lane E1a): yc-oss batches become launch signals for small, active, recently launched
companies in countries we write to."""

from __future__ import annotations

import json
from typing import Any

from nument_engine import db
from nument_engine.segments import load_segments
from nument_engine.sources import startup_lists as sl
from nument_engine.sources.rss import Pass

from .e1a_helpers import ago, fast, fixture
from .sources_helpers import clean_db, ctx, mock_transport, no_network
from .test_funding_rss import ListSink

__all__ = ["clean_db", "fast", "no_network"]


def batch(days_ago: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """The fixture's companies, each launched `days_ago[name]` days ago (5 days when not named)."""
    out = json.loads(fixture("yc_batch_fall_2026.json"))
    for c in out:
        c["launched_at"] = int(ago(days=(days_ago or {}).get(c["name"], 5)).timestamp())
    return out


def routes(companies: list[dict[str, Any]] | None = None, **changes: Any) -> dict[str, Any]:
    meta = json.loads(fixture("yc_meta.json"))
    data = companies if companies is not None else batch()
    base: dict[str, Any] = {
        "https://yc-oss.github.io/robots.txt": (404, ""),
        sl.META_URL: (200, meta),
        **{sl.BATCH_URL.format(key=k): (200, []) for k in ("summer-2027", "winter-2027")},
        sl.BATCH_URL.format(key="fall-2026"): (200, data),
    }
    return {**base, **changes}


def test_newest_batches_and_countries() -> None:
    meta = json.loads(fixture("yc_meta.json"))
    assert sl.newest_batches(meta, 3) == ["summer-2027", "winter-2027", "fall-2026"]
    meta["batches"]["summer-2027"]["count"] = 0
    assert sl.newest_batches(meta, 2) == ["winter-2027", "fall-2026"]  # empty batches and "unspecified" skipped
    assert sl.country_of({"regions": ["United States of America", "America / Canada"]}) == "us"
    assert (
        sl.country_of({"regions": ["India", "South Asia", "Remote"], "all_locations": "Bengaluru, KA, India"}) == "in"
    )
    two = {
        "regions": ["United States of America", "India"],
        "all_locations": "Bengaluru, KA, India; San Francisco, CA, USA",
    }
    assert sl.country_of(two) == "in"  # several countries: the first location decides
    assert sl.country_of({"regions": ["Unspecified"], "all_locations": ""}) is None
    assert sl.country_of({"regions": [], "all_locations": "San Francisco, CA"}) is None  # CA is a state here


async def test_a_pass_keeps_small_recent_companies_we_can_write_to(clean_db: str, fast: None) -> None:
    transport, seen = mock_transport(routes(batch({"Tire Swing": 45})))
    context = ctx()
    sink = ListSink()
    await sl.watch(context, load_segments(), sink, transport=transport)
    got = {sig.business_hint["name"]: (sig, seg.id) for sig, seg in sink.added}
    assert set(got) == {"Kailash Labs", "Organizely", "GrayPass"}
    kailash, seg = got["Kailash Labs"]
    assert seg == "firms-in" and kailash.type == "launch" and kailash.source == "startup_lists"
    assert kailash.url == "https://www.ycombinator.com/companies/kailash-labs" and kailash.evidence_key == "yc:34828"
    assert kailash.business_hint["website"] == "https://kailashlabs.com/"
    assert kailash.details == {"dataset": "yc-oss", "yc_id": 34828, "country_from": "list", "batch": "Fall 2026",
                               "team_size": 2, "team_size_source": "list"}  # fmt: skip
    assert kailash.quote and len(kailash.quote) >= 5
    organizely, _ = got["Organizely"]
    assert "team_size" not in organizely.details  # unknown size passes, and is not invented
    assert got["GrayPass"][1] == "firms-ca"
    s = context.stats
    assert s["startup_lists.too_old"] == 1 and s["startup_lists.too_big"] == 1  # Tire Swing, Perit.AI
    assert s["startup_lists.country_blocked"] == 1 and s["startup_lists.no_country"] == 1  # CONUS, Viraj Aero
    assert s["startup_lists.batches_read"] == 3 and len(seen) == 5  # robots, meta and three batches


async def test_inactive_nonprofit_and_bad_records(clean_db: str, fast: None) -> None:
    companies = batch({"Tire Swing": 45})
    by_name = {c["name"]: c for c in companies}
    by_name["Kailash Labs"]["status"] = "Inactive"
    by_name["GrayPass"]["nonprofit"] = True
    by_name["Organizely"]["website"] = "https://github.com/organizely"
    transport, _ = mock_transport(routes(companies))
    context = ctx()
    sink = ListSink()
    await sl.watch(context, load_segments(), sink, transport=transport)
    assert sink.added == []
    s = context.stats
    assert (
        s["startup_lists.not_active"] == 1 and s["startup_lists.nonprofit"] == 1 and s["startup_lists.no_website"] == 1
    )


async def test_linked_companies_are_skipped(clean_db: str, fast: None) -> None:
    db.execute(
        "insert into public.source_records (source, source_key, payload) values ('startup_lists', 'yc:34828', '{}')"
    )
    transport, _ = mock_transport(routes())
    context = ctx()
    sink = ListSink()
    await sl.watch(context, load_segments(), sink, transport=transport)
    assert "Kailash Labs" not in {s.business_hint["name"] for s, _ in sink.added}
    assert context.stats["startup_lists.seen_before"] == 1


async def test_failures_and_blocks(clean_db: str, fast: None) -> None:
    transport, _ = mock_transport(routes(**{sl.META_URL: (404, "gone")}))
    await sl.watch(ctx(), load_segments(), ListSink(), transport=transport)
    row = db.fetch_one("select last_error from public.source_health where source = 'startup_lists'")
    assert row is not None and row["last_error"] == "yc-oss meta.json could not be read"

    transport, _ = mock_transport(routes(**{sl.BATCH_URL.format(key="fall-2026"): (200, "not json")}))
    context = ctx()
    await sl.watch(context, load_segments(), ListSink(), transport=transport)
    assert context.stats["startup_lists.bad_json"] == 1  # one broken batch file never stops the others

    transport, _ = mock_transport(routes(**{sl.META_URL: (403, "Forbidden")}))
    context = ctx()
    await sl.watch(context, load_segments(), ListSink(), transport=transport)
    row = db.fetch_one("select blocked_until from public.source_health where source = 'startup_lists'")
    assert row is not None and row["blocked_until"] is not None


async def test_backlog_cap(clean_db: str, fast: None) -> None:
    transport, _ = mock_transport(routes())
    sink = ListSink()
    await sl.backlog(ctx(), load_segments(), sink, Pass(days=60, cap=1, backlog=True), transport=transport)
    assert len(sink.added) == 1
