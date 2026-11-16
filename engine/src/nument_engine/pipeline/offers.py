"""Offer matching (15 Nov 2026): one Nument offer per startup lead, a backup, and why now (`pick_offer`).

For new A and B leads in startup segments (domain `firms`) without an offer, the AI reads the startup profile, the
verified facts and the active signals, and picks one of the active offers in `public.offers`, a backup, and one
plain sentence on why now, citing the fact and signal ids it used. Code keeps a pick only when:

- the main offer is an active offer (a backup that is unknown, inactive or the same as the main one is dropped);
- the cited ids are this business's verified facts or active signals (at least one; unknown ids are dropped);
- why now is at most two plain sentences under 280 characters whose numbers and names all come from what it
  cites (the claim check the messages use); dashes become commas.

Any problem gets one rewrite with the problems as feedback. When neither answer is usable nothing is stored, an
`offer_failed` record goes on the lead's timeline, and a lead with two of those in a week waits. Rank 1 (main)
and rank 2 (backup) are written to `lead_offers` together, with the `provider:model#pick_offer.vN` tag.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from .. import db
from ..logging import get_logger
from ..models import OfferPick
from ..segments import Segment, country_name
from . import ai, evidence, score
from .evidence import Row
from .judge import clean_note, evidence_text, fact_inputs, sentence_count, trusted_numbers, trusted_words
from .lint import ClaimContext, claim_problems
from .message import HIDDEN_FIELDS, profile_lines, short_name, startup_profiles, startup_signals
from .runs import RunContext

log = get_logger()

TASK: Final = "pick_offer"
STARTUP_DOMAIN: Final = "firms"
WHY_MAX_SENTENCES: Final = 2
WHY_MAX_CHARS: Final = 280
FAILED_MAX: Final = 2  # offer_failed records in FAILED_DAYS before a lead waits
FAILED_DAYS: Final = 7
AI_FAILURES_BEFORE_STOP: Final = 3

_SELECT: Final = """
select l.id, l.business_id, l.segment_id, l.grade, s.total
  from public.leads l
  left join public.scores s on s.id = l.score_id
 where l.stage = 'new' and l.grade in ('A', 'B') and l.segment_id = any(%(segments)s)
   and not exists (select 1 from public.lead_offers o where o.lead_id = l.id and o.rank = 1)
   and (select count(*) from public.activities a
         where a.lead_id = l.id and a.type = 'ai_output' and a.payload ->> 'kind' = 'offer_failed'
           and a.at > now() - make_interval(days => %(days)s)) < %(failed_max)s
 order by l.grade, s.total desc nulls last, l.created_at
