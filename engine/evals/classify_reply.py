"""The `classify_reply` eval: fictional replies to our email sequence with the category a person would give them.

    golden/classify_reply.jsonl   one reply per line: id, category, our_last_email, reply, subject, return_date,
                                  referral_name, referral_email, note (why it is that category)

It runs the production path: the plain opt-out rule first (`outreach.replies.opt_out_rule`), then the
`classify_reply` task, then `tidy_classification`. A prompt or model change for `classify_reply` passes it before
it goes live:

    uv run python -m evals.classify_reply --env dev      # about 44 small calls on the dev key
    uv run python -m evals.classify_reply --dry-run      # validate the file only, no AI

| Metric | Definition | Threshold |
|---|---|---|
| Accuracy | replies given the expected category | 85% |
| Opt-outs caught | unsubscribe replies classified unsubscribe (they are always honoured) | 100% |
| Harmful automatic actions | a confident (0.85 or more) out_of_office or not_now on a reply that is not one: it would reopen a sequence or close a lead by itself | 0 |
| Field accuracy | return dates and referral addresses that match where the reply states one | 90% |
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nument_engine.models import ReplyClassification
from nument_engine.outreach.replies import SAFE_CONFIDENCE, opt_out_rule, tidy_classification

from .golden import GOLDEN_DIR, GoldenError

FILE: Final = "classify_reply.jsonl"
Category = Literal[
    "interested", "send_plan", "question", "not_now", "out_of_office", "wrong_person", "unsubscribe", "other"
]
CATEGORIES: Final[tuple[str, ...]] = get_args(Category)
AUTOMATIC: Final = ("out_of_office", "not_now")  # categories that change a thread or a lead on their own
MIN_PER_CATEGORY: Final = 3
THRESHOLDS: Final[dict[str, float]] = {
    "accuracy": 0.85,
    "unsubscribe_recall": 1.0,
    "harmful_automatic": 0,
    "field_accuracy": 0.90,
}


class Example(BaseModel):
    """One labelled reply."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^r\d{2,4}$")
    category: Category
    our_last_email: str = Field(min_length=1)
    reply: str = Field(min_length=1)
    subject: str = ""
    return_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    referral_name: str | None = None
    referral_email: str | None = None
    note: str = ""

    def inputs(self) -> dict[str, Any]:
        return {"our_last_email": self.our_last_email, "reply": self.reply, "subject": self.subject}


def load(directory: Path = GOLDEN_DIR) -> list[Example]:
    """The labelled replies, validated: a bad line or a repeated id raises GoldenError naming the line."""
    path = directory / FILE
    if not path.is_file():
        raise GoldenError(f"{path} does not exist")
    out: list[Example] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            ex = Example.model_validate_json(line)
        except ValidationError as exc:
            raise GoldenError(f"{path.name} line {n}: {exc.errors()[0]['msg']} ({exc.errors()[0]['loc']})") from exc
        if ex.id in seen:
            raise GoldenError(f"{path.name} line {n}: id {ex.id} is used twice")
        seen.add(ex.id)
        out.append(ex)
    return out


def coverage_problems(examples: Sequence[Example]) -> list[str]:
    """Every category needs at least MIN_PER_CATEGORY examples."""
    counts: Counter[str] = Counter(str(e.category) for e in examples)
    return [f"{c}: {counts[c]} of {MIN_PER_CATEGORY}" for c in CATEGORIES if counts[c] < MIN_PER_CATEGORY]


@dataclass
class Report:
    items: int
    metrics: dict[str, float]
    passed: bool
    mistakes: list[dict[str, Any]] = field(default_factory=list)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)

    def table(self) -> str:
        lines = ["| Metric | Value | Threshold | Result |", "|---|---|---|---|"]
        for key, value in self.metrics.items():
            limit = THRESHOLDS[key]
            ok = value <= limit if key == "harmful_automatic" else value >= limit
            shown = f"{value:.0f}" if key == "harmful_automatic" else f"{value:.0%}"
            want = f"{limit:.0f}" if key == "harmful_automatic" else f"{limit:.0%}"
            lines.append(f"| {key.replace('_', ' ')} | {shown} | {want} | {'pass' if ok else '**fail**'} |")
        for m in self.mistakes:
            lines.append(f"- {m['id']}: expected {m['expected']}, got {m['got']} ({m['confidence']:.2f}) {m['note']}")
        return "\n".join(lines)


