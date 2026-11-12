"""The weekly report (Step 16.6): what to scale, what to cut, and how healthy the engine is.

Built every Monday for the last complete IST week (Monday to Sunday) and stored in `reports` (kind
'weekly') as numbers (`content`, for the app) and markdown. `content.caller` and `content.caller_markdown`
are the same report without money (no money won, no cost section) for the caller's view; the admin version
also goes to the GitHub job summary and, when configured, by email to everyone opted into the weekly report
(admins get the admin version, everyone else the caller version; `ops.emails`).

Sections, in order: headline; funnel by segment and country; signal type; pitch mode, angle and writer;
test groups to scale or cut; lead quality; cost (admin only); engine health; what the engine changed;
last eval and audit; suggested actions (at most five).
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import jinja2
import yaml

from .. import db
from ..logging import get_logger
from ..ops import emails, notify
from ..pipeline.runs import RunContext
from ..settings import ENGINE_DIR
from . import fmt
from .metrics import CUTS, CutRow, FunnelRow, all_cuts, ist_day_start, load_funnel, median
from .store import store_report

log = get_logger()

TEMPLATES = Path(__file__).resolve().parent / "templates"
FEEDBACK_REASONS: Final[tuple[str, ...]] = (
    "wrong_segment",
    "too_small",
    "too_big_or_corporate",
    "agency_or_vendor",
    "no_real_need",
    "cannot_reach",
    "already_has_solution",
    "bad_message",
    "great_lead",
    "other",
)
EXCLUSION_REASONS: Final[frozenset[str]] = frozenset({"agency_or_vendor", "too_big_or_corporate"})
EXCLUSION_MIN: Final[int] = 3
WRONG_CONTACT_TARGET, PHONE_TARGET, SIGNAL_AGE_TARGET = 0.05, 0.90, 30
AUDIT_AGREEMENT_TARGET: Final[float] = 0.85
MAX_ACTIONS: Final[int] = 5
CUT_TITLES: Final[dict[str, str]] = {
    "segment_id": "Segment",
    "country": "Country",
    "signal_type": "Signal type",
    "pitch_mode": "Pitch mode",
    "angle": "Angle",
    "test_group": "Test group",
    "grade": "Grade",
    "reach_type": "Reach",
    "writer": "Writer",
}
LABELS: Final[dict[tuple[str, str | None], str]] = {
    ("scale", None): "Scale",
    ("keep", None): "Keep",
    ("cut", None): "Cut",
    ("watch", None): "Watch",
    ("early_signal", "green"): "Early: promising",
    ("early_signal", "red"): "Early: weak",
}


@dataclass(frozen=True)
class Period:
    """One IST week, Monday to Sunday."""

    start: date
    end: date

    @property
    def start_at(self) -> datetime:
        return ist_day_start(self.start)

    @property
    def end_at(self) -> datetime:
        """Exclusive: midnight IST after `end`."""
        return ist_day_start(self.end + timedelta(days=1))

    def params(self) -> dict[str, Any]:
        return {"s": self.start_at, "e": self.end_at}


def report_week(today: date) -> Period:
    """The last complete Monday to Sunday before `today`."""
    start = today - timedelta(days=today.weekday() + 7)
    return Period(start, start + timedelta(days=6))


def week_of(monday: date) -> Period:
    if monday.weekday() != 0:
        raise ValueError(f"{monday} is not a Monday")
    return Period(monday, monday + timedelta(days=6))


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

HEADLINE_SQL = """
with ranks(stage, rnk) as (
  values ('contacted',1),('talking',2),('discovery_booked',3),('discovery_done',3),
         ('proposal_sent',4),('won',5),('retainer',5)
),
reach as (
  select a.lead_id,
         min(a.at) filter (where r.rnk >= 1) as at1,
         min(a.at) filter (where r.rnk >= 2) as at2,
         min(a.at) filter (where r.rnk >= 3) as at3,
         min(a.at) filter (where r.rnk >= 4) as at4,
         min(a.at) filter (where r.rnk >= 5) as at5
  from public.activities a
  join ranks r on r.stage = a.payload ->> 'to'
  where a.type = 'stage_change'
  group by a.lead_id
),
x as (
  select l.grade, l.created_at, l.deal_value_inr, l.stage,
         least(l.wa_at::timestamptz, r.at1) as first_contact_at, r.at2, r.at3, r.at4, r.at5
  from public.leads l
  left join reach r on r.lead_id = l.id
)
select
  count(*) filter (where created_at >= %(s)s and created_at < %(e)s) as leads_added,
  count(*) filter (where created_at >= %(s)s and created_at < %(e)s and grade in ('A','B')) as good_added,
  count(*) filter (where first_contact_at >= %(s)s and first_contact_at < %(e)s
                   and stage <> 'wrong_contact') as contacted,
  count(*) filter (where at2 >= %(s)s and at2 < %(e)s) as replied,
  count(*) filter (where at3 >= %(s)s and at3 < %(e)s) as meetings,
  count(*) filter (where at4 >= %(s)s and at4 < %(e)s) as proposals,
  count(*) filter (where at5 >= %(s)s and at5 < %(e)s) as won,
  coalesce(sum(deal_value_inr) filter (where at5 >= %(s)s and at5 < %(e)s), 0)::float as money_won_inr
