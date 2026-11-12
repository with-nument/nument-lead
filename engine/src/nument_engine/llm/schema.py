"""JSON schemas for structured output, and parsing of model answers back into pydantic models (Step 4.7.1).

Providers constrain generation with a JSON schema, but each accepts a different subset:

- Gemini compiles the schema into a grammar with limits on states and nesting. `maxItems`, `minimum` and
  long property lists multiply the states, and very large schemas are refused with 400 INVALID_ARGUMENT.
- OpenAI strict mode needs every property in `required`, `additionalProperties: false` everywhere, and
  optional fields written as nullable.

So the router sends one simplified schema to both (`provider_schema`): references inlined, every property
required, optional fields nullable, and bounds (item counts, lengths, numeric ranges) moved into the field
descriptions as hints. The full pydantic model, bounds included, still validates every answer in code;
`parse_output` first trims lists and strings that are only too long and clamps numbers into range, which
fixes the common small overshoots without paying for a repair call.
"""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ValidationError

from .types import OutputInvalid

JSON = dict[str, Any]

_DROP = ("title", "default", "examples", "$schema", "uniqueItems", "multipleOf", "format", "pattern")
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)
_STEP_REF = re.compile(r"\s*\((?:Steps?|A\.)\s*[0-9][0-9A-Za-z., and]*\)")  # "(Step 9.12)" means nothing to a model


