"""Task registry: load and validate `engine/config/tasks.yaml` for a tier (Step 4.2.3).

Validation runs at load time and fails loudly, so a bad config never reaches a paid call:

1. tiers with `inherit` start from their parent and apply `overrides` task by task;
2. short model names resolve through the `models:` map;
3. every chain contains a Gemini model (Gemini alone must be able to run every task);
4. every model has a price in prices.yaml;
5. every schema exists in `nument_engine.models` and matches the task's canonical model (A.13.1);
6. every prompt file exists, and its front matter names the same task and output model;
7. web-search tasks only use search-capable models, batch tasks have a batch-capable model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .. import models as models_module
from ..models import AI_OUTPUT_MODELS, AI_TASKS
from .types import Provider, ServiceTier, Thinking

ThinkingLevel = Literal["minimal", "low", "medium", "high"]
LEVEL_ORDER: tuple[ThinkingLevel, ...] = ("minimal", "low", "medium", "high")


class ModelSpec(BaseModel):
    """A model and what it accepts (tasks.yaml `models:`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Provider
    model: str
    thinking_levels: tuple[ThinkingLevel, ...] = ("low", "medium", "high")
    sampling: bool = False
    batch: bool = True
    search: bool = True
    search_with_schema: bool = False
    max_output_tokens: int = Field(default=65536, gt=0)

    @property
    def ref(self) -> ModelRef:
        return ModelRef(provider=self.provider, model=self.model)

    def thinking_level(self, wanted: Thinking) -> str | None:
        """The level to send for a task's `thinking`: the nearest one this model accepts.

        "off" maps to the lowest level the model has (Gemini 3.8 Flash and Gemini 4 cannot switch thinking
        off and refuse "minimal"). Other levels map to themselves, or to the closest supported level.
        """
        levels = [lvl for lvl in LEVEL_ORDER if lvl in self.thinking_levels]
        if not levels:
            return None
        if wanted == "off":
            return levels[0]
        if wanted in levels:
            return wanted
        index = LEVEL_ORDER.index(wanted)
        return min(levels, key=lambda lvl: (abs(LEVEL_ORDER.index(lvl) - index), LEVEL_ORDER.index(lvl)))


class ModelRef(BaseModel):
    """`{provider, model}`: one entry of a fallback chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Provider
    model: str

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


# Room added to a task's max_output_tokens for thinking, by level (thinking counts against the output cap).
THINKING_HEADROOM: dict[str, int] = {"minimal": 512, "low": 2048, "medium": 6144, "high": 16384}


class TaskConfig(BaseModel):
    """One AI task for the active tier (Step 4.2.1)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    name: str
    primary: ModelRef
    fallbacks: tuple[ModelRef, ...]
    mode: Literal["sync", "batch"]
    schema_name: str | None = Field(alias="schema")
    prompt: str
    max_output_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0, le=2)
    thinking: Thinking
    tools: tuple[Literal["web_search"], ...] = ()
    priority: int = Field(ge=1, le=6)
    est_input_tokens: int = Field(gt=0)
    est_output_tokens: int = Field(gt=0)
    cache_ttl_days: int = Field(ge=0)
    timeout_s: int = Field(gt=0)
    max_retries: int = Field(ge=0, le=5)
    structure_with: ModelRef | None = None
    structure_prompt: str | None = None
    service_tier: ServiceTier = "standard"
    daily_limit_setting: str | None = None
    daily_limit: int | None = Field(default=None, gt=0)

    @property
    def chain(self) -> list[ModelRef]:
        return [self.primary, *self.fallbacks]

    @property
    def schema_model(self) -> type[BaseModel] | None:
        if self.schema_name is None:
            return None
        model = getattr(models_module, self.schema_name, None)
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise ValueError(f"{self.name}: schema {self.schema_name!r} is not a model in nument_engine.models")
        return model

    @property
    def uses_search(self) -> bool:
        return "web_search" in self.tools

    @field_validator("fallbacks", mode="before")
    @classmethod
    def _tuple(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _rules(self) -> TaskConfig:
        chain = self.chain
        if not any(m.provider == "gemini" for m in chain):
            raise ValueError(f"{self.name}: chain needs at least one gemini model (Gemini must run every task)")
        if len(set(chain)) != len(chain):
            raise ValueError(f"{self.name}: the same model appears twice in the chain")
        if self.uses_search and self.schema_name and not (self.structure_with and self.structure_prompt):
            raise ValueError(f"{self.name}: a web-search task with a schema needs structure_with and structure_prompt")
        if (self.daily_limit_setting is None) != (self.daily_limit is None):
            raise ValueError(f"{self.name}: set both daily_limit_setting and daily_limit, or neither")
        return self


@dataclass(frozen=True)
class TaskRegistry:
    """Validated tasks of one tier plus the model specs they use."""

    tier: str
    tasks: dict[str, TaskConfig]
    specs: dict[ModelRef, ModelSpec]

    def task(self, name: str) -> TaskConfig:
        try:
            return self.tasks[name]
        except KeyError:
            raise KeyError(f"unknown AI task {name!r}; expected one of {', '.join(sorted(self.tasks))}") from None

    def spec(self, ref: ModelRef) -> ModelSpec:
        return self.specs[ref]

    def all_refs(self) -> list[ModelRef]:
        seen: dict[ModelRef, None] = {}
        for cfg in self.tasks.values():
            for ref in cfg.chain:
                seen.setdefault(ref, None)
            if cfg.structure_with:
                seen.setdefault(cfg.structure_with, None)
        return list(seen)


class ConfigError(ValueError):
    """tasks.yaml or a prompt file is wrong. Raised at startup, before any paid call."""


def _tasks_path() -> Path:
    from ..settings import get_settings

    return get_settings().config_dir / "tasks.yaml"


def _tier_tasks(tiers: dict[str, Any], tier: str, seen: tuple[str, ...] = ()) -> dict[str, dict[str, Any]]:
    if tier not in tiers:
        raise ConfigError(f"tier {tier!r} is not defined in tasks.yaml (tiers: {', '.join(tiers)})")
    if tier in seen:
        raise ConfigError(f"tier inheritance loops through {tier!r}")
    body = dict(tiers[tier] or {})
    parent = body.pop("inherit", None)
    overrides = body.pop("overrides", None) or {}
    if parent is None:
        if overrides:
            raise ConfigError(f"tier {tier!r} has overrides but no inherit")
        return {name: dict(cfg) for name, cfg in body.items()}
    base = _tier_tasks(tiers, parent, (*seen, tier))
    for name, cfg in body.items():  # full task definitions next to inherit replace the parent's
        base[name] = dict(cfg)
    for name, partial in overrides.items():
        if name not in base:
            raise ConfigError(f"tier {tier!r} overrides unknown task {name!r}")
        base[name] = {**base[name], **partial}
    return base


def load_registry(tier: str = "balanced", path: Path | None = None, *, check_prompts: bool = True) -> TaskRegistry:
    """Load, resolve and validate one tier. Raises ConfigError with every problem listed."""
    return _load_registry(tier, str(path or _tasks_path()), check_prompts)


@lru_cache(maxsize=8)
def _load_registry(tier: str, path: str, check_prompts: bool) -> TaskRegistry:
    from ..budget import load_prices
    from . import prompts

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    try:
        specs_by_name = {name: ModelSpec.model_validate(spec) for name, spec in (data.get("models") or {}).items()}
    except Exception as exc:
        raise ConfigError(f"tasks.yaml models: {exc}") from None
    specs = {spec.ref: spec for spec in specs_by_name.values()}

    def ref(name: Any, where: str) -> Any:
        if isinstance(name, str):
            if name not in specs_by_name:
                problems.append(f"{where}: unknown model short name {name!r}")
                return {"provider": "gemini", "model": f"<unknown {name}>"}
            return specs_by_name[name].ref.model_dump()
        return name

    raw_tasks = _tier_tasks(data.get("tiers") or {}, tier)
    tasks: dict[str, TaskConfig] = {}
    for name, raw in raw_tasks.items():
        resolved = dict(raw)
        resolved["primary"] = ref(raw.get("primary"), f"{name}.primary")
        resolved["fallbacks"] = [ref(f, f"{name}.fallbacks") for f in raw.get("fallbacks") or []]
        if raw.get("structure_with") is not None:
            resolved["structure_with"] = ref(raw["structure_with"], f"{name}.structure_with")
        try:
            tasks[name] = TaskConfig.model_validate({"name": name, **resolved})
        except Exception as exc:
            problems.append(f"{name}: {exc}")

    missing = sorted(set(AI_TASKS) - set(raw_tasks))
    unknown = sorted(set(raw_tasks) - set(AI_TASKS))
    if missing:
        problems.append(f"tier {tier!r} is missing tasks: {', '.join(missing)}")
    if unknown:
        problems.append(f"tier {tier!r} defines unknown tasks: {', '.join(unknown)} (add them to models.AITask)")

    prices = load_prices()
    for name, cfg in tasks.items():
        refs = [*cfg.chain, *([cfg.structure_with] if cfg.structure_with else [])]
        for r in refs:
            if r not in specs:
                problems.append(f"{name}: model {r} has no entry under models:")
            if r.model not in prices.models:
                problems.append(f"{name}: model {r.model} has no price in prices.yaml")
            elif prices.models[r.model].provider != r.provider:
                problems.append(f"{name}: prices.yaml says {r.model} belongs to {prices.models[r.model].provider}")
        try:
            schema = cfg.schema_model
        except ValueError as exc:
            problems.append(str(exc))
            schema = None
        canonical = AI_OUTPUT_MODELS.get(name)
        if canonical is not None and schema is not canonical:
            problems.append(f"{name}: schema must be {canonical.__name__} (A.13.1), not {cfg.schema_name}")
        if cfg.uses_search:
            for r in cfg.chain:
                if r in specs and not specs[r].search:
                    problems.append(f"{name}: {r} cannot use web search")
        if cfg.mode == "batch" and not any(r in specs and specs[r].batch for r in cfg.chain):
            problems.append(f"{name}: batch task without a batch-capable model")
        if check_prompts:
            for file, role in ((cfg.prompt, "main"), (cfg.structure_prompt, "structure")):
                if file is None:
                    continue
                try:
                    p = prompts.load(file)
                except (FileNotFoundError, ValueError) as exc:
                    problems.append(f"{name}: prompt {file}: {exc}")
                    continue
                if p.task != name:
                    problems.append(f"{name}: prompt {file} is for task {p.task!r}")
                expected = cfg.schema_name if role == "structure" or not cfg.uses_search else None
                if p.output != expected:
                    problems.append(f"{name}: prompt {file} declares output {p.output!r}, expected {expected!r}")
    if problems:
        raise ConfigError("tasks.yaml is invalid:\n  - " + "\n  - ".join(problems))
    return TaskRegistry(tier=tier, tasks=tasks, specs=specs)


def clear_cache() -> None:
    _load_registry.cache_clear()
