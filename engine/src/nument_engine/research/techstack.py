"""Booking, chat, WhatsApp, CRM, ads and CMS detection from raw HTML (Step 9.8).

Patterns are searched in the raw HTML of every fetched page, script sources and inline scripts included. Vendors
change their snippet URLs, so every pattern has a fixture test and should be re-checked against live sites when
a vendor changes its embed code.

The output is one code fact per business (`field = 'tech_stack'`): the tools found, with the derived flags
Step 11 scores (`has_booking`, `has_whatsapp`, `has_chat`, `pays_for_software`, `runs_ads_tag`, `free_builder`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..normalize import is_free_builder


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str  # booking | chat | whatsapp_vendor | whatsapp | ads | analytics | crm | cms | framework
    patterns: tuple[re.Pattern[str], ...]
    paid: bool = False  # a paid product: evidence the business already pays for software


def _p(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.I) for p in patterns)


TOOLS: tuple[Tool, ...] = (
    # booking
    Tool("Practo widget", "booking", _p(r"practo\.com/widget", r"widget\.practo\.com", r"practo\.com/embed"), True),
    Tool("Calendly", "booking", _p(r"calendly\.com/"), True),
    Tool("Setmore", "booking", _p(r"setmore\.com"), True),
    Tool("Zoho Bookings", "booking", _p(r"zohobookings", r"bookings\.zoho"), True),
    Tool("SimplyBook.me", "booking", _p(r"simplybook\.(?:me|it|asia)"), True),
    Tool("Acuity Scheduling", "booking", _p(r"acuityscheduling\.com"), True),
    Tool("Picktime", "booking", _p(r"picktime\.com"), True),
    # chat
    Tool("Zoho SalesIQ", "chat", _p(r"salesiq\.zoho", r"zohopublic\.[a-z.]+/[^\"']*salesiq"), True),
    Tool("Tawk.to", "chat", _p(r"embed\.tawk\.to"), False),
    Tool("Intercom", "chat", _p(r"widget\.intercom\.io", r"js\.intercomcdn\.com"), True),
    Tool("Freshchat", "chat", _p(r"wchat\.freshchat\.com", r"fw-cdn\.com"), True),
    Tool("Crisp", "chat", _p(r"client\.crisp\.chat"), True),
    Tool("Tidio", "chat", _p(r"code\.tidio\.co"), True),
    Tool("HubSpot chat", "chat", _p(r"js\.usemessages\.com"), True),
    # WhatsApp Business API vendors (competitors and partners, Step 3.6)
    Tool("Wati", "whatsapp_vendor", _p(r"wati\.io"), True),
    Tool("Interakt", "whatsapp_vendor", _p(r"interakt\.shop", r"interakt\.ai"), True),
    Tool("Gallabox", "whatsapp_vendor", _p(r"gallabox\.com"), True),
    Tool("AiSensy", "whatsapp_vendor", _p(r"aisensy\.com"), True),
    # WhatsApp click-to-chat links and buttons
    Tool(
        "WhatsApp link",
        "whatsapp",
        _p(r"wa\.me/", r"api\.whatsapp\.com/send", r"whatsapp://send", r"web\.whatsapp\.com/send"),
    ),
    # ads tags (a can-pay hint, not the manual ads_running signal)
    Tool("Meta Pixel", "ads", _p(r"connect\.facebook\.net/[^\"']*fbevents\.js", r"fbq\(\s*['\"]init['\"]")),
    Tool("Google Ads tag", "ads", _p(r"['\"]AW-\d{9,11}['\"]", r"[?&]id=AW-\d{9,11}")),
    # analytics
    Tool("Google Analytics 4", "analytics", _p(r"gtag/js\?id=G-")),
    Tool("Google Tag Manager", "analytics", _p(r"googletagmanager\.com/gtm\.js")),
    # CRM
    Tool("Sell.do", "crm", _p(r"sell\.do"), True),
    Tool("LeadSquared", "crm", _p(r"leadsquared"), True),
    Tool("Meritto (NoPaperForms)", "crm", _p(r"nopaperforms", r"meritto"), True),
    Tool("Zoho CRM forms", "crm", _p(r"crm\.zoho\.[a-z.]+/crm/WebToLeadForm", r"zohocrm"), True),
    Tool("HubSpot", "crm", _p(r"js\.hs-scripts\.com", r"js\.hsforms\.net"), True),
    # CMS and builders
    Tool("WordPress", "cms", _p(r"/wp-content/", r"/wp-includes/")),
    Tool("Wix", "cms", _p(r"static\.wixstatic\.com", r"<meta[^>]+generator[^>]+wix\.com")),
    Tool("Shopify", "cms", _p(r"cdn\.shopify\.com")),
    Tool("Webflow", "cms", _p(r"webflow\.js", r"data-wf-site")),
    Tool("Squarespace", "cms", _p(r"static1\.squarespace\.com", r"squarespace\.com")),
    Tool("GoDaddy builder", "cms", _p(r"img1\.wsimg\.com")),
    Tool("Google Sites", "cms", _p(r"sites\.google\.com/")),
    # frameworks
    Tool("Next.js", "framework", _p(r"/_next/static/")),
)
FREE_BUILDER_TOOLS = frozenset({"Wix", "GoDaddy builder", "Google Sites"})
SNIPPET_CHARS = 200


def _snippet(html: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 60)
    return re.sub(r"\s+", " ", html[start : match.end() + 60])[:SNIPPET_CHARS]


def detect(pages: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    """Tools found on any page: [{tool, kind, page_url, snippet}], one entry per tool (first page wins)."""
    found: dict[str, dict[str, Any]] = {}
    for url, html in pages:
        for tool in TOOLS:
            if tool.name in found:
                continue
            for pattern in tool.patterns:
                match = pattern.search(html)
                if match:
                    found[tool.name] = {
                        "tool": tool.name,
                        "kind": tool.kind,
                        "page_url": url,
                        "snippet": _snippet(html, match),
                    }
                    break
    return list(found.values())


def flags(tools: list[dict[str, Any]], web_domain: str | None = None) -> dict[str, bool]:
    """Derived flags for scoring (Step 9.8 outputs)."""
    by_name = {t["tool"]: t for t in tools}
    kinds = {t["kind"] for t in tools}
    paid = {tool.name for tool in TOOLS if tool.paid}
    return {
        "has_booking": "booking" in kinds,
        "has_whatsapp": "whatsapp" in kinds or "whatsapp_vendor" in kinds,
        "has_chat": "chat" in kinds,
        "pays_for_software": any(name in paid for name in by_name),
        "runs_ads_tag": "ads" in kinds,
        "free_builder": bool(FREE_BUILDER_TOOLS & set(by_name)) or is_free_builder(web_domain),
    }


_VIEWPORT = re.compile(r"<meta[^>]+name\s*=\s*[\"']?viewport", re.I)
_COPYRIGHT = re.compile(
    r"(?:\u00a9|&copy;|copyright)\s*(?:\u00a9|&copy;)?\s*((?:19|20)\d{2})(?:\s*[-\u2013]\s*((?:19|20)\d{2}))?", re.I
)
_OLD_JQUERY = re.compile(r"jquery[.\-/](?:min\.)?(?:v)?([12])\.\d+(?:\.\d+)?(?:\.min)?\.js", re.I)
_WP_GENERATOR = re.compile(r"<meta[^>]+content=[\"']WordPress\s+(\d+)\.(\d+)", re.I)
OLD_SITE_YEARS = 5  # a newest copyright year this many years back reads as an unmaintained site


def site_issues(home_url: str | None, home_html: str | None, today_year: int) -> list[str]:
    """Signs, from the home page alone, that a website is old or not built for phones (13 Nov 2026: the
    `slow_site` signal without a PageSpeed key). Each reason names what code found."""
    html = home_html or ""
    if not html:
        return []
    reasons: list[str] = []
    if not _VIEWPORT.search(html):
        reasons.append("no mobile layout (no viewport tag)")
    if (home_url or "").startswith("http://"):
        reasons.append("no HTTPS")
    years = [int(y) for m in _COPYRIGHT.finditer(html) for y in m.groups() if y]
    if years and max(years) <= today_year - OLD_SITE_YEARS:
        reasons.append(f"copyright {max(years)}")
    jq = _OLD_JQUERY.search(html)
    if jq:
        reasons.append(f"jQuery {jq.group(1)}.x")
    wp = _WP_GENERATOR.search(html)
    if wp and (int(wp.group(1)), int(wp.group(2))) < (5, 5):
        reasons.append(f"WordPress {wp.group(1)}.{wp.group(2)}")
    return reasons


def tech_value(tools: list[dict[str, Any]], web_domain: str | None = None) -> dict[str, Any]:
    """The `tech_stack` fact value: the tools (without snippets) plus the derived flags."""
    return {
        "tools": [{k: t[k] for k in ("tool", "kind", "page_url")} for t in tools],
        **flags(tools, web_domain),
    }
