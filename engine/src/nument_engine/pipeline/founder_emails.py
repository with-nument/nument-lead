"""Founder emails (founder approved, 15 Nov 2026): the founder's own work address for every new A or B startup.

The ladder runs surest and cheapest first and stops at the first rung that gives a usable address:

1. published: their own site (the pages research read, plus the email facts and contacts verify kept);
2. archive: old copies of their contact, about and team pages in the Wayback Machine;
3. snippet: one grounded search `find_founder_email`, within `grounding.allowance("email_snippets")`. The
   address must be at their domain, fit the founder's name and appear word for word in a sentence the search
   results back. When the cited page can be read (never LinkedIn or X) and shows the address, it counts as
   published there (`post`, or `published` on their own site); otherwise it stays an unconfirmed `snippet`.
   Skipped when a published address at the domain already shows the naming pattern (a backed guess is cheaper);
4. store: the developer contact on their Google Play listing (packages from the `probe.app_links` fact);
5. filing: addresses in registry and filing records;
6. guess: a name pattern (first@, first.last@, flast@, firstlast@, f.last@, firstl@) checked by a free
   verification API without sending anything. Never on a free-mail domain, never without an MX record and never
   in a published-only country (config/outreach.yaml: Canada, Australia, New Zealand).

Labels (`contacts.email_status`):
- verified: a verifier said deliverable and the domain is not catch-all;
- likely: published by the person or company and not disproven, or a catch-all or risky answer for a pattern
  that a published address at the same domain backs;
- invalid: a verifier said undeliverable (stored only on a contact that already holds the address);
- unknown: anything else, and then the address is not stored at all (minimal personal data).

At most 5 live checks per lead in 30 days; answers are cached (`email_checks`) and so are domains
(`email_domains`). Suppressed addresses and domains, shared inboxes (info@, hello@) and do-not-contact founders
are never used. Every stored address keeps its evidence: `email_origin`, `email_pattern`, `source_url` and `quote`.
Each lead's attempt is kept in `businesses.extra.founder_email` (when, the outcome, checks used, when to retry).
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit

from .. import db
from ..http import NeverFetch, PoliteClient, SourceBlocked, host_blocked, host_of
from ..logging import get_logger
from ..normalize import is_free_builder, web_domain
from ..outreach import verifier as checks
from ..outreach.net import outreach_config
from ..segments import Segment, country_name
from ..sources.grounded_search import REDIRECT_HOSTS
from . import ai, grounding, score
from .evidence import on_domain, vget
from .lines import GENERIC_LOCAL
from .phones import FREEMAIL, emails_in_text, valid_email
from .runs import RunContext
from .verify import bare_name

log = get_logger()

TASK: Final = "find_founder_email"
PATTERNS: Final[tuple[str, ...]] = ("first", "first.last", "flast", "firstlast", "f.last", "firstl")
MAX_CHECKS: Final = 5  # live checks per lead in 30 days (founder rule, 15 Nov 2026)
WINDOW: Final = timedelta(days=30)
SEND_RESERVE: Final = 10  # live checks left each day for the re-check before sending (outreach verify_emails)
RESERVE_S: Final = 600  # stop this long before the run's deadline, so offers and messages still run
SETTING_LEADS: Final = "founder_emails.leads_per_run"
DEFAULT_LEADS: Final = 30
SETTING_ARCHIVE: Final = "founder_emails.archive_pages"
DEFAULT_ARCHIVE_PAGES: Final = 2
MAX_STORE_LISTINGS: Final = 2
MAX_SNIPPET_FAILURES: Final = 3
QUOTE_PAD: Final = 70
RETRY: Final[dict[str, timedelta]] = {
    "found": timedelta(days=1),  # only matters if the address is lost later (a bounce)
    "not_found": timedelta(days=30),
    "deferred": timedelta(days=1),  # a quota, a block or the AI stopped a rung: try again tomorrow
    "no_founder": timedelta(days=1),  # the people stage may name one later
    "no_domain": timedelta(days=7),
}
SUFFIXES: Final = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md", "mba", "cpa", "esq"})
FREE_MAIL: Final = FREEMAIL | frozenset(
    {"ymail.com", "rocketmail.com", "msn.com", "hotmail.co.uk", "yahoo.co.uk", "outlook.in", "live.in",
     "googlemail.co.uk", "pm.me", "tutanota.com", "tuta.io", "fastmail.com", "hey.com", "mail.com", "gmx.de",
     "gmx.net", "web.de", "yandex.com", "yandex.ru", "mail.ru", "qq.com", "163.com", "126.com", "naver.com",
     "zohomail.com", "inbox.com", "duck.com", "skiff.com"}
)  # fmt: skip
ARCHIVE_WORDS: Final = re.compile(
    r"contact|about|team|founder|people|imprint|impressum|legal|press|who-we-are|company|leadership", re.I
)
FILING_SOURCES: Final = frozenset({"sec_edgar", "art_registry"})
WAYBACK_CDX: Final = "https://web.archive.org/cdx/search/cdx"
WAYBACK_WEB: Final = "https://web.archive.org/web"
PLAY_DETAILS: Final = "https://play.google.com/store/apps/details"
MX_PROVIDERS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("google", ("google.com", "googlemail.com")),
    ("microsoft", ("outlook.com", "microsoft.com", "office365.us")),
    ("zoho", ("zoho.com", "zoho.eu", "zoho.in", "zoho.com.au", "zohomail.com")),
)
SOURCE_FOR: Final[dict[str, str]] = {
    "published": "website", "filing": "registry", "archive": "other", "post": "other", "store": "other",
    "snippet": "other", "guess": "other",
}  # fmt: skip
WHY: Final[dict[str, str]] = {
    "published": "the founder's own address, published on their site",
    "archive": "the founder's own address, on an old copy of their site",
    "post": "the founder's own address, on a public page about them",
    "snippet": "the founder's own address, in a search result",
    "store": "the founder's own address, on their app store listing",
    "filing": "the founder's own address, in a public filing",
    "guess": "the founder's name pattern at their domain, checked without sending",
}

Row = dict[str, Any]
Resolver = Callable[[str], list[str] | None]


# ---------------------------------------------------------------------------------------------------
# Names and patterns
# ---------------------------------------------------------------------------------------------------


def ascii_word(word: str) -> str:
    """'José' -> 'jose', "O'Neil" -> 'oneil'; letters only, lower case."""
    folded = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", folded.lower())


def name_parts(name: str | None) -> tuple[str, str] | None:
    """(first, last) as they would be spelled in an address, or None: a single name, initials only, or a
    script that has no plain-letter spelling (then nothing is guessed)."""
    clean = re.sub(r"\([^)]*\)", " ", bare_name(name or ""))
    words = [w for w in re.split(r"[\s,]+", clean) if w and w.lower().strip(".") not in SUFFIXES]
    if len(words) < 2:
        return None
    first, last = ascii_word(words[0]), ascii_word(words[-1])
    if len(first) < 2 or len(last) < 2:
        return None
    return first, last


def render(pattern: str, first: str, last: str) -> str:
    """The local part of an address for a naming pattern."""
    forms = {
        "first": first,
        "first.last": f"{first}.{last}",
        "flast": f"{first[0]}{last}",
        "firstlast": f"{first}{last}",
        "f.last": f"{first[0]}.{last}",
        "firstl": f"{first}{last[0]}",
    }
    return forms[pattern]


def infer_pattern(local: str, name: str | None) -> str | None:
    """The naming pattern an address's local part follows for this person, or None when it is not theirs."""
    parts = name_parts(name)
    if parts is None:
        return None
    low = local.strip().lower()
    return next((p for p in PATTERNS if render(p, *parts) == low), None)


