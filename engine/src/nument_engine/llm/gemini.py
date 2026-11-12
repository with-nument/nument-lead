"""Gemini provider (google-genai): sync calls, structured output, Google Search grounding, Batch API (Step 4.6).

Two API keys are supported (GEMINI_API_KEY, then GEMINI_API_KEY_BACKUP). When a key fails with an auth,
billing or quota error, the provider switches to the next key for the rest of the process and retries once.
Batch jobs belong to the project of the key that created them, so polling tries every key.

Verified on 2026-11-12 against the API (Gemini 3.5 Flash-Lite, 3.8 Flash, 4 Argon):
- structured output works through `response_json_schema`;
- Gemini 3.8 Flash and Gemini 4 refuse thinking level "minimal" (400 INVALID_ARGUMENT);
- `temperature` is ignored by Gemini 3.5 and newer, so the router only sends it to models that use it;
- combining the google_search tool with a response schema returns no grounding metadata, so the router never
  does that for a task that needs citations;
- the Batch API ignores `response_json_schema`, so batch requests send `response_schema` instead.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from ..logging import get_logger
from .schema import provider_schema
from .types import BatchRow, BatchState, LLMRequest, LLMResponse, ModelInfo, Provider, ProviderError, Usage

log = get_logger("nlead.llm")

_DAILY_QUOTA_HINTS = ("perday", "per day", "per_day", "prepayment", "credits are depleted", "credit balance")
_ACCOUNT_HINTS = ("billing", "location is not supported", "user location", "account is not active", "suspended")
_SAFETY = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}

_JOB_STATES: dict[str, BatchState] = {
    "JOB_STATE_PENDING": "pending",
    "JOB_STATE_QUEUED": "pending",
    "JOB_STATE_RUNNING": "running",
    "JOB_STATE_UPDATING": "running",
    "JOB_STATE_PAUSED": "running",
    "JOB_STATE_CANCELLING": "running",
    "JOB_STATE_SUCCEEDED": "succeeded",
    "JOB_STATE_PARTIALLY_SUCCEEDED": "succeeded",
    "JOB_STATE_FAILED": "failed",
    "JOB_STATE_CANCELLED": "cancelled",
    "JOB_STATE_EXPIRED": "expired",
}


@lru_cache(maxsize=32)
def batch_schema(model: type[BaseModel]) -> types.Schema:
    """The provider schema converted to Gemini's Schema type (nullable fields, upper-case types)."""
    return types.Schema.from_json_schema(
        json_schema=types.JSONSchema.model_validate(provider_schema(model)), api_option="GEMINI_API"
    )


def classify_error(exc: BaseException, model: str = "") -> ProviderError:
    """Turn a google-genai or network exception into a ProviderError the router understands."""
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, genai_errors.APIError):
        code = int(exc.code or 0)
        status = str(exc.status or "")
        message = str(exc.message or exc)
        low = message.lower()
        details = json.dumps(exc.details, default=str).lower() if exc.details else ""
        both = f"{low} {details}"

        def err(kind: Any) -> ProviderError:
            return ProviderError(kind, f"{status} {message}".strip(), provider="gemini", model=model, status=code)

        if "limit: 0" in both:  # this model has no quota at all on this key
            return err("not_found")
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            return err("quota" if any(h in both for h in _DAILY_QUOTA_HINTS) else "transient")
        if code in (401, 403) or "api key not valid" in low or "api_key_invalid" in details:
            return err("auth")
        if code == 404 or status == "NOT_FOUND":
            return err("not_found")
        if code == 400:
            if status == "FAILED_PRECONDITION" or any(h in low for h in _ACCOUNT_HINTS):
                return err("auth")
            if "is not found" in low or "not supported for generatecontent" in low:
                return err("not_found")
            return err("bad_request")
        if code in (408, 499) or code >= 500:
            return err("transient")
        return err("unknown")
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError | TimeoutError | ConnectionError):
        return ProviderError("transient", f"{type(exc).__name__}: {exc}", provider="gemini", model=model)
    return ProviderError("unknown", f"{type(exc).__name__}: {exc}", provider="gemini", model=model)


def _finish(reason: Any) -> str | None:
    if reason is None:
        return None
    name = getattr(reason, "name", None) or str(reason)
    name = name.rsplit(".", 1)[-1].upper()
    if name == "STOP":
        return "stop"
    if name == "MAX_TOKENS":
        return "max_tokens"
    if name in _SAFETY:
        return "safety"
    return name.lower()


def _grounding(candidate: Any) -> dict[str, Any] | None:
    gm = getattr(candidate, "grounding_metadata", None) if candidate is not None else None
    if gm is None:
        return None
    queries = [q for q in (gm.web_search_queries or []) if q and q.strip()]
    sources = []
    for chunk in gm.grounding_chunks or []:
        web = getattr(chunk, "web", None)
        if web is not None and web.uri:
            sources.append({"uri": web.uri, "title": web.title or "", "domain": getattr(web, "domain", None)})
    supports = []
    for support in gm.grounding_supports or []:
        segment = getattr(support, "segment", None)
        supports.append(
            {
                "text": getattr(segment, "text", None) if segment else None,
                "chunks": list(support.grounding_chunk_indices or []),
            }
        )
    if not queries and not sources:
        return None
    return {"queries": list(dict.fromkeys(queries)), "sources": sources, "supports": supports}


