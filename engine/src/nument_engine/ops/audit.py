"""The weekly audit (Step 17.6): a stricter second look at 20 leads from the last 7 days.

1. Sample 20 leads created in the last 7 days: at least 2 per enabled segment and at least 4 grade A (when
   that many exist), the rest at random. The sample is seeded by the ISO week, so a re-run picks the same.
2. Re-fetch each business's key pages live through the polite HTTP client (every Step 18 rule applies),
   re-check the stored verified facts against the fresh text, and check the phone is still on the page.
3. Re-judge with the top model in audit mode (`weekly_audit`, prompt A.10) and compare grades.
4. Put 5 of the 20 in the founder's Audit queue (`content.queue`); the app records his marks as
   `activities` rows of type `feedback` with `payload.audit` = `correct` or `wrong` and `payload.reason`.

Stored as `reports` kind 'audit'. A dry run makes no paid calls and stores nothing: it samples, re-fetches
and re-checks facts only.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import phonenumbers

from .. import db
from ..learn import fmt
from ..learn.store import store_report
from ..logging import get_logger
from ..models import AuditResult
from ..pipeline.runs import RunContext
from . import bindings

log = get_logger()

SAMPLE_SIZE: Final[int] = 20
MIN_PER_SEGMENT: Final[int] = 2
MIN_GRADE_A: Final[int] = 4
QUEUE_SIZE: Final[int] = 5
PAGES_PER_BUSINESS: Final[int] = 4
PAGE_CHARS: Final[int] = 4000  # per page sent to the audit model
GRADE_ORDER: Final[str] = "ABCD"
TARGETS: Final[dict[str, float]] = {
    "grade_agreement": 0.85,
    "facts_still_verify": 0.95,
    "phones_still_present": 0.95,
    "founder_correct": 0.80,
}
IF_MISSED: Final[dict[str, str]] = {
    "grade_agreement": "Check prompts and weights, then run a full eval.",
    "facts_still_verify": "Shorten the re-research interval for the segments with stale facts.",
    "phones_still_present": "Check the verify step and where the phones came from.",
    "founder_correct": "Read the founder's reasons, fix the cause, add the five to the golden set.",
}
_PHONE_LIKE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")

Judge = Callable[[Mapping[str, Any], str], AuditResult]

CANDIDATES_SQL = """
select l.id::text as lead_id, l.business_id::text as business_id, l.segment_id, l.grade, l.pitch_mode,
       l.message, l.stage, b.name, b.website, b.country
