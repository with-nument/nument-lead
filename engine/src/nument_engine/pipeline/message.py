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

Startup segments that go out by email (15 Nov 2026, contract 4.6) take their own path in the second half of
this module: the 12-day sequence from `write_email_sequence`, the same write, check and critic loop with stricter
rules (claims are never stored unchecked), and an open thread with four draft messages for the sender.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from .. import db
from ..logging import get_logger
from ..models import SIGNAL_CATEGORY, EmailSequence, MessageCheck, MessageDraft
from ..segments import PACKAGED_OUTCOME, Segment, country_name, load_yaml_config
from ..settings import get_settings
from . import ai, evidence, leads, score
from .evidence import Row
from .judge import evidence_text, fact_inputs, signal_inputs, trusted_numbers, trusted_words
from .lint import (
    BANNED,
    DASH,
    EMOJI,
    LINK,
    PRICE,
    ClaimContext,
    claim_problems,
    closing_question,
    lint,
    opener,
    similarity,
    word_count,
)
from .phones import email_domain, is_freemail, valid_email
from .runs import RunContext
from .verify import DM_ROLE, Suppression, bare_name

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
    "us": "United States. Plain, direct, friendly English; first names for everyone. Never mention prices, India "
    "or offshore; 'a small senior dev team' is enough. Email: short subject, no hype.",
    "gb": "United Kingdom. Plain, polite, understated English with British spelling; first names. Never mention "
    "prices, India or offshore; 'a small senior dev team' is enough.",
    "au": "Australia. Plain, relaxed, direct English with British spelling; first names. Never mention prices, "
    "India or offshore.",
    "ca": "Canada. Plain, polite English; first names. Never mention prices, India or offshore.",
    "sg": "Singapore. Plain, polite, efficient English; first names unless a title is given. Never mention "
    "prices, India or offshore.",
}


# ---------------------------------------------------------------------------
# 12.1 and 12.2: inputs
# ---------------------------------------------------------------------------


def single_city(b: Mapping[str, Any]) -> str:
    """The business's city, or "" when its places span several cities (a chain): naming one city would be
    wrong for most of its branches."""
    counts = (b.get("extra") or {}).get("city_counts") or {}
    if len(counts) > 1:
        return ""
    return str(b.get("city") or "")


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
        and (
            c.get("source") in ("website", "registry")
            or (c.get("source") == "other" and c.get("quote"))  # a founder found by a backed search (5.11.4)
        )
        and not c.get("do_not_contact")
    ]
    people.sort(key=lambda c: (not c.get("phone_e164"), not c.get("email")))
    return people[0] if people else None


def owner_name(contacts: Sequence[Row]) -> str | None:
    """The owner's name for a message the front desk passes on: a decision maker named on their own site, even
    when the number next to the name turned out to be the business line ("Dr. Rao" or "Asha Rao")."""
    for c in contacts:
        name = str(c.get("name") or "").strip()
        if not name or c.get("do_not_contact") or not c.get("verified"):
            continue
        if c.get("is_decision_maker") or DM_ROLE.search(str(c.get("role") or "")):
            _, person, _ = greeting_for({"name": name, "role": c.get("role")})
            if person:
                doctor = bool(re.match(r"^dr\.?\s", name, re.I)) or bool(_DOCTOR_ROLE.search(str(c.get("role") or "")))
                parts = [p for p in re.split(r"\s+", bare_name(name)) if p.strip(".")]
                return f"Dr. {_cap(parts[-1].strip('.'))}" if doctor and parts else name
    return None


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
    # Who reads it (15 Nov 2026): a front desk or a bot line gets a short message to pass on to the owner.
    reach = score.reach_of(contacts, facts, cfg, now, email_first=seg.outreach_channel == "email")
    line = score.line_of(reach.contact) if reach.contact is not None else "other"
    recipient = "owner" if line == "owner" else "front_desk" if line in ("front_desk", "bot") else "business"
    owner = person or owner_name(contacts)
    if recipient == "front_desk":
        greeting, person, role = "Hi,", None, None
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
        "country_name": country_name(seg.country).removeprefix("the "),
        "city": single_city(b),
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
        "recipient": recipient,
        "owner_name": owner,
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
        trusted_words=trusted_words(seg, b, [name, person or "", owner or "", greeting, *SEEN_WHERE.values()]),
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


FOOTER_SETTING: Final = "outreach.postal_address"
OPT_OUT_LINE: Final = 'Not relevant? Just reply "no" and we won\'t write again.'


def email_footer(address: str | None) -> str:
    """The sign-off every email to an email-first country carries (plan 18.4: who we are, a postal address, an
    easy opt-out; CAN-SPAM, UK PECR, Canada CASL, Australia Spam Act). Nument, never a person (memory rule)."""
    lines = ["Team Nument", *([address.strip()] if address and address.strip() else []), OPT_OUT_LINE]
    return "\n\n--\n" + "\n".join(lines)


def with_footer(body: str | None, seg: Segment) -> str | None:
    if not body or seg.outreach_channel != "email" or OPT_OUT_LINE in body:
        return body
    address = db.get_setting(FOOTER_SETTING)
    return body.rstrip() + email_footer(str(address) if isinstance(address, str) else None)


