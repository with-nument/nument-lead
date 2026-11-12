"""The AI router: the one door every pipeline step uses for AI (Step 4.10).

`Router.run(task, inputs)`:

1. loads the task config (tasks.yaml, active tier) and renders its prompt file;
2. returns a cached answer when the same task, prompt version and rendered prompt were answered recently
   (logged as a free `cache` cost row);
3. walks the fallback chain: skips models whose provider is switched off, has no key or has an open breaker;
4. asks the budget guard before every paid call (raises BudgetExceeded: the step records the skip);
5. calls the provider, retrying transient errors with backoff; on a hard failure it trips the breaker and
   moves to the next model;
6. validates the answer against the task's pydantic model, with one repair call on the same model;
7. logs a cost row for every provider call (with `fallback_from` when the primary did not answer), caches
   the answer and returns an `AIResult` that carries the output and the `provider:model#task.vN` tag.

Web-search tasks with a schema make two calls (Step 5.11.1): a grounded search call that returns text and
citations, then a structuring call on a cheap model. The search queries are logged as provider google_search.

Pipeline code never imports google.genai or openai; only gemini.py and openai_provider.py do.
"""

from __future__ import annotations

import hashlib
import random
import threading
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .. import db
from ..budget import Budget, BudgetExceeded, estimate_tokens
from ..logging import get_logger
from ..settings import Settings, get_settings
from . import prompts, store
from .availability import PROVIDERS, Availability
from .config import THINKING_HEADROOM, ModelRef, ModelSpec, TaskConfig, TaskRegistry, load_registry
from .schema import parse_output, validate_output
from .types import AllProvidersDown, LLMProvider, LLMRequest, LLMResponse, OutputInvalid, ProviderError, Usage

log = get_logger("nlead.llm")

# Outputs that belong to one lead get an `ai_output` activity row (Step 4.5.3).
LEAD_LEVEL_TASKS = frozenset({"write_message", "judge_lead"})
PROMPT_OVERHEAD_TOKENS = 300  # schema and request framing on top of the rendered prompt
LIMIT_REFRESH_S = 60.0
MAX_BACKOFF_S = 30.0

REPAIR_NOTE = (
    "\n\nYour previous answer could not be used: {errors}.\n"
    "Reply again with only JSON that matches the required schema exactly."
)
TRUNCATED_NOTE = (
    "\n\nYour previous answer was cut off before it finished. Keep every text field short and reply again "
    "with complete JSON that matches the required schema."
)
SEARCH_ATTEMPTS = 3  # per model: the first try plus two nudged tries
SEARCH_NUDGE = (
    "\n\nYou have not run a Google Search yet. Use the Google Search tool now for the ideas above, then "
    "answer only from what it finds."
)


class TextOutput(BaseModel):
    """Output of a task that has no schema (free text)."""

    text: str


@dataclass
class AIResult[T: BaseModel]:
    """What `Router.run_result` returns: the validated pydantic `output` plus who produced it and the cost."""

    task: str
    output: T
    provider: str  # provider that produced the answer (for a cache hit: the one that produced it originally)
    model: str
    prompt_version: int
    fallback_from: str | None = None  # "provider:model" of the primary when a fallback answered
    cached: bool = False
    usage: Usage = field(default_factory=Usage)
    inr: float = 0.0  # what this call cost (0 for a cache hit)
    grounding: dict[str, Any] | None = None  # search tasks: {"queries", "sources": [{"uri", "title"}], ...}

    @property
    def tag(self) -> str:
        """`provider:model#task.vN`, stored with every AI output (facts.model, leads.message_model, ...)."""
        return f"{self.provider}:{self.model}#{self.task}.v{self.prompt_version}"

    def meta(self) -> dict[str, Any]:
        """The fields `Router.last_meta` exposes."""
        return {
            "task": self.task,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "fallback_from": self.fallback_from,
            "tag": self.tag,
            "cached": self.cached,
            "inr": round(self.inr, 4),
        }


