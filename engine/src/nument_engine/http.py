"""Polite HTTP: every outbound request of the engine goes through `PoliteClient` (Steps 5.2 and 18.1).

What it guarantees, whatever the caller does:
- Never-fetch hosts (LinkedIn, X, Instagram, Facebook, WhatsApp and the rest of `NEVER_FETCH`) are refused before
  a socket opens, including when a redirect points at them.
- One honest User-Agent (`USER_AGENT`), no proxies (`trust_env=False`), no header spoofing, no cookies kept.
- robots.txt is read once per host per 24 hours and obeyed for our product token, then `*`. Wildcards (`*`, `$`)
  and the longest-match rule follow the Google interpretation, which `urllib.robotparser` does not implement.
- A minimum gap between requests to one host: the policy's gap, or the site's Crawl-delay when larger.
- Redirects are followed by hand (at most 5), so every hop is checked against the never-fetch list and robots.txt.
- Bodies are cut at a size cap, and every response is classified (`ok`, `blocked`, `broken`, `unknown`).
- A block (401, 403, 429, 503 or a challenge page) raises `SourceBlocked`, and the host is never retried in the
  same run. Nothing here tries to get around a block.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Self
from urllib.parse import quote, unquote, urlsplit

import httpx

from .settings import get_settings

# --------------------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------------------

# Union of Step 5.2.1 and Step 18.1.1. Subdomains are covered too (m.facebook.com, in.linkedin.com).
NEVER_FETCH: frozenset[str] = frozenset(
    {
        "linkedin.com",
        "x.com",
        "twitter.com",
        "t.co",
        "instagram.com",
        "facebook.com",
        "fb.com",
        "fb.me",
        "threads.net",
        "tiktok.com",
        "whatsapp.com",  # web.whatsapp.com, api.whatsapp.com: we build links to these, never fetch them
        "wa.me",
        "truecaller.com",
        "reddit.com",
        "justdial.com",
        "indiamart.com",
        "sulekha.com",
    }
)

Policy = Literal["official_api", "open_data", "public", "grey"]
FetchState = Literal["ok", "blocked", "broken", "unknown", "robots_skip"]

# Minimum seconds between two requests to one host (Step 18.1.3). Adapters may ask for a slower gap.
POLICY_GAP_S: dict[str, float] = {"official_api": 0.2, "open_data": 3.0, "public": 2.0, "grey": 6.0}

MAX_BYTES = 6_000_000  # Step 5.2.1: some site builders put content late in huge pages
MAX_REDIRECTS = 5
ROBOTS_TTL_S = 24 * 3600
ROBOTS_MAX_BYTES = 500_000  # Google reads at most 500 KiB of robots.txt
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0, read=20.0)

# Challenge pages. Strong markers only ever appear on interstitials, so they count anywhere in the head of the
# page. Weak markers also appear on real pages ("protected by reCAPTCHA" in a footer, a support article about
# "access denied"), so they count only in the title or on a page with very little visible text.
STRONG_CHALLENGE_MARKERS: tuple[str, ...] = (
    "cf-chl",
    "challenge-platform",
    "_cf_chl_opt",
    "cf_chl_",
    "captcha-delivery.com",
    "px-captcha",
    "distil_r_captcha",
    "incapsula incident",
    "/_incapsula_resource",
)
WEAK_CHALLENGE_MARKERS: tuple[str, ...] = (
    "just a moment",
    "attention required",
    "access denied",
    "are you a robot",
    "are you human",
    "verify you are human",
    "unusual traffic",
    "request blocked",
    "captcha",
    "checking your browser",
    "pardon our interruption",
    "ddos protection",
    "enable javascript and cookies to continue",
)
BLOCK_STATUSES = frozenset({401, 403, 429, 503})
SHORT_PAGE_CHARS = 1500  # visible text below this is treated as a possible interstitial

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-:.]+)""", re.I)

_DNS_DEAD = ("name or service not known", "nodename nor servname", "no address associated", "getaddrinfo failed")


