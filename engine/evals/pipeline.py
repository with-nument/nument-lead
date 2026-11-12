"""How the eval gets an outcome for one golden business.

`LivePipeline` runs production code on the frozen pages, synchronously (17.4.1): extract_facts through the
AI router, quote verification, scoring with the weights in the working tree, the judge (one grade step at
most), then write_message, lint and check_message for A and B leads. It writes nothing to the database;
only the router's cost rows are recorded, as for any AI call.

`ReplayPipeline` reads outcomes saved by an earlier run (`--save-outcomes`), so metrics and thresholds can
be re-checked for free.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import phonenumbers
from pydantic import BaseModel

from nument_engine import db
from nument_engine.models import FactsExtraction, LeadJudgement, MessageCheck, MessageDraft
from nument_engine.ops import bindings
from nument_engine.segments import Segment, load_segments

from .golden import GOLDEN_DIR, Label, load_pages
from .measures import MessageOutcome, Outcome, OutcomeFact

GRADES = "ABCD"
PAGE_CHARS = 12_000  # per page; about 16K tokens for a whole business, like production (9.11.2)

# FactsExtraction attribute -> (Step 9 field name, value keys), see A.13.2
FIELD_MAP: dict[str, str] = {
    "business_name": "business_name",
    "decision_makers": "decision_maker",
    "phones": "phone",
    "emails": "email",
    "branches": "branches",
    "staff_or_doctors": "staff_or_doctors",
    "services": "service",
    "price_points": "price_point",
    "booking_method": "booking_method",
    "whatsapp_present": "whatsapp_present",
    "chat_widget": "chat_widget",
    "careers_roles": "careers_role",
    "in_house_tech": "in_house_tech",
    "is_agency_or_vendor": "is_agency_or_vendor",
    "languages": "language",
    "sales_notes": "sales_note",
}


class EvalNotReady(NotImplementedError):
    """The eval cannot run yet: no golden set, or a production stage is not built.

    A NotImplementedError, so the command line reports it as "not built yet" with exit code 2."""


class EvalPipeline(Protocol):
    def run(self, label: Label) -> Outcome: ...


@dataclass
class ReplayPipeline:
    """Outcomes recorded by an earlier run, one JSON object per line."""

    path: Path
    _by_id: dict[str, Outcome] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                outcome = Outcome.from_dict(json.loads(line))
                self._by_id[outcome.business_id] = outcome

    def run(self, label: Label) -> Outcome:
        return self._by_id.get(label.business_id) or Outcome(
            label.business_id, label.segment, error="not in replay file"
        )


def flatten(extraction: FactsExtraction) -> list[dict[str, Any]]:
    """FactsExtraction to fact rows with Step 9 field names: {id, field, value, quote, url}. Ids are 1, 2, ...
    so prompts show them as F1, F2 and citations map back by dropping the F."""
    rows: list[dict[str, Any]] = []
    for attr, field_name in FIELD_MAP.items():
        found = getattr(extraction, attr)
        for item in found if isinstance(found, list) else [found] if found is not None else []:
            data = item.model_dump() if isinstance(item, BaseModel) else dict(item)
            quote, url = data.pop("quote", None), data.pop("url", None)
            rows.append({"id": str(len(rows) + 1), "field": field_name, "value": data, "quote": quote, "url": url})
    return rows


def phone_rank(fact: Mapping[str, Any], region: str) -> tuple[int, int] | None:
    """Sort key for the best contact phone: mobile first, then a person's number (often the owner's)."""
    raw = (fact.get("value") or {}).get("number")
    try:
        parsed = phonenumbers.parse(str(raw), region.upper())
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_possible_number(parsed):
        return None
    mobile = phonenumbers.number_type(parsed) in (phonenumbers.PhoneNumberType.MOBILE,
                                                  phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE)  # fmt: skip
    person = (fact.get("value") or {}).get("belongs_to") == "person"
    return (0 if mobile else 1, 0 if person else 1)


def top_phone(facts: Sequence[Mapping[str, Any]], region: str) -> tuple[str | None, str]:
    """(E.164, phone type) of the best verified phone, the way the contact step picks one."""
    ranked = []
    for i, f in enumerate(facts):
        if f["field"] == "phone" and f.get("verified"):
            key = phone_rank(f, region)
            if key is not None:
                ranked.append((key, i, f))
    if not ranked:
        return None, "unknown"
    key, _, best = min(ranked)
    parsed = phonenumbers.parse(str(best["value"]["number"]), region.upper())
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), "mobile" if key[
        0
    ] == 0 else "landline"


def clamp_grade(rule: str, judged: str) -> str:
    """The judge may move a grade by one step at most (11.10.4)."""
    i, j = GRADES.index(rule), GRADES.index(judged)
    return GRADES[max(i - 1, min(i + 1, j))]


@dataclass
class LivePipeline:
    """Production stages on frozen pages. Each dependency can be replaced (tests use fakes)."""

    run_task: bindings.TaskRunner
    still_there: bindings.QuoteChecker
    score_business: bindings.Scorer
    lint: bindings.Linter
    segments: dict[str, Segment] = field(default_factory=load_segments)
    associate_name: str = "Aditya"
    golden_dir: Path = GOLDEN_DIR
    business_row: Callable[[str], dict[str, Any] | None] = field(default=lambda bid: _business_row(bid))
    signals_of: Callable[[str], list[dict[str, Any]]] = field(default=lambda bid: _signals(bid))

    @classmethod
    def from_production(cls, rc: Any, golden_dir: Path = GOLDEN_DIR) -> LivePipeline:
        """Bind the real router, verify, score and lint. Raises EvalNotReady naming whatever is missing."""
        missing: list[str] = []
        parts: dict[str, Any] = {}
        for name, make in (("run_task", lambda: bindings.task_runner(rc)), ("still_there", bindings.quote_checker),
                           ("score_business", bindings.business_scorer), ("lint", bindings.message_linter)):  # fmt: skip
            try:
                parts[name] = make()
            except NotImplementedError as exc:
                missing.append(str(exc))
        if missing:
            raise EvalNotReady("; ".join(missing))
        from nument_engine.settings import get_settings

        return cls(**parts, associate_name=get_settings().associate_name, golden_dir=golden_dir)

    def run(self, label: Label) -> Outcome:
        pages = [
            {"url": p["url"], "text": str(p["text"])[:PAGE_CHARS]}
            for p in load_pages(label.business_id, self.golden_dir)
        ]
        if not pages:
            return Outcome(label.business_id, label.segment, error="no frozen pages (run nlead eval --export-golden)")
        seg = self.segments[label.segment]
        region = seg.country
        biz = self.business_row(label.business_id) or {"id": label.business_id, "segment_id": label.segment,
                                                        "name": label.name or "", "country": seg.country}  # fmt: skip
        extraction = self.run_task("extract_facts", {
            "segment_id": seg.id, "business_name": biz.get("name") or label.name or "",
            "website": biz.get("website") or "", "structured_data": {}, "tech_flags": {}, "pages": pages,
        })  # fmt: skip
        facts = flatten(
            extraction if isinstance(extraction, FactsExtraction) else FactsExtraction.model_validate(extraction)
        )
        texts = {p["url"]: p["text"] for p in pages}
        everything = "\n".join(texts.values())
        for f in facts:
            f["verified"] = bool(f["quote"]) and self.still_there(str(f["quote"]), texts.get(str(f["url"]), everything))
        verified = [f for f in facts if f["verified"]]
        phone, phone_type = top_phone(verified, region)
        contacts = [] if phone is None else [{"phone_e164": phone, "phone_type": phone_type, "source": "website",
                                              "is_decision_maker": False, "verified": True, "do_not_contact": False}]  # fmt: skip
        signals = self.signals_of(label.business_id)
        result = self.score_business(biz, verified, signals, contacts, seg)
        grade, total = str(result.grade), float(result.total)
        grade = self._judge(seg, result, verified, signals, grade)
        message = self._message(seg, biz, result, verified, signals) if grade in ("A", "B") else None
        return Outcome(
            business_id=label.business_id, segment=label.segment, total=total, grade=grade,
            facts=[OutcomeFact(f["field"], f["value"], f["verified"]) for f in facts],
            top_phone_e164=phone, message=message,
        )  # fmt: skip

    def _judge(
        self, seg: Segment, result: Any, facts: list[dict[str, Any]], signals: list[dict[str, Any]], grade: str
    ) -> str:
        if grade == "D" or int(getattr(result, "fit", 3)) < 2:
            return grade
        answer = self.run_task("judge_lead", {
            "segment_id": seg.id, "pitch_mode": result.pitch_mode, "total": result.total, "fit": result.fit,
            "can_pay": result.can_pay, "intent": result.intent, "reach": result.reach, "grade": grade,
            "allowed_angles": [a.key for a in seg.angles], "facts": facts, "signals": signals,
        })  # fmt: skip
        judged = answer if isinstance(answer, LeadJudgement) else LeadJudgement.model_validate(answer)
        known = {str(f["id"]) for f in facts} | {str(s.get("id")) for s in signals}
        if any(c.removeprefix("F").removeprefix("S") not in known for c in judged.cited_ids):
            return grade  # a citation that does not exist: the rule grade stands (11.10.4)
        return clamp_grade(grade, judged.judge_grade)

    def _message(
        self,
        seg: Segment,
        biz: Mapping[str, Any],
        result: Any,
        facts: list[dict[str, Any]],
        signals: list[dict[str, Any]],
    ) -> MessageOutcome:
        people = [f["value"] for f in facts if f["field"] == "decision_maker"]
        draft_raw = self.run_task("write_message", {
            "segment_id": seg.id, "pitch_mode": result.pitch_mode, "angle": result.angle,
            "business_name": biz.get("name") or "", "person_name": people[0].get("name") if people else None,
            "person_role": people[0].get("role") if people else None, "seen_where": "their own website",
            "facts": facts, "signals": [{**s, "summary": s.get("quote") or s.get("type")} for s in signals],
            "associate_name": self.associate_name, "packaged_outcome_name": seg.packaged_outcome,
        })  # fmt: skip
        draft = draft_raw if isinstance(draft_raw, MessageDraft) else MessageDraft.model_validate(draft_raw)
        known = {str(f["id"]) for f in facts} | {str(s.get("id")) for s in signals}
        unverified = sum(any(i.removeprefix("F").removeprefix("S") not in known for i in c.ids) for c in draft.claims)
        check_raw = self.run_task("check_message", {"message": draft.message, "facts": facts})
        check = check_raw if isinstance(check_raw, MessageCheck) else MessageCheck.model_validate(check_raw)
        return MessageOutcome(lint_ok_first=not self.lint(draft.message, "message"), critic_score=float(check.score),
                              unverified_claims=unverified)  # fmt: skip


def _business_row(business_id: str) -> dict[str, Any] | None:
    return db.fetch_one("select * from public.businesses where id = %s", [business_id])


def _signals(business_id: str) -> list[dict[str, Any]]:
    rows = db.fetch_all(
        "select id::text as id, type, category, points, observed_at, expires_at, quote, url, details "
        "from public.signals where business_id = %s and expires_at > now()",
        [business_id],
    )
    return [dict(r) for r in rows]
