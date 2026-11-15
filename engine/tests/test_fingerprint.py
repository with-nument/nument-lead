"""Tech fingerprints (E2a, 15 Nov 2026): the pinned rules fetch and cache, the matcher on the webappanalyzer format,
the engine's own builder and AI markers, and the `probe.tech` value.

The webappanalyzer rules are GPL, so no part of them is in this repository: these tests use rules written here in
the same format, and hand-made HTML pages under fixtures/e2a/html.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine.http import PoliteClient
from nument_engine.research import fingerprint as fp

from .sources_helpers import mock_transport, no_network

__all__ = ["no_network"]

HTML_DIR = Path(__file__).resolve().parent / "fixtures" / "e2a" / "html"
COMMIT = "c0ffee" + "0" * 34


def html(name: str) -> str:
    return (HTML_DIR / name).read_text(encoding="utf-8")


CATEGORIES = {
    "1": {"name": "CMS", "priority": 1},
    "5": {"name": "Widgets", "priority": 9},
    "10": {"name": "Analytics", "priority": 9},
    "12": {"name": "JavaScript frameworks", "priority": 8},
    "19": {"name": "Miscellaneous", "priority": 10},
    "22": {"name": "Web servers", "priority": 8},
    "27": {"name": "Programming languages", "priority": 5},
    "51": {"name": "Page builders", "priority": 1},
    "52": {"name": "Live chat", "priority": 9},
    "59": {"name": "JavaScript libraries", "priority": 9},
    "88": {"name": "Hosting", "priority": 9},
    "112": {"name": "Artificial Intelligence", "priority": 9},
}
TECHNOLOGIES: dict[str, Any] = {
    "Acme CMS": {"cats": [1], "meta": {"generator": "^AcmeCMS(?: ([\\d.]+))?\\;version:\\1"}},
    "Pixel Kit": {"cats": [10], "scriptSrc": ["^https?://cdn\\.pixelkit\\.example/"]},
    "Inline Kit": {"cats": [59], "scripts": ["inlinekit\\.boot\\("]},
    "Header Server": {"cats": [22], "headers": {"Server": "^HeaderServer"}},
    "Dom Exists": {"cats": [12], "dom": ["div#app-root[data-domkit]"]},
    "Dom Attr": {"cats": [12], "dom": {"link[href*='attrkit']": {"attributes": {"href": "attrkit\\.example/v(\\d)"}}}},
    "Dom Text": {"cats": [5], "dom": {"span.badge": {"text": "^Made with TextKit$"}}},
    "Url Kit": {"cats": [88], "url": ["^https?://[^/]+\\.urlkit\\.example"]},
    "Text Kit": {"cats": [19], "text": ["Powered by TextEngine"]},
    "Weak One": {"cats": [19], "html": ["weak-marker\\;confidence:25"]},
    "Weak Two": {"cats": [19], "html": ["half-marker-a\\;confidence:25", "half-marker-b\\;confidence:25"]},
    "Implier": {
        "cats": [19],
        "html": ["implier-marker"],
        "implies": ["Implied Lang\\;confidence:50", "Implied Low\\;confidence:25"],
    },
    "Implied Lang": {"cats": [27]},
    "Implied Low": {"cats": [27]},
    "Needs Implier": {"cats": [19], "html": ["needs-marker"], "requires": ["Implier"]},
    "Needs Missing": {"cats": [19], "html": ["needs-marker"], "requires": ["Not Here"]},
    "Needs Category": {"cats": [19], "html": ["needs-marker"], "requiresCategory": [27]},
    "Excluder": {"cats": [19], "html": ["excluder-marker"], "excludes": ["Weak Two"]},
    "Bad Regex": {"cats": [19], "html": ["(unclosed"]},
    "Bad Selector": {"cats": [19], "dom": ["div[[["]},
    "Slow Regex": {"cats": [19], "html": ["(a+)+b"]},
    "Js Only": {"cats": [19], "js": {"jsOnlyGlobal": ""}},
    "Webflow": {"cats": [51], "dom": ["html[data-wf-site]"]},
    "Glide.js": {"cats": [59], "scriptSrc": ["/glidejs/"]},
    "Chatbase": {"cats": [52], "scripts": ["chatbase\\.example"]},
    "Some AI": {"cats": [112], "html": ["someai-widget"]},
}
PAGE = """<!DOCTYPE html><html><head><title>Kitchen sink</title>
<meta name="generator" content="AcmeCMS 4.2">
<link rel="stylesheet" href="https://static.attrkit.example/v3/kit.css">
<script src="https://cdn.pixelkit.example/p.js"></script>
<script src="https://cdn.example/lib/glidejs/glide.min.js"></script>
<script>inlinekit.boot({id: 1}); window.chat = "chatbase.example";</script>
</head><body><div id="app-root" data-domkit="1"></div><span class="badge">Made with TextKit</span>
<p>Powered by TextEngine</p><i class="weak-marker"></i><i class="half-marker-a"></i><i class="half-marker-b"></i>
<i class="implier-marker"></i><i class="needs-marker"></i><div class="someai-widget"></div><p>aaaaaaaaaaaaaaaaaaaaaaac</p>
</body></html>"""


@pytest.fixture(autouse=True)
def _fresh_rules() -> Iterator[None]:
    fp.forget_loaded()
    yield
    fp.forget_loaded()


def rules(technologies: dict[str, Any] | None = None) -> fp.Rules:
    return fp.compile_rules(technologies or TECHNOLOGIES, CATEGORIES, COMMIT)


def names(report: fp.TechReport) -> set[str]:
    return {t.name for t in report.technologies}


# ---- the matcher -----------------------------------------------------------------------------------------


def test_every_static_rule_kind_matches() -> None:
    report = fp.detect("https://shop.urlkit.example/", PAGE, {"Server": "HeaderServer/2.1"}, rules())
    found = names(report)
    for tech in (
        "Acme CMS",
        "Pixel Kit",
        "Inline Kit",
        "Header Server",
        "Dom Exists",
        "Dom Attr",
        "Dom Text",
        "Url Kit",
        "Text Kit",
        "Chatbase",
        "Some AI",
    ):
        assert tech in found, tech
    assert "Js Only" not in found  # JavaScript globals need a browser: never matched on a static page


def test_confidence_adds_up_and_weak_patterns_alone_are_not_reported() -> None:
    found = names(fp.detect("https://a.example/", PAGE, None, rules()))
    assert "Weak One" not in found  # 25 < 50
    assert "Weak Two" in found  # 25 + 25


def test_implies_requires_and_excludes() -> None:
    found = names(fp.detect("https://a.example/", PAGE, None, rules()))
    assert {"Implier", "Implied Lang", "Needs Implier", "Needs Category"} <= found
    assert "Implied Low" not in found  # implied with confidence 25
    assert "Needs Missing" not in found
    excluded = names(fp.detect("https://a.example/", PAGE + "<i class='excluder-marker'></i>", None, rules()))
    assert "Excluder" in excluded and "Weak Two" not in excluded


def test_patterns_python_cannot_run_safely_are_skipped() -> None:
    compiled = rules()
    assert compiled.skipped == 3  # the unclosed group, the bad selector and the nested quantifier
    found = names(fp.detect("https://a.example/", PAGE, None, compiled))
    assert not {"Bad Regex", "Bad Selector", "Slow Regex"} & found


def test_script_src_anchors_match_each_url_on_its_own() -> None:
    page = '<script src="https://other.example/x.js"></script><script src="https://cdn.pixelkit.example/p.js"></script>'
    assert "Pixel Kit" in names(fp.detect("https://a.example/", page, None, rules()))


def test_categories_are_named_and_ai_vendors_come_from_the_ai_category_and_ai_chat() -> None:
    report = fp.detect("https://a.example/", PAGE, None, rules())
    by_name = {t.name: t for t in report.technologies}
    assert by_name["Acme CMS"].categories == ["CMS"]
    assert report.ai_vendors == ["Chatbase", "Some AI"]
    assert report.no_code_platform is None  # Glide.js is a carousel, not the Glide app builder


def test_required_literals_never_change_the_answer() -> None:
    plain = fp.compile_rules(TECHNOLOGIES, CATEGORIES, COMMIT)
    for index in (plain.html, plain.scripts, plain.script_src, plain.text, plain.url):
        index[:] = [(n, fp.Pattern(p.regex, p.confidence, None)) for n, p in index]
    plain.dom = [(n, fp.DomRule(r.selector, r.exists, r.attributes, r.text, None)) for n, r in plain.dom]
    for page in (PAGE, html("webflow_home.html"), html("ai_widgets.html"), html("plain_site.html")):
        assert fp.detect("https://a.example/", page, None, rules()).value() == (
            fp.detect("https://a.example/", page, None, plain).value()
        )


@pytest.mark.parametrize(
    ("regex", "matching", "literals"),
    [
        (r"cdn\.pixelkit\.example/", "x cdn.pixelkit.example/a", ("cdn.pixelkit.example/",)),
        (r"(?:https?:)?//(?:www\.)?tanstack\.com", "//www.tanstack.com", ("tanstack.com",)),
        (r"(?://|-)strapi-|strapi_jwt", "-strapi-x", ("strapi-", "strapi_jwt")),
        (r"Foo(?:Bar)+", "FOOBARBAR", None),
        (r"(?:x|y)z", "xz", None),
        (r"\d+\.\d+", "1.2", None),
    ],
)
def test_required_literals(regex: str, matching: str, literals: tuple[str, ...] | None) -> None:
    """Every text the regex matches contains one of the literals (checked on a matching sample)."""
    found = fp.required_literals(regex)
    assert re.search(regex, matching, re.I)
    if found is not None:
        assert any(lit in matching.lower() for lit in found)
    if literals is not None:
        assert found is not None and set(found) == set(literals)
    elif regex in (r"(?:x|y)z", r"\d+\.\d+"):
        assert found is None  # nothing of three characters is required


def test_selector_tokens() -> None:
    assert fp.selector_tokens("html[data-wf-site]") == (("data-wf-site",),)
    assert fp.selector_tokens("link[href*='softr-files.com/']") == (("href", "softr-files.com/"),)
    assert fp.selector_tokens("div.live-chat, iframe#chat-frame") == (("live-chat",), ("chat-frame",))
    assert fp.selector_tokens("div:not(.skipme)") is None  # nothing is required inside :not()
    assert fp.selector_tokens("script") is None


# ---- the engine's own markers and the probe.tech value --------------------------------------------------------


@pytest.mark.parametrize(
    ("page", "url", "platform"),
    [
        ("webflow_home.html", "https://www.tallyhq-nlead.io/", "webflow"),
        ("bubble_app.html", "https://rentwise-nlead.com/", "bubble"),
        ("lovable_app.html", "https://mealmate-nlead.com/", "lovable"),
        ("framer_site.html", "https://pathly-nlead.com/", "framer"),
        ("plain_site.html", "https://quillworks-nlead.org/", None),
        ("ai_widgets.html", "https://nestly-nlead.com/", None),
    ],
)
def test_builders_are_found_without_the_rules(page: str, url: str, platform: str | None) -> None:
    """The night the rules cannot be fetched, the engine's own markers still name the builder."""
    report = fp.detect(url, html(page), None, None)
    assert report.no_code_platform == platform
    assert report.rules_commit is None


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://acme.webflow.io/", "webflow"),
        ("https://acme.lovable.app/", "lovable"),
        ("https://acme.bubbleapps.io/version-test", "bubble"),
        ("https://acme.replit.app/", "replit"),
        ("https://acme.glide.page/", "glide"),
        ("https://acme.carrd.co/", "carrd"),
        ("https://acme.bolt.host/", "bolt"),
        ("https://acme.myshopify.com/", "shopify"),
        ("https://notwebflow.io.example.com/", None),
    ],
)
def test_builder_hosts(url: str, platform: str | None) -> None:
    assert fp.detect(url, "<html><body><p>Hello</p></body></html>").no_code_platform == platform


