"""Step 11.10 judge guardrails, enforced in code (no database)."""

from __future__ import annotations

from typing import Any

import pytest

from nument_engine.models import LeadJudgement
from nument_engine.pipeline.judge import angle_fits, clamp, clean_note, review, select_for_judging, sentence_count
from nument_engine.pipeline.lint import ClaimContext
from nument_engine.segments import load_segments

SEG = load_segments()["clinics-in"]
CTX = ClaimContext(
    known_ids={"f1": "f1", "s1": "s1"},
    evidence_text={"f1": "branches 2 Baner and Aundh", "s1": "hiring frontdesk front desk executive 5 days ago"},
    trusted_words={"glow", "skin", "studio", "pune", "baner"},
    trusted_numbers={"420"},
)
RULE_NOTE = "Hiring front desk staff on Apna 5 days ago, and 420 Google reviews."


def judgement(**over: Any) -> LeadJudgement:
    values: dict[str, Any] = {
        "judge_grade": "A",
        "cited_ids": ["S1"],
        "best_angle": "frontdesk_load",
        "judge_note": "Hiring a front desk executive 5 days ago with 420 Google reviews.",
        "risks": [],
        "confidence": 0.7,
    }
    values.update(over)
    return LeadJudgement(**values)


def run_review(j: LeadJudgement, rule_grade: str = "B", mode: str = "visible_pain") -> Any:
    return review(
        j,
        rule_grade=rule_grade,
        rule_angle="missed_calls",
        rule_note=RULE_NOTE,
        mode=mode,
        kept_types={"hiring_frontdesk", "review_pain"},
        seg=SEG,
        ctx=CTX,
    )


@pytest.mark.parametrize(
    ("rule", "proposed", "final"),
    [("B", "A", "A"), ("B", "D", "C"), ("C", "A", "B"), ("A", "D", "B"), ("D", "A", "C"), ("B", "B", "B")],
)
def test_grade_moves_at_most_one_step(rule: str, proposed: str, final: str) -> None:
    assert clamp(rule, proposed) == final
    assert run_review(judgement(judge_grade=proposed), rule_grade=rule).final_grade == final


def test_a_good_judgement_is_kept() -> None:
    v = run_review(judgement())
    assert (v.final_grade, v.judge_grade, v.angle, v.discarded, v.note_replaced) == (
        "A",
        "A",
        "frontdesk_load",
        None,
        None,
    )
    assert v.note.startswith("Hiring a front desk executive") and v.cited == ["s1"]


def test_a_fake_citation_discards_the_whole_judgement() -> None:
    v = run_review(judgement(cited_ids=["S1", "Fdeadbeef"]))
    assert (v.final_grade, v.judge_grade, v.note, v.discarded) == ("B", None, RULE_NOTE, "bad_citation")


@pytest.mark.parametrize(
    "note",
    [
        "Hiring a front desk executive with 12 branches across Pune.",  # invented number
        "Hiring a front desk executive at the Kothrud Wellness Centre.",  # invented name
        "Busy clinic. Hiring now. Many reviews. Great fit.",  # more than two sentences
    ],
)
def test_bad_notes_fall_back_to_the_rule_note(note: str) -> None:
    v = run_review(judgement(judge_note=note))
    assert v.note == RULE_NOTE and v.note_replaced in ("new_facts", "shape") and v.final_grade == "A"


def test_dashes_are_cleaned_and_dr_does_not_count_as_a_sentence() -> None:
    assert (
        clean_note("Hiring a front desk executive \u2014 420 reviews") == "Hiring a front desk executive, 420 reviews"
    )
    assert sentence_count("Dr. Rao is hiring. Strong fit.") == 2


def test_angle_must_be_a_segment_angle_that_fits_the_signals() -> None:
    assert angle_fits(SEG, "missed_calls", "visible_pain", {"review_pain"})
    assert not angle_fits(SEG, "missed_calls", "visible_pain", {"hiring_frontdesk"})
    assert not angle_fits(SEG, "invented_angle", "visible_pain", {"review_pain"})
    assert angle_fits(SEG, "build_what_they_asked", "stated_need", {"public_ask"})
    assert not angle_fits(SEG, "frontdesk_load", "stated_need", {"public_ask", "hiring_frontdesk"})
    assert angle_fits(SEG, "after_hours_enquiries", "fit_only", set())
    assert run_review(judgement(best_angle="slow_site")).angle == "missed_calls"


def test_selection_takes_the_best_half_and_every_a() -> None:
    rows = [
        {
            "segment_id": "clinics-in",
            "business_id": f"b{i}",
            "total": 40 + i,
            "reasons": {"rule_grade": "A" if i == 0 else "B"},
        }
        for i in range(6)
    ]
    rows.append({"segment_id": "realestate-in", "business_id": "r1", "total": 30, "reasons": {"rule_grade": "C"}})
    picked = [r["business_id"] for r in select_for_judging(rows, {"clinics-in": 0.5, "realestate-in": 0.5})]
    assert picked == ["b5", "b4", "b3", "b0", "r1"]
