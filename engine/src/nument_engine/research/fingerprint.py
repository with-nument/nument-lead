"""Tech-stack fingerprints from the webappanalyzer rules: no-code builders, AI vendors and the rest (15 Nov 2026).

The rules (github.com/enthec/webappanalyzer, GPL-3.0) are never copied into this repository. They are fetched at
run time from one pinned commit through `PoliteClient`, every file is checked against the sha256 below before it
is used, and verified files are kept in `.cache/webappanalyzer/<commit>/` (git-ignored), so a night with the
cache fetches nothing. A file that does not match its pin is never used and never cached. To move to newer rules,
change `RULES_COMMIT` and every hash in `RULES_SHA256` together, after reading the upstream diff.

Only what a static page shows can match: the HTML, script and iframe URLs, inline scripts and styles, meta tags,
CSS selectors, the page URL and the response headers that were kept. Rules that need a browser (JavaScript
globals, cookies, XHR) or DNS cannot match here. `MARKERS`, written for this engine, cover the builders and AI
widgets whose upstream rules depend on those, so the no-code platform and AI vendors are found even on a night the
rules cannot be fetched.

`detect()` returns the `probe.tech` fact (contract 4.2): technologies with their category names, the no-code
platform (one of `PLATFORMS`, or None) and the AI vendors, plus a short raw excerpt as the quote.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from ..http import NeverFetch, PoliteClient, SourceBlocked
from ..logging import get_logger
from ..settings import get_settings

log = get_logger()

RULES_REPO = "enthec/webappanalyzer"
RULES_COMMIT = "9e52f10a9533c8f7f8d0703c843f7295d56c95a3"  # main on 15 Nov 2026
RAW_URL = "https://raw.githubusercontent.com/{repo}/{commit}/{path}"
# sha256 of every file at RULES_COMMIT. A file that does not match is rejected (never used, never cached).
RULES_SHA256: dict[str, str] = {
    "src/categories.json": "98725a70537a2215a9b151e1a1a111a992428d838e9c701b3302e0901f2d616a",
    "src/technologies/_.json": "9e608aa2f84a6c4e1a0eebc826be7c122ac53fce31e24bbc2424a7a00b170971",
    "src/technologies/a.json": "598d43da989c6841c63b087d04acf1f6a51be018dc6e5b36f85a7c1d7f997284",
    "src/technologies/b.json": "9435ffe8df729781fd39144c358686ff6123da01e80ee42d16d6a4cb53ffee43",
    "src/technologies/c.json": "eaf0111fe728d0585e447fb28ea23d9c92d6253ff87ae72c32f9a469b518655c",
    "src/technologies/d.json": "e4ffd9188293b602e515c919a7ad24d83722864a856b58559c21770e1277b05c",
    "src/technologies/e.json": "bc288ba991df10737e4c3761f7191c00746e5da9071d5f75b7e42f4cf08370db",
    "src/technologies/f.json": "2cd94531b3fa47981f8defc2ba7ee7d57d172b7336a5d498ab45619b82c2fad6",
    "src/technologies/g.json": "88a8b955a49d9e57c879584081d936ceecd27eddd133fefcb29eedb51434fffa",
    "src/technologies/h.json": "c7e5a055af9e576f74ba6cb3c626e60f49adfe3e258a431c1b69c713d007d798",
    "src/technologies/i.json": "aa2ccd81b385e6a68d9ab61847371500d49005ca1421fca16b2b08e10f43b9ad",
    "src/technologies/j.json": "e8b4ec8ccbc147c7088682944af766404800b1e8345791ddcda14acf3c33f8bc",
    "src/technologies/k.json": "80445c130a1654ca92ae669e19591717e0c295c6382a5fb38af9239ed9bf072e",
    "src/technologies/l.json": "52a03863e34eaacf1bd6551a50ba1c53601cc9e037cecc0bb3257ec47ff1eaba",
    "src/technologies/m.json": "8633ac00212c27bf09d77368e0051f89f7e71bcb43bd53a2cc948e370e5410fa",
    "src/technologies/n.json": "9caf68ff1a0f0884caad0e298871b8aa86cfc30e5b234f7c5c41cb5bb94a79e7",
    "src/technologies/o.json": "632d2e22148963c86a0e8716f51863a8c31097f71401ff7f5d1960703dfd040f",
    "src/technologies/p.json": "28345da0de1da3a4c6978ada9abb7d544035b878e3cfd7781747f5e5e0121ad8",
    "src/technologies/q.json": "93d7c0657e85a680ae2fc2796bb0d53c1427eaa8e039e4d4de60b9bda943d972",
    "src/technologies/r.json": "18648f295e14a084fc8ed6d48dd80228cbf74566320d9e8dbc32aaa5b8f9bf37",
    "src/technologies/s.json": "5ffe3195dff31960f8a57e5523098aeec011e2a1367c3423c8f76f426585b4ec",
    "src/technologies/t.json": "511ac38c46b8a1a01b2f14ceefd9933a15fa62f08c1064cda7bba232027e72e5",
    "src/technologies/u.json": "67ee98c4fc627f93eef2aa96f0f021697892c6bbecbad3a3021a70d12b0095db",
    "src/technologies/v.json": "9af94728cbb8dd5bb132816a548e813411ebff26066d5c042590726a0e1e8fcd",
    "src/technologies/w.json": "6d40f22cea183a45d87bfabaceb9e67635f2c513fe272c860af52dc3f7f33173",
    "src/technologies/x.json": "00b262f7e7877ac9494a0f2c3ab9a3684b630fdcf0226d438d60293452c8f92d",
    "src/technologies/y.json": "209246a63cf30a8c81826583b2c9bd2fc1dc9fc5c4a77c5121690220ca8a7b12",
    "src/technologies/z.json": "87af275f7aeb9d3643cfa24921f42a880150bea0f49beaf403a8aa5918cf1143",
}
CATEGORIES_FILE = "src/categories.json"
FILE_MAX_BYTES = 2_000_000  # the largest rules file is about 390 KB
FETCH_GAP_S = 0.5  # raw.githubusercontent.com is GitHub's file CDN; 28 files take about 15 seconds

MIN_CONFIDENCE = 50  # a technology whose matched patterns add up to less than this is not reported
HTML_MAX_CHARS = 400_000  # regexes run over this much HTML (a few homepages are bigger)
SCRIPTS_MAX_CHARS = 150_000  # inline JavaScript searched by `scripts` rules
TEXT_MAX_CHARS = 50_000
MAX_TECHNOLOGIES = 60
EXCERPT_CHARS = 200

# Contract 4.2 `no_code_platform` values, in the order a page with two of them is reported: an app builder says
# more about the product than the builder of its marketing site.
PLATFORMS: tuple[str, ...] = (
    "bubble",
    "lovable",
    "bolt",
    "replit",
    "flutterflow",
    "adalo",
    "thunkable",
    "glide",
    "softr",
    "webflow",
    "framer",
    "wix",
    "squarespace",
    "carrd",
    "shopify",
)
# Technology names that mean a builder ("Bolt CMS" and "Glide.js" in the rules are different products).
PLATFORM_BY_TECH: dict[str, str] = {
    "Bubble": "bubble",
    "Lovable": "lovable",
    "Bolt.new": "bolt",
    "Replit": "replit",
    "FlutterFlow": "flutterflow",
    "Adalo": "adalo",
    "Thunkable": "thunkable",
    "Glide Apps": "glide",
    "Softr": "softr",
    "Webflow": "webflow",
    "Webflow Ecommerce": "webflow",
    "Framer Sites": "framer",
    "Wix": "wix",
    "Wix eCommerce": "wix",
    "Squarespace": "squarespace",
    "Squarespace Commerce": "squarespace",
    "Carrd": "carrd",
    "Shopify": "shopify",
}
AI_CATEGORY = "Artificial Intelligence"  # webappanalyzer category 112
# Live-chat products in the rules that answer with a language model (the category alone mixes them with chat
# staffed by people).
AI_CHAT_TECHS = frozenset(
    {
        "Aidbase",
        "Botpress",
        "Botsonic",
        "Chatbase",
        "ChatNode",
        "Chatsimple",
        "CoRover",
        "DocsBot",
        "EliseAI",
        "Fastmind",
        "Forethought AI",
        "Gleen",
        "Kapa.ai",
        "Lindy",
    }
)


# ---------------------------------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pattern:
    regex: re.Pattern[str]
    confidence: int = 100
    # Lower-case strings of which one must be in any text the regex matches (None: always run the regex). A
    # page that has none of them skips the regex: the same answer, about ten times faster on big pages.
    literals: tuple[str, ...] | None = None


@dataclass(frozen=True)
class DomRule:
    selector: str
    exists: bool = False
    attributes: tuple[tuple[str, Pattern], ...] = ()
    text: Pattern | None = None
    # Per selector branch, the lower-case words (classes, ids, attribute names and values) it needs on the page;
    # None when a branch needs none (then the selector always runs).
    tokens: tuple[tuple[str, ...], ...] | None = None


@dataclass
class Rules:
    """Compiled rules, indexed by what they look at. Patterns that Python cannot compile are skipped."""

    commit: str
    categories: dict[int, str] = field(default_factory=dict)
    tech_categories: dict[str, tuple[int, ...]] = field(default_factory=dict)
    html: list[tuple[str, Pattern]] = field(default_factory=list)
    script_src: list[tuple[str, Pattern]] = field(default_factory=list)
    scripts: list[tuple[str, Pattern]] = field(default_factory=list)
    url: list[tuple[str, Pattern]] = field(default_factory=list)
    text: list[tuple[str, Pattern]] = field(default_factory=list)
    css: list[tuple[str, Pattern]] = field(default_factory=list)
    meta: dict[str, list[tuple[str, Pattern]]] = field(default_factory=dict)
    headers: dict[str, list[tuple[str, Pattern]]] = field(default_factory=dict)
    dom: list[tuple[str, DomRule]] = field(default_factory=list)
    implies: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    excludes: dict[str, list[str]] = field(default_factory=dict)
    requires: dict[str, list[str]] = field(default_factory=dict)
    requires_category: dict[str, list[int]] = field(default_factory=dict)
    skipped: int = 0  # patterns or selectors that could not be compiled

    def category_names(self, tech: str) -> list[str]:
        return [self.categories[c] for c in self.tech_categories.get(tech, ()) if c in self.categories]


_TAG_SPLIT = "\\;"  # webappanalyzer appends tags to a pattern: "regex\;version:\1\;confidence:50"
# A quantified group that itself contains a quantifier ("(a+)+"): such patterns can take exponential time on
# some inputs, so they are skipped rather than risk stalling a night run.
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]")


def _tags(raw: str) -> tuple[str, int | None]:
    """'regex\\;version:\\1\\;confidence:50' -> ('regex', 50); a confidence that is not a number -> None."""
    parts = raw.split(_TAG_SPLIT)
    confidence: int | None = 100
    for tag in parts[1:]:
        key, _, value = tag.partition(":")
        if key == "confidence":
            confidence = int(value) if value.strip().isdigit() else None
    return parts[0], confidence


def _parse_pattern(raw: str, flags: int = re.I) -> Pattern | None:
    regex, confidence = _tags(raw)
    if confidence is None or _NESTED_QUANTIFIER.search(regex):
        return None
    try:
        return Pattern(re.compile(regex, flags), confidence, required_literals(regex))
    except (re.error, OverflowError):
        return None


# Python's own regex parser, to find the literal text a pattern cannot match without (an internal module, so
# any surprise from it only turns the shortcut off).
_SRE_PARSER: Any = importlib.import_module("re._parser")
_SRE: Any = importlib.import_module("re._constants")
MIN_LITERAL = 3


def required_literals(regex: str) -> tuple[str, ...] | None:
    """Lower-case strings of which at least one appears in every text the pattern matches (case-insensitively),
    or None when there is no such string of at least `MIN_LITERAL` ASCII characters."""
    try:
        return _best_literals(list(_SRE_PARSER.parse(regex, re.I)))
    except Exception:
        return None


def _best_literals(seq: list[tuple[Any, Any]]) -> tuple[str, ...] | None:
    candidates: list[tuple[str, ...]] = []
    run: list[str] = []

    def flush() -> None:
        if len(run) >= MIN_LITERAL:
            candidates.append(("".join(run).lower(),))
        run.clear()

    for op, av in seq:
        if op is _SRE.LITERAL and av < 128:
            run.append(chr(av))
            continue
        flush()
        inner: tuple[str, ...] | None = None
        if op is _SRE.SUBPATTERN:
            inner = _best_literals(list(av[-1]))
        elif op in (_SRE.MAX_REPEAT, _SRE.MIN_REPEAT, _SRE.POSSESSIVE_REPEAT) and av[0] >= 1:
            inner = _best_literals(list(av[2]))
        elif op is _SRE.ATOMIC_GROUP:
            inner = _best_literals(list(av))
        elif op is _SRE.BRANCH:
            alternatives: list[str] = []
            for alt in av[1]:
                found = _best_literals(list(alt))
                if not found:
                    alternatives = []
                    break
                alternatives.extend(found)
            inner = tuple(sorted(set(alternatives))) or None
        if inner:
            candidates.append(inner)
    flush()
    if not candidates:
        return None
    return max(candidates, key=lambda c: (min(len(s) for s in c), -len(c)))


_PSEUDO_CALL = re.compile(r":[\w-]+\((?:[^()]|\([^()]*\))*\)")
_ATTR = re.compile(r"\[\s*([\w:-]+)\s*(?:[*^$|~]?=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\]\s]+)))?\s*(?:[iIsS]\s*)?\]")
_CLASS_OR_ID = re.compile(r"[.#]([\w-]+)")


def selector_tokens(selector: str) -> tuple[tuple[str, ...], ...] | None:
    """Per comma branch of a CSS selector, the words a page must contain for the branch to match: classes, ids,
    attribute names and attribute values. Inside `:not(...)` and other functional pseudo-classes nothing is
    required. None when some branch requires nothing."""
    branches: list[tuple[str, ...]] = []
    depth, start, parts = 0, 0, []
    for i, ch in enumerate(selector):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(selector[start:i])
            start = i + 1
    parts.append(selector[start:])
    for part in parts:
        text = _PSEUDO_CALL.sub(" ", part)
        words: list[str] = []
        for match in _ATTR.finditer(text):
            words.append(match.group(1))
            value = match.group(2) or match.group(3) or match.group(4)
            if value:
                words.append(value)
        words += _CLASS_OR_ID.findall(_ATTR.sub(" ", text))
        kept = tuple(dict.fromkeys(w.lower() for w in words if len(w) >= MIN_LITERAL and not set(w) & set("&<>\"'\\")))
        if not kept:
            return None
        branches.append(kept)
    return tuple(branches)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _names(value: Any) -> list[tuple[str, int]]:
    """Technology names of implies, excludes and requires, with their confidence tag (100 without one)."""
    out: list[tuple[str, int]] = []
    for entry in _strings(value):
        name, confidence = _tags(entry)
        if name.strip():
            out.append((name.strip(), 100 if confidence is None else confidence))
    return out


_PROBE_DOC = LexborHTMLParser("<html><head></head><body></body></html>")


def _selector_ok(selector: str) -> bool:
    try:
        _PROBE_DOC.css_first(selector)
    except Exception:  # lexbor rejects selectors it does not support
        return False
    return True


def compile_rules(technologies: Mapping[str, Any], categories: Mapping[str, Any], commit: str) -> Rules:
    """Rules from the decoded webappanalyzer JSON (technology name -> definition, category id -> definition)."""
    rules = Rules(commit=commit)
    for cid, cat in categories.items():
        if str(cid).isdigit() and isinstance(cat, dict) and isinstance(cat.get("name"), str):
            rules.categories[int(cid)] = cat["name"]

    def add(target: list[tuple[str, Pattern]], name: str, value: Any, flags: int = re.I) -> None:
        for raw in _strings(value):
            pattern = _parse_pattern(raw, flags)
            if pattern is None:
                rules.skipped += 1
            else:
                target.append((name, pattern))

    for name, tech in technologies.items():
        if not isinstance(tech, dict):
            continue
        rules.tech_categories[name] = tuple(c for c in tech.get("cats") or [] if isinstance(c, int))
        add(rules.html, name, tech.get("html"))
        add(rules.script_src, name, tech.get("scriptSrc"), re.I | re.M)  # one URL per line
        add(rules.scripts, name, tech.get("scripts"))
        add(rules.url, name, tech.get("url"))
        add(rules.text, name, tech.get("text"))
        add(rules.css, name, tech.get("css"))
        for kind, index in (("meta", rules.meta), ("headers", rules.headers)):
            spec = tech.get(kind)
            if isinstance(spec, dict):
                for key, value in spec.items():
                    add(index.setdefault(str(key).lower(), []), name, value)
        _add_dom(rules, name, tech.get("dom"))
        implies = _names(tech.get("implies"))
        if implies:
            rules.implies[name] = implies
        excludes = [n for n, _ in _names(tech.get("excludes"))]
        if excludes:
            rules.excludes[name] = excludes
        requires = [n for n, _ in _names(tech.get("requires"))]
        if requires:
            rules.requires[name] = requires
        req_cats = [c for c in tech.get("requiresCategory") or [] if isinstance(c, int)]
        if req_cats:
            rules.requires_category[name] = req_cats
    return rules


def _add_dom(rules: Rules, name: str, dom: Any) -> None:
    if isinstance(dom, str | list):
        for selector in _strings(dom):
            if _selector_ok(selector):
                rules.dom.append((name, DomRule(selector, exists=True, tokens=selector_tokens(selector))))
            else:
                rules.skipped += 1
    elif isinstance(dom, dict):
        for selector, spec in dom.items():
            rule = _dom_rule(str(selector), spec)
            if rule is None:
                rules.skipped += 1
            elif rule.exists or rule.attributes or rule.text is not None:
                rules.dom.append((name, rule))  # rules on JavaScript properties alone cannot match a static page


def _dom_rule(selector: str, spec: Any) -> DomRule | None:
    if not _selector_ok(selector):
        return None
    tokens = selector_tokens(selector)
    if not isinstance(spec, dict):
        return DomRule(selector, exists=True, tokens=tokens)
    attributes: list[tuple[str, Pattern]] = []
    for attr, raw in (spec.get("attributes") or {}).items():
        pattern = _parse_pattern(raw) if isinstance(raw, str) else None
        if pattern is None:
            return None
        attributes.append((str(attr).lower(), pattern))
    text: Pattern | None = None
    if isinstance(spec.get("text"), str):
        text = _parse_pattern(spec["text"])
        if text is None:
            return None
    return DomRule(selector, exists="exists" in spec, attributes=tuple(attributes), text=text, tokens=tokens)


def parse_files(files: Mapping[str, bytes], commit: str = RULES_COMMIT) -> Rules:
    """Rules from the verified files (path -> content). Raises ValueError on a file that is not a JSON object."""
    technologies: dict[str, Any] = {}
    categories: dict[str, Any] = {}
    for path, content in files.items():
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a JSON object")
        if path == CATEGORIES_FILE:
            categories = data
        elif path.startswith("src/technologies/"):
            technologies.update(data)
    return compile_rules(technologies, categories, commit)


# ---------------------------------------------------------------------------------------------------
# Fetching, the pin check and the cache
# ---------------------------------------------------------------------------------------------------


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def cache_root(commit: str = RULES_COMMIT) -> Path:
    return get_settings().cache_dir / "webappanalyzer" / commit


def _read_cached(path: Path, digest: str) -> bytes | None:
    try:
        content = path.read_bytes()
    except OSError:
        return None
    return content if sha256(content) == digest else None


def _write_cached(path: Path, content: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)
    except OSError as exc:  # a read-only disk only costs a fetch next time
        log.warning("fingerprint.cache_write_failed", file=path.name, error=str(exc)[:200])


async def fetch_files(
    http: PoliteClient,
    *,
    pins: Mapping[str, str] = RULES_SHA256,
    commit: str = RULES_COMMIT,
    root: Path | None = None,
) -> dict[str, bytes] | None:
    """Every pinned file, from the cache when its hash still matches, else fetched and checked. None when any
    file cannot be fetched or does not match its pin (then nothing of this commit is trusted for the run)."""
    base = root or cache_root(commit)
    out: dict[str, bytes] = {}
    for path, digest in pins.items():
        local = base / path
        cached = _read_cached(local, digest)
        if cached is not None:
            out[path] = cached
            continue
        url = RAW_URL.format(repo=RULES_REPO, commit=commit, path=path)
        try:
            res = await http.get(url, max_bytes=FILE_MAX_BYTES, retries=1)
        except (SourceBlocked, NeverFetch) as exc:
            log.warning("fingerprint.fetch_blocked", file=path, error=str(exc)[:200])
            return None
        if not res.ok or res.truncated:
            log.warning("fingerprint.fetch_failed", file=path, state=res.state, reason=res.reason[:120])
            return None
        content = res.content
        if sha256(content) != digest:
            log.warning("fingerprint.pin_mismatch", file=path, expected=digest[:16], got=sha256(content)[:16])
            return None
        _write_cached(local, content)
        out[path] = content
    return out


_LOADED: dict[str, Rules] = {}


def forget_loaded() -> None:
    """Drop the rules kept in memory (tests)."""
    _LOADED.clear()


async def load_rules(
    http: PoliteClient | None = None,
    *,
    pins: Mapping[str, str] = RULES_SHA256,
    commit: str = RULES_COMMIT,
    root: Path | None = None,
) -> Rules | None:
    """The pinned rules, compiled once per process. None (and a warning) when they cannot be had tonight; the
    engine's own markers still find builders and AI vendors then."""
    if commit in _LOADED:
        return _LOADED[commit]
    own = http is None
    client = http or PoliteClient("fingerprint", policy="open_data", min_gap_s=FETCH_GAP_S, max_bytes=FILE_MAX_BYTES)
    try:
        files = await fetch_files(client, pins=pins, commit=commit, root=root)
    finally:
        if own:
            await client.aclose()
    if files is None:
        log.warning("fingerprint.rules_unavailable", commit=commit[:12])
        return None
    try:
        rules = parse_files(files, commit)
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("fingerprint.rules_unreadable", commit=commit[:12], error=str(exc)[:200])
        return None
    _LOADED[commit] = rules
    log.info("fingerprint.rules_loaded", commit=commit[:12], technologies=len(rules.tech_categories))
    return rules


