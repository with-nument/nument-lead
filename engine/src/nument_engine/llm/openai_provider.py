"""OpenAI provider: Responses API with strict JSON schema output, web search, Batch API (Step 4.7).

OpenAI is switched off today (`settings.providers_enabled.openai = false`): the key returned 401 when the
engine was built on 2026-11-12. This module is exercised by unit tests with a fake client and is used as
soon as the founder adds a working key and switches the provider on.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import openai

from .schema import provider_schema
from .types import BatchRow, BatchState, LLMRequest, LLMResponse, ModelInfo, Provider, ProviderError, Usage

_STATES: dict[str, BatchState] = {
    "validating": "pending",
    "in_progress": "running",
    "finalizing": "running",
    "cancelling": "running",
    "completed": "succeeded",
    "failed": "failed",
    "expired": "expired",
    "cancelled": "cancelled",
}


def classify_error(exc: BaseException, model: str = "") -> ProviderError:
    """Turn an OpenAI SDK or network exception into a ProviderError."""
    if isinstance(exc, ProviderError):
        return exc

    def err(kind: Any, status: int | None = None) -> ProviderError:
        return ProviderError(kind, f"{type(exc).__name__}: {exc}", provider="openai", model=model, status=status)

    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return err("auth", getattr(exc, "status_code", None))
    if isinstance(exc, openai.RateLimitError):
        text = str(exc).lower()
        kind = "quota" if "insufficient_quota" in text or "billing" in text else "transient"
        return err(kind, 429)
    if isinstance(exc, openai.NotFoundError):
        return err("not_found", 404)
    if isinstance(exc, openai.BadRequestError):
        return err("bad_request", 400)
    if isinstance(exc, openai.APITimeoutError | openai.APIConnectionError):
        return err("transient")
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        return err("transient" if status in (408, 409) or status >= 500 else "unknown", status)
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError | TimeoutError | ConnectionError):
        return err("transient")
    return err("unknown")


def _text_format(req: LLMRequest) -> dict[str, Any] | None:
    if req.schema is None:
        return None
    return {
        "format": {
            "type": "json_schema",
            "name": req.schema.__name__,
            "schema": provider_schema(req.schema),
            "strict": True,
        }
    }


def _body(req: LLMRequest, model: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "input": req.user,
        "max_output_tokens": req.max_output_tokens,
    }
    if req.system:
        body["instructions"] = req.system
    if req.thinking:
        body["reasoning"] = {"effort": req.thinking}
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if "web_search" in req.tools:
        body["tools"] = [{"type": "web_search"}]
    text = _text_format(req)
    if text is not None:
        body["text"] = text
    if req.service_tier == "flex":
        body["service_tier"] = "flex"
    return body


def _usage(u: Any) -> Usage:
    if u is None:
        return Usage()
    get = (lambda k: u.get(k)) if isinstance(u, dict) else (lambda k: getattr(u, k, None))
    details = get("input_tokens_details") or {}
    cached = details.get("cached_tokens") if isinstance(details, dict) else getattr(details, "cached_tokens", 0)
    out_details = get("output_tokens_details") or {}
    reasoning = (
        out_details.get("reasoning_tokens")
        if isinstance(out_details, dict)
        else getattr(out_details, "reasoning_tokens", 0)
    )
    return Usage(
        input_tokens=int(get("input_tokens") or 0),
        output_tokens=int(get("output_tokens") or 0),
        cached_tokens=int(cached or 0),
        thinking_tokens=int(reasoning or 0),
    )


def _finish(status: Any, incomplete: Any) -> str | None:
    if status == "completed":
        return "stop"
    reason = getattr(incomplete, "reason", None) if incomplete is not None else None
    if isinstance(incomplete, dict):
        reason = incomplete.get("reason")
    if reason == "max_output_tokens":
        return "max_tokens"
    if reason == "content_filter":
        return "safety"
    return str(status) if status else None


class OpenAIProvider:
    """OpenAI SDK wrapper. `client_factory` builds the client (tests pass a fake)."""

    name: Provider = "openai"

    def __init__(self, api_key: str, *, client_factory: Callable[[str], Any] | None = None) -> None:
        if not api_key:
            raise ValueError("OpenAIProvider needs an API key")
        self._client = (client_factory or (lambda key: openai.OpenAI(api_key=key, timeout=120, max_retries=0)))(api_key)

    def generate(self, req: LLMRequest) -> LLMResponse:
        body = _body(req, req.model)
        try:
            resp = self._client.responses.create(**body, timeout=req.timeout_s)
        except Exception as exc:
            raise classify_error(exc, req.model) from None
        finish = _finish(getattr(resp, "status", None), getattr(resp, "incomplete_details", None))
        if finish == "safety":
            raise ProviderError("blocked", "answer stopped by a content filter", provider="openai", model=req.model)
        usage = _usage(getattr(resp, "usage", None))
        output = getattr(resp, "output", None) or []
        usage.search_queries = sum(1 for o in output if getattr(o, "type", "") == "web_search_call")
        return LLMResponse(
            text=getattr(resp, "output_text", "") or "",
            usage=usage,
            provider="openai",
            model=req.model,
            finish_reason=finish,
            raw=resp,
        )

    # ---- batch ----------------------------------------------------------------

    def submit_batch(self, model: str, reqs: list[LLMRequest], display_name: str) -> str:
        lines = [
            json.dumps(
                {"custom_id": r.key or str(i), "method": "POST", "url": "/v1/responses", "body": _body(r, model)}
            )
            for i, r in enumerate(reqs)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.jsonl"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                with path.open("rb") as handle:
                    uploaded = self._client.files.create(file=handle, purpose="batch")
                batch = self._client.batches.create(
                    input_file_id=uploaded.id,
                    endpoint="/v1/responses",
                    completion_window="24h",
                    metadata={"display_name": display_name[:120]},
                )
            except Exception as exc:
                raise classify_error(exc, model) from None
        return str(batch.id)

    def poll_batch(self, batch_id: str) -> BatchState:
        try:
            status = self._client.batches.retrieve(batch_id).status
        except Exception as exc:
            raise classify_error(exc) from None
        return _STATES.get(str(status), "running")

    def fetch_batch(self, batch_id: str) -> list[BatchRow]:
        try:
            batch = self._client.batches.retrieve(batch_id)
            rows: list[BatchRow] = []
            if batch.output_file_id:
                for line in self._client.files.content(batch.output_file_id).text.splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    body = (row.get("response") or {}).get("body") or {}
                    if (row.get("response") or {}).get("status_code", 200) >= 400 or row.get("error"):
                        rows.append(BatchRow(key=row.get("custom_id"), response=None, error=json.dumps(row)[:500]))
                        continue
                    text = "".join(
                        c.get("text", "")
                        for o in body.get("output", [])
                        if o.get("type") == "message"
                        for c in (o.get("content") or [])
                    )
                    resp = LLMResponse(
                        text=text,
                        usage=_usage(body.get("usage")),
                        provider="openai",
                        model=str(body.get("model", "")),
                        finish_reason=_finish(body.get("status"), body.get("incomplete_details")),
                    )
                    rows.append(BatchRow(key=row.get("custom_id"), response=resp, error=None))
            if batch.error_file_id:
                for line in self._client.files.content(batch.error_file_id).text.splitlines():
                    if line.strip():
                        row = json.loads(line)
                        rows.append(BatchRow(key=row.get("custom_id"), response=None, error=json.dumps(row)[:500]))
        except ProviderError:
            raise
        except Exception as exc:
            raise classify_error(exc) from None
        return rows

    def cancel_batch(self, batch_id: str) -> None:
        try:
            self._client.batches.cancel(batch_id)
        except Exception as exc:
            raise classify_error(exc) from None

    def list_models(self) -> list[ModelInfo]:
        try:
            return [ModelInfo(name=m.id) for m in self._client.models.list()]
        except Exception as exc:
            raise classify_error(exc) from None
