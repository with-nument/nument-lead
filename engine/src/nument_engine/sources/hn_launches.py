"""Hacker News launches (15 Nov 2026): "Show HN" and "Launch HN" posts, read with the official Algolia API
(`hn.algolia.com/api/v1`, which has no robots.txt; job_feeds reads the same API).

A post counts only when it has a company website: the post's own link, unless it points at GitHub, an app
store, Hacker News or another host that is never a company's own site (`rss.NOT_COMPANY_SITES`); a text post (most
Launch HN posts) uses the first company site linked in its text. About 100 Show HN posts arrive a day and around
40 percent link to GitHub; most of the rest are side projects, which the classifier drops (`is_startup`).

For each post left, the homepage is read politely (its title, opening lines and footer) so the classifier sees
what the company does and where it is; quotes still come from the post itself. One `classify_startup_item` call
per post (g_lite), at most `hn_launches.items_per_day` a day, Launch HN posts first; `rss.ItemJudge` applies the size
gate and the country rules. Signal `launch`, dated when the post was made, with the post as the evidence and
`details` hn_id, kind (show_hn or launch_hn), points, comments and the YC batch a Launch HN title names. A launch
is news for 30 days, so no pass looks further back than that.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..http import PoliteClient, SourceBlocked
from ..normalize import clean_text, homepage
from ..segments import Segment
from .base import WINDOW_DAYS, Signal, SourceAdapter, SourceContext
from .rss import (
    ItemJudge,
    Pass,
    Sink,
    StartupItem,
    bounded,
    guarded,
    html_to_text,
    is_company_site,
    judge_items,
    links_in_html,
    nightly_pass,
    root_of,
    site_excerpt,
    title_key,
    to_sink,
    unseen,
)

NAME = "hn_launches"
SETTING = "hn_launches.items_per_day"
DEFAULT_PER_DAY = 60
NIGHT_DAYS = 3
API = "https://hn.algolia.com/api/v1/search_by_date"
API_HOST = "hn.algolia.com"
ITEM_URL = "https://news.ycombinator.com/item?id={id}"
HN_BASE = "https://news.ycombinator.com/"
TAGS = "(show_hn,launch_hn)"
HITS_PER_PAGE = 1000
WINDOW = timedelta(days=3)  # one query per 3 days (about 300 posts) keeps every answer to one page
MAX_PAGES = 5
FETCH_CONCURRENCY = 4
LAUNCH_DAYS = WINDOW_DAYS["launch"] or 30
_BATCH = re.compile(r"\(YC\s+([A-Z]\d{2})\)")


def post_kind(hit: Mapping[str, Any]) -> str:
    tags = hit.get("_tags") or []
    title = str(hit.get("title") or "")
    return "launch_hn" if "launch_hn" in tags or title.lower().startswith("launch hn") else "show_hn"


def post_time(hit: Mapping[str, Any]) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(hit["created_at_i"]), UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


def website_of(hit: Mapping[str, Any]) -> tuple[str | None, str]:
    """(link, where it came from): the post's own link when it is a company site, else the first company site
    linked in the post's text."""
    url = str(hit.get("url") or "")
    if is_company_site(url):
        return url, "post_link"
    link = next((u for u in links_in_html(str(hit.get("story_text") or ""), HN_BASE) if is_company_site(u)), None)
    return (link, "post_text") if link else (None, "")


def item_from(hit: Mapping[str, Any]) -> StartupItem | None:
    """A post as a startup item, or None when it has no id, no title or no company website."""
    object_id = str(hit.get("objectID") or "").strip()
    title = clean_text(str(hit.get("title") or ""), 300)
    if not object_id.isdigit() or not title:
        return None
    link, site_from = website_of(hit)
    if link is None:
        return None
    kind = post_kind(hit)
    details: dict[str, Any] = {"hn_id": int(object_id), "kind": kind, "website_from": site_from}
    for field, key in (("points", "points"), ("num_comments", "comments")):
        value = hit.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            details[key] = value
    batch = _BATCH.search(title)
    if kind == "launch_hn" and batch:
        details["batch"] = batch.group(1)
    raw_text = str(hit.get("story_text") or "")
    return StartupItem(
        source=NAME,
        key=f"hn:{object_id}",
        url=ITEM_URL.format(id=object_id),
        title=title,
        text=html_to_text(raw_text),
        published=post_time(hit),
        links=links_in_html(raw_text, HN_BASE),
        website=homepage(link),
        site_url=root_of(link),
        signal_type="launch",
        details=details,
    )