# ---------------------------------------------------------------------------------------------------
# The engine's own markers (not from webappanalyzer)
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Marker:
    """A builder or AI product, recognised by the site's host, its HTML, or the URLs of its scripts and iframes."""

    name: str
    category: str
    platform: str | None = None
    ai: bool = False
    hosts: tuple[str, ...] = ()  # the page's host is one of these or a subdomain of one
    html: tuple[re.Pattern[str], ...] = ()
    src: tuple[re.Pattern[str], ...] = ()


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.I) for p in patterns)


BUILDER = "Page builders"
CHAT = "Live chat"
MARKERS: tuple[Marker, ...] = (
    # no-code and AI app builders
    Marker(
        "Bubble",
        BUILDER,
        "bubble",
        hosts=("bubbleapps.io",),
        html=_rx(r"appforest_uf", r"\bbubble_page_load_data\b", r"\bbubble_environment\b", r"\.cdn\.bubble\.io/"),
    ),
    Marker(
        "Lovable",
        BUILDER,
        "lovable",
        hosts=("lovable.app", "lovableproject.com"),
        html=_rx(r"cdn\.gpteng\.co/", r"gptengineer\.js", r"/lovable-uploads/", r"<meta[^>]+content=[\"']Lovable[\"']"),
    ),
    Marker("Bolt.new", BUILDER, "bolt", hosts=("bolt.host",), html=_rx(r"https?://bolt\.new/")),
    Marker("Replit", BUILDER, "replit", hosts=("replit.app", "repl.co", "replit.dev"), src=_rx(r"replit\.com/public/")),
    Marker("FlutterFlow", BUILDER, "flutterflow", hosts=("flutterflow.app",), html=_rx(r"flutterflow")),
    Marker(
        "Adalo",
        BUILDER,
        "adalo",
        hosts=("adalo.com", "adaloapp.com"),
        html=_rx(r"assets\.adalo\.com/", r"\.adalo\.com/static/"),
    ),
    Marker("Thunkable", BUILDER, "thunkable", hosts=("thunkable.app",), src=_rx(r"thunkable\.com/")),
    Marker("Glide Apps", BUILDER, "glide", hosts=("glide.page", "glideapp.io"), src=_rx(r"glideapps?\.com/")),
    Marker("Softr", BUILDER, "softr", hosts=("softr.app",), html=_rx(r"softr-files\.com/", r"softr-prod\.imgix\.net")),
    Marker(
        "Webflow",
        BUILDER,
        "webflow",
        hosts=("webflow.io",),
        html=_rx(r"\bdata-wf-(?:site|page)=", r"website-files\.com/"),
    ),
    Marker(
        "Framer Sites",
        BUILDER,
        "framer",
        hosts=("framer.website", "framer.app", "framer.ai"),
        html=_rx(r"framerusercontent\.com/", r"\bdata-framer-(?:hydrate|name|component)", r"content=[\"']Framer\b"),
    ),
    Marker(
        "Wix",
        BUILDER,
        "wix",
        hosts=("wixsite.com", "wixstudio.io", "wixstudio.com"),
        html=_rx(r"static\.wixstatic\.com/", r"static\.parastorage\.com/", r"content=[\"']Wix\.com Website Builder"),
    ),
    Marker(
        "Squarespace",
        BUILDER,
        "squarespace",
        hosts=("squarespace.com",),
        html=_rx(r"static1\.squarespace\.com/", r"<!-- This is Squarespace\. -->", r"SQUARESPACE_CONTEXT"),
    ),
    Marker("Carrd", BUILDER, "carrd", hosts=("carrd.co",), html=_rx(r"carrd\.co/build\?ref=")),
    Marker(
        "Shopify",
        "Ecommerce",
        "shopify",
        hosts=("myshopify.com",),
        html=_rx(r"cdn\.shopify\.com/", r"\bShopify\.theme\b"),
    ),
    # AI agents, chat and voice widgets embedded in the site
    Marker("OpenAI ChatKit", AI_CATEGORY, ai=True, src=_rx(r"cdn\.platform\.openai\.com/")),
    Marker(
        "ElevenLabs",
        AI_CATEGORY,
        ai=True,
        src=_rx(r"elevenlabs\.io/", r"@elevenlabs/convai"),
        html=_rx(r"<elevenlabs-convai\b"),
    ),
    Marker("Vapi", AI_CATEGORY, ai=True, src=_rx(r"@vapi-ai/", r"\bvapi\.ai/")),
    Marker("Retell AI", AI_CATEGORY, ai=True, src=_rx(r"retellai\.com/")),
    Marker("Synthflow", AI_CATEGORY, ai=True, src=_rx(r"synthflow\.ai/")),
    Marker("Voiceflow", CHAT, ai=True, src=_rx(r"(?:cdn|widget)\.voiceflow\.com/")),
    Marker("Botpress", CHAT, ai=True, src=_rx(r"(?:cdn|mediafiles|webchat)\.botpress\.cloud/")),
    Marker("Chatbase", CHAT, ai=True, src=_rx(r"chatbase\.co/"), html=_rx(r"chatbase\.co/chatbot-iframe")),
    Marker("Landbot", CHAT, ai=True, src=_rx(r"landbot\.io/")),
    Marker(
        "Dialogflow",
        CHAT,
        ai=True,
        src=_rx(r"gstatic\.com/dialogflow-console/fast/messenger"),
        html=_rx(r"<df-messenger\b"),
    ),
    Marker("Microsoft Bot Framework", CHAT, ai=True, src=_rx(r"cdn\.botframework\.com/")),
    Marker("Yellow.ai", CHAT, ai=True, src=_rx(r"yellowmessenger\.com/")),
    Marker("Ada", CHAT, ai=True, src=_rx(r"static\.ada\.support/")),
    Marker("Kapa.ai", CHAT, ai=True, src=_rx(r"widget\.kapa\.ai/")),
    Marker("Inkeep", CHAT, ai=True, src=_rx(r"@inkeep/")),
    Marker("CustomGPT", CHAT, ai=True, src=_rx(r"customgpt\.ai/")),
    Marker("SiteGPT", CHAT, ai=True, src=_rx(r"sitegpt\.ai/")),
    Marker("Chatling", CHAT, ai=True, src=_rx(r"chatling\.ai/")),
    Marker("Dante AI", CHAT, ai=True, src=_rx(r"dante-ai\.com/")),
    Marker("Hugging Face Spaces", AI_CATEGORY, ai=True, src=_rx(r"\.hf\.space\b", r"huggingface\.co/spaces/")),
)
AI_MARKERS = frozenset(m.name for m in MARKERS if m.ai)