def store(li: LeadInput, best: Checked, flags: list[str], run_id: str) -> bool:
    """Write the result unless a person changed the message meanwhile. Returns True when stored."""
    d = best.draft
    keep = {
        "message_alt": None if "message_alt" in best.drop else d.message_alt,
        "followup_d3": None if "followup_d3" in best.drop else d.followup_d3,
        "followup_d7": None if "followup_d7" in best.drop else d.followup_d7,
        "email_subject": (d.email_subject if li.needs_email and "email_subject" not in best.drop else None),
        "email_body": with_footer(d.email_body, li.segment)
        if li.needs_email and "email_body" not in best.drop
        else None,
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


def flags_for(best: Checked | SeqChecked) -> list[str]:
    flags = best.claims + best.variety + best.optional
    if best.score is None:
        flags.append("not checked by the reviewer")
    elif best.score < MIN_CRITIC_SCORE:
        flags.append(f"reviewer score {best.score} of 10")
        flags += best.issues
    if best.critic_model and best.model and best.critic_model == best.model:
        flags.append("checked by the same model that wrote it")
    return list(dict.fromkeys(flags))


# ---------------------------------------------------------------------------
# The startup email path (15 Nov 2026, contract 4.6): a 12-day sequence, its thread and four drafts
# ---------------------------------------------------------------------------
#
# Startup segments (domain `firms`) that go out by email get a sequence instead of a WhatsApp message:
# `write_email_sequence` writes the subject and the emails of days 0, 3, 7 and 12; code checks every part (the
# voice rules, every claim, no link on day 0, `{plan_link}` on day 3, `{case_study}` on day 7); a critic that is
# not the writer's model scores the sequence, with one rewrite under 9; the result becomes an open thread in
# review mode with four draft messages. Nothing is written for a lead that could not get a thread: no verified
# or likely address, a country we do not email, a suppressed address or domain, an open thread, or a domain in
# its 90-day cooldown. The sender adds the footer; plans.py fills the two placeholders after day 0 went out.

SEQUENCE_TASK: Final = "write_email_sequence"
PLAN_LINK: Final = "{plan_link}"
CASE_STUDY: Final = "{case_study}"
SENDABLE_EMAIL_STATUS: Final = ("verified", "likely")
# Outgoing steps that may still be rewritten when a person presses Regenerate: nothing approved, queued or sent.
REWRITABLE: Final = frozenset({"draft", "review", "cancelled"})
# Words per part; the founder's rule is under about 120 words a step (15 Nov 2026).
SEQUENCE_WORDS: Final[dict[str, tuple[int, int]]] = {
    "subject": (2, 7),
    "day0": (40, 120),
    "day0_alt": (40, 120),
    "day3": (20, 110),
    "day7": (20, 110),
    "day12": (8, 60),
}
SEQUENCE_PARTS: Final = ("day0", "day3", "day7", "day12")
STEP_OF: Final[dict[str, int]] = {"day0": 0, "day3": 3, "day7": 7, "day12": 12}
PLACEHOLDER_OF: Final[dict[str, str]] = {"day3": PLAN_LINK, "day7": CASE_STUDY}
# Hype, filler and spam words a founder would never type to another founder.
EMAIL_BANNED: Final = (
    "circle back",
    "touch base",
    "just checking in",
    "following up on my",
    "per my last",
    "supercharge",
    "skyrocket",
    "unlock",
    "seamless",
    "next-gen",
    "best-in-class",
    "10x",
    "rockstar",
    "ninja",
    "disrupt",
    "innovative solution",
    "solutions provider",
    "i hope this email",
    "free consultation",
    "limited time",
    "act now",
)
# Probe facts a stranger should not quote back (DNS, certificates, archive dates, GitHub, app links): they help
# pick the offer, but an email or a plan that mentions them reads as surveillance.
PRIVATE_FIELDS: Final = frozenset(
    {"probe.dns", "probe.first_cert", "probe.first_capture", "probe.domain_created", "probe.github", "probe.app_links"}
)
# Where we saw a startup, in words a founder would use; a filing is never named as the source.
STARTUP_SEEN_WHERE: Final[dict[str, str]] = {
    "funding_rss": "the news about your round",
    "gdelt": "a news piece about you",
    "hn_launches": "your Show HN post",
    "betalist": "your BetaList page",
    "ats_jobs": "your job post",
    "job_feeds": "your job post",
    "jobs": "your job post",
    "careers_watch": "your careers page",
    "grounded_search": "your post",
    "startup_lists": "your startup profile",
    "research": "your website",
}
STARTUP_DETAIL_KEYS: Final = ("round", "amount_usd", "investors", "title", "role", "need", "batch", "team_size")
EMAIL_COUNTRY_NOTES: Final[dict[str, str]] = {
    "in": "India. Plain, warm English, no Hinglish; first names. Never mention prices or rupees.",
    "gb": "United Kingdom. Plain, understated English with British spelling; first names.",
    "ie": "Ireland. Plain, friendly English with British spelling; first names.",
    "au": "Australia. Plain, relaxed English with British spelling; first names.",
    "nz": "New Zealand. Plain, relaxed English with British spelling; first names.",
    "sg": "Singapore. Plain, polite, efficient English; first names unless a title is given.",
}
_PLACEHOLDER: Final = re.compile(r"\{[^{}\s]{1,40}\}")
_SLOT: Final = re.compile(r"\[[^\[\]\n]{1,40}\]|<[^<>\n]{1,40}>")
_LIST_LINE: Final = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)
_SIGN_OFF: Final = re.compile(
    r"^(?:best|best regards|regards|kind regards|warm regards|cheers|thanks|thank you|many thanks|best wishes|"
    r"sincerely|yours|talk soon)\b[\w ,.!]{0,30}$",
    re.I,
)
# "a 1-page plan", "a 20-minute call": our own offer, not a claim about them.
_OUR_NUMBERS: Final = re.compile(
    r"\b(?:\d+|one|two|three|five|ten|fifteen|twenty|thirty)[\s-]*(page|minute|min)s?\b", re.I
)
_NUMBER: Final = re.compile(r"\d+")


def is_startup_email(seg: Segment) -> bool:
    """A startup segment that goes out by email: it gets the sequence, everything else the WhatsApp path."""
    return seg.domain == "firms" and seg.outreach_channel == "email"


def writer_facts(facts: Sequence[Row]) -> list[Row]:
    """Facts the email and plan writers may see: no contact details, no probes a stranger should not quote."""
    return [f for f in facts if f["field"] not in HIDDEN_FIELDS and f["field"] not in PRIVATE_FIELDS]


def startup_signal_summary(s: Mapping[str, Any], now: datetime) -> str:
    """'funding; round: pre seed; amount usd: $600,000; "raised $600K"; 5 days ago'."""
    details = s.get("details") or {}
    bits = [str(s["type"]).replace("_", " ")]
    for key in STARTUP_DETAIL_KEYS:
        value = details.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "amount_usd" and isinstance(value, int | float):
            value = f"${value:,.0f}"
        elif key == "investors" and isinstance(value, list):
            value = ", ".join(str(v) for v in value[:3])
        elif key == "round":
            value = str(value).replace("_", " ")
        bits.append(f"{key.replace('_', ' ')}: {value}")
    if s.get("quote"):
        bits.append(f'"{s["quote"]}"')
    bits.append(f"{max(0, (now - s['observed_at']).days)} days ago")
    return "; ".join(bits)