from x
"""

PHONES_SQL = """
select count(*) as good_added,
       count(*) filter (where pc.phone_e164 is not null) as with_phone,
       count(*) filter (where pc.phone_e164 is not null and pc.source = 'website') as own_site_phone
from public.leads l
left join lateral (
  select c.phone_e164, c.source
  from public.contacts c
  where c.business_id = l.business_id and not c.do_not_contact
  order by (c.phone_e164 is not null) desc, c.is_decision_maker desc, (c.phone_type = 'mobile') desc,
           c.verified desc, (c.source = 'website') desc, c.created_at
  limit 1
) pc on true
where l.created_at >= %(s)s and l.created_at < %(e)s and l.grade in ('A','B')
"""

FACTS_SQL = """
select count(*) as n, count(*) filter (where verified) as verified
from public.facts where created_at >= %(s)s and created_at < %(e)s
"""

FEEDBACK_SQL = """
select f.rating, f.reason, l.segment_id, l.id::text as lead_id, l.message, b.name
from public.feedback f
join public.leads l on l.id = f.lead_id
join public.businesses b on b.id = l.business_id
where f.at >= %(s)s and f.at < %(e)s
order by f.at
"""

THUMBS_DOWN_SQL = """
select f.reason, b.web_domain, b.norm_name
from public.feedback f
join public.leads l on l.id = f.lead_id
join public.businesses b on b.id = l.business_id
where f.rating = -1
"""

AUDIT_MARKS_SQL = """
select a.payload ->> 'audit' as mark, count(*)::int as n
from public.activities a
where a.type = 'feedback' and a.payload ? 'audit' and a.at >= %(s)s and a.at < %(e)s
group by 1
"""

COST_SQL = """
select coalesce(sum(inr), 0)::float as inr, coalesce(sum(usd), 0)::float as usd,
       count(*) filter (where fallback_from is not null)::int as fallbacks
from public.costs where at >= %(s)s and at < %(e)s
"""

COST_DAYS_SQL = """
select (at at time zone 'Asia/Kolkata')::date as day, sum(inr)::float as inr
from public.costs where at >= %(s)s and at < %(e)s
group by 1 order by 1
"""

COST_TASKS_SQL = """
select task, provider, sum(calls)::int as calls, sum(inr)::float as inr
from public.costs where at >= %(s)s and at < %(e)s
group by 1, 2 order by 4 desc, 1 limit 8
"""

RESEARCHED_SQL = "select count(*)::int from public.businesses where researched_at >= %(s)s and researched_at < %(e)s"

RUNS_SQL = """
select kind, status, count(*)::int as n
from public.runs where started_at >= %(s)s and started_at < %(e)s
group by 1, 2 order by 1, 2
"""

FAILED_RUNS_SQL = """
select kind, started_at, error
from public.runs where status = 'failed' and started_at >= %(s)s and started_at < %(e)s
order by started_at desc limit 5
"""

SOURCES_SQL = """
select source, health, blocked_until, last_error
from public.v_source_health
where health in ('blocked', 'error', 'disabled') and not starts_with(source, 'llm:')
order by source
"""

BATCHES_SQL = """
select count(*) filter (where completed_at is not null
                          and completed_at - submitted_at > interval '12 hours')::int as slow,
       count(*) filter (where completed_at is null and status in ('submitted', 'running')
                          and submitted_at < %(e)s - interval '24 hours')::int as stuck,
       count(*)::int as total
