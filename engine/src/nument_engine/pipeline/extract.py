"""AI fact extraction as an overnight batch (Steps 9.11 to 9.14).

Night (`submit`): for each business crawled in this cycle, build the model input from its pages (most useful
first, repeated navigation lines removed, contact and price lines kept first, at most 16,000 tokens) and submit
one `extract_facts` batch through the AI router.

Morning (`collect`): read finished results from the router, validate each against `FactsExtraction`, flatten it
into `facts` rows (one row per fact, each with its quote, URL and page), replace that business's earlier AI facts,
mark the business `researched`, and add the `no_booking` signal when nothing on the site lets a customer book.

Batches go through `nument_engine.llm.batch` (Step 4.10.2): `submit(router, task, [BatchItem(key, inputs)])`
reserves the money, picks a batch-capable model and falls back to up to 40 sync calls; `collect(router, task=...)`
validates each finished item, logs batch-price costs and retries an invalid item once as a sync call through
`rebuild_inputs`. Item keys are `extract_facts:<business_id>`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from .. import db
from ..llm import batch as llm_batch
from ..logging import get_logger
from ..models import FactsExtraction
from ..normalize import canonical_url
from ..segments import Segment
from ..sources.base import AIRouter, Signal, SourceContext, field_of, is_ai_stop
from ..sources.jobs import quote_in
from .runs import RunContext
from .selection import active_segments
from .signals import SignalSink

log = get_logger()

TASK = "extract_facts"
CHARS_PER_TOKEN = 4
MAX_INPUT_TOKENS = 16_000
INSTRUCTION_TOKENS = 2_000
# Page order and token budgets (Step 9.11.1 and 9.11.2). Unused budget flows to the next page.
PAGE_BUDGET_TOKENS: dict[str, int] = {
    "home": 3000,
    "team": 2500,
    "contact": 1000,
    "careers": 2000,
    "locations": 1500,
    "pricing": 2000,
    "booking": 800,
    "about": 1500,
    "practo": 1500,
}
PAGE_ORDER = list(PAGE_BUDGET_TOKENS)
REPEATED_ON_PAGES = 3
BOILERPLATE = re.compile(
    r"cookie|all rights reserved|©|copyright|privacy policy|terms (?:and|&) conditions|share on|follow us|"
    r"subscribe|newsletter|sign up for|skip to (?:main )?content|back to top",
    re.I,
)
ONLY_SYMBOLS = re.compile(r"^[\W\d_]+$")
KEEP_FIRST = re.compile(
    r"\+?\d[\d\s().-]{7,}\d|@|₹|\brs\.?\s?\d|\baed\b|\bsar\b|price|fee|\bdr\.?\s|doctor|founder|director|ceo|"
    r"branch|centre|center|years|experience|book|appointment|whatsapp|hiring|\bjob",
    re.I,
)
NO_ONLINE_BOOKING = re.compile(r"call|phone|walk[- ]?in|visit|none|no online|not available", re.I)
ONLINE_BOOKING = re.compile(r"online|form|whatsapp|\bapp\b|portal|practo|book now|calendly|widget", re.I)

# The AI fact fields (A.13.2). Earlier rows of these fields are replaced when new results arrive.
AI_FIELDS = (
    "business_name",
    "decision_maker",
    "phone",
    "email",
    "branches",
    "staff_or_doctors",
    "service",
    "price_point",
    "booking_method",
    "whatsapp_present",
    "chat_widget",
    "careers_role",
    "in_house_tech",
    "is_agency_or_vendor",
    "language",
    "sales_note",
)


# ---------------------------------------------------------------------------------------------------
# Building the input (Step 9.11)
# ---------------------------------------------------------------------------------------------------


@dataclass
class PageIn:
    kind: str
    url: str
    text: str
    page_id: str


def trim_pages(pages: Sequence[PageIn], max_tokens: int = MAX_INPUT_TOKENS - INSTRUCTION_TOKENS) -> list[PageIn]:
    """Apply 9.11.3: repeated lines once (on the homepage), no boilerplate, key lines first, page budgets."""
    split = {p.url: [line.strip() for line in p.text.splitlines() if line.strip()] for p in pages}
    counts: Counter[str] = Counter()
    for lines in split.values():
        counts.update(set(lines))
    repeated = {line for line, n in counts.items() if n >= REPEATED_ON_PAGES}
    out: list[PageIn] = []
    carry = 0
    total_left = max_tokens * CHARS_PER_TOKEN
    seen_repeated: set[str] = set()
    for page in sorted(pages, key=lambda p: PAGE_ORDER.index(p.kind) if p.kind in PAGE_ORDER else len(PAGE_ORDER)):
        budget = min(PAGE_BUDGET_TOKENS.get(page.kind, 1000) * CHARS_PER_TOKEN + carry, total_left)
        lines = []
        for line in split[page.url]:
            if ONLY_SYMBOLS.match(line) or (BOILERPLATE.search(line) and len(line) < 160):
                continue
            if line in repeated:
                if page.kind != "home" or line in seen_repeated:
                    continue
                seen_repeated.add(line)
            lines.append(line)
        keep: set[int] = set()
        used = 0
        for pass_key in (True, False):
            for i, line in enumerate(lines):
                if i in keep or bool(KEEP_FIRST.search(line)) != pass_key:
                    continue
                if used + len(line) + 1 > budget:
                    if pass_key:
                        continue
                    break
                keep.add(i)
                used += len(line) + 1
        text = "\n".join(lines[i] for i in sorted(keep))
        carry = max(0, budget - used)
        total_left -= used
        if text:
            out.append(PageIn(page.kind, page.url, text, page.page_id))
        if total_left <= 0:
            break
    return out


def pages_block(pages: Sequence[PageIn]) -> str:
    """Step 9.11.4 format, so the model can cite each page's URL exactly."""
    return "\n".join(
        f"### PAGE {i}\nURL: {p.url}\nTEXT:\n{p.text}\n### END PAGE {i}" for i, p in enumerate(pages, start=1)
    )


