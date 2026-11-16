"""Cheap public probes per startup (15 Nov 2026): how old the domain is, when it got its first certificate and its
first archive capture, who runs its mail and which tools verified it, its GitHub organisation and its apps.

Every probe stores only what its source states, as one `facts` row of contract 4.2 (`probe.<name>`; the night
phase in `pipeline/probe.py` writes it):

| probe | source | value |
|---|---|---|
| domain_created | RDAP through the rdap.org bootstrap | date, registrar |
| first_cert | crt.sh, earliest certificate | date |
| first_capture | Wayback CDX, earliest capture | date |
| dns | MX and TXT records (dnspython) | mx_provider, txt_hints |
| github | GitHub REST, the organisation linked from the site (or named like it, when its profile links back) | org, public_repos, last_push, members_public |
| app_links | the site's apple-app-site-association and assetlinks.json | ios_app_ids, android_packages |
| app_store | iTunes Search and Lookup | name, seller, url, released |

Rules every probe keeps:
- Every request goes through `PoliteClient`. RDAP, the Wayback CDX server, the GitHub REST API and the iTunes
  Search API are official APIs (no robots.txt). crt.sh documents no API and its robots.txt disallows every path,
  so it is asked like any website: robots.txt decides (today it says no, so `first_cert` stays empty). The two
  app-link files live on the startup's own site, where robots.txt applies too.
- Short timeouts, no retries: a probe that times out or gets a malformed answer is an `error`; the night phase
  tries it again the next night. A block (403, 429, 503 or a challenge page) stops that source for the run.
- GitHub without a token allows 60 requests an hour: at most `probes.github_per_run` requests a run, and a rate
  limit answer stops GitHub for the run. Only organisation profiles, the most recently pushed repository and the
  public member count are read: never commits, events or anyone's email.
- An app or organisation linked from the site is accepted only when its own profile points back to the
  startup (the same web domain) or carries the startup's name; a search result only when its seller website is
  the startup's domain. An app named in the site's own apple-app-site-association file is the site's by
  definition.
- Sites on a shared host (acme.webflow.io, acme.vercel.app) have no domain of their own: the domain probes and
  the app-link files would describe the platform, so only Wayback, GitHub and the App Store are asked.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from ..http import FetchResult, NeverFetch, PoliteClient, SourceBlocked
from ..logging import get_logger
from ..normalize import SHARED_HOSTS, web_domain

log = get_logger()

State = Literal["ok", "none", "error", "skipped", "robots"]
PROBES: tuple[str, ...] = (
    "domain_created",
    "first_cert",
    "first_capture",
    "dns",
    "github",
    "app_links",
    "app_store",
)
FIELDS: dict[str, str] = {name: f"probe.{name}" for name in PROBES}

API_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
SLOW_TIMEOUT = httpx.Timeout(20.0, connect=5.0)  # crt.sh and the Wayback CDX server answer slowly
DNS_LIFETIME_S = 4.0
MAX_JSON_BYTES = 5_000_000
QUOTE_CHARS = 300
RDAP_GAP_S = 1.1  # rdap.org: at most 10 requests in 10 seconds
WAYBACK_GAP_S = 1.5
CRTSH_GAP_S = 2.0
GITHUB_GAP_S = 0.5
ITUNES_GAP_S = 3.1  # the iTunes Search API: about 20 calls a minute
SITE_GAP_S = 2.0
GITHUB_REQUESTS = 50  # default of settings probes.github_per_run (GitHub allows 60 an hour without a token)
GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
MAX_IDS = 10

# Hosts where many unrelated sites live on subdomains (on top of normalize.SHARED_HOSTS).
PLATFORM_HOSTS: frozenset[str] = SHARED_HOSTS | frozenset(
    {
        "bubbleapps.io",
        "lovable.app",
        "lovableproject.com",
        "replit.app",
        "repl.co",
        "replit.dev",
        "framer.website",
        "framer.app",
        "framer.ai",
        "glide.page",
        "glideapp.io",
        "softr.app",
        "bolt.host",
        "flutterflow.app",
        "adalo.com",
        "thunkable.app",
        "wixstudio.io",
        "squarespace.com",
        "super.site",
        "onrender.com",
        "fly.dev",
        "up.railway.app",
        "azurewebsites.net",
        "appspot.com",
    }
)


@dataclass
class Outcome:
    """What one probe learned. Only `ok` carries a value and becomes a fact; `none` means the source answered
    and there is nothing to store; `robots` that robots.txt said no; `skipped` that it was not asked (blocked
    source, request cap); `error` a timeout or a malformed answer."""

    state: State
    value: dict[str, Any] | None = None
    url: str | None = None
    quote: str = ""
    reason: str = ""


def ok(value: dict[str, Any], url: str, quote: str) -> Outcome:
    return Outcome("ok", value, url, _clip(quote))


def none(reason: str) -> Outcome:
    return Outcome("none", reason=reason)


def error(reason: str) -> Outcome:
    return Outcome("error", reason=reason[:200])


def _clip(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:QUOTE_CHARS]


def _compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _day(text: Any) -> str | None:
    """'2024-03-01T04:00:00Z' -> '2024-03-01'; None when it is not a date."""
    raw = str(text or "").strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


@dataclass
class Target:
    """One startup as the probes see it."""

    business_id: str
    name: str
    host: str  # the live site's host (www.acme.io)
    domain: str | None  # its own registrable domain; None on a shared host
    country: str
    github: list[str] = field(default_factory=list)  # owners linked from its pages
    app_store: list[str] = field(default_factory=list)  # App Store ids linked from its pages

    @property
    def platform_hosted(self) -> bool:
        return self.domain is None


def on_platform_host(host: str | None) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return "/" in host or any(host.endswith("." + h) for h in PLATFORM_HOSTS)


_HOSTNAME = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")


def target_of(row: dict[str, Any]) -> Target | None:
    """A Target from a businesses row (with `extra.crawl` from the research stage); None without a usable host."""
    extra = row.get("extra") or {}
    crawl = extra.get("crawl") or {}
    site = str(crawl.get("final_url") or row.get("website") or "")
    host = (urlsplit(site if "://" in site else f"https://{site}").hostname or "").lower().rstrip(".")
    if not _HOSTNAME.match(host):
        return None
    own = web_domain(f"https://{host}")
    shared = on_platform_host(host) or on_platform_host(row.get("web_domain")) or own is None
    domain = None if shared else own
    profiles = crawl.get("profiles") or {}
    return Target(
        business_id=str(row["id"]),
        name=str(row.get("name") or ""),
        host=host,
        domain=domain if domain and _HOSTNAME.match(domain) else None,
        country=str(row.get("country") or "us").lower(),
        github=[str(o) for o in profiles.get("github") or []][:MAX_IDS],
        app_store=[str(i) for i in profiles.get("app_store") or [] if str(i).isdigit()][:MAX_IDS],
    )


# ---------------------------------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------------------------------


class Resolver(Protocol):
    async def query(self, name: str, rdtype: str) -> list[str] | None:
        """Records as text ([] when the name has none), or None when the lookup failed."""
        ...


class DnsResolver:
    """dnspython's asyncio resolver with a short lifetime. Created on first use (tests never touch it)."""

    def __init__(self, lifetime: float = DNS_LIFETIME_S) -> None:
        self.lifetime = lifetime
        self._resolver: Any = None

    async def query(self, name: str, rdtype: str) -> list[str] | None:
        import dns.asyncresolver
        import dns.exception
        import dns.resolver

        if self._resolver is None:
            self._resolver = dns.asyncresolver.Resolver()
            self._resolver.lifetime = self.lifetime
            self._resolver.timeout = self.lifetime / 2
        try:
            answer = await self._resolver.resolve(name, rdtype, search=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except dns.exception.DNSException:
            return None
        if rdtype == "MX":
            return [f"{r.preference} {r.exchange.to_text(omit_final_dot=True)}" for r in answer]
        return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]


