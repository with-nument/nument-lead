"""Which pages of a business website to read (Step 9.4).

From the homepage links (same site only) the best link per group is chosen: team, contact, careers, locations,
pricing, booking, about. At most 7 pages plus the homepage. When fewer than 3 groups are found, the sitemap
fills the gaps. `tel:`, `mailto:` and WhatsApp links are collected on the way: they are published contact
routes even when they are not pages.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from ..normalize import canonical_url, web_domain

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
    "booking": ["book", "booking", "appointment", "schedule", "enquiry", "enquire", "consultation", "visit"],
    "about": ["about", "about us", "story", "who we are", "our story", "overview", "من نحن"],
}
GROUP_ORDER = list(GROUPS)
MAX_PAGES = 8  # homepage + 7
SITEMAP_MAX_URLS = 500
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


def same_site(url: str, home: str) -> bool:
    a, b = web_domain(url), web_domain(home)
    return a is not None and a == b


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
        if urlsplit(absolute).scheme not in ("http", "https") or not same_site(absolute, base_url):
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


def choose_pages(home_url: str, links: list[tuple[str, str]], max_pages: int = MAX_PAGES) -> dict[str, str]:
    """{"home": url, group: url, ...}: the best same-site link per group, in group priority order."""
    home_canon = canonical_url(home_url)
    best: dict[str, tuple[int, int, str]] = {}  # group -> (hits, -path length, url)
    for url, anchor in links:
        if SKIP.search(url) or canonical_url(url) == home_canon:
            continue
        path = urlsplit(url).path
        hay = _tokens(unquote(path) + " " + anchor)
        for group, words in GROUPS.items():
            hits = _hits(words, hay)
            if not hits:
                continue
            candidate = (hits, -len(path), url)
            if group not in best or candidate[:2] > best[group][:2]:
                best[group] = candidate
    chosen = {"home": home_url}
    used = {home_canon}
    for group in GROUP_ORDER:
        if len(chosen) >= max_pages:
            break
        if group in best:
            url = best[group][2]
            if canonical_url(url) not in used:
                chosen[group] = url
                used.add(canonical_url(url))
    return chosen


def sitemap_locs(xml: str) -> list[str]:
    return _LOC.findall(xml or "")


def is_sitemap_index(xml: str) -> bool:
    return "<sitemapindex" in (xml or "")[:2000].lower()