def test_an_app_builder_wins_over_a_site_builder() -> None:
    page = html("webflow_home.html").replace(
        "</body>", "<img src='https://s3.amazonaws.com/appforest_uf/x.png'></body>"
    )
    assert fp.detect("https://a.example/", page).no_code_platform == "bubble"


def test_ai_widgets_are_ai_vendors_and_a_link_is_not_a_builder() -> None:
    report = fp.detect("https://nestly-nlead.com/", html("ai_widgets.html"))
    assert report.ai_vendors == ["Botpress", "ElevenLabs"]
    assert report.no_code_platform is None  # a link to wix.com is not a Wix site
    assert "cdn.botpress.cloud" in report.quote


def test_rules_and_markers_together_name_each_technology_once() -> None:
    report = fp.detect("https://www.tallyhq-nlead.io/", html("webflow_home.html"), None, rules())
    assert [t.name for t in report.technologies].count("Webflow") == 1
    assert report.no_code_platform == "webflow" and report.rules_commit == COMMIT
    assert "data-wf-site" in report.quote or "website-files.com" in report.quote


def test_the_value_has_exactly_the_contract_keys() -> None:
    value = fp.detect("https://mealmate-nlead.com/", html("lovable_app.html")).value()
    assert set(value) == {"technologies", "no_code_platform", "ai_vendors"}
    assert value["no_code_platform"] == "lovable"
    assert value["technologies"] == [{"name": "Lovable", "categories": ["Page builders"]}]
    assert value["ai_vendors"] == []  # an AI app builder is the platform, not an AI vendor of the product
    json.dumps(value)


