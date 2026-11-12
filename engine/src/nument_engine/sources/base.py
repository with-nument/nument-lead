"""What every source adapter shares (Step 5.3): the raw record, the signal object, the run context, the AI router
contract and the adapter base class with its kill switch and block handling.

Dependency direction: `pipeline/*` imports `sources/*`, never the other way round. That is why `Signal` and the
signal constants of A.12.3 live here; `pipeline/signals.py` re-exports them under the names the plan uses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, ClassVar, Protocol, Self, TypeVar

import httpx

from ..http import MAX_BYTES, Policy, PoliteClient, SourceBlocked
from ..logging import get_logger
from ..models import SIGNAL_CATEGORY
from . import health

log = get_logger()

T = TypeVar("T")

# ---------------------------------------------------------------------------------------------------
# Signals (A.12.3, Step 7.4)
# ---------------------------------------------------------------------------------------------------

WINDOW_DAYS: dict[str, int | None] = {
    "public_ask": 14,
    "tender": None,  # until the submission deadline
    "hiring_builder": 30,
    "hiring_frontdesk": 30,
    "review_pain": 90,
    "ads_running": 30,
    "no_booking": 60,
    "slow_site": 60,
    "new_place": 60,
    "new_branch": 60,
    "news": 30,
    "funding": 120,
}
CATEGORY: dict[str, str] = dict(SIGNAL_CATEGORY)
DEFAULT_POINTS: dict[str, float] = {
    "public_ask": 10,
    "tender": 10,
    "hiring_builder": 8,
    "hiring_frontdesk": 8,
    "review_pain": 6,
    "ads_running": 4,
    "no_booking": 3,
    "slow_site": 2,
    "new_place": 5,
    "new_branch": 5,
    "news": 3,
    "funding": 0,
}
SNIPPET_ONLY_POINTS = 6.0  # a public ask seen only as a LinkedIn or X search snippet (Step 5.11.2)
QUOTE_MAX = 300  # Step 7.4.4: quotes are 5 to 300 characters


@dataclass
class Signal:
    """Dated evidence that a business needs help now. `business_id` or `business_hint` identifies the business."""

    type: str
    source: str
    observed_at: datetime
    url: str | None
    quote: str | None
    evidence_key: str  # stable id of the evidence: job id, canonical URL, place_id|YYYY-MM, ...
    business_id: str | None = None
    business_hint: dict[str, Any] = field(default_factory=dict)  # name, website, city, address, phone
    details: dict[str, Any] = field(default_factory=dict)
    deadline: datetime | None = None  # tenders only
    points: float | None = None  # None: the segment's points for the type (Step 7.4.2)
    segment_id: str | None = None  # route to another segment than the one being processed (Step 7.5.1)

    def window(self) -> timedelta | None:
        days = WINDOW_DAYS[self.type]
        return None if days is None else timedelta(days=days)


# ---------------------------------------------------------------------------------------------------
# Raw records from sources (Step 5.3.1)
# ---------------------------------------------------------------------------------------------------


@dataclass
class SourceRecord:
    """One raw record from one source. Many records map to one business (Step 6)."""

    source: str
    source_key: str
    segment_id: str
    name: str | None = None
    website: str | None = None
    phones_raw: list[str] = field(default_factory=list)  # hints only unless `phones_are_listing` (A.4.3)
    emails: list[str] = field(default_factory=list)
    address: str | None = None
    city: str | None = None
    locality: str | None = None
    lat: float | None = None
    lng: float | None = None
    category: str | None = None
    subcategory: str | None = None
    place_id: str | None = None
    overture_id: str | None = None
    rating: float | None = None
    review_count: int | None = None
    business_status: str | None = None  # Places businessStatus (OPERATIONAL, CLOSED_PERMANENTLY, ...)
    phones_are_listing: bool = False  # Places listing phones: stored as `google_listing` contacts (fallback)
    emails_are_registry: bool = False  # registry emails: stored as `registry` contacts
    observed_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)  # slim raw fields we are allowed to keep


# ---------------------------------------------------------------------------------------------------
# AI router contract (Step 4.10). Builder of llm/ provides the real one; tests use a fake.
# ---------------------------------------------------------------------------------------------------


class AIRouter(Protocol):
    """The part of `llm.router.Router` the collect and research stages use."""

    def run(self, task: str, inputs: dict[str, Any], *, lead_id: str | None = None, cache_extra: str = "") -> Any: ...


# The router raises these when the budget or every provider says no (Step 4.1.2 rules 4 and 5). They are matched
# by name so this package does not import llm/ or budget.py.
AI_STOP_ERRORS = frozenset({"BudgetExceeded", "BudgetStop", "AllProvidersDown"})


def is_ai_stop(exc: BaseException) -> bool:
    """True when the router refused the call for budget or provider reasons: stop AI work for this stage."""
    return any(cls.__name__ in AI_STOP_ERRORS for cls in type(exc).__mro__)


def field_of(obj: Any, name: str, default: Any = None) -> Any:
    """Read `name` from a pydantic model, dataclass or dict alike."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ---------------------------------------------------------------------------------------------------
