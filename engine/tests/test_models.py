"""Shared names (A.12) match the database, and the AI output models (A.13.1) behave."""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import ValidationError

from nument_engine import models
from nument_engine.models import (
    AI_OUTPUT_MODELS,
    AI_TASKS,
    FactsExtraction,
    LeadJudgement,
    MessageCheck,
    MessageDraft,
    SignalClassification,
    grade_for,
    make_test_group,
)

from .helpers import Conn


def _allowed(conn: Conn, table: str, column: str) -> set[str]:
    """Values allowed by the `column in (...)` CHECK constraint on public.<table>."""
    for row in conn.execute(
        "select pg_get_constraintdef(oid) as def from pg_constraint where conrelid = %s::regclass and contype = 'c'",
        [f"public.{table}"],
    ).fetchall():
        definition: str = row["def"]
        if re.search(rf"\(\(?{column} = ANY", definition):
            return set(re.findall(r"'([^']+)'::text", definition))
    raise AssertionError(f"no CHECK constraint on {table}.{column}")


@pytest.mark.parametrize(
    ("table", "column", "values"),
    [
        ("segments", "domain", models.DOMAINS),
        ("leads", "stage", models.STAGES),
        ("leads", "pitch_mode", models.PITCH_MODES),
        ("leads", "channel", models.CHANNELS),
        ("signals", "type", models.SIGNAL_TYPES),
        ("signals", "category", models.SIGNAL_CATEGORIES),
        ("businesses", "status", models.BUSINESS_STATUSES),
        ("contacts", "phone_type", models.PHONE_TYPES),
        ("contacts", "source", models.CONTACT_SOURCES),
        ("activities", "source", models.ACTIVITY_SOURCES),
        ("activities", "type", models.ACTIVITY_TYPES),
        ("runs", "kind", models.RUN_KINDS),
        ("runs", "status", models.RUN_STATUSES),
        ("costs", "provider", models.COST_PROVIDERS),
        ("llm_batches", "provider", models.LLM_PROVIDERS),
        ("llm_batches", "status", models.BATCH_STATUSES),
        ("profiles", "role", models.USER_ROLES),
        ("source_records", "source", models.SOURCE_NAMES),
    ],
)
def test_contract_names_match_the_database(db_conn: Conn, table: str, column: str, values: tuple[str, ...]) -> None:
    assert _allowed(db_conn, table, column) == set(values)


@pytest.mark.parametrize("table", ["inbox_posts", "custom_queries"])
def test_inbox_and_custom_query_statuses_follow_a13_5(db_conn: Conn, table: str) -> None:
    """A.13.5 rule 9 statuses are allowed; the database also keeps the older Step 2 and Step 7 values."""
    assert set(models.INBOX_STATUSES) <= _allowed(db_conn, table, "status")


def test_trigger_owned_activity_types() -> None:
    assert {"lead_created", "stage_change", "grade_change", "message_edited"} == models.TRIGGER_ACTIVITY_TYPES
    assert set(models.ACTIVITY_TYPES) > models.TRIGGER_ACTIVITY_TYPES


def test_stage_tables_are_consistent() -> None:
    assert set(models.STAGE_LABELS) == set(models.STAGES)
    assert set(models.STAGES) > models.CLOSED_STAGES
    assert models.OPEN_STAGES == ("new", "contacted", "talking", "discovery_booked", "discovery_done", "proposal_sent")
    assert set(models.SIGNAL_CATEGORY) == set(models.SIGNAL_TYPES)
    assert set(models.SIGNAL_CATEGORY.values()) == set(models.SIGNAL_CATEGORIES)


@pytest.mark.parametrize(
    ("total", "grade"), [(100, "A"), (70, "A"), (69.99, "B"), (55, "B"), (54, "C"), (40, "C"), (39.9, "D"), (0, "D")]
)
def test_grade_thresholds(total: float, grade: str) -> None:
    assert grade_for(total) == grade


def test_test_group_format() -> None:
    assert make_test_group("clinics-in", "visible_pain", "missed_calls") == "clinics-in:visible_pain:missed_calls"
    loud: Any = "loud"  # not a PitchMode: must be refused at runtime too
    with pytest.raises(ValueError, match="pitch mode"):
        make_test_group("clinics-in", loud, "missed_calls")
    with pytest.raises(ValueError, match="must not contain"):
        make_test_group("clinics-in", "fit_only", "a:b")


def test_every_ai_task_has_an_output_model() -> None:
    assert set(AI_OUTPUT_MODELS) == set(AI_TASKS)
    for model in AI_OUTPUT_MODELS.values():
        assert model.model_json_schema()["type"] == "object"


def test_signal_classification_follows_step_7() -> None:
    parsed = SignalClassification.model_validate(
        {
            "is_relevant": True,
            "role_category": "frontdesk",
            "employer_name": "Calmveda Clinic",
            "employer_website": None,
            "employer_domain": "clinics",
            "city": "Pune",
            "evidence_quote": "We are hiring a front desk executive",
            "confidence": 0.9,
        }
    )
    assert parsed.role_category == "frontdesk"
    with pytest.raises(ValidationError):
        SignalClassification.model_validate({**parsed.model_dump(), "confidence": 1.5})


def test_facts_extraction_requires_real_quotes() -> None:
    empty = FactsExtraction.model_validate({})
    assert empty.phones == [] and empty.branches is None
    ok = FactsExtraction.model_validate(
        {"branches": {"count": 3, "quote": "Our 3 branches in Pune", "url": "https://example.com/about"}}
    )
    assert ok.branches is not None and ok.branches.count == 3
    with pytest.raises(ValidationError):
        FactsExtraction.model_validate({"branches": {"count": 3, "quote": "3", "url": "https://example.com"}})
    with pytest.raises(ValidationError):
        FactsExtraction.model_validate(
            {"phones": [{"number": "1", "belongs_to": "business", "quote": "q" * 5, "url": "u"}] * 7}
        )


def test_judgement_message_and_check_shapes() -> None:
    judgement = LeadJudgement.model_validate(
        {
            "judge_grade": "B",
            "cited_ids": ["F1"],
            "judge_note": "Hiring a receptionist now.",
            "best_angle": "missed_calls",
            "confidence": 0.7,
        }
    )
    assert judgement.risks == []
    with pytest.raises(ValidationError):
        LeadJudgement.model_validate({**judgement.model_dump(), "cited_ids": []})
    draft = MessageDraft.model_validate(
        {
            "message": "m",
            "message_alt": "a",
            "followup_d3": "d3",
            "followup_d7": "d7",
            "claims": [{"text": "hiring a receptionist", "ids": ["S1"]}],
        }
    )
    assert draft.email_subject is None
    with pytest.raises(ValidationError):
        MessageCheck.model_validate({"score": 11})