# ---------------------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------------------


@dataclass
class Found:
    name: str
    categories: list[str]
    evidence: str  # a short raw excerpt of what matched
    confidence: int = 100


@dataclass
class TechReport:
    """The `probe.tech` fact: `value()` is the contract 4.2 JSON, `quote` the short raw excerpt."""

    technologies: list[Found]
    no_code_platform: str | None
    ai_vendors: list[str]
    quote: str
    rules_commit: str | None = None  # None: the engine's own markers only (the rules were unavailable)

    def value(self) -> dict[str, Any]:
        return {
            "technologies": [{"name": t.name, "categories": t.categories} for t in self.technologies],
            "no_code_platform": self.no_code_platform,
            "ai_vendors": self.ai_vendors,
        }


@dataclass
class Page:
    """What a static page offers to the rules, parsed once."""

    url: str
    html: str
    headers: dict[str, str]
    srcs: str  # script URLs, one per line (`^` and `$` match per URL)
    frames: str  # script and iframe URLs, one per line (for the engine's own markers)
    scripts: str
    css: str
    meta: list[tuple[str, str, str]]  # (name, content, raw tag)
    tree: LexborHTMLParser
    lower: dict[str, str] = field(default_factory=dict)  # lower-case copies for the literal shortcut

    def lowered(self, part: str) -> str:
        if part not in self.lower:
            self.lower[part] = str(getattr(self, part)).lower()
        return self.lower[part]

    @classmethod
    def parse(cls, url: str, html: str, headers: Mapping[str, str] | None = None) -> Page:
        html = html[:HTML_MAX_CHARS]
        tree = LexborHTMLParser(html)
        script_srcs = [str(n.attributes.get("src") or "") for n in tree.css("script[src]")]
        frame_srcs = [str(n.attributes.get("src") or "") for n in tree.css("iframe[src]")]
        inline: list[str] = []
        size = 0
        for node in tree.css("script"):
            if node.attributes.get("src") is not None:
                continue
            body = node.text(deep=True) or ""
            inline.append(body)
            size += len(body)
            if size >= SCRIPTS_MAX_CHARS:
                break
        meta: list[tuple[str, str, str]] = []
        for node in tree.css("meta"):
            attrs = node.attributes
            name = attrs.get("name") or attrs.get("property") or attrs.get("http-equiv") or attrs.get("itemprop")
            if name:
                meta.append((str(name).lower(), str(attrs.get("content") or ""), node.html or ""))
        css = "\n".join(n.text(deep=True) or "" for n in tree.css("style"))
        return cls(
            url=url,
            html=html,
            headers={k.lower(): v for k, v in (headers or {}).items()},
            srcs="\n".join(s for s in script_srcs if s),
            frames="\n".join(s for s in script_srcs + frame_srcs if s),
            scripts="\n".join(inline)[:SCRIPTS_MAX_CHARS],
            css=css[:SCRIPTS_MAX_CHARS],
            meta=meta,
            tree=tree,
        )

    def visible_text(self) -> str:
        tree = LexborHTMLParser(self.html)
        tree.strip_tags(["script", "style", "noscript", "template"])
        body = tree.body
        return re.sub(r"\s+", " ", body.text(separator=" ") if body is not None else "")[:TEXT_MAX_CHARS]


