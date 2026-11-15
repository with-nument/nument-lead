"""Personal 1-page plans (15 Nov 2026, contract 4.7): written by `write_plan` once day 0 went out, served at
{APP_URL}/p/<token>, and the two links the sequence waits for.

Each outreach run, only while settings `outreach.mode` is not "off":

1. Plans. A thread whose day-0 email was sent gets a plan page when its day-3 email is due within 24 hours, or
   when the founder's reply was sorted as wanting the plan or interested (never before day 0 is sent). One live
   plan per lead; the token is `secrets.token_urlsafe(16)` (22 characters, 128 bits) and the content is
   `PlanContent` as JSON, never HTML: the page renders it with its own components. Code checks the plan: no
   markup, links, placeholders or money talk, a timeline inside the offer's, and names and numbers about them that
   their evidence holds. The price range always comes from the offers table, never from the model. One rewrite;
   a plan that still fails is not stored, the try is logged, and the thread is tried again after
   PLAN_RETRY_HOURS, at most PLAN_MAX_TRIES times, after which the founder is told on the lead.
2. Links. `{plan_link}` in an unsent day-3 email becomes {APP_URL}/p/<token>; `{case_study}` in an unsent day-7
   email becomes {APP_URL}/c/<slug> of the newest published case study for the lead's offer (then its backup
   offer, then any published one), or https://nument.in when none is published. Sent, failed and cancelled
   messages are never touched.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import quote

from .. import db
from ..logging import get_logger
from ..models import PlanContent
from ..segments import Segment, country_name, load_segments
from ..settings import get_settings
from . import ai, evidence
from .evidence import Row
from .judge import clean_note, evidence_text, fact_inputs, trusted_numbers, trusted_words
from .lint import LINK, ClaimContext, claim_problems
from .message import (
    CASE_STUDY,
    PLAN_LINK,
    lead_offer_rows,
    offer_numbers,
    profile_lines,
    short_name,
    startup_profiles,
    startup_signals,
    writer_facts,
)
from .runs import RunContext, outreach_mode

log = get_logger()

TASK: Final = "write_plan"
DUE_WITHIN: Final = timedelta(hours=24)
PLAN_RETRY_HOURS: Final = 2
PLAN_MAX_TRIES: Final = 4
AI_FAILURES_BEFORE_STOP: Final = 3
UNSENT: Final = ("draft", "review", "approved", "queued")
WANTS_PLAN: Final = ("send_plan", "interested")
FALLBACK_CASE_STUDY: Final = "https://nument.in"
_MARKUP: Final = re.compile(r"<\s*/?\s*[A-Za-z!][^>]*>|&[a-z]+;|\]\(")
_MONEY: Final = re.compile(r"[$₹€£]\s*\d|\b(?:usd|inr|eur|gbp|aed)\b|\blakh\b|\bcrore\b", re.I)
_FILLER: Final = re.compile(r"\blorem\b|\bipsum\b|\bplaceholder\b|\btbd\b|[{}]|\[[^\]]*\]", re.I)
_NUMBER: Final = re.compile(r"\d+")
_WEEKS: Final = re.compile(r"\b(\d+)\s*(?:weeks?|wks?)\b|\bweek\s*(\d+)\b", re.I)


# ---------------------------------------------------------------------------
# The plan's own rules
# ---------------------------------------------------------------------------


def _money(value: float, inr: bool) -> str:
    if not inr:
        return f"${value:,.0f}"
    if value >= 100_000:
        return f"₹{value / 100_000:g} lakh"
    return f"₹{value:,.0f}"


def money_range(offer: Mapping[str, Any], country: str) -> str:
    """'Projects like this usually run $3,000 to $12,000, paid in milestones.' from the offer's typical range
    (rupees for India, dollars elsewhere); '' when the offer has no range."""
    ranges = offer.get("typical_range") or {}
    inr = country.lower() == "in"
    order = (("inr", False), ("inr_month", True), ("usd", False), ("usd_month", True)) if inr else (
        ("usd", False), ("usd_month", True)
    )  # fmt: skip
    for key, monthly in order:
        values = ranges.get(key)
        if isinstance(values, list) and len(values) == 2 and all(isinstance(v, int | float) for v in values):
            in_rupees = key.startswith("inr")
            text = f"{_money(float(values[0]), in_rupees)} to {_money(float(values[1]), in_rupees)}"
            if monthly:
                return f"Work like this usually runs {text} a month."
            return f"Projects like this usually run {text}, paid in milestones."
    return ""


def offer_weeks(offer: Mapping[str, Any]) -> int | None:
    """The longest the offer takes in weeks ('4 to 6 weeks' -> 6), None for monthly work."""
    numbers = [int(n) for n in _NUMBER.findall(str(offer.get("timeline") or ""))]
    return max(numbers) if numbers else None


def plan_texts(plan: PlanContent) -> list[tuple[str, str]]:
    """Every piece of text on the page, with where it sits."""
    out = [("headline", plan.headline), ("their_goal", plan.their_goal), ("next_step", plan.next_step)]
    out += [(f"scope_now[{i}]", t) for i, t in enumerate(plan.scope_now)]
    out += [(f"scope_later[{i}]", t) for i, t in enumerate(plan.scope_later)]
    out += [(f"timeline week {w.week}", w.deliverable) for w in plan.timeline]
    screen = plan.first_screen
    out += [("first_screen.app_name", screen.app_name), ("first_screen.title", screen.title)]
    for i, s in enumerate(screen.sections):
        out.append((f"first_screen.sections[{i}].label", s.label))
        out += [(f"first_screen.sections[{i}].items[{j}]", t) for j, t in enumerate(s.items)]
    return out


def plan_problems(plan: PlanContent, ctx: ClaimContext, offer: Mapping[str, Any]) -> list[str]:
    """What is wrong with a plan; an empty list means it may be published."""
    problems: list[str] = []
    for where, text in plan_texts(plan):
        if not text.strip():
            problems.append(f"{where} is empty")
        if _MARKUP.search(text):
            problems.append(f"{where} contains markup; write plain text")
        if LINK.search(text):
            problems.append(f"{where} contains a link")
        if _MONEY.search(text):
            problems.append(f"{where} mentions money; prices appear only in the range code adds")
        if _FILLER.search(text):
            problems.append(f"{where} contains placeholder text")
    weeks = [w.week for w in plan.timeline]
    if weeks != sorted(set(weeks)):
        problems.append("timeline weeks must go up one by one, each week once")
    longest = offer_weeks(offer)
    if longest is not None and weeks and max(weeks) > longest:
        problems.append(f"timeline runs to week {max(weeks)}, past the offer's {offer.get('timeline')}")
    if "nument" in plan.first_screen.app_name.lower():
        problems.append("first_screen.app_name must be their product, not Nument")
    for where, text in plan_texts(plan):
        for m in _WEEKS.finditer(text):
            n = int(m.group(1) or m.group(2))
            if longest is not None and n > longest:
                problems.append(f"{where} promises {n} weeks, past the offer's {offer.get('timeline')}")
    known = list(ctx.known_ids.values())
    problems += [
        f"{where}: {p}"
        for where, text in (("headline", plan.headline), ("their_goal", plan.their_goal))
        for p in claim_problems([_WEEKS.sub("weeks", text)], [known], ctx, need_claim=False)
    ]
    return list(dict.fromkeys(problems))


def finished_plan(plan: PlanContent, offer: Mapping[str, Any], country: str) -> PlanContent:
    """Dashes become commas everywhere; the price range is ours, from the offers table."""

    def clean(text: str) -> str:
        return clean_note(text)

    data = plan.model_dump(mode="json")
    for key in ("headline", "their_goal", "next_step"):
        data[key] = clean(data[key])
    data["scope_now"] = [clean(t) for t in data["scope_now"]]
    data["scope_later"] = [clean(t) for t in data["scope_later"]]
    for week in data["timeline"]:
        week["deliverable"] = clean(week["deliverable"])
    screen = data["first_screen"]
    screen["app_name"], screen["title"] = clean(screen["app_name"]), clean(screen["title"])
    for section in screen["sections"]:
        section["label"] = clean(section["label"])
        section["items"] = [clean(t) for t in section["items"]]
    data["typical_range"] = money_range(offer, country)
    return PlanContent.model_validate(data)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass
class PlanInput:
    thread_id: str
    lead_id: str
    business: Row
    segment: Segment
    offer: Row
    country: str
    inputs: dict[str, Any]
    claim_ctx: ClaimContext


def build_plan_input(
    thread_id: str,
    lead_id: str,
    b: Row,
    seg: Segment,
    offer: Row,
    backup: Row | None,
    facts: Sequence[Row],
    signals: Sequence[Row],
    profile: Row | None,
    now: datetime,
) -> PlanInput:
    active = [s for s in signals if evidence.is_active(s, now)]
    country = str(b.get("country") or seg.country).lower()
    name = short_name(str(b.get("name") or ""))
    inputs = {
        "company": name,
        "offer": str(offer["name"]),
        "offer_promise": str(offer.get("promise") or ""),
        "offer_timeline": str(offer.get("timeline") or ""),
        "offer_best_for": str(offer.get("best_for") or ""),
        "why_now": str(offer.get("why_now") or ""),
        "country_name": country_name(country).removeprefix("the "),
        "profile": profile_lines(profile),
        "facts": fact_inputs(writer_facts(facts)),
        "signals": startup_signals(active, now),
        "feedback": [],
    }
    offer_copy = [f"{o.get('name')} {o.get('promise')} {o.get('best_for')}" for o in (offer, backup) if o]
    ctx = ClaimContext(
        known_ids={
            **{str(f["id"]).lower(): str(f["id"]) for f in facts},
            **{str(s["id"]).lower(): str(s["id"]) for s in active},
        },
        evidence_text=evidence_text(facts, active, now),
        trusted_words=trusted_words(seg, b, [name, *offer_copy, "MVP MVPs"]),
        trusted_numbers=trusted_numbers(seg) | offer_numbers(offer, backup),
    )
    return PlanInput(thread_id, lead_id, b, seg, offer, country, inputs, ctx)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _lock_key(text: str) -> int:
    digest = hashlib.sha1(text.encode(), usedforsecurity=False).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def plan_url(token: str) -> str:
    return f"{get_settings().app_url.rstrip('/')}/p/{token}"


def store_plan(pi: PlanInput, plan: PlanContent, tag: str, run_id: str) -> str:
    """Publish the plan and return its token. One live plan per lead: a plan another run just published wins."""
    token = secrets.token_urlsafe(16)
    with db.tx("engine", {"run_id": run_id, "stage": "plans"}) as conn:
        conn.execute("select pg_advisory_xact_lock(%s)", [_lock_key(f"plan_page:{pi.lead_id}")])
        live = conn.execute(
            "select token from public.plan_pages where lead_id = %s and kind = 'plan' and status = 'live' "
            "and expires_at > now() order by created_at desc limit 1",
            [pi.lead_id],
        ).fetchone()
        if live is not None:
            return str(live["token"])
        conn.execute(
            "insert into public.plan_pages (token, lead_id, kind, content) values (%s, %s, 'plan', %s)",
            [token, pi.lead_id, db.Jsonb(plan.model_dump(mode="json"))],
        )
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'ai_output', %s)",
            [
                pi.lead_id,
                db.Jsonb({"kind": "plan_written", "task": TASK, "model": tag, "offer_key": pi.offer["offer_key"]}),
            ],
        )
    return token


def record_plan_failure(lead_id: str, problems: Sequence[str], tag: str | None, tries: int, run_id: str) -> None:
    """Log a failed try; after the last one the founder sees on the lead that day 3 waits for him."""
    with db.tx("engine", {"run_id": run_id, "stage": "plans"}) as conn:
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'ai_output', %s)",
            [lead_id, db.Jsonb({"kind": "plan_failed", "task": TASK, "issues": list(problems)[:10], "model": tag})],
        )
        if tries >= PLAN_MAX_TRIES:
            conn.execute(
                "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', "
                "'message_flagged', %s)",
                [
                    lead_id,
                    db.Jsonb(
                        {
                            "issues": [
                                "The 1-page plan could not be written, so the day-3 email still holds {plan_link}. "
                                "Edit that email or remove the link to send it.",
                                *list(problems)[:5],
                            ],
                            "task": TASK,
                        }
                    ),
                ],
            )


def fill(message_id: str, placeholder: str, url: str, run_id: str) -> bool:
    """Put the link into one unsent message; sent, failed and cancelled ones are never touched."""
    with db.tx("engine", {"run_id": run_id, "stage": "plans"}) as conn:
        cur = conn.execute(
            "update public.email_messages set body = replace(body, %s, %s), updated_at = now() "
            "where id = %s and direction = 'out' and status = any(%s) and strpos(body, %s) > 0",
            [placeholder, url, message_id, list(UNSENT), placeholder],
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Case studies
# ---------------------------------------------------------------------------


def published_case_studies() -> list[Row]:
    return db.fetch_all(
        "select slug, offer_key, created_at from public.case_studies where published order by created_at desc, slug"
    )


def case_study_url(studies: Sequence[Mapping[str, Any]], offer_keys: Sequence[str | None]) -> str:
    """The newest published case study for the lead's offer, then for its backup, then any; else nument.in."""
    base = get_settings().app_url.rstrip("/")
    for key in offer_keys:
        hit = next((s for s in studies if key and s.get("offer_key") == key), None)
        if hit is not None:
            return f"{base}/c/{quote(str(hit['slug']), safe='')}"
    if studies:
        return f"{base}/c/{quote(str(studies[0]['slug']), safe='')}"
    return FALLBACK_CASE_STUDY