from public.llm_batches where submitted_at >= %(s)s - interval '1 day' and submitted_at < %(e)s
"""

SHEET_ISSUES_SQL = """
select type, count(*)::int as n
from public.activities
where type in ('conflict_overridden', 'unknown_stage') and at >= %(s)s and at < %(e)s
group by 1
"""

VERSIONS_SQL = """
select version, method, reason, diff, created_by, created_at
from public.weight_versions where created_at >= %(s)s and created_at < %(now)s
order by version
"""

LAST_REWEIGHT_SQL = """
select stats -> 'reweight' as reweight
from public.runs where stats ? 'reweight' and started_at >= %(s)s
order by started_at desc limit 1
"""

LAST_REPORTS_SQL = """
select distinct on (kind) kind, created_at, content -> 'summary' as summary
from public.reports where kind in ('eval', 'audit')
order by kind, created_at desc
"""


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _label(row: CutRow) -> str:
    return LABELS.get((row.label, row.tone), row.label)


def _cut_table(cut: str, rows: Sequence[CutRow]) -> str:
    headers = [
        CUT_TITLES[cut],
        "Contacted",
        "Still open",
        "Replies",
        "Reply rate",
        "Meetings",
        "Meeting rate (90% range)",
        "Proposals per 20",
        "Wrong contacts",
        "Decision",
    ]
    body = [
        [
            f"`{r.key}`" if cut == "test_group" else r.key,
            r.contacted,
            r.open_leads,
            r.replied,
            fmt.pct(r.reply_rate),
            r.meetings,
            f"{fmt.pct(r.meeting_rate)} ({fmt.pct_range(r.meeting_ci90)})" if r.meeting.trials else fmt.NA,
            fmt.num(r.proposal_per_20, 1),
            r.wrong_contact,
            _label(r),
        ]
        for r in rows
    ]
    return fmt.table(headers, body) if body else f"No contacted leads by {CUT_TITLES[cut].lower()} yet."


def _headline(rec: Mapping[str, Any], admin: bool) -> str:
    parts = [
        f"**Leads added** {rec['leads_added']} (A or B: {rec['good_added']})",
        f"**Contacted** {rec['contacted']}",
        f"**Replies** {rec['replied']}",
        f"**Meetings** {rec['meetings']}",
        f"**Proposals** {rec['proposals']}",
        f"**Won** {rec['won']}",
    ]
    if admin:
        parts.append(f"**Money won** {fmt.inr(rec['money_won_inr'])}")
    return " · ".join(parts)


def _test_group_lines(rows: Sequence[CutRow]) -> list[str]:
    lines: list[str] = []
    for r in sorted(rows, key=lambda r: -(r.meeting_rate or 0)):
        if r.label == "scale":
            lines.append(f"Scale `{r.key}`: {fmt.pct(r.meeting_rate)} meetings from {r.meeting.trials} contacted.")
    for r in sorted(rows, key=lambda r: r.meeting_rate or 0):
        if r.label == "cut":
            lines.append(f"Cut `{r.key}`: {fmt.pct(r.meeting_rate)} meetings from {r.meeting.trials} contacted.")
    for r in rows:
        if r.label == "early_signal":
            word = "promising" if r.tone == "green" else "weak"
            lines.append(
                f"Early, {word}: `{r.key}` replies at {fmt.pct(r.reply_rate)} from {r.reply.trials} contacted "
                "(meetings not judged yet)."
            )
    return lines


def parse_reasons(raw: str | None) -> list[str]:
    """Feedback reasons from the app: a JSON list or text with the fixed codes (16.5). Unknown text is 'other'."""
    if not raw:
        return []
    text = raw.strip()
    tokens: list[str] = []
    if text.startswith("["):
        try:
            tokens = [str(t) for t in json.loads(text)]
        except ValueError:
            tokens = []
    if not tokens:
        tokens = re.findall(r"[a-z_]+", text.lower())
    found = [t for t in tokens if t in FEEDBACK_REASONS]
    return sorted(set(found)) or ["other"]


def _excluded_already() -> tuple[set[str], list[str]]:
    data = yaml.safe_load((ENGINE_DIR / "config" / "exclusions.yaml").read_text(encoding="utf-8")) or {}
    domains: set[str] = set()
    names: list[str] = []
    for chain in data.get("chains") or []:
        names.append(str(chain.get("name", "")).lower())
        domains |= {str(d).lower() for d in chain.get("domains") or []}
    names += [str(c).lower() for c in data.get("competitors") or []]
    return domains, [n for n in names if n]


def exclusion_suggestions(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Domains or name patterns thumbed down 3+ times as agency or corporate, not yet excluded (16.5.3)."""
    by_domain: Counter[str] = Counter()
    by_name: Counter[str] = Counter()
    for r in rows:
        if not EXCLUSION_REASONS & set(parse_reasons(r["reason"])):
            continue
        if r["web_domain"]:
            by_domain[str(r["web_domain"]).lower()] += 1
        words = str(r["norm_name"] or "").split()
        if words and len(words[0]) >= 4:
            by_name[" ".join(words[:2])] += 1
    domains, names = _excluded_already()
    out = [
        {"kind": "domain", "value": d, "count": n}
        for d, n in by_domain.items()
        if n >= EXCLUSION_MIN and d not in domains
    ]
    out += [
        {"kind": "name", "value": p, "count": n}
        for p, n in by_name.items()
        if n >= EXCLUSION_MIN and not any(p in x or x in p for x in names)
    ]
    return sorted(out, key=lambda s: (-s["count"], s["value"]))


