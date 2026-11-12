"""tasks.yaml loading and validation (Step 4.2.3, 4.13 test 12), prompt files (4.9) and schemas (4.7.1, test 18)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from nument_engine.llm import prompts
from nument_engine.llm.config import ConfigError, ModelRef, ModelSpec, load_registry
from nument_engine.llm.health import SMOKE_INPUTS
from nument_engine.llm.schema import parse_output, provider_schema, to_strict_schema
from nument_engine.llm.types import OutputInvalid
from nument_engine.models import AI_OUTPUT_MODELS, AI_TASKS, FactsExtraction, LeadJudgement
from nument_engine.settings import ENGINE_DIR

TASKS_YAML = ENGINE_DIR / "config" / "tasks.yaml"

# ---------------------------------------------------------------------------
# tasks.yaml
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["balanced", "best", "lean"])
def test_every_tier_loads_and_gemini_can_run_every_task(tier: str) -> None:
    registry = load_registry(tier)
    assert set(registry.tasks) == set(AI_TASKS)
    for name, cfg in registry.tasks.items():
        assert any(ref.provider == "gemini" for ref in cfg.chain), name
        assert cfg.schema_model is AI_OUTPUT_MODELS[name]
        for ref in cfg.chain:
            assert ref in registry.specs


def test_balanced_tier_matches_the_plan() -> None:
    registry = load_registry("balanced")
    expect = {
        "classify_signal": ("gemini-3.5-flash-lite", "sync", 4),
        "extract_facts": ("gemini-3.8-flash", "batch", 3),
        "judge_lead": ("gemini-4-argon", "sync", 2),
        "write_message": ("gpt-5-mini", "sync", 1),
        "check_message": ("gemini-3.8-flash", "sync", 1),
        "grounded_search": ("gemini-3.8-flash", "sync", 5),
        "weekly_audit": ("gemini-4-argon", "sync", 6),
    }
    for task, (model, mode, priority) in expect.items():
        cfg = registry.task(task)
        assert (cfg.primary.model, cfg.mode, cfg.priority) == (model, mode, priority), task
    assert registry.task("write_message").fallbacks[0] == ModelRef(provider="gemini", model="gemini-3.8-flash")
    assert registry.task("grounded_search").tools == ("web_search",)


def test_tiers_inherit_and_override() -> None:
    best = load_registry("best")
    lean = load_registry("lean")
    assert best.task("judge_lead").primary.model == "gemini-4-carbon"
    assert best.task("classify_news").primary == load_registry("balanced").task("classify_news").primary
    assert lean.task("extract_facts").primary.model == "gemini-3.5-flash-lite"
    assert lean.task("extract_facts").mode == "batch"


def _variant(tmp_path: Path, change: Any) -> Path:
    data = yaml.safe_load(TASKS_YAML.read_text())
    change(data)
    path = tmp_path / "tasks.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_a_chain_without_gemini_is_rejected(tmp_path: Path) -> None:
    def openai_only(data: dict[str, Any]) -> None:
        data["tiers"]["balanced"]["write_message"]["fallbacks"] = ["o_nano"]

    with pytest.raises(ConfigError, match="needs at least one gemini model"):
        load_registry("balanced", _variant(tmp_path, openai_only))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["models"]["g_lite"].update(model="gemini-0-unpriced"), "no price in prices.yaml"),
        (lambda d: d["tiers"]["balanced"]["judge_lead"].update(schema="MessageCheck"), "schema must be LeadJudgement"),
        (lambda d: d["tiers"]["balanced"]["judge_lead"].update(prompt="check_message.md"), "is for task"),
        (lambda d: d["tiers"]["balanced"]["judge_lead"].update(primary="g_nope"), "unknown model short name"),
        (lambda d: d["tiers"]["balanced"].pop("weekly_audit"), "missing tasks: weekly_audit"),
        (lambda d: d["tiers"]["balanced"]["judge_lead"].update(priority=9), "priority"),
        (lambda d: d["tiers"]["lean"]["overrides"].update(summarise={"primary": "g_lite"}), "unknown task"),
        (lambda d: d["tiers"]["balanced"]["grounded_search"].pop("structure_with"), "structure_with"),
    ],
    ids=["price", "schema", "prompt", "short-name", "missing-task", "priority", "override", "structure"],
)
def test_config_mistakes_fail_at_startup(tmp_path: Path, change: Any, message: str) -> None:
    tier = "lean" if message == "unknown task" else "balanced"
    with pytest.raises(ConfigError, match=message):
        load_registry(tier, _variant(tmp_path, change))


def test_thinking_levels_map_to_what_each_model_accepts() -> None:
    flash = ModelSpec(provider="gemini", model="gemini-3.8-flash", thinking_levels=("low", "medium", "high"))
    lite = ModelSpec(
        provider="gemini", model="gemini-3.5-flash-lite", thinking_levels=("minimal", "low", "medium", "high")
    )
    none = ModelSpec(provider="gemini", model="x", thinking_levels=())
    only_high = ModelSpec(provider="gemini", model="y", thinking_levels=("medium", "high"))
    assert flash.thinking_level("off") == "low" and lite.thinking_level("off") == "minimal"
    assert flash.thinking_level("medium") == "medium" and none.thinking_level("low") is None
    assert only_high.thinking_level("low") == "medium" and only_high.thinking_level("off") == "medium"


# ---------------------------------------------------------------------------
# Prompt files
# ---------------------------------------------------------------------------


def test_every_prompt_file_parses_and_renders_its_smoke_inputs() -> None:
    registry = load_registry("balanced")
    for name, cfg in registry.tasks.items():
        prompt = prompts.load(cfg.prompt)
        assert prompt.task == name and prompt.version >= 1
        system, user = prompt.render(**SMOKE_INPUTS[name])
        assert system and user
        assert "{{" not in system + user and "{%" not in system + user
        assert '{"' not in system, f"{cfg.prompt}: output format comes from the schema, not a JSON example"


def test_common_rules_and_today_are_available() -> None:
    system, user = prompts.load("classify_signal.md").render(**SMOKE_INPUTS["classify_signal"])
    assert "Use only the information given to you below" in system
    _, user = prompts.load("grounded_public_asks.md").render(**SMOKE_INPUTS["grounded_search"])
    assert "Today is 20" in user


def test_missing_inputs_and_optional_inputs() -> None:
    prompt = prompts.load("classify_signal.md")
    inputs = dict(SMOKE_INPUTS["classify_signal"])
    with pytest.raises(KeyError, match="missing inputs url"):
        prompt.render(**{k: v for k, v in inputs.items() if k != "url"})
    inputs.pop("title")
    _, user = prompt.render(**inputs)
    assert "Title:" not in user
    _, user = prompt.render(**inputs, title="Receptionist", posted_date="2026-11-10")
    assert "Title: Receptionist" in user and "Posted: 2026-11-10" in user


def test_extract_prompt_wraps_pages_so_urls_can_be_cited() -> None:
    _, user = prompts.load("extract_facts.md").render(**SMOKE_INPUTS["extract_facts"])
    assert "### PAGE 1\nURL: https://example.com/\nTEXT:\n" in user
    assert "### END PAGE 2" in user


def test_tag_format() -> None:
    prompt = prompts.load("judge_lead.md")
    assert prompts.tag("gemini", "gemini-4-argon", prompt) == "gemini:gemini-4-argon#judge_lead.v1"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[system]\nx\n[user]\ny", "missing front matter"),
        ("---\ntask: t\n---\n[system]\nx\n[user]\ny", "needs 'version'"),
        ("---\ntask: t\nversion: 1\n---\n[system]\nx", "exactly one"),
        ("---\ntask: t\nversion: 0\n---\n[system]\nx\n[user]\ny", "positive integer"),
    ],
)
def test_bad_prompt_files_are_refused(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        prompts.parse(text, "bad.md")


def test_tojson_filter_keeps_text_readable() -> None:
    prompt = prompts.parse(
        "---\ntask: t\nversion: 1\ninputs: [v]\n---\n[system]\ns\n[user]\n{{ v | tojson }}", "inline.md"
    )
    assert prompt.render(v={"name": "Dr. <Mehta> & Sons", "city": "पुणे"})[1] == (
        '{"name": "Dr. <Mehta> & Sons", "city": "पुणे"}'
    )


# ---------------------------------------------------------------------------
# Schemas and parsing
# ---------------------------------------------------------------------------


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += _walk(value)
    elif isinstance(node, list):
        for value in node:
            found += _walk(value)
    return found


@pytest.mark.parametrize("model", list(AI_OUTPUT_MODELS.values()), ids=list(AI_OUTPUT_MODELS))
def test_provider_schemas_are_strict_and_simple(model: Any) -> None:
    schema = provider_schema(model)
    text = json.dumps(schema)
    for banned in ("$ref", "$defs", "maxItems", "minItems", "maxLength", "minLength", "minimum", "maximum", "default"):
        assert f'"{banned}"' not in text, banned
    for node in _walk(schema):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])


def _fields_match(model: Any, schema: dict[str, Any], path: str) -> None:
    """Every pydantic field appears in the provider schema, recursively (a field may be named like a keyword)."""
    from typing import get_args

    from pydantic import BaseModel

    props = schema.get("properties", {})
    assert set(props) == set(model.model_fields), path
    for name, field in model.model_fields.items():
        node = props[name]
        node = next((b for b in node.get("anyOf", []) if b.get("type") != "null"), node)
        node = node.get("items", node)
        inner = [a for a in (field.annotation, *get_args(field.annotation)) if isinstance(a, type)]
        inner += [b for a in get_args(field.annotation) for b in get_args(a) if isinstance(b, type)]
        for candidate in inner:
            if issubclass(candidate, BaseModel):
                _fields_match(candidate, node, f"{path}.{name}")


@pytest.mark.parametrize("model", list(AI_OUTPUT_MODELS.values()), ids=list(AI_OUTPUT_MODELS))
def test_provider_schema_keeps_every_field(model: Any) -> None:
    """Regression: a field named `title` (RoleFact.title) was dropped as if it were the `title` keyword."""
    _fields_match(model, provider_schema(model), model.__name__)


def test_role_fact_title_is_in_the_extraction_schema() -> None:
    item = provider_schema(FactsExtraction)["properties"]["careers_roles"]["items"]
    assert item["required"] == ["quote", "url", "title", "category"]


def test_strict_schema_for_lead_judgement() -> None:
    """Plan test 18: additionalProperties false everywhere and every field required."""
    schema = to_strict_schema(LeadJudgement)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["judge_grade", "cited_ids", "judge_note", "best_angle", "risks", "confidence"]
    assert "At most 3 items" in schema["properties"]["risks"]["description"]
    assert schema["properties"]["confidence"]["description"] == "Between 0 and 1."


def test_optional_fields_become_nullable() -> None:
    facts = provider_schema(FactsExtraction)["properties"]
    assert facts["business_name"]["anyOf"][1] == {"type": "null"}
    person = facts["decision_makers"]["items"]["properties"]
    assert person["role"]["type"] == ["string", "null"]


def test_parse_output_accepts_fences_and_trims_small_overshoots() -> None:
    answer = {
        "judge_grade": "A",
        "cited_ids": ["F1"],
        "judge_note": "word " * 80,
        "best_angle": "missed_calls",
        "risks": ["a", "b", "c", "d", "e"],
        "confidence": 1.4,
    }
    parsed = parse_output("```json\n" + json.dumps(answer) + "\n```", LeadJudgement)
    assert isinstance(parsed, LeadJudgement)
    assert parsed.risks == ["a", "b", "c"] and parsed.confidence == 1
    assert len(parsed.judge_note) <= 280 and not parsed.judge_note.endswith(" ")
    assert parse_output("Here you go: " + json.dumps({**answer, "risks": []}) + " Done.", LeadJudgement)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty answer"),
        ("not json at all", "not valid JSON"),
        (json.dumps({"judge_grade": "E"}), "judge_grade"),
        (json.dumps({"judge_grade": "A", "cited_ids": [], "judge_note": "x", "best_angle": "y", "confidence": 1}),
         "cited_ids"),
    ],
)  # fmt: skip
def test_parse_output_errors_name_the_field(text: str, message: str) -> None:
    with pytest.raises(OutputInvalid, match=message):
        parse_output(text, LeadJudgement)


# Input dicts shaped exactly like the Steps 10 to 12 builders (pipeline/verify.py, judge.py, message.py):
# the same keys, including the extras those builders pass that a prompt may ignore.
_FACT = {
    "id": "f-1",
    "field": "branches",
    "value": {"count": 2},
    "quote": "Two branches in Baner",
    "url": "https://x.in/",
}
_SIGNAL = {
    "id": "s-1",
    "type": "hiring_frontdesk",
    "category": "visible_pain",
    "observed_at": "2026-11-07",
    "age_days": 5,
    "quote": "Hiring a patient coordinator",
    "url": "https://x.in/careers",
    "details": {},
    "source": "careers_watch",
}
PIPELINE_SHAPES: dict[str, dict[str, Any]] = {
    "verify_flagged": {
        "business_name": "Sunrise Dental",
        "field": "is_agency_or_vendor",
        "question": "Is this business an agency or software vendor that sells the same services as Nument?",
        "hint": "the footer says 'we build websites'",
        "facts": [{k: v for k, v in _FACT.items()}],
        "pages": [{"url": "https://x.in/", "text": "Sunrise Dental. Two branches in Baner."}],
    },
    "judge_lead": {
        "segment_id": "clinics-in",
        "domain": "clinics",
        "country": "in",
        "city": "Pune",
        "business_name": "Sunrise Dental",
        "packaged_outcome_name": "AI front desk",
        "pitch_mode": "visible_pain",
        "total": 64.0,
        "fit": 3,
        "can_pay": 2.0,
        "intent": 8.0,
        "reach": 1.0,
        "grade": "B",
        "reasons": {"fit": ["dental"], "can_pay": None, "intent": ["hiring"], "reach": 1.0},
        "rule_note": "",
        "facts": [_FACT],
        "signals": [_SIGNAL],
        "contacts_summary": ["mobile (website)"],
        "allowed_angles": ["missed_calls", "hire_complement"],
        "angles": [{"key": "missed_calls", "label": "Missed calls", "idea": "answer every call"}],
    },
    "write_message": {
        "segment_id": "clinics-in",
        "domain": "clinics",
        "country": "in",
        "country_name": "India",
        "city": "Pune",
        "pitch_mode": "visible_pain",
        "angle": "hire_complement",
        "angle_label": "Complement the hire",
        "angle_idea": "ship v1 now, their hire runs it",
        "packaged_outcome_name": "AI front desk",
        "packaged_outcome": "every enquiry answered in seconds",
        "business_name": "Sunrise Dental",
        "person_name": None,
        "person_role": None,
        "greeting": "Hi,",
        "seen_where": "your careers page",
        "need": "",
        "what_we_saw": "hiring a patient coordinator",
        "facts": [_FACT],
        "signals": [{**_SIGNAL, "summary": "hiring a patient coordinator 5 days ago"}],
        "associate_name": "Aditya",
        "channel": "whatsapp",
        "needs_email": False,
        "country_notes": "",
        "feedback": ["too long"],
        "avoid_openers": ["hi, saw your"],
        "avoid_questions": ["worth a look?"],
    },
    "check_message": {
        "message": "Hi, saw Sunrise Dental is hiring. We're Nument. Worth a look?",
        "message_alt": "Hi, quick one. We're Nument. Is the role still open?",
        "greeting": "Hi,",
        "business_name": "Sunrise Dental",
        "segment_id": "clinics-in",
        "country": "in",
        "pitch_mode": "visible_pain",
        "angle": "hire_complement",
        "facts": [_FACT],
        "signals": [{**_SIGNAL, "summary": "hiring a patient coordinator"}],
        "writer_model": "gemini-3.8-flash",
    },
}


@pytest.mark.parametrize("task", sorted(PIPELINE_SHAPES))
def test_prompts_render_with_the_pipeline_input_shapes(task: str) -> None:
    prompt = prompts.load(load_registry("balanced").task(task).prompt)
    system, user = prompt.render(**PIPELINE_SHAPES[task])
    assert "{{" not in system + user
    for fact_id in ("f-1",):
        assert fact_id in user
    if task == "write_message":
        assert "Greeting to start with: Hi," in user and "too long" in user and "worth a look?" in user
    if task == "judge_lead":
        assert "rule grade B" in user and "- fit:" in user and "Contacts we have: mobile (website)" in user


@pytest.mark.parametrize("task", ["judge_lead", "write_message", "check_message", "verify_flagged"])
def test_appendix_a_minimum_inputs_are_enough(task: str) -> None:
    """Only the required inputs: every optional part of the template must be guarded."""
    prompt = prompts.load(load_registry("balanced").task(task).prompt)
    minimal = {name: PIPELINE_SHAPES[task][name] for name in prompt.inputs}
    if task == "judge_lead":
        minimal["signals"] = [{"id": "s-1", "type": "news"}]
        minimal["facts"] = [{"id": "f-1", "field": "branches", "value": 2}]
    if task == "write_message":
        minimal["signals"] = [{"id": "s-1", "type": "news"}]
    prompt.render(**minimal)