MX_PROVIDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("google", ("google.com", "googlemail.com")),
    ("microsoft", ("outlook.com", "hotmail.com", "office365.us")),
    ("zoho", ("zoho.com", "zoho.in", "zoho.eu", "zoho.com.au", "zoho.jp", "zohomail.com")),
)
TXT_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.I))
    for name, pattern in (
        ("google_workspace", r"include:_spf\.google\.com"),
        ("microsoft_365", r"include:spf\.protection\.outlook\.com|^ms=ms\d+"),
        ("zoho", r"include:zoho(?:mail)?\.|^zoho-verification="),
        ("google_search_console", r"^google-site-verification="),
        ("stripe", r"^stripe-verification="),
        ("hubspot", r"hubspotemail\.net|^hubspot-developer-verification="),
        ("mailchimp", r"servers\.mcsv\.net|mandrillapp\.com"),
        ("sendgrid", r"sendgrid\.net"),
        ("mailgun", r"mailgun\.org"),
        ("amazon_ses", r"amazonses\.com"),
        ("postmark", r"spf\.mtasv\.net"),
        ("brevo", r"sendinblue\.com|spf\.brevo\.com|^brevo-code:|^sendinblue-code:"),
        ("salesforce", r"_spf\.salesforce\.com|exacttarget\.com"),
        ("zendesk", r"mail\.zendesk\.com|^zendeskverification="),
        ("freshworks", r"freshdesk\.com|freshworks\.com|freshemail\.io"),
        ("intercom", r"intercom\.io|intercom-mail"),
        ("klaviyo", r"klaviyo"),
        ("shopify", r"shops\.shopify\.com"),
        ("facebook", r"^facebook-domain-verification="),
        ("apple", r"^apple-domain-verification="),
        ("atlassian", r"^atlassian-domain-verification="),
        ("docusign", r"^docusign="),
        ("zoom", r"^zoom_verify_"),
        ("slack", r"^slack-domain-verification="),
        ("adobe", r"^adobe-idp-site-verification=|^adobe-sign-verification="),
        ("dropbox", r"^dropbox-domain-verification="),
        ("miro", r"^miro-verification="),
        ("twilio", r"^twilio-domain-verification="),
        ("canva", r"^canva-site-verification="),
        ("openai", r"^openai-domain-verification="),
        ("anthropic", r"^anthropic-domain-verification"),
        ("elevenlabs", r"^elevenlabs="),
        ("cursor", r"^cursor-domain-verification"),
        ("windsurf", r"^windsurf-verification="),
        ("lovable", r"^lovable_verification="),
    )
)


