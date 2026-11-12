"""Fakes and fixtures for the AI router and budget tests. Nothing here touches the network.

- `FakeProvider` answers from a script of replies (responses, exceptions or functions of the request) and keeps
  every request it saw; it also fakes the batch API.
- `FakeClock` is the clock the router, breakers and budget share. Each test gets its own fake IST day in a
  month no other test uses, so cost rows from other tests never count against "today" or "this month".
- `llm_db` gives a migrated throwaway database with the router's tables emptied and its settings reset.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel

from nument_engine import db
from nument_engine.budget import Budget
from nument_engine.llm.availability import Availability
from nument_engine.llm.config import TaskRegistry, load_registry
from nument_engine.llm.router import Router
from nument_engine.llm.types import BatchRow, BatchState, LLMRequest, LLMResponse, ModelInfo, ProviderError, Usage

_MONTHS = itertools.count()


def unique_day() -> datetime:
    """Noon IST on the 15th of a month that no other test in this session uses (from 2031 on)."""
    n = next(_MONTHS)
    return datetime(2031 + n // 12, n % 12 + 1, 15, 6, 30, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or unique_day()

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


Reply = LLMResponse | Exception | Callable[[LLMRequest], LLMResponse]


def reply(
    payload: BaseModel | dict[str, Any] | str,
    *,
    model: str = "model",
    provider: str = "gemini",
    input_tokens: int = 1000,
    output_tokens: int = 200,
    cached_tokens: int = 0,
    finish: str = "stop",
    grounding: dict[str, Any] | None = None,
) -> LLMResponse:
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json()
    elif isinstance(payload, dict):
        text = json.dumps(payload)
    else:
        text = payload
    usage = Usage(input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=cached_tokens)
    if grounding:
        usage.search_queries = len(grounding.get("queries", []))
    return LLMResponse(
        text=text,
        usage=usage,
        provider=provider,  # type: ignore[arg-type]
        model=model,
        finish_reason=finish,
        grounding=grounding,
    )


def err(kind: Any, message: str = "boom", *, provider: str = "gemini", status: int | None = None) -> ProviderError:
    return ProviderError(kind, message, provider=provider, status=status)


@dataclass
class FakeBatch:
    model: str
    reqs: list[LLMRequest]
    display_name: str
    state: BatchState = "running"
    rows: list[BatchRow] = field(default_factory=list)


class FakeProvider:
    """Scripted provider. `replies` are consumed in order by generate()."""

    def __init__(self, name: str, replies: list[Reply] | None = None, *, models: list[str] | None = None) -> None:
        self.name = name
        self.replies: list[Reply] = list(replies or [])
        self.calls: list[LLMRequest] = []
        self.models = models or []
        self.batches: dict[str, FakeBatch] = {}
        self.submit_errors: list[Exception] = []
        self.cancelled: list[str] = []

    def generate(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        if not self.replies:
            raise AssertionError(f"unexpected call to {self.name}:{req.model} for {req.task}")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(req)
        return r

    def submit_batch(self, model: str, reqs: list[LLMRequest], display_name: str) -> str:
        if self.submit_errors:
            raise self.submit_errors.pop(0)
        batch_id = f"batches/{self.name}-{len(self.batches) + 1}"
        self.batches[batch_id] = FakeBatch(model=model, reqs=list(reqs), display_name=display_name)
        return batch_id

    def poll_batch(self, batch_id: str) -> BatchState:
        return self.batches[batch_id].state

    def fetch_batch(self, batch_id: str) -> list[BatchRow]:
        return list(self.batches[batch_id].rows)

    def cancel_batch(self, batch_id: str) -> None:
        self.cancelled.append(batch_id)
        self.batches[batch_id].state = "cancelled"

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name=m, actions=["generateContent", "batchGenerateContent"]) for m in self.models]


def make_router(
    providers: dict[str, Any],
    *,
    clock: FakeClock | None = None,
    enabled: dict[str, bool] | None = None,
    max_spend_inr: float | None = None,
    run_id: str | None = None,
    stats: dict[str, Any] | None = None,
    dry_run: bool = False,
    registry: TaskRegistry | None = None,
    persist: bool = True,
) -> Router:
    clock = clock or FakeClock()
    stats = stats if stats is not None else {}
    availability = Availability(
        enabled=enabled or {"gemini": True, "openai": False},
        has_key={p: p in providers for p in ("gemini", "openai")},
        clock=clock,
        persist=persist,
    )
    budget = Budget(run_id, max_spend_inr=max_spend_inr, stats=stats, clock=clock)
    return Router(
        run_id=run_id,
        stats=stats,
        dry_run=dry_run,
        registry=registry or load_registry("balanced"),
        providers=providers,
        availability=availability,
        budget=budget,
        clock=clock,
        sleep=lambda _s: None,
    )


def reset_llm_state() -> None:
    db.execute("delete from public.llm_batch_reservations")
    db.execute("delete from public.llm_batches")
    db.execute("delete from public.llm_cache")
    db.execute(
        "update public.source_health set blocked_until = null, last_error = null, last_error_at = null, "
        "last_ok_at = null where source like 'llm:%%'"
    )
    defaults = {
        "providers_enabled": {"gemini": True, "openai": False},
        "budget_alert_day": None,
        "daily_cap_inr": 750,
        "alert_pct": 80,
        "fx_inr_per_usd": 88,
        "ai.classify_per_day": 1500,
        "grounded_search.per_day": 160,
        "places_details_cap_in": 230,
        "places_details_cap_global": 30,
        "tier": "balanced",
    }
    for key, value in defaults.items():
        db.set_setting(key, value)
    db.execute(
        "delete from public.settings where key in ('budget_p1_reserve_inr', 'grounding_daily_cap', "
        "'pagespeed_daily_cap', 'places_billing_region', 'places_details_daily_cap')"
    )


@pytest.fixture(name="llm_db")
def llm_db_fixture(engine_db: str) -> Iterator[str]:
    """The throwaway database, with the router's tables empty and its settings at their defaults."""
    reset_llm_state()
    yield engine_db
    reset_llm_state()


def new_run() -> str:
    row = db.fetch_one("insert into public.runs (kind) values ('manual') returning id::text as id")
    assert row is not None
    return str(row["id"])


def new_lead() -> str:
    """A business and an open lead, for ai_output activity tests."""
    tag = next(_MONTHS)
    biz = db.fetch_one(
        "insert into public.businesses (segment_id, name, norm_name, country, city) "
        "values ('clinics-in', %s, %s, 'in', 'Pune') returning id",
        [f"LLM Test Clinic {tag}", f"llm test clinic {tag}"],
    )
    assert biz is not None
    lead = db.fetch_one(
        "insert into public.leads (business_id, segment_id, grade, pitch_mode) "
        "values (%s, 'clinics-in', 'A', 'visible_pain') returning id::text as id",
        [biz["id"]],
    )
    assert lead is not None
    return str(lead["id"])
