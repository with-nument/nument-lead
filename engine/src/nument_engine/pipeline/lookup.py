"""The official website of businesses born from a signal (the need-first track, 13 Nov 2026).

A job post, a public ask or a filing names a business, rarely its website. Two steps find it, cheapest first:

1. **A free domain guess** (15 Nov 2026). Startups mostly own their name: "Care Nimble, Inc." is carenimble.com,
   "CipherSonic Labs" may be ciphersonic.ai. The name (legal suffix removed, and once more without a generic last
   word such as "Labs") is tried with `.com`, `.io`, `.ai`, `.co`, `.app` and the country's own ending. DNS first
   (a name that does not resolve costs no request), then the home page through `PoliteClient` (robots.txt
   respected). A guess is kept only when the page itself names the company, in its title, `og:site_name` or
   visible text, with the address removed first, and the page is not a parked or for-sale page, a server's
   default page, or a redirect to a domain marketplace.
2. **A grounded lookup**, only for what the guess did not find, within `grounding.allowance("lookup", budget)`:
   one Gemini call with Google Search grounding per business; code keeps the answer only when the search cited
   the domain (or a backed sentence of the answer contains it), it is not a never-fetch host, and its home page
   names the business (`page_matches`).

Candidates are businesses without a website that a signal created (`extra.born_from`) or that belong to a
need-first segment (`universe: signals_only`, where every business comes from a signal). A business is looked
up once (`extra.website_lookup_at`, set when the guess found the site or the grounded lookup ran). A guess that
found nothing is remembered (`extra.website_guess_at`) so it is not repeated while the business waits for a
grounded lookup on a later night. Prefilter rule R10 then passes the business (with a website) or rejects it
(no contact route). Night and midday stage, after `signals` and before `prefilter`.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx
import psycopg
from cleanco import basename

from .. import db
from ..http import NeverFetch, PoliteClient, SourceBlocked, host_blocked
from ..logging import get_logger
from ..normalize import web_domain
from ..segments import country_name
from ..sources import health
from . import ai, grounding, score
from .resolve import merge_businesses
from .runs import RunContext
from .verify import distinctive_words

log = get_logger()

TASK: Final = "find_website"
SETTING: Final = "lookup.candidates_per_run"  # businesses considered per run (the guess is free; searches are not)
DEFAULT_PER_RUN: Final = 150
GUESS_SECONDS: Final = 300.0  # the free guess never takes more than five minutes of the run
GUESS_WORKERS: Final = 8  # businesses guessed at once (each host keeps its own polite gap)
DNS_AT_ONCE: Final = 24
DNS_TIMEOUT_S: Final = 4.0
PAGE_BYTES: Final = 400_000
PAGE_GAP_S: float | None = None  # None: the public policy's gap per host (tests set 0)
GUESS_TLDS: Final = ("com", "io", "ai", "co", "app")
# The country's own endings, tried after the global ones (default: the two-letter code itself).
COUNTRY_TLDS: Final[dict[str, tuple[str, ...]]] = {
    "gb": ("co.uk", "uk"),
    "in": ("in", "co.in"),
    "au": ("com.au",),
    "nz": ("co.nz",),
    "sg": ("sg", "com.sg"),
    "br": ("com.br",),
    "mx": ("com.mx",),
    "ph": ("ph", "com.ph"),
    "my": ("my", "com.my"),
    "id": ("co.id", "id"),
}
_TITLE: Final = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SITE_NAME: Final = re.compile(r"""<meta[^>]+property=["']og:site_name["'][^>]+content=["']([^"']+)""", re.I)
_TAGS: Final = re.compile(r"<[^>]+>")
_SCRIPTS: Final = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
# Words that end company names but are not the brand: "Brightcart Foods" is brightcart.in.
COMPANY_WORDS: Final = frozenset(
    ["foods", "food", "technologies", "technology", "tech", "solutions", "ventures", "labs", "services",
     "enterprises", "enterprise", "industries", "systems", "global", "digital", "software", "retail", "brands",
     "studio", "studios", "consulting", "innovations", "infotech", "networks", "corp", "corporation"]
)  # fmt: skip
# Legal words cleanco leaves in place, and filler words that are never part of a domain.
_NAME_FILLER: Final = frozenset(["the", "and", "of", "a", "an", "pbc", "company", "co", "inc", "llc", "ltd"])
# A guessed domain that shows one of these is not the company's site.
PARKED_MARKERS: Final = (
    "domain is for sale", "domain may be for sale", "this domain is for sale", "buy this domain",
    "is available for purchase", "domain for sale", "inquire about this domain", "make an offer on this domain",
    "this web page is parked", "parked free", "parked domain", "domain parking", "sedoparking", "hugedomains",
    "afternic", "this domain has been registered", "this domain has expired", "domain has expired",
    "renew this domain", "future home of something quite cool", "welcome to nginx", "apache2 ubuntu default page",
    "apache2 debian default page", "default web site page", "site not found", "index of /",
)  # fmt: skip
PARKING_HOSTS: Final = (
    "sedo.com", "dan.com", "afternic.com", "hugedomains.com", "godaddy.com", "namecheap.com", "parkingcrew.net",
    "bodis.com", "above.com", "undeveloped.com", "squadhelp.com", "atom.com", "brandbucket.com", "buydomains.com",
    "domainmarket.com", "sav.com", "porkbun.com", "efty.com", "epik.com", "spaceship.com",
)  # fmt: skip

CANDIDATES_SQL: Final = """
select b.id::text as id, b.name, b.city, b.segment_id, b.extra,
       (select s.details->>'need' from public.signals s where s.business_id = b.id
         order by s.observed_at desc limit 1) as need
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.website is null
   and (b.extra ? 'born_from' or b.segment_id = any(%(signals_only)s))
   and not b.extra ? 'website_lookup_at'
   and b.status in ('candidate', 'queued')
 order by b.created_at desc
 limit %(limit)s
"""

Resolve = Callable[[str], Awaitable[bool | None]]


# ---------------------------------------------------------------------------------------------------
# Grounded answers
# ---------------------------------------------------------------------------------------------------


def cited_domains(grounding: dict[str, Any] | None) -> set[str]:
    """Domains the search cited, plus any written in a sentence the search results back."""
    out: set[str] = set()
    for src in (grounding or {}).get("sources") or []:
        for value in (src.get("uri"), src.get("title")):
            dom = web_domain(str(value or ""))
            if dom:
                out.add(dom)
    for sup in (grounding or {}).get("supports") or []:
        for match in re.findall(r"[a-z0-9][a-z0-9.-]+\.[a-z]{2,}", str(sup.get("text") or "").lower()):
            dom = web_domain(match)
            if dom:
                out.add(dom)
    return out


def candidate_url(output: Any, grounding: dict[str, Any] | None) -> str | None:
    """The answer's website when the search backs it and it is not a never-fetch host."""
    raw = str(getattr(output, "website", None) or "").strip()
    if not raw or raw.lower() in ("unknown", "none", "null"):
        return None
    url = raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
    dom = web_domain(url)
    if not dom or host_blocked(url) or dom not in cited_domains(grounding):
        return None
    return url


# ---------------------------------------------------------------------------------------------------
# Does a page name the business
# ---------------------------------------------------------------------------------------------------


def page_names(html: str) -> list[str]:
    """Names a home page gives itself: the title (split at separators) and og:site_name."""
    names: list[str] = []
    title = _TITLE.search(html)
    if title:
        names += [p.strip() for p in re.split(r"\s[|\-\u2013:]\s", _TAGS.sub(" ", title.group(1))) if p.strip()]
    site = _SITE_NAME.search(html)
    if site:
        names.append(site.group(1).strip())
    return names


def page_matches(name: str, html: str, url: str) -> bool:
    """Does the home page name this business? A distinctive word of the name (not "foods" or "technologies")
    in the title or site name, all of them joined in the domain, or all of them in the visible text."""
    words = [w for w in distinctive_words(name) if len(w) >= 3 and w not in COMPANY_WORDS] or [
        w for w in distinctive_words(name) if len(w) >= 3
    ]
    text = re.sub(r"\s+", " ", _TAGS.sub(" ", html)).lower()
    if not words:
        return re.sub(r"\s+", " ", name.lower()).strip() in text
    head = " ".join(page_names(html)).lower()
    if any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", head) for w in words):
        return True
    domain = re.sub(r"[^a-z0-9]", "", web_domain(url) or "")
    if "".join(words) in domain:
        return True
    return all(w in text for w in words)


def name_words(name: str) -> list[str]:
    """The words of a company name without its legal form: "Care Nimble, Inc." -> ["care", "nimble"]."""
    plain = unicodedata.normalize("NFKD", basename(name or "")).encode("ascii", "ignore").decode().lower()
    return [w for w in re.findall(r"[a-z0-9]+", plain.replace("&", " and ")) if w not in _NAME_FILLER]


def _core(words: list[str]) -> list[str]:
    return [w for w in words if w not in COMPANY_WORDS] or words


def visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", _SCRIPTS.sub(" ", html))).strip()


def _names(words: Sequence[str], text: str) -> bool:
    """The words in order as whole tokens, with or without separators ("care nimble", "CareNimble")."""
    pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]{0,3}".join(re.escape(w) for w in words) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def names_company(name: str, html: str, domains: Iterable[str] = ()) -> bool:
    """Does the page itself name the company? Its name (without the legal form, and without a generic last
    word when it has one) in the title or `og:site_name`, or in the visible text. The page's own address is
    removed first: a parked page titled "carenimble.com" names nothing."""
    words = name_words(name)
    if not words:
        return False
    head = " ".join(page_names(html)).lower()
    text = visible_text(html).lower()
    for dom in domains:
        head = head.replace(dom.lower(), " ")
        text = text.replace(dom.lower(), " ")
    variants = [words, _core(words)]
    return any(_names(v, head) for v in variants) or any(_names(v, text) for v in variants)


