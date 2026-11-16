"""Feeds of startup items (lane E1a): parsing real RSS and Atom, polite fetching with every failure state, older
pages for the backlog, and the checks that turn a classifier answer into a routed signal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.http import PoliteClient
from nument_engine.segments import load_segments
from nument_engine.sources import rss
from nument_engine.sources.base import SourceAdapter
from nument_engine.sources.rss import ItemJudge, Pass, StartupItem

from .e1a_helpers import ATOM_TYPE, answer, fast, feed, fixture, fresh_dates
from .sources_helpers import BudgetExceeded, FakeRouter, clean_db, ctx, mock_transport, no_network

__all__ = ["clean_db", "fast", "no_network"]

TC_URL = "https://techcrunch.com/category/startups/feed/"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
EN_DASH, RSQUO = chr(0x2013), chr(0x2019)


# ---- parsing --------------------------------------------------------------------------------------------------


def test_rss_items_are_read_with_utc_dates_and_plain_text() -> None:
    items, state = rss.parse_feed(fixture("techcrunch_startups.xml").encode(), TC_URL, "techcrunch", now=NOW)
    assert state == "ok" and [i.feed for i in items] == ["techcrunch"] * 3
    first, _, last = items
    assert first.title == "AI agent startup LangChain hits $3B valuation"
    assert first.link == "https://techcrunch.com/2026/11/13/ai-agent-startup-langchain-hits-3b-valuation/"
    assert first.published == datetime(2026, 11, 13, 19, 37, 57, tzinfo=UTC)
    assert first.summary.startswith("LangChain now claims 7,000 customers") and first.content == ""
    assert last.title == f"With $720M round, Britain{RSQUO}s Fractile gets a leg up in the race for AI chips"
    assert first.key == "https://techcrunch.com/2026/11/13/ai-agent-startup-langchain-hits-3b-valuation"


def test_full_text_feeds_use_their_content() -> None:
    url = "https://yourstory.com/category/funding/feed"
    items, _ = rss.parse_feed(fixture("yourstory_funding.xml").encode(), url, "yourstory", now=NOW)
    cosmo = items[1]
    assert cosmo.title == "Spacetech startup Cosmoserve raises $6M in seed round"  # CDATA newlines trimmed
    assert "Hyderabad-based spacetech startup, has raised $6 million in a seed round" in cosmo.text()
    assert cosmo.text().startswith("Cosmoserve also opened a facility")  # the description adds a fact
    assert "<p>" not in cosmo.text()


def test_atom_entries_drop_tracking_parameters() -> None:
    url = "https://betalist.com/startups/feed_original"
    items, state = rss.parse_feed(fixture("betalist.atom").encode(), url, "betalist", now=NOW)
    assert state == "ok" and len(items) == 2
    wfh = items[0]
    assert wfh.title == f"WFH Alert {EN_DASH} Remote jobs reviewed by a person before they reach your inbox"
    assert wfh.link == "https://betalist.com/startups/wfh-alert"  # utm_* removed
    assert wfh.published == datetime(2026, 11, 15, 17, 35, tzinfo=UTC)
    assert (
        wfh.text().startswith("WFH Alert is a remote job discovery service") and wfh.text().count("WFH Alert is") == 1
    )


def rss_doc(*items: str) -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>' + "".join(items) + "</channel></rss>"
    ).encode()


def item(title: str, link: str | None = "https://news.example.com/a", date: str | None = None) -> str:
    parts = [f"<title>{title}</title>"]
    if link:
        parts.append(f"<link>{link}</link>")
    if date:
        parts.append(f"<pubDate>{date}</pubDate>")
    return "<item>" + "".join(parts) + "<description>Acme raised a seed round.</description></item>"


def test_dates_missing_unreadable_or_in_the_future() -> None:
    body = rss_doc(
        item("No date", "https://news.example.com/1"),
        item("Garbage date", "https://news.example.com/2", "not a date at all"),
        item("Next week", "https://news.example.com/3", "Mon, 23 Nov 2026 10:00:00 +0000"),
        item("In two hours", "https://news.example.com/4", "Mon, 16 Nov 2026 14:00:00 +0000"),
        item("India time", "https://news.example.com/5", "Mon, 16 Nov 2026 09:30:00 +0530"),
    )
    items, state = rss.parse_feed(body, "https://news.example.com/feed/", now=NOW)
    assert state == "ok"
    dates = {i.title: i.published for i in items}
    assert dates["No date"] is None and dates["Garbage date"] is None and dates["Next week"] is None
    assert dates["In two hours"] == NOW  # a feed clock a little ahead is clamped to now
    assert dates["India time"] == datetime(2026, 11, 16, 4, 0, tzinfo=UTC)


def test_relative_links_resolve_and_items_without_links_are_skipped() -> None:
    body = rss_doc(item("Relative", "/2026/11/acme-seed"), item("No link", None))
    items, _ = rss.parse_feed(body, "https://news.example.com/feed/", now=NOW)
    assert [i.link for i in items] == ["https://news.example.com/2026/11/acme-seed"]


def test_not_a_feed_and_broken_xml() -> None:
    assert rss.parse_feed(b"<html><body><h1>Welcome</h1></body></html>", "https://x.example.com/feed")[1] == "not_feed"
    assert rss.parse_feed(b"", "https://x.example.com/feed")[1] == "not_feed"
    broken = rss_doc(item("Acme raises seed", "https://news.example.com/1"), item("Cut off", "https://n"))[:-40]
    items, state = rss.parse_feed(broken, "https://news.example.com/feed/", now=NOW)
    assert state == "ok" and items[0].title == "Acme raises seed"  # what could be read is kept
    assert rss.parse_feed(b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>x', "u")[1] == "bad_xml"


# ---- fetching -------------------------------------------------------------------------------------------------


async def fetch(routes: dict[str, Any], url: str = TC_URL) -> tuple[rss.FeedPage, list[httpx.Request], PoliteClient]:
    transport, seen = mock_transport(routes)
    client = PoliteClient("funding_rss", policy="public", transport=transport)
    page = await rss.fetch_feed(client, url, "techcrunch")
    return page, seen, client


ROBOTS_OK = {"https://techcrunch.com/robots.txt": (404, "")}


async def test_fetch_ok_and_redirect_followed(fast: None) -> None:
    page, _, _ = await fetch({**ROBOTS_OK, TC_URL: feed(fixture("techcrunch_startups.xml"))})
    assert page.ok and len(page.items) == 3 and page.status == 200
    moved = httpx.Response(301, headers={"location": TC_URL})
    page, seen, _ = await fetch({**ROBOTS_OK, "https://techcrunch.com/startups/feed": moved,
                                 TC_URL: feed(fixture("techcrunch_startups.xml"))},
                                url="https://techcrunch.com/startups/feed")  # fmt: skip
    assert page.ok and len(page.items) == 3 and str(seen[-1].url) == TC_URL


@pytest.mark.parametrize(
    ("response", "state"),
    [
        ((404, "gone"), "broken"),
        ((410, "gone"), "broken"),
        ((500, "oops"), "broken"),
        ((403, "Forbidden"), "blocked"),
        ((429, "slow down"), "blocked"),
        ((200, "<html><title>Just a moment...</title><body>cf-chl</body></html>"), "blocked"),
        ((200, "<html><body><h1>Our new homepage</h1></body></html>"), "not_feed"),
    ],
)
async def test_feed_failures_are_states_not_exceptions(fast: None, response: Any, state: str) -> None:
    page, _, _ = await fetch({**ROBOTS_OK, TC_URL: response})
    assert page.state == state and page.items == []


async def test_a_blocked_host_is_not_asked_again_in_the_run(fast: None) -> None:
    page, seen, client = await fetch({**ROBOTS_OK, TC_URL: (403, "Forbidden")})
    assert page.state == "blocked"
    again = await rss.fetch_feed(client, TC_URL, "techcrunch")
    assert again.state == "blocked" and len([r for r in seen if r.url.path != "/robots.txt"]) == 1


async def test_robots_disallow_and_timeouts(fast: None) -> None:
    page, seen, _ = await fetch({"https://techcrunch.com/robots.txt": (200, "User-agent: *\nDisallow: /category/")})
    assert page.state == "robots_skip" and all(r.url.path == "/robots.txt" for r in seen)

    def timeout(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ReadTimeout("slow", request=request)

    page, seen, _ = await fetch({"*": timeout})
    assert page.state == "unknown" and len([r for r in seen if r.url.path != "/robots.txt"]) == 2  # one retry


async def test_never_fetch_hosts_are_refused(fast: None) -> None:
    page, seen, _ = await fetch({}, url="https://www.linkedin.com/feed/")
    assert page.state == "never_fetch" and seen == []


async def test_older_pages_until_the_window_and_stops(fast: None) -> None:
    def page(n: int) -> httpx.Response:
        stamp = (NOW - timedelta(days=10 * n)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        return feed(rss_doc(item(f"Acme {n}", f"https://news.example.com/{n}", stamp)).decode())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return page(int(request.url.params.get("paged", "1")))

    transport, seen = mock_transport({"*": handler})
    client = PoliteClient("funding_rss", policy="public", transport=transport)
    items, pages = await rss.fetch_feed_back(
        client, "https://news.example.com/feed/", "x", since=NOW - timedelta(days=25), now=NOW
    )
    assert [i.title for i in items] == ["Acme 1", "Acme 2", "Acme 3"]  # page 3 reaches past the window: last one
    assert [str(r.url) for r in seen if r.url.path != "/robots.txt"][1] == "https://news.example.com/feed/?paged=2"

    same = {"*": lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else page(1)}
    transport, _ = mock_transport(same)
    client = PoliteClient("funding_rss", policy="public", transport=transport)
    items, pages = await rss.fetch_feed_back(
        client, "https://news.example.com/feed/", "x", since=NOW - timedelta(days=60), now=NOW
    )
    assert len(items) == 1 and len(pages) == 2  # the site ignores ?paged: stop at the repeat

    robots = {"https://news.example.com/robots.txt": (200, "User-agent: *\nDisallow: /*?*"), "*": lambda r: page(1)}
    transport, _ = mock_transport(robots)
    client = PoliteClient("funding_rss", policy="public", transport=transport)
    items, pages = await rss.fetch_feed_back(
        client, "https://news.example.com/feed/", "x", since=NOW - timedelta(days=60), now=NOW
    )
    assert len(items) == 1 and [p.state for p in pages] == ["ok", "robots_skip"]


# ---- checks on answers ----------------------------------------------------------------------------------------


def test_verbatim_quotes_are_cut_from_the_source() -> None:
    text = f"Brightcart, an Austin startup,  has Raised $600K in a pre-seed round. Britain{RSQUO}s best."
    assert rss.verbatim("raised $600k in a pre-seed round", text) == "Raised $600K in a pre-seed round"
    assert rss.verbatim("Britain's best", text) == f"Britain{RSQUO}s best"
    assert rss.verbatim("raised $6M in a seed round", text) is None
    assert rss.verbatim("call [phone] now", "call [phone] now") is None
    assert rss.verbatim("abc", text) is None and rss.verbatim(None, text) is None


def test_names_must_be_written_in_the_item() -> None:
    text = "Founded by Maya Chen and Leo Park. Annabel joined later."
    assert rss.names_in(["Maya Chen", "maya chen", "Leo", "Ann", "Priya Rao"], text, limit=5) == ["Maya Chen", "Leo"]


@pytest.mark.parametrize(
    ("value", "code"),
    [("US", "us"), ("uk", "gb"), ("United Kingdom", "gb"), ("United States of America", "us"), ("India", "in"),
     ("Remote", None), ("", None), (None, None), ("Atlantis", None)],
)  # fmt: skip
def test_iso_country(value: Any, code: str | None) -> None:
    assert rss.iso_country(value) == code


@pytest.mark.parametrize(
    ("site", "code"),
    [("https://acme.co.uk/", "gb"), ("acme.in", "in"), ("https://www.acme.com.au", "au"), ("acme.de", "de"),
     ("https://acme.io", None), ("acme.ai", None), ("acme.com", None), ("", None), (None, None)],
)  # fmt: skip
def test_country_from_domain(site: str | None, code: str | None) -> None:
    assert rss.country_from_domain(site) == code


def test_company_sites() -> None:
    assert rss.is_company_site("https://brightcart.io/jobs")
    for url in ("https://github.com/acme/x", "https://acme.github.io", "https://apps.apple.com/app/x",
                "https://www.youtube.com/watch?v=1", "https://acme.vercel.app", "https://www.linkedin.com/company/x",
                "https://news.ycombinator.com/item?id=1", "ftp://acme.io", None):  # fmt: skip
        assert not rss.is_company_site(url), url
    assert rss.first_company_site(["https://github.com/a/b", "https://acme.io/pricing?x=1"]) == "https://acme.io/"


@pytest.mark.parametrize(
    ("country", "why"),
    [("us", "ok"), (None, "no_country"), ("de", "country_blocked"), ("ng", "country_not_allowed"),
     ("nl", "segment_off")],
)  # fmt: skip
def test_route_reasons(country: str | None, why: str) -> None:
    segments = {k: v for k, v in load_segments().items() if k != "firms-nl"}  # every allowed country has one now
    seg, got = rss.route(country, segments)
    assert got == why and (seg is not None) is (why == "ok")


TEXT = (
    "Brightcart, a three-person Austin startup founded by Maya Chen and Leo Park, raised $600K in a pre-seed "
    "round led by Northlight Ventures. See brightcart.io for the app."
)


def news_item(**changes: Any) -> StartupItem:
    base: dict[str, Any] = {
        "source": "funding_rss",
        "key": "https://news.example.com/brightcart",
        "url": "https://news.example.com/brightcart",
        "title": "Brightcart raises $600K pre-seed to help grocers sell online",
        "text": TEXT,
        "published": datetime.now(UTC) - timedelta(days=2),
        "feed": "techcrunch",
    }
    return StartupItem(**{**base, **changes})


def judge(*answers: Any, **kwargs: Any) -> ItemJudge:
    return ItemJudge(ctx(FakeRouter({"classify_startup_item": list(answers)})), load_segments(), max_team=10,
                     max_raise_usd=2_000_000, **kwargs)  # fmt: skip


def test_a_pre_seed_round_becomes_a_funding_signal_with_checked_details() -> None:
    sig, why = judge(answer()).judge(news_item())
    assert why == "signal" and sig is not None
    assert sig.type == "funding" and sig.segment_id == "firms-us" and sig.source == "funding_rss"
    assert sig.quote == "raised $600K in a pre-seed round" and sig.evidence_key == "https://news.example.com/brightcart"
    assert sig.business_hint == {"name": "Brightcart", "city": "Austin", "website": "https://brightcart.io/"}
    d = sig.details
    assert d["round"] == "pre_seed" and d["amount_usd"] == 600000 and d["investors"] == ["Northlight Ventures"]
    assert d["founders"] == [
        {"name": "Maya Chen", "role": "Founder", "source_url": "https://news.example.com/brightcart"},
        {"name": "Leo Park", "role": "Founder", "source_url": "https://news.example.com/brightcart"},
    ]
    assert d["team_size"] == 3 and d["team_size_source"] == "item" and d["country_from"] == "item"
    assert d["feed"] == "techcrunch" and "date_estimated" not in d


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"is_relevant": False}, "not_relevant"),
        ({"confidence": 0.4}, "low_confidence"),
        ({"round": "series_a"}, "late_round"),
        ({"round": "series_b_plus"}, "late_round"),  # the classifier's own word for B and later
        ({"amount_usd": 5_000_000.0}, "raise_too_big"),
        ({"team_size": 25}, "too_big"),
        ({"is_startup": False}, "not_startup"),
        ({"company_name": None}, "no_company"),
        ({"company_name": "Stealth startup"}, "no_company"),
        ({"hq_country": "de"}, "country_blocked"),
        ({"hq_country": "ng"}, "country_not_allowed"),
        ({"hq_country": None, "company_website": None}, "no_country"),
    ],
)
def test_items_outside_the_target_are_dropped(changes: dict[str, Any], why: str) -> None:
    sig, got = judge(answer(**changes)).judge(news_item())
    assert sig is None and got == why


def test_unknowns_pass_and_nothing_unwritten_is_kept() -> None:
    sig, why = judge(
        answer(
            team_size=None,
            round="unknown",
            amount_usd=None,
            founders=["Priya Rao"],
            investors=["Acme Capital"],
            company_website="made-up.io",
            evidence_quote="a quote that is not in the item",
        )
    ).judge(news_item())
    assert why == "signal" and sig is not None
    assert sig.quote == "Brightcart raises $600K pre-seed to help grocers sell online"  # the title, verbatim
    assert "website" not in sig.business_hint  # a site the item never shows is not kept
    for key in ("round", "amount_usd", "investors", "founders", "team_size"):
        assert key not in sig.details, key


def test_country_from_the_website_domain_when_the_item_has_none() -> None:
    text = TEXT.replace("brightcart.io", "brightcart.co.uk")
    sig, why = judge(answer(hq_country=None, company_website="brightcart.co.uk", city=None)).judge(news_item(text=text))
    assert why == "signal" and sig is not None and sig.segment_id == "firms-gb"
    assert sig.details["country_from"] == "website_domain"


def test_windows_and_fixed_types() -> None:
    old = news_item(published=datetime.now(UTC) - timedelta(days=45))
    assert judge(answer()).judge(old)[0] is not None  # a round stays news for 60 days
    assert judge(answer(event="launch")).judge(old) == (None, "too_old")  # a launch for 30
    undated = news_item(published=None)
    sig, _ = judge(answer()).judge(undated)
    assert sig is not None and sig.details["date_estimated"] is True
    launch = news_item(source="hn_launches", signal_type="launch", website="https://brightcart.io/app")
    sig, _ = judge(answer(event="funding", company_website=None)).judge(launch)
    assert sig is not None and sig.type == "launch" and sig.business_hint["website"] == "https://brightcart.io/"
    sig, _ = judge(answer(event="other")).judge(news_item())
    assert sig is not None and sig.type == "news"


def test_publisher_site_is_never_the_company_website() -> None:
    sig, _ = judge(answer(company_website="news.example.com")).judge(news_item())
    assert sig is not None and "website" not in sig.business_hint


def test_contacts_are_masked_before_the_ai() -> None:
    router = FakeRouter({"classify_startup_item": [answer()]})
    ItemJudge(ctx(router), load_segments(), max_team=10, max_raise_usd=2e6).judge(
        news_item(text=TEXT + " Press: maya@brightcart.io, +1 512 555 0199.")
    )
    sent = router.calls[0][1]["text"]
    assert "maya@brightcart.io" not in sent and "[email]" in sent and "555 0199" not in sent


# ---- passes, caps and the seen list ---------------------------------------------------------------------------


def test_judge_items_counts_records_and_stops_at_the_cap(clean_db: str) -> None:
    items = [
        news_item(
            key=f"https://news.example.com/{i}", url=f"https://news.example.com/{i}", title=f"Story {i} of a seed round"
        )
        for i in range(4)
    ]
    router = FakeRouter({"classify_startup_item": [answer(), RuntimeError("bad json"), answer(is_relevant=False)]})
    context = ctx(router)
    run = Pass(days=3, cap=2)
    sigs = rss.judge_items(context, ItemJudge(context, load_segments(), max_team=10, max_raise_usd=2e6), items, run)
    assert len(sigs) == 1 and len(router.calls) == 3  # the failed call does not use the allowance
    assert context.stats["funding_rss.no_answer"] == 1 and context.stats["funding_rss.cap_reached"] == 1
    seen = {r["source_key"]: r["payload"]["verdict"] for r in db.fetch_all("select * from public.source_records")}
    assert seen == {
        "https://news.example.com/0": "signal",
        rss.title_key("Story 0 of a seed round"): "signal",  # a copy of the story under another URL is seen too
        "https://news.example.com/2": "not_relevant",
        rss.title_key("Story 2 of a seed round"): "not_relevant",
    }
    assert rss.title_key("Too short a title") is None
    assert context.budget.calls_today("other", ["funding_rss_item"]) == 2
    assert rss.unseen("funding_rss", [i.key for i in items]) == {
        "https://news.example.com/1",
        "https://news.example.com/3",
    }


def test_nightly_pass_uses_what_is_left_of_the_day(clean_db: str) -> None:
    db.set_setting("funding_rss.items_per_day", 5)
    context = ctx()
    for _ in range(3):
        context.budget.record("other", None, "funding_rss_item")
    assert rss.nightly_pass(context, "funding_rss", "funding_rss.items_per_day", 120, days=3).cap == 2
    assert rss.nightly_pass(ctx(limit=1), "funding_rss", "funding_rss.items_per_day", 120, days=3).cap == 1


def test_backlog_pass_stops_on_the_budget_phase_and_the_deadline(
    clean_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ctx(FakeRouter({"classify_startup_item": [answer()] * 3}))
    j = ItemJudge(context, load_segments(), max_team=10, max_raise_usd=2e6)
    items = [news_item(key=f"k{i}", url=f"https://news.example.com/{i}") for i in range(3)]
    monkeypatch.setattr(type(context.budget), "allow_phase", lambda self, phase: False)
    assert rss.judge_items(context, j, items, Pass(days=60, cap=100, backlog=True)) == []
    assert context.stats["funding_rss.budget_stop"] == 1
    monkeypatch.undo()
    assert rss.judge_items(context, j, items, Pass(days=60, cap=100, backlog=True, stop_at=0.0)) == []
    assert context.stats["funding_rss.time_up"] == 1
    sigs = rss.judge_items(context, j, items[:1], Pass(days=60, cap=100, backlog=True))
    assert len(sigs) == 1 and context.budget.calls_today("other", ["funding_rss_item"]) == 0  # not the nightly quota


def test_judging_stops_when_the_ai_budget_says_no(clean_db: str) -> None:
    context = ctx(FakeRouter({"classify_startup_item": [BudgetExceeded("cap"), answer()]}))
    items = [news_item(key=f"k{i}", url=f"https://news.example.com/{i}") for i in range(2)]
    assert (
        rss.judge_items(
            context, ItemJudge(context, load_segments(), max_team=10, max_raise_usd=2e6), items, Pass(3, 10)
        )
        == []
    )
    assert context.ai_stopped and rss.unseen("funding_rss", ["k0", "k1"]) == {"k0", "k1"}


def test_dry_runs_remember_nothing(clean_db: str) -> None:
    context = ctx(FakeRouter({"classify_startup_item": [answer()]}), dry_run=True)
    sigs = rss.judge_items(
        context, ItemJudge(context, load_segments(), max_team=10, max_raise_usd=2e6), [news_item()], Pass(3, 5)
    )
    assert len(sigs) == 1 and db.scalar("select count(*) from public.source_records") == 0


class _Probe(SourceAdapter):
    name = "funding_rss"
    policy = "public"
    failure: str | None = None


async def test_guarded_marks_health(clean_db: str) -> None:
    async def ok() -> int:
        return 1

    probe = _Probe(ctx())
    assert await rss.guarded(probe, ok) == 1
    row = db.fetch_one("select last_ok_at, last_error from public.source_health where source = 'funding_rss'")
    assert row is not None and row["last_ok_at"] is not None

    probe.failure = "no feed could be read"
    await rss.guarded(probe, ok)
    row = db.fetch_one("select last_error from public.source_health where source = 'funding_rss'")
    assert row is not None and row["last_error"] == "no feed could be read"

    db.set_setting("sources_enabled", {"funding_rss": False})
    off = _Probe(ctx())
    assert await rss.guarded(off, ok) is None and off.ctx.stats["skipped.funding_rss"] == 1


async def test_atom_content_type_is_fine(fast: None) -> None:
    url = "https://betalist.com/startups/feed_original"
    page, _, _ = await fetch({"https://betalist.com/robots.txt": (200, "# all allowed"),
                              url: feed(fresh_dates(fixture("betalist.atom"), 1, 2), ATOM_TYPE)}, url=url)  # fmt: skip
    assert page.ok and len(page.items) == 2 and all(i.published for i in page.items)
