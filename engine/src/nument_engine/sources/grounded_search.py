"""Public asks found through grounded web search (Step 5.11, Step 7.5.3). The strongest stated-need signal.

One `grounded_search` router call per query returns `PublicAskResults` items plus the search citations. Evidence
rules, enforced by code:
- An item must point at a URL the search actually cited; items without a citation are dropped.
- A normal web page is fetched politely and the quote must be found in it (10 points, 14 days).
- A LinkedIn or X URL is never fetched (A.4.2): the search snippet is kept as the quote, `snippet_only = true`,
  6 points, and the app shows "snippet only, check before sending".
- Posts older than 14 days are dropped; the poster must be a business in a segment city (checked by
  `classify_signal` and the city rule).

Gemini returns citation links as `vertexaisearch.cloud.google.com/grounding-api-redirect/...` URLs. They are
resolved by reading the redirect's Location header only (one request to Google, nothing at the target), so a
citation can be compared with the item's URL without ever opening a LinkedIn or X page.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil import parser as dateparser
from rapidfuzz import fuzz

from ..http import NeverFetch, PoliteClient, SourceBlocked, host_blocked, host_of
from ..normalize import canonical_url, city_for_text
from ..research.text import page_text
from ..segments import Segment
from .base import QUOTE_MAX, SNIPPET_ONLY_POINTS, Signal, SourceAdapter, field_of
from .jobs import DOMAIN_MAP, MIN_CONFIDENCE, quote_in

MAX_AGE_DAYS = 14
REDIRECT_HOSTS = ("vertexaisearch.cloud.google.com",)
QUOTE_MATCH_MIN = 92  # same threshold as Step 10.2


@dataclass
class Citation:
    uri: str
    title: str
    resolved: str | None = None


@dataclass
class GroundedAnswer:
    items: list[Any]
    citations: list[Citation]


def grounding_of(result: Any) -> dict[str, Any] | None:
    """Grounding metadata from a router result, whatever its shape (attribute or dict key)."""
    for name in ("grounding", "_grounding", "grounding_metadata"):
        value = field_of(result, name)
        if isinstance(value, dict):
            return value
    return None


def answer_from(result: Any) -> GroundedAnswer:
    """Normalise what the router returned: an `AIAnswer` / `AIResult` (output plus grounding), a
    `(parsed, grounding)` pair, a parsed `PublicAskResults`, or a text answer holding the JSON.

    The router's grounding lists the cited pages under `sources` (`chunks` in the raw Gemini shape)."""
    grounding: dict[str, Any] | None = None
    parsed = result
    if isinstance(result, tuple) and len(result) == 2:
        parsed, grounding = result
    elif field_of(result, "output") is not None:
        parsed, grounding = field_of(result, "output"), grounding_of(result)
    grounding = grounding or grounding_of(parsed)
    items = field_of(parsed, "items")
    if items is None and isinstance(field_of(parsed, "text"), str):
        try:
            data = json.loads(str(field_of(parsed, "text")))
            items = data.get("items") or data.get("results") or []
        except ValueError:
            items = []
    cited = (grounding or {}).get("sources") or (grounding or {}).get("chunks") or []
    citations = [Citation(uri=str(c.get("uri") or ""), title=str(c.get("title") or "")) for c in cited if c]
    return GroundedAnswer(items=list(items or []), citations=[c for c in citations if c.uri])


def _same_url(a: str, b: str) -> bool:
    ca, cb = canonical_url(a), canonical_url(b)
    return ca == cb or ca.startswith(cb.rstrip("/") + "/") or cb.startswith(ca.rstrip("/") + "/")


# The prompt reads "a business in {country} ... for a {domain} business"; segment codes ("in", "clinics")
# read badly there, and a garbled ask makes the model more likely to answer without searching.
COUNTRY_NAMES: dict[str, str] = {
    "in": "India",
    "ae": "the UAE",
    "sa": "Saudi Arabia",
    "qa": "Qatar",
    "uk": "the UK",
    "gb": "the UK",
    "sg": "Singapore",
    "us": "the US",
    "au": "Australia",
}
DOMAIN_WORDS: dict[str, str] = {"clinics": "clinic", "realestate": "real estate", "education": "coaching or education"}


