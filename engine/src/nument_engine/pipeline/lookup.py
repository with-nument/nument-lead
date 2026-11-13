"""The official website of businesses born from a signal (the need-first track, 13 Nov 2026).

A job post or a public ask names a business and a city, rarely its website. Without a Google Maps key the Places
lookup never runs, so these businesses used to wait in prefilter rule R10 forever. One Gemini call with Google
Search grounding per business asks for the official website; code keeps it only when:

- the answer's domain is one the search actually cited, or that a backed sentence of the answer contains;
- it is not a never-fetch host (job boards, LinkedIn, X, marketplaces, directories);
- its home page, read politely (robots.txt respected), names the business: the page title, `og:site_name` or
  the visible text carries the business's distinctive words (`verify.names_match`).

Every business is looked up once (`extra.website_lookup_at`); R10 then passes it (with a website) or rejects it
(no contact route). Night stage, after `signals` and before `prefilter`.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final

from .. import db
from ..http import PoliteClient, host_blocked
from ..logging import get_logger
from ..normalize import web_domain
from . import ai, score
from .runs import RunContext
from .verify import distinctive_words

log = get_logger()

TASK: Final = "find_website"
SETTING: Final = "lookup.per_day"
DEFAULT_PER_DAY: Final = 40
COUNTRY_NAMES: Final[dict[str, str]] = {"in": "India", "ae": "the UAE", "sa": "Saudi Arabia", "qa": "Qatar"}
_TITLE: Final = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SITE_NAME: Final = re.compile(r"""<meta[^>]+property=["']og:site_name["'][^>]+content=["']([^"']+)""", re.I)
_TAGS: Final = re.compile(r"<[^>]+>")
# Words that end company names but are not the brand: "Brightcart Foods" is brightcart.in.
COMPANY_WORDS: Final = frozenset(
    ["foods", "food", "technologies", "technology", "tech", "solutions", "ventures", "labs", "services",
     "enterprises", "enterprise", "industries", "systems", "global", "digital", "software", "retail", "brands",
     "studio", "studios", "consulting", "innovations", "infotech", "networks", "corp", "corporation"]
)  # fmt: skip

CANDIDATES_SQL: Final = """
select b.id::text as id, b.name, b.city, b.segment_id, b.extra,
       (select s.details->>'need' from public.signals s where s.business_id = b.id
         order by s.observed_at desc limit 1) as need
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.website is null
   and b.extra ? 'born_from'
   and not b.extra ? 'website_lookup_at'
   and b.status in ('candidate', 'queued')
 order by b.created_at desc
 limit %(limit)s
"""


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


async def check_sites(found: dict[str, str], names: dict[str, str]) -> dict[str, str]:
    """{business id: final url} for the candidates whose home page names the business."""
    ok: dict[str, str] = {}
    async with PoliteClient("website_lookup", policy="public") as http:
        for bid, url in found.items():
            try:
                page = await http.get(url, raise_on_block=False, max_bytes=400_000)
            except Exception as exc:  # one bad site never stops the stage
                log.info("lookup.fetch_failed", url=url, error=type(exc).__name__)
                continue
            if page.state == "ok" and page_matches(names[bid], page.text, page.final_url or url):
                ok[bid] = page.final_url or url
    return ok


def run(rc: RunContext, router: Any = None) -> dict[str, Any]:
    """`nlead lookup`: official websites for signal-born businesses that have none."""
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    segments = score.enabled_segments(rc)
    per_day = db.get_setting(SETTING, DEFAULT_PER_DAY)
    limit = int(per_day) if isinstance(per_day, int | float) else DEFAULT_PER_DAY
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "limit": limit})
    stats["candidates"] = len(rows)
    if rc.opts.dry_run or not rows:
        rc.stats["lookup"] = dict(stats)
        return dict(stats)
    router = router or ai.router_for(rc)
    run_result = getattr(router, "run_result", None) if router is not None else None
    if run_result is None:
        stats["skipped_no_router"] = len(rows)
        rc.stats["lookup"] = dict(stats)
        return dict(stats)
    budget = getattr(router, "budget", None)
    found: dict[str, str] = {}
    names: dict[str, str] = {}
    spent = 0.0
    for b in rows:
        quota = budget.grounding_quota_left() if budget is not None and hasattr(budget, "grounding_quota_left") else 1
        if quota is not None and quota <= 0:
            stats["stopped_quota"] += 1
            break
        if rc.time_left() <= 0:
            stats["stopped_time"] += 1
            break
        seg = segments[b["segment_id"]]
        inputs = {
            "name": b["name"],
            "city": b.get("city") or "",
            "country": COUNTRY_NAMES.get(seg.country, seg.country.upper()),
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
    checked = asyncio.run(check_sites(found, names)) if found else {}
    stats["found"] = len(checked)
    stats["rejected_site"] = len(found) - len(checked)
    with db.tx("engine", {"run_id": rc.run_id, "stage": "lookup"}) as conn:
        for bid in names:
            url = checked.get(bid)
            conn.execute(
                "update public.businesses set website = coalesce(%s, website), "
                "web_domain = coalesce(%s, web_domain), "
                "extra = extra || jsonb_build_object('website_lookup_at', %s::text, 'website_lookup', %s::text) "
                "where id = %s",
                [url, web_domain(url) if url else None, now.isoformat(), url or "not_found", bid],
            )
    result: dict[str, Any] = {**stats, "inr": round(spent, 2)}
    rc.stats["lookup"] = result
    log.info("lookup.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
