"""Hacker News launches (lane E1a): posts from the Algolia API become launch signals when they have a company
website and the classifier sees a small startup in a country we write to."""

from __future__ import annotations

import json
from typing import Any

import httpx

from nument_engine import db
from nument_engine.segments import load_segments
from nument_engine.sources import hn_launches as hn
from nument_engine.sources.rss import Pass

from .e1a_helpers import ago, answer, fast, fixture, html
from .sources_helpers import FakeRouter, clean_db, ctx, mock_transport, no_network
from .test_funding_rss import ListSink

__all__ = ["clean_db", "fast", "no_network"]

WIYOMI = "https://news.ycombinator.com/item?id=50509047"
POMERADO = "https://news.ycombinator.com/item?id=50455811"
BLOCKOFBYTES = "https://news.ycombinator.com/item?id=50508720"


def hits(hours: tuple[float, ...] = (1, 2, 3, 30)) -> dict[str, Any]:
    """The fixture with its posts made `hours` ago (in file order)."""
    data = json.loads(fixture("hn_algolia.json"))
    for hit, h in zip(data["hits"], hours, strict=True):
        hit["created_at_i"] = int(ago(h).timestamp())
    return data


SITES = {
    "https://www.wiyomi.com/": html(
        "<html><head><title>Wiyomi: local AI video agent</title></head><body><h1>Make videos on your own laptop</h1>"
        "<p>Wiyomi runs a video agent fully on your device.</p><footer>Founded by Sam Lee. Wiyomi Ltd, London, "
        "United Kingdom</footer></body></html>"
    ),
    "https://www.blockofbytes.com/": (403, "Forbidden"),
    "https://pomerado.ai/": html(
        "<html><body><h1>Pomerado</h1><p>APIs for any website. San Francisco.</p></body></html>"
    ),
}


def routes(data: dict[str, Any] | None = None, **changes: Any) -> dict[str, Any]:
    return {hn.API: (200, data if data is not None else hits()), **SITES, **changes}


def answers(inputs: dict[str, Any]) -> Any:
    url = inputs["url"]
    if url == POMERADO:
        return answer(event="launch", company_name="Pomerado", company_website="pomerado.ai", hq_country="us",
                      city=None, round="unknown", amount_usd=None, team_size=2, founders=["Ana", "Raj"], investors=[],
                      evidence_quote="Turn any website into an MCP for agents")  # fmt: skip
    if url == WIYOMI:
        return answer(event="launch", company_name="Wiyomi", company_website=None, hq_country="gb", city="London",
                      round="unknown", amount_usd=None, team_size=None, founders=["Sam Lee"], investors=[],
                      evidence_quote="video agent can be run fully local")  # fmt: skip
    if url == BLOCKOFBYTES:
        return answer(event="launch", company_name="Block of Bytes", is_startup=False)
    raise AssertionError(f"unexpected AI call for {url}")


def test_posts_need_a_company_website() -> None:
    data = hits()
    by_title = {h["title"]: h for h in data["hits"]}
    github = next(h for t, h in by_title.items() if "Herdr" in t)
    assert hn.item_from(github) is None  # a GitHub repository is not a company site
    launch = hn.item_from(next(h for t, h in by_title.items() if t.startswith("Launch HN")))
    assert launch is not None and launch.website == "https://pomerado.ai/"
    assert launch.details == {"hn_id": 50455811, "kind": "launch_hn", "website_from": "post_text", "points": 64,
                              "comments": 48, "batch": "F26"}  # fmt: skip
    assert launch.url == POMERADO and launch.key == "hn:50455811" and launch.signal_type == "launch"
    assert f"we{chr(0x2019)}re Ana and Raj from Pomerado" in launch.text and "<a" not in launch.text
    show = hn.item_from(next(h for t, h in by_title.items() if "Local AI Video" in t))
    assert show is not None and show.website == "https://wiyomi.com/" and show.site_url == "https://www.wiyomi.com/"
    assert show.details["kind"] == "show_hn"
    assert hn.item_from({"objectID": "x", "title": "Show HN: X", "url": "https://x.io"}) is None
    assert hn.item_from({"objectID": "1", "title": "", "url": "https://x.io"}) is None


