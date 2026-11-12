"""Google Maps listings read like a person reads them: rating, review count and the reviews Maps shows first, for
businesses without Places data (no Google Cloud billing account, so no Places API).

Grey source, founder approved at a low rate (12 Nov 2026). The rules:
- The same Chromium research uses (Playwright), headless, with the honest User-Agent of every other request.
  No stealth or fingerprint flags, no proxies, no cookies kept between runs, no sign-in, no CAPTCHA handling.
  Images, media and fonts are not downloaded.
- One lookup at a time: `https://www.google.com/maps/search/<name, locality, city>` (robots.txt allows
  `/maps/search/` and `/maps/place/`). robots.txt and a 6 second gap are applied through the polite HTTP client
  before every page load, and each load counts in `source_health.requests_today`.
- A consent wall, a CAPTCHA or "unusual traffic" page, or a sign-in prompt stops the source: `SourceBlocked`, so
  the run pauses it (24 hours, then 72, then 7 days; a second block in 7 days switches it off until the
  founder turns it back on). Sorting reviews by newest needs a sign-in, so only the reviews Maps shows without one
  are read (about 5, most relevant first, each with its age).
- A listing counts only when it is confirmed: the same website, or the business name inside the listing name plus
  a point within 1 km or the business's locality in the listing address. A different website rejects it.
- Nothing is stored here. The stage (`pipeline/maps_reviews.py`) stores the numbers like Places numbers
  (never over Places data, kept 30 days) and turns front-desk complaints into `review_pain`. The listing phone
  is never taken (phones come only from the business's own pages).

The fields are the ones gosom/google-maps-scraper (MIT) reads from the same public page. Its release binary is not
used: it hard-codes a made-up browser User-Agent, a Chromium flag that hides automation and a click through the
consent wall, all of which the rules above forbid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from urllib.parse import parse_qs, quote, urlsplit

from ..http import SourceBlocked
from ..logging import get_logger
from ..normalize import meters, norm_name, web_domain
from ..settings import get_settings
from .base import SourceAdapter
from .practo import covers
from .review_pain import ReviewText

log = get_logger()

SEARCH: Final = "https://www.google.com/maps/search/{query}?hl=en"
HOST: Final = "google.com"
DEFAULT_PER_DAY: Final = 100
SETTING_PER_DAY: Final = "maps_reviews.lookups_per_day"
SETTING_MINUTES: Final = "maps_reviews.minutes_per_run"
DEFAULT_MINUTES: Final = 4  # about 40 lookups; keeps the night job inside the free Actions minutes
NEAR_M: Final = 1000.0
LOAD_MS: Final = 30_000
WAIT_MS: Final = 12_000
BLOCKED_RESOURCES: Final = frozenset({"image", "media", "font"})

_COORDS = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_AT = re.compile(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_COUNT = re.compile(r"\(([\d,.\s]+)\)|([\d,]+)\s+reviews?", re.I)
_RATING = re.compile(r"(\d(?:[.,]\d)?)\s*stars?", re.I)
_AGE = re.compile(r"(?:(\d+)|an?|one)\s+(minute|hour|day|week|month|year)s?\s+ago", re.I)
WALL_TEXT: Final = (
    "unusual traffic",
    "our systems have detected",
    "not a robot",
    "before you continue to google",
    "sign-in to get the best of google maps",
    "sign in to get the best of google maps",
)


@dataclass
class Listing:
    """One Google Maps listing as the page shows it. Review texts stay in memory."""

    url: str
    name: str | None = None
    rating: float | None = None
    review_count: int | None = None
    website: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    reviews: list[ReviewText] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------------
# Parsing (pure, tested with fixtures)
# ---------------------------------------------------------------------------------------------------


def query_for(business: dict[str, Any]) -> str:
    """`Name, Locality, City`, the locality only when it is not the city itself."""
    parts = [str(business.get("name") or "").strip()]
    loc, city = str(business.get("locality") or "").strip(), str(business.get("city") or "").strip()
    if loc and norm_name(loc) != norm_name(city) and norm_name(loc) not in norm_name(parts[0]):
        parts.append(loc)
    if city:
        parts.append(city.split(" and ")[0])  # "Thane and Navi Mumbai" searches as Thane
    return ", ".join(p for p in parts if p)


def search_url(business: dict[str, Any]) -> str:
    return SEARCH.format(query=quote(query_for(business), safe=""))


def age_days(text: str | None) -> int | None:
    """Days from a relative date such as "3 weeks ago", "a month ago" or "Edited 2 years ago"."""
    low = (text or "").lower()
    if "yesterday" in low:
        return 1
    m = _AGE.search(low)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1) else 1
    unit = m.group(2).lower()
    return {"minute": 0, "hour": 0, "day": n, "week": 7 * n, "month": 30 * n, "year": 365 * n}[unit]


def parse_count(text: str | None) -> int | None:
    m = _COUNT.search(text or "")
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(1) or m.group(2) or "")
    return int(digits) if digits else None


def parse_rating(text: str | None) -> float | None:
    m = _RATING.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value if 1.0 <= value <= 5.0 else None


def coords(url: str) -> tuple[float | None, float | None]:
    m = _COORDS.search(url) or _AT.search(url)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def unwrap(href: str | None) -> str | None:
    """The target of a Google redirect link (`/url?q=https://site/`), or the link itself."""
    if not href:
        return None
    parts = urlsplit(href)
    if parts.path == "/url":
        targets = parse_qs(parts.query).get("q") or []
        return targets[0] if targets else None
    return href


def wall_reason(url: str, text: str, dialog: str = "", has_listing: bool = True) -> str | None:
    """Why a page is a consent wall, a bot check or a sign-in prompt, or None. The page text counts only when
    the page shows no listing (a review may well say "unusual traffic"); a dialog's text always counts."""
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("consent."):
        return "consent wall"
    if "/sorry/" in urlsplit(url).path:
        return "bot check (sorry page)"
    if host.startswith("accounts."):
        return "sign-in wall"
    low = dialog.lower() + " " + ("" if has_listing else text.lower())
    for marker in WALL_TEXT:
        if marker in low:
            return f"wall: {marker}"
    if "recaptcha" in low or "captcha" in dialog.lower():
        return "captcha"
    return None