from public.leads l
join public.businesses b on b.id = l.business_id
where l.created_at >= %(since)s and l.created_at < %(until)s
order by l.id
"""


@dataclass
class LeadAudit:
    lead_id: str
    business_id: str
    segment_id: str
    name: str
    grade: str
    pages_checked: int = 0
    facts_checked: int = 0
    facts_still_verify: int = 0
    stale_fact_ids: list[str] = field(default_factory=list)
    phone_checked: bool = False
    phone_still_present: bool | None = None
    audit_grade: str | None = None
    agreement: str | None = None  # same, one_step, two_plus
    message_claims_ok: bool | None = None
    notes: str | None = None
    error: str | None = None


def grade_agreement(rule: str, audit: str) -> str:
    """same, one_step or two_plus."""
    gap = abs(GRADE_ORDER.index(rule) - GRADE_ORDER.index(audit))
    return "same" if gap == 0 else "one_step" if gap == 1 else "two_plus"


def pick_sample(
    candidates: Sequence[Mapping[str, Any]],
    enabled_segments: Sequence[str],
    rng: random.Random,
    *,
    size: int = SAMPLE_SIZE,
) -> list[Mapping[str, Any]]:
    """Stratified sample: MIN_PER_SEGMENT per enabled segment, at least MIN_GRADE_A grade A, the rest random."""
    pool = sorted(candidates, key=lambda c: c["lead_id"])
    rng.shuffle(pool)
    chosen: list[Mapping[str, Any]] = []

    def take(rows: list[Mapping[str, Any]], n: int) -> None:
        for row in rows:
            if n <= 0 or len(chosen) >= size:
                return
            if row not in chosen:
                chosen.append(row)
                n -= 1

    for seg in sorted(enabled_segments):
        take([c for c in pool if c["segment_id"] == seg], MIN_PER_SEGMENT)
    missing_a = MIN_GRADE_A - sum(c["grade"] == "A" for c in chosen)
    if missing_a > 0:
        take([c for c in pool if c["grade"] == "A"], missing_a)
    take(pool, size - len(chosen))
    return chosen


def phone_digits(e164: str) -> str:
    """The national number of an E.164 phone, the part every local format of it contains."""
    try:
        return str(phonenumbers.parse(e164, None).national_number)
    except phonenumbers.NumberParseException:
        return re.sub(r"\D", "", e164)[-10:]


def phone_on_page(e164: str, texts: Sequence[str]) -> bool:
    """The phone appears in any page text, in any common format."""
    wanted = phone_digits(e164)
    for text in texts:
        for match in _PHONE_LIKE.findall(text):
            if re.sub(r"\D", "", match).endswith(wanted):
                return True
    return False


def _key_urls(business: Mapping[str, Any], facts: Sequence[Mapping[str, Any]]) -> list[str]:
    urls: list[str] = []
    if business.get("website"):
        urls.append(str(business["website"]))
    counts: dict[str, int] = {}
    for f in facts:
        if f.get("url"):
            counts[str(f["url"])] = counts.get(str(f["url"]), 0) + 1
    urls += [u for u, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if u not in urls]
    return urls[:PAGES_PER_BUSINESS]


def check_pages(
    lead: Mapping[str, Any],
    *,
    facts: Sequence[Mapping[str, Any]],
    contact: Mapping[str, Any] | None,
    fetch: bindings.Fetcher,
    still_there: bindings.QuoteChecker,
) -> tuple[LeadAudit, dict[str, str]]:
    """Re-fetch the key pages and re-check stored facts and the phone (free, no AI)."""
    out = LeadAudit(lead["lead_id"], lead["business_id"], lead["segment_id"], lead["name"], lead["grade"])
    texts = fetch(_key_urls(lead, facts))
    out.pages_checked = len(texts)
    if texts:
        everything = "\n".join(texts.values())
        for f in facts:
            if not f.get("quote"):
                continue
            out.facts_checked += 1
            if still_there(str(f["quote"]), texts.get(str(f.get("url")), everything)):
                out.facts_still_verify += 1
            else:
                out.stale_fact_ids.append(str(f["id"]))
        if contact and contact.get("phone_e164") and contact.get("source") == "website":
            out.phone_checked = True
            out.phone_still_present = phone_on_page(str(contact["phone_e164"]), list(texts.values()))
    return out, texts


def judge_lead(
    out: LeadAudit,
    lead: Mapping[str, Any],
    facts: Sequence[Mapping[str, Any]],
    texts: Mapping[str, str],
    judge: Judge,
) -> None:
    """Re-judge with the top model in audit mode (prompt A.10) and record the comparison."""
    inputs = {
        "business_name": lead["name"],
        "segment_id": lead["segment_id"],
        "grade": lead["grade"],
        "pitch_mode": lead["pitch_mode"],
        "message": lead.get("message") or "",
        "facts": [{"id": str(f["id"]), "field": f["field"], "value": f["value"]} for f in facts],
        "pages": [{"url": u, "text": t[:PAGE_CHARS]} for u, t in texts.items()],
    }
    result = judge(inputs, lead["lead_id"])
    out.audit_grade = result.audit_grade
    out.agreement = grade_agreement(lead["grade"], result.audit_grade)
    out.message_claims_ok = result.message_claims_ok
    out.notes = result.notes
    if result.stale_facts:
        ids = {s.removeprefix("F") for s in result.stale_facts}
        out.stale_fact_ids = sorted(set(out.stale_fact_ids) | ids)


def summarise(audits: Sequence[LeadAudit]) -> dict[str, Any]:
    """Shares against the 17.6.2 targets, and what to do about each one that is missed."""
    judged = [a for a in audits if a.agreement is not None]
    facts_checked = sum(a.facts_checked for a in audits)
    phones = [a for a in audits if a.phone_checked]
    claims = [a for a in audits if a.message_claims_ok is not None]

    def share(n: int, d: int) -> float | None:
        return n / d if d else None

    summary: dict[str, Any] = {
        "leads": len(audits),
        "judged": len(judged),
        "grade_agreement": share(sum(a.agreement in ("same", "one_step") for a in judged), len(judged)),
        "grade_same": share(sum(a.agreement == "same" for a in judged), len(judged)),
        "facts_still_verify": share(sum(a.facts_still_verify for a in audits), facts_checked),
        "facts_checked": facts_checked,
        "phones_still_present": share(sum(bool(a.phone_still_present) for a in phones), len(phones)),
        "phones_checked": len(phones),
        "message_claims_ok": share(sum(bool(a.message_claims_ok) for a in claims), len(claims)),
        "errors": sum(a.error is not None for a in audits),
        "targets": TARGETS,
    }
    summary["missed"] = [
        {"measure": k, "value": summary[k], "target": t, "action": IF_MISSED[k]}
        for k, t in TARGETS.items()
        if summary.get(k) is not None and summary[k] < t
    ]
    return summary


def render(summary: Mapping[str, Any], audits: Sequence[LeadAudit], queue: Sequence[str], start: datetime) -> str:
    lines = [
        f"# Weekly audit: leads created {fmt.day(start)} to {fmt.day(start + timedelta(days=6))}",
        "",
        f"- Grade agreement (same or one step): {fmt.pct(summary['grade_agreement'])} of {summary['judged']} "
        "(target 85%)",
        f"- Facts still verifying: {fmt.pct(summary['facts_still_verify'])} of {summary['facts_checked']} (target 95%)",
        f"- Phones still on the page: {fmt.pct(summary['phones_still_present'])} of {summary['phones_checked']} "
        "(target 95%)",
        f"- Message claims still true: {fmt.pct(summary['message_claims_ok'])}",
        f'- Founder\'s queue: {len(queue)} leads (Leads, filter "Audit this week")',
    ]
    for m in summary["missed"]:
        lines.append(f"- Missed {m['measure'].replace('_', ' ')}: {m['action']}")
    lines += [
        "",
        fmt.table(
            ["Lead", "Segment", "Grade", "Audit grade", "Facts still true", "Phone on page", "Notes"],
            [
                [
                    a.name,
                    a.segment_id,
                    a.grade,
                    a.audit_grade or fmt.NA,
                    f"{a.facts_still_verify} of {a.facts_checked}",
                    {True: "yes", False: "no", None: fmt.NA}[a.phone_still_present],
                    a.error or a.notes or "",
                ]
                for a in audits
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def _router_judge(rc: RunContext) -> Judge:
    runner = bindings.task_runner(rc)

    def judge(inputs: Mapping[str, Any], lead_id: str) -> AuditResult:
        result = runner("weekly_audit", inputs, lead_id=lead_id)
        return result if isinstance(result, AuditResult) else AuditResult.model_validate(result)

    return judge


def weekly(
    rc: RunContext,
    *,
    fetch: bindings.Fetcher | None = None,
    still_there: bindings.QuoteChecker | None = None,
    judge: Judge | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Run the audit. Production bindings are used for anything not passed in."""
    as_of = as_of or datetime.now(UTC)
    since = as_of - timedelta(days=7)
    candidates = db.fetch_all(CANDIDATES_SQL, {"since": since, "until": as_of})
    if rc.opts.segments:
        candidates = [c for c in candidates if c["segment_id"] in rc.opts.segments]
    enabled = [r["id"] for r in db.fetch_all("select id from public.segments where enabled order by id")]
    iso = as_of.isocalendar()
    rng = random.Random(iso.year * 100 + iso.week)
    sample = pick_sample(
        candidates, rc.opts.segments or enabled, rng, size=min(SAMPLE_SIZE, rc.opts.limit or SAMPLE_SIZE)
    )

    ai_judge: Judge | None = None
    if sample:  # bind production parts only when there is something to audit
        fetch = fetch or bindings.page_fetcher("audit")
        still_there = still_there or bindings.quote_checker()
        ai_judge = None if rc.opts.dry_run else (judge or _router_judge(rc))
    stop = bindings.stop_errors()
    audits: list[LeadAudit] = []
    for lead in sample:
        facts = db.fetch_all(
            "select id::text as id, field, value, quote, url from public.v_verified_facts where business_id = %s",
            [lead["business_id"]],
        )
        contact = db.fetch_one(
            "select phone_e164, source from public.v_primary_contact where business_id = %s", [lead["business_id"]]
        )
        assert fetch is not None and still_there is not None
        try:
            out, texts = check_pages(lead, facts=facts, contact=contact, fetch=fetch, still_there=still_there)
        except Exception as exc:  # one unreadable site must not sink the audit
            log.warning("audit.lead_failed", lead_id=lead["lead_id"], error=type(exc).__name__)
            out = LeadAudit(lead["lead_id"], lead["business_id"], lead["segment_id"], lead["name"], lead["grade"])
            out.error = f"{type(exc).__name__}: {str(exc)[:160]}"
            audits.append(out)
            continue
        if ai_judge is not None:
            try:
                judge_lead(out, lead, facts, texts, ai_judge)
            except stop as exc:  # budget cap or no provider left: keep the free checks, stop AI calls
                log.warning("audit.ai_stopped", error=type(exc).__name__)
                ai_judge = None
            except Exception as exc:  # a bad answer for one lead
                out.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        audits.append(out)

    queue = [a.lead_id for a in rng.sample(audits, min(QUEUE_SIZE, len(audits)))]
    summary = summarise(audits)
    content = {
        "kind": "audit",
        "summary": summary,
        "queue": queue,
        "leads": [asdict(a) for a in audits],
        "window": {"from": since.isoformat(), "to": as_of.isoformat()},
    }
    markdown = render(summary, audits, queue, since)
    report_id = None
    if rc.opts.dry_run:
        print(markdown)
    else:
        report_id = store_report("audit", since.date(), as_of.date(), content, markdown)
    rc.stats["audit"] = {
        "report_id": report_id,
        "leads": len(audits),
        "queue": len(queue),
        "grade_agreement": summary["grade_agreement"],
    }
    log.info("audit.done", report_id=report_id, leads=len(audits), missed=[m["measure"] for m in summary["missed"]])
    return {"report_id": report_id, "summary": summary, "queue": queue}


run = weekly