def mx_provider(records: Sequence[str]) -> str:
    """google | microsoft | zoho | other | none, from MX records ('10 aspmx.l.google.com')."""
    hosts = [r.split()[-1].lower().rstrip(".") for r in records if r.split()]
    hosts = [h for h in hosts if h not in ("", ".")]  # a null MX (RFC 7505) accepts no mail
    if not hosts:
        return "none"
    for provider, suffixes in MX_PROVIDERS:
        if any(h == s or h.endswith("." + s) for h in hosts for s in suffixes):
            return provider
    return "other"


def txt_hints(records: Sequence[str]) -> tuple[list[str], list[str]]:
    """(tool names, the records that named them) from TXT records."""
    names: list[str] = []
    matched: list[str] = []
    for record in records:
        text = record.strip().strip('"')
        for name, pattern in TXT_HINTS:
            if pattern.search(text):
                if name not in names:
                    names.append(name)
                if record not in matched:
                    matched.append(record)
    return sorted(names), matched


# ---------------------------------------------------------------------------------------------------
# Parsers (pure: the tests feed them saved answers)
# ---------------------------------------------------------------------------------------------------


def parse_rdap(data: Any) -> tuple[dict[str, Any], str] | None:
    """(value, quote) from an RDAP domain answer; None when it states no registration date. Raises ValueError
    when the answer is not an RDAP object."""
    if not isinstance(data, dict) or not isinstance(data.get("events", []), list):
        raise ValueError("not an RDAP domain object")
    event = next(
        (e for e in data.get("events") or [] if isinstance(e, dict) and e.get("eventAction") == "registration"), None
    )
    day = _day(event.get("eventDate")) if event else None
    if event is None or day is None:
        return None
    registrar: str | None = None
    for entity in data.get("entities") or []:
        if isinstance(entity, dict) and "registrar" in (entity.get("roles") or []):
            registrar = _vcard_name(entity.get("vcardArray"))
            break
    return {"date": day, "registrar": registrar}, _compact(event)


