"""Rules that code must make impossible to break by accident (Step 18 and A.4).

Network rules live in `http.py` (Step 5, built on its own branch). Those tests run against its interface,
`PoliteClient(source, min_gap_s).get(url)`, and are skipped until that module is present on this branch:
never-fetch hosts are refused before any request, robots.txt is obeyed, the identity is honest, blocks
stop the source and no proxy is ever configured. The repository checks always run.
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

ENGINE = Path(__file__).resolve().parents[1]
REPO = ENGINE.parent
http = importlib.import_module("nument_engine.http")
POLITE = getattr(http, "PoliteClient", None)
NEVER_FETCH_ERROR: type[BaseException] = getattr(http, "NeverFetch", Exception)
BLOCKED_ERROR: type[BaseException] = getattr(http, "SourceBlocked", Exception)
needs_http = pytest.mark.skipif(
    POLITE is None, reason="enabled after merge: http.PoliteClient (Step 5) is not on this branch"
)

# A.4.2 and 18.1.1, plus the Step 5.2 list: the union is what must never be fetched.
NEVER_FETCH = (
    "linkedin.com",
    "x.com",
    "twitter.com",
    "instagram.com",
    "facebook.com",
    "fb.com",
    "threads.net",
    "tiktok.com",
    "web.whatsapp.com",
    "wa.me",
    "api.whatsapp.com",
    "truecaller.com",
    "justdial.com",
    "reddit.com",
    "indiamart.com",
    "sulekha.com",
)
SUBDOMAINS = (
    "https://www.linkedin.com/in/someone",
    "https://in.linkedin.com/company/x",
    "https://mobile.twitter.com/x",
    "https://m.facebook.com/ads/library/",
)
FORBIDDEN_PACKAGES = (
    # CAPTCHA solving
    "2captcha",
    "twocaptcha",
    "2captcha-python",
    "anticaptcha",
    "anticaptchaofficial",
    "capsolver",
    "capmonster",
    "deathbycaptcha",
    "nopecha",
    # stealth and block evasion
    "playwright-stealth",
    "undetected-chromedriver",
    "selenium-stealth",
    "selenium-wire",
    "cloudscraper",
    "cfscrape",
    "curl-cffi",
    "fake-useragent",
    "puppeteer-extra",
    "puppeteer-extra-plugin-stealth",
    # proxy rotation and scraping services
    "scrapy-rotating-proxies",
    "rotating-proxies",
    "free-proxy",
    "proxy-chain",
    "scraperapi",
    "zenrows",
    "brightdata",
    "oxylabs",
    "smartproxy",
    # private APIs and social scrapers (A.4.2)
    "python-jobspy",
    "jobspy",
    "linkedin-api",
    "linkedin-scraper",
    "instaloader",
    "snscrape",
    "twint",
    "ntscraper",
)


def _close(client: Any) -> Any:
    return getattr(client, "aclose", None) or getattr(getattr(client, "client", None), "aclose", None)


async def fetch(url: str) -> Any:
    assert POLITE is not None
    client = POLITE(source="compliance_test", min_gap_s=0)
    try:
        return await client.get(url)
    finally:
        closer = _close(client)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result


# ---------------------------------------------------------------------------
# Network rules (http.py)
# ---------------------------------------------------------------------------


@needs_http
@pytest.mark.parametrize("url", [f"https://{h}/any/page" for h in NEVER_FETCH] + list(SUBDOMAINS))
async def test_never_fetch_hosts_raise_before_any_request(url: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        anything = mock.route().respond(200, text="User-agent: *\nAllow: /")
        with pytest.raises(NEVER_FETCH_ERROR):
            await fetch(url)
        assert not anything.called, "a request was sent to a never-fetch host"


@needs_http
@pytest.mark.parametrize("url", ["https://box.com/pricing", "https://notlinkedin.com/", "https://maxhealth.in/x"])
async def test_lookalike_hosts_are_not_refused(url: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.route(path="/robots.txt").respond(200, text="User-agent: *\nAllow: /")
        mock.route().respond(200, text="<html><body>Fine</body></html>")
        result = await fetch(url)
    assert getattr(result, "state", "ok") == "ok"


@needs_http
async def test_robots_disallow_is_obeyed_with_our_user_agent() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://shop.example.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /private\n")
        page = mock.get("https://shop.example.com/private/report").respond(200, text="secret")
        open_page = mock.get("https://shop.example.com/about").respond(200, text="About us")
        skipped = await fetch("https://shop.example.com/private/report")
        fetched = await fetch("https://shop.example.com/about")
    assert not page.called and getattr(skipped, "state", None) == "robots_skip"
    assert open_page.called and "NumentLeadBot" in open_page.calls.last.request.headers["user-agent"]
    assert getattr(fetched, "state", None) == "ok"


@needs_http
@pytest.mark.parametrize(("robots_status", "allowed"), [(403, False), (401, False), (404, True)])
async def test_robots_status_codes(robots_status: int, allowed: bool) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://site.example.org/robots.txt").respond(robots_status)
        page = mock.get("https://site.example.org/contact").respond(200, text="Call us")
        await fetch("https://site.example.org/contact")
    assert page.called is allowed


@needs_http
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (403, "Forbidden"),
        (429, "Too many requests"),
        (200, "<title>Just a moment...</title> cf-chl captcha cloudflare"),
    ],
)
async def test_blocks_raise_source_blocked(status: int, body: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://blocky.example.net/robots.txt").respond(404)
        mock.get("https://blocky.example.net/page").respond(status, text=body)
        with pytest.raises(BLOCKED_ERROR):
            await fetch("https://blocky.example.net/page")


@needs_http
def test_the_client_has_no_proxy_and_ignores_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://proxy.invalid:1080")
    assert POLITE is not None
    client = POLITE(source="compliance_test", min_gap_s=0)
    inner = next((v for v in vars(client).values() if isinstance(v, httpx.AsyncClient | httpx.Client)), None)
    assert inner is not None, "PoliteClient should hold one httpx client"
    assert inner._trust_env is False, "create the client with trust_env=False (18.1.6)"
    assert not inner._mounts, "no proxy transports may be mounted"


# ---------------------------------------------------------------------------
# Repository rules (always run)
# ---------------------------------------------------------------------------


def _dependency_names() -> set[str]:
    names: set[str] = set()
    lock = ENGINE / "uv.lock"
    if lock.is_file():
        names |= set(re.findall(r'^name = "([^"]+)"', lock.read_text(encoding="utf-8"), flags=re.M))
    pyproject = (ENGINE / "pyproject.toml").read_text(encoding="utf-8")
    names |= {m.lower() for m in re.findall(r'"([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*[<>=!~]', pyproject)}
    package_json = REPO / "web" / "package.json"
    if package_json.is_file():
        data = json.loads(package_json.read_text(encoding="utf-8"))
        for key in ("dependencies", "devDependencies", "optionalDependencies"):
            names |= {n.lower() for n in data.get(key, {})}
    return {n.lower().replace("_", "-") for n in names}


def test_no_forbidden_dependencies() -> None:
    """No CAPTCHA solvers, stealth plugins, proxy rotation or private-API scrapers (18.1.6, A.4.2)."""
    found = _dependency_names() & {p.replace("_", "-") for p in FORBIDDEN_PACKAGES}
    assert not found, f"forbidden dependencies: {sorted(found)}"


def test_adapters_never_open_their_own_http_clients() -> None:
    """Every scrape goes through http.py (18.1): sources, research and pipeline never create a client."""
    pattern = re.compile(
        r"httpx\.(?:Async)?Client\(|requests\.(?:get|post|Session)\(|urlopen\(|aiohttp\.ClientSession\("
    )
    offenders = []
    for folder in ("sources", "research", "pipeline"):
        for path in (ENGINE / "src" / "nument_engine" / folder).rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{path.relative_to(ENGINE)}:{n}")
    assert offenders == []


def test_secrets_stay_out_of_git() -> None:
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in (".env", ".env.*", "!.env.example", ".env.handover", "service-account*.json", "*.pem", "*.key"):
        assert pattern in ignore, pattern
    assert (REPO / ".gitleaks.toml").is_file()
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "gitleaks" in ci and "eval-gate" in ci


def test_published_docs_have_no_en_or_em_dashes() -> None:
    files = [REPO / "README.md", ENGINE / "evals" / "README.md", *sorted((REPO / "docs").glob("*.md"))]
    offenders = [
        f"{p.relative_to(REPO)}:{n}"
        for p in files
        if p.is_file()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if chr(0x2013) in line or chr(0x2014) in line
    ]
    assert offenders == []
