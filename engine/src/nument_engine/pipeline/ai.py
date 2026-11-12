"""The one door from Steps 10 to 12 to the AI router (Step 4).

Pipeline steps never import a provider SDK or the router's internals (Step 4.1.2 rule 1). They call
`call()`, which:

- runs `router.run(task=..., inputs=..., lead_id=...)` exactly as Step 4.10 defines it, and passes
  `exclude_model` only when the router accepts it (Step 12.9: the critic is never the writer's model);
- turns the router's two documented failures into exceptions this package owns: `BudgetExceeded` becomes
  `AIBudgetStop`, `AllProvidersDown` (and any other router error) becomes `AIUnavailable`. Callers record the
  skip in the run stats and move on (Step 4.1.2 rules 4 and 5);
- reports which provider and model answered, so rows can store the `provider:model#task.vN` tag (Step 4.9.3).
  The router's `last_meta` is read when it has one; otherwise the run's latest `costs` row for the task
  (the router writes one per call) names the model.

The router itself comes from `nument_engine.llm.router.for_run(rc)`. Until that exists, the steps run
without AI and say so in the run stats.
"""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from .. import db
from ..logging import get_logger
from ..settings import get_settings
from .runs import RunContext

log = get_logger()

# Exception class names raised by the router and the budget guard (Step 4.10, 4.11). Matched by name so this
# module does not import the router at load time.
BUDGET_ERRORS = frozenset({"BudgetExceeded", "BudgetStop"})
DOWN_ERRORS = frozenset({"AllProvidersDown"})


class AIRouter(Protocol):
    """What the pipeline needs from the Step 4 router."""

    def run(self, task: str, inputs: dict[str, Any], *, lead_id: str | None = None, cache_extra: str = "") -> Any:
        """Render the task's prompt with `inputs`, walk the fallback chain and return the validated output."""
        ...


class AIStop(Exception):
    """The router did not answer. The caller records the reason and carries on without AI."""

    def __init__(self, task: str, reason: str) -> None:
        super().__init__(f"{task}: {reason}")
        self.task = task
        self.reason = reason


class AIBudgetStop(AIStop):
    """The budget guard refused the call (daily cap, priority ladder or --max-spend-inr)."""


class AIUnavailable(AIStop):
    """No provider in the chain could answer, the answer did not fit the schema, or no router exists."""


@dataclass(frozen=True)
class AIResult[T: BaseModel]:
    """A validated AI output plus who produced it."""

    task: str
    output: T
    provider: str | None
    model: str | None
    prompt_version: int | None
    fallback_from: str | None = None

    @property
    def tag(self) -> str:
        """`provider:model#task.vN`, the form every stored AI output carries (Step 4.9.3)."""
        who = f"{self.provider}:{self.model}" if self.provider and self.model else (self.model or "unknown")
        version = f".v{self.prompt_version}" if self.prompt_version is not None else ""
        return f"{who}#{self.task}{version}"


def accepts_kwarg(fn: Callable[..., Any], name: str) -> bool:
    """True when `fn` takes the keyword `name` (or any keyword through **kwargs)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def call[T: BaseModel](
    router: AIRouter,
    task: str,
    inputs: dict[str, Any],
    schema: type[T],
    *,
    run_id: str | None = None,
    lead_id: str | None = None,
    exclude_model: str | None = None,
) -> AIResult[T]:
    """Run one AI task through the router and return its validated output with the model that answered."""
    kwargs: dict[str, Any] = {"lead_id": lead_id}
    if exclude_model and accepts_kwarg(router.run, "exclude_model"):
        kwargs["exclude_model"] = exclude_model
    try:
        raw = router.run(task=task, inputs=inputs, **kwargs)
    except AIStop:
        raise
    except Exception as exc:  # the router's failures are data here, never a crash of the stage
        name = type(exc).__name__
        if name in BUDGET_ERRORS:
            raise AIBudgetStop(task, str(exc)) from exc
        if name not in DOWN_ERRORS:
            log.warning("ai.router_error", task=task, error=f"{name}: {str(exc)[:200]}")
        raise AIUnavailable(task, f"{name}: {str(exc)[:200]}") from exc
    output = coerce(raw, schema, task)
    provider, model, version, fallback_from = answered_by(router, task, run_id)
    return AIResult(task, output, provider, model, version, fallback_from)


def coerce[T: BaseModel](raw: Any, schema: type[T], task: str) -> T:
    """The router returns the task's pydantic object; accept an equivalent model or a plain dict too."""
    if isinstance(raw, schema):
        return raw
    try:
        if isinstance(raw, BaseModel):
            return schema.model_validate(raw.model_dump())
        if isinstance(raw, Mapping):
            return schema.model_validate(dict(raw))
        if isinstance(raw, str | bytes):
            return schema.model_validate_json(raw)
    except ValidationError as exc:
        raise AIUnavailable(task, f"answer does not match {schema.__name__}: {exc.errors()[:3]}") from exc
    raise AIUnavailable(task, f"unexpected answer type {type(raw).__name__}")


def _meta_get(meta: Any, key: str) -> Any:
    if isinstance(meta, Mapping):
        return meta.get(key)
    return getattr(meta, key, None)


def answered_by(router: Any, task: str, run_id: str | None) -> tuple[str | None, str | None, int | None, str | None]:
    """(provider, model, prompt version, fallback_from) of the router's last answer for `task`."""
    meta = getattr(router, "last_meta", None)
    if meta is not None and (_meta_get(meta, "task") in (None, task)):
        provider, model = _meta_get(meta, "provider"), _meta_get(meta, "model")
        version = _meta_get(meta, "prompt_version")
        if provider or model:
            return (
                str(provider) if provider else None,
                str(model) if model else None,
                int(version) if version is not None else prompt_version(task),
                _meta_get(meta, "fallback_from"),
            )
    if run_id:
        try:
            row = db.fetch_one(
                "select provider, model, fallback_from from public.costs "
                "where run_id = %s and task = %s order by at desc limit 1",
                [run_id, task],
            )
        except Exception:  # no database (unit tests with a fake router) or a transient error
            row = None
        if row:
            return row["provider"], row["model"], prompt_version(task), row["fallback_from"]
    return None, None, prompt_version(task), None


_VERSION = re.compile(r"^version:\s*(\d+)\s*$", re.M)


@lru_cache(maxsize=32)
def prompt_version(task: str) -> int | None:
    """The `version:` in the front matter of engine/prompts/<task>.md, or None if the file is missing."""
    path = get_settings().prompts_dir / f"{task}.md"
    try:
        head = path.read_text(encoding="utf-8").split("\n---", 2)[0]
    except OSError:
        return None
    m = _VERSION.search(head)
    return int(m.group(1)) if m else None


def router_for(rc: RunContext) -> AIRouter:
    """The Step 4 router for this run: `nument_engine.llm.router.for_run(rc)`.

    Raises AIUnavailable when the router is not built or cannot start (for example no key in a dry run),
    so the calling step continues without AI and records why.
    """
    try:
        module = importlib.import_module("nument_engine.llm.router")
    except ImportError as exc:
        raise AIUnavailable("router", f"router module missing: {exc}") from exc
    factory = vars(module).get("for_run")
    if not callable(factory):
        raise AIUnavailable("router", "nument_engine.llm.router.for_run(rc) is not available yet")
    try:
        router: AIRouter = factory(rc)
    except Exception as exc:
        raise AIUnavailable("router", f"router could not start: {type(exc).__name__}: {exc}") from exc
    return router
