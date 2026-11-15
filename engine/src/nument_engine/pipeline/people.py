"""Who runs the business: the founder or owner of an A or B lead (plan 5.11.4, 13 Nov 2026; startups 15 Nov 2026).

A message that opens with "Hi Maya," gets more replies than "Hi,", and in the email-first countries (US, UK,
Australia, Canada, Singapore) a named person matters even more. The founder email stage needs the name too.

Startups (segments of the `firms` domain) first use what the engine already read, at no cost:
- founder names the sources put on signals (`details["founders"]`, contract 4.1): a funding article, a launch
  post or a filing (a filing's officers become `registry` contacts);
- founder facts from their own pages (`team_member` facts marked as founders, `decision_maker` facts with a
  founder or owner role), when verify has not already stored the person.
A name counts only as a full name with a role in charge; it is verified when a quote from its source contains
it (a filing's structured fields count as verified). These sources are re-read only when a new signal or fact
arrived since the last read (`extra.founders_read_at`).

Then, and for every other segment, one grounded search per lead asks who runs it, within
`grounding.allowance("people", budget)`. Code keeps the answer only when:
- a sentence the search results back contains the name (`reviews.supported_line`, the same rule as reviews);
- the role is one of a person in charge (`verify.DM_ROLE`: founder, owner, director, CEO, principal, partner);
- the line names this business (a distinctive word of its name).

Every person is stored as a name-only founder contact (`line = 'owner'`, `is_decision_maker`), with the source
and quote that back the name. Never a phone or an email here: phones come only from the business's own pages,
and emails from the founder email stage. LinkedIn and X stay snippet-only. Each business is searched once
(`extra.dm_lookup_at`).
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from .. import db
from ..http import PoliteClient, host_of
from ..logging import get_logger
from ..segments import country_name
from . import ai, grounding, score
from .evidence import vget
from .reviews import REDIRECT_HOSTS, supported_line
from .runs import RunContext
from .verify import DM_ROLE, distinctive_words, same_person

log = get_logger()

TASK: Final = "find_decision_maker"
SETTING: Final = "dm_lookup.per_day"
DEFAULT_PER_DAY: Final = 40
RESERVE_S: Final = 600  # stop this long before the run's deadline, so the message stage still runs (14 Nov 2026)
STARTUP_DOMAIN: Final = "firms"
FILING_SOURCES: Final = frozenset({"sec_edgar"})  # officers named in a filing are registry contacts
FOUNDER_FACT_FIELDS: Final = ("team_member", "decision_maker")
FOUNDER_WORDS: Final = re.compile(r"\b(?:co-?founder|founder|ceo|chief executive|owner|managing director)\b", re.I)
SEARCH_WHY: Final = "a founder or owner found by a backed search"

CANDIDATES_SQL: Final = """
select b.id::text as id, b.name, b.city, b.website, b.segment_id, b.extra
  from public.leads l
  join public.businesses b on b.id = l.business_id
 where l.stage = 'new'
   and l.grade in ('A', 'B')
   and b.segment_id = any(%(segments)s)
   and (not b.extra ? 'dm_lookup_at'
        or (b.segment_id = any(%(startups)s)
            and (exists (select 1 from public.signals s where s.business_id = b.id and s.details ? 'founders'
                          and s.created_at > coalesce((b.extra->>'founders_read_at')::timestamptz, '-infinity'))
                 or exists (select 1 from public.facts f where f.business_id = b.id and f.verified
                             and f.field = any(%(fact_fields)s)
                             and f.created_at > coalesce((b.extra->>'founders_read_at')::timestamptz,
                                                         '-infinity')))))
   and not exists (select 1 from public.contacts c where c.business_id = b.id and c.is_decision_maker
                   and c.name is not null and not c.do_not_contact)
 order by l.grade, l.created_at desc
 limit %(limit)s
"""
SIGNAL_FOUNDERS_SQL: Final = """
select source, url, quote, details from public.signals
 where business_id = %s and details ? 'founders' order by observed_at desc
"""
FACT_FOUNDERS_SQL: Final = """
select field, value, quote, url from public.facts
 where business_id = %s and field = any(%s) and verified and coalesce(verify_score, 0) >= 0
 order by created_at desc