class GroundedSearchAdapter(SourceAdapter):
    name = "grounded_search"
    policy = "official_api"
    min_gap_s = 0.5

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: PoliteClient | None = None

    @property
    def pages(self) -> PoliteClient:
        """Client for the cited pages themselves (public pages: robots.txt, 2 second gap per host)."""
        if self._pages is None:
            self._pages = PoliteClient("grounded_pages", policy="public", transport=self._transport)
        return self._pages

    async def aclose(self) -> None:
        if self._pages is not None:
            await self._pages.aclose()
            self._pages = None
        await super().aclose()

    # ---- quota --------------------------------------------------------------------------------------
    def calls_left(self) -> int:
        """Search queries still allowed today (the budget guard's daily cap and free monthly allowance)."""
        return self.ctx.budget.grounding_quota_left()

    @staticmethod
    def todays_queries(seg: Segment, day: int | None = None) -> list[str]:
        """Each query runs every third day, so every segment is searched at least twice a week (5.11.3)."""
        day = datetime.now(UTC).toordinal() if day is None else day
        return [q for i, q in enumerate(seg.public_ask_queries) if (day + i) % 3 == 0]

    # ---- citations ----------------------------------------------------------------------------------
    async def resolve_citation(self, cite: Citation) -> str:
        if cite.resolved:
            return cite.resolved
        target = cite.uri
        if host_of(cite.uri) in REDIRECT_HOSTS:
            location = await self.http.location(cite.uri)
            target = location or cite.uri
        cite.resolved = target
        return target

    async def cited_url(self, url: str, citations: Sequence[Citation]) -> str | None:
        """The citation that matches the item URL, or None when the search never cited it."""
        for cite in citations:
            if _same_url(url, await self.resolve_citation(cite)):
                return cite.resolved
        return None

    # ---- evidence -----------------------------------------------------------------------------------
    async def verify_on_page(self, url: str, quote: str) -> bool:
        try:
            res = await self.pages.get(url, max_bytes=3_000_000)
        except (SourceBlocked, NeverFetch):
            self.ctx.add("grounded_search.page_blocked")
            return False
        if not res.ok:
            return False
        text, _ = page_text(res.text, res.final_url)
        if quote_in(quote, text):
            return True
        return fuzz.partial_ratio(quote.lower(), text.lower()) >= QUOTE_MATCH_MIN

    @staticmethod
    def posted(value: Any) -> datetime | None:
        if not value or str(value).lower() in ("unknown", "none", "null"):
            return None
        try:
            parsed = dateparser.parse(str(value), default=datetime.now(UTC).replace(month=1, day=1))
        except (ValueError, OverflowError):
            return None
        return parsed if parsed and parsed.tzinfo else parsed.replace(tzinfo=UTC) if parsed else None

    def classify(self, item: Any, seg: Segment) -> bool:
        result = self.ctx.ai(
            "classify_signal",
            {
                "segment_id": seg.id,
                "domain": seg.domain,
                "country": seg.country,
                "source": self.name,
                "url": field_of(item, "url"),
                "posted_date": field_of(item, "posted_date"),
                "title": field_of(item, "poster_business"),
                "employer_name": field_of(item, "poster_business"),
                "employer": field_of(item, "poster_business"),
                "address": field_of(item, "poster_city"),
                "mode": "public_ask",
                "text": f"{field_of(item, 'need') or ''}\n{field_of(item, 'quote') or ''}",
            },
        )
        if result is None or not field_of(result, "is_relevant"):
            return False
        domain = str(field_of(result, "employer_domain") or "other")
        if domain == "agency_or_staffing" or DOMAIN_MAP.get(domain) != seg.domain:
            return False
        return float(field_of(result, "confidence") or 0) >= MIN_CONFIDENCE

    async def item_signal(self, item: Any, citations: Sequence[Citation], seg: Segment) -> Signal | None:
        url, quote = str(field_of(item, "url") or ""), str(field_of(item, "quote") or "").strip()
        if not url or len(quote) < 5:
            return None
        cited = await self.cited_url(url, citations)
        if cited is None:
            self.ctx.add("grounded_search.uncited_dropped")
            return None
        posted = self.posted(field_of(item, "posted_date"))
        now = datetime.now(UTC)
        if posted is not None and posted < now - timedelta(days=MAX_AGE_DAYS):
            self.ctx.add("grounded_search.too_old")
            return None
        city = city_for_text(str(field_of(item, "poster_city") or ""), seg.cities)
        name = str(field_of(item, "poster_business") or "").strip()
        if not name or city is None:
            self.ctx.add("grounded_search.no_business_or_city")
            return None
        snippet_only = host_blocked(cited)
        if not snippet_only and not await self.verify_on_page(cited, quote):
            self.ctx.add("grounded_search.quote_not_on_page")
            return None
        if not self.classify(item, seg):
            self.ctx.add("grounded_search.not_a_business_ask")
            return None
        details: dict[str, Any] = {"need": field_of(item, "need"), "snippet_only": snippet_only}
        if posted is None:
            details["date_estimated"] = True
        return Signal(
            type="public_ask",
            source=self.name,
            observed_at=posted or now,
            url=cited,
            quote=quote[:QUOTE_MAX],
            evidence_key=canonical_url(cited),
            business_hint={"name": name, "city": city},
            details=details,
            points=SNIPPET_ONLY_POINTS if snippet_only else None,
        )

    async def signals_for(self, seg: Segment, *, budget: int, limit: int | None = None) -> list[Signal]:
        out: list[Signal] = []
        for query in self.todays_queries(seg)[:budget]:
            if self.ctx.ai_stopped:
                break
            result = self.ctx.ai_result(  # output and citations together
                "grounded_search",
                {
                    "segment_id": seg.id,
                    "domain": DOMAIN_WORDS.get(seg.domain, seg.domain),
                    "country": COUNTRY_NAMES.get(seg.country, seg.country.upper()),
                    "cities": [c.name for c in seg.cities],
                    "query": query,
                    "queries": [query],
                    "days": MAX_AGE_DAYS,
                    "today": datetime.now(UTC).date().isoformat(),
                },
            )
            if result is None:
                continue
            answer = answer_from(result)
            self.ctx.add("grounded_search.items", len(answer.items))
            for item in answer.items:
                sig = await self.item_signal(item, answer.citations, seg)
                if sig is not None:
                    out.append(sig)
                if limit and len(out) >= limit:
                    return out
        return out
