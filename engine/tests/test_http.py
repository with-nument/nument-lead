"""Polite HTTP (Steps 5.2 and 18.1): never-fetch hosts, robots.txt, blocks, spacing, size cap, redirects."""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx
import pytest

from nument_engine import http
from nument_engine.http import (
    NeverFetch,
    PoliteClient,
    RobotsRules,
    SourceBlocked,
    challenge_reason,
    classify,
    host_blocked,
    redact,
)

from .sources_helpers import mock_transport

UA_TOKEN = "numentleadbot"


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    http.reset_caches()
    yield
    http.reset_caches()


def client(routes: dict[str, object], **kwargs: object) -> tuple[PoliteClient, list[httpx.Request]]:
    transport, seen = mock_transport(routes)  # type: ignore[arg-type]
    kwargs.setdefault("policy", "public")
    kwargs.setdefault("min_gap_s", 0.0)
    return PoliteClient("test", transport=transport, **kwargs), seen  # type: ignore[arg-type]


# ---- never-fetch -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/in/someone",
        "https://in.linkedin.com/company/x",
        "https://x.com/someone/status/1",
        "https://twitter.com/a",
        "https://www.instagram.com/clinic",
        "https://m.facebook.com/page",
        "https://web.whatsapp.com/send?phone=91",
        "https://wa.me/919800000000",
        "https://www.justdial.com/Pune/x",
    ],
)
def test_never_fetch_hosts_are_refused_before_any_request(url: str) -> None:
    assert host_blocked(url)

    async def go() -> None:
        c, seen = client({"*": (200, "ok")})
        async with c:
            with pytest.raises(NeverFetch):
                await c.get(url)
        assert seen == []  # not even robots.txt

    import asyncio

    asyncio.run(go())


def test_lookalike_hosts_are_not_blocked() -> None:
    assert not host_blocked("https://notlinkedin.com/x")
    assert not host_blocked("https://mybox.co/x")


async def test_a_redirect_to_a_never_fetch_host_is_refused() -> None:
    routes = {
        "https://clinic.example/robots.txt": (404, ""),
        "https://clinic.example/": httpx.Response(301, headers={"location": "https://www.facebook.com/clinic"}),
    }
    c, seen = client(routes)
    async with c:
        with pytest.raises(NeverFetch):
            await c.get("https://clinic.example/")
    assert all("facebook" not in str(r.url) for r in seen)


# ---- robots.txt --------------------------------------------------------------------------------------


ROBOTS = """
User-agent: *
Disallow: /search
Disallow: /*?q=
Allow: /search/about
Crawl-delay: 2

User-agent: BadBot
Disallow: /

User-agent: NumentLeadBot
Disallow: /private/
Disallow: /*.pdf$
"""


def test_robots_google_semantics() -> None:
    rules = RobotsRules.parse(ROBOTS)
    # our own group applies, the * group does not
    assert rules.allows("https://s.example/search?q=x", UA_TOKEN)
    assert not rules.allows("https://s.example/private/x", UA_TOKEN)
    assert not rules.allows("https://s.example/files/a.pdf", UA_TOKEN)
    assert rules.allows("https://s.example/files/a.pdf?x=1", UA_TOKEN)  # $ anchors the end
    # the * group for everyone else: wildcard, longest match wins, allow wins a tie
    assert not rules.allows("https://s.example/search?q=x", "otherbot")
    assert not rules.allows("https://s.example/clinic?q=x", "otherbot")
    assert rules.allows("https://s.example/search/about", "otherbot")
    assert rules.allows("https://s.example/clinic/abc", "otherbot")
    assert rules.allows("https://s.example/robots.txt", "badbot")
    assert not rules.allows("https://s.example/anything", "badbot")
    assert rules.crawl_delay("otherbot") == 2.0
    assert rules.crawl_delay(UA_TOKEN) == 0.0


def test_robots_plan_example() -> None:
    """Step 5.16 test 2: a robots.txt that disallows /search."""
    rules = RobotsRules.parse("User-agent: *\nDisallow: /search\n")
    assert not rules.allows("https://www.practo.com/search?q=x", UA_TOKEN)
    assert rules.allows("https://www.practo.com/clinic/abc", UA_TOKEN)


