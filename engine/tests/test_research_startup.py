"""The deeper startup crawl (E2a, 15 Nov 2026): page choice up to `research.startup_max_pages`, the blog's latest
posts, GitHub and app-store links kept for the probes, and the `probe.tech` fact written during research."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.http import PoliteClient
from nument_engine.pipeline import research
from nument_engine.pipeline.research import Crawl, Crawler, save_crawl
from nument_engine.research import fingerprint
from nument_engine.research import pages as pagelib
from nument_engine.segments import load_segments, sync_segments_to_db

from .sources_helpers import clean_db, ctx, insert_business, mock_transport, no_network, run_context, segment

__all__ = ["clean_db", "no_network"]

SITE = "https://tallyhq-nlead.io"
HTML_DIR = Path(__file__).resolve().parent / "fixtures" / "e2a" / "html"
HOME_LINKS = [
    ("/about", "About"),
    ("/team", "Our team"),
    ("/careers", "Careers"),
    ("/pricing", "Pricing"),
    ("/press", "Press"),
    ("/blog", "Blog"),
    ("/contact", "Contact"),
    ("/privacy-policy", "Privacy policy"),
    ("/terms", "Terms of service"),
    ("/imprint", "Imprint"),
    ("/signup", "Sign up"),
    ("https://github.com/tallyhq-nlead", "GitHub"),
    ("https://apps.apple.com/us/app/tallyhq/id6447000001", "App Store"),
    ("https://play.google.com/store/apps/details?id=io.tallyhq.app&hl=en", "Google Play"),
    ("https://www.linkedin.com/company/tallyhq", "LinkedIn"),
]
BLOG = (
    "<html><head><title>Blog</title></head><body><h1>Blog</h1>"
    '<a href="/blog/launching-auto-reminders">Launching auto reminders</a>'
    '<a href="/blog/tag/product">Product</a><a href="/blog/category/news">News</a>'
    '<a href="/blog/we-raised-a-pre-seed">We raised a pre-seed</a><a href="/blog/page/2">Older</a>'
    '<a href="/blog/hello-world">Hello world</a><a href="/blog/fourth-post">Fourth</a>'
    '<a href="https://other-nlead.com/blog/x">Elsewhere</a></body></html>'
)


def home_html() -> str:
    links = "".join(f'<a href="{href}">{text}</a>' for href, text in HOME_LINKS)
    return (HTML_DIR / "webflow_home.html").read_text(encoding="utf-8").replace("</body>", f"<nav>{links}</nav></body>")


def page(title: str) -> str:
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{title} text for TallyHQ.</p></body></html>"
    )


def site_routes() -> dict[str, Any]:
    routes: dict[str, Any] = {
        f"{SITE}/robots.txt": (200, "User-agent: *\nDisallow: /signup\n"),
        f"{SITE}/": (200, home_html()),
        f"{SITE}/blog": (200, BLOG),
    }
    for path in ("about", "team", "careers", "pricing", "press", "contact", "privacy-policy", "terms", "imprint"):
        routes[f"{SITE}/{path}"] = (200, page(path.title()))
    for slug in ("launching-auto-reminders", "we-raised-a-pre-seed", "hello-world", "fourth-post"):
        routes[f"{SITE}/blog/{slug}"] = (200, page(slug))
    return routes


@pytest.fixture
def firms_in(clean_db: str) -> str:
    """The firms-in segment row (the test database seeds only some segments) for the businesses' foreign key."""
    with db.tx() as conn:
        sync_segments_to_db(conn, {k: v for k, v in load_segments().items() if k == "firms-in"})
    return clean_db


def business(**kw: Any) -> dict[str, Any]:
    return {
        "id": "b-startup",
        "website": f"{SITE}/",
        "web_domain": "tallyhq-nlead.io",
        "name": "TallyHQ",
        "segment_id": "firms-in",
        "extra": {},
        **kw,
    }


async def crawl_startup(
    routes: dict[str, Any], b: dict[str, Any], max_pages: int = 12
) -> tuple[Crawl, list[httpx.Request]]:
    from .test_research import FakeBrowser

    transport, seen = mock_transport(routes)
    async with PoliteClient("research", policy="public", min_gap_s=0.0, transport=transport) as http:
        crawl = await Crawler(ctx(), http, FakeBrowser(cap=0)).crawl(b, startup=True, max_pages=max_pages)
    return crawl, seen


# ---- page choice -----------------------------------------------------------------------------------------