def _vcard_name(vcard: Any) -> str | None:
    if not (isinstance(vcard, list) and len(vcard) == 2 and isinstance(vcard[1], list)):
        return None
    for item in vcard[1]:
        if isinstance(item, list) and len(item) >= 4 and item[0] == "fn" and isinstance(item[3], str):
            return item[3].strip() or None
    return None


def parse_crtsh(data: Any) -> tuple[dict[str, Any], str] | None:
    """(value, quote) for the earliest certificate in a crt.sh JSON answer; None when there is none."""
    if not isinstance(data, list):
        raise ValueError("not a crt.sh list")
    rows = [r for r in data if isinstance(r, dict) and _day(r.get("not_before"))]
    if not rows:
        return None
    first = min(rows, key=lambda r: str(r.get("not_before")))
    excerpt = {k: first[k] for k in ("id", "common_name", "not_before", "issuer_name") if k in first}
    return {"date": _day(first.get("not_before"))}, _compact(excerpt)


def parse_cdx(data: Any) -> tuple[dict[str, Any], str] | None:
    """(value, quote) for the first capture in a Wayback CDX JSON answer (a header row, then captures)."""
    if not isinstance(data, list) or (data and not all(isinstance(r, list) for r in data)):
        raise ValueError("not a CDX table")
    if len(data) < 2:
        return None
    header, first = data[0], data[1]
    row = dict(zip(header, first, strict=False))
    stamp = str(row.get("timestamp") or "")
    if not re.fullmatch(r"\d{8,14}", stamp):
        raise ValueError("no timestamp in the first capture")
    try:
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])).isoformat()
    except ValueError as exc:
        raise ValueError("bad timestamp") from exc
    return {"date": day}, " ".join(str(v) for v in first)


_TEAM_APP_ID = re.compile(r"^[A-Z0-9]{10}\.[A-Za-z0-9][A-Za-z0-9.\-]*$")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")


def parse_aasa(data: Any) -> list[str]:
    """iOS app ids ('TEAMID.bundle.id') named in an apple-app-site-association file."""
    if not isinstance(data, dict):
        raise ValueError("not an apple-app-site-association object")
    found: list[str] = []

    def add(value: Any) -> None:
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and _TEAM_APP_ID.match(item) and item not in found:
                found.append(item)

    applinks = data.get("applinks") or {}
    if isinstance(applinks, dict):
        add(applinks.get("apps"))
        for detail in applinks.get("details") or []:
            if isinstance(detail, dict):
                add(detail.get("appID"))
                add(detail.get("appIDs"))
    for section in ("webcredentials", "appclips", "activitycontinuation"):
        part = data.get(section)
        if isinstance(part, dict):
            add(part.get("apps"))
    return found[:MAX_IDS]


def parse_assetlinks(data: Any) -> list[str]:
    """Android package names named in a Digital Asset Links file."""
    if not isinstance(data, list):
        raise ValueError("not an assetlinks list")
    found: list[str] = []
    for statement in data:
        target = statement.get("target") if isinstance(statement, dict) else None
        if isinstance(target, dict) and target.get("namespace") == "android_app":
            package = target.get("package_name")
            if isinstance(package, str) and _PACKAGE.match(package) and package not in found:
                found.append(package)
    return found[:MAX_IDS]


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _names_match(a: str, b: str) -> bool:
    """Same name once punctuation is gone ('TallyHQ' and 'tally-hq'), or one long name inside the other."""
    if len(a) < 3 or len(b) < 3:
        return False
    return a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a))