async def test_disallowed_url_is_skipped_without_fetching_it() -> None:
    routes = {"https://s.example/robots.txt": (200, "User-agent: *\nDisallow: /search\n"), "*": (200, "page")}
    c, seen = client(routes)
    async with c:
        res = await c.get("https://s.example/search?q=x")
        ok = await c.get("https://s.example/clinic/abc")
    assert res.state == "robots_skip" and res.reason == "disallowed by robots.txt"
    assert ok.ok
    assert [str(r.url) for r in seen] == ["https://s.example/robots.txt", "https://s.example/clinic/abc"]


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(401, False), (403, False), (404, True), (410, True), (500, None), (503, None), (429, None)],
)
async def test_robots_status_rules(status: int, allowed: bool | None) -> None:
    routes = {"https://s.example/robots.txt": (status, "x"), "*": (200, "page")}
    c, seen = client(routes)
    async with c:
        res = await c.get("https://s.example/page")
    if allowed:
        assert res.ok
    else:
        assert res.state == "robots_skip"
        assert ("unreachable" in res.reason) is (allowed is None)
    assert sum(1 for r in seen if r.url.path == "/robots.txt") == 1


async def test_robots_is_read_once_per_host() -> None:
    c, seen = client({"https://s.example/robots.txt": (200, "User-agent: *\nAllow: /\n"), "*": (200, "ok")})
    async with c:
        for path in ("a", "b", "c"):
            await c.get(f"https://s.example/{path}")
    assert sum(1 for r in seen if r.url.path == "/robots.txt") == 1


# ---- classification and blocks -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "state"),
    [
        (200, "<html><body>" + "Welcome to our clinic. " * 100 + "</body></html>", "ok"),
        (301, "", "ok"),
        (403, "", "blocked"),
        (429, "", "blocked"),
        (503, "", "blocked"),
        (401, "", "blocked"),
        (404, "", "broken"),
        (500, "", "broken"),
        (200, "<html><head><title>Just a moment...</title></head><body>Checking</body></html>", "blocked"),
        (200, "<html><body><div id='cf-chl-widget'></div>" + "x" * 3000 + "</body></html>", "blocked"),
        (200, "<html><body>Please complete the captcha to continue</body></html>", "blocked"),
    ],
)
def test_classify(status: int, body: str, state: str) -> None:
    assert classify(status, body, None)[0] == state


def test_a_recaptcha_contact_form_is_not_a_block() -> None:
    page = (
        "<html><head><title>Contact | Smile Dental</title>"
        "<script src='https://www.google.com/recaptcha/api.js'></script>"
        "<script src='https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js'></script></head><body>"
        + "<p>Book your appointment with our dentists in Baner. Call +91 98765 43210.</p>" * 40
        + "<footer>This site is protected by reCAPTCHA and the Google Privacy Policy.</footer></body></html>"
    )
    assert challenge_reason(page) is None
    assert classify(200, page, None)[0] == "ok"