def test_startup_segments_are_firms_with_a_signals_only_universe() -> None:
    assert pagelib.is_startup_segment(segment("firms-in"))
    assert not pagelib.is_startup_segment(segment("clinics-in"))
    assert not pagelib.is_startup_segment(segment("firms-in", universe="map"))


def test_a_startup_gets_the_legal_press_and_blog_pages_with_room_for_posts() -> None:
    links = pagelib.extract_links(home_html(), f"{SITE}/").pages
    chosen = pagelib.choose_pages(f"{SITE}/", links, 12, startup=True)
    assert list(chosen) == [
        "home", "about", "team", "careers", "pricing", "press", "blog", "contact", "privacy",
    ]  # fmt: skip
    assert len(chosen) == 12 - pagelib.BLOG_POSTS  # three slots stay free for the latest posts
    assert chosen["privacy"] == f"{SITE}/privacy-policy"
    roomy = pagelib.choose_pages(f"{SITE}/", links, 20, startup=True)
    assert {"terms", "imprint"} <= set(roomy)
    assert "signup" not in " ".join(roomy.values())  # sign-up pages are never read


def test_other_segments_keep_their_page_choice() -> None:
    links = pagelib.extract_links(home_html(), f"{SITE}/").pages
    chosen = pagelib.choose_pages(f"{SITE}/", links)
    assert not {"privacy", "terms", "imprint", "press", "blog"} & set(chosen)
    assert len(chosen) <= pagelib.MAX_PAGES


def test_blog_posts_are_the_first_posts_on_the_blog_page() -> None:
    posts = pagelib.blog_posts(BLOG, f"{SITE}/blog")
    assert posts == [
        f"{SITE}/blog/launching-auto-reminders",
        f"{SITE}/blog/we-raised-a-pre-seed",
        f"{SITE}/blog/hello-world",
    ]
    assert pagelib.blog_posts(BLOG, f"{SITE}/blog", exclude=[f"{SITE}/blog/hello-world"], limit=5)[-1].endswith(
        "fourth-post"
    )
    sub = '<a href="/my-first-post">Post</a><a href="https://tallyhq-nlead.io/pricing">Pricing</a>'
    assert pagelib.blog_posts(sub, "https://blog.tallyhq-nlead.io/") == ["https://blog.tallyhq-nlead.io/my-first-post"]


@pytest.mark.parametrize(
    ("url", "owner", "app_id", "package"),
    [
        ("https://github.com/tallyhq-nlead", "tallyhq-nlead", None, None),
        ("https://github.com/tallyhq-nlead/sdk-js/issues", "tallyhq-nlead", None, None),
        ("https://github.com/orgs/tallyhq-nlead/people", "tallyhq-nlead", None, None),
        ("https://github.com/sponsors/someone", None, None, None),
        ("https://github.com/features/actions", None, None, None),
        ("https://gist.github.com/someone/abc", None, None, None),
        ("https://apps.apple.com/in/app/tallyhq/id6447000001?platform=iphone", None, "6447000001", None),
        ("https://itunes.apple.com/us/app/id6447000001", None, "6447000001", None),
        ("https://apps.apple.com/us/developer/tallyhq/id1600000000", None, "1600000000", None),
        ("https://play.google.com/store/apps/details?id=io.tallyhq.app&hl=en", None, None, "io.tallyhq.app"),
        ("https://play.google.com/store/apps/dev?id=123", None, None, None),
    ],
)
def test_profile_links(url: str, owner: str | None, app_id: str | None, package: str | None) -> None:
    assert pagelib.github_owner(url) == owner
    assert pagelib.app_store_id(url) == app_id
    assert pagelib.play_package(url) == package


# ---- the crawl ---------------------------------------------------------------------------------------------


async def test_a_startup_crawl_reads_up_to_twelve_pages_with_the_latest_posts() -> None:
    crawl, seen = await crawl_startup(site_routes(), business())
    kinds = [p.kind for p in crawl.pages if p.html]
    assert kinds == [
        "home", "about", "team", "careers", "pricing", "press", "blog", "contact", "privacy",
        "blog_post_1", "blog_post_2", "blog_post_3",
    ]  # fmt: skip
    assert len(crawl.pages) <= 12
    hosts = {r.url.host for r in seen}
    assert hosts == {"tallyhq-nlead.io"}  # GitHub, the stores and LinkedIn are never fetched
    assert [u for u, _ in crawl.profiles] == [
        "https://github.com/tallyhq-nlead",
        "https://apps.apple.com/us/app/tallyhq/id6447000001",
        "https://play.google.com/store/apps/details?id=io.tallyhq.app&hl=en",
    ]
    assert research.profile_links(crawl.profiles) == {
        "github": ["tallyhq-nlead"],
        "app_store": ["6447000001"],
        "play_store": ["io.tallyhq.app"],
    }
    assert crawl.pages[0].headers.get("content-type", "").startswith("text/html")