def build_providers(settings: Settings) -> dict[str, LLMProvider]:
    """Provider clients for every key that is set. Whether a provider is used is decided by Availability."""
    providers: dict[str, LLMProvider] = {}
    gateway = settings.et_gateway_key.get_secret_value() if settings.et_gateway_key is not None else ""
    base = settings.gateway_base_url.rstrip("/")
    keys: list[str] = []
    urls: list[str | None] = []
    if gateway:  # the ET AI Gateway first, the direct keys as the automatic backup
        keys.append(gateway)
        urls.append(f"{base}/gemini")
    for k in (settings.gemini_api_key, settings.gemini_api_key_backup):
        if k is not None and k.get_secret_value():
            keys.append(k.get_secret_value())
            urls.append(None)
    if keys:
        from .gemini import GeminiProvider

        providers["gemini"] = GeminiProvider(keys, base_urls=urls)
    from .openai_provider import OpenAIProvider

    if gateway:
        providers["openai"] = OpenAIProvider(gateway, base_url=f"{base}/openai/v1")
    elif settings.openai_api_key is not None and settings.openai_api_key.get_secret_value():
        providers["openai"] = OpenAIProvider(settings.openai_api_key.get_secret_value())
    return providers


def for_run(rc: Any, **kwargs: Any) -> Router:
    """The router for a pipeline run: `nument_engine.llm.router.for_run(rc)` (the Steps 10 to 12 seam)."""
    return Router.for_run(rc, **kwargs)


def _as_provider_error(exc: BaseException, req: LLMRequest) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if req.provider == "gemini":
        from .gemini import classify_error

        return classify_error(exc, req.model)
    from .openai_provider import classify_error as classify_openai

    return classify_openai(exc, req.model)