def _quality(conn: Any, p: Period, rows: Sequence[FunnelRow]) -> dict[str, Any]:
    window_start = p.end_at - timedelta(days=30)
    tried = [r for r in rows if window_start <= r.attempted_at < p.end_at]
    wrong = sum(r.is_wrong_contact for r in tried)
    phones = db.fetch_one(PHONES_SQL, p.params(), conn=conn) or {}
    facts = db.fetch_one(FACTS_SQL, p.params(), conn=conn) or {}
    week_contacted = [r for r in rows if r.contacted and r.contacted_at and p.start_at <= r.contacted_at < p.end_at]
    signal_age = median(r.signal_age_days for r in week_contacted)
    feedback = db.fetch_all(FEEDBACK_SQL, p.params(), conn=conn)
    up = sum(f["rating"] == 1 for f in feedback)
    down = [f for f in feedback if f["rating"] == -1]
    reasons_by_segment: dict[str, Counter[str]] = defaultdict(Counter)
    for f in down:
        reasons_by_segment[f["segment_id"]].update(parse_reasons(f["reason"]))
    top_reasons = {seg: c.most_common(5) for seg, c in sorted(reasons_by_segment.items())}
    bad_messages = [f for f in feedback if "bad_message" in parse_reasons(f["reason"])]
    suggestions = exclusion_suggestions(db.fetch_all(THUMBS_DOWN_SQL, conn=conn))
    marks = {r["mark"]: r["n"] for r in db.fetch_all(AUDIT_MARKS_SQL, p.params(), conn=conn)}
    reply_then_unfit = sum(r.stage == "not_a_fit" and r.max_rank >= 2 for r in rows)

    good = phones.get("good_added") or 0
    phone_share = (phones.get("with_phone") or 0) / good if good else None
    own_share = (phones.get("own_site_phone") or 0) / good if good else None
    fact_share = (facts.get("verified") or 0) / facts["n"] if facts.get("n") else None
    age_text = "n/a" if signal_age is None else f"{fmt.num(signal_age, 1)} days"
    lines = [
        f"Wrong contacts: {fmt.pct(wrong / len(tried) if tried else None)} of numbers tried in the last 30 days "
        f"({wrong} of {len(tried)}). Target under {fmt.pct(WRONG_CONTACT_TARGET, 0)}.",
        f"New A and B leads with a phone the business published: {fmt.pct(phone_share)} "
        f"(from its own website: {fmt.pct(own_share)}). Target {fmt.pct(PHONE_TARGET, 0)} or more.",
        f"Median signal age at first contact: {age_text}. Target under {SIGNAL_AGE_TARGET} days.",
        f"Facts verified by code this week: {fmt.pct(fact_share)} of {facts['n']}."
        if facts.get("n")
        else "No facts were extracted this week.",
        f"Thumbs this week: {up} up, {len(down)} down.",
    ]
    for seg, reasons in top_reasons.items():
        lines.append(f"Thumbs down in {seg}: " + ", ".join(f"{k} ({n})" for k, n in reasons) + ".")
    if reply_then_unfit:
        lines.append(f"Replied, then not a fit: {reply_then_unfit} (counted as replies and as bad examples).")
    if marks:
        lines.append(
            f"Founder's audit marks this week: {marks.get('correct', 0)} correct, {marks.get('wrong', 0)} wrong."
        )
    return {
        "wrong_contact": {"wrong": wrong, "tried": len(tried), "rate": wrong / len(tried) if tried else None},
        "phones": {"good_added": good, "with_phone": phone_share, "own_site": own_share},
        "median_signal_age_days": signal_age,
        "facts": {"n": facts.get("n") or 0, "verified_share": fact_share},
        "thumbs": {"up": up, "down": len(down), "top_down_reasons": {s: dict(r) for s, r in top_reasons.items()}},
        "reply_then_not_a_fit": reply_then_unfit,
        "audit_marks": marks,
        "exclusion_suggestions": suggestions,
        "bad_messages": [
            {
                "lead_id": f["lead_id"],
                "segment_id": f["segment_id"],
                "name": f["name"],
                "message": (f["message"] or "")[:280],
            }
            for f in bad_messages
        ],
        "lines": lines,
        "exclusion_lines": [f"{s['kind']} `{s['value']}`: {s['count']} thumbs down" for s in suggestions],
        "bad_message_lines": [f'{f["name"]} ({f["segment_id"]}): "{(f["message"] or "")[:160]}"' for f in bad_messages],
    }


