"""Eval metrics and thresholds (Step 17.4.2), computed from what the pipeline produced for each business.

| Metric | Definition | Full set | 20-item subset |
|---|---|---|---|
| Fact precision | verified facts matching facts_truth.yaml / verified facts checked | 95% | 95% |
| Field recall | truth fields the extraction found (verified) / truth fields | 80% | 75% |
| Phone accuracy | top contact phone equals a truth phone / businesses with a truth phone | 95% | 90% |
| Grade precision | share labelled good among the 50 (subset: 10) highest totals | 80% | 70% |
| Bad rejection | share of businesses labelled bad that were graded C or D | 70% | 60% |
| Message lint pass | messages passing lint on the first attempt | 98% | 95% |
| Critic score | mean check_message score, 0 to 10 | 8.5 | 8.0 |
| Unverified claims | message claims not linked to a verified fact | 0 | 0 |

One guard is added so a broken run cannot pass: at most 10% of businesses may fail with an error. A metric
with nothing to measure is reported as "not measured" and does not fail the gate on its own.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Literal

import phonenumbers
from rapidfuzz import fuzz

from .golden import Label, Truth, TruthFacts

NAME_MATCH: Final[int] = 90
SERVICE_MATCH: Final[int] = 85
ERROR_SHARE_MAX: Final[float] = 0.10
BOOKING_WORDS: Final[dict[str, tuple[str, ...]]] = {
    "online_widget": ("online", "widget", "book now", "calendly", "practo", "app", "portal", "website booking"),
    "whatsapp": ("whatsapp",),
    "phone": ("phone", "call", "telephone"),
    "form": ("form", "enquiry", "inquiry"),
    "none": ("none", "no booking", "walk in", "walk-in"),
}
_TITLES = re.compile(r"\b(dr|mr|mrs|ms|prof|er)\b\.?", re.I)


@dataclass(frozen=True)
class Threshold:
    key: str
    label: str
    full: float
    subset: float
    kind: Literal["ratio", "score", "count"] = "ratio"
    higher_is_better: bool = True


THRESHOLDS: Final[tuple[Threshold, ...]] = (
    Threshold("fact_precision", "Fact precision", 0.95, 0.95),
    Threshold("field_recall", "Field recall", 0.80, 0.75),
    Threshold("phone_accuracy", "Phone accuracy", 0.95, 0.90),
    Threshold("grade_precision", "Grade precision", 0.80, 0.70),
    Threshold("bad_rejection", "Bad rejection", 0.70, 0.60),
    Threshold("lint_pass", "Message lint pass", 0.98, 0.95),
    Threshold("critic_score", "Critic score", 8.5, 8.0, kind="score"),
    Threshold("unverified_claims", "Unverified claims", 0, 0, kind="count", higher_is_better=False),
    Threshold("item_errors", "Businesses that errored", ERROR_SHARE_MAX, ERROR_SHARE_MAX, higher_is_better=False),
)
TOP_K_FULL, TOP_K_SUBSET = 50, 10


# ---------------------------------------------------------------------------
# What the pipeline produced
# ---------------------------------------------------------------------------


@dataclass
class OutcomeFact:
    field: str  # Step 9 field names (A.13.2): decision_maker, phone, branches, staff_or_doctors, service, ...
    value: Any
    verified: bool


@dataclass
class MessageOutcome:
    lint_ok_first: bool
    critic_score: float | None
    unverified_claims: int = 0


@dataclass
class Outcome:
    business_id: str
    segment: str
    total: float | None = None
    grade: str | None = None
    facts: list[OutcomeFact] = field(default_factory=list)
    top_phone_e164: str | None = None
    message: MessageOutcome | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Outcome:
        msg = d.get("message")
        return cls(
            business_id=d["business_id"],
            segment=d["segment"],
            total=d.get("total"),
            grade=d.get("grade"),
            facts=[OutcomeFact(**f) for f in d.get("facts", [])],
            top_phone_e164=d.get("top_phone_e164"),
            message=MessageOutcome(**msg) if msg else None,
            error=d.get("error"),
        )


# ---------------------------------------------------------------------------
# Comparing a fact with the truth
# ---------------------------------------------------------------------------


def _get(value: Any, *keys: str) -> Any:
    if isinstance(value, Mapping):
        for key in keys:
            if value.get(key) is not None:
                return value[key]
        return None
    return value


def norm_name(text: str) -> str:
    """Lower case, without titles (Dr., Mr.) or punctuation."""
    return " ".join(re.sub(r"[^a-z ]", " ", _TITLES.sub(" ", text.lower())).split())


def names_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return fuzz.token_set_ratio(norm_name(a), norm_name(b)) >= NAME_MATCH


def to_e164(value: Any, region: str) -> str | None:
    raw = _get(value, "e164", "phone_e164", "number", "value")
    if raw is None:
        return None
    try:
        parsed = phonenumbers.parse(str(raw), region.upper())
    except phonenumbers.NumberParseException:
        return None
    return (
        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        if phonenumbers.is_possible_number(parsed)
        else None
    )


def count_of(value: Any) -> float | None:
    raw = _get(value, "count", "value")
    try:
        return None if raw is None or isinstance(raw, bool) else float(raw)
    except (TypeError, ValueError):
        return None


def flag_of(value: Any) -> bool | None:
    raw = _get(value, "value", "present")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.lower() in ("yes", "true", "no", "false"):
        return raw.lower() in ("yes", "true")
    return None


def text_of(value: Any) -> str:
    raw = _get(value, "value", "name", "title", "text")
    return "" if raw is None else str(raw)


def booking_kinds(text: str) -> set[str]:
    """Booking channels named in free text, matched as whole words ("app" is not inside "WhatsApp")."""
    t = text.lower().replace("_", " ")
    return {kind for kind, words in BOOKING_WORDS.items() if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words)}


def widget_present(value: Any) -> bool | None:
    flag = flag_of(value)
    if flag is not None:
        return flag
    t = text_of(value).strip().lower()
    return None if not t else t not in ("none", "no", "unknown", "not found")


def check_fact(fact: OutcomeFact, truth: TruthFacts, region: str) -> bool | None:
    """True or False when the truth covers this fact's field; None when it cannot be checked."""
    f, v = fact.field, fact.value
    if f == "decision_maker" and truth.decision_maker:
        return names_match(text_of(_get(v, "name") or v), truth.decision_maker.name)
    if f == "phone" and truth.phones:
        return to_e164(v, region) in {p.e164 for p in truth.phones}
    if f == "branches" and truth.branches_count is not None:
        c = count_of(v)
        return c is not None and int(c) == truth.branches_count
    if f == "staff_or_doctors" and truth.staff_count_min is not None:
        c = count_of(v)
        return c is not None and c >= truth.staff_count_min
    if f == "booking_method" and truth.booking_method:
        return bool(booking_kinds(text_of(v)) & booking_kinds(truth.booking_method))
    if f == "whatsapp_present" and truth.whatsapp_present is not None:
        return flag_of(v) == truth.whatsapp_present
    if f == "chat_widget" and truth.chat_widget is not None:
        return widget_present(v) == truth.chat_widget
    if f == "in_house_tech" and truth.has_in_house_tech in ("yes", "no"):
        return flag_of(v) == (truth.has_in_house_tech == "yes")
    if f == "is_agency_or_vendor" and truth.is_agency_or_vendor is not None:
        return flag_of(v) == truth.is_agency_or_vendor
    if f == "service" and truth.services_include:  # the truth list is partial: only a match can be checked
        name = text_of(v)
        return (
            True
            if any(fuzz.token_set_ratio(name.lower(), s.lower()) >= SERVICE_MATCH for s in truth.services_include)
            else None
        )
    return None