def startup_signals(active: Sequence[Mapping[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Signal inputs for the startup tasks, each with a plain summary."""
    out = signal_inputs(active, now)
    for item, raw in zip(out, active, strict=True):
        item["summary"] = startup_signal_summary(raw, now)
    return out


def profile_lines(profile: Mapping[str, Any] | None, *, amounts: bool = False) -> list[str]:
    """The startup profile as short lines with their evidence ids; unknown answers are left out."""
    if not profile:
        return []

    def ev(key: str) -> str:
        ids = [str(i) for i in profile.get(key) or []][:4]
        return f" (evidence {', '.join(ids)})" if ids else ""

    out: list[str] = []
    if profile.get("team_size") is not None:
        out.append(f"team size: {profile['team_size']}{ev('team_size_evidence')}")
    if profile.get("tech_team") not in (None, "unknown"):
        out.append(f"tech team: {str(profile['tech_team']).replace('_', ' ')}{ev('tech_team_evidence')}")
    if profile.get("can_pay") not in (None, "unknown"):
        out.append(f"can pay: {profile['can_pay']}{ev('can_pay_evidence')}")
    if profile.get("product_status") not in (None, "unknown"):
        out.append(f"product status: {str(profile['product_status']).replace('_', ' ')}")
    if profile.get("no_code_platform"):
        out.append(f"built on: {profile['no_code_platform']}")
    if profile.get("uses_ai") is not None:
        out.append(f"uses AI: {'yes' if profile['uses_ai'] else 'no'}")
    if profile.get("funding_round"):
        money = f", about ${float(profile['funding_usd']):,.0f}" if amounts and profile.get("funding_usd") else ""
        when = f", {profile['funding_at']}" if profile.get("funding_at") else ""
        out.append(f"funding: {str(profile['funding_round']).replace('_', ' ')}{money}{when}")
    return out


def startup_profiles(business_ids: Sequence[str]) -> dict[str, Row]:
    """The qualification of each startup (startup_profiles, written by the qualify stage), when there is one."""
    if not business_ids:
        return {}
    rows = db.fetch_all(
        "select * from public.startup_profiles where business_id = any(%s::uuid[])", [list(business_ids)]
    )
    return {str(r["business_id"]): r for r in rows}


def offer_numbers(*offers: Mapping[str, Any] | None) -> set[str]:
    """Numbers in our own offer copy ('4 to 6 weeks'): an email may repeat them without a citation."""
    return {n for o in offers if o for k in ("timeline", "promise") for n in _NUMBER.findall(str(o.get(k) or ""))}


def claim_text(text: str) -> str:
    """The text the claim check reads: '1-page plan' and '20-minute call' are our offer, not claims about them,
    and a placeholder ends a sentence (the word after a link starts a new one)."""
    plain = _PLACEHOLDER.sub(". ", text or "")
    return _OUR_NUMBERS.sub(lambda m: m.group(1).lower(), plain)


# ---- who the sequence goes to, and whether a thread may be opened (contract 4.6) -------------------------


@dataclass(frozen=True)
class OutreachRules:
    """config/outreach.yaml: where cold email is allowed, and the per-domain cooldown."""

    allowed: frozenset[str]
    blocked: frozenset[str]
    published_only: frozenset[str]
    cooldown_days: int

    @classmethod
    def load(cls) -> OutreachRules:
        cfg = load_yaml_config("outreach", get_settings().config_dir)

        def codes(key: str) -> frozenset[str]:
            return frozenset(str(c).strip().lower() for c in cfg.get(key) or [])

        return cls(
            codes("allowed_countries"),
            codes("blocked_countries"),
            codes("published_only_countries"),
            int(cfg.get("domain_cooldown_days", 90)),
        )

    def country_block(self, country: str, origin: str | None) -> str | None:
        """Why a cold email to this country is not allowed, or None."""
        cc = (country or "").strip().lower()
        if cc in self.blocked:
            return "country_blocked"
        if cc not in self.allowed:
            return "country_not_allowed"
        if origin == "guess" and cc in self.published_only:
            return "guess_in_published_only_country"
        return None


def sendable_contact(contacts: Sequence[Row], suppressed: Suppression) -> Row | None:
    """The address a sequence goes to: a founder's (owner line) before anyone else's, verified before likely.
    Never a bot line, a do-not-contact person, an invalid, unknown or suppressed address."""
    ok = [
        c
        for c in contacts
        if c.get("email")
        and valid_email(str(c["email"]))
        and c.get("email_status") in SENDABLE_EMAIL_STATUS
        and not c.get("do_not_contact")
        and score.line_of(c) != "bot"
        and str(c["email"]).lower() not in suppressed.emails
    ]
    ok.sort(
        key=lambda c: (
            score.line_of(c) != "owner",
            c.get("email_status") != "verified",
            not c.get("is_decision_maker"),
            not c.get("name"),
            str(c.get("created_at") or ""),
        )
    )
    return ok[0] if ok else None


def thread_domains(email: str, business: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """(to_domain, every domain the cooldown covers). A free-mail address counts as the company's web domain,
    so one founder on gmail.com never blocks every other founder on gmail.com."""
    web = str(business.get("web_domain") or "").strip().lower().removeprefix("www.")
    mail = "" if is_freemail(email) else email_domain(email)
    keys = list(dict.fromkeys(d for d in (mail, web) if d))
    return (mail or web or None), keys


@dataclass(frozen=True)
class DomainThread:
    """A thread to a domain, as the cooldown sees it."""

    id: str
    lead_id: str
    status: str
    created_at: datetime
    last_sent_at: datetime | None
    sending: bool


_DOMAIN_THREADS: Final = """
select t.id::text as id, t.lead_id::text as lead_id, t.to_domain, t.status, t.created_at,
       max(m.sent_at) filter (where m.direction = 'out' and m.status = 'sent') as last_sent_at,
       coalesce(bool_or(m.direction = 'out' and m.status = 'sending'), false) as sending
  from public.email_threads t
  left join public.email_messages m on m.thread_id = t.id
 where t.to_domain = any(%s)
 group by t.id
"""


def domain_threads(domains: Sequence[str], *, conn: Any = None) -> dict[str, list[DomainThread]]:
    """Every thread to these domains, with when it last sent something."""
    out: dict[str, list[DomainThread]] = {d: [] for d in domains}
    if not domains:
        return out
    for r in db.fetch_all(_DOMAIN_THREADS, [list(domains)], conn=conn):
        out.setdefault(r["to_domain"], []).append(
            DomainThread(r["id"], r["lead_id"], r["status"], r["created_at"], r["last_sent_at"], bool(r["sending"]))
        )
    return out


def cooldown_block(
    threads: Sequence[DomainThread], lead_id: str, now: datetime, days: int, own_thread_id: str | None = None
) -> str | None:
    """One open thread per lead and per domain, and no contact with a domain within `days` (90): an email sent
    there, or another lead's thread opened there. A thread of this same lead that never sent anything does not
    count, so Regenerate after a cancelled draft still works."""
    since = now - timedelta(days=days)
    for t in threads:
        if t.id == own_thread_id:
            continue
        if t.status == "open":
            return "open_thread" if t.lead_id == lead_id else "domain_open_thread"
        if t.sending or (t.last_sent_at is not None and t.last_sent_at > since):
            return "domain_cooldown"
        if t.lead_id != lead_id and t.created_at > since:
            return "domain_cooldown"
    return None


# ---- what one lead's sequence is built from ---------------------------------------------------------------


@dataclass
class SequenceInput:
    """Everything one startup lead's sequence is built from, where it goes, and what its checks need."""

    lead: Row
    business: Row
    segment: Segment
    contact: Row
    to_email: str
    to_domain: str
    domains: list[str]
    offer_key: str
    inputs: dict[str, Any]
    claim_ctx: ClaimContext
    greeting: str
    basis: str
    thread_id: str | None = None  # an open thread whose drafts are rewritten in place (Regenerate)


def build_sequence_input(
    lead: Row,
    b: Row,
    seg: Segment,
    contact: Row,
    offer: Row,
    backup: Row | None,
    facts: Sequence[Row],
    signals: Sequence[Row],
    profile: Row | None,
    now: datetime,
) -> SequenceInput:
    """The writer's inputs (verified facts and active signals with their ids, never an address or a phone) and
    the claim context every part is checked against."""
    active = [s for s in signals if evidence.is_active(s, now)]
    greeting, person, role = greeting_for(contact if contact.get("name") else None)
    name = short_name(str(b.get("name") or ""))
    top = max(active, key=lambda s: (float(s.get("points") or 0), s["observed_at"]), default=None)
    seen = STARTUP_SEEN_WHERE.get(str(top.get("source") or ""), "") if top is not None else ""
    country = str(b.get("country") or seg.country).lower()
    place = country_name(country).removeprefix("the ")
    to_domain, domains = thread_domains(str(contact["email"]), b)
    inputs: dict[str, Any] = {
        "founder_name": person,
        "founder_role": role,
        "greeting": greeting,
        "company": name,
        "country": country,
        "country_name": place,
        "country_notes": EMAIL_COUNTRY_NOTES.get(country, ""),
        "offer": str(offer["name"]),
        "offer_promise": str(offer.get("promise") or ""),
        "offer_timeline": str(offer.get("timeline") or ""),
        "offer_best_for": str(offer.get("best_for") or ""),
        "why_now": str(offer.get("why_now") or ""),
        "seen_where": seen,
        "profile": profile_lines(profile),
        "facts": fact_inputs(writer_facts(facts)),
        "signals": startup_signals(active, now),
        "feedback": [],
        "avoid_openers": [],
        "avoid_questions": [],
    }
    known = {
        **{str(f["id"]).lower(): str(f["id"]) for f in facts},
        **{str(s["id"]).lower(): str(s["id"]) for s in active},
    }
    offer_copy = [f"{o.get('name')} {o.get('promise')} {o.get('best_for')}" for o in (offer, backup) if o]
    ctx = ClaimContext(
        known_ids=known,
        evidence_text=evidence_text(facts, active, now),
        trusted_words=trusted_words(seg, b, [name, person or "", greeting, seen, place, *offer_copy, "MVP MVPs"]),
        trusted_numbers=trusted_numbers(seg) | offer_numbers(offer, backup),
    )
    basis = evidence.basis_hash([f["id"] for f in facts], [s["id"] for s in active], offer["offer_key"])
    return SequenceInput(
        lead=lead,
        business=b,
        segment=seg,
        contact=contact,
        to_email=str(contact["email"]).strip(),
        to_domain=to_domain or "",
        domains=domains,
        offer_key=str(offer["offer_key"]),
        inputs=inputs,
        claim_ctx=ctx,
        greeting=greeting,
        basis=basis,
    )


# ---- code checks of one sequence -------------------------------------------------------------------------


def lint_part(text: str, part: str, greeting: str = "") -> list[str]:
    """Voice and safety problems in one part of a sequence ('subject', 'day0', 'day0_alt', 'day3', 'day7',
    'day12'); an empty list means it passes."""
    text = (text or "").strip()
    lo, hi = SEQUENCE_WORDS[part]
    problems: list[str] = []
    words = word_count(text)
    if not lo <= words <= hi:
        problems.append(f"{words} words (want {lo} to {hi})")
    want = PLACEHOLDER_OF.get(part)
    found = _PLACEHOLDER.findall(text)
    if want is not None and found.count(want) != 1:
        problems.append(f"must contain {want} exactly once")
    extra = sorted({p for p in found if p != want})
    if extra:
        problems.append(f"placeholder {', '.join(extra)} does not belong here")
    plain = _PLACEHOLDER.sub(" ", text)
    if LINK.search(plain):
        problems.append("contains a link" if want is None else f"contains a link other than {want}")
    if _SLOT.search(plain):
        problems.append("contains an unfilled template slot such as [Name]")
    if DASH.search(plain):
        problems.append("contains a dash")
    if EMOJI.search(plain):
        problems.append("contains an emoji")
    if PRICE.search(plain):
        problems.append("mentions money or a price")
    if plain.count("!") > 1:
        problems.append("more than one exclamation mark")
    low = plain.lower()
    problems += [f"banned phrase '{b}'" for b in (*BANNED, *EMAIL_BANNED) if b in low]
    if part == "subject":
        if "?" in text:
            problems.append("subject asks a question")
        if re.match(r"^\s*(?:re|fwd?)\s*:", text, re.I):
            problems.append("subject pretends to be a reply")
        if "\n" in text:
            problems.append("subject has a line break")
        return problems
    if greeting and not text.startswith(greeting):
        problems.append(f"must start with the greeting '{greeting}'")
    questions = text.count("?")
    if questions != 1:
        problems.append(f"{questions} question marks (want exactly 1)")
    named = text.count("Nument")
    if part in ("day0", "day0_alt") and named != 1:
        problems.append("must name Nument once" if named == 0 else "names Nument more than once")
    elif named > 1:
        problems.append("names Nument more than once")
    if part in ("day0", "day0_alt") and _LIST_LINE.search(text):
        problems.append("a list in the first email (write sentences)")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and (_SIGN_OFF.match(lines[-1]) or "team nument" in lines[-1].lower()):
        problems.append("ends with a sign-off (code adds 'Team Nument')")
    return problems


@dataclass
class SeqChecked:
    """One sequence draft with everything the code and the critic found."""

    seq: EmailSequence
    tag: str
    model: str | None
    hard: list[str]  # lint problems of a part that is sent: never stored
    claims: list[str]  # invented numbers or names, unknown ids: never stored either
    variety: list[str]  # too close to today's first emails: stored, flagged
    optional: list[str]  # problems of the alternative first email: stored without it
    drop_alt: bool
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
            -len(self.optional),
        )


def sequence_parts(seq: EmailSequence) -> dict[str, str]:
    return {"subject": seq.subject, "day0": seq.day0, "day3": seq.day3, "day7": seq.day7, "day12": seq.day12}


def check_sequence(
    seq: EmailSequence, si: SequenceInput, day: DayLog, tag: str = "", model: str | None = None
) -> SeqChecked:
    """Lint every part, check every claim in every part, and the first email's variety against today's."""
    hard: list[str] = []
    for part, text in sequence_parts(seq).items():
        hard += [f"{part}: {p}" for p in lint_part(text, part, si.greeting)]
    optional: list[str] = []
    alt = (seq.day0_alt or "").strip()
    drop_alt = not alt
    if alt:
        alt_problems = lint_part(alt, "day0_alt", si.greeting)
        if alt_problems:
            drop_alt = True
            optional += [f"day0_alt: {p}" for p in alt_problems]
    texts = [claim_text(t) for t in sequence_parts(seq).values()]
    if not drop_alt:
        texts.append(claim_text(alt))
    claims = claim_problems(texts, [c.ids for c in seq.claims], si.claim_ctx)
    variety = variety_problems(seq.day0, si.segment.id, si.business.get("web_domain"), day)
    # canonical ids, as the lead rules compare them with the evidence (leads.decide)
    resolved = (evidence.resolve_cited_id(i, si.claim_ctx.known_ids) for c in seq.claims for i in c.ids)
    cited = list(dict.fromkeys(i for i in resolved if i is not None))
    return SeqChecked(seq, tag, model, hard, claims, variety, optional, drop_alt, cited)


class SequenceWriter:
    """The write, check and critic loop for one startup lead: one rewrite for code problems, one for a critic
    score under 9, at most three drafts and two critic calls (the same rules as `Writer`)."""

    def __init__(self, router: ai.AIRouter, run_id: str, day: DayLog) -> None:
        self.router, self.run_id, self.day = router, run_id, day

    def _write(self, si: SequenceInput, feedback: list[str]) -> ai.AIResult[EmailSequence]:
        today = self.day.by_segment.get(si.segment.id, [])
        inputs = {
            **si.inputs,
            "feedback": feedback,
            "avoid_openers": sorted({opener(m) for m in today} - {""})[-10:],
            "avoid_questions": sorted({closing_question(m) for m in today} - {""})[-10:],
        }
        return ai.call(self.router, SEQUENCE_TASK, inputs, EmailSequence, run_id=self.run_id, lead_id=si.lead["id"])

    def _critic(self, si: SequenceInput, c: SeqChecked) -> None:
        res = ai.call(
            self.router,
            "check_message",
            {
                "kind": "email",
                "message": c.seq.day0,
                "subject": c.seq.subject,
                "followups": [
                    {"day": 3, "text": c.seq.day3},
                    {"day": 7, "text": c.seq.day7},
                    {"day": 12, "text": c.seq.day12},
                ],
                "greeting": si.greeting,
                "business_name": si.inputs["company"],
                "offer": si.inputs["offer"],
                "why_now": si.inputs["why_now"],
                "segment_id": si.segment.id,
                "country": si.segment.country,
                "facts": si.inputs["facts"],
                "signals": si.inputs["signals"],
                "writer_model": c.model or "",
            },
            MessageCheck,
            run_id=self.run_id,
            lead_id=si.lead["id"],
            exclude_model=c.model,
        )
        c.score, c.issues = res.output.score, list(res.output.issues)
        if res.output.suggested_fix and res.output.score < MIN_CRITIC_SCORE:
            c.issues.append(f"a reviewer suggested this first email: {res.output.suggested_fix}")
        c.critic_tag, c.critic_model = res.tag, res.model

    def write(self, si: SequenceInput) -> list[SeqChecked]:
        drafts: list[SeqChecked] = []
        feedback: list[str] = []
        code_rewrite = critic_rewrite = False
        while True:
            res = self._write(si, feedback)
            c = check_sequence(res.output, si, self.day, res.tag, res.model)
            drafts.append(c)
            if c.problems and not code_rewrite:
                code_rewrite = True
                feedback = c.problems
                continue
            if c.hard or c.claims:
                return drafts  # second failure: the best version is kept only if it passes (never with claims)
            self._critic(si, c)
            if (c.score or 0) >= MIN_CRITIC_SCORE or critic_rewrite:
                return drafts
            critic_rewrite = True
            feedback = c.issues or ["make the first email more specific to them and easier to answer in five seconds"]


def pick_sequence(drafts: Sequence[SeqChecked]) -> SeqChecked:
    return max(drafts, key=lambda c: c.rank)


# ---- storage: the lead, the thread and its four drafts in one transaction ------------------------------


class _NotStored(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _lock_key(domain: str) -> int:
    """A stable advisory lock id per domain, so two runs never open two threads to one company."""
    digest = hashlib.sha1(f"email_thread:{domain}".encode(), usedforsecurity=False).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def store_sequence(
    si: SequenceInput, best: SeqChecked, flags: list[str], run_id: str, rules: OutreachRules, now: datetime
) -> str:
    """Write the lead's first email, open the thread (or rewrite its drafts) and log it, all or nothing.
    Returns 'stored' or why nothing was written: the open thread and the cooldown are checked again here,
    under a per-domain lock, and the lead must still be new with the text we read."""
    seq = best.seq
    bodies = {STEP_OF[p]: str(getattr(seq, p)).strip() for p in SEQUENCE_PARTS}
    subject = seq.subject.strip()
    try:
        with db.tx("engine", {"run_id": run_id, "stage": "message"}) as conn:
            for d in sorted(si.domains):
                conn.execute("select pg_advisory_xact_lock(%s)", [_lock_key(d)])
            threads = [t for ts in domain_threads(si.domains, conn=conn).values() for t in ts]
            why = cooldown_block(threads, si.lead["id"], now, rules.cooldown_days, own_thread_id=si.thread_id)
            if why:
                raise _NotStored(why)
            cur = conn.execute(
                """
                update public.leads set message = %(message)s, message_alt = %(alt)s, email_subject = %(subject)s,
                       email_body = null, followup_d3 = null, followup_d7 = null, message_model = %(model)s,
                       message_check_score = %(score)s, regen_requested_at = null
                 where id = %(id)s and stage = 'new' and message is not distinct from %(old)s
                """,
                {
                    "message": bodies[0],
                    "alt": None if best.drop_alt else (seq.day0_alt or "").strip() or None,
                    "subject": subject,
                    "model": best.tag,
                    "score": best.score,
                    "id": si.lead["id"],
                    "old": si.lead.get("message"),
                },
            )
            if cur.rowcount == 0:
                raise _NotStored("changed_meanwhile")
            if si.thread_id is not None:
                changed = 0
                for step, body in bodies.items():
                    changed += conn.execute(
                        "update public.email_messages set subject = %s, body = %s, status = 'draft', "
                        "scheduled_for = null, error = null, updated_at = now() "
                        "where thread_id = %s and direction = 'out' and step = %s and status = any(%s)",
                        [subject if step == 0 else None, body, si.thread_id, step, sorted(REWRITABLE)],
                    ).rowcount
                if changed != len(bodies):
                    raise _NotStored("thread_moved_on")
                thread_id = si.thread_id
            else:
                row = conn.execute(
                    "insert into public.email_threads (lead_id, contact_id, to_email, to_domain, mode, status) "
                    "values (%s, %s, %s, %s, 'review', 'open') "
                    "on conflict (lead_id) where status = 'open' do nothing returning id",
                    [si.lead["id"], si.contact.get("id"), si.to_email, si.to_domain],
                ).fetchone()
                if row is None:
                    raise _NotStored("open_thread")
                thread_id = str(row["id"])
                conn.cursor().executemany(
                    "insert into public.email_messages (thread_id, direction, step, subject, body, status) "
                    "values (%s, 'out', %s, %s, %s, 'draft')",
                    [[thread_id, step, subject if step == 0 else None, body] for step, body in bodies.items()],
                )
            conn.execute(
                "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'ai_output', %s)",
                [
                    si.lead["id"],
                    db.Jsonb(
                        {
                            "kind": "message_stored",
                            "task": SEQUENCE_TASK,
                            "model": best.tag,
                            "critic_model": best.critic_tag,
                            "check_score": best.score,
                            "cited_ids": sorted(set(best.cited)),
                            "basis": si.basis,
                            "offer_key": si.offer_key,
                            "thread_id": thread_id,
                            "rewritten": si.thread_id is not None,
                        }
                    ),
                ],
            )
            if flags:
                # clock_timestamp(): strictly newer than the drafts (their now()), so the auto-send bar sees it
                conn.execute(
                    "insert into public.activities (lead_id, source, type, payload, at) "
                    "values (%s, 'engine', 'message_flagged', %s, clock_timestamp())",
                    [
                        si.lead["id"],
                        db.Jsonb(
                            {
                                "issues": flags[:10],
                                "score": best.score,
                                "model": best.tag,
                                "critic_model": best.critic_tag,
                                "thread_id": thread_id,
                            }
                        ),
                    ],
                )
    except _NotStored as exc:
        return exc.reason
    return "stored"


def flag_unwritable_sequence(lead_id: str, problems: list[str], tag: str | None, run_id: str) -> None:
    """No sequence passed the checks: nothing is stored and no thread opened; the founder sees why."""
    with db.tx("engine", {"run_id": run_id, "stage": "message"}) as conn:
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', "
            "'message_flagged', %s)",
            [lead_id, db.Jsonb({"issues": problems[:10], "stored": False, "model": tag, "task": SEQUENCE_TASK})],
        )


def restore_from_thread(lead_id: str, thread_id: str, run_id: str) -> bool:
    """A rescore cleared the lead's text while its thread is already under way: show the thread's first email
    again (drafts are never rewritten once approved, queued or sent)."""
    with db.tx("engine", {"run_id": run_id, "stage": "message"}) as conn:
        cur = conn.execute(
            "update public.leads l set message = m.body, email_subject = m.subject "
            "from public.email_messages m "
            "where l.id = %s and l.stage = 'new' and l.message is null "
            "and m.thread_id = %s and m.direction = 'out' and m.step = 0",
            [lead_id, thread_id],
        )
        return cur.rowcount > 0


# ---- selection: which startup leads get a sequence, and what happens to their threads -------------------

_STARTUP_SELECT: Final = """
select l.id, l.business_id, l.segment_id, l.grade, l.pitch_mode, l.angle, l.channel, l.message, l.message_model,
       l.regen_requested_at, l.created_at, s.total
  from public.leads l
  left join public.scores s on s.id = l.score_id
 where l.stage = 'new' and l.grade in ('A', 'B') and l.segment_id = any(%(segments)s)
   and (l.message is null or l.regen_requested_at is not null or l.message_model is null
        or l.message_model not like %(sequence_tag)s)
 order by l.grade, s.total desc nulls last, l.created_at
"""
# A lead whose sequences failed the checks this often in the last days waits (each try costs up to 5 AI calls).
UNWRITABLE_MAX: Final = 2
UNWRITABLE_DAYS: Final = 3


@dataclass
class StartupLead:
    """A selected startup lead and what the stage does with it."""

    lead: Row
    action: str  # write | rewrite | restore | skip:<why>
    thread: Row | None = None


def sequence_action(
    lead: Mapping[str, Any], hist: leads.MessageHistory, thread: Row | None, steps: Sequence[Row]
) -> str:
    """write (no open thread), rewrite (an open thread with nothing approved or sent), restore, or skip:<why>.

    A person's edit is never overwritten unless they pressed Regenerate afterwards (12.11). A text a rescore
    cleared is rewritten only while every step is still an untouched draft."""
    regen = lead.get("regen_requested_at")
    asked = regen is not None and (hist.edited_at is None or regen > hist.edited_at)
    if thread is not None:
        statuses = {str(m["status"]) for m in steps}
        if asked and statuses <= REWRITABLE:
            return "rewrite"
        if not asked and lead.get("message") is None and statuses <= {"draft"}:
            return "rewrite"
        if lead.get("message") is None:
            return "restore"
        return "skip:thread_in_progress" if asked else "skip:has_thread"
    if asked:
        return "write"
    if hist.edited:
        return "skip:edited_by_person"
    return "write"


def select_startup(segment_ids: Sequence[str]) -> list[StartupLead]:
    """New A and B leads of startup email segments without a sequence, or with Regenerate pressed, and what to
    do with each."""
    if not segment_ids:
        return []
    rows = db.fetch_all(_STARTUP_SELECT, {"segments": list(segment_ids), "sequence_tag": f"%#{SEQUENCE_TASK}%"})
    for r in rows:
        r["id"], r["business_id"] = str(r["id"]), str(r["business_id"])
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    history = leads.message_history(ids)
    threads = {
        str(t["lead_id"]): {**t, "id": str(t["id"])}
        for t in db.fetch_all(
            "select id, lead_id, contact_id::text as contact_id, to_email, to_domain from public.email_threads "
            "where lead_id = any(%s::uuid[]) and status = 'open'",
            [ids],
        )
    }
    steps: dict[str, list[Row]] = {}
    if threads:
        for m in db.fetch_all(
            "select thread_id::text as thread_id, step, status from public.email_messages "
            "where thread_id = any(%s::uuid[]) and direction = 'out' and step is not null",
            [[t["id"] for t in threads.values()]],
        ):
            steps.setdefault(m["thread_id"], []).append(m)
    failed = {
        str(r["lead_id"])
        for r in db.fetch_all(
            "select lead_id from public.activities where lead_id = any(%s::uuid[]) and type = 'message_flagged' "
            "and payload ->> 'task' = %s and (payload ->> 'stored') = 'false' "
            "and at > now() - make_interval(days => %s) group by lead_id having count(*) >= %s",
            [ids, SEQUENCE_TASK, UNWRITABLE_DAYS, UNWRITABLE_MAX],
        )
    }
    out: list[StartupLead] = []
    for r in rows:
        thread = threads.get(r["id"])
        action = sequence_action(
            r, history.get(r["id"], leads.MessageHistory()), thread, steps.get(thread["id"], []) if thread else []
        )
        if action in ("write", "rewrite") and r["id"] in failed and r.get("regen_requested_at") is None:
            action = "skip:failed_recently"
        out.append(StartupLead(r, action, thread))
    return out


def sequence_contacts(business_ids: Sequence[str]) -> dict[str, list[Row]]:
    """Every contact with an address, with what the founder-email stage knows about it."""
    if not business_ids:
        return {}
    rows = db.fetch_all(
        "select id::text as id, business_id::text as business_id, name, role, email, email_status, email_origin, "
        "line, is_decision_maker, verified, source, do_not_contact, created_at "
        "from public.contacts where business_id = any(%s::uuid[]) and email is not null order by created_at",
        [list(business_ids)],
    )
    out: dict[str, list[Row]] = {}
    for r in rows:
        out.setdefault(r["business_id"], []).append(r)
    return out


def lead_offer_rows(lead_ids: Sequence[str]) -> dict[str, dict[int, Row]]:
    """The stored offer picks per lead (rank 1 main, rank 2 backup) with the offer's own copy."""
    if not lead_ids:
        return {}
    rows = db.fetch_all(
        "select lo.lead_id::text as lead_id, lo.rank, lo.offer_key, lo.why_now, lo.cited_ids, "
        "o.name, o.best_for, o.promise, o.timeline, o.typical_range "
        "from public.lead_offers lo join public.offers o on o.key = lo.offer_key "
        "where lo.lead_id = any(%s::uuid[])",
        [list(lead_ids)],
    )
    out: dict[str, dict[int, Row]] = {}
    for r in rows:
        out.setdefault(r["lead_id"], {})[int(r["rank"])] = r
    return out


def eligibility(
    c: StartupLead,
    b: Row,
    seg: Segment,
    contacts: Sequence[Row],
    suppressed: Suppression,
    rules: OutreachRules,
    threads: Mapping[str, Sequence[DomainThread]],
    now: datetime,
) -> tuple[Row | None, str | None]:
    """(the contact to write to, None) when a thread may be opened or rewritten, else (None, why not)."""
    if c.thread is not None:  # a rewrite keeps the thread's address
        contact = next((x for x in contacts if x["id"] == c.thread.get("contact_id")), None)
        if contact is None or str(contact.get("email") or "").lower() != str(c.thread["to_email"]).lower():
            return None, "thread_contact_changed"
        if sendable_contact([contact], suppressed) is None:
            return None, "no_sendable_email"
    else:
        found = sendable_contact(contacts, suppressed)
        if found is None:
            return None, "no_sendable_email"
        contact = found
    why = rules.country_block(str(b.get("country") or seg.country), contact.get("email_origin"))
    if why:
        return None, why
    to_domain, domains = thread_domains(str(contact["email"]), b)
    if not to_domain:
        return None, "no_domain"
    if email_domain(str(contact["email"])) in suppressed.domains or any(d in suppressed.domains for d in domains):
        return None, "suppressed_domain"
    own = c.thread["id"] if c.thread is not None else None
    for d in domains:
        why = cooldown_block(threads.get(d, []), c.lead["id"], now, rules.cooldown_days, own_thread_id=own)
        if why:
            return None, why
    return contact, None


def run(rc: RunContext, router: ai.AIRouter | None = None) -> dict[str, Any]:
    """`nlead message`: write, check and store messages for new A and B leads. Startup segments that go out by
    email get the 12-day sequence and its thread; every other lead the WhatsApp message (or its email)."""
    now = datetime.now(UTC)
    segments = score.enabled_segments(rc)
    startup = {k: s for k, s in segments.items() if is_startup_email(s)}
    classic = {k: s for k, s in segments.items() if k not in startup}
    stats: Counter[str] = Counter()
    rows = db.fetch_all(_SELECT, {"segments": list(classic), "limit": None}) if classic else []
    for r in rows:
        r["id"], r["business_id"] = str(r["id"]), str(r["business_id"])
    history = leads.message_history([r["id"] for r in rows]) if rows else {}
    todo = [r for r in rows if wants_message(r, history.get(r["id"], leads.MessageHistory()))]
    stats["skipped.edited_by_person"] = len(rows) - len(todo)
    if rc.opts.limit:
        todo = todo[: rc.opts.limit]
    stats["selected"] = len(todo)
    planned = select_startup(list(startup))
    for c in planned:
        if c.action.startswith("skip:"):
            stats[f"sequence.skipped.{c.action.removeprefix('skip:')}"] += 1
    work = [c for c in planned if not c.action.startswith("skip:")]
    if rc.opts.limit:
        work = work[: max(0, rc.opts.limit - len(todo))]
    if startup:
        stats["sequence.selected"] = len(work)
    if rc.opts.dry_run or not (todo or work):
        return _finish(rc, stats)
    for c in work:
        if (
            c.action == "restore"
            and c.thread is not None
            and restore_from_thread(c.lead["id"], c.thread["id"], rc.run_id)
        ):
            stats["sequence.restored"] += 1
    writes = [c for c in work if c.action in ("write", "rewrite")]
    if not (todo or writes):
        return _finish(rc, stats)
    if router is None:
        try:
            router = ai.router_for(rc)
        except ai.AIUnavailable as exc:
            stats["ai.unavailable"] += 1
            log.warning("message.no_ai", reason=exc.reason)
            return _finish(rc, stats)
    day = load_day(list(segments), now)
    going = _write_classic(rc, router, todo, classic, day, now, stats) if todo else True
    if going and writes:
        _write_startup(rc, router, writes, startup, day, now, stats)
    return _finish(rc, stats)


def _finish(rc: RunContext, stats: Counter[str]) -> dict[str, Any]:
    result = dict(sorted(stats.items()))
    rc.stats["message"] = result
    log.info("message.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result


def _write_startup(
    rc: RunContext,
    router: ai.AIRouter,
    writes: Sequence[StartupLead],
    segments: Mapping[str, Segment],
    day: DayLog,
    now: datetime,
    stats: Counter[str],
) -> None:
    """The sequence, its checks and its thread for each startup lead that may get one (contract 4.6). Leads that
    may not get a thread are skipped before any AI call."""
    lead_ids = [c.lead["id"] for c in writes]
    bids = list(dict.fromkeys(c.lead["business_id"] for c in writes))
    biz = evidence.businesses(bids)
    facts = evidence.verified_facts(bids)
    signals = evidence.signals_for(bids)
    contacts = sequence_contacts(bids)
    profiles = startup_profiles(bids)
    offers = lead_offer_rows(lead_ids)
    suppressed = Suppression.load()
    rules = OutreachRules.load()
    keys = {
        d
        for bid in bids
        if bid in biz
        for c in contacts.get(bid, [])
        for d in thread_domains(str(c["email"]), biz[bid])[1]
    }
    threads = domain_threads(sorted(keys))
    writer = SequenceWriter(router, rc.run_id, day)
    failures = 0
    for c in writes:
        lead, bid = c.lead, c.lead["business_id"]
        b, seg = biz.get(bid), segments.get(str(lead["segment_id"]))
        if b is None or seg is None:
            continue
        picks = offers.get(lead["id"], {})
        if 1 not in picks:
            stats["sequence.skipped.no_offer"] += 1
            continue
        contact, why = eligibility(c, b, seg, contacts.get(bid, []), suppressed, rules, threads, now)
        if contact is None:
            stats[f"sequence.skipped.{why}"] += 1
            continue
        try:
            si = build_sequence_input(
                lead, b, seg, contact, picks[1], picks.get(2), facts.get(bid, []), signals.get(bid, []),
                profiles.get(bid), now,
            )  # fmt: skip
        except Exception as exc:  # bad data for one lead must not stop the others
            stats["sequence.errors"] += 1
            log.error("message.sequence_input_failed", lead_id=lead["id"], error=f"{type(exc).__name__}: {exc}")
            continue
        si.thread_id = c.thread["id"] if c.thread is not None else None
        try:
            drafts = writer.write(si)
        except ai.AIBudgetStop:
            stats["sequence.stopped.budget"] += 1
            break
        except ai.AIUnavailable:
            stats["sequence.ai.failed"] += 1
            failures += 1
            if failures >= AI_FAILURES_BEFORE_STOP:
                stats["sequence.stopped.ai_down"] += 1
                break
            continue
        failures = 0
        stats["sequence.drafts"] += len(drafts)
        best = pick_sequence(drafts)
        if best.hard or best.claims:
            flag_unwritable_sequence(lead["id"], best.problems, best.tag, rc.run_id)
            stats["sequence.flagged.not_stored"] += 1
            continue
        flags = flags_for(best)
        outcome = store_sequence(si, best, flags, rc.run_id, rules, now)
        if outcome != "stored":
            stats[f"sequence.skipped.{outcome}"] += 1
            continue
        day.add(seg.id, b.get("web_domain"), best.seq.day0)
        for d in si.domains:  # the next lead of the same company now sees this thread
            threads.setdefault(d, []).append(DomainThread("new", lead["id"], "open", now, None, False))
        stats["sequence.stored"] += 1
        stats["sequence.rewritten" if si.thread_id else "sequence.threads"] += 1
        if flags:
            stats["sequence.flagged.needs_edit"] += 1
        if best.score is not None:
            stats[f"sequence.score.{best.score}"] += 1


def _write_classic(
    rc: RunContext,
    router: ai.AIRouter,
    todo: Sequence[Row],
    segments: Mapping[str, Segment],
    day: DayLog,
    now: datetime,
    stats: Counter[str],
) -> bool:
    """The WhatsApp path for every other lead. Returns False when the budget or the AI stopped the stage."""
    configs = score.segment_configs(segments)
    ids = [r["business_id"] for r in todo]
    biz = evidence.businesses(ids)
    facts = evidence.verified_facts(ids)
    signals = evidence.signals_for(ids)
    contacts = evidence.contacts_for(ids)
    writer = Writer(router, rc.run_id, day)
    failures = 0
    for lead in todo:
        b, seg = biz.get(lead["business_id"]), segments.get(str(lead["segment_id"]))
        if b is None or seg is None:
            continue
        try:
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
        except Exception as exc:  # bad data for one lead must not stop the others
            stats["errors"] += 1
            log.error("message.input_failed", lead_id=lead["id"], error=f"{type(exc).__name__}: {exc}")
            continue
        try:
            drafts = writer.write(li)
        except ai.AIBudgetStop:
            stats["stopped.budget"] += 1
            return False
        except ai.AIUnavailable:
            stats["ai.failed"] += 1
            failures += 1
            if failures >= AI_FAILURES_BEFORE_STOP:
                stats["stopped.ai_down"] += 1
                return False
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
    return True