# ---------------------------------------------------------------------------
# Selection and the phase
# ---------------------------------------------------------------------------

_DUE: Final = """
select distinct on (t.lead_id) t.id::text as thread_id, t.lead_id::text as lead_id,
       l.business_id::text as business_id, l.segment_id
  from public.email_threads t
  join public.leads l on l.id = t.lead_id
 where t.status <> 'done'
   and exists (select 1 from public.email_messages m where m.thread_id = t.id and m.direction = 'out'
                 and m.step = 0 and m.status = 'sent')
   and not exists (select 1 from public.plan_pages p where p.lead_id = t.lead_id and p.kind = 'plan'
                     and p.status = 'live' and p.expires_at > now())
   and (exists (select 1 from public.email_messages m where m.thread_id = t.id and m.direction = 'out'
                  and m.step = 3 and m.status = any(%(unsent)s) and m.scheduled_for <= %(due)s)
        or exists (select 1 from public.email_messages m where m.thread_id = t.id and m.direction = 'in'
                     and m.classification = any(%(wants)s)))
 order by t.lead_id, t.created_at desc
"""
_PLAN_LINKS: Final = """
select m.id::text as id, p.token
  from public.email_messages m
  join public.email_threads t on t.id = m.thread_id
  join lateral (select token from public.plan_pages p where p.lead_id = t.lead_id and p.kind = 'plan'
                  and p.status = 'live' and p.expires_at > now() order by p.created_at desc limit 1) p on true
 where m.direction = 'out' and m.step = 3 and m.status = any(%(unsent)s) and t.status <> 'done'
   and strpos(m.body, %(placeholder)s) > 0
"""
_CASE_LINKS: Final = """
select m.id::text as id, t.lead_id::text as lead_id
  from public.email_messages m
  join public.email_threads t on t.id = m.thread_id
 where m.direction = 'out' and m.step = 7 and m.status = any(%(unsent)s) and t.status <> 'done'
   and strpos(m.body, %(placeholder)s) > 0
   and exists (select 1 from public.email_messages m0 where m0.thread_id = t.id and m0.direction = 'out'
                 and m0.step = 0 and m0.status = 'sent')
"""