def _usage(meta: Any) -> Usage:
    if meta is None:
        return Usage()
    prompt = getattr(meta, "prompt_token_count", None) or 0
    tool = getattr(meta, "tool_use_prompt_token_count", None) or 0
    candidates = getattr(meta, "candidates_token_count", None) or 0
    thoughts = getattr(meta, "thoughts_token_count", None) or 0
    cached = getattr(meta, "cached_content_token_count", None) or 0
    return Usage(
        input_tokens=prompt + tool,
        output_tokens=candidates + thoughts,
        cached_tokens=cached,
        thinking_tokens=thoughts,
    )


def _usage_from_dict(meta: dict[str, Any] | None) -> Usage:
    m = meta or {}

    def get(*names: str) -> int:
        for name in names:
            if m.get(name) is not None:
                return int(m[name])
        return 0

    prompt = get("promptTokenCount", "prompt_token_count")
    tool = get("toolUsePromptTokenCount", "tool_use_prompt_token_count")
    candidates = get("candidatesTokenCount", "candidates_token_count")
    thoughts = get("thoughtsTokenCount", "thoughts_token_count")
    cached = get("cachedContentTokenCount", "cached_content_token_count")
    return Usage(prompt + tool, candidates + thoughts, cached, thoughts)


def response_from_sdk(resp: Any, model: str) -> LLMResponse:
    """Normalise a GenerateContentResponse. Raises ProviderError for blocked or empty answers."""
    feedback = getattr(resp, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        raise ProviderError("blocked", f"prompt blocked: {feedback.block_reason}", provider="gemini", model=model)
    candidate = resp.candidates[0] if getattr(resp, "candidates", None) else None
    if candidate is None:
        raise ProviderError("blocked", "no candidates in the answer", provider="gemini", model=model)
    finish = _finish(getattr(candidate, "finish_reason", None))
    if finish == "safety":
        raise ProviderError("blocked", "answer stopped by a safety filter", provider="gemini", model=model)
    usage = _usage(getattr(resp, "usage_metadata", None))
    grounding = _grounding(candidate)
    if grounding:
        usage.search_queries = len(grounding["queries"])
    try:
        text = resp.text or ""
    except (ValueError, AttributeError):
        text = ""
    return LLMResponse(
        text=text,
        usage=usage,
        provider="gemini",
        model=model,
        finish_reason=finish,
        grounding=grounding,
        raw=resp,
    )


def response_from_dict(data: dict[str, Any], model: str) -> LLMResponse:
    """Normalise one JSON response line from a batch results file."""
    candidates = data.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    parts = ((candidate.get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    finish = _finish(candidate.get("finishReason") or candidate.get("finish_reason"))
    usage = _usage_from_dict(data.get("usageMetadata") or data.get("usage_metadata"))
    return LLMResponse(text=text, usage=usage, provider="gemini", model=model, finish_reason=finish)


class GeminiProvider:
    """google-genai wrapper. `client_factory` builds a client for a key (tests pass a fake)."""

    name: Provider = "gemini"

    def __init__(self, api_keys: list[str], *, client_factory: Callable[[str], Any] | None = None) -> None:
        keys = [k for k in api_keys if k]
        if not keys:
            raise ValueError("GeminiProvider needs at least one API key")
        self._keys = keys
        self._factory = client_factory or (lambda key: genai.Client(api_key=key))
        self._clients: dict[int, Any] = {}
        self._active = 0
        self._lock = threading.Lock()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    @property
    def active_key(self) -> int:
        """1-based number of the key in use (1 = GEMINI_API_KEY, 2 = GEMINI_API_KEY_BACKUP)."""
        return self._active + 1

    def _client(self, index: int) -> Any:
        with self._lock:
            if index not in self._clients:
                self._clients[index] = self._factory(self._keys[index])
            return self._clients[index]

    def _with_key_fallback(self, call: Callable[[Any], Any], model: str) -> Any:
        """Run `call(client)` on the active key; on auth or quota errors move to the next key and retry."""
        start = self._active
        last: ProviderError | None = None
        for index in range(start, len(self._keys)):
            try:
                return call(self._client(index))
            except Exception as exc:
                err = classify_error(exc, model)
                if err.kind not in ("auth", "quota") or index + 1 >= len(self._keys):
                    raise err from None
                last = err
                with self._lock:
                    if self._active == index:
                        self._active = index + 1
                log.warning("llm.gemini_key_switch", from_key=index + 1, to_key=index + 2, reason=err.kind)
        assert last is not None
        raise last

    # ---- requests -------------------------------------------------------------

    @staticmethod
    def build_config(req: LLMRequest, *, for_batch: bool = False) -> types.GenerateContentConfig:
        cfg: dict[str, Any] = {"max_output_tokens": req.max_output_tokens}
        if req.system:
            cfg["system_instruction"] = req.system
        if req.temperature is not None:
            cfg["temperature"] = req.temperature
        if req.thinking:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_level=types.ThinkingLevel(req.thinking.upper()))
        if req.schema is not None:
            cfg["response_mime_type"] = "application/json"
            if for_batch:
                # Verified 2026-11-12: the Batch API ignores responseJsonSchema (answers came back in free-form
                # JSON), so batch requests carry the same schema as Gemini's own responseSchema.
                cfg["response_schema"] = batch_schema(req.schema)
            else:
                cfg["response_json_schema"] = provider_schema(req.schema)
        if "web_search" in req.tools:
            cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        if req.service_tier == "flex":
            cfg["service_tier"] = types.ServiceTier.FLEX
        if not for_batch:
            cfg["http_options"] = types.HttpOptions(timeout=int(req.timeout_s * 1000))
            cfg["automatic_continuation"] = False  # keep spend bounded by max_output_tokens
        return types.GenerateContentConfig(**cfg)

    def generate(self, req: LLMRequest) -> LLMResponse:
        config = self.build_config(req)

        def call(client: Any) -> Any:
            return client.models.generate_content(model=req.model, contents=req.user, config=config)

        resp = self._with_key_fallback(call, req.model)
        return response_from_sdk(resp, req.model)

    # ---- batch ----------------------------------------------------------------

    def submit_batch(self, model: str, reqs: list[LLMRequest], display_name: str) -> str:
        """Inline batch (the caller keeps each job under the 20 MB inline limit). Returns the job name."""
        src = [
            types.InlinedRequest(
                contents=[types.Content(role="user", parts=[types.Part(text=r.user)])],
                config=self.build_config(r, for_batch=True),
                metadata={"key": r.key or str(i)},
            )
            for i, r in enumerate(reqs)
        ]

        def call(client: Any) -> Any:
            return client.batches.create(
                model=model, src=src, config=types.CreateBatchJobConfig(display_name=display_name[:120])
            )

        job = self._with_key_fallback(call, model)
        return str(job.name)

    def _get_job(self, name: str) -> Any:
        """A job belongs to the project of the key that created it: try every key."""
        last: ProviderError | None = None
        order = [self._active, *[i for i in range(len(self._keys)) if i != self._active]]
        for index in order:
            try:
                return self._client(index).batches.get(name=name)
            except Exception as exc:
                err = classify_error(exc)
                if err.kind not in ("not_found", "auth"):
                    raise err from None
                last = err
        assert last is not None
        raise last

    def poll_batch(self, batch_id: str) -> BatchState:
        job = self._get_job(batch_id)
        state = getattr(job.state, "name", None) or str(job.state)
        return _JOB_STATES.get(state.rsplit(".", 1)[-1], "running")

    def fetch_batch(self, batch_id: str) -> list[BatchRow]:
        job = self._get_job(batch_id)
        model = str(job.model or "").removeprefix("models/")
        rows: list[BatchRow] = []
        dest = job.dest
        if dest is not None and dest.inlined_responses:
            for i, item in enumerate(dest.inlined_responses):
                key = (item.metadata or {}).get("key") if item.metadata else None
                key = key or str(i)
                if item.error is not None or item.response is None:
                    message = getattr(item.error, "message", None) or str(item.error or "no response")
                    rows.append(BatchRow(key=key, response=None, error=message))
                    continue
                try:
                    rows.append(BatchRow(key=key, response=response_from_sdk(item.response, model), error=None))
                except ProviderError as err:
                    rows.append(BatchRow(key=key, response=None, error=f"{err.kind}: {err.message}"))
        elif dest is not None and dest.file_name:
            content = self._client(self._active).files.download(file=dest.file_name)
            for line in bytes(content).decode("utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                key = data.get("key")
                if data.get("error") or not data.get("response"):
                    rows.append(BatchRow(key=key, response=None, error=json.dumps(data.get("error"))[:500]))
                else:
                    rows.append(BatchRow(key=key, response=response_from_dict(data["response"], model), error=None))
        return rows

    def cancel_batch(self, batch_id: str) -> None:
        self._get_job(batch_id)  # find the key that owns it first
        for index in range(len(self._keys)):
            try:
                self._client(index).batches.cancel(name=batch_id)
                return
            except Exception as exc:
                err = classify_error(exc)
                if err.kind not in ("not_found", "auth"):
                    raise err from None

    # ---- models ---------------------------------------------------------------

    def list_models(self) -> list[ModelInfo]:
        def call(client: Any) -> list[ModelInfo]:
            return [
                ModelInfo(name=str(m.name).removeprefix("models/"), actions=list(m.supported_actions or []))
                for m in client.models.list()
            ]

        result: list[ModelInfo] = self._with_key_fallback(call, "")
        return result