def _cost(conn: Any, p: Period, headline: Mapping[str, Any]) -> dict[str, Any]:
    total = db.fetch_one(COST_SQL, p.params(), conn=conn) or {"inr": 0.0, "usd": 0.0, "fallbacks": 0}
    days = db.fetch_all(COST_DAYS_SQL, p.params(), conn=conn)
    tasks = db.fetch_all(COST_TASKS_SQL, p.params(), conn=conn)
    researched = db.scalar(RESEARCHED_SQL, p.params(), conn=conn) or 0
    cap = float(db.get_setting("daily_cap_inr", 750, conn=conn))
    inr = float(total["inr"])
    avg = inr / 7

    def per(n: int) -> float | None:
        return inr / n if n else None

    top_day = max(days, key=lambda d: d["inr"]) if days else None
    unit = {
        "researched_business": per(researched),
        "good_lead": per(int(headline["good_added"])),
        "meeting": per(int(headline["meetings"])),
        "won_client": per(int(headline["won"])),
    }
    lines = [
        f"Spend this week: {fmt.inr(inr)} (${total['usd']:.2f}), {fmt.inr(avg)} a day on average against the "
        f"{fmt.inr(cap)} daily cap."
        + (f" Highest day: {fmt.day(top_day['day'])}, {fmt.inr(top_day['inr'])}." if top_day else ""),
        f"Per researched business: {fmt.inr(unit['researched_business'], 2)}; per good lead: "
        f"{fmt.inr(unit['good_lead'], 2)}; per meeting: {fmt.inr(unit['meeting'])}; per won client: "
        f"{fmt.inr(unit['won_client'])}.",
    ]
    if total["fallbacks"]:
        lines.append(f"Answers from a fallback model this week: {total['fallbacks']}.")
    return {
        "inr": inr,
        "usd": float(total["usd"]),
        "avg_per_day_inr": avg,
        "daily_cap_inr": cap,
        "by_day": [{"day": d["day"].isoformat(), "inr": d["inr"]} for d in days],
        "by_task": [dict(t) for t in tasks],
        "researched": researched,
        "per_unit_inr": unit,
        "fallbacks": total["fallbacks"],
        "lines": lines,
    }


