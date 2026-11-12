"""Message writing (Step 12): a first WhatsApp message in the founder's casual voice, an alternate, day 3
and day 7 follow-ups, and an email when there is no mobile.

Voice (A.2.3, `whatsapp_playbook.md` voice v2): "Hi Dhruv, saw Calmveda's post on Internshala about ...",
one honest line about Nument, one idea in plain words, one short varied question; 30 to 60 words; no
links, emojis, dashes or prices. The writer sees verified facts and active signals with their ids, never
page text, phone numbers or emails.

For each lead: write, then code checks (lint, claims, daily variety) with one rewrite, then a critic that
is a different model from the writer, with one more rewrite below 9 of 10. A message that fails lint is
never stored; one that still has claim problems or scores under 9 is stored and flagged "Needs your edit"
(a `message_flagged` activity). A message a person edited is never overwritten unless they press
Regenerate afterwards (12.11).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from .. import db
from ..logging import get_logger
from ..models import SIGNAL_CATEGORY, MessageCheck, MessageDraft
from ..segments import PACKAGED_OUTCOME, Segment
from ..settings import get_settings
from . import ai, evidence, leads, score
from .evidence import Row
from .judge import evidence_text, fact_inputs, signal_inputs, trusted_numbers, trusted_words
from .lint import ClaimContext, claim_problems, closing_question, lint, opener, similarity
from .runs import RunContext
from .verify import bare_name

log = get_logger()
IST: Final = ZoneInfo("Asia/Kolkata")

MIN_CRITIC_SCORE: Final = 9
SIMILARITY_MAX: Final = 85
OPENER_MAX_SHARE: Final = 0.30
QUESTION_MAX_SHARE: Final = 0.25
SHARE_MIN_MESSAGES: Final = 4  # the share rules start once a segment has this many messages that day
SAME_DOMAIN_DAYS: Final = 7
AI_FAILURES_BEFORE_STOP: Final = 3
# Contact details and URLs never go to the writer (12.1, 12.13).
HIDDEN_FIELDS: Final = frozenset(
    {
        "phone",
        "email",
        "jsonld_phone",
        "jsonld_email",
        "contact_form_url",
        "careers_url",
        "locations_url",
        "website_status",
        "tech_stack",
        "site_speed_mobile",
    }
)
_SUFFIX: Final = re.compile(
    r"[\s,]*\b(?:pvt\.?\s*ltd\.?|private\s+limited|pte\.?\s*ltd\.?|llp|ltd\.?|limited|inc\.?|llc|l\.l\.c\.?|"
    r"fz-?llc|fze|fzco|plc)\s*$",
    re.I,
)
_DOCTOR_ROLE: Final = re.compile(
    r"\b(?:doctor|dermatologist|dentist|surgeon|physician|gyn(?:a)?ecologist|obstetrician|orthodontist|"
    r"endodontist|ophthalmologist|cardiologist|psychiatrist|pa?ediatrician|trichologist|cosmetologist|"
    r"medical director)\b",
    re.I,
)
SEEN_WHERE: Final[dict[str, str]] = {
    "apna": "your post on Apna",
    "internshala": "your post on Internshala",
    "naukri": "your job post on Naukri",
    "adzuna": "your job post",
    "careers_watch": "your careers page",
    "places": "a few of your Google reviews",
    "grounded_search": "your post",
    "inbox": "your post",
    "gdelt": "a news piece about you",
    "research": "your website",
    "manual": "your ads",
    "overture": "your new Google listing",
    "legacy": "your post",
}
COUNTRY_NOTES: Final[dict[str, str]] = {
    "in": "India. Simple English, no Hinglish. Use 'Dr.' for doctors and first names for founders. "
    "Never mention prices or rupees.",
    "ae": "UAE. Plain, polite English for owners from anywhere. Greet by first name or 'Dr. Surname', no other "
    "honorifics. Name the emirate or area only when a fact gives it. Never mention AED, prices or 'cheap', and "
    "never suggest a low-cost vendor from India; 'a small dev team' is enough.",
}
COUNTRY_NAMES: Final[dict[str, str]] = {"in": "India", "ae": "UAE"}


# ---------------------------------------------------------------------------
# 12.1 and 12.2: inputs
# ---------------------------------------------------------------------------


def short_name(name: str) -> str:
    """'Calmveda Wellness Pvt Ltd' -> 'Calmveda Wellness'."""
    out = (name or "").strip()
    while True:
        cut = _SUFFIX.sub("", out).strip(" ,.")
        if cut == out or not cut:
            return out
        out = cut


def _cap(word: str) -> str:
    return word[:1].upper() + word[1:] if word.islower() or word.isupper() else word


def greeting_for(contact: Mapping[str, Any] | None) -> tuple[str, str | None, str | None]:
    """(greeting, person name, role). 'Hi Dr. Surname,' for doctors, 'Hi Firstname,' for founders and
    owners, plain 'Hi,' when no name is confirmed by a verified fact (12.2). Never a surname alone."""
    if not contact or not contact.get("name"):
        return "Hi,", None, None
    name = str(contact["name"]).strip()
    role = str(contact.get("role") or "") or None
    parts = [p for p in re.split(r"\s+", bare_name(name)) if p.strip(".")]
    if not parts:
        return "Hi,", None, None
    doctor = bool(re.match(r"^dr\.?\s", name, re.I)) or bool(role and _DOCTOR_ROLE.search(role))
    if doctor:
        return f"Hi Dr. {_cap(parts[-1].strip('.'))},", name, role
    first = parts[0].strip(".")
    if len(first) < 2:
        return "Hi,", None, None
    return f"Hi {_cap(first)},", name, role


def greeting_contact(contacts: Sequence[Row]) -> Row | None:
    """The decision maker whose name a verified fact confirms (website or registry), number holders first."""
    people = [
        c
        for c in contacts
        if c.get("is_decision_maker")
        and c.get("name")
        and c.get("verified")
        and c.get("source") in ("website", "registry")
        and not c.get("do_not_contact")
    ]
    people.sort(key=lambda c: (not c.get("phone_e164"), not c.get("email")))
    return people[0] if people else None


def seen_where(signal: Mapping[str, Any] | None, business: Mapping[str, Any]) -> str:
    """Where we saw them, in everyday words."""
    if signal is None:
        return "your website" if business.get("website") else "your Google listing"
    return SEEN_WHERE.get(str(signal.get("source") or ""), "your post")


def signal_summary(s: Mapping[str, Any], now: datetime) -> str:
    details = s.get("details") or {}
    bits = [str(s["type"]).replace("_", " ")]
    for key in ("role", "title", "need", "branch", "location", "apply_by"):
        if details.get(key):
            bits.append(f"{key.replace('_', ' ')}: {details[key]}")
    if s.get("quote"):
        bits.append(f'"{s["quote"]}"')
    bits.append(f"{max(0, (now - s['observed_at']).days)} days ago")
    return "; ".join(bits)


def strongest(kept: Sequence[Mapping[str, Any]], mode: str) -> Mapping[str, Any] | None:
    """The signal the message opens with: the strongest one of the lead's pitch mode."""
    want = {"stated_need": "stated_need", "visible_pain": "visible_pain"}.get(mode)
    for s in kept:
        if want is None or SIGNAL_CATEGORY.get(str(s["type"])) == want:
            return s
    return kept[0] if kept else None