def due_threads(now: datetime) -> list[Row]:
    return db.fetch_all(_DUE, {"unsent": list(UNSENT), "due": now + DUE_WITHIN, "wants": list(WANTS_PLAN)})


def plan_tries(lead_ids: Sequence[str]) -> dict[str, tuple[int, datetime]]:
    """Failed plan tries per lead: (how many, the last one)."""
    if not lead_ids:
        return {}
    rows = db.fetch_all(
        "select lead_id::text as lead_id, count(*) as n, max(at) as last from public.activities "
        "where lead_id = any(%s::uuid[]) and type = 'ai_output' and payload ->> 'kind' = 'plan_failed' "
        "group by lead_id",
        [list(lead_ids)],
    )
    return {r["lead_id"]: (int(r["n"]), r["last"]) for r in rows}


def _segments(rc: RunContext) -> dict[str, Segment]:
    """Every segment, also one switched off since its threads began: a thread under way still gets its plan."""
    segments = load_segments(get_settings().segments_dir)
    return {k: v for k, v in segments.items() if not rc.opts.segments or k in rc.opts.segments}


def write_plans(rc: RunContext, router: ai.AIRouter, due: Sequence[Row], now: datetime, stats: Counter[str]) -> None:
    segments = _segments(rc)
    lead_ids = [r["lead_id"] for r in due]
    bids = list(dict.fromkeys(r["business_id"] for r in due))
    biz = evidence.businesses(bids)
    facts = evidence.verified_facts(bids)
    signals = evidence.signals_for(bids)
    profiles = startup_profiles(bids)
    offers = lead_offer_rows(lead_ids)
    tries = plan_tries(lead_ids)
    failures = 0
    for row in due:
        lead_id, bid = row["lead_id"], row["business_id"]
        n, last = tries.get(lead_id, (0, None))
        if n >= PLAN_MAX_TRIES:
            stats["plans.skipped.gave_up"] += 1
            continue
        if last is not None and now - last < timedelta(hours=PLAN_RETRY_HOURS):
            stats["plans.skipped.retry_later"] += 1
            continue
        b, seg, picks = biz.get(bid), segments.get(str(row["segment_id"])), offers.get(lead_id, {})
        if b is None or seg is None or 1 not in picks:
            stats["plans.skipped.no_offer" if b is not None and seg is not None else "plans.skipped.no_lead"] += 1
            continue
        pi = build_plan_input(
            row["thread_id"], lead_id, b, seg, picks[1], picks.get(2), facts.get(bid, []), signals.get(bid, []),
            profiles.get(bid), now,
        )  # fmt: skip
        try:
            res = ai.call(router, TASK, pi.inputs, PlanContent, run_id=rc.run_id, lead_id=lead_id)
            problems = plan_problems(res.output, pi.claim_ctx, pi.offer)
            plan, tag = res.output, res.tag
            if problems:
                stats["plans.rewrites"] += 1
                again = ai.call(
                    router, TASK, {**pi.inputs, "feedback": problems}, PlanContent, run_id=rc.run_id, lead_id=lead_id
                )
                plan, tag = again.output, again.tag
                problems = plan_problems(plan, pi.claim_ctx, pi.offer)
        except ai.AIBudgetStop:
            stats["plans.stopped.budget"] += 1
            return
        except ai.AIUnavailable as exc:
            stats["plans.ai.failed"] += 1
            record_plan_failure(lead_id, [exc.reason], None, n + 1, rc.run_id)
            failures += 1
            if failures >= AI_FAILURES_BEFORE_STOP:
                stats["plans.stopped.ai_down"] += 1
                return
            continue
        failures = 0
        if problems:
            record_plan_failure(lead_id, problems, tag, n + 1, rc.run_id)
            stats["plans.failed"] += 1
            continue
        store_plan(pi, finished_plan(plan, pi.offer, pi.country), tag, rc.run_id)
        stats["plans.written"] += 1


