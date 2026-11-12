"""Signal adapters (Steps 5.9 to 5.11): careers page changes, GDELT news and grounded-search public asks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.models import NewsClassification, PageChangeClassification, PublicAskItem, PublicAskResults
from nument_engine.sources.careers_watch import CareersWatchAdapter, WatchTarget, added_lines, text_hash
from nument_engine.sources.gdelt import GdeltAdapter, parse_articles
from nument_engine.sources.grounded_search import Citation, GroundedSearchAdapter, answer_from

from .sources_helpers import (
    FakeRouter,
    clean_db,
    ctx,
    fixture_json,
    insert_business,
    mock_transport,
    no_network,
    segment,
)

__all__ = ["clean_db", "no_network"]

OLD_CAREERS = "Careers at Lotus Skin Clinic\nJoin our team\nSenior Dermatologist\nHome | About | Contact"
NEW_CAREERS = (
    "Careers at Lotus Skin Clinic\nJoin our team\nSenior Dermatologist\n"
    "Front Desk Executive (Baner): answer patient calls and book appointments\nHome | About | Contact"
)


# ---- careers watch ------------------------------------------------------------------------------------


def test_added_lines_ignore_site_chrome() -> None:
    chrome = {"Home | About | Contact", "Footer line"}
    added = added_lines(OLD_CAREERS, NEW_CAREERS + "\nFooter line", chrome)
    assert added == ["Front Desk Executive (Baner): answer patient calls and book appointments"]


def target(business_id: str, text: str = OLD_CAREERS) -> WatchTarget:
    return WatchTarget(
        page_id="00000000-0000-0000-0000-000000000001",
        url="https://lotusskin-nlead.in/careers",
        text=text,
        text_hash=text_hash(text),
        fetched_at=datetime.now(UTC) - timedelta(days=1),
        field="careers_url",
        business_id=business_id,
        name="Lotus Skin Clinic",
        segment_id="clinics-in",
    )


def change(quote: str, signal_type: str = "hiring_frontdesk") -> PageChangeClassification:
    return PageChangeClassification(
        change_type="new_job", roles=["Front Desk Executive"], quote=quote, signal_type=signal_type
    )  # type: ignore[arg-type]


def test_a_changed_careers_page_becomes_a_signal_with_a_verified_quote() -> None:
    """Step 5.18: a changed careers page fixture turns into hiring_frontdesk with a quote found in the page."""
    quote = "Front Desk Executive (Baner): answer patient calls"
    router = FakeRouter({"classify_page_change": [change(quote)]})
    watcher = CareersWatchAdapter(ctx(router))
    added = added_lines(OLD_CAREERS, NEW_CAREERS)
    sig = watcher.classify(target("b-1"), NEW_CAREERS, added)
    assert sig is not None and sig.type == "hiring_frontdesk" and sig.business_id == "b-1"
    assert sig.quote == quote and sig.url == "https://lotusskin-nlead.in/careers"
    assert sig.evidence_key.startswith("https://lotusskin-nlead.in/careers|") and sig.details["date_estimated"]
    assert router.calls[0][1]["added_text"].startswith("Front Desk Executive")


def test_an_invented_quote_is_dropped() -> None:
    router = FakeRouter({"classify_page_change": [change("We are hiring 10 receptionists today")]})
    watcher = CareersWatchAdapter(ctx(router))
    assert watcher.classify(target("b-1"), NEW_CAREERS, added_lines(OLD_CAREERS, NEW_CAREERS)) is None
    assert watcher.ctx.stats["careers_watch.quote_not_found"] == 1


async def test_check_refetches_classifies_and_stores_the_new_text(
    clean_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    bid = insert_business(
        name="Lotus Skin Clinic",
        status="researched",
        website="https://lotusskin-nlead.in/",
        web_domain="lotusskin-nlead.in",
    )
    page_id = db.scalar(
        "insert into public.pages (business_id, url, text, text_hash, fetched_at) values (%s, %s, %s, %s, %s) "
        "returning id",
        [
            bid,
            "https://lotusskin-nlead.in/careers",
            OLD_CAREERS,
            text_hash(OLD_CAREERS),
            datetime.now(UTC) - timedelta(days=2),
        ],
    )
    db.execute(
        "insert into public.facts (business_id, field, value, quote, url, model, verified) "
        "values (%s, 'careers_url', %s, %s, %s, 'rule', true)",
        [bid, db.Jsonb({"url": "https://lotusskin-nlead.in/careers"}), "careers", "https://lotusskin-nlead.in/careers"],
    )
    html = "<html><body>" + "".join(f"<p>{line}</p>" for line in NEW_CAREERS.splitlines()) + "</body></html>"
    transport, _ = mock_transport({"https://lotusskin-nlead.in/robots.txt": (404, ""), "*": (200, html)})
    monkeypatch.setattr(CareersWatchAdapter, "min_gap_s", 0.0)
    router = FakeRouter({"classify_page_change": [change("Front Desk Executive (Baner)")]})
    async with CareersWatchAdapter(ctx(router), transport=transport) as watcher:
        targets = watcher.targets(["clinics-in"], 10)
        assert [t.page_id for t in targets] == [str(page_id)]
        sigs = await watcher.watch(["clinics-in"])
    assert len(sigs) == 1 and sigs[0].business_id == bid
    stored = db.fetch_one("select text, text_hash from public.pages where id = %s", [page_id])
    assert stored is not None and "Front Desk Executive" in stored["text"]
    assert stored["text_hash"] == text_hash(stored["text"])


# ---- GDELT -------------------------------------------------------------------------------------------


def news(**over: Any) -> NewsClassification:
    base: dict[str, Any] = {
        "relevant": True,
        "business_name": "Lotus IVF",
        "city": "Pune",
        "signal_type": "new_branch",
        "quote": "Lotus IVF opens second centre in Baner",
        "confidence": 0.9,
    }
    return NewsClassification(**{**base, **over})


def test_gdelt_articles_parse() -> None:
    arts = parse_articles(fixture_json("gdelt", "artlist.json"))
    assert len(arts) == 2 and arts[0].seen == datetime(2026, 11, 10, 8, 15, tzinfo=UTC)
    assert parse_articles({}) == []


ARTICLE = (
    "<html><body><nav>Home</nav><article><h1>Lotus IVF opens second centre in Baner</h1>"
    "<p>Pune: Lotus IVF opened its second centre in Baner on Monday, adding six consultation rooms.</p>"
    "<p>The clinic said it now sees 40 couples a day.</p></article></body></html>"
)


async def test_gdelt_news_becomes_a_growth_signal(monkeypatch: pytest.MonkeyPatch, clean_db: str) -> None:
    routes = {
        "https://api.gdeltproject.org/api/v2/doc/doc": (200, fixture_json("gdelt", "artlist.json")),
        "https://news-nlead.in/robots.txt": (404, ""),
        "https://news-nlead.in/pune/lotus-ivf-opens-second-centre-in-baner": (200, ARTICLE),
        "https://news-nlead.in/markets/sensex": (200, "<html><body><p>Markets</p></body></html>"),
    }
    transport, _ = mock_transport(routes)
    monkeypatch.setattr(GdeltAdapter, "min_gap_s", 0.0)
    router = FakeRouter({"classify_news": [news(), news(relevant=False, signal_type="none", quote=None)]})
    async with GdeltAdapter(ctx(router), transport=transport) as gdelt:
        gdelt.pages.min_gap = 0.0
        sigs = await gdelt.signals_for(segment(), budget=1)
    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.type == "new_branch" and sig.business_hint == {"name": "Lotus IVF", "city": "Pune"}
    assert sig.details["source"] == "GDELT" and sig.details["event_key"] == "growth:2026-11"
    assert sig.evidence_key == "https://news-nlead.in/pune/lotus-ivf-opens-second-centre-in-baner"


async def test_gdelt_rate_limit_waits_once_then_stops(monkeypatch: pytest.MonkeyPatch, clean_db: str) -> None:
    transport, seen = mock_transport({"*": (429, "Please limit requests to one every 5 seconds")})
    monkeypatch.setattr(GdeltAdapter, "min_gap_s", 0.0)
    monkeypatch.setattr("nument_engine.sources.gdelt.RATE_LIMIT_WAIT_S", 0.0)
    context = ctx(FakeRouter({}))
    async with GdeltAdapter(context, transport=transport) as gdelt:
        assert await gdelt.search("anything") == []
        assert gdelt.rate_limited
    assert len(seen) == 2 and context.stats["gdelt.rate_limited"] == 1


# ---- grounded search -----------------------------------------------------------------------------------

REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"


def ask(url: str, quote: str, posted: str | None = None, city: str = "Pune") -> PublicAskItem:
    return PublicAskItem(
        poster_business="Lotus Skin Clinic",
        poster_city=city,
        need="A WhatsApp booking bot for the clinic",
        quote=quote,
        url=url,
        posted_date=posted or datetime.now(UTC).date().isoformat(),
    )


class Grounded:
    """What the router may return for a grounded call: the parsed items plus the citations."""

    def __init__(self, items: list[PublicAskItem], chunks: list[dict[str, str]]) -> None:
        self.items = items
        self.grounding = {"chunks": chunks, "queries": ["q"]}


def relevant(_: dict[str, Any]) -> Any:
    from nument_engine.models import SignalClassification

    return SignalClassification(
        is_relevant=True,
        role_category="builder",
        employer_name="Lotus Skin Clinic",
        employer_website=None,
        employer_domain="clinics",
        city="Pune",
        evidence_quote="looking for",
        confidence=0.9,
    )


def test_answer_shapes() -> None:
    parsed = PublicAskResults(items=[ask("https://forum-nlead.in/t/1", "Looking for a developer")])
    a = answer_from((parsed, {"chunks": [{"uri": "https://forum-nlead.in/t/1", "title": "forum"}]}))
    assert len(a.items) == 1 and a.citations[0].uri == "https://forum-nlead.in/t/1"
    b = answer_from(Grounded(parsed.items, [{"uri": REDIRECT + "x", "title": "linkedin.com"}]))
    assert b.citations[0].uri.startswith(REDIRECT)
    c = answer_from(type("R", (), {"text": '{"items": []}', "grounding": None})())
    assert c.items == [] and c.citations == []


async def test_public_ask_rules(monkeypatch: pytest.MonkeyPatch, clean_db: str) -> None:
    forum = "https://forum-nlead.in/t/clinic-bot-123"
    linkedin = "https://www.linkedin.com/posts/lotus-skin-clinic_whatsapp-bot-123"
    items = [
        ask(forum, "Looking for a developer to build a WhatsApp booking bot for our clinic"),
        ask(linkedin, "We need a WhatsApp chatbot for patient bookings, DM me"),
        ask("https://not-cited-nlead.in/post", "Looking for an agency"),  # never cited by the search
        ask(forum + "-old", "Looking for a developer", posted="2026-09-01"),  # too old
    ]
    chunks = [
        {"uri": REDIRECT + "a", "title": "forum-nlead.in"},
        {"uri": REDIRECT + "b", "title": "linkedin.com"},
        {"uri": REDIRECT + "c", "title": "forum-nlead.in"},
    ]
    page = "<html><body><p>Looking for a developer to build a WhatsApp booking bot for our clinic in Baner.</p></body></html>"
    routes = {
        REDIRECT + "a": httpx.Response(302, headers={"location": forum}),
        REDIRECT + "b": httpx.Response(302, headers={"location": linkedin}),
        REDIRECT + "c": httpx.Response(302, headers={"location": forum + "-old"}),
        "https://forum-nlead.in/robots.txt": (404, ""),
        forum: (200, page),
    }
    transport, seen = mock_transport(routes)
    router = FakeRouter({"grounded_search": lambda inputs: Grounded(items, chunks), "classify_signal": relevant})
    monkeypatch.setattr(GroundedSearchAdapter, "todays_queries", staticmethod(lambda seg, day=None: ["q1"]))
    context = ctx(router)
    async with GroundedSearchAdapter(context, transport=transport) as gs:
        gs.pages.min_gap = 0.0
        sigs = await gs.signals_for(segment(), budget=5)
    by_url = {s.url: s for s in sigs}
    assert set(by_url) == {forum, linkedin}
    assert by_url[forum].points is None and by_url[forum].details["snippet_only"] is False
    assert by_url[linkedin].points == 6.0 and by_url[linkedin].details["snippet_only"] is True
    assert context.stats["grounded_search.uncited_dropped"] == 1 and context.stats["grounded_search.too_old"] == 1
    assert not any("linkedin.com" in r.url.host for r in seen)  # the LinkedIn page was never opened
    assert all(s.business_hint == {"name": "Lotus Skin Clinic", "city": "Pune"} for s in sigs)


async def test_a_quote_missing_from_the_page_drops_the_item(monkeypatch: pytest.MonkeyPatch, clean_db: str) -> None:
    forum = "https://forum-nlead.in/t/9"
    routes = {
        "https://forum-nlead.in/robots.txt": (404, ""),
        forum: (200, "<html><body><p>Completely different discussion about cricket.</p></body></html>"),
    }
    transport, _ = mock_transport(routes)
    items = [ask(forum, "Looking for a developer to build a WhatsApp booking bot")]
    router = FakeRouter(
        {"grounded_search": lambda _: Grounded(items, [{"uri": forum, "title": "forum"}]), "classify_signal": relevant}
    )
    monkeypatch.setattr(GroundedSearchAdapter, "todays_queries", staticmethod(lambda seg, day=None: ["q1"]))
    context = ctx(router)
    async with GroundedSearchAdapter(context, transport=transport) as gs:
        gs.pages.min_gap = 0.0
        assert await gs.signals_for(segment(), budget=1) == []
    assert context.stats["grounded_search.quote_not_on_page"] == 1


def test_queries_rotate_every_third_day() -> None:
    seg = segment()
    runs = [GroundedSearchAdapter.todays_queries(seg, day) for day in range(700_000, 700_003)]
    assert sorted(q for day in runs for q in day) == sorted(seg.public_ask_queries)
    assert Citation("u", "t").resolved is None