class HnLaunchesAdapter(SourceAdapter):
    name = NAME
    policy = "official_api"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sites: PoliteClient | None = None
        self.failure: str | None = None

    @property
    def sites(self) -> PoliteClient:
        """A separate client for the startups' homepages (public pages: robots.txt and a 2 second gap)."""
        if self._sites is None:
            self._sites = PoliteClient(f"{NAME}_sites", policy="public", transport=self._transport)
        return self._sites

    async def aclose(self) -> None:
        if self._sites is not None:
            await self._sites.aclose()
            self._sites = None
        await super().aclose()

    @staticmethod
    def since(run: Pass, now: datetime) -> datetime:
        """The start of the window: the pass's days, but never more than a launch stays news."""
        return max(run.since(now), now - timedelta(days=LAUNCH_DAYS))

    async def posts(self, run: Pass, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Show HN and Launch HN posts of the window, newest first, three days per query. A block from the API
        pauses the source (`SourceBlocked`); other errors end that query."""
        now = now or datetime.now(UTC)
        since = self.since(run, now)
        hits: list[dict[str, Any]] = []
        asked = answered = 0
        end = now
        while end > since and not run.time_up():
            start = max(end - WINDOW, since)
            for page in range(MAX_PAGES):
                asked += 1
                window = f"created_at_i>{int(start.timestamp())},created_at_i<={int(end.timestamp())}"
                res = await self.http.get(
                    API,
                    params={"tags": TAGS, "numericFilters": window, "hitsPerPage": HITS_PER_PAGE, "page": page},
                    check_robots=False,
                    raise_on_block=False,
                    retries=1,
                )
                if res.state == "blocked":
                    raise SourceBlocked(NAME, API_HOST, res.reason, res.status)
                if res.status != 200:
                    self.ctx.add(f"{NAME}.api_{res.status or res.state}")
                    break
                try:
                    data = res.json()
                except ValueError:
                    self.ctx.add(f"{NAME}.bad_json")
                    break
                answered += 1
                found = [h for h in data.get("hits") or [] if isinstance(h, dict)]
                hits += found
                if not found or page + 1 >= int(data.get("nbPages") or 0):
                    break
            end = start
        if asked and not answered:
            self.failure = "the Algolia API did not answer"
        self.ctx.add(f"{NAME}.posts", len(hits))
        return hits

    def candidates(
        self, hits: Sequence[Mapping[str, Any]], run: Pass, *, now: datetime | None = None
    ) -> list[StartupItem]:
        """Posts worth one AI call: in the window, with a company website, not judged before (by id or title),
        Launch HN first, then the most upvoted, then the newest."""
        since = self.since(run, now or datetime.now(UTC))
        items: dict[str, StartupItem] = {}
        for hit in hits:
            item = item_from(hit)
            if item is None:
                self.ctx.add(f"{NAME}.no_website")
                continue
            if item.published is not None and item.published < since:
                self.ctx.add(f"{NAME}.outside_window")
                continue
            items.setdefault(item.key, item)
        titles = {k: title_key(i.title) for k, i in items.items()}
        fresh = unseen(NAME, [k for key in items for k in (key, titles[key]) if k])
        out: list[StartupItem] = []
        taken: set[str] = set()
        for key, item in items.items():
            tkey = titles[key]
            if key not in fresh or (tkey is not None and tkey not in fresh):
                self.ctx.add(f"{NAME}.seen_before")
                continue
            if tkey is not None and tkey in taken:
                self.ctx.add(f"{NAME}.repeat")  # the same post submitted twice
                continue
            taken.update(k for k in (key, tkey) if k)
            out.append(item)
        out.sort(
            key=lambda i: (
                i.details.get("kind") != "launch_hn",
                -int(i.details.get("points") or 0),
                -(i.published.timestamp() if i.published else 0.0),
            )
        )
        return out

    async def read_site(self, item: StartupItem) -> None:
        """The homepage excerpt for the classifier (nothing when the site cannot be read politely)."""
        page = item.site_url or item.website
        if not page:
            return
        item.context = await site_excerpt(self.sites, page)
        item.context_url = page if item.context else None
        self.ctx.add(f"{NAME}.sites_read" if item.context else f"{NAME}.sites_unread")

    async def collect(self, segments: Mapping[str, Segment], run: Pass) -> list[Signal]:
        """Launch signals from Show HN and Launch HN, routed to the startup segments."""
        if not any(s.domain == "firms" for s in segments.values()):
            self.ctx.add(f"{NAME}.no_startup_segments")
            return []
        if run.cap <= 0:
            self.ctx.add(f"{NAME}.daily_cap_reached")
            return []
        items = self.candidates(await self.posts(run), run)[: run.cap]
        self.ctx.add(f"{NAME}.candidates", len(items))
        await bounded(FETCH_CONCURRENCY, [_reader(self, item) for item in items])
        return judge_items(self.ctx, ItemJudge(self.ctx, segments), items, run)


def _reader(adapter: HnLaunchesAdapter, item: StartupItem) -> Callable[[], Awaitable[None]]:
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
    async with HnLaunchesAdapter(ctx, transport=transport) as adapter:
        to_sink(await guarded(adapter, lambda: adapter.collect(segments, run)), segments, sink)


async def watch(
    ctx: SourceContext,
    segments: dict[str, Segment],
    sink: Sink,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """The nightly pass: the last few days of posts, within the daily item allowance."""
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
    """The backlog pass (`pipeline/backlog.py`): posts of the last 30 days."""
    await collect(ctx, segments, sink, run, transport=transport)
