"""GDELT DOC 2.0 API: news about openings, new branches, launches and funding (Step 5.10, Step 7.5.9).

Free, commercial use allowed with credit to GDELT (`details.source = "GDELT"` on every signal). The API asks for
at most one request every 5 seconds and answers faster callers with HTTP 429 and a plain-text notice, so the gap
here is 6 seconds, a 429 waits once and retries, and a second 429 ends GDELT for this run (no long pause: it is
rate limiting, not a block). Articles are fetched politely from their own sites (robots.txt obeyed); a news
site that blocks us is skipped, it does not pause the GDELT source.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..http import NeverFetch, PoliteClient, SourceBlocked
from ..normalize import canonical_url, city_for_text
from ..research.text import article_text
from ..segments import Segment
from . import health
from .base import QUOTE_MAX, Signal, SourceAdapter, field_of
from .jobs import quote_in

API = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_QUERIES_PER_DAY = 30
MAX_RECORDS = 100
MIN_CONFIDENCE = 0.6
ARTICLE_CHARS = 3000
RATE_LIMIT_WAIT_S = 12.0
EVENT_TO_SIGNAL = {"new_branch": "new_branch", "news": "news", "funding": "funding"}
QUERY_TASK = "gdelt_query"


@dataclass
class Article:
    url: str
    title: str
    seen: datetime | None
    domain: str
    language: str
    country: str


def parse_articles(data: dict[str, Any]) -> list[Article]:
    out = []
    for a in data.get("articles", []) or []:
        url = str(a.get("url") or "")
        if not url:
            continue
        seen = None
        if a.get("seendate"):
            try:
                seen = datetime.strptime(str(a["seendate"]), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            except ValueError:
                seen = None
        out.append(
            Article(
                url=url,
                title=str(a.get("title") or ""),
                seen=seen,
                domain=str(a.get("domain") or ""),
                language=str(a.get("language") or ""),
                country=str(a.get("sourcecountry") or ""),
            )
        )
    return out


class GdeltAdapter(SourceAdapter):
    name = "gdelt"
    policy = "official_api"
    min_gap_s = 6.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: PoliteClient | None = None
        self.rate_limited = False

    @property
    def pages(self) -> PoliteClient:
        """A separate client for the news sites themselves (public pages: robots.txt and a 2 second gap)."""
        if self._pages is None:
            self._pages = PoliteClient("gdelt_articles", policy="public", transport=self._transport)
        return self._pages

    async def aclose(self) -> None:
        if self._pages is not None:
            await self._pages.aclose()
            self._pages = None
        await super().aclose()

    async def search(self, query: str, timespan: str = "3d") -> list[Article]:
        """Articles of the last `timespan` (3 days since 13 Nov 2026: a night lost to a rate limit or a timeout
        no longer loses that day's news; the signal's evidence key keeps an article from counting twice)."""
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": MAX_RECORDS,
            "timespan": timespan,
            "sort": "DateDesc",
        }
        for attempt in range(2):
            res = await self.http.get(API, params=params, check_robots=False, raise_on_block=False, retries=1)
            self.ctx.budget.record("other", None, QUERY_TASK)  # free, counted for the daily query cap
            if res.status == 429:
                self.http.blocked_hosts.pop("api.gdeltproject.org", None)
                if attempt == 0:
                    await asyncio.sleep(RATE_LIMIT_WAIT_S)
                    continue
                self.rate_limited = True
                self.ctx.add("gdelt.rate_limited")
                return []
            if res.status != 200:
                self.ctx.add("gdelt.errors")
                return []
            try:
                return parse_articles(res.json())
            except ValueError:  # GDELT answers {} or a text notice when nothing matched
                return []
        return []

    async def article(self, url: str) -> str | None:
        try:
            res = await self.pages.get(url, max_bytes=3_000_000)
        except (SourceBlocked, NeverFetch):
            self.ctx.add("gdelt.article_blocked")
            return None
        if not res.ok:
            self.ctx.add("gdelt.article_unreadable")
            return None
        return article_text(res.text, res.final_url, ARTICLE_CHARS)

    def classify(self, art: Article, text: str, seg: Segment) -> Signal | None:
        result = self.ctx.ai(
            "classify_news",
            {
                "segment_id": seg.id,
                "domain": seg.domain,
                "country": seg.country,
                "cities": [c.name for c in seg.cities],
                "url": art.url,
                "published": art.seen.date().isoformat() if art.seen else "unknown",
                "title": art.title,
                "text": text,
            },
        )
        if result is None:
            return None
        sig_type = EVENT_TO_SIGNAL.get(str(field_of(result, "signal_type") or "none"))
        if not field_of(result, "relevant") or sig_type is None:
            self.ctx.add("gdelt.not_relevant")
            return None
        if float(field_of(result, "confidence") or 0) < MIN_CONFIDENCE:
            self.ctx.add("gdelt.low_confidence")
            return None
        quote = (field_of(result, "quote") or "").strip()
        if not quote_in(quote, f"{art.title}\n{text}"):
            self.ctx.add("gdelt.quote_not_found")
            return None
        name = (field_of(result, "business_name") or "").strip()
        city = city_for_text(str(field_of(result, "city") or ""), seg.cities) or city_for_text(text, seg.cities)
        if not name or (city is None and seg.universe != "signals_only"):  # need-first: remote companies
            self.ctx.add("gdelt.no_business_or_city")
            return None
        observed = art.seen or datetime.now(UTC)
        details: dict[str, Any] = {"source": "GDELT", "title": art.title[:200], "domain": art.domain}
        if sig_type in ("new_branch", "news"):
            details["event_key"] = f"growth:{observed:%Y-%m}"
        if art.seen is None:
            details["date_estimated"] = True
        return Signal(
            type=sig_type,
            source=self.name,
            observed_at=observed,
            url=art.url,
            quote=quote[:QUOTE_MAX],
            evidence_key=canonical_url(art.url),
            business_hint={"name": name, "city": city},
            details=details,
        )

    async def signals_for(self, seg: Segment, *, budget: int, limit: int | None = None) -> list[Signal]:
        """News signals for one segment from at most `budget` queries."""
        out: list[Signal] = []
        seen: set[str] = set()
        for query in seg.news_queries[:budget]:
            if self.rate_limited:
                break
            for art in await self.search(query):
                key = canonical_url(art.url)
                if key in seen:
                    continue
                seen.add(key)
                text = await self.article(art.url)
                if not text:
                    continue
                sig = self.classify(art, text, seg)
                if sig is not None:
                    out.append(sig)
                if limit and len(out) >= limit:
                    return out
        return out

    def queries_left(self) -> int:
        cap = health.setting_int("gdelt.queries_per_day", DEFAULT_QUERIES_PER_DAY)
        return max(0, cap - self.ctx.budget.calls_today("other", [QUERY_TASK]))