def is_parked(html: str) -> bool:
    """A for-sale, parked, expired or server default page."""
    low = (" ".join(page_names(html)) + " " + visible_text(html[:200_000])).lower()
    return any(marker in low for marker in PARKED_MARKERS)


# ---------------------------------------------------------------------------------------------------
# The free domain guess
# ---------------------------------------------------------------------------------------------------


def guess_labels(name: str) -> list[str]:
    """Domain labels the company would likely own: the whole name joined ("blueskyrobotics") and, when it ends
    in a generic word, the name without it ("ciphersonic" for "CipherSonic Labs"). Labels under 4 characters are
    too common to be anyone's in particular."""
    words = name_words(name)
    labels: list[str] = []
    for variant in (words, _core(words)):
        label = "".join(variant)
        if 4 <= len(label) <= 40 and label not in labels:
            labels.append(label)
    return labels


def candidate_domains(name: str, country: str) -> list[str]:
    """Every guessed domain, most likely first: each label with .com, .io, .ai, .co, .app, then the country's
    own endings."""
    cc = (country or "").lower()
    tlds = GUESS_TLDS + COUNTRY_TLDS.get(cc, (cc,) if re.fullmatch(r"[a-z]{2}", cc) else ())
    out: list[str] = []
    for label in guess_labels(name):
        for tld in tlds:
            dom = f"{label}.{tld}"
            if dom not in out:
                out.append(dom)
    return out