def domain_of(email: str) -> str:
    return checks.domain_of(email)


def mx_provider(hosts: Sequence[str]) -> str:
    """google, microsoft, zoho, other, or none for a domain without mail servers."""
    if not hosts:
        return "none"
    for provider, suffixes in MX_PROVIDERS:
        if any(h.rstrip(".").lower().endswith(s) for h in hosts for s in suffixes):
            return provider
    return "other"


def lookup_mx(domain: str) -> list[str] | None:
    """MX hosts of a domain, best first; [] when it has none (or a null MX); None when DNS gave no answer."""
    import dns.exception
    import dns.resolver

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        return None
    hosts = [str(r.exchange).rstrip(".").lower() for r in sorted(answers, key=lambda r: r.preference)]
    return [h for h in hosts if h]


def visible(html: str) -> str:
    """Page text without scripts, styles and tags (quotes come from what a reader sees)."""
    text = re.sub(r"<(script|style|noscript)\b.*?</\1\s*>", " ", html, flags=re.I | re.S)
    return re.sub(r"<[^>]+>", " ", text)


def page_quote(html: str, email: str) -> str | None:
    return quote_around(visible(html), email) or quote_around(html, email)


def quote_around(text: str, email: str) -> str | None:
    """About 140 characters of the source around the address (whitespace collapsed), or None when the source
    does not show it."""
    low = text.lower()
    at = low.find(email.lower())
    size = len(email)
    if at < 0:
        at = low.find(email.split("@")[0].lower() + " ")  # an obfuscated form: name [at] domain [dot] com
        size = len(email.split("@")[0])
    if at < 0:
        return None
    snippet = text[max(0, at - QUOTE_PAD) : at + size + QUOTE_PAD]
    return re.sub(r"\s+", " ", snippet).strip()[:300] or None


# ---------------------------------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------------------------------


def label(origin: str, answer: checks.Check | None, *, backed: bool, catch_all_domain: bool | None) -> str:
    """verified, likely, invalid or unknown for one address (contract 4.4).

    verified: deliverable on a domain that is not catch-all. invalid: undeliverable. likely: published by the
    person or company and not disproven, or a catch-all or risky answer when a published address at the same
    domain backs the pattern. Everything else is unknown."""
    if answer is not None:
        if answer.result == "undeliverable":
            return "invalid"
        if answer.deliverable:
            return "verified"
    if origin in checks.PUBLISHED_ORIGINS:
        return "likely"
    risky = catch_all_domain is True or (answer is not None and (answer.result == "risky" or bool(answer.catch_all)))
    return "likely" if backed and risky else "unknown"


