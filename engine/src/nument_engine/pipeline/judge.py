"""Judge (Step 11.10): the top model gives a second opinion on the best half of the day's scores.

Who: per segment, the newest unjudged score rows with fit 2 or more, best half by total plus every A.
A business whose facts, signals and total did not change keeps its old judgement, because scoring writes
a new row only when one of them changes (score.same_result).

Guardrails enforced in code (11.10.4):
1. the grade moves at most one step from the rule grade (clamped);
2. every cited id must be this business's verified fact or active signal, else the judgement is discarded;
3. every number and capitalised name in the note must come from what it cites, else the rule note is used;
4. at most two plain sentences and no dashes, else the rule note is used;
5. the angle must be one of the segment's angles and fit the business's signals, else the rule angle stays.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, cast

from .. import db
from ..logging import get_logger
from ..models import SIGNAL_CATEGORY, LeadJudgement, PitchMode, make_test_group
from ..segments import PACKAGED_OUTCOME, Segment
from . import ai, evidence, leads, score
from .evidence import Row, fact_text
from .lint import ClaimContext, claim_problems
from .runs import RunContext
from .verify import Exclusions, Suppression

log = get_logger()

GRADE_ORDER: Final = "ABCD"
MAX_NOTE_SENTENCES: Final = 2
AI_FAILURES_BEFORE_STOP: Final = 3
_DASHES: Final = re.compile(r"\s*[\u2013\u2014]\s*|\s+-\s+")
_ABBREV: Final = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|St|No|Pvt|Ltd|Co|Inc|vs)\.", re.I)


# Score s2.0 (13 Nov 2026): the judge moves the number, and the grade follows the number. Raising is rare and
# small; lowering is cheap, because a wrong lead costs the founder more than a missed one.
RAISE: Final = 5
LOWER_ONE: Final = 8
LOWER_MAX: Final = 15
RAISE_MIN_CONFIDENCE: Final = 0.7
RAISE_MIN_CITED: Final = 2
DISQUALIFY_MIN_CONFIDENCE: Final = 0.6
DISQUALIFIERS: Final = re.compile(
    r"\b(agency|agencies|software (?:vendor|company|house)|it services|chain|franchise|head office|hospital|"
    r"in.house tech|tech team|corporate|listed company)\b",
    re.I,
)

# A partner (white-label) lead is a marketing or design agency on purpose: being an agency is not a risk there.
PARTNER_DISQUALIFIERS: Final = re.compile(
    r"\b(software (?:vendor|company|house|agency)|dev(?:elopment)? (?:shop|agency)|it services|chain|franchise|"
    r"head office|in.house (?:tech|dev)|tech team|corporate|listed company)\b",
    re.I,
)


def clamp(rule_grade: str, proposed: str) -> str:
    """At most one step away from the rule grade: B may become A, B or C (11.10.4 rule 1)."""
    r, p = GRADE_ORDER.index(rule_grade), GRADE_ORDER.index(proposed)
    return GRADE_ORDER[max(r - 1, min(r + 1, p))]


def adjustment(rule_grade: str, judgement: LeadJudgement, cited: int, total: float, *, partner: bool = False) -> int:
    """Points the judge adds to or takes from the rule total (s2.0).

    A higher grade adds RAISE points, only with confidence of at least 0.7 and two cited facts or signals.
    A lower grade takes LOWER_ONE points, or LOWER_MAX for two grades or more. A D with a disqualifying risk
    (agency, chain, hospital, in-house tech team) takes the lead below 40, so it becomes D.
    """
    r, p = GRADE_ORDER.index(rule_grade), GRADE_ORDER.index(judgement.judge_grade)
    if (
        judgement.judge_grade == "D"
        and judgement.confidence >= DISQUALIFY_MIN_CONFIDENCE
        and any((PARTNER_DISQUALIFIERS if partner else DISQUALIFIERS).search(risk) for risk in judgement.risks)
    ):
        return int(min(-LOWER_MAX, 39 - total))
    if p < r:
        return RAISE if judgement.confidence >= RAISE_MIN_CONFIDENCE and cited >= RAISE_MIN_CITED else 0
    if p > r:
        return -LOWER_ONE if p - r == 1 else -LOWER_MAX
    return 0


def sentence_count(text: str) -> int:
    body = _ABBREV.sub(lambda m: m.group(0)[:-1], text.strip())
    return len([s for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()])


def clean_note(text: str) -> str:
    """Dashes become commas; spacing tidied."""
    return re.sub(r"\s{2,}", " ", _DASHES.sub(", ", text or "")).strip()


@dataclass
class Verdict:
    final_grade: str
    judge_grade: str | None
    note: str
    angle: str
    discarded: str | None = None
    note_replaced: str | None = None
    angle_rejected: bool = False
    cited: list[str] = field(default_factory=list)
    final_total: float | None = None  # rule total plus `adjust`, 0 to 100 (s2.0)
    adjust: int = 0


def angle_fits(seg: Segment, angle: str, mode: str, kept_types: set[str]) -> bool:
    """An angle of the segment that answers one of the business's signals (or fit_only for no signal)."""
    found = next((a for a in seg.angles if a.key == angle), None)
    if found is None:
        return False
    allowed = set(found.signals)
    if mode == "stated_need":
        return angle == "build_what_they_asked"
    return bool(allowed & kept_types) or ("fit_only" in allowed and mode == "fit_only")