@dataclass
class LeadInput:
    """Everything one lead's message is built from, plus what its checks need."""

    lead: Row
    business: Row
    segment: Segment
    inputs: dict[str, Any]
    claim_ctx: ClaimContext
    greeting: str
    needs_email: bool
    basis: str


def build_input(
    lead: Row,
    b: Row,
    seg: Segment,
    facts: Sequence[Row],
    signals: Sequence[Row],
    contacts: Sequence[Row],
    cfg: score.ScoringConfig,
    now: datetime,
) -> LeadInput:
    active = [s for s in signals if evidence.is_active(s, now)]
    _, kept = score.intent_score([s for s in active if SIGNAL_CATEGORY.get(str(s["type"])) != "money"], now, cfg, seg)
    mode, angle_key = str(lead["pitch_mode"]), str(lead.get("angle") or seg.fit_only_angle())
    top = strongest(kept, mode)
    greeting, person, role = greeting_for(greeting_contact(contacts))
    angle = next((a for a in seg.angles if a.key == angle_key), None)
    shown = [f for f in facts if f["field"] not in HIDDEN_FIELDS]
    sigs = signal_inputs(active, now)
    for s, raw in zip(sigs, active, strict=True):
        s["summary"] = signal_summary(raw, now)
    channel = str(lead.get("channel") or "whatsapp")
    needs_email = channel != "whatsapp"
    details = (top or {}).get("details") or {}
    name = short_name(str(b.get("name") or ""))
    inputs = {
        "segment_id": seg.id,
        "domain": seg.domain,
        "country": seg.country,
        "country_name": COUNTRY_NAMES.get(seg.country, seg.country.upper()),
        "city": b.get("city") or "",
        "pitch_mode": mode,
        "angle": angle_key,
        "angle_label": angle.label if angle else angle_key,
        "angle_idea": angle.idea if angle else "",
        "packaged_outcome_name": PACKAGED_OUTCOME[seg.domain],
        "packaged_outcome": seg.packaged_outcome,
        "business_name": name,
        "person_name": person,
        "person_role": role,
        "greeting": greeting,
        "seen_where": seen_where(top, b),
        "need": str(details.get("need") or ""),
        "what_we_saw": signal_summary(top, now) if top else "",
        "facts": fact_inputs(shown),
        "signals": sigs,
        "associate_name": get_settings().associate_name,
        "channel": channel,
        "needs_email": needs_email,
        "country_notes": COUNTRY_NOTES.get(seg.country, ""),
        "feedback": [],
        "avoid_openers": [],
        "avoid_questions": [],
    }
    known = {
        **{str(f["id"]).lower(): str(f["id"]) for f in facts},
        **{str(s["id"]).lower(): str(s["id"]) for s in active},
    }
    ctx = ClaimContext(
        known_ids=known,
        evidence_text=evidence_text(facts, active, now),
        trusted_words=trusted_words(seg, b, [name, person or "", greeting, *SEEN_WHERE.values()]),
        trusted_numbers=trusted_numbers(seg),
    )
    basis = evidence.basis_hash([f["id"] for f in facts], [s["id"] for s in active], angle_key)
    return LeadInput(lead, b, seg, inputs, ctx, greeting, needs_email, basis)