def _resolve(node: Any, defs: dict[str, JSON], stack: tuple[str, ...] = ()) -> Any:
    """Inline every `$ref` into `#/$defs/...`. Our models are not recursive; a cycle is a bug."""
    if isinstance(node, list):
        return [_resolve(item, defs, stack) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in stack:
            raise ValueError(f"recursive schema through {name!r} is not supported")
        target = {k: v for k, v in node.items() if k != "$ref"}
        return _resolve({**copy.deepcopy(defs[name]), **target}, defs, (*stack, name))
    return {k: _resolve(v, defs, stack) for k, v in node.items() if k != "$defs"}


def _bounds_hint(node: JSON) -> str:
    hints: list[str] = []
    lo, hi = node.get("minItems"), node.get("maxItems")
    if hi is not None:
        hints.append(f"At most {hi} items." if not lo else f"{lo} to {hi} items.")
    elif lo:
        hints.append(f"At least {lo} item{'s' if lo != 1 else ''}.")
    lo, hi = node.get("minLength"), node.get("maxLength")
    if hi is not None:
        hints.append(f"At most {hi} characters." if not lo else f"{lo} to {hi} characters.")
    elif lo:
        hints.append(f"At least {lo} characters.")
    lo = node.get("minimum", node.get("exclusiveMinimum"))
    hi = node.get("maximum", node.get("exclusiveMaximum"))
    if lo is not None and hi is not None:
        hints.append(f"Between {lo} and {hi}.")
    elif lo is not None:
        hints.append(f"At least {lo}.")
    elif hi is not None:
        hints.append(f"At most {hi}.")
    return " ".join(hints)


_BOUNDS = (
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
)


def _simplify(node: Any) -> Any:
    """Simplify one schema node. Keywords are dropped by name, so a `properties` map (whose keys are field
    names such as `title` or `format`, not keywords) is walked separately and never filtered."""
    if isinstance(node, list):
        return [_simplify(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: JSON = {}
    hint = _bounds_hint(node)
    for key, value in node.items():
        if key in _DROP or key in _BOUNDS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: _simplify(prop) for name, prop in value.items()}
        else:
            out[key] = _simplify(value)
    if "description" in out:
        out["description"] = _STEP_REF.sub("", out["description"]).strip()
    if hint:
        desc = out.get("description", "").strip()
        out["description"] = f"{desc.rstrip('.')}. {hint}" if desc else hint

    # Optional fields arrive as anyOf [X, {"type": "null"}]. A plain scalar becomes {"type": [T, "null"]};
    # enums and objects keep the anyOf, which both providers accept.
    if "anyOf" in out:
        branches = out["anyOf"]
        nulls = [b for b in branches if b == {"type": "null"}]
        others = [b for b in branches if b != {"type": "null"}]
        if nulls and len(others) == 1:
            other = others[0]
            simple = isinstance(other.get("type"), str) and other["type"] not in ("object", "array")
            if simple and "enum" not in other:
                merged = {k: v for k, v in out.items() if k != "anyOf"}
                merged.update(other)
                merged["type"] = [other["type"], "null"]
                if "description" in out and "description" in other and out["description"] != other["description"]:
                    merged["description"] = f"{out['description']} {other['description']}"
                return merged
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out


@lru_cache(maxsize=64)
def _provider_schema_cached(model: type[BaseModel]) -> str:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    simplified = _simplify(_resolve(raw, defs))
    simplified.pop("description", None)  # the model's docstring is for engineers, the prompt explains the task
    return json.dumps(simplified, sort_keys=False)


def provider_schema(model: type[BaseModel]) -> JSON:
    """The simplified JSON schema sent to Gemini and OpenAI for this model (a fresh copy each time)."""
    result: JSON = json.loads(_provider_schema_cached(model))
    return result


def to_strict_schema(model: type[BaseModel]) -> JSON:
    """OpenAI strict-mode schema (Step 4.7.1). Same as provider_schema: every property required, no extras."""
    return provider_schema(model)


# ---------------------------------------------------------------------------
# Parsing answers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _full_schema(model: type[BaseModel]) -> str:
    raw = model.model_json_schema()
    return json.dumps(_resolve(raw, raw.get("$defs", {})))


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return cut[:space].rstrip() if space > limit * 0.6 else cut


def _coerce(value: Any, schema: JSON) -> Any:
    """Trim over-long lists and strings, clamp numbers, following the full (bounded) schema."""
    if "anyOf" in schema:
        if value is None:
            return None
        for branch in schema["anyOf"]:
            if branch.get("type") == "null":
                continue
            kind = branch.get("type")
            matches = (
                (kind == "object" and isinstance(value, dict))
                or (kind == "array" and isinstance(value, list))
                or (kind == "string" and isinstance(value, str))
                or (kind in ("number", "integer") and isinstance(value, int | float) and not isinstance(value, bool))
            )
            if matches:
                return _coerce(value, branch)
        return value
    kind = schema.get("type")
    if kind == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: _coerce(v, props[k]) if k in props else v for k, v in value.items()}
    if kind == "array" and isinstance(value, list):
        items = schema.get("items", {})
        out = [_coerce(v, items) for v in value]
        limit = schema.get("maxItems")
        return out[:limit] if isinstance(limit, int) else out
    if kind == "string" and isinstance(value, str):
        limit = schema.get("maxLength")
        return _cut(value, limit) if isinstance(limit, int) else value
    if kind in ("number", "integer") and isinstance(value, int | float) and not isinstance(value, bool):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if lo is not None and value < lo:
            return lo
        if hi is not None and value > hi:
            return hi
    return value


def extract_json_text(text: str) -> str:
    """The JSON part of an answer: strips code fences and any text around the outermost object."""
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    if stripped.startswith("{"):
        return stripped
    start, end = stripped.find("{"), stripped.rfind("}")
    return stripped[start : end + 1] if start != -1 and end > start else stripped


def parse_output(text: str, model: type[BaseModel]) -> BaseModel:
    """Parse and validate a model answer. Raises OutputInvalid with errors a repair prompt can quote."""
    if not text or not text.strip():
        raise OutputInvalid("empty answer")
    try:
        data = json.loads(extract_json_text(text))
    except json.JSONDecodeError as exc:
        raise OutputInvalid(f"not valid JSON: {exc.msg} at character {exc.pos}") from None
    return validate_output(data, model)


def validate_output(data: Any, model: type[BaseModel]) -> BaseModel:
    """Validate already-decoded JSON (coerced first). Raises OutputInvalid."""
    coerced = _coerce(data, json.loads(_full_schema(model)))
    try:
        return model.model_validate(coerced)
    except ValidationError as exc:
        raise OutputInvalid(describe_errors(exc)) from None


def describe_errors(exc: ValidationError, limit: int = 6) -> str:
    """Short, model-readable list of validation errors (no input values, which may be long)."""
    parts = []
    for err in exc.errors()[:limit]:
        where = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{where}: {err['msg']}")
    more = len(exc.errors()) - limit
    if more > 0:
        parts.append(f"and {more} more")
    return "; ".join(parts)
