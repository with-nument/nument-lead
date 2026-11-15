"""Feeds of startup items (15 Nov 2026): RSS and Atom feeds fetched politely, and the one place where an item
about a startup (a funding story, a Show HN post, a BetaList entry) becomes a routed signal.

Fetching (`fetch_feed`): every feed goes through `PoliteClient` (robots.txt, spacing, redirects followed and
checked hop by hop, block detection). feedparser only ever parses the bytes we fetched, so it never opens a
connection or a file itself. A feed that is gone, blocked, disallowed or not a feed at all comes back as a state
(`FeedPage.state`), never as an exception: one dead feed never stops the others. `fetch_feed_back` follows a
WordPress feed's older pages (`?paged=2`, ...) for the backlog, where robots.txt allows it.

Dates: feedparser reads an item's published (or updated) time and converts it to UTC. An item without a date
keeps None, and a date more than a day ahead of now counts as unknown (a broken feed clock must not keep a signal
alive for longer than its window).

Judging (`ItemJudge`): one `classify_startup_item` call per item (g_lite) names the startup and reads the event,
round, amount, team size, country, founders and investors. Code then checks every answer against the item
itself: the quote must be a verbatim part of the item, founder and investor names must be written in it, the
website must appear in it (or come from the source), the size gate (`startup.startup_gate`) drops clear
outsiders, and the country rules (`startup.startup_segment`) pick the segment: only countries we write to, never
one where cold email needs prior consent. A country the item does not state may come from the website's country
domain (`.co.uk`, `.in`, ...; marked `country_from: website_domain`); otherwise the item is dropped. Nothing is
guessed.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import html as htmllib
import io
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import tldextract

from .. import db
from ..http import NeverFetch, PoliteClient, SourceBlocked, host_blocked, host_of
from ..logging import get_logger
from ..normalize import canonical_url, city_for_text, clean_text, homepage, web_domain
from ..research.text import title_of, visible_lines
from ..segments import Segment, load_yaml_config
from . import health, startup
from .base import QUOTE_MAX, WINDOW_DAYS, Signal, SourceAdapter, SourceContext, field_of
from .jobs import mask_contacts

log = get_logger()

# ---------------------------------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------------------------------

FEED_MAX_BYTES = 5_000_000  # BetaKit's full-text feed is about 1.6 MB for 150 items
FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5"
FUTURE_SLACK = timedelta(days=1)
MAX_FEED_PAGES = 60  # backlog: older pages of one feed, at most
_TRACKING = ("utm_", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "_ga", "ref", "igshid")
_BLOCK_TAG = re.compile(r"<\s*/?\s*(?:br|p|div|li|ul|ol|h[1-6]|tr|blockquote|section|article)\b[^>]*>", re.I)
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)


@dataclass
class FeedItem:
    """One item of a feed, as plain text. `link` is the item's own page (tracking parameters removed)."""

    feed: str
    title: str
    link: str
    published: datetime | None
    summary: str = ""
    content: str = ""  # the full text when the feed carries it, else ""
    links: list[str] = field(default_factory=list)  # absolute links written in the description and content

    @property
    def key(self) -> str:
        """Stable id for dedupe: the canonical form of the item's link."""
        return canonical_url(self.link)

    def text(self, limit: int | None = None) -> str:
        """The item's own words: the full content when the feed has it (the description is usually its first
        paragraph), else the description."""
        summary, content = self.summary.strip(), self.content.strip()
        if content and summary and summary[:80].rstrip(".\u2026 ") not in content:
            body = f"{summary}\n{content}"
        else:
            body = content or summary
        return body[:limit] if limit else body