# ---------------------------------------------------------------------------
# 12.5 to 12.7: code checks of one draft
# ---------------------------------------------------------------------------


@dataclass
class DayLog:
    """Messages already written today per segment (12.7), and recent ones per web domain (12.13)."""

    by_segment: dict[str, list[str]] = field(default_factory=dict)
    by_domain: dict[str, list[str]] = field(default_factory=dict)

    def add(self, segment_id: str, domain: str | None, message: str) -> None:
        self.by_segment.setdefault(segment_id, []).append(message)
        if domain:
            self.by_domain.setdefault(domain, []).append(message)


@dataclass
class Checked:
    """One draft with everything the code and the critic found."""

    draft: MessageDraft
    tag: str
    model: str | None
    hard: list[str]  # lint problems of the first message: never stored
    claims: list[str]  # invented numbers or names, unknown ids: stored only flagged
    variety: list[str]  # too close to today's messages: stored, flagged
    optional: list[str]  # lint problems of the alternate, follow-ups or email: those fields are stored empty
    drop: set[str]
    cited: list[str]
    score: int | None = None
    issues: list[str] = field(default_factory=list)
    critic_tag: str | None = None
    critic_model: str | None = None

    @property
    def problems(self) -> list[str]:
        return self.hard + self.claims + self.variety + self.optional

    @property
    def rank(self) -> tuple[bool, bool, int, int, int]:
        """Best first: passes lint, no claim problems, highest critic score, fewest other problems."""
        return (
            not self.hard,
            not self.claims,
            self.score if self.score is not None else -1,
            -len(self.variety),
            -len(self.drop),
        )


