"""Startup funding news (15 Nov 2026): the feeds of 13 startup outlets plus GDELT funding queries.

Feeds (checked 16 Nov 2026: each answers a fresh RSS feed and its robots.txt lets us read it): TechCrunch
(startups), Inc42, e27, BetaKit, Startup Daily (funding), YourStory (funding), TechCabal, Disrupt Africa,
LatamList, Tech Funding News, Crunchbase News (seed), AlleyWatch (funding) and Silicon Republic. EU-Startups, the
fourteenth outlet of the plan, is not read: its robots.txt answers a Cloudflare bot check (HTTP 403), which
counts as "do not fetch", and a bot check is never worked around. Inc42's category feed for funding stopped in
2023 and BetaKit's in 2024, so their main feeds are read.

GDELT (`sources/gdelt.py`, credit to GDELT on every signal it found): English news worldwide with seed,
pre-seed or angel phrases, within the shared `gdelt.queries_per_day`; the article is read politely for its text.

A run reads every feed once (a feed that is gone, blocked or disallowed is counted and skipped, the others go
on), drops items older than the window, items already judged (`source_records`, by canonical URL) and repeats of
one story, and keeps only items that read like an early round or a launch: late rounds, big amounts,
acquisitions and weekly round-ups never reach the AI. The rest are judged newest first, at most
`funding_rss.items_per_day` a day: one `classify_startup_item` call each (g_lite), with the article's own page read
when the feed carries only a line or two. `rss.ItemJudge` applies the size gate and the country rules and emits a
`funding`, `launch` or `news` signal with the round, amount, investors and founders the item names.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..http import NeverFetch, PoliteClient, SourceBlocked
from ..logging import get_logger
from ..normalize import canonical_url, clean_text
from ..research.text import article_text
from ..segments import Segment
from . import health
from .base import Signal, SourceAdapter, SourceContext
from .gdelt import Article, GdeltAdapter
from .rss import (
    TEXT_CHARS,
    FeedItem,
    ItemJudge,
    Pass,
    Sink,
    StartupItem,
    bounded,
    fetch_feed,
    fetch_feed_back,
    guarded,
    judge_items,
    nightly_pass,
    title_key,
    to_sink,
    unseen,
)

log = get_logger()

NAME = "funding_rss"
SETTING = "funding_rss.items_per_day"
DEFAULT_PER_DAY = 120
NIGHT_DAYS = 3  # a night lost to an outage does not lose that day's news; dedupe keeps items from repeating
MIN_FEED_TEXT = 600  # shorter feed text: the article's own page is read too
ARTICLE_CHARS = 3000
FETCH_CONCURRENCY = 4
PREFILTER_MARGIN = 1.5  # titles with an amount over 1.5 x startup.max_raise_usd never reach the AI
GDELT_WEEK = timedelta(days=7)
GDELT_BACKLOG_RECORDS = 250
GDELT_RANK = 9  # GDELT items are judged after every feed item


@dataclass(frozen=True)
class Feed:
    key: str
    url: str
    rank: int = 1  # 1: outlets that cover countries we write to; 2: mostly other regions (judged last)
    pageable: bool = True  # WordPress `?paged=N` for the backlog (robots.txt still decides)


FEEDS: tuple[Feed, ...] = (
    Feed("inc42", "https://inc42.com/feed/"),
    Feed("yourstory", "https://yourstory.com/category/funding/feed", pageable=False),
    Feed("startup_daily", "https://www.startupdaily.net/topic/funding/feed/"),
    Feed("betakit", "https://betakit.com/feed/"),
    Feed("e27", "https://e27.co/feed/"),
    Feed("tech_funding_news", "https://techfundingnews.com/feed/"),
    Feed("alleywatch", "https://www.alleywatch.com/category/funding/feed/"),
    Feed("silicon_republic", "https://www.siliconrepublic.com/feed/"),
    Feed("techcrunch", "https://techcrunch.com/category/startups/feed/"),
    Feed("crunchbase_news", "https://news.crunchbase.com/sections/seed/feed/"),
    Feed("latamlist", "https://latamlist.com/feed/", rank=2),
    Feed("techcabal", "https://techcabal.com/feed/", rank=2),
    Feed("disrupt_africa", "https://disruptafrica.com/feed/", rank=2),
)
GDELT_QUERIES: tuple[str, ...] = (
    '("seed round" OR "pre-seed round" OR "seed funding" OR "pre-seed funding" OR "angel round") '
    "(startup OR founders) sourcelang:english",
)

# ---- the code filter before the AI (titles and the first lines only) -----------------------------------------

_EARLY = re.compile(
    r"\b(?:rais(?:e|es|ed|ing)|fund(?:ing|ed|raise|raising)|pre-?\s?seed|seed|angel|round|backed|backing|"
    r"invest(?:s|ed|ment|or|ors)?|secur(?:e|es|ed)|bags?|lands?|nets?|closes|closed|grant|crowd-?fund\w*|"
    r"accelerator|incubat\w+|cohort|launch(?:es|ed)?|debut\w*|unveil\w*|stealth|introduc(?:es|ed))\b",
    re.I,
)
_LATE = re.compile(
    r"\b(?:pre-?\s?)?series\s?[a-z]\b|\bipo\b|\bacqui(?:re|res|red|sition)\b|\bmerg(?:e|es|ed|er)\b|\bunicorn\b|"
    r"\bvaluation\b|\bbillion\b|\bbn\b|\blayoffs?\b|\bdebt\b|\bprivate equity\b",
    re.I,
)
_ROUNDUP = re.compile(
    r"round-?\s?ups?\b|funding galore|\bweekly\b|this week|\bweek'?s\b|biggest (?:funding )?rounds|"
    r"notable startup funding|funding report|deals of the week|\btop \d+ (?:funding|deals|startups)",
    re.I,
)
_EURO, _POUND, _RUPEE = "\u20ac", "\u00a3", "\u20b9"
_AMOUNT = re.compile(
    r"(?P<cur>US\$|USD|A\$|AU\$|AUD|C\$|CA\$|CAD|S\$|SGD|NZ\$|NZD|R\$|BRL|\$|EUR|"
    + _EURO
    + r"|GBP|"
    + _POUND
    + r"|INR|"
    + _RUPEE
    + r"|Rs\.?)\s?(?P<num>\d+(?:[.,]\d+)*)\s?"
    r"(?P<mult>thousand|million|billion|trillion|crores?|lakhs?|mln|mn|bn|cr|k|m|b|l)?\b",
    re.I,
)
_USD_PER = {"usd": 1.0, "aud": 0.65, "cad": 0.72, "sgd": 0.75, "nzd": 0.6, "brl": 0.18, "eur": 1.08, "gbp": 1.27,
            "inr": 0.012}  # fmt: skip
_CURRENCY = {"us$": "usd", "usd": "usd", "$": "usd", "a$": "aud", "au$": "aud", "aud": "aud", "c$": "cad",
             "ca$": "cad", "cad": "cad", "s$": "sgd", "sgd": "sgd", "nz$": "nzd", "nzd": "nzd", "r$": "brl",
             "brl": "brl", "eur": "eur", _EURO: "eur", "gbp": "gbp", _POUND: "gbp", "inr": "inr", _RUPEE: "inr",
             "rs": "inr", "rs.": "inr"}  # fmt: skip
_MULT = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mln": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9,
         "b": 1e9, "trillion": 1e12, "crore": 1e7, "crores": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5,
         "l": 1e5}  # fmt: skip


def _number(raw: str) -> float | None:
    """'1,500,000' -> 1500000, '2.5' -> 2.5, '2,5' (a decimal comma) -> 2.5."""
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        raw = raw.replace(",", "")
    elif raw.count(",") == 1 and "." not in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def amounts_usd(text: str) -> list[float]:
    """Money amounts written in a title, roughly in US dollars ("$720M", "Rs 100 Cr", "EUR 2.5 million")."""
    out: list[float] = []
    for m in _AMOUNT.finditer(text or ""):
        cur = _CURRENCY.get(m.group("cur").lower())
        value = _number(m.group("num"))
        if cur is None or value is None:
            continue
        out.append(value * _MULT.get((m.group("mult") or "").lower(), 1.0) * _USD_PER[cur])
    return out


def prefilter(title: str, lead: str, *, max_raise_usd: float) -> str | None:
    """Why an item never reaches the AI (`roundup`, `late_or_big`, `no_funding_words`), or None to judge it."""
    if _ROUNDUP.search(title):
        return "roundup"
    if _LATE.search(title) or any(a > max_raise_usd * PREFILTER_MARGIN for a in amounts_usd(title)):
        return "late_or_big"
    if not _EARLY.search(f"{title}\n{lead[:600]}"):
        return "no_funding_words"
    return None


class FundingRssAdapter(SourceAdapter):
    name = NAME
    policy = "public"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: PoliteClient | None = None
        self.failure: str | None = None

    @property
    def pages(self) -> PoliteClient:
        """A separate client for the articles themselves (news sites: robots.txt and a 2 second gap per host)."""
        if self._pages is None:
            self._pages = PoliteClient(f"{NAME}_pages", policy="public", transport=self._transport)
        return self._pages

    async def aclose(self) -> None:
        if self._pages is not None:
            await self._pages.aclose()
            self._pages = None
        await super().aclose()

    # ---- reading ---------------------------------------------------------------------------------------------
    async def read_feeds(self, run: Pass, feeds: Sequence[Feed] | None = None) -> list[tuple[Feed, FeedItem]]:
        """Items of every feed (with their older pages in the backlog). A feed that fails is counted and skipped;
        when none could be read the run is an error."""
        out: list[tuple[Feed, FeedItem]] = []
        failed: list[str] = []
        tried = 0
        for feed in FEEDS if feeds is None else feeds:
            if run.time_up():
                self.ctx.add(f"{NAME}.time_up")
                break
            tried += 1
            if run.backlog and feed.pageable:
                items, pages = await fetch_feed_back(
                    self.http, feed.url, feed.key, since=run.since(), time_up=run.time_up
                )
                page = pages[0]
                self.ctx.add(f"{NAME}.feed_pages", len(pages))
            else:
                page = await fetch_feed(self.http, feed.url, feed.key)
                items = page.items
            self.ctx.add(f"{NAME}.feeds_{page.state}")
            if not page.ok:
                failed.append(f"{feed.key} ({page.state}: {page.reason})")
                self.ctx.add(f"{NAME}.feed.{feed.key}.{page.state}")
                log.warning("funding_rss.feed_failed", feed=feed.key, state=page.state, reason=page.reason[:120])
                continue
            out += [(feed, item) for item in items]
        if tried and len(failed) == tried:
            self.failure = "no feed could be read: " + "; ".join(failed)[:400]
        return out

    async def gdelt_articles(self, run: Pass) -> list[Article]:
        """Funding articles from GDELT: the window in one query each (nightly, within the shared daily query cap),
        or week by week for the backlog. GDELT switched off, paused or rate limiting means none."""
        usable, _ = health.source_status("gdelt")
        if not usable:
            self.ctx.add(f"{NAME}.gdelt_skipped")
            return []
        now = datetime.now(UTC)
        windows: list[tuple[datetime, datetime] | None] = [None]
        if run.backlog:
            windows = []
            end = now
            while end > run.since(now):
                start = max(end - GDELT_WEEK, run.since(now))
                windows.append((start, end))
                end = start
        out: list[Article] = []
        async with GdeltAdapter(self.ctx, transport=self._transport) as gdelt:
            for query in GDELT_QUERIES:
                for window in windows:
                    if run.time_up() or gdelt.rate_limited:
                        return out
                    if not run.backlog and gdelt.queries_left() <= 0:
                        self.ctx.add(f"{NAME}.gdelt_cap_reached")
                        return out
                    try:
                        if window is None:
                            found = await gdelt.search(query, f"{run.days}d")
                        else:
                            found = await gdelt.search(
                                query, start=window[0], end=window[1], max_records=GDELT_BACKLOG_RECORDS
                            )
                    except SourceBlocked as err:  # GDELT itself refused us: pause GDELT, not the feeds
                        gdelt.health_blocked(err)
                        self.ctx.add(f"{NAME}.gdelt_blocked")
                        return out
                    self.ctx.add(f"{NAME}.gdelt_articles", len(found))
                    out += found
        return out

    async def fill_text(self, item: StartupItem) -> None:
        """Add the article's own text when the feed carried only a line or two (GDELT items carry none). A page
        that is blocked, disallowed or unreadable leaves the feed text as it is."""
        if len(item.text) >= MIN_FEED_TEXT:
            return
        try:
            res = await self.pages.get(item.url, raise_on_block=False, max_bytes=3_000_000)
        except (SourceBlocked, NeverFetch):
            self.ctx.add(f"{NAME}.article_blocked")
            return
        if not res.ok or "html" not in (res.content_type or "").lower():
            self.ctx.add(f"{NAME}.article_{res.state}")
            return
        body = article_text(res.text, res.final_url, ARTICLE_CHARS).strip()
        if not body:
            return
        if item.text and item.text[:80] not in body:
            item.text = f"{item.text}\n{body}"[:TEXT_CHARS]
        else:
            item.text = body[:TEXT_CHARS]
        self.ctx.add(f"{NAME}.articles_read")

    # ---- choosing what to judge --------------------------------------------------------------------------------
    def candidates(
        self,
        feed_items: Sequence[tuple[Feed, FeedItem]],
        articles: Sequence[Article],
        run: Pass,
        *,
        max_raise_usd: float,
        now: datetime | None = None,
    ) -> list[StartupItem]:
        """Items worth one AI call, best first: in the window, not judged before, not a repeat of a story seen in
        this run, and past the code filter. Feed items come before GDELT items."""
        now = now or datetime.now(UTC)
        since = run.since(now)
        pool: list[tuple[tuple[int, float], StartupItem]] = []
        for feed, fi in feed_items:
            if fi.published is not None and fi.published < since:
                self.ctx.add(f"{NAME}.outside_window")
                continue
            text = fi.text(TEXT_CHARS)
            why = prefilter(fi.title, text, max_raise_usd=max_raise_usd)
            if why:
                self.ctx.add(f"{NAME}.{why}")
                continue
            item = StartupItem(
                source=NAME,
                key=fi.key,
                url=fi.link,
                title=fi.title,
                text=text,
                published=fi.published,
                links=fi.links,
                feed=feed.key,
            )
            pool.append(((feed.rank, -(fi.published or now).timestamp()), item))
        for art in articles:
            if art.seen is not None and art.seen < since:
                self.ctx.add(f"{NAME}.outside_window")
                continue
            why = prefilter(art.title, "", max_raise_usd=max_raise_usd)
            if why:
                self.ctx.add(f"{NAME}.{why}")
                continue
            item = StartupItem(
                source=NAME,
                key=canonical_url(art.url),
                url=art.url,
                title=clean_text(art.title, 400),
                text="",
                published=art.seen,
                feed="gdelt",
                details={"source": "GDELT", "domain": art.domain},
            )
            pool.append(((GDELT_RANK, -(art.seen or now).timestamp()), item))
        pool.sort(key=lambda pair: pair[0])
        titles = {item.key: title_key(item.title) for _, item in pool}
        fresh = unseen(NAME, [k for _, item in pool for k in (item.key, titles[item.key]) if k])
        out: list[StartupItem] = []
        taken: set[str] = set()
        for _, item in pool:
            tkey = titles[item.key]
            if item.key not in fresh or (tkey is not None and tkey not in fresh):
                self.ctx.add(f"{NAME}.seen_before")
                continue
            if item.key in taken or (tkey is not None and tkey in taken):
                self.ctx.add(f"{NAME}.repeat")
                continue
            taken.update(k for k in (item.key, tkey) if k)
            out.append(item)
        return out

    # ---- the run -----------------------------------------------------------------------------------------------
    async def collect(self, segments: Mapping[str, Segment], run: Pass) -> list[Signal]:
        """Funding, launch and news signals from the feeds and GDELT, routed to the startup segments."""
        if not any(s.domain == "firms" for s in segments.values()):
            self.ctx.add(f"{NAME}.no_startup_segments")
            return []
        if run.cap <= 0:
            self.ctx.add(f"{NAME}.daily_cap_reached")
            return []
        feed_items = await self.read_feeds(run)
        articles = await self.gdelt_articles(run)
        judge = ItemJudge(self.ctx, segments)
        items = self.candidates(feed_items, articles, run, max_raise_usd=judge.max_raise_usd)[: run.cap]
        self.ctx.add(f"{NAME}.candidates", len(items))
        await bounded(FETCH_CONCURRENCY, [_filler(self, item) for item in items])
        ready = [item for item in items if item.text]
        if len(ready) < len(items):
            self.ctx.add(f"{NAME}.no_text", len(items) - len(ready))
        return judge_items(self.ctx, judge, ready, run)


def _filler(adapter: FundingRssAdapter, item: StartupItem) -> Callable[[], Awaitable[None]]:
    async def fill() -> None:
        await adapter.fill_text(item)

    return fill


async def collect(
    ctx: SourceContext,
    segments: Mapping[str, Segment],
    sink: Sink,
    run: Pass,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """One pass of the source into the sink, behind its kill switch."""
    async with FundingRssAdapter(ctx, transport=transport) as adapter:
        to_sink(await guarded(adapter, lambda: adapter.collect(segments, run)), segments, sink)


async def watch(
    ctx: SourceContext,
    segments: dict[str, Segment],
    sink: Sink,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """The nightly pass: the last few days of the feeds and GDELT, within the daily item allowance."""
    run = nightly_pass(ctx, NAME, SETTING, DEFAULT_PER_DAY, days=NIGHT_DAYS)
    await collect(ctx, segments, sink, run, transport=transport)


async def backlog(
    ctx: SourceContext,
    segments: dict[str, Segment],
    sink: Sink,
    run: Pass,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """The backlog pass (`pipeline/backlog.py`): older feed pages, and GDELT week by week."""
    await collect(ctx, segments, sink, run, transport=transport)
