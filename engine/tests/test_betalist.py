"""BetaList (lane E1a): feed entries with a website behind the visit link become launch signals; a blocked feed
pauses the source, a gone feed is an error, failing visit links stop early."""

from __future__ import annotations

from typing import Any

import httpx

from nument_engine import db
from nument_engine.segments import load_segments
from nument_engine.sources import betalist as bl
from nument_engine.sources.rss import FeedItem, Pass

from .e1a_helpers import ATOM_TYPE, ago, answer, fast, feed, fixture, fresh_dates, html
from .sources_helpers import FakeRouter, clean_db, ctx, mock_transport, no_network
from .test_funding_rss import ListSink

__all__ = ["clean_db", "fast", "no_network"]

WFH = "https://betalist.com/startups/wfh-alert"
ENIWHER3 = "https://betalist.com/startups/eniwher3"


def moved(target: str) -> httpx.Response:
    return httpx.Response(301, headers={"location": target})


def routes(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "https://betalist.com/robots.txt": (200, "# See https://www.robotstxt.org/robotstxt.html"),
        bl.FEED_URL: feed(fresh_dates(fixture("betalist.atom"), 2, 5), ATOM_TYPE),
        f"{WFH}/visit": moved("https://www.wfhalert.com/?ref=betalist&utm_source=betalist&utm_medium=referral"),
        f"{ENIWHER3}/visit": moved("https://eniwher3.app/"),
        "https://www.wfhalert.com/": html(
            "<html><head><title>WFH Alert</title></head><body><h1>Remote jobs, reviewed by a person</h1>"
            "<footer>WFH Alert LLC, Austin, Texas, USA</footer></body></html>"
        ),
        "https://eniwher3.app/": html("<html><body><h1>eniwher3</h1><p>A scratch pad.</p></body></html>"),
    }
    return {**base, **changes}


def answers(inputs: dict[str, Any]) -> Any:
    if inputs["url"] == WFH:
        return answer(event="launch", company_name="WFH Alert", company_website=None, hq_country="us", city="Austin",
                      round="unknown", amount_usd=None, team_size=None, founders=[], investors=[],
                      evidence_quote="remote job discovery service")  # fmt: skip
    if inputs["url"] == ENIWHER3:
        return answer(event="launch", company_name="eniwher3", hq_country=None, company_website=None)
    raise AssertionError(inputs["url"])


def test_only_startup_pages_are_items() -> None:
    entry = FeedItem(feed="betalist", title="Acme - a tool", link=WFH, published=ago(1), summary="Acme helps.")
    item = bl.item_from(entry)
    assert item is not None and item.key == "betalist:wfh-alert" and item.signal_type == "launch"
    assert bl.slug_of("https://betalist.com/topics/ai") is None and bl.slug_of("https://example.com/startups/x") is None
    assert bl.slug_of("https://www.betalist.com/startups/acme") == "acme"


async def test_a_nightly_pass_finds_websites_behind_visit_links(clean_db: str, fast: None) -> None:
    transport, seen = mock_transport(routes())
    router = FakeRouter({"classify_startup_item": answers})
    context = ctx(router)
    sink = ListSink()
    await bl.watch(context, load_segments(), sink, transport=transport)

    assert [i["url"] for _, i in router.calls] == [WFH, ENIWHER3]  # newest first
    assert len(sink.added) == 1
    sig, seg = sink.added[0]
    assert seg.id == "firms-us" and sig.type == "launch" and sig.url == WFH
    assert sig.business_hint == {"name": "WFH Alert", "city": "Austin", "website": "https://wfhalert.com/"}
    assert sig.quote == "remote job discovery service" and sig.evidence_key == "betalist:wfh-alert"
    assert sig.details["website_from"] == "betalist_visit" and sig.details["betalist_slug"] == "wfh-alert"
    sent = router.calls[0][1]["text"]
    assert "WFH Alert LLC, Austin, Texas, USA" in sent  # the homepage footer reached the classifier
    assert context.stats["betalist.no_country"] == 1  # eniwher3.app says nowhere where it is
    targets = [str(r.url) for r in seen]
    assert not any("ref=betalist" in t for t in targets)  # the redirect target is read without BetaList's tags
    assert db.scalar("select count(*) from public.source_records where source_key like 'betalist:%'") == 2

    again = FakeRouter({"classify_startup_item": answers})
    transport, seen = mock_transport(routes())
    await bl.watch(ctx(again), load_segments(), ListSink(), transport=transport)
    assert again.calls == [] and not any(r.url.path.endswith("/visit") for r in seen)


async def test_entries_without_a_website_are_not_judged(clean_db: str, fast: None) -> None:
    transport, _ = mock_transport(routes(**{f"{WFH}/visit": moved("https://github.com/someone/wfh")}))
    router = FakeRouter({"classify_startup_item": answers})
    context = ctx(router)
    await bl.watch(context, load_segments(), ListSink(), transport=transport)
    assert [i["url"] for _, i in router.calls] == [ENIWHER3] and context.stats["betalist.no_website"] == 1
    assert bl.unseen("betalist", ["betalist:wfh-alert"]) == {"betalist:wfh-alert"}  # tried again next run


async def test_failing_visit_links_stop_early(clean_db: str, fast: None, monkeypatch: Any) -> None:
    monkeypatch.setattr(bl, "MAX_VISIT_MISSES", 1)
    transport, seen = mock_transport(routes(**{f"{WFH}/visit": (200, "no redirect"), f"{ENIWHER3}/visit": (200, "x")}))
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await bl.watch(context, load_segments(), ListSink(), transport=transport)
    assert context.stats["betalist.visit_links_failing"] == 1
    assert len([r for r in seen if r.url.path.endswith("/visit")]) == 1


async def test_a_blocked_feed_pauses_the_source_and_a_gone_feed_is_an_error(clean_db: str, fast: None) -> None:
    transport, _ = mock_transport(routes(**{bl.FEED_URL: (403, "Forbidden")}))
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await bl.watch(context, load_segments(), ListSink(), transport=transport)
    row = db.fetch_one("select blocked_until from public.source_health where source = 'betalist'")
    assert row is not None and row["blocked_until"] is not None

    db.execute("update public.source_health set blocked_until = null where source = 'betalist'")
    transport, _ = mock_transport(routes(**{bl.FEED_URL: (404, "gone")}))
    await bl.watch(
        ctx(FakeRouter({"classify_startup_item": answers})), load_segments(), ListSink(), transport=transport
    )
    row = db.fetch_one("select last_error from public.source_health where source = 'betalist'")
    assert row is not None and row["last_error"].startswith("the BetaList feed could not be read (broken")


async def test_robots_can_forbid_the_visit_links(clean_db: str, fast: None) -> None:
    robots = (200, "User-agent: *\nDisallow: /startups/*/visit")
    transport, seen = mock_transport(routes(**{"https://betalist.com/robots.txt": robots}))
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await bl.backlog(context, load_segments(), ListSink(), Pass(days=60, cap=100, backlog=True), transport=transport)
    assert context.stats["betalist.visit_disallowed"] == 2 and not any(r.url.path.endswith("/visit") for r in seen)