def variety_problems(message: str, segment_id: str, domain: str | None, day: DayLog) -> list[str]:
    today = day.by_segment.get(segment_id, [])
    recent = today + day.by_domain.get(domain or "", [])
    problems: list[str] = []
    if any(similarity(message, m) > SIMILARITY_MAX for m in recent):
        problems.append("too similar to another message today: use a different opener and a different question")
    n = len(today) + 1
    if n >= SHARE_MIN_MESSAGES:
        mine = opener(message)
        if mine and (sum(opener(m) == mine for m in today) + 1) / n > OPENER_MAX_SHARE:
            problems.append(f"the opener '{mine}' is overused today: start differently")
        q = closing_question(message)
        if q and (sum(closing_question(m) == q for m in today) + 1) / n > QUESTION_MAX_SHARE:
            problems.append(f"the question '{q}' is overused today: ask something else")
    return problems


def check_draft(draft: MessageDraft, li: LeadInput, day: DayLog, tag: str = "", model: str | None = None) -> Checked:
    """Lint every field, check the claims of the two first messages, and the day's variety."""
    hard = lint(draft.message, "message")
    if not draft.message.startswith(li.greeting):
        hard.append(f"must start with the greeting '{li.greeting}'")
    optional: list[str] = []
    drop: set[str] = set()
    fields = {"message_alt": draft.message_alt, "followup_d3": draft.followup_d3, "followup_d7": draft.followup_d7}
    if li.needs_email:
        fields |= {"email_subject": draft.email_subject or "", "email_body": draft.email_body or ""}
    for kind, text in fields.items():
        problems = lint(text, kind)
        if kind == "message_alt" and text and not text.startswith(li.greeting):
            problems.append(f"must start with the greeting '{li.greeting}'")
        if problems:
            drop.add(kind)
            optional += [f"{kind}: {p}" for p in problems]
    texts = [draft.message] + ([draft.message_alt] if "message_alt" not in drop else [])
    claims = claim_problems(texts, [c.ids for c in draft.claims], li.claim_ctx)
    variety = variety_problems(draft.message, li.segment.id, li.business.get("web_domain"), day)
    cited = [i for c in draft.claims for i in c.ids]
    return Checked(draft, tag, model, hard, claims, variety, optional, drop, cited)


# ---------------------------------------------------------------------------
# Writing one lead
# ---------------------------------------------------------------------------


class Writer:
    """Runs the write, check and critic loop for one lead (12.4 to 12.9)."""

    def __init__(self, router: ai.AIRouter, run_id: str, day: DayLog) -> None:
        self.router, self.run_id, self.day = router, run_id, day

    def _write(self, li: LeadInput, feedback: list[str]) -> ai.AIResult[MessageDraft]:
        inputs = {
            **li.inputs,
            "feedback": feedback,
            "avoid_openers": sorted({opener(m) for m in self.day.by_segment.get(li.segment.id, [])} - {""})[-10:],
            "avoid_questions": sorted({closing_question(m) for m in self.day.by_segment.get(li.segment.id, [])} - {""})[
                -10:
            ],
        }
        return ai.call(self.router, "write_message", inputs, MessageDraft, run_id=self.run_id, lead_id=li.lead["id"])

    def _critic(self, li: LeadInput, c: Checked) -> None:
        res = ai.call(
            self.router,
            "check_message",
            {
                "message": c.draft.message,
                "message_alt": c.draft.message_alt,
                "greeting": li.greeting,
                "business_name": li.inputs["business_name"],
                "segment_id": li.segment.id,
                "country": li.segment.country,
                "pitch_mode": li.inputs["pitch_mode"],
                "angle": li.inputs["angle"],
                "facts": li.inputs["facts"],
                "signals": li.inputs["signals"],
                "writer_model": c.model or "",
            },
            MessageCheck,
            run_id=self.run_id,
            lead_id=li.lead["id"],
            exclude_model=c.model,
        )
        c.score, c.issues = res.output.score, list(res.output.issues)
        if res.output.suggested_fix and res.output.score < MIN_CRITIC_SCORE:
            c.issues.append(f"a reviewer suggested: {res.output.suggested_fix}")
        c.critic_tag, c.critic_model = res.tag, res.model

    def write(self, li: LeadInput) -> list[Checked]:
        """Up to three drafts and two critic calls: one rewrite for code problems, one for a score under 9."""
        drafts: list[Checked] = []
        feedback: list[str] = []
        code_rewrite = critic_rewrite = False
        while True:
            res = self._write(li, feedback)
            c = check_draft(res.output, li, self.day, res.tag, res.model)
            drafts.append(c)
            if c.problems and not code_rewrite:
                code_rewrite = True
                feedback = c.problems
                continue
            if c.hard or c.claims:
                return drafts  # second failure: keep the best version and flag it (12.6)
            self._critic(li, c)
            if (c.score or 0) >= MIN_CRITIC_SCORE or critic_rewrite:
                return drafts
            critic_rewrite = True
            feedback = c.issues or ["make it more specific to them and easier to answer in five seconds"]