# Run context for adapters
# ---------------------------------------------------------------------------------------------------


@dataclass
class SourceContext:
    """What an adapter needs from the run: ids, flags, the AI router and a place for counters and alerts."""

    run_id: str | None = None
    dry_run: bool = False
    limit: int | None = None
    router: AIRouter | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    ai_stopped: str | None = None  # set when the router refused (budget, providers): no more AI calls this stage

    @classmethod
    def from_run(cls, rc: Any, router: AIRouter | None = None) -> SourceContext:
        """From a `pipeline.runs.RunContext`. The router comes from the argument or `rc.router` when present."""
        opts = getattr(rc, "opts", None)
        return cls(
            run_id=getattr(rc, "run_id", None),
            dry_run=bool(getattr(opts, "dry_run", False)),
            limit=getattr(opts, "limit", None),
            router=router if router is not None else getattr(rc, "router", None),
        )

    def add(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def alert(self, message: str) -> None:
        if message not in self.alerts:
            self.alerts.append(message)
        log.warning("run.alert", message=message)

    def ai(self, task: str, inputs: dict[str, Any]) -> Any | None:
        """One AI call through the router. Returns None (and records why) when there is no router, when the
        budget or every provider refused, or when this item failed. Never raises for AI problems."""
        if self.router is None:
            self.add(f"ai_skipped.{task}.no_router")
            return None
        if self.ai_stopped:
            self.add(f"ai_skipped.{task}.stopped")
            return None
        try:
            return self.router.run(task, inputs)
        except Exception as exc:  # the router's own errors are typed; anything else is one bad item
            if is_ai_stop(exc):
                self.ai_stopped = f"{type(exc).__name__}: {exc}"
                self.add(f"ai_skipped.{task}.{type(exc).__name__}")
                log.warning("ai.stopped", task=task, reason=str(exc)[:200])
                return None
            self.add(f"ai_errors.{task}")
            log.warning("ai.error", task=task, error=f"{type(exc).__name__}: {str(exc)[:200]}")
            return None


# ---------------------------------------------------------------------------------------------------
# Adapter base class (Step 5.3.2)
# ---------------------------------------------------------------------------------------------------


class SourceAdapter:
    """Base for every adapter. Subclasses set `name` and `policy`, and implement what they support:
    `discover` (businesses for the universe), `signals` (signal rows) or `enrich` (facts for one business)."""

    name: ClassVar[str]
    policy: ClassVar[Policy]
    min_gap_s: ClassVar[float | None] = None
    max_bytes: ClassVar[int] = MAX_BYTES

    def __init__(self, ctx: SourceContext, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.ctx = ctx
        self._transport = transport
        self._http: PoliteClient | None = None
        self._flushed_requests = 0

    @property
    def http(self) -> PoliteClient:
        if self._http is None:
            self._http = PoliteClient(
                self.name,
                policy=self.policy,
                min_gap_s=self.min_gap_s,
                max_bytes=self.max_bytes,
                transport=self._transport,
            )
        return self._http

    def new_requests(self) -> int:
        """Requests made since the last call (so each is counted once in source_health)."""
        total = self._http.requests if self._http else 0
        fresh = total - self._flushed_requests
        self._flushed_requests = total
        return fresh

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---- switches and health ---------------------------------------------------------------------------
    def status(self) -> tuple[bool, str]:
        return health.source_status(self.name)

    def enabled(self) -> bool:
        return self.status()[0]

    def health_ok(self) -> None:
        health.mark_ok(self.name, requests=self.new_requests())

    def health_error(self, message: str, *, blocked_until: datetime | None = None) -> None:
        health.mark_error(self.name, message, blocked_until=blocked_until, requests=self.new_requests())

    def health_blocked(self, err: SourceBlocked, *, until: datetime | None = None) -> datetime:
        end = health.record_block(
            self.name,
            f"{err.host}: {err.reason}",
            grey=self.policy == "grey",
            until=until,
            requests=self.new_requests(),
        )
        self.ctx.alert(f"{self.name} blocked at {err.host} ({err.reason}); paused until {end:%Y-%m-%d %H:%M} UTC")
        return end

    async def safe_call(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T | None:
        """Run one adapter call behind the kill switch. A block pauses the source and returns None."""
        usable, why = self.status()
        if not usable:
            self.ctx.add(f"skipped.{self.name}")
            self.ctx.stats.setdefault("skip_reasons", {})[self.name] = why
            return None
        try:
            out = await fn(*args, **kwargs)
        except SourceBlocked as err:
            self.health_blocked(err)
            return None
        self.health_ok()
        return out