async def dns_resolves(domain: str) -> bool | None:
    """True when the domain has an address (A or AAAA), False when it does not exist or has none, None when DNS
    did not answer in time (unknown: tried again on a later night)."""
    for rdtype in ("A", "AAAA"):
        try:
            answer = await dns.asyncresolver.resolve(domain, rdtype, lifetime=DNS_TIMEOUT_S)
        except dns.resolver.NXDOMAIN:
            return False
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            continue
        except dns.exception.DNSException:
            return None
        if len(answer):
            return True
    return False


@dataclass(frozen=True)
class Guess:
    url: str | None
    status: Literal["found", "not_found", "unknown"]


async def check_guess(http: PoliteClient, name: str, domain: str) -> tuple[str | None, bool]:
    """(the site's address or None, whether the answer may change on a later try) for one guessed domain."""
    url = f"https://{domain}/"
    try:
        page = await http.get(url, raise_on_block=False, max_bytes=PAGE_BYTES)
    except (NeverFetch, SourceBlocked):  # a redirect to a never-fetch host, or a host already blocked this run
        return None, False
    if page.state == "unknown" and page.reason != "TLS verification failed":
        return None, True  # a timeout or a network error: not an answer
    if page.state != "ok":
        return None, False
    final = page.final_url or url
    final_dom = web_domain(final)
    if not final_dom or host_blocked(final) or final_dom.endswith(PARKING_HOSTS) or is_parked(page.text):
        return None, False
    if not names_company(name, page.text, {domain, final_dom}):
        return None, False
    return final, False


async def guess_site(
    http: PoliteClient, name: str, country: str, resolve: Resolve, dns_gate: asyncio.Semaphore
) -> Guess:
    """The first guessed domain that resolves and whose home page names the company."""
    domains = candidate_domains(name, country)
    if not domains:
        return Guess(None, "not_found")

    async def alive(dom: str) -> bool | None:
        async with dns_gate:
            return await resolve(dom)

    answers = await asyncio.gather(*(alive(d) for d in domains))
    unsure = any(a is None for a in answers)
    for dom, ok in zip(domains, answers, strict=True):
        if ok is not True:
            continue
        url, retry = await check_guess(http, name, dom)
        if url:
            return Guess(url, "found")
        unsure = unsure or retry
    return Guess(None, "unknown" if unsure else "not_found")