def pick(drafts: Sequence[Checked]) -> Checked:
    return max(drafts, key=lambda c: c.rank)


# ---------------------------------------------------------------------------
# Selection, storage and the stage
# ---------------------------------------------------------------------------

_SELECT: Final = """
select l.id, l.business_id, l.segment_id, l.grade, l.pitch_mode, l.angle, l.test_group, l.channel, l.message,
       l.regen_requested_at, l.created_at, s.total
  from public.leads l
  left join public.scores s on s.id = l.score_id
 where l.stage = 'new' and l.grade in ('A', 'B') and l.segment_id = any(%(segments)s)
   and (l.message is null or l.regen_requested_at is not null)
 order by l.grade, s.total desc nulls last, l.created_at
 limit %(limit)s
"""


def wants_message(lead: Mapping[str, Any], hist: leads.MessageHistory) -> bool:
    """Empty and never edited by a person, or a Regenerate press newer than any edit (12.11)."""
    regen = lead.get("regen_requested_at")
    if regen is not None and (hist.edited_at is None or regen > hist.edited_at):
        return True
    return lead.get("message") is None and not hist.edited


def load_day(segment_ids: Sequence[str], now: datetime) -> DayLog:
    """Messages stored today per segment, and in the last 7 days per web domain."""
    start = datetime.combine(now.astimezone(IST).date(), time(0, 0), tzinfo=IST)
    day = DayLog()
    rows = db.fetch_all(
        """
        select l.segment_id, b.web_domain, l.message, max(a.at) as at
          from public.activities a
          join public.leads l on l.id = a.lead_id
          join public.businesses b on b.id = l.business_id
         where a.type = 'ai_output' and a.payload ->> 'kind' = 'message_stored' and a.at >= %s
           and l.message is not null and l.segment_id = any(%s)
         group by 1, 2, 3
        """,
        [now - timedelta(days=SAME_DOMAIN_DAYS), list(segment_ids)],
    )
    for r in rows:
        if r["at"] >= start:
            day.by_segment.setdefault(r["segment_id"], []).append(r["message"])
        if r["web_domain"]:
            day.by_domain.setdefault(r["web_domain"], []).append(r["message"])
    return day


def store(li: LeadInput, best: Checked, flags: list[str], run_id: str) -> bool:
    """Write the result unless a person changed the message meanwhile. Returns True when stored."""
    d = best.draft
    keep = {
        "message_alt": None if "message_alt" in best.drop else d.message_alt,
        "followup_d3": None if "followup_d3" in best.drop else d.followup_d3,
        "followup_d7": None if "followup_d7" in best.drop else d.followup_d7,
        "email_subject": (d.email_subject if li.needs_email and "email_subject" not in best.drop else None),
        "email_body": (d.email_body if li.needs_email and "email_body" not in best.drop else None),
    }
    with db.tx("engine", {"run_id": run_id, "stage": "message"}) as conn:
        cur = conn.execute(
            """
            update public.leads set message = %(message)s, message_alt = %(message_alt)s,
                   followup_d3 = %(followup_d3)s, followup_d7 = %(followup_d7)s,
                   email_subject = %(email_subject)s, email_body = %(email_body)s,
                   message_model = %(model)s, message_check_score = %(score)s, regen_requested_at = null
             where id = %(id)s and stage = 'new' and message is not distinct from %(old)s
            """,
            {
                **keep,
                "message": d.message,
                "model": best.tag,
                "score": best.score,
                "id": li.lead["id"],
                "old": li.lead.get("message"),
            },
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'ai_output', %s)",
            [
                li.lead["id"],
                db.Jsonb(
                    {
                        "kind": "message_stored",
                        "task": "write_message",
                        "model": best.tag,
                        "critic_model": best.critic_tag,
                        "check_score": best.score,
                        "cited_ids": sorted(set(best.cited)),
                        "basis": li.basis,
                    }
                ),
            ],
        )
        if flags:
            conn.execute(
                "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', "
                "'message_flagged', %s)",
                [
                    li.lead["id"],
                    db.Jsonb(
                        {"issues": flags[:10], "score": best.score, "model": best.tag, "critic_model": best.critic_tag}
                    ),
                ],
            )
    return True