def _health(conn: Any, p: Period) -> dict[str, Any]:
    runs = db.fetch_all(RUNS_SQL, p.params(), conn=conn)
    failed = db.fetch_all(FAILED_RUNS_SQL, p.params(), conn=conn)
    sources = db.fetch_all(SOURCES_SQL, conn=conn)
    batches = db.fetch_one(BATCHES_SQL, p.params(), conn=conn) or {"slow": 0, "stuck": 0, "total": 0}
    sheet = {r["type"]: r["n"] for r in db.fetch_all(SHEET_ISSUES_SQL, p.params(), conn=conn)}
    per_kind: dict[str, list[str]] = defaultdict(list)
    for r in runs:
        per_kind[r["kind"]].append(f"{r['n']} {r['status']}")
    lines = [
        "Runs: " + "; ".join(f"{k} {', '.join(v)}" for k, v in sorted(per_kind.items())) + "."
        if runs
        else "Runs: none this week."
    ]
    for f in failed:
        last = [ln for ln in str(f["error"] or "").strip().splitlines() if ln.strip()]
        lines.append(
            f"Failed: {f['kind']} at {fmt.when(f['started_at'])}: {(last[-1] if last else 'no error text')[:160]}"
        )
    blocked = [s for s in sources if s["health"] == "blocked"]
    errors = [s for s in sources if s["health"] == "error"]
    disabled = [s["source"] for s in sources if s["health"] == "disabled"]
    lines += [f"Blocked: {s['source']} until {fmt.day(s['blocked_until'])}." for s in blocked]
    lines += [f"Errors: {s['source']}: {str(s['last_error'] or '')[:120]}" for s in errors]
    if disabled:
        lines.append("Switched off: " + ", ".join(disabled) + ".")
    if batches["total"]:
        lines.append(f"AI batches: {batches['slow']} took over 12 hours; {batches['stuck']} stuck for over 24 hours.")
    if sheet:
        lines.append(
            f"Sheet edits overridden by a newer edit: {sheet.get('conflict_overridden', 0)}; "
            f"unknown stage text: {sheet.get('unknown_stage', 0)}."
        )
    return {
        "runs": [dict(r) for r in runs],
        "failed": [{"kind": f["kind"], "started_at": f["started_at"].isoformat()} for f in failed],
        "sources": [
            {
                "source": s["source"],
                "health": s["health"],
                "blocked_until": s["blocked_until"].isoformat() if s["blocked_until"] else None,
            }
            for s in sources
        ],
        "batches": dict(batches),
        "sheet": sheet,
        "lines": lines,
    }


def _changes(conn: Any, p: Period, reweight: Mapping[str, Any] | None) -> dict[str, Any]:
    versions = db.fetch_all(VERSIONS_SQL, {**p.params(), "now": datetime.now(UTC) + timedelta(days=1)}, conn=conn)
    if reweight is None:
        row = db.fetch_one(LAST_REWEIGHT_SQL, p.params(), conn=conn)
        reweight = row["reweight"] if row else None
    notes = {(c["segment_id"], c["key"]): c for c in (reweight or {}).get("changes", [])}
    lines: list[str] = []
    for v in versions:
        lines.append(f"Version {v['version']} ({v['method'].replace('_', ' ')}): {v['reason'] or 'no reason given'}.")
        for d in (v["diff"] or [])[:12]:
            why = notes.get((d.get("segment_id"), d.get("key")))
            extra = f" ({why['note']}, {why['trials']} leads, {why['event']})" if why else ""
            lines.append(f"  {d.get('segment_id') or 'all'} {d.get('key')}: {d.get('old')} to {d.get('new')}{extra}")
    status = (reweight or {}).get("status")
    gate = (reweight or {}).get("gate") or {}
    if status == "rejected_by_eval":
        lines.append(f"Weights proposal rejected by eval: {gate.get('detail', '')}")
    elif status == "not_checked":
        lines.append(f"Weights proposal not applied, the eval gate could not run: {gate.get('detail', '')}")
    elif status == "frozen":
        lines.append("Weights are frozen by the founder: nothing was changed.")
    elif status in (None, "no_change") and not versions:
        lines.append("No weight changes: not enough new outcomes yet.")
    for card in (reweight or {}).get("model_cards", []):
        verdict = "accepted" if card.get("accepted") else "not used"
        lines.append(
            f"Logistic model for {card['segment_id']} ({card['target']}, {card['sample_size']} leads): {verdict}; "
            f"AUC {fmt.num(card.get('auc_model'), 3)} vs {fmt.num(card.get('auc_points'), 3)} for the current score."
        )
    return {
        "versions": [
            {
                "version": v["version"],
                "method": v["method"],
                "reason": v["reason"],
                "diff": v["diff"],
                "created_at": v["created_at"].isoformat(),
            }
            for v in versions
        ],
        "reweight": reweight,
        "lines": lines,
    }