def evaluate(examples: Sequence[Example], outputs: Sequence[ReplyClassification]) -> Report:
    """The metrics for one run; `outputs[i]` is the answer for `examples[i]`."""
    if len(examples) != len(outputs):
        raise ValueError("one output per example")
    right = 0
    unsub = unsub_caught = 0
    harmful = 0
    fields_checked = fields_right = 0
    confusion: dict[str, dict[str, int]] = {}
    mistakes: list[dict[str, Any]] = []
    for ex, out in zip(examples, outputs, strict=True):
        confusion.setdefault(ex.category, {}).setdefault(out.category, 0)
        confusion[ex.category][out.category] += 1
        if out.category == ex.category:
            right += 1
        else:
            mistakes.append(
                {
                    "id": ex.id,
                    "expected": ex.category,
                    "got": out.category,
                    "confidence": out.confidence,
                    "note": ex.note,
                }
            )
        if ex.category == "unsubscribe":
            unsub += 1
            unsub_caught += out.category == "unsubscribe"
        if out.category in AUTOMATIC and out.category != ex.category and out.confidence >= SAFE_CONFIDENCE:
            harmful += 1
        for want, got in ((ex.return_date, out.return_date), (ex.referral_email, out.referral_email)):
            if want is not None:
                fields_checked += 1
                fields_right += (got or "").lower() == want.lower()
    metrics = {
        "accuracy": right / len(examples) if examples else 0.0,
        "unsubscribe_recall": unsub_caught / unsub if unsub else 1.0,
        "harmful_automatic": float(harmful),
        "field_accuracy": fields_right / fields_checked if fields_checked else 1.0,
    }
    passed = all((metrics[k] <= v) if k == "harmful_automatic" else (metrics[k] >= v) for k, v in THRESHOLDS.items())
    return Report(len(examples), metrics, passed, mistakes, confusion)


Classifier = Callable[[Example], ReplyClassification]


def production(ai_classify: Classifier) -> Classifier:
    """What the replies phase does: the opt-out rule first, then the classifier, then the tidy step."""

    def classify(ex: Example) -> ReplyClassification:
        if opt_out_rule(ex.reply):
            return ReplyClassification(category="unsubscribe", confidence=1.0, summary="Asked us to stop writing.")
        return tidy_classification(ai_classify(ex), ex.reply, set())

    return classify


def run(classify: Classifier, examples: Sequence[Example] | None = None) -> Report:
    examples = list(examples) if examples is not None else load()
    return evaluate(examples, [production(classify)(ex) for ex in examples])


def router_classifier(router: Any, run_id: str | None = None) -> Classifier:
    """The live `classify_reply` task through the AI router."""
    from nument_engine.pipeline import ai

    def classify(ex: Example) -> ReplyClassification:
        return ai.call(router, "classify_reply", ex.inputs(), ReplyClassification, run_id=run_id).output

    return classify


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - live, by hand
    parser = argparse.ArgumentParser(description="classify_reply eval")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    examples = load()
    problems = coverage_problems(examples)
    if problems or args.dry_run:
        print(json.dumps({"examples": len(examples), "coverage_problems": problems}))
        return 1 if problems else 0
    import os

    from nument_engine.pipeline import ai
    from nument_engine.pipeline.runs import Options, run_context

    os.environ["APP_ENV"] = args.env
    with run_context("manual", Options(env=args.env)) as rc:
        report = run(router_classifier(ai.router_for(rc), rc.run_id), examples)
    print(report.table())
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