# ---------------------------------------------------------------------------------------------------
# Leads and their evidence
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """An address and where it came from. `founder` is the founder contact it belongs to, if any."""

    email: str
    origin: str
    url: str | None
    quote: str | None
    founder: Row | None = None
    person: str | None = None
    pattern: str | None = None


@dataclass
class Lead:
    lead_id: str
    business_id: str
    name: str
    domain: str
    country: str
    segment: Segment
    extra: dict[str, Any]
    founders: list[Row]
    people: list[str]
    contacts: list[Row]
    checks_used: int = 0
    window_start: datetime | None = None
    backed: set[str] = field(default_factory=set)  # patterns a published address at the domain shows
    tried: set[str] = field(default_factory=set)
    deferred: list[str] = field(default_factory=list)  # why a rung could not finish (retry tomorrow)

    @property
    def checks_left(self) -> int:
        return max(MAX_CHECKS - self.checks_used, 0)


@dataclass
class Outcome:
    kind: str  # found, not_found, deferred, no_founder, no_domain
    candidate: Candidate | None = None
    status: str | None = None
    answer: checks.Check | None = None


@dataclass
class Suppressed:
    emails: frozenset[str]
    domains: frozenset[str]

    @classmethod
    def load(cls) -> Suppressed:
        rows = db.fetch_all("select lower(email) as email, lower(web_domain) as domain from public.suppression")
        return cls(
            frozenset(str(r["email"]) for r in rows if r["email"]),
            frozenset(str(r["domain"]) for r in rows if r["domain"]),
        )


CANDIDATES_SQL: Final = """
select l.id::text as lead_id, b.id::text as business_id, b.name, b.website, b.web_domain, b.country,
       b.segment_id, b.extra
  from public.leads l
  join public.businesses b on b.id = l.business_id
 where l.stage = 'new'
   and l.grade in ('A', 'B')
   and b.segment_id = any(%(segments)s)
   and coalesce((b.extra #>> '{founder_email,next_at}')::timestamptz, '-infinity'::timestamptz) <= now()
   and not exists (select 1 from public.contacts c
                    where c.business_id = b.id and c.email is not null and not c.do_not_contact
                      and (c.line = 'owner' or c.is_decision_maker)
                      and c.email_status in ('verified', 'likely'))
 order by l.grade, l.created_at desc
 limit %(limit)s
"""
CONTACTS_SQL: Final = """
select id::text as id, name, role, email, source, source_url, quote, is_decision_maker, do_not_contact, line,
       email_status, email_origin, created_at
  from public.contacts where business_id = %s order by created_at
"""
FACTS_SQL: Final = """
select field, value, quote, url from public.facts
 where business_id = %s and verified and coalesce(verify_score, 0) >= 0
   and field = any(%s)
 order by created_at desc
"""
PEOPLE_FIELDS: Final = ("decision_maker", "team_member")
EMAIL_FIELDS: Final = ("email", "jsonld_email", "mailto_link")
PROBE_FIELDS: Final = ("probe.dns", "probe.app_links")


def founder_rank(row: Mapping[str, Any]) -> tuple[int, str]:
    """CEO first, then a sole founder, then co-founders, then anyone else in charge; older rows first."""
    role = str(row.get("role") or "").lower()
    if re.search(r"\bceo\b|chief executive", role):
        rank = 0
    elif re.search(r"\bco-?founder\b", role):
        rank = 2
    elif re.search(r"\bfounder\b|\bowner\b", role):
        rank = 1
    else:
        rank = 3
    return rank, str(row.get("created_at") or "")


def load_lead(row: Mapping[str, Any], segment: Segment, now: datetime) -> Lead:
    contacts = db.fetch_all(CONTACTS_SQL, [row["business_id"]])
    founders = sorted(
        (c for c in contacts if c["is_decision_maker"] and c["name"] and not c["do_not_contact"]), key=founder_rank
    )
    facts = db.fetch_all(FACTS_SQL, [row["business_id"], list(PEOPLE_FIELDS)])
    people: list[str] = [str(c["name"]) for c in founders]
    for name in [c["name"] for c in contacts] + [vget(f["value"], "name") for f in facts]:
        if name and str(name) not in people:
            people.append(str(name))
    extra = dict(row.get("extra") or {})
    past = extra.get("founder_email") if isinstance(extra.get("founder_email"), dict) else {}
    since = _parse_time(past.get("since")) if past else None
    used = int(past.get("checks") or 0) if past else 0
    if since is None or now - since > WINDOW:
        since, used = now, 0
    return Lead(
        lead_id=str(row["lead_id"]),
        business_id=str(row["business_id"]),
        name=str(row["name"]),
        domain=str(row.get("web_domain") or "").lower(),
        country=str(row.get("country") or segment.country).lower(),
        segment=segment,
        extra=extra,
        founders=founders,
        people=people,
        contacts=contacts,
        checks_used=used,
        window_start=since,
    )