@pytest.mark.parametrize(
    ("err", "state"),
    [
        (httpx.ConnectTimeout("timed out"), "unknown"),
        (httpx.ReadTimeout("timed out"), "unknown"),
        (httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"), "unknown"),
        (httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known"), "broken"),
        (httpx.ConnectError("[Errno -2] Name or service not known"), "broken"),
        (httpx.ConnectError("[Errno -3] Temporary failure in name resolution"), "unknown"),
        (httpx.RemoteProtocolError("Server disconnected"), "unknown"),
    ],
)
def test_classify_network_errors(err: Exception, state: str) -> None:
    assert classify(None, "", err)[0] == state


async def test_a_block_raises_and_the_host_is_not_tried_again() -> None:
    routes = {"https://b.example/robots.txt": (404, ""), "https://b.example/one": (403, "denied"), "*": (200, "x")}
    c, seen = client(routes)
    async with c:
        with pytest.raises(SourceBlocked) as err:
            await c.get("https://b.example/one")
        assert err.value.status == 403 and err.value.host == "b.example"
        count = len(seen)
        with pytest.raises(SourceBlocked, match="already blocked"):
            await c.get("https://b.example/two")
    assert len(seen) == count  # no network call for the second page


async def test_a_challenge_page_raises() -> None:
    page = "<html><head><title>Attention Required! | Cloudflare</title></head><body>blocked</body></html>"
    c, _ = client({"https://b.example/robots.txt": (404, ""), "https://b.example/": (200, page)})
    async with c:
        with pytest.raises(SourceBlocked):
            await c.get("https://b.example/")


async def test_official_apis_can_read_a_block_without_raising() -> None:
    c, _ = client({"https://api.example/v1": (429, '{"error": {"status": "RESOURCE_EXHAUSTED"}}')})
    async with c:
        res = await c.get("https://api.example/v1", check_robots=False, raise_on_block=False)
    assert res.state == "blocked" and res.status == 429


# ---- spacing, size cap, retries, identity --------------------------------------------------------------


async def test_requests_to_one_host_are_spaced() -> None:
    c, _ = client({"*": (200, "ok")}, min_gap_s=0.3)
    async with c:
        start = time.monotonic()
        await c.get("https://gap.example/a", check_robots=False)
        await c.get("https://gap.example/b", check_robots=False)
        await c.get("https://other.example/a", check_robots=False)  # another host does not wait
    assert 0.3 <= time.monotonic() - start < 0.9


async def test_crawl_delay_slows_a_host_down() -> None:
    routes = {"https://slow.example/robots.txt": (200, "User-agent: *\nCrawl-delay: 0.4\n"), "*": (200, "ok")}
    c, _ = client(routes, min_gap_s=0.0)
    async with c:
        await c.get("https://slow.example/a")
        start = time.monotonic()
        await c.get("https://slow.example/b")
    assert time.monotonic() - start >= 0.35


async def test_body_is_cut_at_the_size_cap() -> None:
    c, _ = client({"*": (200, "a" * 50_000)}, max_bytes=1000)
    async with c:
        res = await c.get("https://big.example/", check_robots=False)
    assert res.truncated and len(res.text) <= 1000


async def test_one_retry_on_a_timeout() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, text="ok")

    c, _ = client({"*": flaky})
    async with c:
        res = await c.get("https://flaky.example/", check_robots=False, retries=1)
    assert res.ok and calls["n"] == 2


async def test_honest_user_agent_and_no_proxy() -> None:
    c, seen = client({"*": (200, "ok")})
    async with c:
        await c.get("https://ua.example/", check_robots=False)
        assert c._client._trust_env is False
    assert seen[0].headers["user-agent"] == "NumentLeadBot/1.0 (+https://nument.in)"


async def test_redirects_are_followed_and_checked_per_hop() -> None:
    routes = {
        "https://r.example/robots.txt": (404, ""),
        "https://www.r.example/robots.txt": (200, "User-agent: *\nDisallow: /blocked\n"),
        "https://r.example/": httpx.Response(301, headers={"location": "https://www.r.example/home"}),
        "https://www.r.example/home": (200, "home page"),
        "https://r.example/old": httpx.Response(302, headers={"location": "https://www.r.example/blocked"}),
    }
    c, _ = client(routes)
    async with c:
        res = await c.get("https://r.example/")
        skipped = await c.get("https://r.example/old")
    assert res.ok and res.final_url == "https://www.r.example/home"
    assert skipped.state == "robots_skip"


async def test_location_reads_a_redirect_without_following_it() -> None:
    routes = {
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc": httpx.Response(
            302, headers={"location": "https://www.linkedin.com/posts/clinic-123"}
        )
    }
    c, seen = client(routes)
    async with c:
        target = await c.location("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc")
    assert target == "https://www.linkedin.com/posts/clinic-123"
    assert len(seen) == 1 and "linkedin" not in str(seen[0].url)


def test_secrets_in_query_strings_are_redacted() -> None:
    assert (
        redact("https://a.example/x?url=1&key=SECRET&app_key=K2")
        == "https://a.example/x?url=1&key=REDACTED&app_key=REDACTED"
    )
