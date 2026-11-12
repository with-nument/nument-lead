"""Deep research, night part: crawl each queued business's own website and keep the evidence (Step 9).

For every business queued in the last day (best first, 6 hosts at a time, pages of one host one after another):
1. Homepage over https (http once on a TLS error); robots.txt decides, a disallowed homepage stops the crawl.
2. Up to 7 more pages chosen from the homepage links (team, contact, careers, locations, pricing, booking,
   about), the sitemap when the links give fewer than 3; Chromium only for JavaScript shells, or for every page
   when verification asked for it (`extra.force_browser`, set when most quotes failed: the text was incomplete).
3. Pages are stored (visible text, 20,000 characters at most) with code facts taken from the business's own
   pages only: JSON-LD data, the tech stack, careers and locations URLs, the contact form, and published contact
   routes (`tel:` and WhatsApp links as `tel_link`, JSON-LD telephone as `jsonld_phone`, `mailto:` links as
   `mailto_link`, each with the page URL and the raw link as the quote).
4. A JobPosting for a front-desk or builder role becomes a hiring signal (classified like any job post).
5. Practo profile for clinics in India, when that source is switched on: the confirmed profile page is stored
   (never as contacts), code writes its rating, stories, doctors, fees and claim as facts, and recent patient
   stories that complain about the front desk become a `review_pain` signal. Practo has its own 5 second pace,
   so its lookups wait outside the crawl slots.

Fact models: contact routes read by verification are `model = 'code'`; the other code facts keep the A.13.2
label `model = 'rule'`. Both mean "made by code" and are stored as verified.

Nothing here decides whether a lead is good. The morning run collects the AI extraction and verifies it.
`pagespeed()` is the morning part of Step 9.9.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb
from selectolax.lexbor import LexborHTMLParser

from .. import db
from ..http import FetchResult, NeverFetch, PoliteClient, SourceBlocked, host_of
from ..logging import get_logger
from ..normalize import canonical_url, homepage, is_ignored_host, phone, web_domain
from ..research import pages as pagelib
from ..research import quality, structured, techstack
from ..research.browser import Browser
from ..research.text import main_text_length, page_text
from ..segments import Segment
from ..sources import health, review_pain
from ..sources import practo as practolib
from ..sources.base import AIRouter, Signal, SourceContext
from ..sources.jobs import JobPost, classify_job, parse_date, role_from_keywords
from ..sources.practo import PractoAdapter, PractoMatch
from .runs import RunContext
from .selection import active_segments
from .signals import SignalSink

log = get_logger()

CONCURRENCY = 6  # hosts in parallel (Step 18.1.3)
HOST_GAP_S = 2.0
PAGE_MAX_BYTES = 3_000_000
BROWSER_DEFAULT = 40
JS_SHELL_TEXT = 400
JS_SHELL_MARKERS = ('id="root"', "id='root'", 'id="__next"', 'id="app"', "enable javascript", "you need to enable")
RECRAWL_AFTER = timedelta(hours=20)
JOB_MAX_AGE_DAYS = 30
PAGESPEED_PARALLEL = 4
PAGESPEED_RECHECK_DAYS = 60

CODE = "code"  # published contact routes, the label verification asked for
RULE = "rule"  # other code facts (A.13.2)
CONTACT_FIELDS = ("tel_link", "jsonld_phone", "mailto_link", "jsonld_email")
# Code facts this stage owns. They are replaced on every crawl; facts from AI or other steps are untouched.
RESEARCH_FIELDS = (
    *CONTACT_FIELDS,
    "jsonld_name",
    "jsonld_price_range",
    "jsonld_employees",
    "jsonld_job",
    "tech_stack",
    "careers_url",
    "locations_url",
    "contact_form_url",
)


@dataclass
class PageOut:
    kind: str
    url: str
    status: int | None
    html: str = ""
    render_mode: str = "http"
    robots_allowed: bool = True

    @property
    def canonical(self) -> str:
        return canonical_url(self.url)


@dataclass
class Crawl:
    business_id: str
    home: str
    state: str = "ok"  # ok | robots_disallowed | blocked | broken | unknown | ignored_host | no_website
    reason: str = ""
    final_url: str | None = None
    pages: list[PageOut] = field(default_factory=list)
    tel: list[tuple[str, str]] = field(default_factory=list)  # (raw number, page url)
    whatsapp: list[tuple[str, str]] = field(default_factory=list)
    mailto: list[tuple[str, str]] = field(default_factory=list)
    browser_used: int = 0
    forced_browser: bool = False
    practo: PractoMatch | None = None


@dataclass
class Loaded:
    """One page load, by HTTP or by the browser."""

    state: str  # ok | robots_skip | blocked | broken | unknown
    url: str
    final_url: str
    status: int | None = None
    html: str = ""
    mode: str = "http"
    reason: str = ""


def looks_like_js_shell(html: str, links: int, url: str) -> bool:
    """Step 9.5: little main text and an empty app root, or almost no links."""
    if main_text_length(html, url) >= JS_SHELL_TEXT:
        return False
    low = html[:200_000].lower()
    return links < 3 or any(m in low for m in JS_SHELL_MARKERS)


def contact_form(html: str) -> bool:
    """A form that asks for a phone, an email or a message (a contact route, Step 11.5)."""
    tree = LexborHTMLParser(html)
    for form in tree.css("form"):
        fields = " ".join(
            f"{n.attributes.get('type') or ''} {n.attributes.get('name') or ''} {n.tag}"
            for n in form.css("input, textarea")
        ).lower()
        asks_contact = "textarea" in fields or any(k in fields for k in ("tel", "phone", "email", "mobile"))
        if asks_contact and "search" not in (form.attributes.get("role") or "") and "password" not in fields:
            return True
    return False


# ---------------------------------------------------------------------------------------------------
# Crawling
# ---------------------------------------------------------------------------------------------------


class Crawler:
    def __init__(self, ctx: SourceContext, http: PoliteClient, browser: Browser) -> None:
        self.ctx = ctx
        self.http = http
        self.browser = browser

    async def _http(self, url: str) -> FetchResult:
        return await self.http.get(url, max_bytes=PAGE_MAX_BYTES, retries=1)

    async def _browser(self, url: str) -> Loaded | None:
        """Load a page with the browser after the HTTP client applied every rule. None: no browser left."""
        skip = await self.http.reserve(url)
        if skip:
            return Loaded("robots_skip", url, url, reason=skip)
        rendered = await self.browser.render(url)
        if rendered.state == "blocked":
            self.http.mark_blocked(url, "bot check seen by the browser")
            raise SourceBlocked("research", host_of(url), "bot check seen by the browser", rendered.status)
        if rendered.state != "ok" or rendered.html is None:
            return None
        self.ctx.add("research.browser_renders")
        return Loaded("ok", url, rendered.final_url or url, rendered.status, rendered.html, "browser")

    async def load(self, url: str, *, force_browser: bool = False, homepage_retry: bool = False) -> Loaded:
        """One page: the browser first when forced, else HTTP with the browser only for JavaScript shells."""
        if force_browser and self.browser.available():
            loaded = await self._browser(url)
            if loaded is not None:
                return loaded
        res = await self._http(url)
        if homepage_retry and res.reason == "TLS verification failed" and url.startswith("https://"):
            res = await self._http("http://" + url.removeprefix("https://"))  # one http fallback (Step 9.4.1)
        if not res.ok:
            return Loaded(res.state, url, res.final_url, res.status, reason=res.reason)
        out = Loaded("ok", url, res.final_url, res.status, res.text)
        if not force_browser and self.browser.available():
            links = len(pagelib.extract_links(res.text, res.final_url).pages)
            if looks_like_js_shell(res.text, links, res.final_url):
                rendered = await self._browser(res.final_url)  # waits the host's turn again before loading
                if rendered is not None and rendered.state == "ok":
                    out.html, out.mode = rendered.html, "browser"
        return out

    async def crawl(self, business: dict[str, Any]) -> Crawl:
        home = homepage(business.get("website"))
        crawl = Crawl(business["id"], home or "")
        crawl.forced_browser = bool((business.get("extra") or {}).get("force_browser"))
        if not home:
            crawl.state = "no_website"
            return crawl
        try:
            first = await self.load(home, force_browser=crawl.forced_browser, homepage_retry=True)
        except SourceBlocked as err:
            crawl.state, crawl.reason = "blocked", err.reason
            return crawl
        except NeverFetch:
            crawl.state, crawl.reason = "ignored_host", "redirects to a never-fetch host"
            return crawl
        crawl.final_url = first.final_url
        if first.state == "robots_skip":
            crawl.state, crawl.reason = "robots_disallowed", first.reason
            crawl.pages.append(PageOut("home", home, None, robots_allowed=False))
            return crawl
        if first.state != "ok":
            crawl.state, crawl.reason = first.state, first.reason
            crawl.pages.append(PageOut("home", home, first.status))
            return crawl
        if is_ignored_host(first.final_url):
            crawl.state = "ignored_host"
            crawl.reason = f"homepage redirects to {web_domain(first.final_url) or 'a directory'}"
            return crawl
        self._add(crawl, PageOut("home", first.final_url, first.status, first.html, first.mode))
        links = pagelib.extract_links(first.html, first.final_url)
        chosen = pagelib.choose_pages(first.final_url, links.pages)
        if len(chosen) - 1 < 3:
            chosen = pagelib.choose_pages(first.final_url, links.pages + await self.sitemap_links(first.final_url))
        for kind, url in chosen.items():
            if kind == "home":
                continue
            try:
                page = await self.load(url, force_browser=crawl.forced_browser)
            except SourceBlocked as err:
                crawl.reason = f"blocked on {kind}: {err.reason}"
                break
            except NeverFetch:
                continue
            if page.state == "robots_skip":
                crawl.pages.append(PageOut(kind, url, None, robots_allowed=False))
                continue
            if page.state != "ok":
                self.ctx.add(f"research.page_{page.state}")
                continue
            self._add(crawl, PageOut(kind, page.final_url, page.status, page.html, page.mode))
        return crawl

    @staticmethod
    def _add(crawl: Crawl, page: PageOut) -> None:
        """Keep a page and the contact routes printed on it (only pages of the business's own site get here)."""
        crawl.pages.append(page)
        crawl.browser_used += page.render_mode == "browser"
        links = pagelib.extract_links(page.html, page.url)
        for target, values in ((crawl.tel, links.tel), (crawl.whatsapp, links.whatsapp), (crawl.mailto, links.mailto)):
            known = {v for v, _ in target}
            target.extend((v, page.url) for v in values if v not in known)

    async def sitemap_links(self, home: str) -> list[tuple[str, str]]:
        """Up to 500 same-site URLs from /sitemap.xml and one level of nested sitemaps (Step 9.4.3)."""
        base = homepage(home) or home
        try:
            res = await self.http.get(base.rstrip("/") + "/sitemap.xml", max_bytes=2_000_000)
        except (SourceBlocked, NeverFetch):
            return []
        if not res.ok:
            return []
        urls = pagelib.sitemap_locs(res.text)
        if pagelib.is_sitemap_index(res.text):
            nested: list[str] = []
            for child in urls[:3]:
                try:
                    sub = await self.http.get(child, max_bytes=2_000_000)
                except (SourceBlocked, NeverFetch):
                    break
                if sub.ok:
                    nested += pagelib.sitemap_locs(sub.text)
                if len(nested) >= pagelib.SITEMAP_MAX_URLS:
                    break
            urls = nested
        return [(u, "") for u in urls[: pagelib.SITEMAP_MAX_URLS] if pagelib.same_site(u, home)]


# ---------------------------------------------------------------------------------------------------
# Code facts and storage
# ---------------------------------------------------------------------------------------------------


@dataclass
class FactRow:
    field: str
    value: Any
    quote: str
    url: str
    model: str = RULE


def code_facts(crawl: Crawl, seg: Segment, web_dom: str | None) -> list[FactRow]:
    """Facts made by code from the crawl, from pages of the business's own site only."""
    region = seg.country.upper()
    home = crawl.final_url or crawl.home
    out: list[FactRow] = []
    seen: set[tuple[str, str]] = set()

    def add(row: FactRow) -> None:
        key = (row.field, str(sorted(row.value.items())) if isinstance(row.value, dict) else str(row.value))
        if key not in seen:
            seen.add(key)
            out.append(row)

    own = [p for p in crawl.pages if p.html and home and pagelib.same_site(p.url, home)]
    for page in own:
        for fact in structured.facts_from_html(page.html, page.url, region):
            model = CODE if fact.field in CONTACT_FIELDS else RULE
            add(FactRow(fact.field, fact.value, fact.quote, fact.url, model))
        if page.kind in ("careers", "locations"):
            add(FactRow(f"{page.kind}_url", {"url": page.url}, page.url, page.url))
        if page.kind in ("contact", "booking", "home") and contact_form(page.html):
            add(FactRow("contact_form_url", {"url": page.url}, f"contact form on {page.url}", page.url))
    if own:
        tools = techstack.detect((p.url, p.html) for p in own)
        quote = tools[0]["snippet"] if tools else "no booking, chat, WhatsApp or CRM tool found"
        add(FactRow("tech_stack", techstack.tech_value(tools, web_dom), quote, tools[0]["page_url"] if tools else home))
    for raw, url in crawl.tel:
        parsed = phone(raw, region)
        if parsed:
            value = {"number": raw, "e164": parsed[0], "kind": parsed[1], "via": "tel", "label": "tel link"}
            add(FactRow("tel_link", value, f"tel:{raw}", url, CODE))
    for raw, url in crawl.whatsapp:
        parsed = phone(raw if raw.startswith("+") else "+" + raw, region)
        if parsed:
            value = {"number": raw, "e164": parsed[0], "kind": parsed[1], "via": "whatsapp", "label": "WhatsApp link"}
            add(FactRow("tel_link", value, f"wa.me/{raw.lstrip('+')}", url, CODE))
    for email, url in crawl.mailto:
        add(FactRow("mailto_link", {"email": email}, f"mailto:{email}", url, CODE))
    return out


def save_crawl(crawl: Crawl, seg: Segment, business: dict[str, Any], conn: Connection[Any]) -> dict[str, str]:
    """Store pages and code facts for one business in the caller's transaction. Returns {canonical url: id}."""
    page_ids: dict[str, str] = {}
    with conn.cursor() as cur:
        for page in crawl.pages:
            text, title = page_text(page.html, page.url) if page.html else ("", None)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
            cur.execute(
                """insert into public.pages (business_id, url, fetched_at, http_status, render_mode, title, text,
                                             text_hash, robots_allowed)
                   values (%s, %s, now(), %s, %s, %s, %s, %s, %s)
                   on conflict (url) do update set fetched_at = excluded.fetched_at,
                     http_status = excluded.http_status, render_mode = excluded.render_mode,
                     title = coalesce(excluded.title, pages.title),
                     text = coalesce(excluded.text, pages.text),
                     text_hash = coalesce(excluded.text_hash, pages.text_hash),
                     robots_allowed = excluded.robots_allowed
                   where pages.business_id is null or pages.business_id = excluded.business_id
                   returning id""",
                [
                    crawl.business_id,
                    page.canonical,
                    page.status,
                    page.render_mode,
                    title,
                    text or None,
                    digest,
                    page.robots_allowed,
                ],
            )
            row = cur.fetchone()
            if row is not None:
                page_ids[page.canonical] = str(row["id"] if isinstance(row, dict) else row[0])
        cur.execute(
            "delete from public.facts where business_id = %s and model in ('rule', 'code') and field = any(%s)",
            [crawl.business_id, list(RESEARCH_FIELDS)],
        )
        rows = [
            [
                crawl.business_id,
                f.field,
                Jsonb(f.value),
                f.quote[:300],
                f.url,
                page_ids.get(canonical_url(f.url)),
                f.model,
            ]
            for f in code_facts(crawl, seg, business.get("web_domain"))
        ]
        if rows:
            cur.executemany(
                """insert into public.facts (business_id, field, value, quote, url, page_id, model, verified,
                                             verify_score, verified_at)
                   values (%s, %s, %s, %s, %s, %s, %s, true, 100, now())""",
                rows,
            )
        if crawl.practo is not None:
            prof = crawl.practo.page
            cur.execute(
                "delete from public.facts where business_id = %s and model = 'rule' and url like %s",
                [crawl.business_id, f"{practolib.BASE}/%"],
            )
            cur.executemany(
                """insert into public.facts (business_id, field, value, quote, url, page_id, model, verified,
                                             verify_score, verified_at)
                   values (%s, %s, %s, %s, %s, %s, %s, true, 100, now())""",
                [
                    [
                        crawl.business_id,
                        name,
                        Jsonb(value),
                        quote[:300],
                        prof.url,
                        page_ids.get(canonical_url(crawl.practo.result.final_url)),
                        RULE,
                    ]
                    for name, value, quote in practolib.facts(prof)
                ],
            )
            practo_info = {
                "at": datetime.now(UTC).isoformat(),
                "url": prof.url,
                "how": crawl.practo.how,
                "rating": prof.rating,
                "stories": prof.stories,
                "recent_stories": len(review_pain.recent(crawl.practo.stories)),
            }
            cur.execute(
                "update public.businesses set extra = jsonb_set(extra, '{practo}', %s) where id = %s",
                [Jsonb(practo_info), crawl.business_id],
            )
        crawl_info = {
            "at": datetime.now(UTC).isoformat(),
            "state": crawl.state,
            "reason": crawl.reason[:200],
            "final_url": crawl.final_url,
            "pages": {p.kind: p.canonical for p in crawl.pages if p.html},
            "browser": crawl.browser_used,
            "forced_browser": crawl.forced_browser,
        }
        # The browser request from verification is answered by this crawl: clear it (one forced crawl only).
        cur.execute(
            "update public.businesses set extra = jsonb_set(extra - 'force_browser', '{crawl}', %s) where id = %s",
            [Jsonb(crawl_info), crawl.business_id],
        )
    return page_ids


def job_signals(crawl: Crawl, seg: Segment, segments: dict[str, Segment], ctx: SourceContext) -> list[Signal]:
    """JobPosting data on the business's own site: a recent front-desk or builder role is a hiring signal."""
    out: list[Signal] = []
    now = datetime.now(UTC)
    home = crawl.final_url or crawl.home
    for page in crawl.pages:
        if not page.html or not (home and pagelib.same_site(page.url, home)):
            continue
        for fact in structured.facts_from_html(page.html, page.url, seg.country.upper()):
            if fact.field != "jsonld_job":
                continue
            title = str(fact.value.get("title") or "")
            if role_from_keywords(title, seg) is None:
                continue
            posted = parse_date(fact.value.get("date_posted"))
            if posted is None or posted < now - timedelta(days=JOB_MAX_AGE_DAYS):
                continue
            post = JobPost(
                source="careers_watch",
                job_id=f"{crawl.business_id}:{hashlib.sha1(title.encode()).hexdigest()[:10]}",
                url=page.url,
                title=title,
                employer=fact.value.get("hiring_organization"),
                description=page_text(page.html, page.url)[0][:1500],
                posted_at=posted,
                valid_through=parse_date(fact.value.get("valid_through")),
            )
            sig = classify_job(ctx, post, segments, country=seg.country, default_segment=seg)
            if sig is not None:
                sig.business_id = crawl.business_id
                sig.segment_id = seg.id
                out.append(sig)
    return out


# ---------------------------------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------------------------------

QUEUE_SQL = """
select id::text as id, segment_id, name, website, web_domain, city, locality, address, lat, lng, place_id, extra
from public.businesses
where status = 'queued' and queued_at > now() - interval '1 day' and segment_id = any(%(segments)s)
  and (coalesce((extra #>> '{crawl,at}')::timestamptz, 'epoch') < %(recrawl)s or extra ? 'force_browser')
order by (extra ? 'force_browser') desc, queue_priority desc nulls last
limit %(limit)s
"""


async def research_all(
    ctx: SourceContext,
    segments: dict[str, Segment],
    queue: list[dict[str, Any]],
    time_left: Callable[[], float] | None = None,
) -> Counter[str]:
    """Crawl the queue. Once the run's deadline passes, no new business is started (the rest wait a night)."""
    stats: Counter[str] = Counter()
    browser = Browser(health.setting_int("research.browser_pages_per_run", BROWSER_DEFAULT))
    sink = SignalSink(segments, ctx)
    practo = PractoAdapter(ctx, time_left=time_left)
    practo_on = practo.enabled() and "clinics-in" in segments
    sem = asyncio.Semaphore(CONCURRENCY)
    try:
        async with PoliteClient("research", policy="public", min_gap_s=HOST_GAP_S, max_bytes=PAGE_MAX_BYTES) as http:
            crawler = Crawler(ctx, http, browser)

            async def one(b: dict[str, Any]) -> None:
                seg = segments[b["segment_id"]]
                async with sem:
                    if time_left is not None and time_left() <= 0:
                        stats["deadline_skipped"] += 1
                        return
                    crawl = await crawler.crawl(b)
                # Outside the crawl slots: Practo's own 5 second pace must not hold up other sites.
                if practo_on and seg.id == "clinics-in" and (time_left is None or time_left() > 0):
                    crawl.practo = await practo.safe_call(practo.match, b, seg)
                    if crawl.practo is not None:
                        crawl.pages.append(
                            PageOut(
                                "practo",
                                crawl.practo.result.final_url,
                                crawl.practo.result.status,
                                crawl.practo.result.text,
                            )
                        )
                        stats["practo_matched"] += 1
                stats[f"crawl_{crawl.state}"] += 1
                stats["pages"] += sum(1 for p in crawl.pages if p.html)
                stats["forced_browser"] += crawl.forced_browser
                if not ctx.dry_run:
                    with db.tx() as conn:
                        save_crawl(crawl, seg, b, conn)
                for sig in job_signals(crawl, seg, segments, ctx):
                    sink.add(sig, seg)
                if crawl.practo is not None:
                    pain = review_pain.classify(
                        ctx, crawl.practo.stories, business_name=str(b["name"]), source="practo"
                    )
                    if pain is not None:
                        sig = review_pain.pain_signal(
                            pain, source="practo", business_id=crawl.business_id, url=crawl.practo.page.url, seg=seg
                        )
                        sink.add(sig, seg)
                        stats["practo_review_pain"] += 1

            results = await asyncio.gather(*(one(b) for b in queue), return_exceptions=True)
            for res in results:
                if isinstance(res, BaseException):
                    stats["errors"] += 1
                    log.error("research.business_failed", error=f"{type(res).__name__}: {str(res)[:300]}")
    finally:
        await browser.aclose()
        await practo.aclose()
    signal_counts = sink.flush()
    stats["hiring_signals"] = sum(
        n for counts in signal_counts.values() for k, n in counts.items() if k.startswith("hiring")
    )
    return stats


def run(rc: RunContext, *, router: AIRouter | None = None) -> dict[str, Any]:
    """Crawl queued businesses politely and store their pages and code facts."""
    ctx = SourceContext.from_run(rc, router)
    segments = active_segments(rc.opts.segments)
    research_cap = health.setting_int("research_per_day", 300)
    queue = db.fetch_all(
        QUEUE_SQL,
        {
            "segments": list(segments),
            "recrawl": datetime.now(UTC) - RECRAWL_AFTER,
            "limit": min(rc.opts.limit or research_cap, research_cap),
        },
    )
    stats: dict[str, Any] = dict(asyncio.run(research_all(ctx, segments, queue, getattr(rc, "time_left", None))))
    stats["queued"] = len(queue)
    stats.update({k: v for k, v in ctx.stats.items() if k not in stats})
    rc.stats["research"] = stats
    log.info("research.done", businesses=len(queue))
    return stats


# ---------------------------------------------------------------------------------------------------
# Morning: PageSpeed for the best businesses (Step 9.9)
# ---------------------------------------------------------------------------------------------------

PAGESPEED_SQL = """
select b.id::text as id, b.segment_id, b.website, b.web_domain
from public.businesses b
where b.website is not null and b.segment_id = any(%(segments)s)
  and (b.status = 'qualified'
       or exists (select 1 from public.scores s where s.business_id = b.id and s.grade in ('A', 'B')
                  and s.computed_at > now() - interval '2 days'))
  and not exists (select 1 from public.facts f where f.business_id = b.id and f.field = 'site_speed_mobile'
                  and f.created_at > now() - make_interval(days => %(days)s))
order by b.queue_priority desc nulls last
limit %(limit)s
"""


async def _pagespeed_all(ctx: SourceContext, rows: list[dict[str, Any]], segments: dict[str, Segment]) -> Counter[str]:
    stats: Counter[str] = Counter()
    key = quality.api_key()
    sem = asyncio.Semaphore(PAGESPEED_PARALLEL)
    sink = SignalSink(segments, ctx)
    async with PoliteClient("pagespeed", policy="official_api", min_gap_s=0.0, timeout=quality.TIMEOUT) as client:

        async def one(row: dict[str, Any]) -> None:
            async with sem:
                if stats["quota"]:
                    return
                score, problem = await quality.mobile_score(client, row["website"], key)
            ctx.budget.record_pagespeed()
            if score is None:
                stats["quota" if problem == "quota" else "failed"] += 1
                return
            stats["scored"] += 1
            if not ctx.dry_run:
                with db.tx() as conn:
                    conn.execute(
                        "delete from public.facts where business_id = %s and field = 'site_speed_mobile' "
                        "and model in ('rule', 'code')",
                        [row["id"]],
                    )
                    conn.execute(
                        """insert into public.facts (business_id, field, value, quote, url, model, verified,
                                                     verify_score, verified_at)
                           values (%s, 'site_speed_mobile', %s, %s, %s, 'rule', true, 100, now())""",
                        [row["id"], Jsonb(score), f"PageSpeed mobile {score}", row["website"]],
                    )
            if score < quality.SLOW_SITE_BELOW:
                sink.add(
                    Signal(
                        type="slow_site",
                        source="pagespeed",
                        observed_at=datetime.now(UTC),
                        url=row["website"],
                        quote=f"PageSpeed mobile score {score}",
                        evidence_key=f"{row['web_domain']}|{datetime.now(UTC):%Y-%m}",
                        business_id=row["id"],
                        details={"score": score},
                    ),
                    segments[row["segment_id"]],
                )
                stats["slow_site"] += 1

        await asyncio.gather(*(one(r) for r in rows))
    sink.flush()
    return stats


def pagespeed(rc: RunContext) -> dict[str, Any]:
    """Morning: mobile speed for businesses graded B or better (about 100 a day). Needs the Google key."""
    if not quality.api_key():
        stats: dict[str, Any] = {"skipped": "GOOGLE_MAPS_API_KEY is not set: PageSpeed checks are skipped"}
        rc.stats["pagespeed"] = stats
        return stats
    ctx = SourceContext.from_run(rc)
    segments = active_segments(rc.opts.segments)
    cap = ctx.budget.pagespeed_quota_left()  # pagespeed_daily_cap and the API's free daily allowance
    rows = db.fetch_all(
        PAGESPEED_SQL,
        {"segments": list(segments), "days": PAGESPEED_RECHECK_DAYS, "limit": max(0, min(cap, rc.opts.limit or cap))},
    )
    stats = dict(asyncio.run(_pagespeed_all(ctx, rows, segments)))
    stats["candidates"] = len(rows)
    rc.stats["pagespeed"] = stats
    return stats