async def test_the_page_budget_is_a_setting() -> None:
    crawl, _ = await crawl_startup(site_routes(), business(), max_pages=5)
    assert len([p for p in crawl.pages if p.html]) <= 5


async def test_a_non_startup_crawl_keeps_no_profiles() -> None:
    from .test_research import FakeBrowser

    transport, _ = mock_transport(site_routes())
    async with PoliteClient("research", policy="public", min_gap_s=0.0, transport=transport) as http:
        crawl = await Crawler(ctx(), http, FakeBrowser(cap=0)).crawl(business())
    assert crawl.profiles == [] and not crawl.startup
    assert len([p for p in crawl.pages if p.html]) <= pagelib.MAX_PAGES


async def test_the_fingerprint_runs_on_the_homepage_of_a_startup() -> None:
    crawl, _ = await crawl_startup(site_routes(), business())
    report = await research.tech_report(crawl, None)
    assert report is not None and report.no_code_platform == "webflow"
    blocked = Crawl("b", f"{SITE}/", state="blocked", startup=True)
    assert await research.tech_report(blocked, None) is None


async def test_save_crawl_writes_one_probe_tech_fact_and_the_profiles(firms_in: str) -> None:
    bid = insert_business(
        name="TallyHQ Research",
        segment_id="firms-in",
        website=f"{SITE}/",
        web_domain="tallyhq-nlead.io",
        status="queued",
        queued_at=datetime.now(UTC),
    )
    crawl, _ = await crawl_startup(site_routes(), business(id=bid))
    crawl.tech = await research.tech_report(crawl, None)
    for _ in range(2):  # a second crawl replaces the fact instead of adding one
        with db.tx() as conn:
            page_ids = save_crawl(crawl, segment("firms-in"), {"web_domain": "tallyhq-nlead.io"}, conn)
    rows = db.fetch_all(
        "select value, quote, url, page_id::text as page_id, model, verified, verified_at from public.facts "
        "where business_id = %s and field = 'probe.tech'",
        [bid],
    )
    assert len(rows) == 1
    fact = rows[0]
    assert set(fact["value"]) == {"technologies", "no_code_platform", "ai_vendors"}
    assert fact["value"]["no_code_platform"] == "webflow"
    assert fact["model"] == "rule" and fact["verified"] and fact["verified_at"] is not None
    assert fact["url"] == f"{SITE}/" and fact["page_id"] == page_ids[f"{SITE}/"]
    assert fact["quote"]
    extra = db.scalar("select extra from public.businesses where id = %s", [bid])
    assert extra["crawl"]["profiles"]["github"] == ["tallyhq-nlead"]
    assert "blog_post_1" in extra["crawl"]["pages"] and "privacy" in extra["crawl"]["pages"]


def test_the_stage_reads_startups_deeper_and_stores_probe_tech(firms_in: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from .test_research import FakeBrowser

    bid = insert_business(
        name="TallyHQ Stage",
        segment_id="firms-in",
        website=f"{SITE}/",
        web_domain="tallyhq-nlead.io",
        status="queued",
        queued_at=datetime.now(UTC),
        queue_priority=50,
    )
    db.set_setting("research.startup_max_pages", 8)
    transport, _ = mock_transport(site_routes())
    real = PoliteClient.__init__

    def init(self: PoliteClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        kwargs["min_gap_s"] = 0.0
        real(self, *args, **kwargs)

    loads: list[int] = []

    async def no_rules(*_: Any, **__: Any) -> None:
        loads.append(1)
        return None

    monkeypatch.setattr(PoliteClient, "__init__", init)
    monkeypatch.setattr(research, "Browser", lambda cap: FakeBrowser(cap=0))
    monkeypatch.setattr(fingerprint, "load_rules", no_rules)
    stats = research.run(run_context(segments=["firms-in"]))
    assert stats["crawl_ok"] >= 1 and stats["probe_tech"] >= 1 and stats["tech_rules_unavailable"] == 1
    assert loads == [1]  # the rules are loaded once per run
    pages = db.scalar("select count(*) from public.pages where business_id = %s and text is not null", [bid])
    assert 6 <= pages <= 8
    value = db.scalar("select value from public.facts where business_id = %s and field = 'probe.tech'", [bid])
    assert value["no_code_platform"] == "webflow"
