"""Which providers and models may be called right now: switches, keys and circuit breakers (Step 4.5).

A provider is skipped when it is switched off (`settings.providers_enabled`), has no API key, or its circuit
breaker is open. Breakers work at two levels:

- **Provider** (persisted in `source_health` as `llm:gemini` and `llm:openai`, so the next run respects a
  cool-off that is still running):
  - auth, billing or quota-exhausted errors open it at once for 6 hours;
  - 3 transient failures in a row (on any of its models) open it for 15 minutes;
  - after a cool-off the next call is a trial: success closes it, failure opens it again for twice as long
    (at most 24 hours);
  - any success resets it.
- **Model** (in memory, this run only): 3 transient failures in a row on one model open it for 15 minutes,
  and a model the provider says does not exist is skipped for the rest of the run. One overloaded model
  therefore moves work to the next model in the chain without taking the whole provider out.

Request-specific errors (bad request, safety block, invalid output) never trip a breaker: the next model in
the chain simply gets the request.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging import get_logger
from . import store
from .types import Provider, ProviderError

log = get_logger("nlead.llm")

PROVIDERS: tuple[Provider, ...] = ("gemini", "openai")
FAILURES_TO_TRIP = 3
BASE_COOLOFF = timedelta(minutes=15)
MAX_COOLOFF = timedelta(hours=24)
AUTH_COOLOFF = timedelta(hours=6)
HARD_KINDS = frozenset({"auth", "quota"})


def health_source(provider: str) -> str:
    return f"llm:{provider}"


@dataclass
class Breaker:
    """One provider's breaker."""

    provider: str
    failures: int = 0
    open_until: datetime | None = None
    cooloff: timedelta = BASE_COOLOFF
    tripped: bool = False  # opened at least once since the last success: the next failure is a failed trial

    def is_open(self, now: datetime) -> bool:
        return self.open_until is not None and now < self.open_until

    def success(self) -> bool:
        """Reset. Returns True if the state changed (worth persisting)."""
        changed = self.failures > 0 or self.open_until is not None or self.tripped
        self.failures, self.open_until, self.cooloff, self.tripped = 0, None, BASE_COOLOFF, False
        return changed

    def failure(self, err: ProviderError, now: datetime) -> bool:
        """Count a failure. Returns True if the breaker opened."""
        if err.kind in HARD_KINDS:
            self.open_until, self.tripped = now + AUTH_COOLOFF, True
            return True
        if err.kind != "transient":
            return False
        if self.tripped and not self.is_open(now):
            # failed trial after a cool-off: open again, twice as long
            self.cooloff = min(self.cooloff * 2, MAX_COOLOFF)
            self.open_until = now + self.cooloff
            return True
        self.failures += 1
        if self.failures >= FAILURES_TO_TRIP:
            self.open_until, self.tripped, self.failures = now + self.cooloff, True, 0
            return True
        return False


@dataclass
class ModelHealth:
    failures: int = 0
    open_until: datetime | None = None
    missing: bool = False
    last_error: str = ""


@dataclass
class Availability:
    """Provider switches, keys and breakers for one run."""

    enabled: dict[str, bool]
    has_key: dict[str, bool]
    breakers: dict[str, Breaker] = field(default_factory=dict)
    persist: bool = True
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    models: dict[str, ModelHealth] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _ok_persisted: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        for provider in PROVIDERS:
            self.breakers.setdefault(provider, Breaker(provider))

    @classmethod
    def load(
        cls,
        *,
        has_key: dict[str, bool],
        app_env: str,
        clock: Callable[[], datetime] | None = None,
        enabled_override: dict[str, bool] | None = None,
    ) -> Availability:
        """Read `settings.providers_enabled` and the persisted breakers from the database."""
        default: dict[str, bool] = {"gemini": True, "openai": app_env == "prod"}
        raw = store.get_setting("providers_enabled", default) or default
        enabled: dict[str, bool] = {p: bool(raw.get(p, default[p])) for p in PROVIDERS}
        if enabled_override:
            enabled.update(enabled_override)
        clock = clock or (lambda: datetime.now(UTC))
        now = clock()
        rows = store.health_rows([health_source(p) for p in PROVIDERS])
        breakers: dict[str, Breaker] = {}
        for provider in PROVIDERS:
            row = rows.get(health_source(provider)) or {}
            until = row.get("blocked_until")
            breaker = Breaker(provider)
            if until is not None and until > now:
                breaker.open_until, breaker.tripped = until, True
            breakers[provider] = breaker
            if row and row.get("enabled") is not enabled[provider]:
                store.health_set_enabled(health_source(provider), enabled[provider])
        return cls(enabled=enabled, has_key=has_key, breakers=breakers, clock=clock)

    # ---- questions --------------------------------------------------------

    def provider_reason(self, provider: str) -> str | None:
        """None if the provider may be called, else why not."""
        with self._lock:
            if not self.enabled.get(provider, False):
                return f"providers_enabled.{provider} = false"
            if not self.has_key.get(provider, False):
                return f"no {provider} API key"
            breaker = self.breakers[provider]
            now = self.clock()
            if breaker.is_open(now):
                assert breaker.open_until is not None
                return f"{provider} circuit breaker open until {breaker.open_until.isoformat(timespec='minutes')}"
            return None

    def model_reason(self, provider: str, model: str) -> str | None:
        reason = self.provider_reason(provider)
        if reason:
            return reason
        with self._lock:
            health = self.models.get(f"{provider}:{model}")
            if health is None:
                return None
            if health.missing:
                return f"{model} is not available on this key ({health.last_error})"
            if health.open_until is not None and self.clock() < health.open_until:
                return f"{model} paused after repeated failures"
            return None

    def usable(self, provider: str) -> bool:
        return self.provider_reason(provider) is None

    # ---- events -----------------------------------------------------------

    def record_success(self, provider: str, model: str) -> None:
        with self._lock:
            changed = self.breakers[provider].success()
            self.models.pop(f"{provider}:{model}", None)
            first = provider not in self._ok_persisted
            self._ok_persisted.add(provider)
        if self.persist and (changed or first):
            store.health_ok(health_source(provider))

    def record_failure(self, provider: str, model: str, err: ProviderError) -> None:
        now = self.clock()
        with self._lock:
            health = self.models.setdefault(f"{provider}:{model}", ModelHealth())
            health.last_error = err.message[:200]
            if err.kind == "not_found":
                health.missing = True
            elif err.kind == "transient":
                health.failures += 1
                if health.failures >= FAILURES_TO_TRIP:
                    health.open_until, health.failures = now + BASE_COOLOFF, 0
            breaker = self.breakers[provider]
            opened = breaker.failure(err, now)
            blocked_until = breaker.open_until if breaker.is_open(now) else None
        if opened:
            log.warning(
                "llm.breaker_open",
                provider=provider,
                model=model,
                kind=err.kind,
                until=blocked_until.isoformat() if blocked_until else None,
            )
        if self.persist and (opened or err.kind in HARD_KINDS or err.kind == "transient"):
            store.health_error(health_source(provider), f"{model}: {err.kind}: {err.message}", blocked_until)

    def snapshot(self) -> dict[str, Any]:
        """State for logs and `nlead health`."""
        now = self.clock()
        with self._lock:
            return {
                p: {
                    "enabled": self.enabled.get(p, False),
                    "has_key": self.has_key.get(p, False),
                    "open_until": b.open_until.isoformat() if b.is_open(now) and b.open_until else None,
                }
                for p, b in self.breakers.items()
            }