@dataclass
class FeedPage:
    """One fetched feed page: its state (ok, blocked, robots_skip, broken, unknown, not_feed, bad_xml,
    never_fetch) and the items read from it."""

    url: str
    state: str
    reason: str = ""
    status: int | None = None
    items: list[FeedItem] = field(default_factory=list)
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def html_to_text(raw: str | None) -> str:
    """Plain text of an HTML fragment: one line per block, entities decoded, whitespace collapsed."""
    text = _SCRIPT_STYLE.sub(" ", raw or "")
    text = _TAG.sub(" ", _BLOCK_TAG.sub("\n", text))
    text = htmllib.unescape(text).replace("\u00a0", " ")
    return "\n".join(line for line in (clean_text(part) for part in text.split("\n")) if line)


def links_in_html(raw: str | None, base: str = "") -> list[str]:
    """Absolute http(s) links of an HTML fragment, in order, without duplicates."""
    out: list[str] = []
    for href in _HREF.findall(raw or ""):
        url = urljoin(base, htmllib.unescape(href.strip()))
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
    return out


def without_tracking(url: str) -> str:
    """The URL without analytics parameters (utm_*, fbclid, ...). Host and path are kept as published."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith(_TRACKING)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def entry_date(entry: Mapping[str, Any], now: datetime) -> datetime | None:
    """The item's publication time in UTC: published, else updated. None when missing, unreadable or more than a
    day in the future; a date a little ahead (a feed's clock or time zone) is clamped to now."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key) if key in entry else None  # `in` first: feedparser warns on a missing updated date
        if not value:
            continue
        try:
            when = datetime.fromtimestamp(calendar.timegm(value), UTC)
        except (OverflowError, OSError, TypeError, ValueError):
            continue
        if when > now + FUTURE_SLACK:
            return None
        return min(when, now)
    return None


def _entry_link(entry: Mapping[str, Any], base: str) -> str | None:
    candidates = [entry.get("feedburner_origlink"), entry.get("link")]
    if entry.get("guidislink") or str(entry.get("id") or "").startswith(("http://", "https://")):
        candidates.append(entry.get("id"))
    for raw in candidates:
        if not raw:
            continue
        url = urljoin(base, str(raw).strip())
        if url.startswith(("http://", "https://")) and urlsplit(url).hostname:
            return without_tracking(url)
    return None


def parse_feed(content: bytes, url: str, feed: str = "", *, now: datetime | None = None) -> tuple[list[FeedItem], str]:
    """(items, state) from the raw bytes of a feed. state: `ok`, `not_feed` (the body is not RSS or Atom, for
    example a homepage served instead) or `bad_xml` (a broken feed with no readable item). Items that could still
    be read from a broken feed are kept; items without a link are skipped."""
    now = now or datetime.now(UTC)
    parsed = feedparser.parse(io.BytesIO(content), response_headers={"content-location": url})
    entries = list(parsed.get("entries") or [])
    if not entries and not parsed.get("version"):
        return [], "not_feed"
    items: list[FeedItem] = []
    for entry in entries:
        link = _entry_link(entry, url)
        if link is None:
            continue
        summary_html = str(entry.get("summary") or "")
        content_html = "\n".join(str(c.get("value") or "") for c in entry.get("content") or [] if isinstance(c, dict))
        items.append(
            FeedItem(
                feed=feed,
                title=clean_text(html_to_text(str(entry.get("title") or "")), 400),
                link=link,
                published=entry_date(entry, now),
                summary=html_to_text(summary_html),
                content=html_to_text(content_html) if content_html.strip() else "",
                links=[without_tracking(u) for u in links_in_html(f"{summary_html}\n{content_html}", link)],
            )
        )
    if not items and parsed.get("bozo"):
        return [], "bad_xml"
    return items, "ok"


async def fetch_feed(
    http: PoliteClient, url: str, feed: str = "", *, now: datetime | None = None, retries: int = 1
) -> FeedPage:
    """Fetch and parse one feed page. Never raises for network trouble: the state says what happened."""
    try:
        res = await http.get(
            url, headers={"Accept": FEED_ACCEPT}, raise_on_block=False, max_bytes=FEED_MAX_BYTES, retries=retries
        )
    except SourceBlocked as err:  # the host blocked us earlier in this run
        return FeedPage(url, "blocked", err.reason, err.status)
    except NeverFetch:
        return FeedPage(url, "never_fetch", f"never fetched: {host_of(url)}")
    if res.state != "ok":
        return FeedPage(url, res.state, res.reason, res.status)
    if res.status != 200:
        return FeedPage(url, "broken", f"http {res.status}", res.status)
    items, state = parse_feed(res.content, res.final_url or url, feed, now=now)
    return FeedPage(url, state, "" if state == "ok" else state, res.status, items, res.truncated)


def page_url(url: str, page: int) -> str:
    """Page `page` of a WordPress feed (`?paged=N`); page 1 is the feed itself."""
    if page <= 1:
        return url
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "paged"]
    query.append(("paged", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


async def fetch_feed_back(
    http: PoliteClient,
    url: str,
    feed: str,
    *,
    since: datetime,
    max_pages: int = MAX_FEED_PAGES,
    now: datetime | None = None,
    time_up: Callable[[], bool] | None = None,
) -> tuple[list[FeedItem], list[FeedPage]]:
    """Items of a feed back to `since`, following its older pages while there are any. Stops at the first page
    that is not ok (robots.txt may disallow query strings), brings nothing new (the site ignores `paged`) or
    reaches past `since`."""
    items: list[FeedItem] = []
    pages: list[FeedPage] = []
    seen: set[str] = set()
    for n in range(1, max_pages + 1):
        if n > 1 and time_up is not None and time_up():
            break
        page = await fetch_feed(http, page_url(url, n), feed, now=now)
        pages.append(page)
        if not page.ok:
            break
        fresh = [i for i in page.items if i.key not in seen]
        if not fresh:
            break
        seen.update(i.key for i in fresh)
        items += fresh
        dated = [i.published for i in fresh if i.published is not None]
        if not dated or min(dated) < since:
            break
    return items, pages


# ---------------------------------------------------------------------------------------------------
# Websites and countries
# ---------------------------------------------------------------------------------------------------

# Hosts an item links to that are never a startup's own website: code hosts, app stores, video and blog
# platforms, launch sites, shared hosting for side projects, documents and link shorteners.
NOT_COMPANY_SITES: tuple[str, ...] = (
    "github.com", "github.io", "githubusercontent.com", "gitlab.com", "gitlab.io", "bitbucket.org",
    "codeberg.org", "sourceforge.net", "apps.apple.com", "itunes.apple.com", "play.google.com",
    "chromewebstore.google.com", "chrome.google.com", "addons.mozilla.org", "apps.microsoft.com",
    "ycombinator.com", "betalist.com", "producthunt.com", "youtube.com", "youtu.be", "vimeo.com", "loom.com",
    "medium.com", "substack.com", "dev.to", "hashnode.dev", "npmjs.com", "pypi.org", "crates.io",
    "huggingface.co", "arxiv.org", "kaggle.com", "itch.io", "steampowered.com", "docs.google.com",
    "drive.google.com", "notion.site", "notion.so", "kickstarter.com", "indiegogo.com", "wikipedia.org",
    "archive.org", "discord.gg", "discord.com", "linktr.ee", "bit.ly", "vercel.app", "netlify.app", "pages.dev",
    "herokuapp.com", "replit.app", "repl.co", "streamlit.app", "glitch.me", "fly.dev", "onrender.com",
    "railway.app", "surge.sh", "web.app", "firebaseapp.com", "crunchbase.com", "google.com",
)  # fmt: skip

COUNTRY_NAMES: dict[str, str] = {
    "united states": "us", "united states of america": "us", "usa": "us", "u.s.": "us", "u.s.a.": "us",
    "united kingdom": "gb", "uk": "gb", "u.k.": "gb", "great britain": "gb", "britain": "gb", "england": "gb",
    "scotland": "gb", "wales": "gb", "northern ireland": "gb", "india": "in", "united arab emirates": "ae",
    "uae": "ae", "ireland": "ie", "netherlands": "nl", "the netherlands": "nl", "holland": "nl", "france": "fr",
    "sweden": "se", "finland": "fi", "belgium": "be", "portugal": "pt", "australia": "au", "new zealand": "nz",
    "canada": "ca", "singapore": "sg", "brazil": "br", "mexico": "mx", "philippines": "ph",
    "the philippines": "ph", "malaysia": "my", "indonesia": "id", "germany": "de", "austria": "at",
    "denmark": "dk", "italy": "it", "spain": "es", "poland": "pl", "israel": "il", "south africa": "za",
    "vietnam": "vn", "viet nam": "vn", "saudi arabia": "sa", "qatar": "qa", "switzerland": "ch", "norway": "no",
    "nigeria": "ng", "kenya": "ke", "egypt": "eg", "ghana": "gh", "colombia": "co", "argentina": "ar",
    "chile": "cl", "peru": "pe", "japan": "jp", "south korea": "kr", "korea": "kr", "china": "cn",
    "hong kong": "hk", "taiwan": "tw", "thailand": "th", "pakistan": "pk", "bangladesh": "bd", "sri lanka": "lk",
    "turkey": "tr", "turkiye": "tr", "estonia": "ee", "lithuania": "lt", "latvia": "lv", "czech republic": "cz",
    "czechia": "cz", "greece": "gr", "romania": "ro", "ukraine": "ua", "hungary": "hu", "luxembourg": "lu",
    "cyprus": "cy", "malta": "mt", "iceland": "is", "uruguay": "uy", "rwanda": "rw", "morocco": "ma",
    "tunisia": "tn", "uganda": "ug", "tanzania": "tz", "ethiopia": "et", "senegal": "sn", "jordan": "jo",
    "lebanon": "lb", "bahrain": "bh", "oman": "om", "kuwait": "kw", "nepal": "np",
}  # fmt: skip
# Country-code domains that are used worldwide as generic names (.io, .ai, .co, ...): they say nothing about where
# a company is.
GENERIC_CCTLDS = frozenset(
    {"io", "ai", "co", "me", "tv", "fm", "gg", "ly", "so", "sh", "to", "cc", "ws", "la", "is", "vc", "ac", "im",
     "st", "gl", "ms", "nu", "tk", "ml", "ga", "cf", "gq", "sx", "ps", "cx", "bz", "ag", "lc", "mu", "re"}
)  # fmt: skip
_TLDX = tldextract.TLDExtract(suffix_list_urls=())  # offline: the bundled public suffix list


def iso_country(value: Any) -> str | None:
    """ISO 3166-1 alpha-2 (lower case) from a code or an English country name; None when it is not one."""
    raw = clean_text(str(value or "")).lower().strip(" .,")
    if not raw:
        return None
    if re.fullmatch(r"[a-z]{2}", raw):
        return "gb" if raw == "uk" else raw
    return COUNTRY_NAMES.get(raw)


def country_from_domain(url_or_domain: str | None) -> str | None:
    """The country of a country-code domain (`acme.co.uk` -> gb, `acme.in` -> in), None for .com, .io, .ai and
    the other domains used worldwide."""
    raw = (url_or_domain or "").strip()
    host = host_of(raw if "//" in raw else f"https://{raw}") if raw else ""
    if not host:
        return None
    last = _TLDX(host).suffix.rsplit(".", 1)[-1].lower()
    if len(last) != 2 or last in GENERIC_CCTLDS:
        return None
    return "gb" if last == "uk" else last


def is_company_site(url: str | None) -> bool:
    """True for a URL that can be a startup's own website (not a code host, store, video, social or portal)."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    if host_blocked(url) or web_domain(url) is None:
        return False
    host = host_of(url)
    return not any(host == h or host.endswith("." + h) for h in NOT_COMPANY_SITES)


def first_company_site(links: Iterable[str]) -> str | None:
    """The homepage of the first link that can be a company's own website."""
    for link in links:
        if is_company_site(link):
            return homepage(link)
    return None


@cache
def _country_rules() -> tuple[frozenset[str], frozenset[str]]:
    cfg = load_yaml_config("outreach")
    return (
        frozenset(str(c).lower() for c in cfg.get("allowed_countries", [])),
        frozenset(str(c).lower() for c in cfg.get("blocked_countries", [])),
    )


def route(country: str | None, segments: Mapping[str, Segment]) -> tuple[Segment | None, str]:
    """(segment, why) for a startup's country: `startup.startup_segment` with the reason when there is none
    (no_country, country_blocked: cold email needs consent there, country_not_allowed, segment_off)."""
    seg = startup.startup_segment(country, segments)
    if seg is not None:
        return seg, "ok"
    if not country:
        return None, "no_country"
    allowed, blocked = _country_rules()
    if country in blocked:
        return None, "country_blocked"
    if country not in allowed:
        return None, "country_not_allowed"
    return None, "segment_off"


async def site_excerpt(http: PoliteClient, url: str, *, head_chars: int = 1200, tail_chars: int = 500) -> str:
    """What a startup's homepage says about itself: its title, the first lines (what it does) and the last lines
    (the footer, where the company and its city are usually written). Empty when it cannot be read politely."""
    try:
        res = await http.get(url, raise_on_block=False, max_bytes=2_000_000)
    except (SourceBlocked, NeverFetch):
        return ""
    if not res.ok or "html" not in (res.content_type or "").lower() or not res.text:
        return ""
    lines = visible_lines(res.text)
    head = _fit(lines, head_chars)
    tail = _fit(lines[len(head) :][::-1], tail_chars)[::-1]
    title = title_of(res.text) or ""
    return "\n".join(part for part in (title, "\n".join(head), "\n".join(tail)) if part)


def _fit(lines: Sequence[str], limit: int) -> list[str]:
    """The leading lines that fit in `limit` characters."""
    out: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) > limit:
            break
        out.append(line)
        used += len(line) + 1
    return out


# ---------------------------------------------------------------------------------------------------
# Startup items: one AI call, then code checks every answer against the item
# ---------------------------------------------------------------------------------------------------

TASK = "classify_startup_item"
MIN_CONFIDENCE = 0.6
TEXT_CHARS = 3500
EVENT_TO_TYPE = {"funding": "funding", "launch": "launch", "hiring": "news", "ask": "news", "other": "news"}
# Round words of the classifier that `startup.normalize_round` does not know as written.
MODEL_ROUNDS = {"series_b_plus": "series_b"}
NOT_A_NAME = frozenset({"startup", "stealth", "stealth startup", "unknown", "n/a", "na", "none", "company"})
MAX_INVESTORS = 8
BACKLOG_BUDGET_PHASE = "low_priority_research"
_FOLD = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


@dataclass
class StartupItem:
    """One item that may be about a startup, ready for `classify_startup_item`.

    `text` is what the AI reads and what quotes, names and websites are checked against. `website` is a site the
    source itself gives (a Show HN post's link, a BetaList visit link); otherwise only a site the AI names and
    the item shows is kept. `signal_type` fixes the type (a launch post is a launch whatever else it says);
    None lets the event decide (funding news)."""

    source: str
    key: str  # source_records key and the signal's evidence key
    url: str  # the item's own page: the signal's evidence URL
    title: str
    text: str
    published: datetime | None
    links: list[str] = field(default_factory=list)
    website: str | None = None
    feed: str = ""
    signal_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").translate(_FOLD)).strip()


def verbatim(quote: str | None, text: str) -> str | None:
    """The part of `text` that `quote` copies (case, spacing and curly quotes may differ), cut from `text`
    itself so the stored quote is always a verbatim part of the source. None when it is not there."""
    words = _squash(quote or "").split(" ")
    if len("".join(words)) < 5 or "[email]" in (quote or "") or "[phone]" in (quote or ""):
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    match = re.search(pattern, (text or "").translate(_FOLD), re.I)
    if match is None:
        return None
    found = clean_text(text[match.start() : match.end()], QUOTE_MAX)
    return found if len(found) >= 5 else None


def names_in(names: Iterable[Any], text: str, *, limit: int) -> list[str]:
    """The names that are written in `text` as whole words (never a name the AI added), cleaned, at most
    `limit`."""
    hay = _squash(text).lower()
    out: list[str] = []
    for raw in names:
        name = clean_text(str(raw or ""), 80).strip(" ,.;:")
        if len(name) < 3 or name.lower() in (n.lower() for n in out):
            continue
        if re.search(rf"(?<!\w){re.escape(_squash(name).lower())}(?!\w)", hay):
            out.append(name)
        if len(out) >= limit:
            break
    return out


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value > 0 else None


class ItemJudge:
    """Classify startup items and turn each answer into a routed signal, or say why not (`judge`)."""

    def __init__(
        self,
        ctx: SourceContext,
        segments: Mapping[str, Segment],
        *,
        max_team: int | None = None,
        max_raise_usd: float | None = None,
        now: datetime | None = None,
    ) -> None:
        self.ctx = ctx
        self.segments = segments
        if max_team is None or max_raise_usd is None:
            team, money = startup.limits()
            max_team = team if max_team is None else max_team
            max_raise_usd = money if max_raise_usd is None else max_raise_usd
        self.max_team = max_team
        self.max_raise_usd = max_raise_usd
        self.now = now or datetime.now(UTC)

    def inputs(self, item: StartupItem) -> dict[str, Any]:
        return {
            "source": item.source,
            "url": item.url,
            "published": item.published.date().isoformat() if item.published else None,
            "title": item.title,
            "text": mask_contacts(item.text)[:TEXT_CHARS],
        }

    def judge(self, item: StartupItem) -> tuple[Signal | None, str]:
        """(signal or None, why) for one item: one AI call, then the checks of `signal_from`."""
        result = self.ctx.ai(TASK, self.inputs(item))
        if result is None:
            return None, "no_answer"
        return self.signal_from(item, result)

    def _website(self, item: StartupItem, answer: Any) -> str | None:
        if item.website:
            return homepage(item.website) if is_company_site(item.website) else None
        dom = web_domain(str(answer or ""))
        if not dom or not is_company_site(f"https://{dom}") or dom == web_domain(item.url):
            return None
        shown = f"{item.text} {item.title} {' '.join(item.links)}".lower()
        return f"https://{dom}/" if dom.lower() in shown else None

    def signal_from(self, item: StartupItem, result: Any) -> tuple[Signal | None, str]:
        """(signal or None, why) from the classifier's answer for one item."""
        if not field_of(result, "is_relevant"):
            return None, "not_relevant"
        if float(field_of(result, "confidence") or 0) < MIN_CONFIDENCE:
            return None, "low_confidence"
        sig_type = item.signal_type or EVENT_TO_TYPE.get(str(field_of(result, "event") or "other"), "news")
        raw_round = str(field_of(result, "round") or "unknown")
        funding_round = startup.normalize_round(MODEL_ROUNDS.get(raw_round, raw_round))
        team = _positive_int(field_of(result, "team_size"))
        amount = _positive_float(field_of(result, "amount_usd"))
        gate = startup.startup_gate(
            is_startup=field_of(result, "is_startup"),
            team_size=team,
            funding_round=funding_round,
            amount_usd=amount,
            max_team=self.max_team,
            max_raise_usd=self.max_raise_usd,
        )
        if not gate.ok:
            return None, gate.reason
        name = clean_text(str(field_of(result, "company_name") or ""), 120).strip(" ,.;:")
        if len(name) < 2 or name.lower() in NOT_A_NAME:
            return None, "no_company"
        text = mask_contacts(item.text)[:TEXT_CHARS]
        source_text = f"{item.title}\n{text}"
        website = self._website(item, field_of(result, "company_website"))
        country = iso_country(field_of(result, "hq_country"))
        country_from = "item"
        if country is None and website:
            country, country_from = country_from_domain(website), "website_domain"
        seg, why = route(country, self.segments)
        if seg is None:
            return None, why
        observed = item.published or self.now
        window = WINDOW_DAYS[sig_type]
        if window is not None and observed + timedelta(days=window) <= self.now:
            return None, "too_old"
        quote = verbatim(field_of(result, "evidence_quote"), source_text) or clean_text(item.title, QUOTE_MAX)
        details: dict[str, Any] = {**item.details, "title": item.title[:200], "country_from": country_from}
        if item.feed:
            details["feed"] = item.feed
        if funding_round != "unknown":
            details["round"] = funding_round
        if amount is not None:
            details["amount_usd"] = round(amount)
        investors = names_in(field_of(result, "investors") or [], source_text, limit=MAX_INVESTORS)
        if investors:
            details["investors"] = investors
        founders = startup.founders_detail(
            [
                {"name": n, "role": "Founder"}
                for n in names_in(field_of(result, "founders") or [], source_text, limit=5)
            ],
            source_url=item.url,
        )
        if founders:
            details["founders"] = founders
        if team is not None:
            details["team_size"] = team
            details["team_size_source"] = "item"
        if item.published is None:
            details["date_estimated"] = True
        city = city_for_text(str(field_of(result, "city") or ""), seg.cities)
        return (
            Signal(
                type=sig_type,
                source=item.source,
                observed_at=observed,
                url=item.url,
                quote=quote,
                evidence_key=item.key,
                business_hint={k: v for k, v in {"name": name, "city": city, "website": website}.items() if v},
                details=details,
                segment_id=seg.id,
            ),
            "signal",
        )


# ---------------------------------------------------------------------------------------------------
# One pass of a source: window, caps, deadline, seen items
# ---------------------------------------------------------------------------------------------------


@dataclass
class Pass:
    """One run of a startup source: how many days back it looks, how many items it may classify, and when it must
    stop starting new work. The nightly pass counts its items per IST day (`<source>_item` rows in `costs`, the
    same way GDELT queries are counted); the backlog pass has its own cap and never uses the nightly allowance."""

    days: int
    cap: int
    backlog: bool = False
    stop_at: float | None = None  # time.monotonic() deadline

    def time_up(self) -> bool:
        return self.stop_at is not None and time.monotonic() >= self.stop_at

    def since(self, now: datetime | None = None) -> datetime:
        return (now or datetime.now(UTC)) - timedelta(days=self.days)


def item_task(source: str) -> str:
    """`costs.task` of one item classified by `source` in a nightly pass (provider `other`, no money)."""
    return f"{source}_item"


def nightly_pass(ctx: SourceContext, source: str, setting: str, default: int, *, days: int) -> Pass:
    """The nightly pass: today's allowance is the daily setting minus the items already classified today."""
    cap = health.setting_int(setting, default)
    left = max(0, cap - ctx.budget.calls_today("other", [item_task(source)]))
    if ctx.limit:
        left = min(left, ctx.limit)
    return Pass(days=days, cap=left)


def title_key(title: str | None) -> str | None:
    """A second key for an item: its title without case and punctuation, hashed. One story is often published
    under several URLs (syndicated press releases, a site's AMP copy); the title key keeps it to one AI call.
    Titles under five words are too generic to identify a story (None)."""
    words = re.findall(r"\w+", (title or "").lower())
    if len(words) < 5:
        return None
    return "title:" + hashlib.sha1(" ".join(words).encode()).hexdigest()[:20]


def unseen(source: str, keys: Sequence[str]) -> set[str]:
    """The keys not yet in `source_records` for this source (each item is judged once)."""
    if not keys:
        return set()
    known = {
        r["source_key"]
        for r in db.fetch_all(
            "select source_key from public.source_records where source = %s and source_key = any(%s)",
            [source, list(dict.fromkeys(keys))],
        )
    }
    return {k for k in keys if k not in known}


def record_seen(ctx: SourceContext, item: StartupItem, verdict: str) -> None:
    """Remember a judged item by its key and its title, so neither it nor a copy of the same story is sent to the
    AI again (nothing is written in a dry run)."""
    if ctx.dry_run:
        return
    payload = {"url": item.url, "title": item.title[:200], "verdict": verdict}
    keys = [k for k in dict.fromkeys((item.key, title_key(item.title))) if k]
    db.upsert(
        "source_records",
        [{"source": item.source, "source_key": k, "payload": payload, "fetched_at": health.now_utc()} for k in keys],
        conflict=["source", "source_key"],
        update=["payload", "fetched_at"],
    )


def judge_items(ctx: SourceContext, judge: ItemJudge, items: Sequence[StartupItem], run: Pass) -> list[Signal]:
    """Classify items in order until the pass's cap, its deadline, the AI budget or (backlog) the
    low-priority budget phase says stop. Every judged item is remembered; an item the AI did not answer is
    left for the next run."""
    out: list[Signal] = []
    for item in items:
        name = item.source
        if run.cap <= 0:
            ctx.add(f"{name}.cap_reached")
            break
        if run.time_up():
            ctx.add(f"{name}.time_up")
            break
        if ctx.ai_stopped:
            break
        if run.backlog and not ctx.budget.allow_phase(BACKLOG_BUDGET_PHASE):
            ctx.add(f"{name}.budget_stop")
            break
        sig, why = judge.judge(item)
        ctx.add(f"{name}.{why}")
        if why == "no_answer":
            continue
        run.cap -= 1
        if not run.backlog:
            ctx.budget.record("other", None, item_task(name))
        record_seen(ctx, item, why)
        if sig is not None:
            out.append(sig)
    return out


async def guarded[T](adapter: SourceAdapter, fn: Callable[[], Awaitable[T]]) -> T | None:
    """Run a source behind its kill switch. A block pauses the source; a run where nothing could be read is an
    error (`adapter.failure`), anything else is a healthy run."""
    usable, why = adapter.status()
    if not usable:
        adapter.ctx.add(f"skipped.{adapter.name}")
        adapter.ctx.stats.setdefault("skip_reasons", {})[adapter.name] = why
        return None
    try:
        out = await fn()
    except SourceBlocked as err:
        adapter.health_blocked(err)
        return None
    failure = getattr(adapter, "failure", None)
    if failure:
        adapter.health_error(str(failure))
        log.warning("source.failed", source=adapter.name, error=str(failure)[:200])
    else:
        adapter.health_ok()
    return out


async def bounded(limit: int, jobs: Sequence[Callable[[], Awaitable[None]]]) -> None:
    """Run jobs with at most `limit` at a time (pages on different hosts load in parallel; `PoliteClient` still
    spaces requests to one host)."""
    gate = asyncio.Semaphore(max(1, limit))

    async def one(job: Callable[[], Awaitable[None]]) -> None:
        async with gate:
            await job()

    await asyncio.gather(*(one(j) for j in jobs))


class Sink(Protocol):
    """What a watcher hands its signals to (`pipeline.signals.SignalSink`)."""

    def add(self, sig: Signal, seg: Segment) -> None: ...


def to_sink(sigs: Iterable[Signal] | None, segments: Mapping[str, Segment], sink: Sink) -> None:
    """Hand routed signals to the sink (each carries its segment id)."""
    for sig in sigs or []:
        seg = segments.get(sig.segment_id or "")
        if seg is not None:
            sink.add(sig, seg)
