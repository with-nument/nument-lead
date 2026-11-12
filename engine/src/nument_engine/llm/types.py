"""Types shared by the AI router and its providers (Step 4.6.1): requests, responses, errors.

Providers turn every SDK exception into a `ProviderError` with a `kind`, so the router's retry, failover and
circuit-breaker decisions never depend on SDK exception classes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Provider = Literal["gemini", "openai"]
Thinking = Literal["off", "low", "medium", "high"]
ServiceTier = Literal["standard", "flex"]

ErrorKind = Literal[
    "transient",  # network error, timeout, 429 rate limit, 5xx: retry, then fail over
    "auth",  # bad key, permission, billing: the provider is out for hours
    "quota",  # daily or account quota used up: the provider is out for hours
    "not_found",  # the model id does not exist (any more): skip this model for the run
    "bad_request",  # the provider refused this request (schema too complex, bad parameter): try the next model
    "blocked",  # safety block or empty answer: try the next model
    "truncated",  # the answer hit the output cap before it finished
    "unknown",  # anything else: not retried, logged as an error
]


class LLMError(Exception):
    """Base class for AI router errors."""


class ProviderError(LLMError):
    """One failed provider call, classified so the router knows whether to retry, fail over or trip a breaker."""

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        status: int | None = None,
    ) -> None:
        self.kind: ErrorKind = kind
        self.message = redact(message)
        self.provider = provider
        self.model = model
        self.status = status
        super().__init__(f"{provider or 'provider'} {model} {kind}{f' {status}' if status else ''}: {self.message}")


class AllProvidersDown(LLMError):
    """No model in the task's chain could answer. The step skips the item; the run ends `partial`."""

    def __init__(self, task: str, attempts: list[str]) -> None:
        self.task = task
        self.attempts = attempts
        detail = "; ".join(attempts) if attempts else "no model in the chain"
        super().__init__(f"{task}: no usable provider ({detail})")


class OutputInvalid(LLMError):
    """The model answered, but the answer did not match the task's schema (after one repair, when raised
    out of the router). `truncated` means the answer was cut off at the output token cap."""

    def __init__(self, message: str, *, truncated: bool = False) -> None:
        super().__init__(message)
        self.truncated = truncated


@dataclass
class LLMRequest:
    """One provider call, already rendered."""

    task: str
    provider: Provider
    model: str
    system: str
    user: str
    schema: type[BaseModel] | None  # validated by the router; providers send its JSON schema
    max_output_tokens: int  # what the provider receives, thinking included
    temperature: float | None  # None: do not send (the model does not accept sampling parameters)
    thinking: str | None  # provider-specific level (minimal, low, medium, high) or None
    tools: list[str] = field(default_factory=list)
    timeout_s: int = 60
    service_tier: ServiceTier = "standard"
    key: str | None = None  # stable id for batch items, for example "extract_facts:<business_id>"


@dataclass
class Usage:
    input_tokens: int = 0  # billed input, including tool prompts
    output_tokens: int = 0  # billed output, including thinking or reasoning tokens
    cached_tokens: int = 0  # part of input_tokens served from the provider's cache
    thinking_tokens: int = 0  # part of output_tokens spent on thinking
    search_queries: int = 0  # Gemini grounding queries or OpenAI web_search calls

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_tokens + other.cached_tokens,
            self.thinking_tokens + other.thinking_tokens,
            self.search_queries + other.search_queries,
        )


@dataclass
class LLMResponse:
    text: str
    usage: Usage
    provider: Provider
    model: str
    finish_reason: str | None = None  # normalised: stop, max_tokens, safety, other
    grounding: dict[str, Any] | None = None  # {"queries": [...], "sources": [{"uri", "title"}], "supports": [...]}
    raw: Any = None


BatchState = Literal["pending", "running", "succeeded", "failed", "cancelled", "expired"]
BATCH_DONE_STATES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "expired"})


@dataclass
class BatchRow:
    """One result line of a finished batch."""

    key: str | None
    response: LLMResponse | None
    error: str | None


@dataclass
class ModelInfo:
    """One model a provider says is available to this key."""

    name: str  # bare id, for example gemini-3.8-flash
    actions: list[str] = field(default_factory=list)  # generateContent, batchGenerateContent, ...


class LLMProvider(Protocol):
    """What the router needs from a provider. GeminiProvider and OpenAIProvider implement it; tests use fakes."""

    name: Provider

    def generate(self, req: LLMRequest) -> LLMResponse: ...

    def submit_batch(self, model: str, reqs: list[LLMRequest], display_name: str) -> str: ...

    def poll_batch(self, batch_id: str) -> BatchState: ...

    def fetch_batch(self, batch_id: str) -> list[BatchRow]: ...

    def cancel_batch(self, batch_id: str) -> None: ...

    def list_models(self) -> list[ModelInfo]: ...


_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"sk-[A-Za-z0-9_\-*]{8,}"),  # OpenAI keys, including masked ones
    re.compile(r"(?i)([?&](?:key|api_key|access_token)=)[^&\s'\"]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"),
)


def redact(text: str, limit: int = 500) -> str:
    """Remove anything that looks like a credential and cap the length. Used on every provider error message."""
    out = str(text)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "[redacted]", out)
    out = " ".join(out.split())
    return out if len(out) <= limit else out[: limit - 3] + "..."