def load_pages(business: dict[str, Any]) -> list[PageIn]:
    """This cycle's pages of a business, labelled by kind (home, team, contact, ...) from the crawl record."""
    kinds: dict[str, str] = ((business.get("extra") or {}).get("crawl") or {}).get("pages") or {}
    if not kinds:
        return []
    by_url = {url: kind for kind, url in kinds.items()}
    rows = db.fetch_all(
        "select id::text as id, url, text from public.pages where business_id = %s and url = any(%s) "
        "and text is not null and fetched_at > now() - interval '1 day'",
        [business["id"], list(by_url)],
    )
    return [PageIn(by_url[r["url"]], r["url"], r["text"], r["id"]) for r in rows]


def context_for(business_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """(structured data, tech flags, context text) from code facts: saves the model from re-finding them."""
    rows = db.fetch_all(
        "select field, value from public.facts where business_id = %s and model in ('rule', 'code') "
        "and field in ('jsonld_phone', 'jsonld_email', 'jsonld_name', 'jsonld_price_range', 'jsonld_employees', "
        "'tel_link', 'mailto_link', 'tech_stack')",
        [business_id],
    )
    structured = [
        {"field": r["field"], **(r["value"] if isinstance(r["value"], dict) else {"value": r["value"]})}
        for r in rows
        if r["field"] != "tech_stack"
    ]
    tech: Any = next((r["value"] for r in rows if r["field"] == "tech_stack"), {}) or {}
    flags = {k: v for k, v in tech.items() if k != "tools"} if isinstance(tech, dict) else {}
    tools = [t.get("tool") for t in tech.get("tools", [])] if isinstance(tech, dict) else []
    lines = []
    if tools:
        lines.append("Tools found on the site: " + ", ".join(str(t) for t in tools))
    for item in structured:
        if item["field"] in ("jsonld_phone", "tel_link"):
            how = "WhatsApp link" if item.get("via") == "whatsapp" else "phone link or structured data"
            lines.append(f"Phone published on the site ({how}): {item.get('number') or item.get('phone')}")
        elif item["field"] in ("jsonld_email", "mailto_link"):
            lines.append(f"Email published on the site: {item.get('email')}")
    return structured, flags, "\n".join(lines)


def build_inputs(business: dict[str, Any], seg: Segment, pages: list[PageIn]) -> dict[str, Any]:
    trimmed = trim_pages(pages)
    structured, flags, context = context_for(business["id"])
    branches = business.get("branches_count")
    if branches and branches > 1:
        context = (context + f"\nMap listings suggest {branches} branches.").strip()
    return {
        "segment_id": seg.id,
        "segment_label": seg.display_name,
        "domain": seg.domain,
        "country": seg.country,
        "business_name": business["name"],
        "website": business.get("website") or "",
        "structured_data": structured,
        "tech_flags": flags,
        "context": context,
        "pages": [{"url": p.url, "text": p.text, "kind": p.kind} for p in trimmed],
        "pages_block": pages_block(trimmed),
        "allowed_urls": [p.url for p in trimmed],
    }


ITEMS_SQL = """
select b.id::text as id, b.segment_id, b.name, b.website, b.place_id, b.branches_count, b.extra,
       exists (select 1 from public.contacts c where c.business_id = b.id) as has_contact,
       coalesce((b.extra #>> '{crawl,at}')::timestamptz >= b.queued_at, false) as crawled_since_queued
from public.businesses b
where b.status = 'queued' and b.queued_at > now() - interval '1 day' and b.segment_id = any(%(segments)s)
  and coalesce((b.extra #>> '{extract,submitted_at}')::timestamptz, 'epoch') < now() - interval '20 hours'
order by b.queue_priority desc nulls last
limit %(limit)s
"""


def build_items(
    segments: dict[str, Segment], limit: int, *, dry_run: bool
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Batch items for today's queue. Businesses with nothing to read are settled here without AI."""
    stats: Counter[str] = Counter()
    items: list[dict[str, Any]] = []
    for b in db.fetch_all(ITEMS_SQL, {"segments": list(segments), "limit": limit}):
        pages = load_pages(b)
        if not pages:
            if not b["crawled_since_queued"]:
                stats["waiting_for_research"] += 1  # research has not reached it yet: never reject it unread
                continue
            if b["place_id"] or b["has_contact"]:
                stats["researched_without_pages"] += 1  # Places, registry and signal data only (Step 9.4.1)
                if not dry_run:
                    mark_researched(b["id"])
            else:
                stats["rejected_no_material"] += 1
                if not dry_run:
                    db.execute(
                        "update public.businesses set status = 'rejected', reject_reason = 'no_research_material' "
                        "where id = %s",
                        [b["id"]],
                    )
            continue
        items.append({"key": item_key(b["id"]), "inputs": build_inputs(b, segments[b["segment_id"]], pages)})
    return items, stats


def item_key(business_id: str) -> str:
    return f"{TASK}:{business_id}"


def business_of(key: str) -> str:
    return key.split(":", 1)[1] if key.startswith(f"{TASK}:") else key


def rebuild_inputs(key: str, segments: dict[str, Segment]) -> dict[str, Any] | None:
    """Inputs for one item again, for the sync retry of an invalid or failed batch answer (Step 9.14.3)."""
    b = db.fetch_one(
        "select id::text as id, segment_id, name, website, place_id, branches_count, extra "
        "from public.businesses where id = %s",
        [business_of(key)],
    )
    if b is None or b["segment_id"] not in segments:
        return None
    pages = load_pages(b)
    return build_inputs(b, segments[b["segment_id"]], pages) if pages else None


def mark_researched(business_id: str) -> None:
    db.execute(
        "update public.businesses set status = 'researched', researched_at = now(), reject_reason = null "
        "where id = %s and status = 'queued'",
        [business_id],
    )


# ---------------------------------------------------------------------------------------------------
# Flattening (Step 9.14)
# ---------------------------------------------------------------------------------------------------

# schema attribute -> (facts.field, value keys taken from the item)
FLAT: dict[str, tuple[str, tuple[str, ...]]] = {
    "business_name": ("business_name", ("value",)),
    "decision_makers": ("decision_maker", ("name", "role", "is_decision_maker")),
    "phones": ("phone", ("number", "label", "belongs_to")),
    "emails": ("email", ("email",)),
    "branches": ("branches", ("count",)),
    "staff_or_doctors": ("staff_or_doctors", ("count",)),
    "services": ("service", ("name",)),
    "price_points": ("price_point", ("item", "amount", "currency")),
    "booking_method": ("booking_method", ("value",)),
    "whatsapp_present": ("whatsapp_present", ("value",)),
    "chat_widget": ("chat_widget", ("value",)),
    "careers_roles": ("careers_role", ("title", "category")),
    "in_house_tech": ("in_house_tech", ("value",)),
    "is_agency_or_vendor": ("is_agency_or_vendor", ("value",)),
    "languages": ("language", ("value",)),
    "sales_notes": ("sales_note", ("value",)),
}


def flatten(facts: FactsExtraction) -> list[tuple[str, dict[str, Any], str, str]]:
    """(field, value, quote, url) per fact. `business_name` keeps the plan's `{"name": ...}` value shape."""
    out: list[tuple[str, dict[str, Any], str, str]] = []
    for attr, (field_name, keys) in FLAT.items():
        raw = getattr(facts, attr)
        for item in raw if isinstance(raw, list) else [raw] if raw is not None else []:
            value = {k: getattr(item, k) for k in keys}
            if attr == "business_name":
                value = {"name": value["value"]}
            out.append((field_name, value, item.quote, item.url))
    return out


def page_for(url: str, quote: str, pages: dict[str, tuple[str, str]]) -> tuple[str, str | None]:
    """(url, page_id) for a fact. Models sometimes cite the homepage for a line of the contact page (9.18), so:
    the cited page when the quote is on it, else the page whose text holds the quote, else the cited page as
    given (verification then marks the fact unverified)."""
    canon = canonical_url(url) if url else ""
    cited = pages.get(canon)
    if cited is not None and quote_in(quote, cited[1]):
        return canon, cited[0]
    for page_url, (page_id, text) in pages.items():
        if quote_in(quote, text):
            return page_url, page_id
    if cited is not None:
        return canon, cited[0]
    return url, None


def parsed_of(result: Any) -> FactsExtraction | None:
    raw = field_of(result, "output")
    if raw is None:
        raw = field_of(result, "parsed")
    if isinstance(raw, FactsExtraction):
        return raw
    try:
        if isinstance(raw, BaseModel):
            return FactsExtraction.model_validate(raw.model_dump())
        if isinstance(raw, dict):
            return FactsExtraction.model_validate(raw)
        if isinstance(raw, str):
            return FactsExtraction.model_validate_json(raw)
    except ValidationError:
        return None
    return None


def write_facts(business_id: str, facts: FactsExtraction, model_tag: str) -> int:
    """Replace the business's AI facts with these, in one transaction. Returns the number of rows."""
    pages = {
        r["url"]: (r["id"], r["text"] or "")
        for r in db.fetch_all(
            "select id::text as id, url, text from public.pages where business_id = %s", [business_id]
        )
    }
    rows = []
    for field_name, value, quote, url in flatten(facts):
        cited, page_id = page_for(url, quote, pages)
        rows.append([business_id, field_name, Jsonb(value), quote, cited, page_id, model_tag])
    with db.tx() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from public.facts where business_id = %s and model <> 'rule' and field = any(%s)",
            [business_id, list(AI_FIELDS)],
        )
        if rows:
            cur.executemany(
                "insert into public.facts (business_id, field, value, quote, url, page_id, model, verified) "
                "values (%s, %s, %s, %s, %s, %s, %s, false)",
                rows,
            )
        cur.execute(
            "update public.businesses set status = 'researched', researched_at = now(), reject_reason = null, "
            "extra = extra - 'extract' where id = %s and status = 'queued'",
            [business_id],
        )
    return len(rows)


def no_booking_signal(business_id: str, facts: FactsExtraction) -> Signal | None:
    """Step 9.8: no booking tool, WhatsApp or chat on any page, and the extraction found no online booking."""
    row = db.fetch_one(
        """select b.website, b.web_domain, f.value as tech, (b.extra #>> '{crawl,state}') as crawl_state,
                  (select count(*) from public.pages p where p.business_id = b.id and p.text is not null) as n_pages
           from public.businesses b
           left join public.facts f on f.business_id = b.id and f.field = 'tech_stack' and f.model in ('rule', 'code')
           where b.id = %s""",
        [business_id],
    )
    if row is None or not row["website"] or row["crawl_state"] != "ok" or not row["n_pages"]:
        return None
    tech = row["tech"] if isinstance(row["tech"], dict) else {}
    if tech.get("has_booking") or tech.get("has_whatsapp") or tech.get("has_chat"):
        return None
    if facts.whatsapp_present is not None and facts.whatsapp_present.value:
        return None
    if facts.chat_widget is not None:
        return None
    method = facts.booking_method.value if facts.booking_method is not None else ""
    if method and ONLINE_BOOKING.search(method) and not NO_ONLINE_BOOKING.search(method):
        return None
    now = datetime.now(UTC)
    return Signal(
        type="no_booking",
        source="research",
        observed_at=now,
        url=row["website"],
        quote=f"No booking form, WhatsApp link or chat widget found on {row['n_pages']} pages checked",
        evidence_key=f"{row['web_domain']}|{now:%Y-%m}",
        business_id=business_id,
        details={"booking_method": method or None, "pages_checked": int(row["n_pages"])},
    )


HIRING_TYPES: Final[dict[str, str]] = {"frontdesk": "hiring_frontdesk", "builder": "hiring_builder"}


def hiring_signals(business_id: str, facts: FactsExtraction) -> list[Signal]:
    """Roles the business's own careers page lists (13 Nov 2026: they were stored as facts only).

    One signal per front-desk or builder role, quoting the page; the role title and month make the evidence key,
    so a role still listed next month counts again but the same listing never counts twice.
    """
    domain = db.scalar("select web_domain from public.businesses where id = %s", [business_id]) or business_id
    now = datetime.now(UTC)
    out: list[Signal] = []
    seen: set[str] = set()
    for role in facts.careers_roles:
        kind = HIRING_TYPES.get(role.category)
        title = role.title.strip()
        if kind is None or not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append(
            Signal(
                type=kind,
                source="research",
                observed_at=now,
                url=role.url,
                quote=role.quote,
                evidence_key=f"{domain}|{title.lower()}|{now:%Y-%m}",
                business_id=business_id,
                details={"role": title, "from": "careers_page"},
            )
        )
    return out


def ads_signal(business_id: str) -> Signal | None:
    """An advertising tag (Meta or Google Ads) on the business's own pages: they pay for leads (visible pain)."""
    row = db.fetch_one(
        """select b.web_domain, f.value as tech, f.quote, f.url
             from public.businesses b
             join public.facts f on f.business_id = b.id and f.field = 'tech_stack' and f.model in ('rule', 'code')
            where b.id = %s
            order by f.created_at desc limit 1""",
        [business_id],
    )
    tech = (row or {}).get("tech")
    if not row or not isinstance(tech, dict) or not tech.get("runs_ads_tag"):
        return None
    tools = [t for t in tech.get("tools") or [] if isinstance(t, dict) and t.get("kind") == "ads"]
    names = ", ".join(sorted({str(t.get("tool")) for t in tools if t.get("tool")})) or "an ads tag"
    page = next((str(t["page_url"]) for t in tools if t.get("page_url")), None) or row.get("url")
    now = datetime.now(UTC)
    return Signal(
        type="ads_running",
        source="research",
        observed_at=now,
        url=page,
        quote=f"Advertising tag on their website: {names}"[:300],
        evidence_key=f"{row['web_domain'] or business_id}|ads|{now:%Y-%m}",
        business_id=business_id,
        details={"tools": names, "from": "site_tag"},
    )


def ingest(results: Iterable[Any], ctx: SourceContext, segments: dict[str, Segment]) -> Counter[str]:
    """Write facts for each finished item (`llm.batch.ItemResult`); a failed one stays queued for tomorrow."""
    stats: Counter[str] = Counter()
    sink = SignalSink(segments, ctx)
    for result in results:
        bid = business_of(str(field_of(result, "key") or ""))
        if not bid:
            continue
        facts = parsed_of(result)
        tag = str(
            field_of(result, "tag")
            or f"{field_of(result, 'provider') or 'unknown'}:{field_of(result, 'model') or 'unknown'}#{TASK}"
        )
        if facts is None:
            stats["failed"] += 1
            if not ctx.dry_run:
                db.execute("update public.businesses set reject_reason = 'extract_failed' where id = %s", [bid])
            continue
        if ctx.dry_run:
            stats["would_write"] += 1
            continue
        stats["facts"] += write_facts(bid, facts, tag)
        stats["businesses"] += 1
        stats["sync_answers"] += bool(field_of(result, "sync"))
        seg_id = db.scalar("select segment_id from public.businesses where id = %s", [bid])
        if seg_id not in segments:
            continue
        found = [no_booking_signal(bid, facts), ads_signal(bid), *hiring_signals(bid, facts)]
        for sig in found:
            if sig is not None:
                sink.add(sig, segments[seg_id])
                stats[sig.type] += 1
    sink.flush()
    return stats


# ---------------------------------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------------------------------


def submit(rc: RunContext, *, router: AIRouter | None = None) -> dict[str, Any]:
    """Night: build today's items and submit the extraction batch (dry runs build the items only)."""
    ctx = SourceContext.from_run(rc, router)
    segments = active_segments(rc.opts.segments)
    limit = rc.opts.limit or int(db.get_setting("research_per_day", 800) or 800)
    items, stats = build_items(segments, limit, dry_run=rc.opts.dry_run)
    out: dict[str, Any] = {**stats, "items": len(items)}
    if rc.opts.dry_run:
        out["would_submit"] = len(items)
    elif items:
        out.update(_submit(ctx, items, segments))
    rc.stats["extract_submit"] = out
    log.info("extract.submitted", **{k: v for k, v in out.items() if isinstance(v, int | str)})
    return out


def _submit(ctx: SourceContext, items: list[dict[str, Any]], segments: dict[str, Segment]) -> dict[str, Any]:
    router = ctx.get_router()
    if router is None:
        return {"skipped": "no AI router"}
    try:
        result = llm_batch.submit(router, TASK, [llm_batch.BatchItem(i["key"], i["inputs"]) for i in items])
    except Exception as exc:  # BudgetExceeded and provider errors: items stay queued for the next night
        return {"stopped" if is_ai_stop(exc) else "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    jobs = list(field_of(result, "jobs") or [])
    submitted = [k for job in jobs for k in field_of(job, "keys", [])]
    out: dict[str, Any] = {
        "submitted": len(submitted),
        "batches": [field_of(job, "provider_batch_id") for job in jobs],
        "providers": sorted({str(field_of(job, "provider")) for job in jobs}),
        "deferred": len(field_of(result, "deferred") or []),
        "in_flight": len(field_of(result, "in_flight") or []),
        "reasons": list(field_of(result, "reasons") or [])[:5],
    }
    if submitted:
        db.execute(
            "update public.businesses set extra = jsonb_set(extra, '{extract}', %s) where id = any(%s)",
            [Jsonb({"submitted_at": datetime.now(UTC).isoformat()}), [business_of(k) for k in submitted]],
        )
    sync_results = list(field_of(result, "sync_results") or [])
    if sync_results:
        out["sync"] = dict(ingest(sync_results, ctx, segments))
    return out


def collect(rc: RunContext, *, router: AIRouter | None = None, max_wait_s: float = 0.0) -> dict[str, Any]:
    """Morning: collect finished batch results and store the facts. Unfinished batches wait for the next run."""
    ctx = SourceContext.from_run(rc, router)
    segments = active_segments(rc.opts.segments)
    out: dict[str, Any] = {}
    active = ctx.get_router()
    if active is None:
        out["skipped"] = "no AI router"
    else:
        try:
            result = llm_batch.collect(
                active, task=TASK, max_wait_s=max_wait_s, rebuild_inputs=lambda key: rebuild_inputs(key, segments)
            )
        except Exception as exc:  # recorded; the batches stay open for the next run
            result = None
            ctx.add("extract.collect_errors")
            log.error("extract.collect_failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        results = list(field_of(result, "results") or [])
        out = {
            "results": len(results),
            "failed_batches_items": len(field_of(result, "failed_keys") or []),
            "pending_batches": len(field_of(result, "pending") or []),
            **ingest(results, ctx, segments),
        }
    out.update({k: v for k, v in ctx.stats.items() if k not in out})
    rc.stats["extract_collect"] = out
    log.info("extract.collected", **{k: v for k, v in out.items() if isinstance(v, int | str)})
    return out