async def guess_sites(
    rows: Sequence[Mapping[str, Any]],
    countries: Mapping[str, str],
    *,
    resolve: Resolve | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    seconds: float = GUESS_SECONDS,
) -> dict[str, Guess]:
    """{business id: guess} for the rows, several businesses at once, within `seconds` (unfinished ones are
    left for the next run)."""
    resolver = resolve or dns_resolves
    out: dict[str, Guess] = {}
    if not rows:
        return out
    sites_gate, dns_gate = asyncio.Semaphore(GUESS_WORKERS), asyncio.Semaphore(DNS_AT_ONCE)
    async with PoliteClient("website_lookup", policy="public", min_gap_s=PAGE_GAP_S, transport=transport) as http:

        async def one(b: Mapping[str, Any]) -> None:
            async with sites_gate:
                try:
                    out[str(b["id"])] = await guess_site(
                        http, str(b["name"]), countries[str(b["id"])], resolver, dns_gate
                    )
                except Exception as exc:  # one strange site never stops the others
                    log.info("lookup.guess_failed", business_id=b["id"], error=type(exc).__name__)

        tasks = [asyncio.create_task(one(b)) for b in rows]
        _, pending = await asyncio.wait(tasks, timeout=max(seconds, 0.0))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return out


# ---------------------------------------------------------------------------------------------------
# Home pages of grounded answers, and writing
# ---------------------------------------------------------------------------------------------------


async def check_sites(
    found: dict[str, str], names: dict[str, str], *, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, str]:
    """{business id: final url} for the candidates whose home page names the business."""
    ok: dict[str, str] = {}
    async with PoliteClient("website_lookup", policy="public", min_gap_s=PAGE_GAP_S, transport=transport) as http:
        for bid, url in found.items():
            try:
                page = await http.get(url, raise_on_block=False, max_bytes=PAGE_BYTES)
            except Exception as exc:  # one bad site never stops the stage
                log.info("lookup.fetch_failed", url=url, error=type(exc).__name__)
                continue
            if page.state == "ok" and page_matches(names[bid], page.text, page.final_url or url):
                ok[bid] = page.final_url or url
    return ok


TWIN_SQL: Final = """
select o.id::text as id from public.businesses o join public.businesses b on b.id = %s
 where o.segment_id = b.segment_id and o.web_domain = %s and o.id <> b.id limit 1
"""


def write_results(
    run_id: str,
    names: dict[str, str],
    checked: dict[str, str],
    now: datetime,
    *,
    via: Mapping[str, str] | None = None,
    guess_missed: Iterable[str] = (),
) -> Counter[str]:
    """Save each lookup. A site that already belongs to another business of the segment means the signal-born
    business is a duplicate of it: its signals and facts move there and it is removed (live, 14 Nov 2026: one
    duplicate stopped the whole night run's lookup, which also threw away every other website it had found).
    Each business has its own savepoint, so one failure never undoes the others. `guess_missed` are businesses
    whose free guess found nothing and that still wait for a grounded lookup: only the guess is remembered."""
    stats: Counter[str] = Counter()
    how = via or {}
    with db.tx("engine", {"run_id": run_id, "stage": "lookup"}) as conn:
        for bid in names:
            url = checked.get(bid)
            try:
                with conn.transaction():
                    twin = conn.execute(TWIN_SQL, [bid, web_domain(url)]).fetchone() if url else None
                    if twin:
                        merge_businesses(str(twin["id"]), bid, conn=conn)
                        stats["merged_duplicate"] += 1
                        continue
                    conn.execute(
                        "update public.businesses set website = coalesce(%s, website), "
                        "web_domain = coalesce(%s, web_domain), "
                        "extra = extra || jsonb_build_object('website_lookup_at', %s::text, "
                        "'website_lookup', %s::text, 'website_lookup_via', %s::text) where id = %s",
                        [
                            url,
                            web_domain(url) if url else None,
                            now.isoformat(),
                            url or "not_found",
                            how.get(bid, "grounded_search"),
                            bid,
                        ],
                    )
            except psycopg.Error as exc:  # never retried every night: the lookup is marked done
                stats["write_failed"] += 1
                log.warning("lookup.write_failed", business_id=bid, error=str(exc)[:200])
                conn.execute(
                    "update public.businesses set extra = extra || jsonb_build_object('website_lookup_at', %s::text, "
                    "'website_lookup', 'write_failed') where id = %s",
                    [now.isoformat(), bid],
                )
        for bid in guess_missed:
            if bid in names:
                continue
            conn.execute(
                "update public.businesses set extra = extra || jsonb_build_object('website_guess_at', %s::text, "
                "'website_guess', 'not_found') where id = %s",
                [now.isoformat(), bid],
            )
            stats["waiting_search"] += 1
    return stats