class Router:
    """Routes AI tasks to models. One per run; safe to share between threads.

    run_id          costs rows and logs are tied to this `runs.id`
    max_spend_inr   the `--max-spend-inr` cap for this run (None in production)
    stats           RunContext.stats: fallbacks, errors, cache hits and budget alerts are counted there
    dry_run         batch submission is skipped (sync calls still run, inside --max-spend-inr)
    The other arguments exist for tests and tools: inject a registry, providers, availability or budget.
    """

    def __init__(
        self,
        *,
        run_id: str | None = None,
        max_spend_inr: float | None = None,
        stats: dict[str, Any] | None = None,
        dry_run: bool = False,
        tier: str | None = None,
        registry: TaskRegistry | None = None,
        providers: dict[str, LLMProvider] | None = None,
        availability: Availability | None = None,
        budget: Budget | None = None,
        settings: Settings | None = None,
        enabled_override: dict[str, bool] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        settings = settings or get_settings()
        self.run_id = run_id
        self.stats: dict[str, Any] = stats if stats is not None else {}
        self.dry_run = dry_run
        self.registry = registry or load_registry(tier or str(db.get_setting("tier", "balanced")))
        self.providers: dict[str, LLMProvider] = providers if providers is not None else build_providers(settings)
        self.availability = availability or Availability.load(
            has_key={p: p in self.providers for p in PROVIDERS},
            app_env=settings.app_env,
            clock=clock,
            enabled_override=enabled_override,
        )
        self.budget = budget or Budget(run_id, max_spend_inr=max_spend_inr, stats=self.stats, clock=clock)
        self._sleep = sleep
        self._lock = threading.RLock()
        self._limit_used: dict[str, tuple[float, int]] = {}
        self._local = threading.local()

    @classmethod
    def for_run(cls, rc: Any, **kwargs: Any) -> Router:
        """Router for a pipeline run (`rc` is a RunContext): its run id, --max-spend-inr, stats and dry run."""
        return cls(
            run_id=rc.run_id, max_spend_inr=rc.opts.max_spend_inr, stats=rc.stats, dry_run=rc.opts.dry_run, **kwargs
        )

    @property
    def last_meta(self) -> dict[str, Any] | None:
        """Who answered the last successful `run` in this thread: task, provider, model, prompt_version,
        fallback_from, tag, cached, inr. None before the first answer and after a failed call."""
        meta: dict[str, Any] | None = getattr(self._local, "meta", None)
        return meta

    # ------------------------------------------------------------------ public

    def task(self, name: str) -> TaskConfig:
        return self.registry.task(name)

    def skip_reason(self, ref: ModelRef) -> str | None:
        """Why this model cannot be called now (switched off, open breaker, no key), or None."""
        reason = self.availability.model_reason(ref.provider, ref.model)
        if reason is None and ref.provider not in self.providers:
            reason = f"no {ref.provider} API key"
        return reason

    def render(self, task: str, inputs: dict[str, Any]) -> tuple[prompts.Prompt, str, str]:
        """(prompt, system text, user text) for a task and its inputs."""
        cfg = self.registry.task(task)
        prompt = prompts.load(cfg.prompt)
        system, user = prompt.render(**inputs)
        return prompt, system, user

    @staticmethod
    def cache_key(task: str, version: int, system: str, user: str, extra: str = "") -> str:
        return hashlib.sha256("\x1f".join([task, str(version), system, user, extra]).encode()).hexdigest()

    def run(
        self,
        task: str,
        inputs: dict[str, Any],
        *,
        lead_id: str | None = None,
        cache_extra: str = "",
        models: Sequence[ModelRef] | None = None,
        exclude_model: str | None = None,
        exclude_models: Collection[str] = (),
        use_cache: bool = True,
    ) -> Any:
        """Run one AI task and return its validated pydantic output (Step 4.1.2 rule 2).

        Who answered is in `last_meta` afterwards; `run_result` returns output and metadata together.
        Arguments are the same as for `run_result`.
        """
        return self.run_result(
            task,
            inputs,
            lead_id=lead_id,
            cache_extra=cache_extra,
            models=models,
            exclude_model=exclude_model,
            exclude_models=exclude_models,
            use_cache=use_cache,
        ).output

    def run_result(
        self,
        task: str,
        inputs: dict[str, Any],
        *,
        lead_id: str | None = None,
        cache_extra: str = "",
        models: Sequence[ModelRef] | None = None,
        exclude_model: str | None = None,
        exclude_models: Collection[str] = (),
        use_cache: bool = True,
    ) -> AIResult[Any]:
        """Run one AI task and return an AIResult (output, provider, model, prompt version, tag, cost).

        lead_id         for write_message and judge_lead: records an `ai_output` activity on the lead
        cache_extra     extra text mixed into the cache key (for example a page text hash)
        models          force these models instead of the task's chain (evals and the smoke test)
        exclude_model   a model id never to use for this call, for example the writer's model when the
                        critic runs (Step 12.9); the next model in the chain answers instead
        exclude_models  the same for several model ids
        Raises BudgetExceeded, AllProvidersDown (also when every model is excluded), or KeyError for a
        missing prompt input.
        """
        self._local.meta = None
        excluded = {*exclude_models, *([exclude_model] if exclude_model else [])}
        cfg = self.registry.task(task)
        chain = self._chain(cfg, models, excluded)
        prompt, system, user = self.render(task, inputs)
        schema = cfg.schema_model
        key = self.cache_key(task, prompt.version, system, user, cache_extra)
        caching = use_cache and cfg.cache_ttl_days > 0
        if caching:
            cached = self._from_cache(cfg, store.cache_get(key))
            if cached is not None and cached.model not in excluded:
                self.budget.record("cache", cached.model, task, calls=1, usd=0.0)
                self._count("cache_hits", task)
                log.info("llm.cache_hit", task=task, model=cached.model)
                self._local.meta = cached.meta()
                return cached
        self._check_daily_limit(cfg)

        attempts: list[str] = [f"{m} excluded for this call" for m in sorted(excluded)]
        for ref in chain:
            reason = self.skip_reason(ref)
            if reason:
                attempts.append(f"{ref} skipped ({reason})")
                continue
            spec = self.registry.spec(ref)
            fallback_from = None if ref == cfg.primary else str(cfg.primary)
            try:
                result = self._run_on(cfg, prompt, spec, system, user, schema, fallback_from)
            except ProviderError as err:
                self.availability.record_failure(ref.provider, ref.model, err)
                attempts.append(f"{ref} {err.kind}: {err.message[:160]}")
                self._count("ai_errors", f"{task}:{err.kind}")
                log.warning(
                    "llm.call_failed",
                    task=task,
                    provider=ref.provider,
                    model=ref.model,
                    kind=err.kind,
                    error=err.message[:300],
                )
                continue
            except OutputInvalid as err:
                attempts.append(f"{ref} invalid output: {str(err)[:160]}")
                self._count("ai_errors", f"{task}:invalid_output")
                log.warning(
                    "llm.invalid_output", task=task, provider=ref.provider, model=ref.model, error=str(err)[:300]
                )
                continue
            self.availability.record_success(ref.provider, ref.model)
            if fallback_from:
                self._count("fallbacks", task)
            if lead_id and task in LEAD_LEVEL_TASKS:
                store.insert_ai_output(
                    lead_id,
                    {
                        "task": task,
                        "provider": result.provider,
                        "model": result.model,
                        "fallback_from": fallback_from,
                        "prompt_version": prompt.version,
                        "tag": result.tag,
                    },
                )
            if caching:
                store.cache_put(key, task, result.model, self._cache_payload(result), cfg.cache_ttl_days)
            log.info(
                "llm.call",
                task=task,
                provider=result.provider,
                model=result.model,
                fallback_from=fallback_from,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                inr=round(result.inr, 4),
            )
            self._local.meta = result.meta()
            return result
        self._count("all_providers_down", task)
        raise AllProvidersDown(task, attempts)

    def estimate_inr(self, task: str, items: int = 1, *, batch: bool | None = None) -> float:
        """Planning estimate for `items` calls of a task on the first usable model of its chain."""
        cfg = self.registry.task(task)
        for ref in cfg.chain:
            if ref.provider in self.providers and self.availability.model_reason(ref.provider, ref.model) is None:
                use_batch = cfg.mode == "batch" if batch is None else batch
                one = self.budget.estimate_llm_inr(
                    ref.model, cfg.est_input_tokens, cfg.est_output_tokens, batch=use_batch
                )
                return one * items
        return 0.0

    # ------------------------------------------------------------- internals

    def _chain(self, cfg: TaskConfig, models: Sequence[ModelRef] | None, exclude: Collection[str]) -> list[ModelRef]:
        chain = list(models) if models is not None else cfg.chain
        for ref in chain:
            if ref not in self.registry.specs:
                raise KeyError(f"{cfg.name}: model {ref} is not declared under models: in tasks.yaml")
        return [ref for ref in chain if ref.model not in exclude]

    def request(
        self,
        cfg: TaskConfig,
        spec: ModelSpec,
        system: str,
        user: str,
        schema: type[BaseModel] | None,
        *,
        tools: Sequence[str] | None = None,
        thinking: Any = None,
        key: str | None = None,
    ) -> LLMRequest:
        """Build the provider request for a task on one model (also used by batch submission)."""
        level = spec.thinking_level(thinking or cfg.thinking)
        headroom = THINKING_HEADROOM.get(level, 0) if level else 0
        return LLMRequest(
            task=cfg.name,
            provider=spec.provider,
            model=spec.model,
            system=system,
            user=user,
            schema=schema,
            max_output_tokens=min(spec.max_output_tokens, cfg.max_output_tokens + headroom),
            temperature=cfg.temperature if spec.sampling else None,
            thinking=level,
            tools=list(cfg.tools if tools is None else tools),
            timeout_s=cfg.timeout_s,
            service_tier=cfg.service_tier,
            key=key,
        )

    def _call(self, req: LLMRequest, cfg: TaskConfig) -> LLMResponse:
        """One provider call with retries on transient errors (network, 429, 5xx), exponential backoff."""
        provider = self.providers[req.provider]
        attempts = cfg.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return provider.generate(req)
            except Exception as exc:
                err = _as_provider_error(exc, req)
                if err.kind != "transient" or attempt == attempts:
                    raise err from None
                delay = min(MAX_BACKOFF_S, 2.0 * 2 ** (attempt - 1)) * (0.5 + random.random() / 2)
                log.info("llm.retry", task=req.task, model=req.model, attempt=attempt, delay_s=round(delay, 1))
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _log(self, cfg: TaskConfig, ref: ModelRef, usage: Usage, fallback_from: str | None) -> float:
        usd = self.budget.llm_cost_usd(
            ref.model,
            usage.input_tokens,
            usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            flex=cfg.service_tier == "flex",
        )
        inr = self.budget.record(
            ref.provider,
            ref.model,
            cfg.name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            calls=1,
            usd=usd,
            fallback_from=fallback_from,
        )
        if cfg.daily_limit_setting:
            with self._lock:
                read_at, used = self._limit_used.get(cfg.daily_limit_setting, (0.0, 0))
                self._limit_used[cfg.daily_limit_setting] = (read_at, used + 1)
        return inr

    def _estimate(self, cfg: TaskConfig, ref: ModelRef, system: str, user: str) -> float:
        est_in = estimate_tokens(system) + estimate_tokens(user) + PROMPT_OVERHEAD_TOKENS
        return self.budget.estimate_llm_inr(ref.model, est_in, cfg.est_output_tokens, flex=cfg.service_tier == "flex")

    def parse_response(self, resp: LLMResponse, schema: type[BaseModel]) -> BaseModel:
        """Validate an answer; a parse failure on an answer cut off at the token cap is marked truncated."""
        try:
            return parse_output(resp.text, schema)
        except OutputInvalid as err:
            if resp.finish_reason == "max_tokens":
                raise OutputInvalid(f"answer cut off at the output limit ({err})", truncated=True) from None
            raise

    def _ask(
        self,
        cfg: TaskConfig,
        spec: ModelSpec,
        req: LLMRequest,
        schema: type[BaseModel],
        fallback_from: str | None,
        cost: list[float],
        usage: list[Usage],
    ) -> BaseModel:
        """Call, parse, and repair once on the same model. Every call made is logged as a cost."""
        resp = self._call(req, cfg)
        cost.append(self._log(cfg, spec.ref, resp.usage, fallback_from))
        usage.append(resp.usage)
        try:
            return self.parse_response(resp, schema)
        except OutputInvalid as err:
            note = TRUNCATED_NOTE if err.truncated else REPAIR_NOTE.format(errors=str(err)[:600])
            max_out = req.max_output_tokens * 2 if err.truncated else req.max_output_tokens
            repair = replace(req, user=req.user + note, max_output_tokens=min(spec.max_output_tokens, max_out))
            self.budget.check(cfg.name, cfg.priority, self._estimate(cfg, spec.ref, repair.system, repair.user))
            log.info("llm.repair", task=cfg.name, model=spec.model, truncated=err.truncated)
            resp2 = self._call(repair, cfg)
            cost.append(self._log(cfg, spec.ref, resp2.usage, fallback_from))
            usage.append(resp2.usage)
            return self.parse_response(resp2, schema)

    def _run_on(
        self,
        cfg: TaskConfig,
        prompt: prompts.Prompt,
        spec: ModelSpec,
        system: str,
        user: str,
        schema: type[BaseModel] | None,
        fallback_from: str | None,
    ) -> AIResult[Any]:
        ref = spec.ref
        if cfg.uses_search and ref.provider == "gemini" and self.budget.grounding_quota_left() <= 0:
            raise BudgetExceeded(cfg.name, "grounded search quota for today or this month is used up")
        self.budget.check(cfg.name, cfg.priority, self._estimate(cfg, ref, system, user))
        cost: list[float] = []
        usage: list[Usage] = []

        if cfg.uses_search and schema is not None and not spec.search_with_schema:
            return self._search_then_structure(cfg, prompt, spec, system, user, schema, fallback_from)

        req = self.request(cfg, spec, system, user, schema)
        if schema is None:
            if cfg.uses_search:
                resp = self._searched(cfg, spec, req, fallback_from, cost, usage)
            else:
                resp = self._call(req, cfg)
                cost.append(self._log(cfg, ref, resp.usage, fallback_from))
            return AIResult(
                task=cfg.name,
                output=TextOutput(text=resp.text),
                provider=ref.provider,
                model=ref.model,
                prompt_version=prompt.version,
                fallback_from=fallback_from,
                usage=resp.usage,
                inr=sum(cost),
                grounding=resp.grounding,
            )
        output = self._ask(cfg, spec, req, schema, fallback_from, cost, usage)
        total = usage[0]
        for extra in usage[1:]:
            total = total + extra
        return AIResult(
            task=cfg.name,
            output=output,
            provider=ref.provider,
            model=ref.model,
            prompt_version=prompt.version,
            fallback_from=fallback_from,
            usage=total,
            inr=sum(cost),
        )

    def _searched(
        self,
        cfg: TaskConfig,
        spec: ModelSpec,
        req: LLMRequest,
        fallback_from: str | None,
        cost: list[float],
        usage: list[Usage],
    ) -> LLMResponse:
        """A web-search call whose answer is only used if the model really searched (it has citations).

        Verified 2026-11-12: Gemini sometimes skips the search tool and still answers "I found nothing" or
        describes "search results" it never fetched (live night run: 4 of 4 answers without a search; a retry
        usually searches). Such an answer gets up to two nudges; if the model still does not search, the
        answer is refused and the next model in the chain gets the task.
        """
        ref = spec.ref
        resp: LLMResponse | None = None
        for attempt in range(SEARCH_ATTEMPTS):
            if attempt == 1:  # the nudge is added once and kept for the last try
                req = replace(req, user=req.user + SEARCH_NUDGE)
                self.budget.check(cfg.name, cfg.priority, self._estimate(cfg, ref, req.system, req.user))
                log.info("llm.search_nudge", task=cfg.name, model=ref.model)
            resp = self._call(req, cfg)
            cost.append(self._log(cfg, ref, resp.usage, fallback_from))
            cost.append(
                self.budget.record_search(
                    ref.provider, ref.model, resp.usage.search_queries, fallback_from=fallback_from
                )
            )
            usage.append(resp.usage)
            grounding = resp.grounding or {}
            if grounding.get("queries") or grounding.get("sources"):
                return resp
        raise OutputInvalid("the model answered without using web search, so its answer has no citations")

    def _search_then_structure(
        self,
        cfg: TaskConfig,
        prompt: prompts.Prompt,
        spec: ModelSpec,
        system: str,
        user: str,
        schema: type[BaseModel],
        fallback_from: str | None,
    ) -> AIResult[Any]:
        """Grounded search call (text and citations), then a structuring call into the task schema."""
        ref = spec.ref
        cost: list[float] = []
        usage: list[Usage] = []
        resp = self._searched(cfg, spec, self.request(cfg, spec, system, user, None), fallback_from, cost, usage)
        if not resp.text.strip():
            raise ProviderError("blocked", "empty answer from the search call", provider=ref.provider, model=ref.model)

        assert cfg.structure_with is not None and cfg.structure_prompt is not None
        structure_prompt = prompts.load(cfg.structure_prompt)
        grounding = resp.grounding or {}
        s_system, s_user = structure_prompt.render(
            answer=resp.text, sources=grounding.get("sources", []), queries=grounding.get("queries", [])
        )
        candidates = [cfg.structure_with] + ([ref] if ref != cfg.structure_with else [])
        problems: list[str] = []
        for s_ref in candidates:
            reason = self.skip_reason(s_ref)
            if reason:
                problems.append(f"{s_ref} skipped ({reason})")
                continue
            s_spec = self.registry.spec(s_ref)
            s_req = self.request(cfg, s_spec, s_system, s_user, schema, tools=[], thinking="off")
            try:
                output = self._ask(cfg, s_spec, s_req, schema, fallback_from, cost, usage)
            except ProviderError as err:
                self.availability.record_failure(s_ref.provider, s_ref.model, err)
                problems.append(f"{s_ref} {err.kind}")
                continue
            except OutputInvalid as err:
                problems.append(f"{s_ref} invalid output: {str(err)[:120]}")
                continue
            self.availability.record_success(s_ref.provider, s_ref.model)
            total = usage[0]
            for extra in usage[1:]:
                total = total + extra
            return AIResult(
                task=cfg.name,
                output=output,
                provider=ref.provider,
                model=ref.model,
                prompt_version=prompt.version,
                fallback_from=fallback_from,
                usage=total,
                inr=sum(cost),
                grounding=resp.grounding,
            )
        raise OutputInvalid("could not structure the search answer: " + "; ".join(problems))

    def _check_daily_limit(self, cfg: TaskConfig) -> None:
        if not cfg.daily_limit_setting or cfg.daily_limit is None:
            return
        setting = cfg.daily_limit_setting
        limit = int(db.get_setting(setting, cfg.daily_limit) or cfg.daily_limit)
        with self._lock:
            read_at, used = self._limit_used.get(setting, (0.0, 0))
            if time.monotonic() - read_at >= LIMIT_REFRESH_S:
                group = [t.name for t in self.registry.tasks.values() if t.daily_limit_setting == setting]
                used = self.budget.calls_today(None, group)
                self._limit_used[setting] = (time.monotonic(), used)
        if used >= limit:
            raise BudgetExceeded(cfg.name, f"daily limit {setting} = {limit} reached")

    def _cache_payload(self, result: AIResult[Any]) -> dict[str, Any]:
        return {
            "output": result.output.model_dump(mode="json"),
            "provider": result.provider,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "fallback_from": result.fallback_from,
            "grounding": result.grounding,
        }

    def _from_cache(self, cfg: TaskConfig, hit: dict[str, Any] | None) -> AIResult[Any] | None:
        if not hit or "output" not in hit:
            return None
        schema = cfg.schema_model or TextOutput
        try:
            output = validate_output(hit["output"], schema)
        except OutputInvalid:
            return None  # the schema changed since this was cached: ask again
        return AIResult(
            task=cfg.name,
            output=output,
            provider=str(hit.get("provider", "cache")),
            model=str(hit.get("model", "")),
            prompt_version=int(hit.get("prompt_version", 0)),
            fallback_from=hit.get("fallback_from"),
            cached=True,
            grounding=hit.get("grounding"),
        )

    def _count(self, group: str, key: str, n: int = 1) -> None:
        with self._lock:
            bucket = self.stats.setdefault(group, {})
            bucket[key] = bucket.get(key, 0) + n