def test_nothing_found_quotes_the_page_title() -> None:
    report = fp.detect("https://quillworks-nlead.org/", html("plain_site.html"))
    assert report.technologies == [] and report.quote == "<title>Quillworks</title>"


# ---- fetching, the sha256 pin and the cache ---------------------------------------------------------------------


def rule_files() -> dict[str, bytes]:
    return {
        "src/categories.json": json.dumps(CATEGORIES).encode(),
        "src/technologies/a.json": json.dumps({k: v for k, v in TECHNOLOGIES.items() if k < "N"}).encode(),
        "src/technologies/n.json": json.dumps({k: v for k, v in TECHNOLOGIES.items() if k >= "N"}).encode(),
    }


def raw_url(path: str, commit: str = COMMIT) -> str:
    return fp.RAW_URL.format(repo=fp.RULES_REPO, commit=commit, path=path)


def routes_for(files: dict[str, bytes], commit: str = COMMIT) -> dict[str, Any]:
    routes: dict[str, Any] = {"https://raw.githubusercontent.com/robots.txt": (404, "")}
    for path, content in files.items():
        routes[raw_url(path, commit)] = httpx.Response(200, content=content)
    return routes


async def load(routes: dict[str, Any], pins: dict[str, str], root: Path) -> tuple[fp.Rules | None, list[httpx.Request]]:
    transport, seen = mock_transport(routes)
    async with PoliteClient("fingerprint", policy="open_data", min_gap_s=0.0, transport=transport) as http:
        loaded = await fp.load_rules(http, pins=pins, commit=COMMIT, root=root)
    return loaded, seen


