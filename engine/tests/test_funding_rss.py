"""Startup funding news (lane E1a): the code filter, the choice of items, a whole nightly pass over real feed
fixtures (some feeds gone or blocked), GDELT, caps, health and the backlog pass."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.pipeline.signals import SignalSink
from nument_engine.segments import Segment, load_segments, sync_segments_to_db
from nument_engine.sources import funding_rss as fr
from nument_engine.sources.base import Signal
from nument_engine.sources.gdelt import Article
from nument_engine.sources.rss import FeedItem, Pass

from .e1a_helpers import ago, answer, fast, feed, fixture, fresh_dates, html
from .sources_helpers import FakeRouter, clean_db, ctx, mock_transport, no_network

__all__ = ["clean_db", "fast", "no_network"]

GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
TC_FEED = "https://techcrunch.com/category/startups/feed/"
YS_FEED = "https://yourstory.com/category/funding/feed"
SD_FEED = "https://www.startupdaily.net/topic/funding/feed/"
INC42_FEED = "https://inc42.com/feed/"
NECTAR = "https://techcrunch.com/2026/11/12/nectar-launches-an-ai-agent-to-automate-creator-discovery-and-outreach-for-brands/"
INDRUS = "https://www.startupdaily.net/topic/funding/perth-logistics-analysis-startup-indrus-moves-on-750000-pre-seed/"
ACME = "https://citynews.example.com/2026/11/acme-robotics-seed"


class ListSink:
    def __init__(self) -> None:
        self.added: list[tuple[Signal, Segment]] = []

    def add(self, sig: Signal, seg: Segment) -> None:
        self.added.append((sig, seg))


# ---- the code filter ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "why"),
    [
        ("With $720M round, Britain's Fractile gets a leg up in the race for AI chips", "late_or_big"),
        ("AI agent startup LangChain hits $3B valuation", "late_or_big"),
        ("Peppermint Robotics bags Rs 100 Cr in pre-Series B funding round", "late_or_big"),
        ("altM raises $10.3M in Series A funding led by Rainmatter, Mela Ventures", "late_or_big"),
        ("Spacetech startup Cosmoserve raises $6M in seed round", "late_or_big"),
        ("OpenAI acquires Odessia, travel startup created by Sonder founder", "late_or_big"),
        ("(Weekly funding roundup Nov 7-14) VC inflow drops to its lowest level in 2026", "roundup"),
        ("Weekly funding round-up! All of the European startup funding rounds we tracked this week", "roundup"),
        ("The Weekly Notable Startup Funding Report: 11/16/26", "roundup"),
        ("EaseMyTrip Q2: Loss Narrows 98% YoY To Rs 57 Lakh, Revenue Up 34%", "no_funding_words"),
        ("Perth logistics analysis startup Indrus moves on $750,000 pre-Seed", None),
        ("Kiwi agtech Aimer Farming raises $2.44 million to solve the grass-to-beef ratio problem", None),
        ("Nectar launches an AI agent to automate creator discovery and outreach for brands", None),
        ("Brightcart raises EUR 1,5 million to help grocers", None),
    ],
)
def test_prefilter(title: str, why: str | None) -> None:
    assert fr.prefilter(title, "", max_raise_usd=2_000_000) == why


def test_amounts_in_titles() -> None:
    assert fr.amounts_usd("raises $750,000 pre-Seed") == [750_000.0]
    assert fr.amounts_usd("bags Rs 100 Cr") == pytest.approx([12_000_000.0])
    assert fr.amounts_usd("raises A$3 million") == pytest.approx([1_950_000.0])
    assert fr.amounts_usd("raises €2.5m and £1M") == pytest.approx([2_700_000.0, 1_270_000.0])
    assert fr.amounts_usd("7,000 customers and 30% growth") == []


def test_the_feed_list_is_confirmed_and_eu_startups_is_not_read() -> None:
    assert len(fr.FEEDS) == 13 and len({f.key for f in fr.FEEDS}) == 13
    assert all(f.url.startswith("https://") for f in fr.FEEDS)
    assert not any("eu-startups" in f.url for f in fr.FEEDS)  # robots.txt behind a bot check: never read


# ---- choosing items -------------------------------------------------------------------------------------------


def feed_item(title: str, link: str, hours: float, text: str = "Acme raised a seed round.") -> FeedItem:
    return FeedItem(feed="techcrunch", title=title, link=link, published=ago(hours), summary=text)


def test_candidates_window_filter_seen_repeats_and_order(clean_db: str) -> None:
    adapter = fr.FundingRssAdapter(ctx())
    tc = fr.FEEDS[8]
    africa = next(f for f in fr.FEEDS if f.key == "techcabal")
    db.execute(
        "insert into public.source_records (source, source_key, payload) values ('funding_rss', %s, '{}')",
        ["https://news.example.com/seen"],
    )
    feed_items = [
        (tc, feed_item("Acme raises its seed round", "https://news.example.com/acme", 5)),
        (tc, feed_item("Acme raises its seed round", "https://other.example.com/acme-copy", 4)),  # same story
        (tc, feed_item("Old Co raises pre-seed", "https://news.example.com/old", 24 * 5)),  # outside 3 days
        (tc, feed_item("Seen Co raises seed", "https://news.example.com/seen", 2)),  # judged before
        (tc, feed_item("Big Co raises $50M Series B", "https://news.example.com/big", 1)),
        (africa, feed_item("Lagos startup raises pre-seed", "https://africa.example.com/a", 1)),
        (tc, feed_item("Newer Co raises seed", "https://news.example.com/newer?utm_source=rss", 3)),
    ]
    articles = [
        Article("https://gdelt.example.com/z", "Zed raises seed funding", ago(1), "gdelt.example.com", "English", "US")
    ]
    items = adapter.candidates(feed_items, articles, Pass(days=3, cap=50), max_raise_usd=2e6)
    assert [i.title for i in items] == [
        "Newer Co raises seed",  # rank 1, newest first
        "Acme raises its seed round",
        "Lagos startup raises pre-seed",  # rank 2 after rank 1
        "Zed raises seed funding",  # GDELT last
    ]
    assert items[0].key == "https://news.example.com/newer"  # tracking parameters are not part of the key
    assert items[-1].details == {"source": "GDELT", "domain": "gdelt.example.com"} and items[-1].text == ""
    s = adapter.ctx.stats
    assert s["funding_rss.outside_window"] == 1 and s["funding_rss.seen_before"] == 1
    assert s["funding_rss.repeat"] == 1 and s["funding_rss.late_or_big"] == 1


# ---- a whole nightly pass ---------------------------------------------------------------------------------------

INDRUS_FEED = (
    '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Funding | Startup Daily</title>'
    "<item><title>Perth logistics analysis startup Indrus moves on $750,000 pre-Seed</title>"
    f"<link>{INDRUS}</link><pubDate>Thu, 05 Nov 2026 04:00:00 +0000</pubDate>"
    "<description><![CDATA[Indrus, founded in Perth by Jo Smith, raised $750,000 in a pre-Seed round led by "
    "Westcoast Angels.]]></description></item></channel></rss>"
)
NECTAR_ARTICLE = (
    "<html><head><title>Nectar launches an AI agent</title></head><body><article><h1>Nectar launches an AI agent "
    "to automate creator discovery</h1><p>Nectar, a five-person startup based in New York, launched an AI agent "
    "that finds creators for brands and manages outreach. The company was founded last year and sells to "
    "consumer brands that run influencer campaigns every month.</p><p>Nectar plans to hire its first engineers "
    "next year and is working with an outside studio until then, the founders said.</p></article></body></html>"
)
ACME_ARTICLE = (
    "<html><body><article><h1>Acme Robotics raises $1.2M seed round to build farm robots</h1><p>Acme Robotics, "
    "a London startup, raised $1.2 million in a seed round to build small robots for farms. The four founders "
    "met at university and plan to ship their first robot next spring.</p></article></body></html>"
)


def gdelt_json(*arts: tuple[str, str, float]) -> dict[str, Any]:
    return {
        "articles": [
            {"url": url, "title": title, "seendate": ago(hours).strftime("%Y%m%dT%H%M%SZ"), "domain": "citynews",
             "language": "English", "sourcecountry": "United Kingdom"}
            for url, title, hours in arts
        ]
    }  # fmt: skip


def routes(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        TC_FEED: feed(fresh_dates(fixture("techcrunch_startups.xml"), 5, 20, 30)),
        YS_FEED: feed(fresh_dates(fixture("yourstory_funding.xml"), 2, 4)),
        SD_FEED: feed(fresh_dates(INDRUS_FEED, 6)),
        INC42_FEED: (403, "Forbidden"),
        NECTAR: html(NECTAR_ARTICLE),
        INDRUS: (403, "Forbidden"),  # the article page refuses us: the feed text is used
        GDELT_API: (200, gdelt_json((ACME, "Acme Robotics raises $1.2M seed round to build farm robots", 3),
                                    (ACME + "-copy", "Acme Robotics raises $1.2M seed round to build farm robots", 3))),
        ACME: html(ACME_ARTICLE),
    }  # fmt: skip
    return {**base, **changes}


def answers(inputs: dict[str, Any]) -> Any:
    url = inputs["url"]
    if url == NECTAR:
        return answer(event="launch", company_name="Nectar", company_website=None, city="New York", team_size=5,
                      round="unknown", amount_usd=None, founders=[], investors=[],
                      evidence_quote="Nectar launches an AI agent")  # fmt: skip
    if url == INDRUS:
        return answer(company_name="Indrus", company_website=None, hq_country="au", city="Perth", team_size=None,
                      amount_usd=490_000.0, founders=["Jo Smith"], investors=["Westcoast Angels"],
                      evidence_quote="raised $750,000 in a pre-Seed round")  # fmt: skip
    if url == ACME:
        return answer(company_name="Acme Robotics", company_website=None, hq_country="gb", city="London",
                      team_size=4, round="seed", amount_usd=1_200_000.0, founders=[], investors=[],
                      evidence_quote="raised $1.2 million in a seed round")  # fmt: skip
    raise AssertionError(f"unexpected AI call for {url}")


async def test_a_nightly_pass_reads_feeds_and_gdelt_and_emits_checked_signals(clean_db: str, fast: None) -> None:
    transport, seen = mock_transport(routes())
    router = FakeRouter({"classify_startup_item": answers})
    context = ctx(router)
    segments = load_segments()
    sink = ListSink()
    await fr.watch(context, segments, sink, transport=transport)

    by_name = {sig.business_hint["name"]: (sig, seg.id) for sig, seg in sink.added}
    assert set(by_name) == {"Nectar", "Indrus", "Acme Robotics"} and len(router.calls) == 3
    nectar, seg = by_name["Nectar"]
    assert seg == "firms-us" and nectar.type == "launch" and nectar.url == NECTAR
    assert nectar.quote == "Nectar launches an AI agent" and nectar.details["team_size"] == 5
    sent = next(i for t, i in router.calls if i["url"] == NECTAR)["text"]
    assert "five-person startup based in New York" in sent  # the short feed text was completed from the article
    indrus, seg = by_name["Indrus"]
    assert seg == "firms-au" and indrus.type == "funding" and indrus.details["round"] == "pre_seed"
    assert indrus.details["founders"][0]["name"] == "Jo Smith" and indrus.details["investors"] == ["Westcoast Angels"]
    acme, seg = by_name["Acme Robotics"]
    assert seg == "firms-gb" and acme.details["source"] == "GDELT" and acme.details["amount_usd"] == 1_200_000

    s = context.stats
    assert s["funding_rss.late_or_big"] == 3 and s["funding_rss.roundup"] == 1 and s["funding_rss.repeat"] == 1
    assert s["funding_rss.feeds_blocked"] == 1 and s["funding_rss.feeds_ok"] == 3 and s["funding_rss.feeds_broken"] == 9
    assert s["funding_rss.article_blocked"] == 1 and s["funding_rss.signal"] == 3
    assert context.budget.calls_today("other", ["funding_rss_item"]) == 3
    assert context.budget.calls_today("other", ["gdelt_query"]) == 1
    row = db.fetch_one("select last_ok_at, last_error from public.source_health where source = 'funding_rss'")
    assert row is not None and row["last_ok_at"] is not None
    assert len([r for r in seen if str(r.url) == INC42_FEED]) == 1  # a block is never retried

    # The signals are stored with their windows: a round lasts 60 days, a launch 30.
    with db.tx() as conn:
        sync_segments_to_db(conn, segments)
    real = SignalSink(segments, context)
    for sig, seg_obj in sink.added:
        real.add(sig, seg_obj)
    real.flush()
    rows = db.fetch_all(
        "select b.name, b.segment_id, s.type, s.expires_at - s.observed_at as window, s.details "
        "from public.signals s join public.businesses b on b.id = s.business_id order by b.name"
    )
    assert [(r["name"], r["segment_id"], r["type"], r["window"].days) for r in rows] == [
        ("Acme Robotics", "firms-gb", "funding", 60),
        ("Indrus", "firms-au", "funding", 60),
        ("Nectar", "firms-us", "launch", 30),
    ]
    assert rows[1]["details"]["founders"][0]["source_url"] == INDRUS

    # The next run judges nothing again.
    again = FakeRouter({"classify_startup_item": answers})
    transport, _ = mock_transport(routes())
    await fr.watch(ctx(again), segments, ListSink(), transport=transport)
    assert again.calls == []


async def test_the_daily_allowance_limits_ai_calls(clean_db: str, fast: None) -> None:
    db.set_setting("funding_rss.items_per_day", 1)
    transport, _ = mock_transport(routes())
    router = FakeRouter({"classify_startup_item": answers})
    context = ctx(router)
    sink = ListSink()
    await fr.watch(context, load_segments(), sink, transport=transport)
    assert len(router.calls) == 1 and len(sink.added) == 1
    transport, _ = mock_transport(routes())
    later = ctx(FakeRouter({"classify_startup_item": answers}))
    await fr.watch(later, load_segments(), ListSink(), transport=transport)
    assert later.stats["funding_rss.daily_cap_reached"] == 1


async def test_every_feed_failing_is_a_source_error_and_gdelt_can_be_off(clean_db: str, fast: None) -> None:
    db.set_setting("sources_enabled", {"gdelt": False})
    transport, seen = mock_transport({"*": (503, "Service Unavailable")})
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await fr.watch(context, load_segments(), ListSink(), transport=transport)
    row = db.fetch_one("select last_error from public.source_health where source = 'funding_rss'")
    assert row is not None and row["last_error"].startswith(
        "no feed could be read: inc42 (robots_skip"
    )  # a 503 robots.txt: skip the host
    assert not any("gdeltproject" in str(r.url) for r in seen) and context.stats["funding_rss.gdelt_skipped"] == 1


async def test_gdelt_rate_limit_and_a_bad_answer_are_quiet(clean_db: str, fast: None) -> None:
    transport, seen = mock_transport(routes(**{GDELT_API: (429, "Please limit requests to one every 5 seconds")}))
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    sink = ListSink()
    await fr.watch(context, load_segments(), sink, transport=transport)
    assert {s.business_hint["name"] for s, _ in sink.added} == {"Nectar", "Indrus"}
    assert len([r for r in seen if "gdeltproject" in str(r.url)]) == 2  # one wait and one retry, then stop
    assert context.stats["gdelt.rate_limited"] == 1

    transport, _ = mock_transport(routes(**{GDELT_API: (200, "Your query was too short or too long.")}))
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    await fr.watch(context, load_segments(), ListSink(), transport=transport)  # a text notice, not JSON: no items
    assert "funding_rss.gdelt_articles" in context.stats


async def test_no_startup_segment_means_no_request(clean_db: str, fast: None) -> None:
    transport, seen = mock_transport(routes())
    context = ctx(FakeRouter({"classify_startup_item": answers}))
    clinics = {k: v for k, v in load_segments().items() if k == "clinics-in"}
    await fr.watch(context, clinics, ListSink(), transport=transport)
    assert seen == [] and context.stats["funding_rss.no_startup_segments"] == 1


# ---- the backlog pass ---------------------------------------------------------------------------------------------


async def test_backlog_reads_older_pages_and_gdelt_week_by_week(
    clean_db: str, fast: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fr, "FEEDS", (fr.Feed("techcrunch", TC_FEED),))
    pages: list[str] = []
    windows: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if url.startswith(GDELT_API):
            windows.append((request.url.params["startdatetime"], request.url.params["enddatetime"]))
            assert "timespan" not in request.url.params and request.url.params["maxrecords"] == "250"
            return httpx.Response(200, json={"articles": []})
        if url.startswith(TC_FEED):
            n = int(request.url.params.get("paged", "1"))
            pages.append(url)
            stamp = (datetime.now(UTC) - timedelta(days=8 * n)).strftime("%a, %d %b %Y %H:%M:%S +0000")
            body = (
                f'<?xml version="1.0"?><rss version="2.0"><channel><item><title>Co{n} raises pre-seed round</title>'
                f"<link>https://techcrunch.com/co{n}</link><pubDate>{stamp}</pubDate><description>Co{n}, a two-person "
                "startup, raised a pre-seed round to build its first app for clinics. " + "More words. " * 60
                + "</description></item></channel></rss>"
            )  # fmt: skip
            return feed(body)
        return httpx.Response(404)

    transport, _ = mock_transport({"*": handler})
    replies = [
        answer(company_name=f"Co{n}", company_website=None, evidence_quote="raised a pre-seed round")
        for n in range(1, 4)
    ]
    router = FakeRouter({"classify_startup_item": replies})
    context = ctx(router)
    sink = ListSink()
    run = Pass(days=20, cap=50, backlog=True)
    await fr.backlog(context, load_segments(), sink, run, transport=transport)
    assert len(pages) == 3 and pages[1].endswith("?paged=2")  # page 3 reaches past 20 days
    assert [s.business_hint["name"] for s, _ in sink.added] == ["Co1", "Co2"]  # Co3 is 24 days old
    assert len(windows) == 3  # 20 days, a week at a time
    assert context.budget.calls_today("other", ["funding_rss_item"]) == 0  # the nightly allowance is untouched