def _excerpt(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 60)
    return re.sub(r"\s+", " ", text[start : match.end() + 60]).strip()[:EXCERPT_CHARS]


def _short(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:EXCERPT_CHARS]


def _line_of(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start : end if end >= 0 else len(text)]


class _Hits:
    """Matched confidence and the first evidence per technology."""

    def __init__(self) -> None:
        self.confidence: dict[str, int] = {}
        self.evidence: dict[str, str] = {}

    def add(self, name: str, confidence: int, evidence: str) -> None:
        self.confidence[name] = min(100, self.confidence.get(name, 0) + confidence)
        self.evidence.setdefault(name, evidence)


def _search_all(
    hits: _Hits, rules: Iterable[tuple[str, Pattern]], text: str, lowered: str, *, lines: bool = False
) -> None:
    if not text:
        return
    for name, pattern in rules:
        if pattern.literals is not None and not any(lit in lowered for lit in pattern.literals):
            continue
        match = pattern.regex.search(text)
        if match:
            hits.add(
                name, pattern.confidence, _short(_line_of(text, match.start())) if lines else _excerpt(text, match)
            )


def _match_rules(page: Page, rules: Rules) -> _Hits:
    hits = _Hits()
    for part, index in (("html", rules.html), ("scripts", rules.scripts), ("css", rules.css), ("url", rules.url)):
        _search_all(hits, index, getattr(page, part), page.lowered(part))
    _search_all(hits, rules.script_src, page.srcs, page.lowered("srcs"), lines=True)
    for name, content, raw in page.meta:
        for tech, pattern in rules.meta.get(name, ()):
            if pattern.regex.search(content):
                hits.add(tech, pattern.confidence, _short(raw))
    for header, value in page.headers.items():
        for tech, pattern in rules.headers.get(header, ()):
            if pattern.regex.search(value):
                hits.add(tech, pattern.confidence, _short(f"{header}: {value}"))
    for tech, rule in rules.dom:
        _match_dom(hits, page, tech, rule)
    if rules.text:
        text = page.visible_text()
        _search_all(hits, rules.text, text, text.lower())
    return hits


