"""The classify_reply eval set: the golden file, its coverage, the metrics and the production path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals import classify_reply as ev
from evals.golden import GoldenError

from nument_engine.models import ReplyClassification
from nument_engine.outreach.replies import opt_out_rule

from .pipeline_fakes import FakeRouter


def oracle(ex: ev.Example) -> ReplyClassification:
    return ReplyClassification(
        category=ex.category,
        confidence=0.95,
        summary=ex.note[:200] or "labelled",
        return_date=ex.return_date,
        referral_name=ex.referral_name,
        referral_email=ex.referral_email,
    )


def test_the_golden_file_is_valid_and_covers_every_category() -> None:
    examples = ev.load()
    assert len(examples) >= 40
    assert ev.coverage_problems(examples) == []
    assert {e.category for e in examples} == set(ev.CATEGORIES)
    text = (ev.GOLDEN_DIR / ev.FILE).read_text(encoding="utf-8")
    assert chr(0x2013) not in text and chr(0x2014) not in text
    for e in examples:
        if e.referral_email:
            assert e.referral_email in e.reply, e.id  # labels only use what the reply says
        assert "Team Nument" in e.our_last_email and "@" not in e.our_last_email


def test_bad_lines_are_named(tmp_path: Path) -> None:
    good = ev.load()[0].model_dump()
    (tmp_path / ev.FILE).write_text(json.dumps(good) + "\n" + json.dumps(good) + "\n", encoding="utf-8")
    with pytest.raises(GoldenError, match="line 2: id r01 is used twice"):
        ev.load(tmp_path)
    (tmp_path / ev.FILE).write_text(json.dumps({**good, "category": "maybe"}) + "\n", encoding="utf-8")
    with pytest.raises(GoldenError, match="line 1"):
        ev.load(tmp_path)
    (tmp_path / ev.FILE).write_text(json.dumps({**good, "mood": "happy"}) + "\n", encoding="utf-8")
    with pytest.raises(GoldenError, match="line 1"):
        ev.load(tmp_path)
    with pytest.raises(GoldenError, match="does not exist"):
        ev.load(tmp_path / "missing")


def test_a_perfect_classifier_passes() -> None:
    report = ev.run(oracle)
    assert report.passed and report.metrics["accuracy"] == 1.0 and report.mistakes == []
    assert "| accuracy | 100% | 85% | pass |" in report.table()


def test_a_missed_opt_out_fails_the_eval() -> None:
    examples = ev.load()

    def misses_one(ex: ev.Example) -> ReplyClassification:
        out = oracle(ex)
        if ex.id == "r36":  # "Not interested." is left to the classifier by the rule
            return out.model_copy(update={"category": "not_now"})
        return out

    flat_no = next(e for e in examples if e.id == "r36")
    assert flat_no.category == "unsubscribe" and not opt_out_rule(flat_no.reply)
    report = ev.run(misses_one, examples)
    assert not report.passed and report.metrics["unsubscribe_recall"] < 1.0
    assert report.confusion["unsubscribe"]["not_now"] == 1


def test_a_confident_wrong_automatic_action_fails_the_eval() -> None:
    def reopens(ex: ev.Example) -> ReplyClassification:
        out = oracle(ex)
        if ex.id == "r01":  # a founder asking for a call, read as an auto-reply
            return out.model_copy(update={"category": "out_of_office", "confidence": 0.9})
        return out

    report = ev.run(reopens)
    assert report.metrics["harmful_automatic"] == 1 and not report.passed
    unsure = ev.run(lambda ex: reopens(ex).model_copy(update={"confidence": 0.6}) if ex.id == "r01" else oracle(ex))
    assert unsure.metrics["harmful_automatic"] == 0  # below 0.85 a person checks it, nothing happens alone


def test_the_opt_out_rule_never_fires_on_a_reply_that_is_not_one() -> None:
    caught = [e for e in ev.load() if opt_out_rule(e.reply)]
    assert caught and all(e.category == "unsubscribe" for e in caught)


def test_the_live_runner_uses_the_router() -> None:
    examples = ev.load()[:5]
    router = FakeRouter(
        {"classify_reply": lambda inputs: oracle(next(e for e in examples if e.reply == inputs["reply"]))}
    )
    report = ev.run(ev.router_classifier(router), examples)
    assert report.items == 5 and report.passed
    assert all(
        c.task == "classify_reply" and set(c.inputs) == {"our_last_email", "reply", "subject"} for c in router.calls
    )