def review(
    judgement: LeadJudgement,
    *,
    rule_grade: str,
    rule_angle: str,
    rule_note: str,
    mode: str,
    kept_types: set[str],
    seg: Segment,
    ctx: ClaimContext,
    total: float | None = None,
    grade_for: Callable[[float], str] | None = None,
    locked: bool = False,
) -> Verdict:
    """Apply the guardrails to one judgement.

    With `total` and `grade_for` (s2.0) the judge moves the number by `adjustment` and the grade is the grade of
    the new number; `locked` (fit gate failed, nobody reachable) keeps a D whatever the judge says. Without them
    the grade moves at most one step (s1.0).
    """
    cited: list[str] = []
    for raw in judgement.cited_ids:
        known = evidence.resolve_cited_id(raw, ctx.known_ids)
        if known is None:
            return Verdict(rule_grade, None, rule_note, rule_angle, discarded="bad_citation", final_total=total)
        cited.append(known)
    final_total, adjust = total, 0
    if total is not None and grade_for is not None:
        adjust = (
            0 if locked else adjustment(rule_grade, judgement, len(set(cited)), total, partner=seg.domain == "partners")
        )
        final_total = max(0.0, min(100.0, total + adjust))
        final = "D" if locked else grade_for(final_total)
    else:
        final = clamp(rule_grade, judgement.judge_grade)
    note = clean_note(judgement.judge_note)
    replaced = None
    if not note or sentence_count(note) > MAX_NOTE_SENTENCES or len(note) > 280:
        replaced = "shape"
    elif claim_problems([note], [cited], ctx, need_claim=False):
        replaced = "new_facts"
    angle = judgement.best_angle.strip()
    angle_ok = angle_fits(seg, angle, mode, kept_types)
    return Verdict(
        final_grade=final,
        judge_grade=final,
        note=rule_note if replaced else note,
        angle=angle if angle_ok else rule_angle,
        note_replaced=replaced,
        angle_rejected=not angle_ok,
        cited=cited,
        final_total=final_total,
        adjust=adjust,
    )


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def evidence_text(facts: Sequence[Row], signals: Sequence[Mapping[str, Any]], now: datetime) -> dict[str, str]:
    """Canonical id -> everything a claim may be checked against (value, quote, details, a signal's age)."""
    out: dict[str, str] = {}
    for f in facts:
        out[str(f["id"])] = f"{fact_text(f)} {f.get('quote') or ''}"
    for s in signals:
        details = " ".join(str(v) for v in (s.get("details") or {}).values() if isinstance(v, str | int | float))
        age = max(0, (now - s["observed_at"]).days)
        out[str(s["id"])] = f"{s['type'].replace('_', ' ')} {s.get('quote') or ''} {details} {age} days ago"
    return out