def _match_dom(hits: _Hits, page: Page, tech: str, rule: DomRule) -> None:
    if rule.tokens is not None:
        html = page.lowered("html")
        if not any(all(token in html for token in branch) for branch in rule.tokens):
            return
    try:
        if rule.exists and not rule.attributes and rule.text is None:
            node = page.tree.css_first(rule.selector)
            if node is not None:
                hits.add(tech, 100, _short(node.html or rule.selector))
            return
        for node in page.tree.css(rule.selector):
            if rule.exists:
                hits.add(tech, 100, _short(node.html or rule.selector))
                return
            for attr, pattern in rule.attributes:
                value = node.attributes.get(attr)
                if value is not None and pattern.regex.search(str(value)):
                    hits.add(tech, pattern.confidence, _short(node.html or rule.selector))
                    return
            if rule.text is not None and rule.text.regex.search(node.text(deep=True) or ""):
                hits.add(tech, rule.text.confidence, _short(node.html or rule.selector))
                return
    except Exception:  # a selector lexbor accepted at load time but cannot run on this page
        return


def _resolve(hits: _Hits, rules: Rules) -> dict[str, int]:
    """Apply the threshold and the relations: implies (recursively), requires, requiresCategory, excludes."""
    found = {name: conf for name, conf in hits.confidence.items() if conf >= MIN_CONFIDENCE}

    def imply() -> None:
        queue = list(found)
        while queue:
            name = queue.pop()
            for implied, conf in rules.implies.get(name, ()):
                if conf >= MIN_CONFIDENCE and implied not in found and implied in rules.tech_categories:
                    found[implied] = conf
                    queue.append(implied)

    imply()
    for _ in range(3):  # a requirement may itself have been implied
        before = set(found)
        cats = {c for name in found for c in rules.tech_categories.get(name, ())}
        for name in list(found):
            needs = rules.requires.get(name)
            need_cats = rules.requires_category.get(name)
            if (needs and not all(n in found for n in needs)) or (need_cats and not cats.intersection(need_cats)):
                del found[name]
        imply()
        if set(found) == before:
            break
    for name in list(found):
        for excluded in rules.excludes.get(name, ()):
            found.pop(excluded, None)
    return found