class NeverFetch(Exception):
    """The URL is on a never-fetch host (A.4.2). Raised before any network call."""

    def __init__(self, url: str) -> None:
        super().__init__(f"never fetched: {host_of(url)}")
        self.url = url


class SourceBlocked(Exception):
    """A site answered with a block or a challenge page. The caller stops using it for this run."""

    def __init__(self, source: str, host: str, reason: str, status: int | None = None) -> None:
        super().__init__(f"{source} blocked at {host}: {reason}")
        self.source = source
        self.host = host
        self.reason = reason
        self.status = status


@dataclass
class FetchResult:
    """One fetched URL. `text` is empty unless the response had a body we could read."""

    url: str
    final_url: str
    status: int | None
    text: str
    state: FetchState
    reason: str = ""
    content_type: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    truncated: bool = False
    content: bytes = field(default=b"", repr=False)  # the raw body, for binary files such as gzipped sitemaps

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    def json(self) -> Any:
        """The body as JSON (raises ValueError on a non-JSON body)."""
        return json.loads(self.text)


# --------------------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------------------


def host_of(url: str) -> str:
    """Lower-case host without port and without a leading `www.`."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host.removeprefix("www.")


def host_blocked(url: str) -> bool:
    """True for never-fetch hosts and their subdomains (Step 18.1.1)."""
    host = host_of(url)
    return any(host == h or host.endswith("." + h) for h in NEVER_FETCH)


def _visible_text(html: str, limit: int = 20_000) -> str:
    text = _SCRIPT_STYLE.sub(" ", html[:limit])
    return _WS.sub(" ", _TAG.sub(" ", text)).strip()


def challenge_reason(body: str) -> str | None:
    """The marker that makes this page look like a bot check, or None."""
    head = body[:20_000].lower()
    for marker in STRONG_CHALLENGE_MARKERS:
        if marker in head:
            return marker
    title_match = _TITLE.search(body[:20_000])
    title = _WS.sub(" ", title_match.group(1)).strip().lower() if title_match else ""
    visible = _visible_text(body).lower()
    short = len(visible) < SHORT_PAGE_CHARS
    for marker in WEAK_CHALLENGE_MARKERS:
        if marker in title or (short and marker in visible):
            return marker
    return None


def classify(status: int | None, body: str, err: BaseException | None) -> tuple[FetchState, str]:
    """Step 5.2.1 table: what a response (or a network error) means for us."""
    if err is not None:
        msg = str(err).lower() or type(err).__name__.lower()
        if "certificate" in msg or "ssl" in msg or "tls" in msg:
            return "unknown", "TLS verification failed"
        if isinstance(err, httpx.TimeoutException | httpx.RemoteProtocolError | httpx.ReadError) or "reset" in msg:
            return "unknown", f"network: {msg[:80]}"
        if "temporary failure in name resolution" in msg:
            return "unknown", "dns temporarily unavailable"
        if any(hint in msg for hint in _DNS_DEAD):
            return "broken", "dns: host not found"
        return "broken", msg[:120]
    if status is None:
        return "unknown", "no response"
    if status in BLOCK_STATUSES:
        return "blocked", f"http {status}"
    if 200 <= status < 400:
        marker = challenge_reason(body) if body else None
        if marker:
            return "blocked", f"challenge page ({marker})"
        return "ok", str(status)
    return "broken", f"http {status}"


_SECRET_PARAM = re.compile(r"(?i)([?&][^=&]*(?:key|token|secret|password|signature|sig)[^=&]*=)[^&]*")


def redact(url: str) -> str:
    """The URL with secret-looking query values replaced, for anything that is stored or logged."""
    return _SECRET_PARAM.sub(r"\1REDACTED", url)


def _decode(raw: bytes, content_type: str) -> str:
    charset = None
    match = re.search(r"charset=([\w\-:.]+)", content_type or "", re.I)
    if match:
        charset = match.group(1)
    else:
        meta = _META_CHARSET.search(raw[:4096])
        if meta:
            charset = meta.group(1).decode("ascii", "ignore")
    for enc in (charset, "utf-8"):
        if not enc:
            continue
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------------------------------
# robots.txt with Google semantics
# --------------------------------------------------------------------------------------------------


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile("^" + regex + ("$" if anchored else ""))


def _norm_path(path: str) -> str:
    """Percent-encode consistently so `/caf%C3%A9` and `/café` compare equal."""
    return quote(unquote(path), safe="/?=&*$%:@!,;+~-._")


@dataclass
class RobotsGroup:
    agents: list[str]
    rules: list[tuple[bool, str, re.Pattern[str]]] = field(default_factory=list)  # (allow, pattern, regex)
    crawl_delay: float | None = None


@dataclass
class RobotsRules:
    """A parsed robots.txt. `allow_all` / `disallow_all` cover the status-code cases (Step 18.1.2)."""

    groups: list[RobotsGroup] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    allow_all: bool = False
    disallow_all: bool = False

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        rules = cls()
        current: RobotsGroup | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = RobotsGroup(agents=[])
                    rules.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if key == "sitemap":
                if value:
                    rules.sitemaps.append(value)
                continue
            if current is None:
                continue
            if key in ("allow", "disallow"):
                if not value:
                    continue  # "Disallow:" with nothing means allow everything; it adds no rule
                pattern = _norm_path(value if value.startswith(("/", "*")) else "/" + value)
                current.rules.append((key == "allow", pattern, _pattern_to_regex(pattern)))
            elif key == "crawl-delay":
                with contextlib.suppress(ValueError):
                    current.crawl_delay = float(value)
        return rules

    def _groups_for(self, token: str) -> list[RobotsGroup]:
        token = token.lower()
        specific = [g for g in self.groups if any(a != "*" and a and a in token for a in g.agents)]
        if specific:
            return specific
        return [g for g in self.groups if "*" in g.agents]

    def allows(self, url: str, token: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        parts = urlsplit(url)
        path = _norm_path(parts.path or "/") + (("?" + parts.query) if parts.query else "")
        if path == "/robots.txt":
            return True
        best: tuple[int, bool] | None = None
        for group in self._groups_for(token):
            for allow, pattern, regex in group.rules:
                if regex.match(path):
                    candidate = (len(pattern), allow)
                    # Longest match wins; on a tie the least restrictive rule (allow) wins.
                    if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and allow):
                        best = candidate
        return True if best is None else best[1]

    def crawl_delay(self, token: str) -> float:
        delays = [g.crawl_delay for g in self._groups_for(token) if g.crawl_delay is not None]
        return max(delays) if delays else 0.0


# Process-wide request times, so two clients in one process still space their requests to a host. Plain data
# only (no asyncio objects), so it is safe across event loops. robots.txt is cached per client: one client
# serves one source for one run, which is the "once per host per run" of Step 5.2.1.
_LAST_REQUEST: dict[str, float] = {}  # host -> monotonic time of the last request


def reset_caches() -> None:
    """Forget request times (tests, and the start of a new run)."""
    _LAST_REQUEST.clear()


# --------------------------------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------------------------------


class PoliteClient:
    """One client per source per run. Use as `async with PoliteClient("apna", policy="grey") as http:`.

    Requests to one host are spaced by `min_gap_s` (or Crawl-delay). A blocked host raises `SourceBlocked`
    and is remembered, so later calls fail fast without touching the network.
    """

    def __init__(
        self,
        source: str,
        *,
        policy: Policy = "public",
        min_gap_s: float | None = None,
        max_bytes: int = MAX_BYTES,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.source = source
        self.policy = policy
        self.min_gap = POLICY_GAP_S[policy] if min_gap_s is None else min_gap_s
        self.max_bytes = max_bytes
        self.user_agent = settings.user_agent
        self.robots_token = self.user_agent.split("/", 1)[0].strip().lower() or "*"
        self.requests = 0  # network requests made, robots.txt included (source_health.requests_today)
        self.blocked_hosts: dict[str, str] = {}
        self._robots: dict[str, tuple[float, RobotsRules | None]] = {}  # base url -> (read at, rules or None)
        self._locks: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en",
            },
            timeout=timeout,
            follow_redirects=False,  # handled by hand: every hop is checked
            http2=True,
            trust_env=False,  # never pick up proxy settings from the environment (Step 18.1.6)
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- spacing ---------------------------------------------------------------------------------
    async def _wait_turn(self, host: str, gap: float) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = gap - (time.monotonic() - _LAST_REQUEST.get(host, float("-inf")))
            if delay > 0:
                await asyncio.sleep(delay)
            _LAST_REQUEST[host] = time.monotonic()

    def _gap_for(self, url: str) -> float:
        rules = self._cached_robots(url)
        delay = rules.crawl_delay(self.robots_token) if rules else 0.0
        return max(self.min_gap, min(delay, 60.0))  # a silly Crawl-delay never stalls a run for more than 60 s

    # ---- robots.txt --------------------------------------------------------------------------------
    @staticmethod
    def _robots_key(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}".lower()

    def _cached_robots(self, url: str) -> RobotsRules | None:
        entry = self._robots.get(self._robots_key(url))
        return entry[1] if entry else None

    async def robots(self, url: str) -> RobotsRules | None:
        """Rules for the host of `url`, or None when robots.txt could not be read (skip the host this run)."""
        key = self._robots_key(url)
        entry = self._robots.get(key)
        if entry and time.monotonic() - entry[0] < ROBOTS_TTL_S:
            return entry[1]
        res = await self._fetch(
            key + "/robots.txt",
            max_bytes=ROBOTS_MAX_BYTES,
            robots_check=False,
            raise_on_block=False,
            register_block=False,
        )
        rules: RobotsRules | None
        if res.status in (401, 403):
            rules = RobotsRules(disallow_all=True)  # Step 18.1.2: treat the whole host as disallowed
        elif res.state == "blocked" and res.status is not None and res.status < 400:
            rules = RobotsRules(disallow_all=True)  # a bot wall in front of robots.txt
        elif res.status is not None and 200 <= res.status < 300:
            rules = RobotsRules.parse(res.text)
        elif res.status is not None and 400 <= res.status < 500 and res.status != 429:
            rules = RobotsRules(allow_all=True)  # missing robots.txt: everything is allowed
        else:
            rules = None  # 5xx, 429, timeout or network error: unknown, skip the host this run
        self._robots[key] = (time.monotonic(), rules)
        return rules

    async def robots_allows(self, url: str) -> bool:
        rules = await self.robots(url)
        return rules is not None and rules.allows(url, self.robots_token)

    # ---- requests ----------------------------------------------------------------------------------
    def _check_blocked_host(self, url: str) -> None:
        host = host_of(url)
        if host in self.blocked_hosts:
            raise SourceBlocked(self.source, host, f"already blocked this run: {self.blocked_hosts[host]}")

    async def _fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
        robots_check: bool = True,
        raise_on_block: bool = True,
        register_block: bool = True,
    ) -> FetchResult:
        """One request with hand-followed redirects. Never-fetch, robots and spacing apply to every hop."""
        limit = max_bytes or self.max_bytes
        current = url
        request = self._client.build_request(method, current, params=params, json=json_body, headers=headers)
        current = str(request.url)
        for _hop in range(MAX_REDIRECTS + 1):
            if host_blocked(current):
                raise NeverFetch(current)
            self._check_blocked_host(current)
            if robots_check and not await self.robots_allows(current):
                rules = self._cached_robots(current)
                why = "robots.txt unreachable" if rules is None else "disallowed by robots.txt"
                return FetchResult(redact(url), redact(current), None, "", "robots_skip", why)
            host = host_of(current)
            await self._wait_turn(host, self._gap_for(current))
            self.requests += 1
            try:
                response = await self._client.send(request, stream=True)
            except httpx.HTTPError as exc:
                state, reason = classify(None, "", exc)
                return FetchResult(redact(url), redact(current), None, "", state, reason)
            try:
                if response.has_redirect_location and response.next_request is not None:
                    request = response.next_request
                    current = str(request.url)
                    continue
                chunks: list[bytes] = []
                size = 0
                truncated = False
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= limit:
                        truncated = True
                        break
                content_type = response.headers.get("content-type", "")
                raw = b"".join(chunks)[:limit]
                body = _decode(raw, content_type)
            except httpx.HTTPError as exc:
                state, reason = classify(None, "", exc)
                return FetchResult(redact(url), redact(current), response.status_code, "", state, reason)
            finally:
                await response.aclose()
            state, reason = classify(response.status_code, body, None)
            result = FetchResult(
                redact(url),
                redact(current),
                response.status_code,
                body,
                state,
                reason,
                content_type=content_type,
                headers={k.lower(): v for k, v in response.headers.items() if k.lower() in _KEPT_HEADERS},
                truncated=truncated,
                content=raw,
            )
            if state == "blocked" and register_block:
                self.blocked_hosts[host] = reason
                if raise_on_block:
                    raise SourceBlocked(self.source, host, reason, response.status_code)
            return result
        return FetchResult(redact(url), redact(current), None, "", "broken", f"more than {MAX_REDIRECTS} redirects")

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        check_robots: bool = True,
        raise_on_block: bool = True,
        max_bytes: int | None = None,
        retries: int = 0,
    ) -> FetchResult:
        """Polite GET. `check_robots=False` only for official APIs. `retries` re-tries timeouts and 5xx once each."""
        result = await self._fetch(
            url,
            params=params,
            headers=headers,
            max_bytes=max_bytes,
            robots_check=check_robots,
            raise_on_block=raise_on_block,
        )
        for _ in range(retries):
            transient = result.state == "unknown" or (result.status is not None and result.status in (500, 502, 504))
            if not transient or result.reason == "TLS verification failed":
                break
            await asyncio.sleep(2.0)
            result = await self._fetch(
                url,
                params=params,
                headers=headers,
                max_bytes=max_bytes,
                robots_check=check_robots,
                raise_on_block=raise_on_block,
            )
        return result

    async def reserve(self, url: str) -> str | None:
        """Every rule of a fetch except the fetch itself, for a page another client (the browser) will load:
        never-fetch and blocked hosts raise, robots.txt is checked, the host's gap is waited and the request is
        counted. Returns None when the page may be loaded now, or the reason it must be skipped."""
        if host_blocked(url):
            raise NeverFetch(url)
        self._check_blocked_host(url)
        if not await self.robots_allows(url):
            return "robots.txt unreachable" if self._cached_robots(url) is None else "disallowed by robots.txt"
        await self._wait_turn(host_of(url), self._gap_for(url))
        self.requests += 1
        return None

    def mark_blocked(self, url: str, reason: str) -> None:
        """Remember a host as blocked for this run (a block seen by the browser counts too)."""
        self.blocked_hosts[host_of(url)] = reason

    async def location(self, url: str) -> str | None:
        """The Location header of one redirect, without following it and without reading any body.

        Used to resolve search citation links (a Google redirector) into the cited URL. The target is never
        requested, so this is safe even when the target is a never-fetch host.
        """
        if host_blocked(url):
            raise NeverFetch(url)
        self._check_blocked_host(url)
        await self._wait_turn(host_of(url), self.min_gap)
        self.requests += 1
        request = self._client.build_request("GET", url)
        try:
            response = await self._client.send(request, stream=True)
        except httpx.HTTPError:
            return None
        try:
            if response.has_redirect_location and response.next_request is not None:
                return str(response.next_request.url)
            return None
        finally:
            await response.aclose()

    async def post_json(
        self,
        url: str,
        body: Any,
        *,
        headers: Mapping[str, str] | None = None,
        raise_on_block: bool = False,
    ) -> FetchResult:
        """POST for official APIs only (no robots.txt; the caller handles API status codes)."""
        return await self._fetch(
            url, method="POST", json_body=body, headers=headers, robots_check=False, raise_on_block=raise_on_block
        )


_KEPT_HEADERS = frozenset({"content-type", "last-modified", "etag", "retry-after", "location"})
