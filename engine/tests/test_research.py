"""Deep research (Step 9.4 to 9.10): page choice, page text, structured data, tech detection, the crawl with its
rules (robots, blocks, forced browser) and what is stored."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.http import PoliteClient
from nument_engine.pipeline import research
from nument_engine.pipeline.research import Crawl, Crawler, PageOut, code_facts, contact_form, save_crawl
from nument_engine.research import pages as pagelib
from nument_engine.research import structured, techstack
from nument_engine.research.browser import Rendered, blocked_request
from nument_engine.research.text import page_text, visible_lines

from .sources_helpers import FakeRouter, clean_db, ctx, insert_business, mock_transport, no_network, segment

__all__ = ["clean_db", "no_network"]

SEG = segment()
SITE = "https://lotusskin-nlead.in"
JSONLD = {
    "@context": "https://schema.org",
    "@graph": [
        {
            "@type": ["MedicalClinic", "LocalBusiness"],
            "name": "Lotus Skin & Hair Clinic",
            "telephone": "+91 98765 43210",
            "email": "care@lotusskin-nlead.in",
            "priceRange": "₹₹",
            "numberOfEmployees": {"@type": "QuantitativeValue", "value": 12},
        }
    ],
}
NAV = (
    '<header><nav><a href="/">Home</a> <a href="/about-us/">About Us</a> <a href="/our-doctors">Our Doctors</a> '
    '<a href="/contact-us">Contact</a> <a href="/careers">Careers</a> <a href="/treatments">Treatments</a> '
    '<a href="/book-appointment">Book appointment</a> <a href="https://www.instagram.com/lotus">Instagram</a> '
    '<a href="/blog/page/2">Older posts</a> <a href="/brochure.pdf">Brochure</a></nav>'
    '<p>Call <a href="tel:+919876543210">+91 98765 43210</a> or '
    '<a href="https://wa.me/919876543211">WhatsApp us</a></p></header>'
)
FOOTER = "<footer><p>Office 2, Baner Road, Pune 411045</p><p>© 2026 Lotus Skin. All rights reserved.</p></footer>"


def page(body: str, title: str = "Lotus Skin & Hair Clinic", head: str = "") -> str:
    return f"<html><head><title>{title}</title>{head}</head><body>{NAV}<main>{body}</main>{FOOTER}</body></html>"


HOME = page(
    "<h1>Skin and hair care in Baner</h1>" + "<p>We treat acne, pigmentation and hair loss for 15 years.</p>" * 8,
    head=f'<script type="application/ld+json">{json.dumps(JSONLD)}</script>'
    '<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC123"></script>'
    "<script>fbq('init', '1234567890');</script>",
)
CONTACT = page(
    "<h1>Contact us</h1><p>Email <a href='mailto:care@lotusskin-nlead.in'>care@lotusskin-nlead.in</a></p>"
    "<form><input type='text' name='name'><input type='tel' name='phone'><textarea name='message'></textarea></form>"
)
CAREERS = page(
    "<h1>Careers</h1><p>Front Desk Executive: answer patient calls and book appointments.</p>",
    head='<script type="application/ld+json">'
    + json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Front Desk Executive",
            "datePosted": (datetime.now(UTC) - timedelta(days=3)).date().isoformat(),
            "hiringOrganization": {"@type": "Organization", "name": "Lotus Skin & Hair Clinic"},
        }
    )
    + "</script>",
)


def site_routes(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    routes: dict[str, Any] = {
        f"{SITE}/robots.txt": (200, "User-agent: *\nDisallow: /book-appointment\n"),
        f"{SITE}/": (200, HOME),
        f"{SITE}/about-us/": (200, page("<h1>About</h1><p>Founded by Dr. Asha Rao, dermatologist.</p>")),
        f"{SITE}/our-doctors": (200, page("<h1>Our doctors</h1><p>Dr. Asha Rao, Founder and Medical Director</p>")),
        f"{SITE}/contact-us": (200, CONTACT),
        f"{SITE}/careers": (200, CAREERS),
        f"{SITE}/treatments": (200, page("<h1>Treatments</h1><p>Laser hair removal from ₹25,000</p>")),
    }
    routes.update(extra or {})
    return routes


class FakeBrowser:
    def __init__(self, html: str | None = None, state: str = "ok", cap: int = 40) -> None:
        self.html, self.state, self.cap, self.renders = html, state, cap, 0
        self.urls: list[str] = []

    def available(self) -> bool:
        return self.renders < self.cap

    async def render(self, url: str) -> Rendered:
        self.renders += 1
        self.urls.append(url)
        return Rendered(self.state, self.html, 200, url)

    async def aclose(self) -> None:
        return None


async def crawl_with(
    routes: dict[str, Any], business: dict[str, Any], browser: Any = None
) -> tuple[Crawl, list[httpx.Request]]:
    transport, seen = mock_transport(routes)
    async with PoliteClient("research", policy="public", min_gap_s=0.0, transport=transport) as http:
        crawler = Crawler(ctx(), http, browser or FakeBrowser(cap=0))
        crawl = await crawler.crawl(business)
    return crawl, seen


# ---- page choice and text -------------------------------------------------------------------------------


def test_links_contact_routes_and_page_choice() -> None:
    links = pagelib.extract_links(HOME, f"{SITE}/")
    assert links.tel == ["+919876543210"] and links.whatsapp == ["919876543211"]
    urls = [u for u, _ in links.pages]
    assert not any("instagram.com" in u for u in urls)  # other sites are not followed
    chosen = pagelib.choose_pages(f"{SITE}/", links.pages)
    assert chosen == {
        "home": f"{SITE}/",
        "team": f"{SITE}/our-doctors",
        "contact": f"{SITE}/contact-us",
        "careers": f"{SITE}/careers",
        "pricing": f"{SITE}/treatments",
        "booking": f"{SITE}/book-appointment",
        "about": f"{SITE}/about-us/",
    }


@pytest.mark.parametrize(
    ("links", "group"),
    [
        ([("https://a.in/team", "Meet the team")], "team"),
        ([("https://a.in/reach-us", "")], "contact"),
        ([("https://a.in/join-us", "")], "careers"),
        ([("https://a.in/our-clinics", "Branches")], "locations"),
        ([("https://a.in/fees", "Fee structure")], "pricing"),
        ([("https://a.in/x", "Book now")], "booking"),
        ([("https://a.in/من-نحن", "من نحن")], "about"),
        ([("https://a.in/فروعنا", "فروعنا")], "locations"),
    ],
)
def test_groups(links: list[tuple[str, str]], group: str) -> None:
    assert group in pagelib.choose_pages("https://a.in/", links)


def test_a_treatment_page_is_not_a_booking_page() -> None:
    """Seen live: /cerec-single-visit-crowns/ was picked as the booking page because of the word "visit"."""
    chosen = pagelib.choose_pages("https://a.in/", [("https://a.in/cerec-single-visit-crowns/", "Single visit crowns")])
    assert "booking" not in chosen
    assert (
        pagelib.choose_pages("https://a.in/", [("https://a.in/visit-us", "Visit us")])["booking"]
        == "https://a.in/visit-us"
    )


def test_skip_patterns() -> None:
    chosen = pagelib.choose_pages(
        "https://a.in/",
        [("https://a.in/contact.pdf", "Contact"), ("https://a.in/cart", "Book"), ("https://a.in/login", "About")],
    )
    assert chosen == {"home": "https://a.in/"}


def test_page_text_keeps_header_and_footer_contacts() -> None:
    text, title = page_text(HOME, f"{SITE}/")
    assert title == "Lotus Skin & Hair Clinic"
    assert "Call +91 98765 43210 or WhatsApp us" in text  # header
    assert "Office 2, Baner Road, Pune 411045" in text  # footer
    assert "fbq(" not in text and "googletagmanager" not in text  # scripts removed


def test_very_long_pages_keep_contact_lines_first() -> None:
    html = "<html><body>" + "<p>filler line about skin care</p>" * 2000 + "<p>Call +91 98765 43210</p></body></html>"
    text, _ = page_text(html, "")
    assert len(text) <= 20_000 and "Call +91 98765 43210" in text


def test_visible_lines_split_blocks_and_join_inline_text() -> None:
    lines = visible_lines("<div><p>We are a team of <strong>5 doctors</strong>.</p><ul><li>A</li><li>B</li></ul></div>")
    assert lines == ["We are a team of 5 doctors.", "A", "B"]


# ---- structured data and tech ---------------------------------------------------------------------------


def test_structured_facts() -> None:
    facts = {f.field: f for f in structured.facts_from_html(HOME, f"{SITE}/", "IN")}
    assert facts["jsonld_phone"].value == {"phone": "+91 98765 43210", "e164": "+919876543210", "kind": "mobile"}
    assert facts["jsonld_email"].value == {"email": "care@lotusskin-nlead.in"}
    assert facts["jsonld_name"].value == {"name": "Lotus Skin & Hair Clinic"}
    assert facts["jsonld_employees"].value == {"employees": 12}
    assert facts["jsonld_price_range"].value == {"price_range": "₹₹"}
    assert '"telephone"' in facts["jsonld_phone"].quote
    job = structured.facts_from_html(CAREERS, f"{SITE}/careers", "IN")
    assert [f.field for f in job] == ["jsonld_job"] and job[0].value["title"] == "Front Desk Executive"


TECH_CASES = [
    ("Practo widget", '<script src="https://widget.practo.com/x.js"></script>'),
    ("Calendly", '<a href="https://calendly.com/lotus/consult">Book</a>'),
    ("Setmore", '<iframe src="https://lotus.setmore.com"></iframe>'),
    ("Zoho Bookings", '<a href="https://lotus.zohobookings.in">Book</a>'),
    ("Zoho SalesIQ", '<script src="https://salesiq.zoho.in/widget"></script>'),
    ("Tawk.to", '<script src="https://embed.tawk.to/123/default"></script>'),
    ("Intercom", '<script src="https://widget.intercom.io/widget/abc"></script>'),
    ("Freshchat", '<script src="https://wchat.freshchat.com/js/widget.js"></script>'),
    ("Wati", '<script src="https://wati-integration-service.wati.io/x.js"></script>'),
    ("Interakt", '<script src="https://app.interakt.ai/kiwi-sdk/kiwi-sdk.js"></script>'),
    ("Gallabox", '<a href="https://gallabox.com/x">chat</a>'),
    ("AiSensy", '<script src="https://cdn.aisensy.com/w.js"></script>'),
    ("WhatsApp link", '<a href="https://api.whatsapp.com/send?phone=919800000000">WhatsApp</a>'),
    ("Meta Pixel", "<script>!function(){};fbq('init', '123');</script>"),
    ("Google Ads tag", "<script>gtag('config', 'AW-123456789');</script>"),
    ("Google Analytics 4", '<script src="https://www.googletagmanager.com/gtag/js?id=G-XYZ"></script>'),
    ("Google Tag Manager", '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-1"></script>'),
    ("Sell.do", '<script src="https://forms.sell.do/x.js"></script>'),
    ("LeadSquared", '<script src="https://web.mxradon.com/leadsquared/x.js"></script>'),
    ("Meritto (NoPaperForms)", '<script src="https://widgets.nopaperforms.com/x.js"></script>'),
    ("WordPress", '<link href="/wp-content/themes/x/style.css">'),
    ("Wix", '<img src="https://static.wixstatic.com/media/x.png">'),
    ("Shopify", '<script src="https://cdn.shopify.com/s/x.js"></script>'),
    ("Webflow", '<html data-wf-site="123">'),
    ("Squarespace", '<link href="https://static1.squarespace.com/x.css">'),
    ("GoDaddy builder", '<img src="https://img1.wsimg.com/isteam/x.jpg">'),
    ("Next.js", '<script src="/_next/static/chunks/main.js"></script>'),
]


@pytest.mark.parametrize(("tool", "html"), TECH_CASES)
def test_every_tech_pattern(tool: str, html: str) -> None:
    found = techstack.detect([("https://a.in/", f"<html><head>{html}</head><body></body></html>")])
    assert tool in [t["tool"] for t in found]


def test_tech_flags() -> None:
    tools = techstack.detect([("https://a.in/", TECH_CASES[1][1] + TECH_CASES[12][1] + TECH_CASES[13][1])])
    value = techstack.tech_value(tools, "a.in")
    assert value["has_booking"] and value["has_whatsapp"] and value["runs_ads_tag"] and value["pays_for_software"]
    assert not value["has_chat"] and not value["free_builder"]
    assert techstack.flags([], "drx.wixsite.com")["free_builder"]


def test_contact_form_detection() -> None:
    assert contact_form(CONTACT)
    assert not contact_form("<form role='search'><input type='text' name='q'></form>")
    assert not contact_form("<form><input type='email' name='user'><input type='password' name='pw'></form>")


def test_the_browser_never_loads_social_widgets_or_media() -> None:
    assert blocked_request("https://platform.twitter.com/widgets.js", "script")
    assert blocked_request("https://connect.facebook.net/en_US/fbevents.js", "script")
    assert blocked_request("https://lotus.in/hero.jpg", "image")
    assert not blocked_request("https://lotus.in/app.js", "script")


# ---- the crawl -----------------------------------------------------------------------------------------


def business(**kw: Any) -> dict[str, Any]:
    return {
        "id": "b-research",
        "website": f"{SITE}/",
        "web_domain": "lotusskin-nlead.in",
        "name": "Lotus",
        "segment_id": "clinics-in",
        "extra": {},
        **kw,
    }


async def test_crawl_reads_the_chosen_pages_and_obeys_robots() -> None:
    crawl, seen = await crawl_with(site_routes(), business())
    kinds = {p.kind: p for p in crawl.pages}
    assert crawl.state == "ok" and set(kinds) == {"home", "team", "contact", "careers", "pricing", "booking", "about"}
    assert kinds["booking"].robots_allowed is False and kinds["booking"].html == ""  # disallowed, never fetched
    assert not any(r.url.path == "/book-appointment" for r in seen)
    assert ("+919876543210", f"{SITE}/") in crawl.tel and (
        "care@lotusskin-nlead.in",
        f"{SITE}/contact-us",
    ) in crawl.mailto


async def test_a_disallowed_homepage_stops_the_crawl() -> None:
    crawl, seen = await crawl_with({f"{SITE}/robots.txt": (200, "User-agent: *\nDisallow: /\n")}, business())
    assert crawl.state == "robots_disallowed" and crawl.pages[0].robots_allowed is False
    assert [r.url.path for r in seen] == ["/robots.txt"]


async def test_a_bot_check_stops_the_host() -> None:
    challenge = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
    crawl, _ = await crawl_with(site_routes({f"{SITE}/": (200, challenge)}), business())
    assert crawl.state == "blocked" and crawl.pages == []


async def test_a_directory_homepage_means_no_website() -> None:
    routes = site_routes(
        {
            f"{SITE}/": httpx.Response(301, headers={"location": "https://www.practo.com/pune/clinic/x"}),
            "https://www.practo.com/robots.txt": (200, "User-agent: *\nAllow: /\n"),
            "https://www.practo.com/pune/clinic/x": (200, page("Practo")),
        }
    )
    crawl, _ = await crawl_with(routes, business())
    assert crawl.state == "ignored_host"


async def test_sitemap_fills_in_when_links_are_few() -> None:
    bare = "<html><body><p>" + "Welcome to our clinic in Baner. " * 30 + "</p></body></html>"
    routes = {
        f"{SITE}/robots.txt": (404, ""),
        f"{SITE}/": (200, bare),
        f"{SITE}/sitemap.xml": (
            200,
            f"<urlset><url><loc>{SITE}/contact</loc></url><url><loc>{SITE}/team</loc></url>"
            f"<url><loc>{SITE}/careers</loc></url></urlset>",
        ),
        "*": (200, page("<p>sub page</p>")),
    }
    crawl, _ = await crawl_with(routes, business())
    assert {p.kind for p in crawl.pages} == {"home", "contact", "team", "careers"}


async def test_javascript_shells_are_rendered_once_in_the_browser() -> None:
    shell = (
        '<html><head><title>App</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
    )
    rendered = page("<h1>Rendered home</h1>" + "<p>Real content after JavaScript runs.</p>" * 20)
    browser = FakeBrowser(rendered)
    crawl, _ = await crawl_with(site_routes({f"{SITE}/": (200, shell)}), business(), browser)
    assert crawl.pages[0].render_mode == "browser" and "Rendered home" in crawl.pages[0].html
    assert browser.urls == [f"{SITE}/"]  # sub pages have real HTML: no more renders


async def test_force_browser_skips_plain_http_for_pages() -> None:
    """Verification asks for a browser crawl when quotes failed (extra.force_browser)."""
    browser = FakeBrowser(HOME)
    crawl, seen = await crawl_with(site_routes(), business(extra={"force_browser": True}), browser)
    assert crawl.forced_browser and crawl.state == "ok"
    assert all(p.render_mode == "browser" for p in crawl.pages if p.html)
    page_requests = [r for r in seen if r.url.path != "/robots.txt"]
    assert page_requests == []  # robots.txt only: the pages themselves came from the browser
    assert f"{SITE}/book-appointment" not in browser.urls  # robots.txt still decides


async def test_a_bot_check_in_the_browser_stops_the_host() -> None:
    crawl, _ = await crawl_with(site_routes(), business(extra={"force_browser": True}), FakeBrowser(None, "blocked"))
    assert crawl.state == "blocked"


# ---- facts and storage ---------------------------------------------------------------------------------


async def test_code_facts_come_from_own_pages_with_the_contract_names_and_models() -> None:
    crawl, _ = await crawl_with(site_routes(), business())
    crawl.pages.append(
        PageOut(
            "practo",
            "https://www.practo.com/pune/clinic/lotus",
            200,
            page(
                "<p>Doctors (5)</p>",
                head=f'<script type="application/ld+json">'
                f"{json.dumps({'@type': 'MedicalClinic', 'telephone': '+91 80000 00000'})}</script>",
            ),
        )
    )
    facts = code_facts(crawl, SEG, "lotusskin-nlead.in")
    by_field: dict[str, list[Any]] = {}
    for f in facts:
        by_field.setdefault(f.field, []).append(f)
    tel = {f.value["via"]: f for f in by_field["tel_link"]}
    assert tel["tel"].model == "code" and tel["tel"].quote == "tel:+919876543210" and tel["tel"].url == f"{SITE}/"
    assert tel["whatsapp"].value["e164"] == "+919876543211" and tel["whatsapp"].quote == "wa.me/919876543211"
    assert by_field["jsonld_phone"][0].model == "code"
    assert all("practo.com" not in f.url for f in facts)  # Practo's masked numbers are never a contact
    assert by_field["mailto_link"][0].value == {"email": "care@lotusskin-nlead.in"}
    assert by_field["careers_url"][0].value == {"url": f"{SITE}/careers"} and by_field["careers_url"][0].model == "rule"
    assert by_field["contact_form_url"][0].url == f"{SITE}/contact-us"
    tech = by_field["tech_stack"][0]
    assert tech.model == "rule" and tech.value["runs_ads_tag"] and tech.value["has_whatsapp"]
    assert "jsonld_job" in by_field


async def test_save_crawl_stores_pages_facts_and_clears_the_browser_request(clean_db: str) -> None:
    bid = insert_business(
        name="Lotus Research Clinic",
        website=f"{SITE}/",
        web_domain="lotusskin-nlead.in",
        status="queued",
        queued_at=datetime.now(UTC),
        extra={"force_browser": True},
    )
    crawl, _ = await crawl_with(site_routes(), business(id=bid))
    with db.tx() as conn:
        page_ids = save_crawl(crawl, SEG, {"web_domain": "lotusskin-nlead.in"}, conn)
    assert len(page_ids) == len([p for p in crawl.pages])
    pages = db.fetch_all("select url, text, robots_allowed from public.pages where business_id = %s", [bid])
    assert {p["url"] for p in pages} >= {f"{SITE}/", f"{SITE}/contact-us", f"{SITE}/book-appointment"}
    assert any("Baner Road" in (p["text"] or "") for p in pages)
    facts = db.fetch_all("select field, model, verified, page_id from public.facts where business_id = %s", [bid])
    assert {f["field"] for f in facts} >= {"tel_link", "jsonld_phone", "mailto_link", "tech_stack", "careers_url"}
    assert all(f["verified"] for f in facts) and all(f["page_id"] for f in facts if f["field"] == "tel_link")
    extra = db.scalar("select extra from public.businesses where id = %s", [bid])
    assert "force_browser" not in extra and extra["crawl"]["state"] == "ok"
    assert extra["crawl"]["pages"]["contact"] == f"{SITE}/contact-us"
    with db.tx() as conn:  # a second crawl replaces the code facts instead of adding to them
        save_crawl(crawl, SEG, {"web_domain": "lotusskin-nlead.in"}, conn)
    assert db.scalar("select count(*) from public.facts where business_id = %s", [bid]) == len(facts)


async def test_jsonld_jobs_become_hiring_signals() -> None:
    from nument_engine.models import SignalClassification

    crawl, _ = await crawl_with(site_routes(), business())
    verdict = SignalClassification(
        is_relevant=True,
        role_category="frontdesk",
        employer_name="Lotus",
        employer_website=None,
        employer_domain="clinics",
        city="Pune",
        evidence_quote="Front Desk Executive",
        confidence=0.9,
    )
    sigs = research.job_signals(crawl, SEG, {SEG.id: SEG}, ctx(FakeRouter({"classify_signal": [verdict]})))
    assert len(sigs) == 1 and sigs[0].type == "hiring_frontdesk" and sigs[0].business_id == "b-research"


def test_the_stage_crawls_the_queue(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from .sources_helpers import run_context

    bid = insert_business(
        name="Stage Research Clinic",
        website=f"{SITE}/",
        web_domain="lotusskin-nlead.in",
        status="queued",
        queued_at=datetime.now(UTC),
        queue_priority=50,
    )
    transport, _ = mock_transport(site_routes())
    real = PoliteClient.__init__

    def init(self: PoliteClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        kwargs["min_gap_s"] = 0.0
        real(self, *args, **kwargs)

    monkeypatch.setattr(PoliteClient, "__init__", init)
    monkeypatch.setattr(research, "Browser", lambda cap: FakeBrowser(cap=0))
    rc = run_context(segments=["clinics-in"])
    stats = research.run(rc)
    assert stats["queued"] >= 1 and stats["crawl_ok"] >= 1
    assert db.scalar("select count(*) from public.pages where business_id = %s", [bid]) >= 6
    again = research.run(run_context(segments=["clinics-in"]))
    assert again["queued"] == 0  # crawled in the last 20 hours: not again
