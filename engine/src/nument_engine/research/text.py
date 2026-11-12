"""Page text for storage and AI input (Step 9.6).

Quotes are verified against `pages.text` (Step 10.2), so the stored text must hold everything the business
printed, including the header and footer where phone numbers, WhatsApp links and addresses usually live.
Main-content extractors such as trafilatura drop exactly those parts, so the stored text is the page's visible
text with one line per block element (scripts, styles and hidden templates removed). trafilatura still decides
whether a page is a JavaScript shell that needs the browser (`main_text_length`).
"""

from __future__ import annotations

import re
import unicodedata

import trafilatura
from selectolax.lexbor import LexborHTMLParser

MAX_CHARS = 20_000  # A.13.5 rule 13: page text is stored trimmed to 20,000 characters
KEY_LINES_BUDGET = 5_000  # on very long pages, lines with contacts and prices are kept first

_REMOVE = ("script", "style", "noscript", "svg", "template", "iframe", "object", "canvas", "head")
_BLOCK = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "button",
        "dd",
        "details",
        "dialog",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "label",
        "li",
        "main",
        "nav",
        "ol",
        "option",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "thead",
        "tr",
        "ul",
    }
)
_CELL = frozenset({"td", "th"})
_SPACES = re.compile("[ \t\r\f\v\u00a0\u200b]+")
KEY_LINE = re.compile(
    r"(\+?\d[\d\s().-]{7,}\d|@|₹|\brs\.?\s?\d|\baed\b|\bsar\b|\bdr\.?\s|doctor|founder|director|ceo|"
    r"branch|centre|center|years|experience|book|appointment|whatsapp|hiring|job|address|call)",
    re.I,
)


def title_of(html: str) -> str | None:
    tree = LexborHTMLParser(html)
    node = tree.css_first("title")
    title = _SPACES.sub(" ", node.text()).strip() if node is not None else ""
    return title[:300] or None


def visible_lines(html: str) -> list[str]:
    """Visible text, one line per block element, with whitespace collapsed and empty lines removed."""
    tree = LexborHTMLParser(html)
    for selector in _REMOVE:
        for node in tree.css(selector):
            node.decompose()
    for node in tree.css("[hidden], [aria-hidden='true'], [style*='display:none'], [style*='display: none']"):
        node.decompose()
    root = tree.body or tree.root
    if root is None:
        return []
    blocks = [n for n in root.traverse() if n.tag in _BLOCK or n.tag in _CELL]
    for node in blocks:
        if node.tag in _CELL:
            node.insert_after(" \t ")
        else:
            node.insert_before("\n")
            node.insert_after("\n")
    raw = root.text(separator="", deep=True)
    lines: list[str] = []
    for line in raw.split("\n"):
        clean = _SPACES.sub(" ", unicodedata.normalize("NFKC", line)).strip()
        if clean and (not lines or lines[-1] != clean):
            lines.append(clean)
    return lines


def fit_lines(lines: list[str], limit: int = MAX_CHARS) -> str:
    """Join lines under `limit` characters. Over the limit, contact and price lines are kept first (in page
    order), then the rest until the limit."""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    keep: set[int] = set()
    used = 0
    for i, line in enumerate(lines):
        if KEY_LINE.search(line) and used + len(line) + 1 <= KEY_LINES_BUDGET:
            keep.add(i)
            used += len(line) + 1
    for i, line in enumerate(lines):
        if i not in keep and used + len(line) + 1 <= limit:
            keep.add(i)
            used += len(line) + 1
    return "\n".join(lines[i] for i in sorted(keep))[:limit]


def page_text(html: str, url: str = "") -> tuple[str, str | None]:
    """(text, title) for storage: the page's visible text, capped at 20,000 characters."""
    return fit_lines(visible_lines(html)), title_of(html)


def main_text(html: str, url: str = "") -> tuple[str, list[tuple[str, str]]]:
    """(text, links) as in Step 9.6: the stored page text and the page's (href, anchor text) pairs. Anyone who
    re-checks a quote later (verification, the weekly audit) must extract text the same way it was stored."""
    from .pages import extract_links

    links = extract_links(html, url).pages if url else []
    return page_text(html, url)[0], links


def main_text_length(html: str, url: str = "") -> int:
    """Length of the main content as trafilatura sees it (0 for an empty JavaScript shell)."""
    text = trafilatura.extract(html, url=url or None, include_links=False, include_tables=True, favor_recall=True)
    return len(text or "")


def article_text(html: str, url: str = "", limit: int = 3000) -> str:
    """Main text of a news article (navigation and footers dropped), for the news classifier."""
    text = trafilatura.extract(html, url=url or None, include_links=False, include_tables=False, favor_recall=False)
    if not text:
        text = "\n".join(visible_lines(html))
    return text[:limit]