def _match_markers(page: Page) -> dict[str, tuple[Marker, str]]:
    host = (urlsplit(page.url).hostname or "").lower().rstrip(".")
    out: dict[str, tuple[Marker, str]] = {}
    for marker in MARKERS:
        evidence = next((host for h in marker.hosts if host == h or host.endswith("." + h)), None)
        for pattern in marker.src if evidence is None else ():
            match = pattern.search(page.frames)
            if match:
                evidence = _short(_line_of(page.frames, match.start()))
                break
        for pattern in marker.html if evidence is None else ():
            match = pattern.search(page.html)
            if match:
                evidence = _excerpt(page.html, match)
                break
        if evidence is not None:
            out[marker.name] = (marker, evidence)
    return out


def detect(url: str, html: str, headers: Mapping[str, str] | None = None, rules: Rules | None = None) -> TechReport:
    """Technologies on one page (the homepage). `rules` None: the engine's own markers only."""
    page = Page.parse(url, html, headers)
    techs: dict[str, Found] = {}
    if rules is not None:
        hits = _match_rules(page, rules)
        for name, conf in _resolve(hits, rules).items():
            techs[name] = Found(name, rules.category_names(name), hits.evidence.get(name, ""), conf)
    for name, (marker, evidence) in _match_markers(page).items():
        if name not in techs:
            techs[name] = Found(name, [marker.category], evidence)
    platforms: dict[str, str] = {}
    for name in techs:
        key = PLATFORM_BY_TECH.get(name)
        if key is not None:
            platforms.setdefault(key, name)
    platform = next((p for p in PLATFORMS if p in platforms), None)
    ai = sorted(
        name
        for name, found in techs.items()
        if name not in PLATFORM_BY_TECH
        and (AI_CATEGORY in found.categories or name in AI_CHAT_TECHS or name in AI_MARKERS)
    )
    ordered = sorted(techs.values(), key=lambda f: f.name.lower())[:MAX_TECHNOLOGIES]
    decisive = techs[platforms[platform]] if platform else (techs[ai[0]] if ai else None)
    if decisive is None:
        decisive = next((t for t in ordered if t.evidence), None)
    quote = decisive.evidence if decisive is not None else _page_head(page)
    return TechReport(ordered, platform, ai, quote, rules.commit if rules is not None else None)


def _page_head(page: Page) -> str:
    """The quote when nothing matched: the generator meta tag or the title, as written on the page."""
    generator = next((raw for name, _, raw in page.meta if name == "generator"), None)
    if generator:
        return _short(generator)
    title = page.tree.css_first("title")
    if title is not None and title.html:
        return _short(title.html)
    return _short(page.html[:EXCERPT_CHARS])