async def test_pinned_files_are_checked_cached_and_reused(tmp_path: Path) -> None:
    files = rule_files()
    pins = {path: fp.sha256(content) for path, content in files.items()}
    loaded, seen = await load(routes_for(files), pins, tmp_path)
    assert loaded is not None and loaded.commit == COMMIT and "Acme CMS" in loaded.tech_categories
    assert {r.url.path for r in seen} >= {f"/{fp.RULES_REPO}/{COMMIT}/{p}" for p in files}
    assert (tmp_path / "src" / "technologies" / "a.json").read_bytes() == files["src/technologies/a.json"]
    fp.forget_loaded()
    again, seen_again = await load({}, pins, tmp_path)  # every file from the verified cache
    assert again is not None and seen_again == []


async def test_a_file_that_does_not_match_its_pin_is_never_used_or_cached(tmp_path: Path) -> None:
    files = rule_files()
    pins = {path: fp.sha256(content) for path, content in files.items()}
    tampered = dict(files)
    tampered["src/technologies/n.json"] = files["src/technologies/n.json"] + b" "
    loaded, _ = await load(routes_for(tampered), pins, tmp_path)
    assert loaded is None
    assert not (tmp_path / "src" / "technologies" / "n.json").exists()


async def test_a_changed_cache_file_is_fetched_again(tmp_path: Path) -> None:
    files = rule_files()
    pins = {path: fp.sha256(content) for path, content in files.items()}
    for path, content in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(content)
    (tmp_path / "src" / "categories.json").write_bytes(b"{}")  # changed on disk: no longer matches the pin
    loaded, seen = await load(routes_for(files), pins, tmp_path)
    assert loaded is not None
    assert [r.url.path for r in seen if r.url.path != "/robots.txt"] == [
        f"/{fp.RULES_REPO}/{COMMIT}/src/categories.json"
    ]


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(404, text="404: Not Found"),
        httpx.Response(429, text="Too Many Requests"),
        "timeout",
    ],
)
async def test_rules_are_unavailable_when_a_file_cannot_be_fetched(tmp_path: Path, failure: Any) -> None:
    files = rule_files()
    pins = {path: fp.sha256(content) for path, content in files.items()}
    routes = routes_for(files)

    def fail(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        assert isinstance(failure, httpx.Response)
        return failure

    routes[raw_url("src/technologies/n.json")] = fail
    loaded, _ = await load(routes, pins, tmp_path)
    assert loaded is None


def test_the_real_pin_covers_the_categories_and_every_technology_file() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", fp.RULES_COMMIT)
    expected = {"src/categories.json"} | {f"src/technologies/{c}.json" for c in "_abcdefghijklmnopqrstuvwxyz"}
    assert set(fp.RULES_SHA256) == expected
    assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in fp.RULES_SHA256.values())
    assert fp.cache_root().parts[-3:] == (".cache", "webappanalyzer", fp.RULES_COMMIT)
