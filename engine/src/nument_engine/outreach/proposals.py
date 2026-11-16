"""Proposal drafts after calls (write_proposal), contract 4.8.

After a discovery call the founder writes his notes in the app, which creates a `proposals` row (`status='draft'`,
`call_notes`, empty `content`). This phase fills `content` with a `write_proposal` draft built from the notes,
the lead's offer (and its typical range) and the plan page they saw, then the founder edits the prices and sends
it. Code keeps three promises the writer might bend: prices per milestone only when the notes name a budget, the
guarantee word for word, and no dashes. A proposal someone already filled or moved on is never overwritten.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Final

from .. import db
from ..logging import get_logger
from ..models import ProposalDraft
from ..pipeline import ai
from ..pipeline.runs import RunContext, outreach_mode
from .inbox import activity
from .replies import typical_range_text

log = get_logger()

GUARANTEE: Final = "If milestone 1 is not what we agreed, you do not pay for it."
AI_FAILURES_BEFORE_STOP: Final = 3
_MONEY: Final = re.compile(
    r"(?:[$\u20b9\u20ac\u00a3]\s?\d"
    r"|\b(?:usd|inr|eur|gbp|aed|sgd|aud|cad|rs\.?)\s?\d"
    r"|\d[\d,.]*\s?(?:k\s)?(?:usd|inr|eur|gbp|aed|sgd|aud|cad|dollars|rupees|lakhs?|lacs?|crores?)\b"
    r"|\bbudget\b.{0,25}?\d)",
    re.I,
)
_RANGE_DASH: Final = re.compile("(?<=[\\d%kKmM])\\s*[\u2013\u2014]\\s*(?=[\\d$\u20b9\u20ac\u00a3])")
_DASH: Final = re.compile("\\s*[\u2013\u2014]\\s*")

_TODO: Final = """
select p.id::text as id, p.lead_id::text as lead_id, p.call_notes, p.plan_token,
       b.name as company, pc.name as contact_name,
       o.key as offer_key, o.name as offer_name, o.promise as offer_promise, o.timeline as offer_timeline,
       o.typical_range
  from public.proposals p
  join public.leads l on l.id = p.lead_id
  join public.businesses b on b.id = l.business_id
  left join public.v_primary_contact pc on pc.business_id = l.business_id
  left join public.lead_offers lo on lo.lead_id = l.id and lo.rank = 1
  left join public.offers o on o.key = lo.offer_key
 where p.status = 'draft' and p.content = '{}'::jsonb and length(trim(coalesce(p.call_notes, ''))) > 0
 order by p.created_at
 limit %s
"""


def has_budget(notes: str) -> bool:
    """Do the call notes name an amount of money ("budget about $6k", "5 lakh", "USD 8000")?"""
    return bool(_MONEY.search(notes or ""))


def plain(text: str) -> str:
    """No en or em dashes in anything a client reads: a range dash becomes "to", any other a comma."""
    return _DASH.sub(", ", _RANGE_DASH.sub(" to ", text)).strip()


def _plain_all(value: Any) -> Any:
    if isinstance(value, str):
        return plain(value)
    if isinstance(value, list):
        return [_plain_all(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain_all(v) for k, v in value.items()}
    return value


def tidy(draft: ProposalDraft, notes: str) -> ProposalDraft:
    """Keep the promises: the guarantee word for word, milestone prices only with a stated budget, no dashes."""
    data = _plain_all(draft.model_dump())
    data["guarantee"] = GUARANTEE
    if not has_budget(notes):
        for m in data["milestones"]:
            m["price_usd"] = None
    return ProposalDraft.model_validate(data)


def plan_content(row: dict[str, Any]) -> Any:
    """The plan the lead saw: the proposal's own plan page, else the lead's latest live plan."""
    if row.get("plan_token"):
        hit = db.fetch_one("select content from public.plan_pages where token = %s", [row["plan_token"]])
        if hit:
            return hit["content"]
    hit = db.fetch_one(
        "select content from public.plan_pages where lead_id = %s and kind = 'plan' and status = 'live' "
        "order by created_at desc limit 1",
        [row["lead_id"]],
    )
    return hit["content"] if hit else None


def inputs_for(row: dict[str, Any]) -> dict[str, Any]:
    offer = (
        f"{row['offer_name']}: {row['offer_promise']} ({row['offer_timeline']})"
        if row.get("offer_key")
        else "to be decided from the call notes"
    )
    return {
        "company": str(row.get("company") or ""),
        "founder_name": str(row.get("contact_name") or ""),
        "offer": offer,
        "typical_range": typical_range_text(row.get("typical_range")),
        "call_notes": str(row["call_notes"]).strip(),
        "plan": plan_content(row),
    }


def run(rc: RunContext, *, router: ai.AIRouter | None = None, **_: Any) -> dict[str, Any]:
    """Draft the proposals whose call notes are in."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    rows = db.fetch_all(_TODO, [rc.opts.limit])
    stats: Counter[str] = Counter(waiting=len(rows))
    if rc.opts.dry_run or not rows:
        return {**stats, **({"skipped": "dry run"} if rc.opts.dry_run else {})}
    if router is None:
        try:
            router = ai.router_for(rc)
        except ai.AIUnavailable as exc:
            log.warning("proposals.no_ai", reason=exc.reason)
            return {**stats, "ai.unavailable": 1}
    failures = 0
    for row in rows:
        try:
            res = ai.call(
                router, "write_proposal", inputs_for(row), ProposalDraft, run_id=rc.run_id, lead_id=row["lead_id"]
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
        draft = tidy(res.output, str(row["call_notes"]))
        with db.tx("engine", {"run_id": rc.run_id, "stage": "proposals"}) as conn:
            n = db.execute(
                "update public.proposals set content = %s, model = %s, updated_at = now() "
                "where id = %s and status = 'draft' and content = '{}'::jsonb",
                [db.Jsonb(draft.model_dump()), res.tag, row["id"]],
                conn=conn,
            )
            if n:
                activity(
                    conn,
                    row["lead_id"],
                    "ai_output",
                    {"kind": "proposal_drafted", "proposal_id": row["id"], "model": res.tag},
                )
        stats["drafted" if n else "skipped.changed_meanwhile"] += 1
    result = dict(sorted(stats.items()))
    rc.stats["proposals"] = result
    log.info("proposals.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