async def test_a_nightly_pass_reads_sites_and_routes_launches(clean_db: str, fast: None) -> None:
    transport, seen = mock_transport(routes())
    router = FakeRouter({"classify_startup_item": answers})
    context = ctx(router)
    sink = ListSink()
    await hn.watch(context, load_segments(), sink, transport=transport)

    assert [i["url"] for _, i in router.calls] == [POMERADO, BLOCKOFBYTES, WIYOMI]  # Launch HN first, then points
    by_name = {sig.business_hint["name"]: (sig, seg.id) for sig, seg in sink.added}
    assert set(by_name) == {"Pomerado", "Wiyomi"}
    pomerado, seg = by_name["Pomerado"]
    assert seg == "firms-us" and pomerado.type == "launch" and pomerado.url == POMERADO
    assert pomerado.business_hint["website"] == "https://pomerado.ai/" and pomerado.details["batch"] == "F26"
    assert [f["name"] for f in pomerado.details["founders"]] == ["Ana", "Raj"]
    assert pomerado.quote == "Turn any website into an MCP for agents"
    wiyomi, seg = by_name["Wiyomi"]
    assert seg == "firms-gb" and wiyomi.quote == "video agent can be run fully local"
    # a founder named only on the homepage cites the homepage, not the post
    assert wiyomi.details["founders"] == [
        {"name": "Sam Lee", "role": "Founder", "source_url": "https://www.wiyomi.com/"}
    ]
    sent = next(i for _, i in router.calls if i["url"] == WIYOMI)["text"]
    assert "From the company's homepage (https://www.wiyomi.com/)" in sent and "London, United Kingdom" in sent
    s = context.stats
    assert s["hn_launches.no_website"] == 1 and s["hn_launches.not_startup"] == 1
    assert s["hn_launches.sites_read"] == 2 and s["hn_launches.sites_unread"] == 1  # one homepage refused us
    api_calls = [r for r in seen if r.url.host == "hn.algolia.com"]
    assert len(api_calls) == 1 and api_calls[0].url.params["tags"] == "(show_hn,launch_hn)"
    assert api_calls[0].url.params["numericFilters"].startswith("created_at_i>")

    again = FakeRouter({"classify_startup_item": answers})
    transport, _ = mock_transport(routes())
    await hn.watch(ctx(again), load_segments(), ListSink(), transport=transport)
    assert again.calls == []  # every post was judged already


async def test_old_posts_and_the_daily_allowance(clean_db: str, fast: None) -> None:
    db.set_setting("hn_launches.items_per_day", 1)
    transport, _ = mock_transport(routes(hits((1, 2, 100, 30))))  # the 100-hour-old post is outside 3 days
    router = FakeRouter({"classify_startup_item": answers})
    context = ctx(router)
    await hn.watch(context, load_segments(), ListSink(), transport=transport)
    assert len(router.calls) == 1 and context.stats["hn_launches.outside_window"] == 1


async def test_a_blocked_api_pauses_the_source(clean_db: str, fast: None) -> None:
    transport, _ = mock_transport(routes(**{hn.API: (403, "Forbidden")}))
    router = FakeRouter({"classify_startup_item": answers})
    context = ctx(router)
    await hn.watch(context, load_segments(), ListSink(), transport=transport)
    row = db.fetch_one("select blocked_until, last_error from public.source_health where source = 'hn_launches'")
    assert row is not None and row["blocked_until"] is not None and router.calls == []
    assert any("hn_launches blocked" in a for a in context.alerts)


async def test_an_api_that_never_answers_is_an_error(clean_db: str, fast: None) -> None:
    transport, _ = mock_transport(routes(**{hn.API: (500, "oops")}))
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await hn.watch(context, load_segments(), ListSink(), transport=transport)
    row = db.fetch_one("select last_error from public.source_health where source = 'hn_launches'")
    assert row is not None and row["last_error"] == "the Algolia API did not answer"
    transport, _ = mock_transport(routes(**{hn.API: (200, "<html>maintenance</html>")}))
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await hn.watch(context, load_segments(), ListSink(), transport=transport)
    assert context.stats["hn_launches.bad_json"] == 1


async def test_backlog_looks_back_30_days_three_days_per_query(clean_db: str, fast: None) -> None:
    calls: list[httpx.Request] = []

    def api(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"hits": [], "nbPages": 0})

    transport, _ = mock_transport({hn.API: api})
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await hn.backlog(context, load_segments(), ListSink(), Pass(days=60, cap=500, backlog=True), transport=transport)
    assert len(calls) == 10  # a launch is news for 30 days: 10 windows of 3 days, not 20
    lows = sorted(int(r.url.params["numericFilters"].split(",")[0].split(">")[1]) for r in calls)
    assert int(ago(days=30).timestamp()) - lows[0] < 120


async def test_pages_of_one_window(clean_db: str, fast: None) -> None:
    pages: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        pages.append(request.url.params["page"])
        page = int(request.url.params["page"])
        found = (
            []
            if page >= 2
            else [{"objectID": str(100 + page), "title": f"Show HN: Tool {page}", "url": "https://github.com/x"}]
        )
        return httpx.Response(200, json={"hits": found, "nbPages": 3})

    transport, _ = mock_transport({hn.API: api})
    async with hn.HnLaunchesAdapter(ctx(), transport=transport) as adapter:
        found = await adapter.posts(Pass(days=1, cap=10))
    assert pages == ["0", "1", "2"] and len(found) == 2