def links_back(url: Any, target: Target) -> bool:
    """True when a profile's website is the startup's own site."""
    raw = str(url or "").strip()
    if not raw:
        return False
    dom = web_domain(raw if "://" in raw else f"https://{raw}")
    return dom is not None and dom in {target.domain, web_domain(f"https://{target.host}")}


def names_target(names: Sequence[Any], target: Target) -> bool:
    ours = [_norm(target.name), _norm((target.domain or target.host).split(".")[0])]
    return any(_names_match(_norm(n), o) for n in names for o in ours)


def pick_app(
    results: Any, target: Target, *, trusted_ids: Sequence[str] = (), search: bool = False
) -> dict[str, Any] | None:
    """The startup's app among iTunes results. A search result must have the startup's site as its seller
    website; a looked-up id or bundle needs that or the startup's name (or to be trusted: named in its AASA)."""
    if not isinstance(results, list):
        raise ValueError("no results list")
    for app in results:
        if not isinstance(app, dict) or app.get("kind") not in ("software", "mac-software", None):
            continue
        if not app.get("trackName") or not app.get("trackViewUrl"):
            continue
        if links_back(app.get("sellerUrl"), target):
            return app
        if search:
            continue
        if str(app.get("trackId")) in trusted_ids or str(app.get("bundleId")) in trusted_ids:
            return app
        if names_target([app.get("sellerName"), app.get("artistName")], target):
            return app
    return None


def app_value(app: dict[str, Any]) -> tuple[dict[str, Any], str]:
    parts = urlsplit(str(app.get("trackViewUrl")))
    store_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    value = {
        "name": str(app.get("trackName")),
        "seller": str(app.get("sellerName") or app.get("artistName") or "") or None,
        "url": store_url,
        "released": _day(app.get("releaseDate")),
    }
    excerpt = {k: app[k] for k in ("trackName", "sellerName", "releaseDate", "sellerUrl") if k in app}
    return value, _compact(excerpt)


# ---------------------------------------------------------------------------------------------------
# The probes
# ---------------------------------------------------------------------------------------------------


def _json(res: FetchResult) -> Any:
    try:
        return json.loads(res.text)
    except ValueError as exc:
        raise ValueError(f"malformed JSON from {urlsplit(res.final_url).hostname}") from exc