def _parse_time(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def published_only(lead: Lead) -> bool:
    """Canada, Australia, New Zealand: only addresses the person or business published (never a guess)."""
    countries = {str(c).lower() for c in outreach_config().get("published_only_countries", [])}
    return lead.country in countries or lead.segment.country in countries


def same_company(email_domain: str, lead: Lead) -> bool:
    """The address is at their own domain, or at a domain with the same name (brightcart.com for brightcart.io)."""
    if email_domain == lead.domain:
        return True
    registrable = web_domain(f"https://{email_domain}") or email_domain
    if registrable == lead.domain:
        return True
    brand = lead.domain.split(".")[0]
    return len(brand) >= 4 and registrable.split(".")[0] == brand


# ---------------------------------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------------------------------


@dataclass
class Env:
    """What every lead of one run shares."""

    rc: RunContext
    verifier: checks.Verifier
    router: Any
    http: PoliteClient
    resolver: Resolver
    suppressed: Suppressed
    stats: Counter[str]
    now: datetime
    snippets_left: int = 0
    snippet_failures: int = 0
    archive_pages: int = DEFAULT_ARCHIVE_PAGES
    blocked: set[str] = field(default_factory=set)  # rungs whose host blocked us this run


def usable(email: str, lead: Lead, env: Env) -> str | None:
    """Why an address can never be used (None when it can)."""
    if not valid_email(email):
        return "bad_syntax"
    dom = domain_of(email)
    if dom in FREE_MAIL:
        return "free_mail"
    if email in env.suppressed.emails or dom in env.suppressed.domains:
        return "suppressed"
    if GENERIC_LOCAL.match(email):
        return "shared_inbox"
    if not same_company(dom, lead):
        return "other_domain"
    return None


def candidates_from(
    found: list[tuple[str, str | None, str | None]], origin: str, lead: Lead, env: Env
) -> list[Candidate]:
    """Addresses read on a source become candidates when usable: a founder's own address, or another known
    person's (that one only teaches the domain's naming pattern)."""
    out: list[Candidate] = []
    seen: set[str] = set()
    for raw, url, quote in found:
        email = raw.strip().lower().rstrip(".")
        if email in seen:
            continue
        seen.add(email)
        why = usable(email, lead, env)
        if why:
            env.stats[f"skipped.{why}"] += 1
            continue
        local = email.split("@")[0]
        founder = next((f for f in lead.founders if infer_pattern(local, f["name"])), None)
        person = founder["name"] if founder else next((p for p in lead.people if infer_pattern(local, p)), None)
        pattern = infer_pattern(local, person) if person else None
        out.append(Candidate(email, origin, url, quote, founder, person, pattern))
    return out


def learn(lead: Lead, found: list[Candidate]) -> None:
    """A published address that fits a known person at their own domain shows the domain's naming pattern."""
    for c in found:
        if c.pattern and c.origin in checks.PUBLISHED_ORIGINS and domain_of(c.email) == lead.domain:
            lead.backed.add(c.pattern)


def settle(cand: Candidate, lead: Lead, env: Env, catch_all_domain: bool | None) -> tuple[str, checks.Check | None]:
    """Check one candidate (cached answers are free; live ones count against the lead's 5) and label it."""
    lead.tried.add(cand.email)
    answer = env.verifier.cached(cand.email)
    if answer is not None:
        env.stats["checks.cached"] += 1
    elif lead.checks_left > 0:
        answer = env.verifier.check(cand.email, use_cache=False, reserve=SEND_RESERVE)
        if answer is not None:
            lead.checks_used += 1
            env.stats["checks.live"] += 1
        elif cand.origin not in checks.PUBLISHED_ORIGINS:
            lead.deferred.append("no_check")
    else:
        env.stats["checks.lead_cap"] += 1
    backed = cand.pattern is not None and cand.pattern in lead.backed
    return label(cand.origin, answer, backed=backed, catch_all_domain=catch_all_domain), answer


async def archive_rung(lead: Lead, env: Env) -> list[tuple[str, str | None, str | None]]:
    """Old copies of their contact, about and team pages (Wayback Machine), read politely."""
    if env.archive_pages <= 0:
        return []
    if "archive" in env.blocked:  # blocked earlier in this run: this lead tries again tomorrow
        lead.deferred.append("archive_blocked")
        return []
    params = {"url": f"{lead.domain}/*", "output": "json", "fl": "timestamp,original",
              "filter": ["statuscode:200", "mimetype:text/html"], "collapse": "urlkey", "limit": "500"}  # fmt: skip
    try:
        index = await env.http.get(WAYBACK_CDX, params=params, max_bytes=2_000_000)
        rows = index.json() if index.ok else []
    except SourceBlocked:
        env.blocked.add("archive")
        lead.deferred.append("archive_blocked")
        return []
    except (ValueError, NeverFetch):
        return []
    if index.state == "unknown":
        lead.deferred.append("archive_unreachable")
    pages: list[tuple[int, str, str]] = []
    for item in rows[1:] if isinstance(rows, list) else []:
        if not isinstance(item, list) or len(item) < 2:
            continue
        stamp, original = str(item[0]), str(item[1])
        if not stamp.isdigit() or not on_domain(original, lead.domain):
            continue
        path = urlsplit(original).path.strip("/")
        hit = ARCHIVE_WORDS.search(path)
        if hit or not path:
            pages.append((0 if hit else 1, stamp, original))
    found: list[tuple[str, str | None, str | None]] = []
    for _, stamp, original in sorted(pages)[: env.archive_pages]:
        try:
            page = await env.http.get(f"{WAYBACK_WEB}/{stamp}id_/{original}", max_bytes=1_500_000)
        except SourceBlocked:
            env.blocked.add("archive")
            lead.deferred.append("archive_blocked")
            break
        except NeverFetch:
            continue
        env.stats["archive.pages"] += 1
        if not page.ok:
            continue
        for email in sorted(emails_in_text(page.text)):
            found.append((email, f"{WAYBACK_WEB}/{stamp}/{original}", page_quote(page.text, email)))
    return found


async def store_rung(lead: Lead, facts: list[Row], env: Env) -> list[tuple[str, str | None, str | None]]:
    """The developer contact on their Google Play listings (packages from the probe.app_links fact)."""
    packages: list[str] = []
    for f in facts:
        if f["field"] == "probe.app_links":
            for pkg in vget(f["value"], "android_packages") or []:
                if isinstance(pkg, str) and re.fullmatch(r"[A-Za-z0-9_.]{3,150}", pkg) and pkg not in packages:
                    packages.append(pkg)
    if packages and "store" in env.blocked:  # blocked earlier in this run: this lead tries again tomorrow
        lead.deferred.append("store_blocked")
        return []
    found: list[tuple[str, str | None, str | None]] = []
    for pkg in packages[:MAX_STORE_LISTINGS]:
        url = f"{PLAY_DETAILS}?id={pkg}&hl=en"
        try:
            page = await env.http.get(url, max_bytes=1_500_000)
        except SourceBlocked:
            env.blocked.add("store")
            lead.deferred.append("store_blocked")
            break
        except NeverFetch:
            continue
        env.stats["store.listings"] += 1
        if page.ok:
            found += [(e, url, page_quote(page.text, e)) for e in sorted(emails_in_text(page.text))]
    return found


def filing_rung(lead: Lead) -> list[tuple[str, str | None, str | None]]:
    """Addresses in registry contacts, filing records and filing signals."""
    found: list[tuple[str, str | None, str | None]] = [
        (str(c["email"]), c.get("source_url"), c.get("quote") or str(c["email"]))
        for c in lead.contacts
        if c.get("email")
        and c.get("source") == "registry"
        and not c.get("do_not_contact")
        and c.get("email_origin") in (None, "filing")
    ]
    records = db.fetch_all(
        "select payload from public.source_records where business_id = %s and source = any(%s)",
        [lead.business_id, list(FILING_SOURCES)],
    )
    records += db.fetch_all(
        "select details as payload, url from public.signals where business_id = %s and source = any(%s)",
        [lead.business_id, list(FILING_SOURCES)],
    )
    for rec in records:
        payload = rec.get("payload") or {}
        text = json.dumps(payload, ensure_ascii=False)
        url = rec.get("url") or (payload.get("url") if isinstance(payload, dict) else None)
        found += [(e, str(url) if url else None, e) for e in sorted(emails_in_text(text))]
    return found


def published_rung(lead: Lead, facts: list[Row]) -> list[tuple[str, str | None, str | None]]:
    """Their own site: page text research read, verified email facts on their domain, and site contacts."""
    found: list[tuple[str, str | None, str | None]] = []
    for page in db.fetch_all(
        "select url, text from public.pages where business_id = %s and text is not null", [lead.business_id]
    ):
        if on_domain(page["url"], lead.domain):
            text = str(page["text"])
            found += [(e, str(page["url"]), quote_around(text, e)) for e in sorted(emails_in_text(text))]
    for f in facts:
        if f["field"] in EMAIL_FIELDS and on_domain(f.get("url"), lead.domain):
            raw = vget(f["value"], "email", "value")
            if isinstance(raw, str):
                found.append((raw, f.get("url"), f.get("quote") or raw))
    found += [
        (str(c["email"]), c.get("source_url"), c.get("quote") or str(c["email"]))
        for c in lead.contacts
        if c.get("email")
        and c.get("source") == "website"
        and not c.get("do_not_contact")
        and c.get("email_origin") in (None, "published")  # never a guess stored on a founder named on the site
    ]
    return found


async def snippet_rung(lead: Lead, env: Env) -> list[Candidate]:
    """One grounded search for the first founder's published address (contract: `find_founder_email`)."""
    founder = next((f for f in lead.founders if name_parts(f["name"])), None)
    run_result = getattr(env.router, "run_result", None) if env.router is not None else None
    if founder is None or run_result is None:
        return []
    if "snippet" in env.blocked:  # the AI stopped earlier in this run (budget or failures)
        lead.deferred.append("snippet_stopped")
        return []
    if env.snippets_left <= 0:
        lead.deferred.append("snippet_allowance")
        env.stats["snippet.no_allowance"] += 1
        return []
    inputs = {"name": founder["name"], "company": lead.name, "domain": lead.domain,
              "country": country_name(lead.segment.country)}  # fmt: skip
    try:
        res = run_result(TASK, inputs)
    except Exception as exc:  # typed router errors: stop on budget, skip one stubborn lead
        name = type(exc).__name__
        env.stats[f"snippet.error.{name}"] += 1
        lead.deferred.append("snippet_failed")
        env.snippet_failures += 1
        if name in ai.BUDGET_ERRORS or env.snippet_failures >= MAX_SNIPPET_FAILURES:
            env.blocked.add("snippet")
        return []
    env.snippet_failures = 0
    ground = getattr(res, "grounding", None) or {}
    env.snippets_left -= max(len(ground.get("queries") or []), 1)
    env.stats["snippet.searched"] += 1
    found = snippet_candidate(res.output, ground, founder, lead, env)
    if found is None:
        return []
    confirmed = await confirm(found, lead, env)
    if confirmed.origin == "snippet" and published_only(lead):  # unconfirmed counts as a guess there
        env.stats["snippet.unconfirmed_published_only"] += 1
        return []
    return [confirmed]


def snippet_candidate(output: Any, ground: Mapping[str, Any], founder: Row, lead: Lead, env: Env) -> Candidate | None:
    """The answer's address when it is at their own domain, fits the founder's name and a sentence the search
    results back contains it word for word."""
    email = str(getattr(output, "email", None) or "").strip().strip(".,;:<>()[]").lower()
    line = str(getattr(output, "line", None) or "")
    if not email or email in ("unknown", "none", "null") or email not in line.lower():
        env.stats["snippet.none"] += 1
        return None
    if usable(email, lead, env) or domain_of(email) != lead.domain:
        env.stats["snippet.rejected"] += 1
        return None
    pattern = infer_pattern(email.split("@")[0], founder["name"])
    if pattern is None:
        env.stats["snippet.not_theirs"] += 1
        return None
    sources = ground.get("sources") or []
    for sup in ground.get("supports") or []:
        text = str(sup.get("text") or "")
        if email in text.lower():
            uris = [
                str(sources[i].get("uri"))
                for i in sup.get("chunks") or []
                if isinstance(i, int) and 0 <= i < len(sources) and sources[i].get("uri")
            ]
            return Candidate(email, "snippet", uris[0] if uris else None, text.strip()[:300], founder,
                             founder["name"], pattern)  # fmt: skip
    env.stats["snippet.unbacked"] += 1
    return None


async def confirm(cand: Candidate, lead: Lead, env: Env) -> Candidate:
    """Read the cited page (never LinkedIn, X or another never-fetch host); when it shows the address, the
    address counts as published there. A grounding redirect is resolved from its Location header only."""
    url = cand.url
    if not url:
        return cand
    try:
        if host_of(url) in REDIRECT_HOSTS:
            url = await env.http.location(url) or url
        if host_blocked(url) or host_of(url) in REDIRECT_HOSTS:
            return Candidate(cand.email, "snippet", url, cand.quote, cand.founder, cand.person, cand.pattern)
        page = await env.http.get(url, raise_on_block=False, max_bytes=1_500_000)
    except (NeverFetch, SourceBlocked):
        return cand
    quote = page_quote(page.text, cand.email) if page.ok else None
    if quote is None or cand.email not in page.text.lower():
        return Candidate(cand.email, "snippet", url, cand.quote, cand.founder, cand.person, cand.pattern)
    env.stats["snippet.confirmed"] += 1
    final = page.final_url or url
    origin = "published" if on_domain(final, lead.domain) else "post"
    return Candidate(cand.email, origin, final, quote, cand.founder, cand.person, cand.pattern)


def mail_domain_info(lead: Lead, facts: list[Row], env: Env) -> checks.DomainInfo | None:
    """The domain's mail provider and catch-all answer: the cached row, the probe.dns fact, else DNS."""
    info = checks.domain_info(lead.domain, now=env.now)
    if info is not None and info.mx_provider:
        return info
    probe = next((f for f in facts if f["field"] == "probe.dns"), None)
    provider = vget(probe["value"], "mx_provider") if probe else None
    if provider not in ("google", "microsoft", "zoho", "other", "none"):
        hosts = env.resolver(lead.domain)
        if hosts is None:
            lead.deferred.append("dns")
            env.stats["dns.no_answer"] += 1
            return None
        provider = mx_provider(hosts)
    checks.save_domain(lead.domain, str(provider), now=env.now)
    if info is not None and info.catch_all is not None:  # a catch-all answer learned before the MX lookup
        checks.record_catch_all(lead.domain, info.catch_all, env.now)
    return checks.DomainInfo(lead.domain, str(provider), info.catch_all if info else None, env.now)


def guess_rung(lead: Lead, facts: list[Row], env: Env) -> Outcome | None:
    """Name patterns at their domain, checked without sending; a pattern a published address backs goes first.
    Stops at a deliverable answer, at a catch-all domain, at an inconclusive answer or at 5 live checks."""
    if published_only(lead):
        env.stats["guess.published_only_country"] += 1
        return None
    if lead.domain in FREE_MAIL or is_free_builder(lead.domain):
        env.stats["guess.free_domain"] += 1
        return None
    info = mail_domain_info(lead, facts, env)
    if info is None or info.mx_provider == "none":
        env.stats["guess.no_mx" if info else "guess.no_dns"] += 1
        return None
    order = [p for p in PATTERNS if p in lead.backed] + [p for p in PATTERNS if p not in lead.backed]
    catch_all = info.catch_all
    fallback: Outcome | None = None
    for founder in lead.founders:
        parts = name_parts(founder["name"])
        if parts is None:
            continue
        for pattern in order:
            email = f"{render(pattern, *parts)}@{lead.domain}"
            if email in lead.tried or usable(email, lead, env):
                continue
            cand = Candidate(email, "guess", founder.get("source_url"), founder.get("quote"), founder,
                             founder["name"], pattern)  # fmt: skip
            if catch_all is True:  # every address is accepted: nothing to learn from a check
                if pattern in lead.backed:
                    return Outcome("found", cand, "likely", None)
                env.stats["guess.catch_all"] += 1
                return fallback
            if lead.checks_left <= 0 and env.verifier.cached(email) is None:
                env.stats["guess.lead_cap"] += 1
                return fallback
            status, answer = settle(cand, lead, env, catch_all)
            env.stats["guess.tried"] += 1
            if answer is None:
                lead.deferred.append("no_check")
                return fallback
            if status == "verified":
                return Outcome("found", cand, status, answer)
            if answer.catch_all:
                catch_all = True
                if status == "likely":
                    return Outcome("found", cand, status, answer)
                if lead.backed:  # the backed pattern was not this one: label it without another check
                    continue
                env.stats["guess.catch_all"] += 1
                return fallback
            if answer.result == "unknown":
                lead.deferred.append("inconclusive")
                return fallback
            if status == "likely" and fallback is None:
                fallback = Outcome("found", cand, status, answer)
    return fallback


async def find(lead: Lead, env: Env) -> Outcome:
    """The ladder for one lead."""
    if not lead.founders:
        return Outcome("no_founder")
    if not lead.domain or lead.domain in env.suppressed.domains:
        return Outcome("no_domain")
    facts = db.fetch_all(FACTS_SQL, [lead.business_id, [*EMAIL_FIELDS, *PROBE_FIELDS]])
    known_catch_all = info.catch_all if (info := checks.domain_info(lead.domain, now=env.now)) else None
    best: Outcome | None = None
    for rung in ("published", "archive", "snippet", "store", "filing"):
        if rung == "snippet":
            if lead.backed and env.verifier.available():
                env.stats["snippet.skipped_backed"] += 1
                continue
            found = await snippet_rung(lead, env)
        elif rung == "published":
            found = candidates_from(published_rung(lead, facts), "published", lead, env)
        elif rung == "archive":
            found = candidates_from(await archive_rung(lead, env), "archive", lead, env)
        elif rung == "store":
            found = candidates_from(await store_rung(lead, facts, env), "store", lead, env)
        else:
            found = candidates_from(filing_rung(lead), "filing", lead, env)
        learn(lead, found)
        for cand in sorted((c for c in found if c.founder), key=lambda c: founder_rank(c.founder or {})):
            if cand.email in lead.tried:
                continue
            status, answer = settle(cand, lead, env, known_catch_all)
            env.stats[f"{rung}.{status}"] += 1
            if status == "invalid":
                mark_invalid(lead, cand, answer, env)
            elif status == "verified":
                return Outcome("found", cand, status, answer)
            elif status == "likely" and best is None:
                best = Outcome("found", cand, status, answer)
        if best is not None:
            return best
    guessed = guess_rung(lead, facts, env)
    if guessed is not None:
        return guessed
    return Outcome("deferred" if lead.deferred else "not_found")


# ---------------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------------

_SAME_EMAIL: Final = "select id::text as id from public.contacts where business_id = %s and lower(email) = lower(%s)"


def mark_invalid(lead: Lead, cand: Candidate, answer: checks.Check | None, env: Env) -> None:
    """An undeliverable address that a contact already holds is marked invalid (never mailed)."""
    row = db.fetch_one(_SAME_EMAIL, [lead.business_id, cand.email])
    if row is not None:
        db.execute(
            "update public.contacts set email_status = 'invalid', email_checked_at = %s where id = %s",
            [answer.checked_at if answer else env.now, row["id"]],
        )
        env.stats["marked_invalid"] += 1


def save(lead: Lead, outcome: Outcome, env: Env) -> None:
    """Store the address on the founder (with its evidence), then the attempt on the business."""
    cand, status = outcome.candidate, outcome.status
    with db.tx("engine", {"run_id": env.rc.run_id, "stage": "founder_emails"}) as conn:
        if cand is not None and cand.founder is not None and status in ("verified", "likely"):
            founder = cand.founder
            checked_at = outcome.answer.checked_at if outcome.answer else None
            why = WHY.get(cand.origin, "")
            same = conn.execute(_SAME_EMAIL, [lead.business_id, cand.email]).fetchone()
            values = [status, cand.origin, cand.pattern, checked_at]
            if same is not None:
                conn.execute(
                    "update public.contacts set email_status = %s, email_origin = %s, email_pattern = %s, "
                    "email_checked_at = %s, name = coalesce(name, %s), role = coalesce(role, %s), "
                    "is_decision_maker = true, line = 'owner', line_why = %s where id = %s",
                    [*values, founder["name"], founder.get("role"), why, same["id"]],
                )
            elif not founder.get("email") and cand.origin in ("guess",):
                conn.execute(  # a guess has no page of its own: the founder's row keeps the name's evidence
                    "update public.contacts set email = %s, email_status = %s, email_origin = %s, "
                    "email_pattern = %s, email_checked_at = %s, line = 'owner', line_why = %s where id = %s",
                    [cand.email, *values, why, founder["id"]],
                )
            else:
                conn.execute(
                    "insert into public.contacts (business_id, name, role, email, source, source_url, quote, "
                    "is_decision_maker, verified, verified_at, line, line_why, email_status, email_origin, "
                    "email_pattern, email_checked_at) values (%s, %s, %s, %s, %s, %s, %s, true, true, %s, 'owner', "
                    "%s, %s, %s, %s, %s)",
                    [lead.business_id, founder["name"], founder.get("role"), cand.email,
                     SOURCE_FOR.get(cand.origin, "other"), cand.url, cand.quote, env.now, why, *values],
                )  # fmt: skip
        record = {
            "at": env.now.isoformat(),
            "outcome": outcome.kind,
            "status": status,
            "next_at": (env.now + RETRY.get(outcome.kind, timedelta(days=1))).isoformat(),
            "checks": lead.checks_used,
            "since": (lead.window_start or env.now).isoformat(),
            "deferred": sorted(set(lead.deferred))[:6],
        }
        conn.execute(
            "update public.businesses set extra = extra || jsonb_build_object('founder_email', %s::jsonb) "
            "where id = %s",
            [json.dumps(record), lead.business_id],
        )


def run(
    rc: RunContext,
    router: Any = None,
    verifier: checks.Verifier | None = None,
    resolver: Resolver | None = None,
    transport: Any = None,
    **_: Any,
) -> dict[str, Any]:
    """`founder_emails` (morning and midday): the founder's address for new A and B startups that have no
    verified or likely owner email yet."""
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    segments = {k: s for k, s in score.enabled_segments(rc).items() if s.domain == "firms"}
    if not segments:
        return {"skipped": "no startup segments"}
    per_run = db.get_setting(SETTING_LEADS, DEFAULT_LEADS)
    limit = int(per_run) if isinstance(per_run, int | float) else DEFAULT_LEADS
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "limit": limit})
    stats["candidates"] = len(rows)
    if rc.opts.dry_run or not rows:
        rc.stats["founder_emails"] = dict(stats)
        return dict(stats)
    if router is None:
        try:
            router = ai.router_for(rc)
        except ai.AIStop as exc:  # the published rungs and the guesses still run without AI
            stats["snippet.no_router"] += 1
            log.info("founder_emails.no_router", reason=exc.reason[:120])
    own = verifier is None
    checker = verifier if verifier is not None else checks.Verifier.from_settings()
    try:
        asyncio.run(_run(rc, rows, segments, router, checker, resolver or lookup_mx, transport, stats, now))
    finally:
        if own:
            checker.close()
    stats.update({f"verifier.{k}": v for k, v in checker.stats.items()})
    result: dict[str, Any] = dict(stats)
    rc.stats["founder_emails"] = result
    log.info("founder_emails.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result


async def _run(
    rc: RunContext,
    rows: list[Row],
    segments: Mapping[str, Segment],
    router: Any,
    verifier: checks.Verifier,
    resolver: Resolver,
    transport: Any,
    stats: Counter[str],
    now: datetime,
) -> None:
    budget = getattr(router, "budget", None) if router is not None else None
    pages = db.get_setting(SETTING_ARCHIVE, DEFAULT_ARCHIVE_PAGES)
    async with PoliteClient("founder_emails", policy="public", transport=transport) as http:
        env = Env(
            rc=rc,
            verifier=verifier,
            router=router,
            http=http,
            resolver=resolver,
            suppressed=Suppressed.load(),
            stats=stats,
            now=now,
            snippets_left=grounding.allowance("email_snippets", budget) if router is not None else 0,
            archive_pages=int(pages) if isinstance(pages, int | float) else DEFAULT_ARCHIVE_PAGES,
        )
        for row in rows:
            if rc.time_left() <= RESERVE_S:
                stats["stopped_time"] += 1
                break
            lead = load_lead(row, segments[row["segment_id"]], now)
            outcome = await find(lead, env)
            save(lead, outcome, env)
            stats[f"outcome.{outcome.kind}"] += 1
            if outcome.candidate is not None and outcome.status:
                stats[f"found.{outcome.status}"] += 1
                stats[f"origin.{outcome.candidate.origin}"] += 1