# ---------------------------------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------------------------------


def _grounded(
    rc: RunContext,
    router: Any,
    rows: Sequence[dict[str, Any]],
    segments: Mapping[str, Any],
    stats: Counter[str],
) -> tuple[dict[str, str], dict[str, str], float]:
    """Grounded lookups within the lookup use's allowance: ({id: cited url}, {id: name looked up}, INR)."""
    found: dict[str, str] = {}
    names: dict[str, str] = {}
    spent = 0.0
    run_result = getattr(router, "run_result", None) if router is not None else None
    if run_result is None:
        stats["skipped_no_router"] += len(rows)
        return found, names, spent
    budget = getattr(router, "budget", None)
    for b in rows:
        if grounding.allowance("lookup", budget) <= 0:
            stats["stopped_quota"] += 1
            break
        if rc.time_left() <= 0:
            stats["stopped_time"] += 1
            break
        seg = segments[b["segment_id"]]
        inputs = {
            "name": b["name"],
            "city": b.get("city") or "",
            "country": country_name(seg.country),
            "need": str(b.get("need") or "")[:200],
        }
        try:
            res = run_result(TASK, inputs)
        except Exception as exc:  # typed router errors: stop on budget, skip one stubborn business
            name = type(exc).__name__
            stats[f"error.{name}"] += 1
            if name in ("BudgetExceeded", "BudgetStop"):
                break
            continue
        spent += float(getattr(res, "inr", 0) or 0)
        stats["looked_up"] += 1
        names[b["id"]] = str(b["name"])
        url = candidate_url(res.output, res.grounding)
        if url:
            found[b["id"]] = url
        else:
            stats["not_found"] += 1
    return found, names, spent


def run(
    rc: RunContext,
    router: Any = None,
    *,
    resolve: Resolve | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """`nlead lookup`: official websites for signal-born businesses that have none (free guess, then search)."""
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    segments = score.enabled_segments(rc)
    limit = health.setting_int(SETTING, DEFAULT_PER_RUN)
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    signals_only = [s.id for s in segments.values() if s.universe == "signals_only"]
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "signals_only": signals_only, "limit": limit})
    stats["candidates"] = len(rows)
    if rc.opts.dry_run or not rows:
        rc.stats["lookup"] = dict(stats)
        return dict(stats)

    to_guess = [b for b in rows if "website_guess_at" not in (b.get("extra") or {})]
    countries = {b["id"]: segments[b["segment_id"]].country for b in to_guess}
    seconds = min(GUESS_SECONDS, max(rc.time_left(), 0.0))
    guesses = asyncio.run(guess_sites(to_guess, countries, resolve=resolve, transport=transport, seconds=seconds))
    guessed = {bid: g.url for bid, g in guesses.items() if g.url}
    for g in guesses.values():
        stats[f"guess_{g.status}"] += 1

    rest = [b for b in rows if b["id"] not in guessed]
    found: dict[str, str] = {}
    names: dict[str, str] = {}
    spent = 0.0
    if rest:
        if router is None:
            try:
                router = ai.router_for(rc)
            except Exception as exc:  # no AI today: the guesses found so far are still saved
                log.warning("lookup.no_router", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        found, names, spent = _grounded(rc, router, rest, segments, stats)
    checked = asyncio.run(check_sites(found, names, transport=transport)) if found else {}
    stats["found"] = len(checked)
    stats["rejected_site"] = len(found) - len(checked)

    by_id = {b["id"]: str(b["name"]) for b in rows}
    names_all = {**{bid: by_id[bid] for bid in guessed}, **names}
    via = {**{bid: "domain_guess" for bid in guessed}, **{bid: "grounded_search" for bid in checked}}
    missed = [bid for bid, g in guesses.items() if g.status == "not_found"]
    stats.update(write_results(rc.run_id, names_all, {**guessed, **checked}, now, via=via, guess_missed=missed))
    result: dict[str, Any] = {**stats, "inr": round(spent, 2)}
    rc.stats["lookup"] = result
    log.info("lookup.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