def _eval_audit(conn: Any) -> dict[str, Any]:
    latest = {r["kind"]: r for r in db.fetch_all(LAST_REPORTS_SQL, conn=conn)}
    lines: list[str] = []
    ev = latest.get("eval")
    if ev:
        s = ev["summary"] or {}
        verdict = "passed" if s.get("passed") else "failed"
        metrics = ", ".join(f"{m['label'].lower()} {m['display']}" for m in s.get("metrics", []) if m.get("display"))
        lines.append(f"Last eval {fmt.day(ev['created_at'])}: {verdict} on {s.get('items', 0)} businesses. {metrics}.")
    else:
        lines.append("No eval has run yet (Step 17.4).")
    au = latest.get("audit")
    if au:
        s = au["summary"] or {}
        lines.append(
            f"Last audit {fmt.day(au['created_at'])}: grade agreement {fmt.pct(s.get('grade_agreement'))} "
            f"(target 85%), facts still verifying {fmt.pct(s.get('facts_still_verify'))} (95%), phones still on "
            f"the page {fmt.pct(s.get('phones_still_present'))} (95%), message claims true "
            f"{fmt.pct(s.get('message_claims_ok'))}."
        )
    else:
        lines.append("No audit has run yet (Step 17.6).")
    return {
        "eval": None if not ev else {"created_at": ev["created_at"].isoformat(), "summary": ev["summary"]},
        "audit": None if not au else {"created_at": au["created_at"].isoformat(), "summary": au["summary"]},
        "lines": lines,
    }


def suggested_actions(content: Mapping[str, Any]) -> list[str]:
    """At most five plain actions, most important first."""
    actions: list[str] = []
    rows = content["cuts"].get("test_group", [])
    for r in sorted((r for r in rows if r["label"] == "scale"), key=lambda r: -(r["meeting_rate"] or 0))[:2]:
        seg = r["key"].split(":")[0]
        actions.append(
            f"Raise the daily quota for {seg}: `{r['key']}` books meetings at {fmt.pct(r['meeting_rate'])} "
            f"from {r['meeting']['trials']} contacted."
        )
    for r in sorted((r for r in rows if r["label"] == "cut"), key=lambda r: r["meeting_rate"] or 0)[:2]:
        actions.append(
            f"Consider pausing `{r['key']}`: {fmt.pct(r['meeting_rate'])} meetings from {r['meeting']['trials']} contacted."
        )
    q, h = content["quality"], content["health"]
    rate = q["wrong_contact"]["rate"]
    if rate is not None and rate > WRONG_CONTACT_TARGET and q["wrong_contact"]["tried"] >= 20:
        actions.append(f"Wrong contacts are at {fmt.pct(rate)}: check where phone numbers come from (verify step).")
    if h["failed"]:
        actions.append(f"{len(h['failed'])} run(s) failed this week: open the Engine page and re-run what failed.")
    for s in (s for s in h["sources"] if s["health"] == "blocked"):
        actions.append(
            f"{s['source']} is blocked until {fmt.day(s['blocked_until'])}: leave it, never work around a block."
        )
    cost = content.get("cost")
    if cost and cost["avg_per_day_inr"] > 0.8 * cost["daily_cap_inr"]:
        actions.append(f"Spend averaged {fmt.inr(cost['avg_per_day_inr'])} a day, near the cap: check cost by task.")
    if q["exclusion_suggestions"]:
        actions.append(
            f"Add {len(q['exclusion_suggestions'])} name(s) or domain(s) to exclusions.yaml (see Lead quality)."
        )
    ev = (content["eval_audit"]["eval"] or {}).get("summary") or {}
    if content["eval_audit"]["eval"] and not ev.get("passed"):
        actions.append("The last eval failed: fix it before changing prompts, models or weights.")
    au = (content["eval_audit"]["audit"] or {}).get("summary") or {}
    agreement = au.get("grade_agreement")
    if agreement is not None and agreement < AUDIT_AGREEMENT_TARGET:
        actions.append(f"Audit agreement is {fmt.pct(agreement)}: check prompts and weights, then run a full eval.")
    if not content["eval_audit"]["eval"]:
        actions.append("Label the golden set (Step 17.3) so every change can be checked before it goes live.")
    return actions[:MAX_ACTIONS] or ["Nothing needs action this week."]


# ---------------------------------------------------------------------------
# Build, render, store
# ---------------------------------------------------------------------------