def business_numbers(b: Mapping[str, Any]) -> set[str]:
    """Counts the judge is shown in the score reasons: reviews (Places), branches and staff (verified facts)."""
    return {str(int(b[c])) for c in ("review_count", "branches_count", "staff_count") if b.get(c) is not None}


def trusted_words(seg: Segment, business: Mapping[str, Any], extra: Sequence[str] = ()) -> set[str]:
    """Words a note or message may use without a citation: the business's own name, the segment's
    places, our own copy (packaged outcome, angle labels and ideas) and the platforms we name."""
    texts = [
        str(business.get("name") or ""),
        str(business.get("city") or ""),
        str(business.get("locality") or ""),
        seg.display_name,
        seg.packaged_outcome,
        *(c.name for c in seg.cities),
        *(a for c in seg.cities for a in c.aliases),
        *(loc for c in seg.cities for loc in c.localities),
        *(f"{a.label} {a.idea}" for a in seg.angles),
        "Google Apna Internshala Naukri Practo India UAE Dubai Abu Dhabi Sharjah Ajman",
        *extra,
    ]
    return {w.strip(".,'\u2019()").lower() for t in texts for w in re.findall(r"[\w'\u2019.&]+", t)} - {""}


def trusted_numbers(seg: Segment) -> set[str]:
    """Numbers in our own angle copy (for example 'answered in 5 seconds')."""
    return {n for a in seg.angles for n in re.findall(r"\d+", a.idea)}


def contact_summary(contacts: Sequence[Row]) -> list[str]:
    """Contact types only, never the number or address (11.10.2)."""
    out = []
    for c in contacts:
        kind = (
            f"{'decision maker' if c.get('is_decision_maker') else 'business'} {c.get('phone_type')}"
            if c.get("phone_e164")
            else "email"
            if c.get("email")
            else None
        )
        if kind:
            out.append(f"{kind} from {str(c.get('source')).replace('_', ' ')}")
    return out


def fact_inputs(facts: Sequence[Row]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(f["id"]),
            "field": f["field"],
            "value": f.get("value"),
            "quote": f.get("quote") or "",
            "url": f.get("url") or "",
        }
        for f in facts
    ]


def signal_inputs(signals: Sequence[Mapping[str, Any]], now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": str(s["id"]),
            "type": s["type"],
            "category": s.get("category") or SIGNAL_CATEGORY.get(str(s["type"])),
            "observed_at": s["observed_at"].date().isoformat(),
            "age_days": max(0, (now - s["observed_at"]).days),
            "quote": s.get("quote") or "",
            "url": s.get("url") or "",
            "details": s.get("details") or {},
            "source": s.get("source") or "",
        }
        for s in signals
    ]


def judge_inputs(
    row: Mapping[str, Any],
    b: Mapping[str, Any],
    seg: Segment,
    facts: Sequence[Row],
    active: Sequence[Mapping[str, Any]],
    contacts: Sequence[Row],
    now: datetime,
) -> dict[str, Any]:
    reasons = row.get("reasons") or {}
    return {
        "segment_id": seg.id,
        "domain": seg.domain,
        "country": seg.country,
        "city": b.get("city") or "",
        "business_name": b.get("name") or "",
        "packaged_outcome_name": PACKAGED_OUTCOME[seg.domain],
        "pitch_mode": row["pitch_mode"],
        "total": float(row["total"]),
        "fit": int(row["fit"]),
        "can_pay": float(row["can_pay"]),
        "intent": float(row["intent"]),
        "reach": float(row["reach"]),
        "grade": reasons.get("rule_grade") or row["grade"],
        "reasons": {k: reasons.get(k) for k in ("fit", "can_pay", "intent", "reach")},
        "rule_note": row.get("judge_note") or "",
        "facts": fact_inputs(facts),
        "signals": signal_inputs(active, now),
        "contacts_summary": contact_summary(contacts),
        "allowed_angles": [a.key for a in seg.angles],
        "angles": [{"key": a.key, "label": a.label, "idea": a.idea} for a in seg.angles],
    }