def listing_from(raw: dict[str, Any]) -> Listing:
    """A Listing from what the browser read off the page (see `READ_LISTING_JS`). The URL loses its query
    (language and tracking parameters); the path names the place."""
    url = str(raw.get("url") or "").split("?", 1)[0]
    lat, lng = coords(url)
    address = str(raw.get("address") or "").removeprefix("Address:").strip() or None
    reviews = [
        ReviewText(str(r.get("text") or "").strip(), age_days(r.get("when")), parse_rating(r.get("stars")))
        for r in raw.get("reviews") or []
        if isinstance(r, dict)
    ]
    summary = " ".join(str(raw.get(k) or "") for k in ("summary", "reviews_button"))
    return Listing(
        url=url,
        name=str(raw.get("name") or "").strip() or None,
        rating=parse_rating(raw.get("stars")) or _summary_rating(raw.get("summary")),
        review_count=parse_count(raw.get("reviews_button")) or parse_count(summary),
        website=unwrap(raw.get("website")),
        address=address,
        lat=lat,
        lng=lng,
        reviews=[r for r in reviews if r.text],
    )


def _summary_rating(text: Any) -> float | None:
    m = re.match(r"\s*(\d[.,]\d)", str(text or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def confirms(business: dict[str, Any], listing: Listing) -> str | None:
    """Why this listing is the business ("website", "distance", "address"), or None. The same website settles
    it and a different one rejects it; otherwise the listing name must hold the business name and the place
    must agree (within 1 km, or the business's locality named in the listing address)."""
    own = business.get("web_domain") or web_domain(business.get("website"))
    theirs = web_domain(listing.website) if listing.website else None
    if own and theirs:
        return "website" if own == theirs else None
    city = str(business.get("city") or "")
    ignore = [city, *city.split(" and "), str(business.get("locality") or "")]
    if not listing.name or not covers(str(business.get("name") or ""), listing.name, ignore):
        return None
    lat, lng = business.get("lat"), business.get("lng")
    if lat is not None and lng is not None and listing.lat is not None and listing.lng is not None:
        return "distance" if meters(float(lat), float(lng), listing.lat, listing.lng) <= NEAR_M else None
    loc = norm_name(str(business.get("locality") or ""))
    if len(loc) >= 4 and loc != norm_name(city) and loc in norm_name(listing.address or ""):
        return "address"
    return None


# ---------------------------------------------------------------------------------------------------
# The browser (Playwright Chromium, the one research installs)
# ---------------------------------------------------------------------------------------------------

READ_LISTING_JS: Final = """() => {
  const q = (s) => document.querySelector(s);
  const reviews = Array.from(document.querySelectorAll("div.jftiEf")).slice(0, 10).map((r) => ({
    stars: r.querySelector("span.kvMYJc")?.getAttribute("aria-label") || "",
    when: r.querySelector("span.rsqaWe")?.textContent || "",
    text: r.querySelector("div.MyEned span.wiI7pd")?.textContent || "",
  }));
  const tab = Array.from(document.querySelectorAll("button[role='tab']"))
    .find((b) => (b.getAttribute("aria-label") || "").toLowerCase().startsWith("reviews"));
  return {
    url: location.href,
    name: q("h1")?.textContent || "",
    stars: q("div.F7nice span[role='img']")?.getAttribute("aria-label") || "",
    summary: q("div.F7nice")?.textContent || "",
    reviews_button: q("button[jsaction*='reviewChart']")?.textContent || "",
    website: q("a[data-item-id='authority']")?.getAttribute("href") || "",
    address: q("button[data-item-id='address']")?.getAttribute("aria-label") || "",
    has_reviews_tab: Boolean(tab),
    reviews,
  };
}"""
PLACE_OR_LIST_JS: Final = """() => location.pathname.includes("/maps/place/")
  || document.querySelectorAll("div[role='feed'] a.hfpxzc").length > 0"""
RESULTS_JS: Final = """() => Array.from(document.querySelectorAll("div[role='feed'] a.hfpxzc")).slice(0, 10)
  .map((a) => ({name: a.getAttribute("aria-label") || "", href: a.href}))"""
EXPAND_JS: Final = """() => { let n = 0;
  for (const b of document.querySelectorAll("div.jftiEf button.w8nwRe")) {
    if ((b.getAttribute("jsaction") || "").includes("expandReview")) { b.click(); n++; } }
  return n; }"""
PAGE_STATE_JS: Final = """() => ({
  has_listing: Boolean(document.querySelector("h1, div[role='feed']")),
  dialog: Array.from(document.querySelectorAll("[role='dialog'], [role='alertdialog']"))
    .map((d) => d.innerText || "").join(" ").slice(0, 2000),
  text: (document.body?.innerText || "").slice(0, 5000)
    + (document.querySelector("iframe[src*='recaptcha']") ? " recaptcha" : ""),
})"""
STABLE_REVIEWS_JS: Final = """() => { const n = document.querySelectorAll("div.jftiEf").length;
  const prev = window.__nleadReviews ?? -1; window.__nleadReviews = n; return n > 0 && n === prev; }"""


class Page(Protocol):
    """The part of a Playwright page this module uses (tests pass a fake)."""

    url: str

    async def goto(self, url: str, **kwargs: Any) -> Any: ...
    async def wait_for_selector(self, selector: str, **kwargs: Any) -> Any: ...
    async def wait_for_function(self, expression: str, **kwargs: Any) -> Any: ...
    async def wait_for_timeout(self, timeout: float) -> None: ...
    async def evaluate(self, expression: str) -> Any: ...
    async def click(self, selector: str, **kwargs: Any) -> None: ...
    async def close(self) -> None: ...


class MapsBrowser:
    """One headless Chromium for one run, one page at a time, honest defaults."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def page(self) -> Any:
        if self._context is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent=get_settings().user_agent, locale="en-IN", accept_downloads=False
            )
        page = await self._context.new_page()

        async def route(r: Any) -> None:
            if r.request.resource_type in BLOCKED_RESOURCES:
                await r.abort()
            else:
                await r.continue_()

        await page.route("**/*", route)
        return page

    async def aclose(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                await closer.close()
        if self._pw is not None:
            await self._pw.stop()
        self._pw = self._browser = self._context = None


# ---------------------------------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------------------------------


@dataclass
class Lookup:
    """The outcome of one lookup: the listing (None when Maps found nothing) and why it does or does not count."""

    listing: Listing | None
    how: str | None  # website, distance, address; None = not confirmed
    why: str = ""


class MapsReviewsAdapter(SourceAdapter):
    name = "maps_reviews"
    policy = "grey"
    min_gap_s = 6.0

    def __init__(self, *args: Any, browser: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.browser = browser or MapsBrowser()

    async def aclose(self) -> None:
        await self.browser.aclose()
        await super().aclose()

    async def _open(self, page: Page, url: str) -> None:
        """Load one Maps URL after the polite checks; a wall raises SourceBlocked (the source stops)."""
        skip = await self.http.reserve(url)
        if skip:
            raise SourceBlocked(self.name, HOST, skip)
        await page.goto(url, wait_until="domcontentloaded", timeout=LOAD_MS)
        await self._check_wall(page)

    async def _check_wall(self, page: Page) -> None:
        try:
            state = await page.evaluate(PAGE_STATE_JS)
        except Exception:  # a page between two navigations: checked again after the next step
            state = {}
        why = wall_reason(
            page.url,
            str(state.get("text") or ""),
            str(state.get("dialog") or ""),
            bool(state.get("has_listing", True)),
        )
        if why:
            self.http.mark_blocked(page.url, why)
            raise SourceBlocked(self.name, HOST, why)

    async def lookup(self, business: dict[str, Any]) -> Lookup:
        """Find one business on Maps, confirm it, and read its numbers and first reviews."""
        page = await self.browser.page()
        try:
            await self._open(page, search_url(business))
            try:  # the search lands on one listing (the URL turns into /maps/place/) or on a list of results
                await page.wait_for_function(PLACE_OR_LIST_JS, polling=300, timeout=WAIT_MS)
            except Exception:
                await self._check_wall(page)
                return Lookup(None, None, "nothing found")
            if "/maps/place/" not in page.url:
                results = await page.evaluate(RESULTS_JS)
                pick = next(
                    (r for r in results or [] if covers(str(business.get("name") or ""), str(r.get("name") or ""))),
                    None,
                )
                if pick is None or "/maps/place/" not in str(pick.get("href") or ""):
                    return Lookup(None, None, f"no matching result among {len(results or [])}")
                await self._open(page, str(pick["href"]))
            await page.wait_for_selector("h1", timeout=WAIT_MS)
            listing = listing_from(await page.evaluate(READ_LISTING_JS))
            how = confirms(business, listing)
            if how is None:
                return Lookup(listing, None, "listing not confirmed")
            listing.reviews = await self._reviews(page) or listing.reviews
            return Lookup(listing, how)
        finally:
            await page.close()

    async def _reviews(self, page: Page) -> list[ReviewText]:
        """The reviews tab as Maps shows it without a sign-in (no sorting: sorting asks for one)."""
        try:
            await page.click("button[role='tab'][aria-label^='Reviews']", timeout=5_000)
            await page.wait_for_function(STABLE_REVIEWS_JS, polling=700, timeout=WAIT_MS)
        except Exception:
            await self._check_wall(page)
            return []
        await page.evaluate(EXPAND_JS)
        await page.wait_for_timeout(500)
        await self._check_wall(page)
        return listing_from(await page.evaluate(READ_LISTING_JS)).reviews
