"""Batch AI calls: submit at night, collect in the morning, at about half price (Step 4.10.2, Steps 9.13, 9.14).

submit():
  1. drops keys that are already in a live batch (never pay twice for the same item);
  2. picks the first model in the task's chain whose provider is usable and has a batch API;
  3. submits as many items as the budget allows (best first, in the order given), in inline jobs kept under
     the provider's request size limit, and reserves their estimated cost so the daily cap holds;
  4. if a submission fails, trips the breaker and tries the next batch-capable model;
  5. if no batch provider works, runs up to 40 items as sync calls (budget permitting) and leaves the rest
     queued for the next night.

collect():
  polls every open batch (optionally waiting up to `max_wait_s`), validates each finished item against the
  task schema, logs costs at batch prices, releases the reservation, and gives invalid or failed items one
  sync retry when the caller can rebuild their inputs. Failed or expired batches return their keys so the
  items go back to the queue.

Dry runs (`--dry-run`) never submit a batch.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .. import db
from ..budget import BudgetExceeded, estimate_tokens
from ..logging import get_logger
from . import prompts, store
from .config import ModelRef, TaskConfig
from .router import PROMPT_OVERHEAD_TOKENS, Router, TextOutput, _as_provider_error
from .types import AllProvidersDown, LLMRequest, OutputInvalid, ProviderError

log = get_logger("nlead.llm")

INLINE_LIMIT_BYTES = 15_000_000  # Gemini inline batch requests must stay under 20 MB; keep a margin
SYNC_FALLBACK_LIMIT = 40


@dataclass
class BatchItem:
    key: str  # stable and unique per item, for example "extract_facts:<business_id>"
    inputs: dict[str, Any]


@dataclass
class SubmittedJob:
    llm_batch_id: str
    provider: str
    provider_batch_id: str
    model: str
    keys: list[str]
    reserved_inr: float


@dataclass
class ItemResult:
    key: str
    output: BaseModel | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    tag: str | None = None
    fallback_from: str | None = None
    inr: float = 0.0
    sync: bool = False  # answered by a sync call (no batch provider, or a retry after an invalid answer)

    @property
    def ok(self) -> bool:
        return self.output is not None


@dataclass
class SubmitResult:
    jobs: list[SubmittedJob] = field(default_factory=list)
    sync_results: list[ItemResult] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)  # left queued for the next night
    in_flight: list[str] = field(default_factory=list)  # skipped: already in a live batch
    reasons: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def submitted_keys(self) -> list[str]:
        return [k for job in self.jobs for k in job.keys]


@dataclass
class CollectResult:
    results: list[ItemResult] = field(default_factory=list)
    failed_keys: list[str] = field(default_factory=list)  # batch failed, expired or was cancelled
    pending: list[str] = field(default_factory=list)  # llm_batches ids still running


def _payload_size(req: LLMRequest) -> int:
    return len(req.system.encode()) + len(req.user.encode()) + 4096  # config and schema framing


def _chunks(reqs: list[LLMRequest], limit: int) -> list[list[LLMRequest]]:
    chunks: list[list[LLMRequest]] = []
    current: list[LLMRequest] = []
    size = 0
    for req in reqs:
        item = _payload_size(req)
        if current and size + item > limit:
            chunks.append(current)
            current, size = [], 0
        current.append(req)
        size += item
    if current:
        chunks.append(current)
    return chunks


def _fallback_from(cfg: TaskConfig, ref: ModelRef) -> str | None:
    return None if ref == cfg.primary else str(cfg.primary)


def submit(
    router: Router,
    task: str,
    items: Sequence[BatchItem],
    *,
    display_name: str | None = None,
    sync_fallback_limit: int = SYNC_FALLBACK_LIMIT,
) -> SubmitResult:
    """Submit items as one or more provider batch jobs. Items are taken in the order given (best first)."""
    cfg = router.task(task)
    schema = cfg.schema_model
    result = SubmitResult(dry_run=router.dry_run)
    unique: dict[str, BatchItem] = {}
    for item in items:
        if item.key in unique:
            log.warning("llm.batch_duplicate_key", task=task, key=item.key)
            continue
        unique[item.key] = item
    in_flight = store.items_in_flight(task, list(unique))
    result.in_flight = sorted(in_flight)
    todo = [item for key, item in unique.items() if key not in in_flight]
    if not todo:
        return result
    if router.dry_run:
        result.deferred = [item.key for item in todo]
        result.reasons.append("dry run: no batch submitted")
        return result

    rendered: dict[str, tuple[int, str, str]] = {}
    for item in todo:
        prompt, system, user = router.render(task, item.inputs)
        rendered[item.key] = (prompt.version, system, user)
    remaining = list(todo)
    budget_stopped = False
    name = display_name or f"nlead:{task}:{router.run_id or 'manual'}"

    for ref in cfg.chain:
        if not remaining:
            break
        spec = router.registry.spec(ref)
        reason = None if spec.batch else "no batch API"
        reason = reason or router.skip_reason(ref)
        if reason:
            result.reasons.append(f"{ref} skipped ({reason})")
            continue
        estimates = [
            router.budget.estimate_llm_inr(
                ref.model,
                estimate_tokens(rendered[i.key][1]) + estimate_tokens(rendered[i.key][2]) + PROMPT_OVERHEAD_TOKENS,
                cfg.est_output_tokens,
                batch=True,
            )
            for i in remaining
        ]
        fits = router.budget.affordable(task, cfg.priority, estimates)
        if fits == 0:
            result.reasons.append("budget: no room for another batch item today")
            budget_stopped = True
            break
        take, over = remaining[:fits], remaining[fits:]
        estimate_by_key = {i.key: est for i, est in zip(remaining, estimates, strict=True)}
        reqs = [router.request(cfg, spec, rendered[i.key][1], rendered[i.key][2], schema, key=i.key) for i in take]
        provider = router.providers[ref.provider]
        failed = False
        for n, chunk in enumerate(_chunks(reqs, INLINE_LIMIT_BYTES), start=1):
            keys = [r.key or "" for r in chunk]
            job_name = f"{name}:{n}" if len(reqs) > len(chunk) else name
            try:
                provider_batch_id = provider.submit_batch(ref.model, chunk, job_name)
            except Exception as exc:
                err = _as_provider_error(exc, chunk[0])
                router.availability.record_failure(ref.provider, ref.model, err)
                result.reasons.append(f"{ref} batch submit failed: {err.kind}: {err.message[:120]}")
                log.warning("llm.batch_submit_failed", task=task, model=ref.model, kind=err.kind, error=err.message)
                failed = True
                break
            reserved = sum(estimate_by_key[k] for k in keys)
            version = rendered[keys[0]][0]
            try:
                with db.tx() as conn:
                    batch_id = store.insert_batch(
                        provider=ref.provider,
                        provider_batch_id=provider_batch_id,
                        task=task,
                        keys=keys,
                        model=ref.model,
                        prompt_version=version,
                        fallback_from=_fallback_from(cfg, ref),
                        reserved_inr=reserved,
                        conn=conn,
                    )
                    router.budget.reserve(batch_id, reserved, conn=conn)
            except Exception:
                # The provider has the job but we could not record it: cancel it so nothing is billed unseen.
                try:
                    provider.cancel_batch(provider_batch_id)
                finally:
                    raise
            router.availability.record_success(ref.provider, ref.model)
            result.jobs.append(
                SubmittedJob(batch_id, ref.provider, provider_batch_id, ref.model, keys, round(reserved, 4))
            )
            log.info(
                "llm.batch_submitted", task=task, model=ref.model, items=len(keys), reserved_inr=round(reserved, 2)
            )
        done = set(result.submitted_keys)
        remaining = [i for i in remaining if i.key not in done]
        if not failed and over:
            result.reasons.append(f"budget: {len(over)} items left for the next night")
            budget_stopped = True
            break

    if remaining and budget_stopped:
        result.deferred = [i.key for i in remaining]
    elif remaining:
        # No batch provider worked: run a few items now, synchronously, so the night is not wasted.
        result.reasons.append(f"no batch provider: up to {sync_fallback_limit} items run as sync calls")
        for index, item in enumerate(remaining):
            if index >= sync_fallback_limit:
                result.deferred.append(item.key)
                continue
            try:
                res = router.run_result(task, item.inputs)
            except BudgetExceeded as exc:
                result.reasons.append(f"budget: {exc.reason}")
                result.deferred.extend(i.key for i in remaining[index:])
                break
            except AllProvidersDown as exc:
                result.sync_results.append(ItemResult(key=item.key, error=str(exc), sync=True))
                continue
            result.sync_results.append(
                ItemResult(
                    key=item.key,
                    output=res.output,
                    provider=res.provider,
                    model=res.model,
                    tag=res.tag,
                    fallback_from=res.fallback_from,
                    inr=res.inr,
                    sync=True,
                )
            )
    router.stats.setdefault("batches", {}).setdefault(task, {"submitted": 0, "sync": 0, "deferred": 0})
    counters = router.stats["batches"][task]
    counters["submitted"] += len(result.submitted_keys)
    counters["sync"] += len(result.sync_results)
    counters["deferred"] += len(result.deferred)
    return result


def collect(
    router: Router,
    task: str | None = None,
    *,
    max_wait_s: float = 0.0,
    poll_s: float = 60.0,
    rebuild_inputs: Callable[[str], dict[str, Any] | None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectResult:
    """Poll open batches and ingest the finished ones (Step 4.10.2, 9.14).

    max_wait_s      keep polling until every batch is done or this many seconds have passed (0: poll once)
    rebuild_inputs  key -> prompt inputs, used to retry an invalid or failed item once as a sync call
    """
    out = CollectResult()
    deadline = time.monotonic() + max_wait_s
    while True:
        pending: list[str] = []
        for row in store.open_batches(task):
            batch_id = row["id"]
            provider = router.providers.get(row["provider"])
            if provider is None:
                pending.append(batch_id)
                continue
            meta = store.batch_meta(batch_id) or {}
            try:
                state = provider.poll_batch(row["provider_batch_id"])
            except Exception as exc:
                log.warning("llm.batch_poll_failed", batch=batch_id, error=str(exc)[:300])
                pending.append(batch_id)
                continue
            if state in ("pending", "running"):
                if state == "running" and row["status"] == "submitted":
                    store.set_batch_status(batch_id, "running")
                pending.append(batch_id)
                continue
            if state == "succeeded":
                try:
                    out.results.extend(_ingest(router, row, meta, rebuild_inputs))
                except (ProviderError, OSError) as exc:  # results not readable yet: try again next run
                    log.warning("llm.batch_fetch_failed", batch=batch_id, error=str(exc)[:300])
                    pending.append(batch_id)
                continue
            keys = list(meta.get("keys") or [])
            out.failed_keys.extend(keys)
            with db.tx() as conn:
                store.set_batch_status(batch_id, state, conn=conn)
                router.budget.release(batch_id, conn=conn)
                store.clear_batch_markers(batch_id, row["task"], keys, conn=conn)
            model = str(meta.get("model") or "")
            router.availability.record_failure(
                row["provider"],
                model,
                ProviderError("transient", f"batch {state}", provider=row["provider"], model=model),
            )
            log.warning("llm.batch_failed", batch=batch_id, state=state, items=len(keys))
        out.pending = pending
        remaining = deadline - time.monotonic()
        if not pending or remaining <= 0:
            return out
        sleep(min(poll_s, remaining))


def _ingest(
    router: Router,
    row: dict[str, Any],
    meta: dict[str, Any],
    rebuild_inputs: Callable[[str], dict[str, Any] | None] | None,
) -> list[ItemResult]:
    batch_id, task, provider_name = row["id"], row["task"], row["provider"]
    cfg = router.task(task)
    schema = cfg.schema_model
    provider = router.providers[provider_name]
    model = str(meta.get("model") or "")
    fallback_from = meta.get("fallback_from")
    version = int(meta.get("prompt_version") or 0)
    if not version:  # metadata row lost: fall back to the prompt file as it is now
        version = prompts.load(cfg.prompt).version
    keys = list(meta.get("keys") or [])
    rows = provider.fetch_batch(row["provider_batch_id"])
    if not model:
        model = next((r.response.model for r in rows if r.response is not None and r.response.model), "")

    results: list[ItemResult] = []
    retry: list[tuple[str, str]] = []
    costs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        key = r.key or ""
        seen.add(key)
        if r.response is None:
            retry.append((key, r.error or "no response"))
            continue
        usage = r.response.usage
        usd = router.budget.llm_cost_usd(
            model, usage.input_tokens, usage.output_tokens, cached_tokens=usage.cached_tokens, batch=True
        )
        costs.append(
            {
                "provider": provider_name,
                "model": model,
                "task": task,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "usd": usd,
                "fallback_from": fallback_from,
            }
        )
        try:
            output = router.parse_response(r.response, schema) if schema else TextOutput(text=r.response.text)
        except OutputInvalid as err:
            retry.append((key, f"invalid output: {err}"))
            continue
        results.append(
            ItemResult(
                key=key,
                output=output,
                provider=provider_name,
                model=model,
                tag=f"{provider_name}:{model}#{task}.v{version}",
                fallback_from=fallback_from,
                inr=round(router.budget.usd_to_inr(usd), 4),
            )
        )
    retry.extend((k, "missing from the batch results") for k in keys if k not in seen)

    router.budget.record_many(costs)
    with db.tx() as conn:
        store.set_batch_status(batch_id, "completed", conn=conn)
        router.budget.release(batch_id, conn=conn)
        store.clear_batch_markers(batch_id, task, keys, conn=conn)
    if model:
        router.availability.record_success(provider_name, model)
    log.info("llm.batch_collected", batch=batch_id, task=task, ok=len(results), retry=len(retry))

    if retry:
        chain_first = [ModelRef(provider=provider_name, model=model)] if model else []
        chain = chain_first + [r for r in cfg.chain if r not in chain_first]
        for key, why in retry:
            inputs = rebuild_inputs(key) if rebuild_inputs else None
            if inputs is None:
                results.append(ItemResult(key=key, error=why))
                continue
            try:
                res = router.run_result(task, inputs, models=chain, use_cache=False)
            except BudgetExceeded as exc:
                results.append(ItemResult(key=key, error=f"{why}; retry skipped: {exc.reason}"))
                continue
            except AllProvidersDown as exc:
                results.append(ItemResult(key=key, error=f"{why}; retry failed: {exc}"))
                continue
            results.append(
                ItemResult(
                    key=key,
                    output=res.output,
                    provider=res.provider,
                    model=res.model,
                    tag=res.tag,
                    fallback_from=res.fallback_from,
                    inr=res.inr,
                    sync=True,
                )
            )
    return results


def cancel_open(router: Router, task: str | None = None) -> list[str]:
    """Cancel every open batch (operations helper). Returns the llm_batches ids cancelled."""
    cancelled: list[str] = []
    for row in store.open_batches(task):
        provider = router.providers.get(row["provider"])
        if provider is None:
            continue
        meta = store.batch_meta(row["id"]) or {}
        try:
            provider.cancel_batch(row["provider_batch_id"])
        except Exception as exc:
            log.warning("llm.batch_cancel_failed", batch=row["id"], error=str(exc)[:300])
            continue
        with db.tx() as conn:
            store.set_batch_status(row["id"], "cancelled", conn=conn)
            router.budget.release(row["id"], conn=conn)
            store.clear_batch_markers(row["id"], row["task"], list(meta.get("keys") or []), conn=conn)
        cancelled.append(row["id"])
    return cancelled


def describe(result: SubmitResult | CollectResult) -> str:
    """One-line summary for logs and job summaries."""
    if isinstance(result, SubmitResult):
        return json.dumps(
            {
                "submitted": len(result.submitted_keys),
                "jobs": len(result.jobs),
                "sync": len(result.sync_results),
                "deferred": len(result.deferred),
                "in_flight": len(result.in_flight),
                "dry_run": result.dry_run,
            }
        )
    return json.dumps(
        {
            "ok": sum(1 for r in result.results if r.ok),
            "errors": sum(1 for r in result.results if not r.ok),
            "failed_keys": len(result.failed_keys),
            "pending": len(result.pending),
        }
    )
