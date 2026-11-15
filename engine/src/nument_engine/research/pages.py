"""Which pages of a business website to read (Step 9.4).

From the homepage links (same site only) the best link per group is chosen: team, contact, careers, locations,
pricing, booking, about. At most 7 pages plus the homepage. When fewer than 3 groups are found, the sitemap
fills the gaps. `tel:`, `mailto:` and WhatsApp links are collected on the way: they are published contact
routes even when they are not pages.

Startups (15 Nov 2026, segments in the `firms` domain with a `signals_only` universe) are read deeper, up to
`research.startup_max_pages` (12) pages: also privacy, terms, imprint, press and the blog, then the latest posts
listed on the blog page. Their links to a GitHub organisation, the App Store and Google Play are kept for the
night probes (the links only: those sites are never crawled).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from ..normalize import canonical_url, web_domain
from ..segments import Segment

GROUPS: dict[str, list[str]] = {
    "team": [
        "team",
        "doctors",
        "our doctors",
        "specialists",
        "faculty",
        "experts",
        "people",
        "leadership",
        "founder",
        "management",
        "dermatologist",
        "dentists",
    ],
    "contact": ["contact", "reach us", "locate", "find us", "get in touch", "اتصل"],
    "careers": [
        "careers",
        "career",
        "jobs",
        "join us",
        "hiring",
        "work with us",
        "vacancies",
        "opportunities",
        "وظائف",
    ],
    "locations": ["locations", "branches", "centres", "centers", "our clinics", "offices", "campuses", "فروعنا"],
    "pricing": [
        "pricing",
        "price",
        "packages",
        "fees",
        "plans",
        "treatments",
        "services",
        "courses",
        "programs",
        "programmes",
        "projects",
        "properties",
        "rooms",
    ],
    # "visit" alone matched treatment pages such as "single visit crowns" on a live site: only "visit us" counts.
    "booking": ["book", "booking", "appointment", "schedule", "enquiry", "enquire", "consultation", "visit us"],
    "about": ["about", "about us", "story", "who we are", "our story", "overview", "من نحن"],
}
GROUP_ORDER = list(GROUPS)
MAX_PAGES = 8  # homepage + 7
SITEMAP_MAX_URLS = 500

# Startups only. Legal pages name the company and its address; press and blog posts date what it is doing now.
STARTUP_GROUPS: dict[str, list[str]] = {
    "privacy": ["privacy", "privacy policy", "data protection", "datenschutz"],
    "terms": ["terms", "terms of service", "terms of use", "terms and conditions", "legal"],
    "imprint": ["imprint", "impressum", "legal notice", "mentions legales"],
    "press": ["press", "newsroom", "in the news", "media kit", "press kit", "news"],
    "blog": ["blog", "updates", "changelog", "journal", "insights", "articles"],
}
STARTUP_ORDER = [
    "about",
    "team",
    "careers",
    "pricing",
    "press",
    "blog",
    "contact",
    "privacy",
    "terms",
    "imprint",
    "booking",
    "locations",
]
STARTUP_MAX_PAGES = 12  # default of settings research.startup_max_pages (contract 4.9)
BLOG_POSTS = 3  # the latest posts read from the blog page, when the page budget allows
SKIP = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|mp4|mp3|zip|docx?|xlsx?|pptx?)(\?|$)|/(tag|category|page|author|feed)/|"
    r"/wp-json/|login|signin|sign-in|signup|register|cart|checkout|my-account|wishlist|\?replytocom=",
    re.I,
)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_WA_NUMBER = re.compile(r"(?:wa\.me/|phone=)(\+?\d{8,15})")


@dataclass
class Links:
    """Links found on a page: same-site page links plus contact routes."""

    pages: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)
    tel: list[str] = field(default_factory=list)  # raw numbers from tel: links
    whatsapp: list[str] = field(default_factory=list)  # numbers from wa.me / api.whatsapp.com links
    mailto: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)  # GitHub, App Store and Google Play links (never fetched)


def same_site(url: str, home: str) -> bool:
    a, b = web_domain(url), web_domain(home)
    return a is not None and a == b


def is_startup_segment(seg: Segment) -> bool:
    """Startup segments (15 Nov 2026): the `firms` domain with a `signals_only` universe."""
    return seg.domain == "firms" and seg.universe == "signals_only"


# github.com/<owner>[/<repo>]: GitHub's own pages are not owners.
_GITHUB_RESERVED = frozenset(
    {
        "about",
        "apps",
        "collections",
        "contact",
        "customer-stories",
        "enterprise",
        "events",
        "explore",
        "features",
        "github",
        "login",
        "marketplace",
        "new",
        "notifications",
        "orgs",
        "pricing",
        "readme",
        "search",
        "security",
        "settings",
        "site",
        "sponsors",
        "team",
        "topics",
        "trending",
        "users",
    }
)
_GITHUB_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_APP_STORE_ID = re.compile(r"/id(\d{6,12})/")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")


def github_owner(url: str) -> str | None:
    """The account a github.com link points at (`github.com/acme/app` -> `acme`), or None."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if segments[:1] == ["orgs"] and len(segments) > 1:
        segments = segments[1:]
    if not segments or segments[0].lower() in _GITHUB_RESERVED or not _GITHUB_OWNER.match(segments[0]):
        return None
    return segments[0]