def truth_items(truth: TruthFacts) -> list[tuple[str, Any]]:
    """Truth fields that an extraction can find (positive values only: absence cannot be quoted)."""
    items: list[tuple[str, Any]] = []
    if truth.decision_maker:
        items.append(("decision_maker", truth.decision_maker.name))
    items += [("phone", p.e164) for p in truth.phones]
    if truth.branches_count:
        items.append(("branches", truth.branches_count))
    if truth.staff_count_min:
        items.append(("staff_or_doctors", truth.staff_count_min))
    if truth.booking_method and booking_kinds(truth.booking_method) - {"none"}:
        items.append(("booking_method", truth.booking_method))
    if truth.whatsapp_present:
        items.append(("whatsapp_present", True))
    if truth.chat_widget:
        items.append(("chat_widget", True))
    if truth.has_in_house_tech == "yes":
        items.append(("in_house_tech", True))
    if truth.is_agency_or_vendor:
        items.append(("is_agency_or_vendor", True))
    items += [("service", s) for s in truth.services_include]
    return items


def found(item: tuple[str, Any], facts: Sequence[OutcomeFact], truth: TruthFacts, region: str) -> bool:
    """A verified fact of the item's field matches that specific truth value."""
    field_name, wanted = item
    for f in facts:
        if not f.verified or f.field != field_name:
            continue
        if field_name == "phone":
            if to_e164(f.value, region) == wanted:
                return True
        elif field_name == "service":
            if fuzz.token_set_ratio(text_of(f.value).lower(), str(wanted).lower()) >= SERVICE_MATCH:
                return True
        elif check_fact(f, truth, region):
            return True
    return False


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass
class MetricResult:
    key: str
    label: str
    value: float | None
    threshold: float
    n: int
    passed: bool | None  # None: not measured
    kind: str
    higher_is_better: bool

    @property
    def display(self) -> str | None:
        if self.value is None:
            return None
        if self.kind == "ratio":
            return f"{self.value * 100:.1f}%"
        if self.kind == "score":
            return f"{self.value:.2f}"
        return f"{self.value:.0f}"

    @property
    def threshold_display(self) -> str:
        op = ">=" if self.higher_is_better else "<="
        if self.kind == "ratio":
            return f"{op} {self.threshold * 100:.0f}%"
        return f"{op} {self.threshold:g}"