class Probes:
    """The probes of one night run, each source with its own client and pace. Use as an async context manager."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
        github_requests: int = GITHUB_REQUESTS,
    ) -> None:
        def client(
            source: str, policy: Literal["official_api", "public"], gap: float, timeout: httpx.Timeout
        ) -> PoliteClient:
            return PoliteClient(
                source, policy=policy, min_gap_s=gap, timeout=timeout, max_bytes=MAX_JSON_BYTES, transport=transport
            )

        self.rdap = client("probes.rdap", "official_api", RDAP_GAP_S, API_TIMEOUT)
        self.crtsh = client("probes.crtsh", "public", CRTSH_GAP_S, SLOW_TIMEOUT)
        self.wayback = client("probes.wayback", "official_api", WAYBACK_GAP_S, SLOW_TIMEOUT)
        self.github_http = client("probes.github", "official_api", GITHUB_GAP_S, API_TIMEOUT)
        self.itunes = client("probes.itunes", "official_api", ITUNES_GAP_S, API_TIMEOUT)
        self.sites = client("probes.sites", "public", SITE_GAP_S, API_TIMEOUT)
        self.resolver: Resolver = resolver or DnsResolver()
        self.github_left = github_requests

    async def __aenter__(self) -> Probes:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        for http in (self.rdap, self.crtsh, self.wayback, self.github_http, self.itunes, self.sites):
            await http.aclose()

    @property
    def requests(self) -> int:
        return sum(h.requests for h in (self.rdap, self.crtsh, self.wayback, self.github_http, self.itunes, self.sites))

    # ---- one call with every failure turned into an Outcome --------------------------------------------------
    async def _call(self, fn: Callable[[], Awaitable[Outcome]]) -> Outcome:
        try:
            return await fn()
        except SourceBlocked as err:
            return Outcome("skipped", reason=f"blocked: {err.reason}"[:200])
        except NeverFetch:
            return Outcome("skipped", reason="never-fetch host")
        except ValueError as exc:  # malformed answers
            return error(str(exc))
        except (httpx.HTTPError, OSError) as exc:
            return error(f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # a probe never stops the run: anything unexpected is this probe's error
            log.warning("probes.unexpected_error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
            return error(f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _failed(res: FetchResult) -> Outcome | None:
        """The Outcome of an answer that is not a 200, or None for a usable answer."""
        if res.state == "robots_skip":
            return Outcome("robots", reason=res.reason)
        if res.status in (404, 410):
            return none(f"http {res.status}")
        if not res.ok:
            return error(res.reason or f"http {res.status}")
        if res.truncated:
            return error("answer too large")
        return None

    async def run(self, name: str, target: Target) -> Outcome:
        """One probe by name (`PROBES`) for one startup."""
        probe: Callable[[Target], Awaitable[Outcome]] = getattr(self, name)
        return await self._call(lambda: probe(target))

    async def probe(self, target: Target, due: set[str], time_left: Callable[[], float]) -> dict[str, Outcome]:
        """The due probes of one startup, side by side. App links run before the App Store (the bundle ids in
        the site's AASA file are the surest way to its app), so asking for either runs both. A probe still
        waiting when `time_left()` runs out is left out of the answer (it is due again next night)."""
        if due & {"app_links", "app_store"}:
            due = due | {"app_links", "app_store"}

        async def timed(fn: Callable[[], Awaitable[Outcome]]) -> Outcome | None:
            left = time_left()
            if left <= 0:
                return None
            try:
                return await asyncio.wait_for(self._call(fn), timeout=left)
            except TimeoutError:
                return None

        async def single(name: str) -> tuple[str, Outcome | None]:
            return name, await timed(lambda: self.run(name, target))

        async def apps() -> list[tuple[str, Outcome | None]]:
            links = await timed(lambda: self.app_links(target))
            ios = list((links.value or {}).get("ios_app_ids") or []) if links is not None else []
            store = await timed(lambda: self.app_store(target, ios))
            return [("app_links", links), ("app_store", store)]

        singles = [n for n in PROBES if n in due and n not in ("app_links", "app_store")]
        jobs: list[Awaitable[Any]] = [single(n) for n in singles]
        if "app_links" in due:
            jobs.append(apps())
        out: dict[str, Outcome] = {}
        for result in await asyncio.gather(*jobs):
            for name, outcome in result if isinstance(result, list) else [result]:
                if outcome is not None:
                    out[name] = outcome
        return out

    # ---- domain age ---------------------------------------------------------------------------------------
    async def domain_created(self, target: Target) -> Outcome:
        if target.domain is None:
            return none("shared host")
        url = f"https://rdap.org/domain/{quote(target.domain)}"
        res = await self.rdap.get(url, check_robots=False, headers={"Accept": "application/rdap+json"})
        failed = self._failed(res)
        if failed is not None:
            return failed
        parsed = parse_rdap(_json(res))
        if parsed is None:
            return none("no registration date")
        return ok(parsed[0], res.final_url, parsed[1])

    async def first_cert(self, target: Target) -> Outcome:
        if target.domain is None:
            return none("shared host")
        url = f"https://crt.sh/?q={quote(target.domain)}&output=json"
        res = await self.crtsh.get(url, check_robots=True)  # not an official API: robots.txt decides
        failed = self._failed(res)
        if failed is not None:
            return failed
        parsed = parse_crtsh(_json(res))
        if parsed is None:
            return none("no certificate")
        return ok(parsed[0], res.final_url, parsed[1])

    async def first_capture(self, target: Target) -> Outcome:
        site = target.domain or target.host
        url = f"https://web.archive.org/cdx/search/cdx?url={quote(site)}&output=json&limit=1&fl=timestamp,original,statuscode"
        res = await self.wayback.get(url, check_robots=False)
        failed = self._failed(res)
        if failed is not None:
            return failed
        parsed = parse_cdx(_json(res))
        if parsed is None:
            return none("never captured")
        return ok(parsed[0], res.final_url, parsed[1])

    # ---- DNS ----------------------------------------------------------------------------------------------
    async def dns(self, target: Target) -> Outcome:
        if target.domain is None:
            return none("shared host")
        mx, txt = await asyncio.gather(
            self.resolver.query(target.domain, "MX"), self.resolver.query(target.domain, "TXT")
        )
        if mx is None or txt is None:
            return error("dns lookup failed")
        hints, matched = txt_hints(txt)
        provider = mx_provider(mx)
        parts = [f"MX {'; '.join(sorted(mx)[:2])}" if mx else "no MX record"]
        parts += [f"TXT {r[:80]}" for r in matched[:3]]
        return ok({"mx_provider": provider, "txt_hints": hints}, f"dns:{target.domain}", "; ".join(parts))

    # ---- GitHub -------------------------------------------------------------------------------------------
    async def _github_get(self, path: str) -> FetchResult | None:
        if self.github_left <= 0:
            return None
        self.github_left -= 1
        return await self.github_http.get(f"{GITHUB_API}{path}", check_robots=False, headers=GITHUB_HEADERS)

    async def github(self, target: Target) -> Outcome:
        linked = list(dict.fromkeys(target.github))
        guess = re.sub(r"[^a-z0-9-]", "", (target.domain or target.host).split(".")[0].lower())
        candidates = [(o, True) for o in linked]
        if guess and guess.lower() not in {o.lower() for o in linked}:
            candidates.append((guess, False))  # a guess must have the startup's site on its profile
        for owner, was_linked in candidates:
            res = await self._github_get(f"/orgs/{quote(owner)}")
            if res is None:
                return Outcome("skipped", reason="GitHub request cap reached")
            if res.status in (404, 410):
                continue  # no such organisation (or a person's account, which is never read)
            failed = self._failed(res)
            if failed is not None:
                return failed
            org = _json(res)
            if not isinstance(org, dict) or not org.get("login"):
                raise ValueError("malformed GitHub organisation")
            accepted = links_back(org.get("blog"), target) or (
                was_linked and names_target([org.get("login"), org.get("name")], target)
            )
            if accepted:
                return await self._github_org(org, res.final_url)
        return none("no GitHub organisation of this startup")

    async def _github_org(self, org: dict[str, Any], url: str) -> Outcome:
        login = str(org["login"])
        public_repos = org.get("public_repos")
        repos = int(public_repos) if isinstance(public_repos, int) else None
        last_push: str | None = None
        if repos:
            res = await self._github_get(
                f"/orgs/{quote(login)}/repos?type=public&sort=pushed&direction=desc&per_page=1"
            )
            if res is None:
                return Outcome("skipped", reason="GitHub request cap reached")
            failed = self._failed(res)
            if failed is not None and failed.state != "none":
                return failed
            items = _json(res) if failed is None else []
            if not isinstance(items, list):
                raise ValueError("malformed GitHub repository list")
            if items and isinstance(items[0], dict):
                last_push = _day(items[0].get("pushed_at"))
        res = await self._github_get(f"/orgs/{quote(login)}/public_members?per_page=100")
        if res is None:
            return Outcome("skipped", reason="GitHub request cap reached")
        failed = self._failed(res)
        if failed is not None and failed.state != "none":
            return failed
        members = _json(res) if failed is None else []
        if not isinstance(members, list):
            raise ValueError("malformed GitHub member list")
        value = {"org": login, "public_repos": repos, "last_push": last_push, "members_public": len(members)}
        excerpt = {k: org[k] for k in ("login", "name", "blog", "public_repos", "created_at") if k in org}
        return ok(value, url, _compact(excerpt))

    # ---- apps ---------------------------------------------------------------------------------------------
    async def _site_json(self, url: str, opener: str) -> tuple[Outcome | None, Any, FetchResult | None]:
        """(failure, parsed JSON, result) for a file on the startup's own site. A page that is not JSON at all
        (a soft 404 served as HTML) counts as no file."""
        res = await self.sites.get(url)
        failed = self._failed(res)
        if failed is not None:
            return failed, None, res
        body = res.text.lstrip("﻿ \t\r\n")
        if not body.startswith(opener):
            return none("no such file"), None, res
        return None, _json(res), res

    async def app_links(self, target: Target) -> Outcome:
        if target.domain is None:
            return none("shared host")
        aasa_url = f"https://{target.host}/.well-known/apple-app-site-association"
        links_url = f"https://{target.host}/.well-known/assetlinks.json"
        ios: list[str] = []
        android: list[str] = []
        problems: list[Outcome] = []
        failed, data, aasa_res = await self._site_json(aasa_url, "{")
        if failed is None:
            ios = parse_aasa(data)
        else:
            problems.append(failed)
        failed, data, links_res = await self._site_json(links_url, "[")
        if failed is None:
            android = parse_assetlinks(data)
        else:
            problems.append(failed)
        if ios or android:
            answered = aasa_res if ios else links_res
            url = answered.final_url if answered is not None else aasa_url
            quote_parts = [f'"appIDs":{_compact(ios)}'] if ios else []
            quote_parts += [f'"package_name":{_compact(android)}'] if android else []
            return ok({"ios_app_ids": ios, "android_packages": android}, url, ", ".join(quote_parts))
        for state in ("error", "skipped", "robots"):
            worst = next((p for p in problems if p.state == state), None)
            if worst is not None:
                return worst
        return none("no app links")

    async def app_store(self, target: Target, ios_app_ids: Sequence[str] = ()) -> Outcome:
        """The startup's iOS app: by the App Store ids its pages link to, by the bundle ids its AASA names,
        else a search by name kept only when the seller website is the startup's own."""
        bundles = list(dict.fromkeys(i.split(".", 1)[1] for i in ios_app_ids if "." in i))[:2]
        lookups: list[tuple[str, Sequence[str]]] = []
        if target.app_store:
            lookups.append((f"id={','.join(target.app_store[:MAX_IDS])}", ()))
        lookups += [(f"bundleId={quote(b)}", (b,)) for b in bundles]
        for params, trusted in lookups:
            url = f"https://itunes.apple.com/lookup?{params}&country={quote(target.country)}&entity=software"
            res = await self.itunes.get(url, check_robots=False)
            failed = self._failed(res)
            if failed is not None:
                return failed
            data = _json(res)
            if not isinstance(data, dict):
                raise ValueError("malformed iTunes answer")
            app = pick_app(data.get("results"), target, trusted_ids=trusted)
            if app is not None:
                value, excerpt = app_value(app)
                return ok(value, res.final_url, excerpt)
        if not target.name.strip():
            return none("no name to search")
        url = (
            f"https://itunes.apple.com/search?term={quote(target.name.strip())}&entity=software"
            f"&country={quote(target.country)}&limit=10"
        )
        res = await self.itunes.get(url, check_robots=False)
        failed = self._failed(res)
        if failed is not None:
            return failed
        data = _json(res)
        if not isinstance(data, dict):
            raise ValueError("malformed iTunes answer")
        app = pick_app(data.get("results"), target, search=True)
        if app is None:
            return none("no app sold from this site")
        value, excerpt = app_value(app)
        return ok(value, res.final_url, excerpt)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