def flag_unwritable(lead_id: str, problems: list[str], tag: str | None, run_id: str) -> None:
    """No draft passed lint: nothing is stored, the founder sees why on the lead."""
    with db.tx("engine", {"run_id": run_id, "stage": "message"}) as conn:
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', "
            "'message_flagged', %s)",
            [lead_id, db.Jsonb({"issues": problems[:10], "stored": False, "model": tag})],
        )


def flags_for(best: Checked) -> list[str]:
    flags = best.claims + best.variety + best.optional
    if best.score is None:
        flags.append("not checked by the reviewer")
    elif best.score < MIN_CRITIC_SCORE:
        flags.append(f"reviewer score {best.score} of 10")
        flags += best.issues
    if best.critic_model and best.model and best.critic_model == best.model:
        flags.append("checked by the same model that wrote it")
    return list(dict.fromkeys(flags))


def run(rc: RunContext, router: ai.AIRouter | None = None) -> dict[str, Any]:
    """`nlead message`: write, check and store messages for new A and B leads."""
    now = datetime.now(UTC)
    segments = score.enabled_segments(rc)
    configs = score.segment_configs(segments)
    stats: Counter[str] = Counter()
    rows = db.fetch_all(_SELECT, {"segments": list(segments), "limit": None})
    for r in rows:
        r["id"], r["business_id"] = str(r["id"]), str(r["business_id"])
    history = leads.message_history([r["id"] for r in rows]) if rows else {}
    todo = [r for r in rows if wants_message(r, history.get(r["id"], leads.MessageHistory()))]
    stats["skipped.edited_by_person"] = len(rows) - len(todo)
    if rc.opts.limit:
        todo = todo[: rc.opts.limit]
    stats["selected"] = len(todo)
    if rc.opts.dry_run or not todo:
        rc.stats["message"] = dict(stats)
        return dict(stats)
    if router is None:
        try:
            router = ai.router_for(rc)
        except ai.AIUnavailable as exc:
            stats["ai.unavailable"] += 1
            log.warning("message.no_ai", reason=exc.reason)
            rc.stats["message"] = dict(stats)
            return dict(stats)
    ids = [r["business_id"] for r in todo]
    biz = evidence.businesses(ids)
    facts = evidence.verified_facts(ids)
    signals = evidence.signals_for(ids)
    contacts = evidence.contacts_for(ids)
    day = load_day(list(segments), now)
    writer = Writer(router, rc.run_id, day)
    failures = 0
    for lead in todo:
        b, seg = biz.get(lead["business_id"]), segments.get(str(lead["segment_id"]))
        if b is None or seg is None:
            continue
        li = build_input(
            lead,
            b,
            seg,
            facts.get(lead["business_id"], []),
            signals.get(lead["business_id"], []),
            contacts.get(lead["business_id"], []),
            configs[seg.id],
            now,
        )
        try:
            drafts = writer.write(li)
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
        stats["drafts"] += len(drafts)
        best = pick(drafts)
        if best.hard:
            flag_unwritable(lead["id"], best.problems, best.tag, rc.run_id)
            stats["flagged.not_stored"] += 1
            continue
        flags = flags_for(best)
        if store(li, best, flags, rc.run_id):
            day.add(seg.id, b.get("web_domain"), best.draft.message)
            stats["stored"] += 1
            if flags:
                stats["flagged.needs_edit"] += 1
            if best.score is not None:
                stats[f"score.{best.score}"] += 1
        else:
            stats["skipped.changed_meanwhile"] += 1
    result = dict(sorted(stats.items()))
    rc.stats["message"] = result
    log.info("message.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