def _render(content: Mapping[str, Any], admin: bool) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=False,  # markdown, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    tables = {cut: _cut_table(cut, [_row_from_dict(r) for r in content["cuts"][cut]]) for cut in CUTS}
    cost = content.get("cost") or {}
    tables["cost_by_task"] = fmt.table(
        ["Task", "Provider", "Calls", "Spend"],
        [[t["task"], t["provider"], t["calls"], fmt.inr(t["inr"], 2)] for t in cost.get("by_task", [])],
    )
    view = {**content, "headline": {**content["headline"], "line": _headline(content["headline"], admin)}}
    text = env.get_template("weekly.md.j2").render(c=view, t=tables, admin=admin)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _row_from_dict(d: Mapping[str, Any]) -> CutRow:
    from .metrics import Rate

    def rate(x: Mapping[str, Any]) -> Rate:
        return Rate(int(x["successes"]), int(x["trials"]))

    return CutRow(
        cut=d["cut"],
        key=d["key"],
        contacted=d["contacted"],
        replied=d["replied"],
        meetings=d["meetings"],
        proposals=d["proposals"],
        won=d["won"],
        wrong_contact=d["wrong_contact"],
        open_leads=d["open_leads"],
        reply=rate(d["reply"]),
        meeting=rate(d["meeting"]),
        proposal=rate(d["proposal"]),
        win=rate(d["win"]),
        label=d["label"],
        tone=d["tone"],
    )


def caller_view(content: Mapping[str, Any]) -> dict[str, Any]:
    """The report without money: no money won, no cost section (16.6.1)."""
    view = copy.deepcopy(dict(content))
    view.pop("cost", None)
    view.pop("caller", None)
    view.pop("caller_markdown", None)
    view["headline"] = {k: v for k, v in view["headline"].items() if k != "money_won_inr"}
    view["actions"] = [a for a in view["actions"] if "Spend averaged" not in a]
    return view


def build_weekly(
    period: Period, *, reweight: Mapping[str, Any] | None = None, conn: Any = None
) -> tuple[dict[str, Any], str, str]:
    """(content, admin markdown, caller markdown) for one week."""
    headline = db.fetch_one(HEADLINE_SQL, period.params(), conn=conn) or {}
    headline = {k: (float(v) if k == "money_won_inr" else int(v or 0)) for k, v in headline.items()}
    rows = load_funnel(conn, as_of=period.end_at)
    cuts = all_cuts(rows, period.end_at)
    content: dict[str, Any] = {
        "version": 1,
        "kind": "weekly",
        "period": {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "label": fmt.period(period.start, period.end),
        },
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "headline": headline,
        "cuts": {cut: [r.as_dict() for r in rows_] for cut, rows_ in cuts.items()},
        "test_groups": {"lines": _test_group_lines(cuts["test_group"])},
        "quality": _quality(conn, period, rows),
        "cost": _cost(conn, period, headline),
        "health": _health(conn, period),
        "changes": _changes(conn, period, reweight),
        "eval_audit": _eval_audit(conn),
        "admin_only": ["headline.money_won_inr", "cost"],
    }
    content["actions"] = suggested_actions(content)
    admin_md = _render(content, admin=True)
    caller = caller_view(content)
    caller_md = _render(caller, admin=False)
    content["caller"] = caller
    content["caller_markdown"] = caller_md
    return content, admin_md, caller_md


def save(period: Period, content: Mapping[str, Any], markdown: str, conn: Any = None) -> int:
    """Insert the report (kind 'weekly'); returns its id."""
    return store_report("weekly", period.start, period.end, content, markdown, conn=conn)


def weekly(rc: RunContext, *, week_start: date | None = None) -> dict[str, Any]:
    """Build, store and deliver the weekly report. A dry run prints it and stores nothing."""
    today = datetime.now(fmt.IST).date()
    period = week_of(week_start) if week_start else report_week(today)
    content, admin_md, _ = build_weekly(period, reweight=rc.stats.get("reweight"))
    result: dict[str, Any] = {"period": content["period"], "actions": len(content["actions"])}
    if rc.opts.dry_run:
        print(admin_md)
        result["report_id"] = None
    else:
        result["report_id"] = save(period, content, admin_md)
        notify.step_summary(admin_md)
        result["emailed"] = emails.send_weekly(content, admin_md, content["caller_markdown"]) > 0
    log.info("report.weekly", **{k: v for k, v in result.items() if k != "period"}, period=content["period"]["label"])
    rc.stats["report"] = {k: v for k, v in result.items() if k != "period"}
    return result