"""


def is_startup(seg: Segment) -> bool:
    """Startup segments get offers, whatever channel they go out by."""
    return seg.domain == STARTUP_DOMAIN


def active_offers() -> dict[str, Row]:
    """The offers the founder sells today (public.offers, seeded by migration 0021), in his order."""
    rows = db.fetch_all(
        "select key, name, best_for, promise, timeline, typical_range from public.offers where active order by sort, key"
    )
    return {str(r["key"]): r for r in rows}


@dataclass
class Pick:
    """One `pick_offer` answer after the code checks."""

    offer_key: str
    backup_key: str | None
    why_now: str
    cited: list[str]
    confidence: float
    problems: list[str] = field(default_factory=list)  # everything wrong: the first answer gets a rewrite
    fatal: bool = False  # problems that make the answer unusable even after the drops


def review_pick(pick: OfferPick, offers: Mapping[str, Row], ctx: ClaimContext) -> Pick:
    """Check one answer: known offers, existing ids, a grounded why now."""
    problems: list[str] = []
    fatal = False
    key = pick.offer_key.strip()
    if key not in offers:
        problems.append(f"offer_key '{key}' is not one of the listed offer keys")
        fatal = True
    backup = (pick.backup_offer_key or "").strip() or None
    if backup is not None and (backup not in offers or backup == key):
        problems.append(f"backup_offer_key '{backup}' must be another key from the offers list, or null")
        backup = None
    cited: list[str] = []
    unknown: list[str] = []
    for raw in pick.cited_ids:
        known = evidence.resolve_cited_id(raw, ctx.known_ids)
        if known is None:
            unknown.append(raw)
        elif known not in cited:
            cited.append(known)
    if unknown:
        problems.append(f"cites ids that are not listed: {', '.join(unknown[:5])}")
    if not cited:
        problems.append("cites no listed fact or signal")
        fatal = True
    why = clean_note(pick.why_now)
    if not why:
        problems.append("why_now is empty")
        fatal = True
    elif sentence_count(why) > WHY_MAX_SENTENCES or len(why) > WHY_MAX_CHARS:
        problems.append("why_now must be one short plain sentence")
        fatal = True
    elif cited:
        bad = claim_problems([why], [cited], ctx, need_claim=False)
        if bad:
            problems += [f"why_now: {p}" for p in bad]
            fatal = True
    return Pick(key, backup, why, cited, float(pick.confidence), problems, fatal)


def pick_inputs(
    b: Row,
    seg: Segment,
    facts: Sequence[Row],
    active: Sequence[Row],
    profile: Row | None,
    offers: Mapping[str, Row],
    now: datetime,
) -> dict[str, Any]:
    """What the picker reads: the profile, verified facts and active signals with their ids, and the offers.
    Never a phone number or an address."""
    country = str(b.get("country") or seg.country).lower()
    return {
        "company": short_name(str(b.get("name") or "")),
        "country": country,
        "country_name": country_name(country).removeprefix("the "),
        "profile": profile_lines(profile, amounts=True),
        "facts": fact_inputs([f for f in facts if f["field"] not in HIDDEN_FIELDS]),
        "signals": startup_signals(active, now),
        "offers": [
            {
                "key": o["key"],
                "name": o["name"],
                "best_for": o["best_for"],
                "promise": o["promise"],
                "timeline": o["timeline"],
            }
            for o in offers.values()
        ],
        "feedback": [],
    }


def claim_context(
    b: Row, seg: Segment, facts: Sequence[Row], active: Sequence[Row], offers: Mapping[str, Row], now: datetime
) -> ClaimContext:
    """What a why-now sentence may cite and mention."""
    names = [short_name(str(b.get("name") or "")), *(f"{o['name']} {o['best_for']}" for o in offers.values())]
    return ClaimContext(
        known_ids={
            **{str(f["id"]).lower(): str(f["id"]) for f in facts},
            **{str(s["id"]).lower(): str(s["id"]) for s in active},
        },
        evidence_text=evidence_text(facts, active, now),
        trusted_words=trusted_words(seg, b, names),
        trusted_numbers=trusted_numbers(seg),
    )


def choose(first: Pick, second: Pick | None) -> Pick | None:
    """The rewrite when it is usable, else the first answer when it is, else nothing."""
    for p in (second, first):
        if p is not None and not p.fatal:
            return p
    return None


def store_pick(lead_id: str, p: Pick, tag: str, run_id: str) -> bool:
    """Write rank 1 and the backup (rank 2) for a lead that is still new. Returns True when stored."""
    with db.tx("engine", {"run_id": run_id, "stage": "offers"}) as conn:
        if conn.execute("select 1 from public.leads where id = %s and stage = 'new'", [lead_id]).fetchone() is None:
            return False
        conn.execute("delete from public.lead_offers where lead_id = %s", [lead_id])
        conn.execute(
            "insert into public.lead_offers (lead_id, rank, offer_key, why_now, cited_ids, model) "
            "values (%s, 1, %s, %s, %s, %s)",
            [lead_id, p.offer_key, p.why_now, p.cited, tag],
        )
        if p.backup_key:
            conn.execute(
                "insert into public.lead_offers (lead_id, rank, offer_key, why_now, cited_ids, model) "
                "values (%s, 2, %s, null, %s, %s)",
                [lead_id, p.backup_key, p.cited, tag],
            )
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'ai_output', %s)",
            [
                lead_id,
                db.Jsonb(
                    {
                        "kind": "offer_picked",
                        "task": TASK,
                        "model": tag,
                        "offer_key": p.offer_key,
                        "backup_offer_key": p.backup_key,
                        "cited_ids": p.cited,
                        "confidence": p.confidence,
                    }
                ),
            ],
        )
    return True


def record_failure(lead_id: str, problems: Sequence[str], tag: str | None, run_id: str) -> None:
    """Neither answer was usable: nothing is stored, the timeline says why."""
    with db.tx("engine", {"run_id": run_id, "stage": "offers"}) as conn:
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'ai_output', %s)",
            [lead_id, db.Jsonb({"kind": "offer_failed", "task": TASK, "issues": list(problems)[:10], "model": tag})],
        )


def _finish(rc: RunContext, stats: Counter[str]) -> dict[str, Any]:
    result = dict(sorted(stats.items()))
    rc.stats["offers"] = result
    log.info("offers.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result


def run(rc: RunContext, router: ai.AIRouter | None = None, **_: Any) -> dict[str, Any]:
    """`offers` phase: pick the offer, a backup and why now for new A and B startup leads without one."""
    now = datetime.now(UTC)
    segments = {k: s for k, s in score.enabled_segments(rc).items() if is_startup(s)}
    stats: Counter[str] = Counter()
    rows = (
        db.fetch_all(_SELECT, {"segments": list(segments), "days": FAILED_DAYS, "failed_max": FAILED_MAX})
        if segments
        else []
    )
    for r in rows:
        r["id"], r["business_id"] = str(r["id"]), str(r["business_id"])
    if rc.opts.limit:
        rows = rows[: rc.opts.limit]
    stats["selected"] = len(rows)
    if rc.opts.dry_run or not rows:
        return _finish(rc, stats)
    offers = active_offers()
    if not offers:
        stats["skipped.no_offers"] += 1
        return _finish(rc, stats)
    if router is None:
        try:
            router = ai.router_for(rc)
        except ai.AIUnavailable as exc:
            stats["ai.unavailable"] += 1
            log.warning("offers.no_ai", reason=exc.reason)
            return _finish(rc, stats)
    ids = list(dict.fromkeys(r["business_id"] for r in rows))
    biz = evidence.businesses(ids)
    facts = evidence.verified_facts(ids)
    signals = evidence.signals_for(ids)
    profiles = startup_profiles(ids)
    failures = 0
    for lead in rows:
        bid = lead["business_id"]
        b, seg = biz.get(bid), segments.get(str(lead["segment_id"]))
        if b is None or seg is None:
            continue
        active = [s for s in signals.get(bid, []) if evidence.is_active(s, now)]
        b_facts = facts.get(bid, [])
        if not b_facts and not active:
            stats["skipped.no_evidence"] += 1
            continue
        inputs = pick_inputs(b, seg, b_facts, active, profiles.get(bid), offers, now)
        ctx = claim_context(b, seg, b_facts, active, offers, now)
        try:
            res = ai.call(router, TASK, inputs, OfferPick, run_id=rc.run_id, lead_id=lead["id"])
            first = review_pick(res.output, offers, ctx)
            second: Pick | None = None
            tag = res.tag
            if first.problems:
                stats["rewrites"] += 1
                again = ai.call(
                    router,
                    TASK,
                    {**inputs, "feedback": first.problems},
                    OfferPick,
                    run_id=rc.run_id,
                    lead_id=lead["id"],
                )
                second = review_pick(again.output, offers, ctx)
                if not second.fatal:
                    tag = again.tag
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
        best = choose(first, second)
        if best is None:
            record_failure(lead["id"], (second or first).problems, tag, rc.run_id)
            stats["failed"] += 1
            continue
        if store_pick(lead["id"], best, tag, rc.run_id):
            stats["stored"] += 1
            stats[f"offer.{best.offer_key}"] += 1
        else:
            stats["skipped.changed_meanwhile"] += 1
    return _finish(rc, stats)