"""


def names_business(line: str, business_name: str) -> bool:
    """Does the answer line name this business (a distinctive word of its name)?"""
    words = [w for w in distinctive_words(business_name) if len(w) >= 3] or business_name.lower().split()
    low = line.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low) for w in words)


def accepted(output: Any, grounding: dict[str, Any] | None, business_name: str) -> dict[str, str] | None:
    """{name, role, quote, url} when the search backs a person in charge of this business, else None."""
    name = str(getattr(output, "name", None) or "").strip()
    role = str(getattr(output, "role", None) or "").strip()
    line = str(getattr(output, "line", None) or "").strip()
    if not name or name.lower() in ("unknown", "none", "null") or len(name.split()) < 2:
        return None  # a full name only: "Maya" alone could be anyone
    if not role or not DM_ROLE.search(role):
        return None
    if not line or not names_business(line, business_name) or name.lower() not in line.lower():
        return None
    backed = supported_line(f"{name}, {role}", grounding) or supported_line(line, grounding)
    if backed is None or name.split()[-1].lower() not in backed[0].lower():
        return None
    return {"name": name[:120], "role": role[:80], "quote": backed[0], "url": backed[1] or ""}


def resolve_url(url: str) -> str:
    """A grounding redirect becomes the page it points at (the owner's LinkedIn profile, say), read from the
    Location header only: nothing at the target is fetched, so LinkedIn stays snippet-only (15 Nov 2026: the
    founder messages the owner there himself instead of the clinic's front desk)."""
    if not url or host_of(url) not in REDIRECT_HOSTS:
        return url

    async def follow() -> str:
        async with PoliteClient("review_citations", policy="public", min_gap_s=0.2) as http:
            return await http.location(url) or url

    try:
        return asyncio.run(follow())
    except Exception as exc:  # a nicety: never lose the person over it
        log.info("people.url_unresolved", error=type(exc).__name__)
        return url


# ---------------------------------------------------------------------------------------------------
# Startups: founders the sources and the site already named
# ---------------------------------------------------------------------------------------------------


def _quote_with(name: str, *texts: Any) -> str | None:
    """The first text that contains the full name (case aside), cut to 300 characters around it."""
    for text in texts:
        if not isinstance(text, str):
            continue
        at = text.lower().find(name.lower())
        if at >= 0:
            start = max(0, at - 120)
            return re.sub(r"\s+", " ", text[start : at + len(name) + 160]).strip()
    return None


def founders_from_signals(signals: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Founder contacts from `details["founders"]` on the business's signals (contract 4.1), newest first."""
    out: list[dict[str, Any]] = []
    for sig in signals:
        details = sig.get("details") if isinstance(sig.get("details"), Mapping) else {}
        founders = details.get("founders") if isinstance(details, Mapping) else None
        filing = str(sig.get("source") or "") in FILING_SOURCES
        for f in founders if isinstance(founders, list) else []:
            if not isinstance(f, Mapping):
                continue
            name = re.sub(r"\s+", " ", str(f.get("name") or "")).strip()
            role = str(f.get("role") or "Founder").strip() or "Founder"
            if len(name.split()) < 2 or not DM_ROLE.search(role):
                continue  # a full name with a role in charge only
            quote = _quote_with(name, sig.get("quote"), f.get("quote"))
            out.append(
                {
                    "name": name[:120],
                    "role": role[:80],
                    "source": "registry" if filing else "other",
                    "source_url": str(f.get("source_url") or sig.get("url") or "") or None,
                    "quote": quote,
                    "verified": filing or quote is not None,
                    "why": "a founder named in their filing" if filing else "a founder named in a news or launch item",
                }
            )
    return out


def founders_from_facts(facts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Founder contacts from verified facts of their own pages: team members marked as founders (extract v2) and
    decision makers with a founder or owner role."""
    out: list[dict[str, Any]] = []
    for f in facts:
        value = f.get("value")
        name = re.sub(r"\s+", " ", str(vget(value, "name") or "")).strip()
        role = str(vget(value, "role") or "").strip()
        founder = vget(value, "is_founder") is True or bool(FOUNDER_WORDS.search(role))
        if len(name.split()) < 2 or not founder:
            continue
        out.append(
            {
                "name": name[:120],
                "role": (role or "Founder")[:80],
                "source": "website",
                "source_url": f.get("url"),
                "quote": f.get("quote"),
                "verified": True,  # verify proved the quote on their own page
                "why": "a founder named on their own site",
            }
        )
    return out


def add_founders(business_id: str, run_id: str, now: datetime) -> Counter[str]:
    """Store the founders the sources and the site named that are not contacts yet; remember the read."""
    stats: Counter[str] = Counter()
    signals = db.fetch_all(SIGNAL_FOUNDERS_SQL, [business_id])
    facts = db.fetch_all(FACT_FOUNDERS_SQL, [business_id, list(FOUNDER_FACT_FIELDS)])
    known = [str(r["name"]) for r in db.fetch_all(
        "select name from public.contacts where business_id = %s and name is not null", [business_id]
    )]  # fmt: skip
    with db.tx("engine", {"run_id": run_id, "stage": "people"}) as conn:
        for kind, people in (("signals", founders_from_signals(signals)), ("facts", founders_from_facts(facts))):
            for p in people:
                if any(same_person(p["name"], k) for k in known):
                    continue  # already a contact (do-not-contact ones included: never added back)
                conn.execute(
                    "insert into public.contacts (business_id, name, role, source, source_url, quote, "
                    "is_decision_maker, verified, verified_at, line, line_why) "
                    "values (%s, %s, %s, %s, %s, %s, true, %s, %s, 'owner', %s)",
                    [business_id, p["name"], p["role"], p["source"], p["source_url"], p["quote"], p["verified"],
                     now if p["verified"] else None, p["why"]],
                )  # fmt: skip
                known.append(p["name"])
                stats[f"founders.{kind}"] += 1
        conn.execute(
            "update public.businesses set extra = extra || jsonb_build_object('founders_read_at', %s::text) "
            "where id = %s",
            [now.isoformat(), business_id],
        )
    return stats


# ---------------------------------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------------------------------


def run(rc: RunContext, router: Any = None) -> dict[str, Any]:
    """`nlead people`: the founder or owner of new A and B leads that have no named decision maker."""
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    segments = score.enabled_segments(rc)
    startups = [k for k, s in segments.items() if s.domain == STARTUP_DOMAIN]
    per_day = db.get_setting(SETTING, DEFAULT_PER_DAY)
    limit = int(per_day) if isinstance(per_day, int | float) else DEFAULT_PER_DAY
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    rows = db.fetch_all(
        CANDIDATES_SQL,
        {"segments": list(segments), "startups": startups, "fact_fields": list(FOUNDER_FACT_FIELDS), "limit": limit},
    )
    stats["candidates"] = len(rows)
    if rc.opts.dry_run or not rows:
        rc.stats["people"] = dict(stats)
        return dict(stats)

    todo: list[dict[str, Any]] = []
    for b in rows:  # free first: founders the startup sources and their own site already named
        if b["segment_id"] in startups:
            added = add_founders(str(b["id"]), rc.run_id, now)
            stats.update(added)
            if added.total() > 0:
                stats["named_free"] += 1
                continue
        if "dm_lookup_at" not in (b.get("extra") or {}):
            todo.append(b)
    if not todo:
        result: dict[str, Any] = dict(stats)
        rc.stats["people"] = result
        return result

    if router is None:
        try:
            router = ai.router_for(rc)
        except ai.AIStop as exc:
            stats["skipped_no_router"] = len(todo)
            log.info("people.no_router", reason=exc.reason[:120])
    run_result = getattr(router, "run_result", None) if router is not None else None
    if run_result is None:
        stats["skipped_no_router"] = len(todo)
        rc.stats["people"] = dict(stats)
        return dict(stats)
    left = grounding.allowance("people", getattr(router, "budget", None))  # once; spent searches count down
    spent = 0.0
    for b in todo:
        if left <= 0:
            stats["stopped_allowance"] += 1
            break
        if rc.time_left() <= RESERVE_S:
            stats["stopped_time"] += 1
            break
        seg = segments[b["segment_id"]]
        try:
            res = run_result(
                TASK,
                {"name": b["name"], "city": b.get("city") or "", "country": country_name(seg.country),
                 "website": b.get("website") or ""},
            )  # fmt: skip
        except Exception as exc:  # typed router errors: stop on budget, skip one stubborn business
            name = type(exc).__name__
            stats[f"error.{name}"] += 1
            if name in ai.BUDGET_ERRORS:
                break
            continue
        spent += float(getattr(res, "inr", 0) or 0)
        left -= max(len((getattr(res, "grounding", None) or {}).get("queries") or []), 1)
        stats["looked_up"] += 1
        person = accepted(res.output, res.grounding, str(b["name"]))
        if person and person["url"]:
            person["url"] = resolve_url(person["url"])
            stats["linkedin"] += "linkedin.com/" in person["url"]
        with db.tx("engine", {"run_id": rc.run_id, "stage": "people"}) as conn:
            if person:
                conn.execute(
                    "insert into public.contacts (business_id, name, role, source, source_url, quote, "
                    "is_decision_maker, verified, verified_at, line, line_why) "
                    "values (%s, %s, %s, 'other', %s, %s, true, true, now(), 'owner', %s)",
                    [b["id"], person["name"], person["role"], person["url"] or None, person["quote"], SEARCH_WHY],
                )
                stats["found"] += 1
            else:
                stats["not_found"] += 1
            conn.execute(
                "update public.businesses set extra = extra || jsonb_build_object('dm_lookup_at', %s::text) "
                "where id = %s",
                [now.isoformat(), b["id"]],
            )
    result = {**stats, "inr": round(spent, 2)}
    rc.stats["people"] = result
    log.info("people.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