def app_store_id(url: str) -> str | None:
    """The numeric App Store id of an apps.apple.com or itunes.apple.com app link, or None."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() not in ("apps.apple.com", "itunes.apple.com"):
        return None
    match = _APP_STORE_ID.search(parts.path.rstrip("/") + "/")
    return match.group(1) if match else None


def play_package(url: str) -> str | None:
    """The package name of a Google Play app link (`details?id=com.acme.app`), or None."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() != "play.google.com" or "/store/apps/details" not in parts.path:
        return None
    package = (parse_qs(parts.query).get("id") or [""])[0]
    return package if _PACKAGE.match(package) else None


def is_profile_link(url: str) -> bool:
    return bool(github_owner(url) or app_store_id(url) or play_package(url))


def extract_links(html: str, base_url: str) -> Links:
    tree = LexborHTMLParser(html)
    out = Links()
    seen: set[str] = set()
    for node in tree.css("a[href], link[rel='alternate'][href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        low = href.lower()
        if low.startswith("tel:"):
            number = unquote(href[4:]).strip()
            if number and number not in out.tel:
                out.tel.append(number)
            continue
        if low.startswith("mailto:"):
            email = unquote(href[7:]).split("?", 1)[0].strip()
            if email and email.lower() not in out.mailto:
                out.mailto.append(email.lower())
            continue
        if "wa.me/" in low or "whatsapp.com/send" in low or low.startswith("whatsapp:"):
            wa = _wa_number(href)
            if wa and wa not in out.whatsapp:
                out.whatsapp.append(wa)
            continue
        absolute = urljoin(base_url, href)
        if urlsplit(absolute).scheme not in ("http", "https"):
            continue
        if not same_site(absolute, base_url):
            if is_profile_link(absolute) and absolute not in out.profiles:
                out.profiles.append(absolute)
            continue
        canon = canonical_url(absolute)
        if canon in seen:
            continue
        seen.add(canon)
        anchor = re.sub(r"\s+", " ", node.text() or str(node.attributes.get("title") or "")).strip()[:80]
        out.pages.append((absolute.split("#", 1)[0], anchor))
    return out


def _wa_number(href: str) -> str | None:
    match = _WA_NUMBER.search(href)
    if match:
        return match.group(1)
    phones = parse_qs(urlsplit(href).query).get("phone") or []
    phone = phones[0] if phones else ""
    return phone if phone and phone.lstrip("+").isdigit() else None


def _tokens(text: str) -> str:
    return " " + " ".join(re.split(r"\W+", text.lower())) + " "


def _hits(words: Iterable[str], hay: str) -> int:
    return sum(1 for w in words if _tokens(w).strip() and _tokens(w)[:-1] in hay)


def choose_pages(
    home_url: str, links: list[tuple[str, str]], max_pages: int = MAX_PAGES, *, startup: bool = False
) -> dict[str, str]:
    """{"home": url, group: url, ...}: the best same-site link per group, in group priority order.

    For a startup the extra groups count too, in `STARTUP_ORDER`, and once the blog page is chosen up to
    `BLOG_POSTS` of the remaining budget is kept for its latest posts (`blog_posts`)."""
    groups = {**GROUPS, **STARTUP_GROUPS} if startup else GROUPS
    order = STARTUP_ORDER if startup else GROUP_ORDER
    home_canon = canonical_url(home_url)
    best: dict[str, tuple[int, int, str]] = {}  # group -> (hits, -path length, url)
    for url, anchor in links:
        if SKIP.search(url) or canonical_url(url) == home_canon:
            continue
        path = urlsplit(url).path
        hay = _tokens(unquote(path) + " " + anchor)
        for group, words in groups.items():
            hits = _hits(words, hay)
            if not hits:
                continue
            candidate = (hits, -len(path), url)
            if group not in best or candidate[:2] > best[group][:2]:
                best[group] = candidate
    chosen = {"home": home_url}
    used = {home_canon}
    for group in order:
        if len(chosen) >= max_pages:
            break
        if group not in best or canonical_url(best[group][2]) in used:
            continue
        if startup and "blog" in chosen and len(chosen) >= max_pages - BLOG_POSTS:
            continue  # the rest of the budget is for the blog's latest posts
        chosen[group] = best[group][2]
        used.add(canonical_url(best[group][2]))
    return chosen


def blog_posts(html: str, blog_url: str, exclude: Iterable[str] = (), limit: int = BLOG_POSTS) -> list[str]:
    """The first `limit` posts linked from a blog page, in page order (blog pages list the newest first).

    A post is a same-site link below the blog page's path (or, for a blog on its own host such as blog.acme.com,
    any deeper link on that host), and not a tag, category, author, feed or paging link."""
    base = urlsplit(blog_url)
    prefix = base.path.rstrip("/")
    skip = {canonical_url(u) for u in exclude} | {canonical_url(blog_url)}
    out: list[str] = []
    for url, _anchor in extract_links(html, blog_url).pages:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.hostname != base.hostname or SKIP.search(url) or parts.query:
            continue
        if prefix and not path.startswith(prefix + "/"):
            continue
        if not prefix and path.count("/") < 1:
            continue
        canon = canonical_url(url)
        if canon in skip:
            continue
        skip.add(canon)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def sitemap_locs(xml: str) -> list[str]:
    return _LOC.findall(xml or "")


def is_sitemap_index(xml: str) -> bool:
    return "<sitemapindex" in (xml or "")[:2000].lower()
