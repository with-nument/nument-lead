"""BetaList (15 Nov 2026): startups that list themselves before or at launch, from BetaList's public Atom feed.

Checked 16 Nov 2026: betalist.com's robots.txt allows every path, and its terms of use (betalist.com/terms) say
nothing against reading the site or its feed by machine. The homepage advertises a FeedBurner copy of the feed;
we read the original, `betalist.com/startups/feed_original` (its own self link). About 15 to 20 startups a day,
the last 25 in the feed; the feed has no older pages, so the backlog reads the same entries.

Each entry is a startup's BetaList page with its one-line pitch and description. Its website sits behind the
page's "Visit website" link (`/startups/<slug>/visit`, a redirect): only that redirect's Location header is read,
and the homepage itself is then read politely (title, opening lines and footer) for the classifier. Entries
without a website are skipped. The rest are judged newest first, at most `betalist.items_per_day` a day (one
`classify_startup_item` call each); `rss.ItemJudge` applies the size gate and the country rules. Signal `launch`,
dated when BetaList featured the startup, with the BetaList page as the evidence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..http import NeverFetch, PoliteClient, SourceBlocked
from ..normalize import homepage
from ..segments import Segment
from .base import WINDOW_DAYS, Signal, SourceAdapter, SourceContext
from .rss import (
    FeedItem,
    ItemJudge,
    Pass,
    Sink,
    StartupItem,
    bounded,
    fetch_feed,
    guarded,
    is_company_site,
    judge_items,
    nightly_pass,
    root_of,
    site_excerpt,
    title_key,
    to_sink,
    unseen,
)

NAME = "betalist"
SETTING = "betalist.items_per_day"
DEFAULT_PER_DAY = 40
NIGHT_DAYS = 3
FEED_URL = "https://betalist.com/startups/feed_original"
HOST = "betalist.com"
FETCH_CONCURRENCY = 4
MAX_VISIT_MISSES = 3  # visit links in a row without a website: stop for this run
LAUNCH_DAYS = WINDOW_DAYS["launch"] or 30


def slug_of(link: str) -> str | None:
    """`wfh-alert` for `https://betalist.com/startups/wfh-alert`, None for any other page."""
    parts = urlsplit(link)
    path = [p for p in parts.path.split("/") if p]
    if (parts.hostname or "").removeprefix("www.") != HOST or len(path) != 2 or path[0] != "startups":
        return None
    return path[1]


def item_from(entry: FeedItem) -> StartupItem | None:
    slug = slug_of(entry.link)
    if slug is None or not entry.title:
        return None
    return StartupItem(
        source=NAME,
        key=f"betalist:{slug}",
        url=entry.link,
        title=entry.title,
        text=entry.text(),
        published=entry.published,
        links=entry.links,
        signal_type="launch",
        details={"betalist_slug": slug},
    )


class BetaListAdapter(SourceAdapter):
    name = NAME
    policy = "public"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sites: PoliteClient | None = None
        self.failure: str | None = None

    @property
    def sites(self) -> PoliteClient:
        """A separate client for the startups' homepages."""
        if self._sites is None:
            self._sites = PoliteClient(f"{NAME}_sites", policy="public", transport=self._transport)
        return self._sites

    async def aclose(self) -> None:
        if self._sites is not None:
            await self._sites.aclose()
            self._sites = None
        await super().aclose()

    async def entries(self) -> list[FeedItem]:
        """The feed's entries. A block pauses the source; any other failure is an error for this run."""
        page = await fetch_feed(self.http, FEED_URL, NAME)
        self.ctx.add(f"{NAME}.feed_{page.state}")
        if page.state == "blocked":
            raise SourceBlocked(NAME, HOST, page.reason, page.status)
        if not page.ok:
            self.failure = f"the BetaList feed could not be read ({page.state}: {page.reason})"
            return []
        return page.items

    def candidates(self, entries: list[FeedItem], run: Pass, *, now: datetime | None = None) -> list[StartupItem]:
        """Entries worth one AI call: in the window (never older than a launch stays news), not judged before,
        newest first."""
        now = now or datetime.now(UTC)
        since = max(run.since(now), now - timedelta(days=LAUNCH_DAYS))
        items: dict[str, StartupItem] = {}
        for entry in entries:
            item = item_from(entry)
            if item is None:
                self.ctx.add(f"{NAME}.not_a_startup_page")
                continue
            if item.published is not None and item.published < since:
                self.ctx.add(f"{NAME}.outside_window")
                continue
            items.setdefault(item.key, item)
        titles = {k: title_key(i.title) for k, i in items.items()}
        fresh = unseen(NAME, [k for key in items for k in (key, titles[key]) if k])
        out = []
        for key, item in items.items():
            tkey = titles[key]
            if key not in fresh or (tkey is not None and tkey not in fresh):
                self.ctx.add(f"{NAME}.seen_before")
                continue
            out.append(item)
        out.sort(key=lambda i: -(i.published.timestamp() if i.published else now.timestamp()))
        return out

    async def find_website(self, item: StartupItem) -> None:
        """The startup's website from its visit link: the redirect's Location header only (robots.txt checked
        first; the target is never fetched through BetaList)."""
        visit = f"https://{HOST}/startups/{item.details['betalist_slug']}/visit"
        if not await self.http.robots_allows(visit):
            self.ctx.add(f"{NAME}.visit_disallowed")
            return
        try:
            target = await self.http.location(visit)
        except NeverFetch:
            target = None
        if not target or not is_company_site(target):
            self.ctx.add(f"{NAME}.no_website")
            return
        item.website = homepage(target)
        item.site_url = root_of(target)
        item.details["website_from"] = "betalist_visit"

    async def read_site(self, item: StartupItem) -> None:
        if not item.site_url:
            return
        item.context = await site_excerpt(self.sites, item.site_url)
        item.context_url = item.site_url if item.context else None
        self.ctx.add(f"{NAME}.sites_read" if item.context else f"{NAME}.sites_unread")

    async def collect(self, segments: Mapping[str, Segment], run: Pass) -> list[Signal]:
        """Launch signals from BetaList, routed to the startup segments."""
        if not any(s.domain == "firms" for s in segments.values()):
            self.ctx.add(f"{NAME}.no_startup_segments")
            return []
        if run.cap <= 0:
            self.ctx.add(f"{NAME}.daily_cap_reached")
            return []
        items = self.candidates(await self.entries(), run)[: run.cap]
        self.ctx.add(f"{NAME}.candidates", len(items))
        misses = 0
        for item in items:  # one host: the client spaces these requests
            if run.time_up():
                break
            if misses >= MAX_VISIT_MISSES:  # the visit links stopped answering: do not keep asking
                self.ctx.add(f"{NAME}.visit_links_failing")
                break
            await self.find_website(item)
            misses = 0 if item.website else misses + 1
        ready = [i for i in items if i.website]
        await bounded(FETCH_CONCURRENCY, [_reader(self, item) for item in ready])
        return judge_items(self.ctx, ItemJudge(self.ctx, segments), ready, run)


def _reader(adapter: BetaListAdapter, item: StartupItem) -> Callable[[], Awaitable[None]]:
    async def read() -> None:
        await adapter.read_site(item)

    return read


async def collect(
    ctx: SourceContext,
    segments: Mapping[str, Segment],
    sink: Sink,
    run: Pass,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """One pass of the source into the sink, behind its kill switch."""
    async with BetaListAdapter(ctx, transport=transport) as adapter:
        to_sink(await guarded(adapter, lambda: adapter.collect(segments, run)), segments, sink)


async def watch(
    ctx: SourceContext,
    segments: dict[str, Segment],
    sink: Sink,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """The nightly pass: the newest entries, within the daily item allowance."""
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
    """The backlog pass (`pipeline/backlog.py`): the feed holds only its newest entries, so this is one read."""
    await collect(ctx, segments, sink, run, transport=transport)