@dataclass
class EvalReport:
    subset: bool
    items: int
    metrics: list[MetricResult]

    @property
    def passed(self) -> bool:
        return all(m.passed is not False for m in self.metrics)

    def summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "subset": self.subset,
            "items": self.items,
            "metrics": [
                {**asdict(m), "display": m.display, "threshold_display": m.threshold_display} for m in self.metrics
            ],
        }

    def table(self) -> str:
        width = max(len(m.label) for m in self.metrics) + 2
        lines = [f"{'metric':<{width}}{'value':>9}  {'threshold':<11}{'n':>5}  result"]
        for m in self.metrics:
            result = "not measured" if m.passed is None else ("pass" if m.passed else "FAIL")
            lines.append(f"{m.label:<{width}}{m.display or 'n/a':>9}  {m.threshold_display:<11}{m.n:>5}  {result}")
        lines.append(
            f"\n{'PASSED' if self.passed else 'FAILED'}: {self.items} businesses ({'subset' if self.subset else 'full set'})"
        )
        return "\n".join(lines)


def _result(t: Threshold, value: float | None, n: int, subset: bool) -> MetricResult:
    limit = t.subset if subset else t.full
    passed = None if value is None else (value >= limit if t.higher_is_better else value <= limit)
    label = t.label
    if t.key == "grade_precision":
        label = f"Grade precision at {TOP_K_SUBSET if subset else TOP_K_FULL}"
    return MetricResult(t.key, label, value, limit, n, passed, t.kind, t.higher_is_better)


def evaluate(
    outcomes: Sequence[Outcome],
    labels: Mapping[str, Label],
    truth: Mapping[str, Truth],
    *,
    subset: bool,
) -> EvalReport:
    """Every metric in THRESHOLDS from the outcomes of one eval run."""
    ok = [o for o in outcomes if o.error is None]
    by_t = {t.key: t for t in THRESHOLDS}

    checked = matched = items_total = items_found = phones_total = phones_ok = 0
    for o in ok:
        t = truth.get(o.business_id)
        if t is None:
            continue
        region = o.segment.rsplit("-", 1)[-1]
        for f in o.facts:
            if f.verified:
                verdict = check_fact(f, t.facts, region)
                if verdict is not None:
                    checked += 1
                    matched += verdict
        wanted = truth_items(t.facts)
        items_total += len(wanted)
        items_found += sum(found(item, o.facts, t.facts, region) for item in wanted)
        if t.facts.phones:
            phones_total += 1
            phones_ok += o.top_phone_e164 in {p.e164 for p in t.facts.phones}

    k = TOP_K_SUBSET if subset else TOP_K_FULL
    ranked = sorted((o for o in ok if o.total is not None), key=lambda o: (-(o.total or 0), o.business_id))[:k]
    good_top = sum(labels[o.business_id].label == "good" for o in ranked if o.business_id in labels)
    bad = [o for o in ok if o.business_id in labels and labels[o.business_id].label == "bad" and o.grade]
    rejected = sum(o.grade in ("C", "D") for o in bad)
    messages = [o.message for o in ok if o.message is not None]
    critic = [m.critic_score for m in messages if m.critic_score is not None]

    def share(n: int, d: int) -> float | None:
        return n / d if d else None

    values: dict[str, tuple[float | None, int]] = {
        "fact_precision": (share(matched, checked), checked),
        "field_recall": (share(items_found, items_total), items_total),
        "phone_accuracy": (share(phones_ok, phones_total), phones_total),
        "grade_precision": (share(good_top, len(ranked)), len(ranked)),
        "bad_rejection": (share(rejected, len(bad)), len(bad)),
        "lint_pass": (share(sum(m.lint_ok_first for m in messages), len(messages)), len(messages)),
        "critic_score": (statistics.fmean(critic) if critic else None, len(critic)),
        "unverified_claims": (float(sum(m.unverified_claims for m in messages)) if messages else None, len(messages)),
        "item_errors": (share(len(outcomes) - len(ok), len(outcomes)), len(outcomes)),
    }
    metrics = [_result(by_t[key], value, n, subset) for key, (value, n) in values.items()]
    return EvalReport(subset=subset, items=len(outcomes), metrics=metrics)