def fill_links(rc: RunContext, stats: Counter[str]) -> None:
    """Both placeholders, wherever their message has not gone out yet."""
    for r in db.fetch_all(_PLAN_LINKS, {"unsent": list(UNSENT), "placeholder": PLAN_LINK}):
        if fill(r["id"], PLAN_LINK, plan_url(str(r["token"])), rc.run_id):
            stats["links.plan"] += 1
    rows = db.fetch_all(_CASE_LINKS, {"unsent": list(UNSENT), "placeholder": CASE_STUDY})
    if not rows:
        return
    studies = published_case_studies()
    offers = lead_offer_rows(list({r["lead_id"] for r in rows}))
    for r in rows:
        picks = offers.get(r["lead_id"], {})
        url = case_study_url(studies, [(picks.get(1) or {}).get("offer_key"), (picks.get(2) or {}).get("offer_key")])
        if fill(r["id"], CASE_STUDY, url, rc.run_id):
            stats["links.case_study"] += 1
            if url == FALLBACK_CASE_STUDY:
                stats["links.case_study_fallback"] += 1


def run(rc: RunContext, router: ai.AIRouter | None = None, **_: Any) -> dict[str, Any]:
    """`plans` phase (outreach run): write the plans that are due, then fill the links that wait for them."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    due = due_threads(now)
    if rc.opts.limit:
        due = due[: rc.opts.limit]
    stats["plans.due"] = len(due)
    if rc.opts.dry_run:
        return _finish(rc, stats)
    if due:
        if router is None:
            try:
                router = ai.router_for(rc)
            except ai.AIUnavailable as exc:
                stats["plans.ai.unavailable"] += 1
                log.warning("plans.no_ai", reason=exc.reason)
        if router is not None:
            write_plans(rc, router, due, now, stats)
    fill_links(rc, stats)
    return _finish(rc, stats)


def _finish(rc: RunContext, stats: Counter[str]) -> dict[str, Any]:
    result = dict(sorted(stats.items()))
    rc.stats["plans"] = result
    log.info("plans.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
