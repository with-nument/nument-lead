"""Load, version and render the prompt files in `engine/prompts` (Step 4.9).

File format::

    ---
    task: extract_facts
    version: 1
    output: FactsExtraction          # model in nument_engine.models, or null for free text
    inputs: [business_name, pages]   # required inputs; anything else is optional
    description: one line
    ---
    [system]
    ...Jinja2 template...
    [user]
    ...Jinja2 template...

Every template can use `{{ common_rules }}` (the shared rules in `_common_rules.md`) and `{{ today }}` (the
IST date). Undefined variables are errors, so optional inputs must use `| default(...)`.
Any wording change bumps `version`; every stored AI output records `provider:model#task.vN` (see `tag`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, Template

_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_SECTION = re.compile(r"^\[(system|user)\]\s*$", re.M)
COMMON_RULES_FILE = "_common_rules.md"


def _tojson(value: Any) -> str:
    """Plain JSON for prompts (Jinja's built-in tojson escapes <, > and & for HTML)."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _environment() -> Environment:
    env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = _tojson
    return env


_ENV = _environment()


def prompts_dir() -> Path:
    from ..settings import get_settings

    return get_settings().prompts_dir


@dataclass(frozen=True)
class Prompt:
    """One parsed prompt file."""

    name: str
    task: str
    version: int
    output: str | None
    inputs: tuple[str, ...]
    description: str
    system_template: Template
    user_template: Template

    def render(self, **inputs: Any) -> tuple[str, str]:
        """(system, user) text. Raises KeyError when a required input is missing."""
        missing = [name for name in self.inputs if name not in inputs]
        if missing:
            raise KeyError(f"{self.task} ({self.name}): missing inputs {', '.join(missing)}")
        context = {"common_rules": common_rules(), "today": _today(), **inputs}
        system = self.system_template.render(**context).strip()
        user = self.user_template.render(**context).strip()
        return system, user


def _today() -> str:
    from ..budget import ist_today

    return ist_today().isoformat()


def parse(text: str, name: str) -> Prompt:
    match = _FRONT.match(text)
    if not match:
        raise ValueError(f"{name}: missing front matter between --- lines")
    meta = yaml.safe_load(match.group(1)) or {}
    for key in ("task", "version"):
        if key not in meta:
            raise ValueError(f"{name}: front matter needs {key!r}")
    body = match.group(2)
    parts = _SECTION.split(body)
    # parts: [before, "system", text, "user", text]
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    if set(sections) != {"system", "user"} or parts[0].strip():
        raise ValueError(f"{name}: needs exactly one [system] and one [user] section, and nothing before them")
    version = meta["version"]
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"{name}: version must be a positive integer")
    inputs = meta.get("inputs") or []
    if not isinstance(inputs, list) or not all(isinstance(i, str) for i in inputs):
        raise ValueError(f"{name}: inputs must be a list of names")
    return Prompt(
        name=name,
        task=str(meta["task"]),
        version=version,
        output=meta.get("output"),
        inputs=tuple(inputs),
        description=str(meta.get("description", "")),
        system_template=_ENV.from_string(sections["system"].strip()),
        user_template=_ENV.from_string(sections["user"].strip()),
    )


@lru_cache(maxsize=64)
def _load(path: str) -> Prompt:
    file = Path(path)
    return parse(file.read_text(encoding="utf-8"), file.name)


def load(name: str, directory: Path | None = None) -> Prompt:
    """Parse a prompt file once per process."""
    path = (directory or prompts_dir()) / name
    if not path.is_file():
        raise FileNotFoundError(f"prompt file {path} does not exist")
    return _load(str(path))


@lru_cache(maxsize=4)
def _common_rules(path: str) -> str:
    file = Path(path)
    return file.read_text(encoding="utf-8").strip() if file.is_file() else ""


def common_rules(directory: Path | None = None) -> str:
    return _common_rules(str((directory or prompts_dir()) / COMMON_RULES_FILE))


def tag(provider: str, model: str, prompt: Prompt) -> str:
    """Stored with every AI output (facts.model, leads.message_model, scores.judge_model).

    Example: 'gemini:gemini-3.8-flash#extract_facts.v1'.
    """
    return f"{provider}:{model}#{prompt.task}.v{prompt.version}"


def clear_cache() -> None:
    _load.cache_clear()
    _common_rules.cache_clear()