# ---------------------------------------------------------------------------
# Selection and the stage
# ---------------------------------------------------------------------------

_CANDIDATES: Final = """
select s.*, b.segment_id
  from (select distinct on (s.business_id) s.*
          from public.scores s
          join public.businesses b on b.id = s.business_id
         where b.segment_id = any(%(segments)s) and b.status in ('researched', 'qualified')
         order by s.business_id, s.computed_at desc) s
  join public.businesses b on b.id = s.business_id
 where s.judge_model is null and s.computed_at >= %(since)s and s.fit >= 2
"""


def select_for_judging(rows: Sequence[Row], share: Mapping[str, float]) -> list[Row]:
    """Per segment: the best `share` by total (rounded up) plus every A; best first overall."""
    by_seg: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_seg[str(r["segment_id"])].append(r)
    picked: list[Row] = []
    for seg_id, items in by_seg.items():
        items = sorted(items, key=lambda r: (-float(r["total"]), str(r["business_id"])))
        top = math.ceil(share.get(seg_id, 0.5) * len(items))
        picked += [r for i, r in enumerate(items) if i < top or (r.get("reasons") or {}).get("rule_grade") == "A"]
    return sorted(picked, key=lambda r: -float(r["total"]))


def run(rc: RunContext, router: ai.AIRouter | None = None) -> dict[str, Any]:
    """`nlead judge`: second opinions for the top half, then the lead rules with the final grades."""
    now = datetime.now(UTC)
    segments = score.enabled_segments(rc)
    configs = score.segment_configs(segments)
    stats: Counter[str] = Counter()
    rows = db.fetch_all(_CANDIDATES, {"segments": list(segments), "since": now - score.JUDGE_LOOKBACK})
    for r in rows:
        r["id"], r["business_id"] = str(r["id"]), str(r["business_id"])
    picked = select_for_judging(rows, {k: c.judge_top_share for k, c in configs.items()})
    if rc.opts.limit:
        picked = picked[: rc.opts.limit]
    stats["candidates"], stats["selected"] = len(rows), len(picked)
    if rc.opts.dry_run or not picked:
        rc.stats["judge"] = dict(stats)
        return dict(stats)
    if router is None:
        try:
            router = ai.router_for(rc)
        except ai.AIUnavailable as exc:
            stats["ai.unavailable"] += 1
            log.warning("judge.no_ai", reason=exc.reason)
            rc.stats["judge"] = dict(stats)
            return dict(stats)
    suppressed = Suppression.load()
    excl = Exclusions.load()
    ids = [r["business_id"] for r in picked]
    biz = evidence.businesses(ids)
    facts = evidence.verified_facts(ids)
    signals = evidence.signals_for(ids)
    contacts = evidence.contacts_for(ids)
    states = leads.load_states(ids)
    judged: list[leads.Candidate] = []
    failures = 0
    for row in picked:
        bid = row["business_id"]
        b, seg = biz.get(bid), segments.get(str(row["segment_id"]))
        if b is None or seg is None:
            continue
        active = [s for s in signals.get(bid, []) if evidence.is_active(s, now)]
        b_facts = facts.get(bid, [])
        open_lead = states.get(bid, leads.LeadState()).open_lead
        try:
            res = ai.call(
                router,
                "judge_lead",
                judge_inputs(row, b, seg, b_facts, active, contacts.get(bid, []), now),
                LeadJudgement,
                run_id=rc.run_id,
                lead_id=(open_lead or {}).get("id"),
            )
        except ai.AIBudgetStop:
            stats["stopped.budget"] += 1
            break
        except ai.AIUnavailable:
            stats["ai.failed"] += 1
            failures += 1
            if failures >= AI_FAILURES_BEFORE_STOP:
                stats["stopped.ai_down"] += 1
                break
            continue
        failures = 0
        reasons = row.get("reasons") or {}
        rule_grade = str(reasons.get("rule_grade") or row["grade"])
        rule_angle = str(reasons.get("angle") or score.pick_angle(row["pitch_mode"], [], seg))
        kept_types = {str(i["type"]) for i in reasons.get("intent") or []}
        ctx = ClaimContext(
            known_ids={
                **{str(f["id"]).lower(): str(f["id"]) for f in b_facts},
                **{str(s["id"]).lower(): str(s["id"]) for s in active},
            },
            evidence_text=evidence_text(b_facts, active, now),
            trusted_words=trusted_words(seg, b, [str(b.get("subcategory") or ""), str(b.get("category") or "")]),
            trusted_numbers=trusted_numbers(seg) | business_numbers(b),
        )
        cfg = configs[seg.id]
        rule_total = float(reasons.get("rule_total") or row["total"])
        verdict = review(
            res.output,
            rule_grade=rule_grade,
            rule_angle=rule_angle,
            rule_note=str(row.get("judge_note") or ""),
            mode=str(row["pitch_mode"]),
            kept_types=kept_types,
            seg=seg,
            ctx=ctx,
            total=rule_total,
            grade_for=lambda t, cfg=cfg: score.grade_of(t, cfg),  # type: ignore[misc]
            locked=bool(reasons.get("fit_gate_failed")) or reasons.get("reach_kind") == "none",
        )
        final_total = float(verdict.final_total if verdict.final_total is not None else rule_total)
        record = {
            "angle": verdict.angle,
            "rule_angle": rule_angle,
            "cited_ids": verdict.cited,
            "risks": res.output.risks,
            "confidence": res.output.confidence,
            "proposed_grade": res.output.judge_grade,
            "discarded": verdict.discarded,
            "note_replaced": verdict.note_replaced,
            "adjust": verdict.adjust,
        }
        with db.tx("engine", {"run_id": rc.run_id, "stage": "judge"}) as conn:
            conn.execute(
                "update public.scores set judge_grade = %s, judge_note = %s, judge_model = %s, grade = %s, "
                "total = %s, reasons = reasons || %s where id = %s",
                [
                    verdict.judge_grade,
                    verdict.note,
                    res.tag,
                    verdict.final_grade,
                    final_total,
                    db.Jsonb({"judge": record, "rule_total": rule_total}),
                    row["id"],
                ],
            )
        stats["judged"] += 1
        if verdict.discarded:
            stats[f"judge_{verdict.discarded}"] += 1
        if verdict.note_replaced:
            stats[f"note_replaced.{verdict.note_replaced}"] += 1
        if verdict.angle_rejected:
            stats["angle_rejected"] += 1
        move = GRADE_ORDER.index(verdict.final_grade) - GRADE_ORDER.index(rule_grade)
        stats["grade.up" if move < 0 else "grade.down" if move > 0 else "grade.same"] += 1
        fresh = score.score_business(
            b, b_facts, signals.get(bid, []), contacts.get(bid, []), seg, configs[seg.id], excl, now, suppressed
        )
        judged.append(
            leads.Candidate(
                business_id=bid,
                segment_id=seg.id,
                score_id=row["id"],
                grade=verdict.final_grade,
                total=final_total,
                pitch_mode=str(row["pitch_mode"]),
                angle=verdict.angle,
                test_group=make_test_group(seg.id, cast(PitchMode, row["pitch_mode"]), verdict.angle),
                reach_kind=fresh.reach_kind,
                best_contact=fresh.best_contact,
                region=seg.country,
                evidence_ids=fresh.evidence_ids,
                has_email=fresh.has_email,
            )
        )
    if judged:
        plans = leads.plan_all(
            judged,
            states,
            {k: c.fit_only_max_pct for k, c in configs.items()},
            now,
            stats=stats,
            fit_only_min={k: c.fit_only_min_per_day for k, c in configs.items()},
        )
        with db.tx("engine", {"run_id": rc.run_id, "stage": "judge"}) as conn:
            leads.apply(conn, plans, now)
            conn.cursor().executemany(
                "update public.businesses set status = %(status)s where id = %(id)s and status <> %(status)s",
                [
                    {"id": c.business_id, "status": score.business_status(c.grade, plans.capped(c.business_id))}
                    for c in judged
                ],
            )
    result = dict(sorted(stats.items()))
    rc.stats["judge"] = result
    log.info("judge.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
