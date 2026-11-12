"""Spend tracking and the daily cap: every paid call is estimated before it is made and logged after (Steps 4, 19).

Three things live here:

1. **Prices** (`engine/config/prices.yaml`): token prices with announced future changes, search, Places and
   PageSpeed allowances, and the cost formulas built on them.
2. **The degradation ladder** (Step 19.6): as today's spend (IST) approaches `settings.daily_cap_inr`, the
   cheapest-to-lose work stops first. AI tasks carry a priority from `tasks.yaml` (1 stops last, 6 first);
   pipeline phases that are not a single AI call (fit-only research, low-priority research) ask
   `allow_phase()`. Messages for the best leads are the last paid work to stop, and nothing ever pushes the
   day past the cap (an optional `budget_p1_reserve_inr` setting can let priority 1 run a little over).
3. **Logging and quotas** (Step 19.3, 19.7): every paid or quota-limited call writes one `costs` row, and the
   free allowances (Google Places, Gemini grounded search, PageSpeed) are counted from that same table.

The guard keeps a short-lived snapshot of today's spend so it does not query the database before every call;
its own writes are added to the snapshot immediately, and it re-reads the database every `refresh_s` seconds
to see spend from other processes. All methods are safe to call from several threads.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .logging import get_logger

log = get_logger("nlead.budget")

IST = ZoneInfo("Asia/Kolkata")

# Share of the daily cap at which work of each AI task priority stops (tasks.yaml `priority`).
PRIORITY_STOP_AT: dict[int, float] = {
    1: 1.00,  # write_message, check_message: finishes leads already paid for
    2: 0.95,  # judge_lead
    3: 0.95,  # extract_facts, verify_flagged
    4: 0.95,  # classify_signal, classify_page_change
    5: 0.85,  # grounded_search, classify_news
    6: 0.80,  # weekly_audit: can wait a day
}

# Share of the daily cap at which a pipeline phase may no longer start (Step 19.6).
PHASE_STOP_AT: dict[str, float] = {
    "fit_only_research": 0.60,
    "low_priority_research": 0.75,
    "grounded_search": 0.85,
    "research": 0.95,
    "extract": 0.95,
    "judge": 0.95,
    "message": 1.00,
}

SNAPSHOT_REFRESH_S = 30.0

PlacesKind = Literal["text_search", "details", "details_reviews"]
PLACES_TASKS: dict[str, str] = {
    "text_search": "places_text_search",
    "details": "places_details",
    "details_reviews": "places_details_reviews",
}
# Which Places SKU each kind of call is billed as (Places API New field masks, Step 5).
PLACES_SKUS: dict[str, str] = {
    "text_search": "text_search_ids_only",
    "details": "place_details_enterprise",
    "details_reviews": "place_details_enterprise_atmosphere",
}
# Daily caps per kind and region: settings keys tried in order (A.13.4 names first, then the 0004 seed names).
PLACES_DAILY_CAP_KEYS: dict[tuple[str, str], tuple[tuple[str, ...], int | None]] = {
    ("text_search", "india"): ((), None),
    ("text_search", "global"): ((), None),
    ("details", "india"): (("places_details_daily_cap", "places_details_cap_in"), 230),
    ("details", "global"): (("places_details_daily_cap_global", "places_details_cap_global"), 30),
    ("details_reviews", "india"): (("places_reviews_daily_cap", "places_details_cap_in"), 230),
    ("details_reviews", "global"): (("places_reviews_daily_cap_global", "places_details_cap_global"), 30),
}
GROUNDING_TASK = "grounded_search"  # costs.task for search queries (provider google_search, A.13.5 rule 4)


class BudgetExceeded(Exception):
    """A paid call or phase was refused by the budget guard. The step records the skip and moves on."""

    def __init__(self, task: str, reason: str) -> None:
        super().__init__(f"{task}: {reason}")
        self.task = task
        self.reason = reason


BudgetStop = BudgetExceeded  # the Step 19 name for the same thing


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


class PriceChange(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    starts: date = Field(alias="from")
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cached_input: float | None = Field(default=None, ge=0)


class ModelPrice(BaseModel):
    """USD per 1M tokens for one model, with the announced future changes."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "openai"]
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cached_input: float | None = Field(default=None, ge=0)
    changes: list[PriceChange] = Field(default_factory=list)

    def on(self, day: date) -> tuple[float, float, float]:
        """(input, output, cached input) prices that apply on `day`."""
        price = (self.input, self.output, self.cached_input if self.cached_input is not None else self.input)
        for change in sorted(self.changes, key=lambda c: c.starts):
            if change.starts <= day:
                cached = change.cached_input if change.cached_input is not None else change.input
                price = (change.input, change.output, cached)
        return price


class SkuPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usd_per_1000: float = Field(ge=0)
    free_per_month: int | None = None  # None means unlimited


class GroundingPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    free_per_month: int = 5000
    usd_per_1000: float = 14.0
    daily_limit: int = 1500


class WebSearchPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usd_per_1000: float = 10.0


class SearchPrices(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gemini_grounding: GroundingPrice = Field(default_factory=GroundingPrice)
    openai_web_search: WebSearchPrice = Field(default_factory=WebSearchPrice)


class PageSpeedPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usd_per_1000: float = 0.0
    daily_free: int = 25000


class Prices(BaseModel):
    """The whole of `engine/config/prices.yaml`, validated."""

    model_config = ConfigDict(extra="forbid")

    verified_on: date
    sources: dict[str, str] = Field(default_factory=dict)
    fx_inr_per_usd: float = Field(gt=0)
    batch_discount: float = Field(gt=0, le=1)
    flex_discount: float = Field(default=0.5, gt=0, le=1)
    models: dict[str, ModelPrice]
    search: SearchPrices = Field(default_factory=SearchPrices)
    google_places: dict[Literal["india", "global"], dict[str, SkuPrice]] = Field(default_factory=dict)
    pagespeed: PageSpeedPrice = Field(default_factory=PageSpeedPrice)

    def model(self, model: str) -> ModelPrice:
        try:
            return self.models[model]
        except KeyError:
            raise KeyError(f"no price for model {model!r} in prices.yaml") from None


def prices_path() -> Path:
    from .settings import get_settings

    return get_settings().config_dir / "prices.yaml"


@lru_cache(maxsize=4)
def _load_prices(path: str) -> Prices:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Prices.model_validate(data)


def load_prices(path: Path | None = None) -> Prices:
    """Validated prices (cached per file)."""
    return _load_prices(str(path or prices_path()))


def ist_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def ist_day_start(now: datetime | None = None) -> datetime:
    """Midnight IST of the current IST day, as an aware datetime."""
    today = ist_today(now)
    return datetime(today.year, today.month, today.day, tzinfo=IST)


def ist_month_start(now: datetime | None = None) -> datetime:
    today = ist_today(now)
    return datetime(today.year, today.month, 1, tzinfo=IST)


def estimate_tokens(text: str, script: str = "latin") -> int:
    """Rough token count before a call: about 4 characters per token for English, 2 for Devanagari or Arabic."""
    per = 2 if script in ("devanagari", "arabic") else 4
    return math.ceil(len(text) / per)


def llm_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cached_tokens: int = 0,
    batch: bool = False,
    flex: bool = False,
    on: date | None = None,
    prices: Prices | None = None,
) -> float:
    """USD for one call. Output tokens include thinking. Cached input is billed at the cached rate."""
    p = prices or load_prices()
    price_in, price_out, price_cached = p.model(model).on(on or ist_today())
    cached = max(0, min(cached_tokens, input_tokens))
    usd = ((input_tokens - cached) * price_in + cached * price_cached + output_tokens * price_out) / 1e6
    if batch:
        usd *= p.batch_discount
    elif flex:
        usd *= p.flex_discount
    return usd


def search_cost_usd(provider: str, queries: int, *, used_this_month: int = 0, prices: Prices | None = None) -> float:
    """USD for the web searches of one call. Gemini queries inside the monthly free allowance cost nothing."""
    if queries <= 0:
        return 0.0
    p = prices or load_prices()
    if provider == "gemini":
        g = p.search.gemini_grounding
        over = max(0, used_this_month + queries - g.free_per_month) - max(0, used_this_month - g.free_per_month)
        return over * g.usd_per_1000 / 1000
    if provider == "openai":
        return queries * p.search.openai_web_search.usd_per_1000 / 1000
    raise ValueError(f"unknown search provider {provider!r}")


def places_cost_usd(
    sku: str,
    calls: int,
    *,
    used_this_month: int = 0,
    region: Literal["india", "global"] = "india",
    prices: Prices | None = None,
) -> float:
    """USD for Places calls of one SKU; calls inside the monthly free allowance cost nothing."""
    if calls <= 0:
        return 0.0
    p = prices or load_prices()
    try:
        price = p.google_places[region][sku]
    except KeyError:
        raise KeyError(f"no Places price for {region}/{sku} in prices.yaml") from None
    if price.free_per_month is None:
        return 0.0
    free = price.free_per_month
    over = max(0, used_this_month + calls - free) - max(0, used_this_month - free)
    return over * price.usd_per_1000 / 1000


def places_task(kind: PlacesKind, country: str) -> str:
    """`costs.task` for a Places call: India calls and calls abroad are counted apart (they have separate caps)."""
    base = PLACES_TASKS[kind]
    return base if country.lower() == "in" else f"{base}_global"


def places_tasks_all(kind: PlacesKind) -> list[str]:
    """Both `costs.task` names of a kind of Places call (India and abroad)."""
    return [PLACES_TASKS[kind], f"{PLACES_TASKS[kind]}_global"]


def _region(country: str) -> Literal["india", "global"]:
    return "india" if country.lower() == "in" else "global"


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


@dataclass
class _Snapshot:
    spent_today: float
    reserved: float
    spent_run: float
    day: date
    read_at: float


class Budget:
    """Daily cap, per-run cap, batch reservations, cost logging and quota counting for one run.

    Rows it writes are stamped with its own clock (`costs.at`, `llm_batch_reservations.created_at`), and every
    "today" and "this month" it reads is an IST day or month of that clock, so tests can run on a fake day.

    run_id         `runs.id` the cost rows belong to (None outside a run, for example in a one-off check)
    max_spend_inr  the global `--max-spend-inr` flag: stops every paid call of this run once reached
    stats          the run's stats dict (RunContext.stats); alerts are appended to stats["alerts"]
    clock          returns an aware UTC datetime (tests pass a fake clock)
    """

    def __init__(
        self,
        run_id: str | None = None,
        *,
        max_spend_inr: float | None = None,
        stats: dict[str, Any] | None = None,
        prices: Prices | None = None,
        clock: Callable[[], datetime] | None = None,
        refresh_s: float = SNAPSHOT_REFRESH_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run_id = run_id
        self.max_spend_inr = max_spend_inr
        self.stats = stats if stats is not None else {}
        self.prices = prices or load_prices()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.refresh_s = refresh_s
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._snap: _Snapshot | None = None
        self._settings: dict[str, Any] | None = None
        self._alerted_day: date | None = None

    # ---- settings ---------------------------------------------------------

    SETTING_KEYS = (
        "daily_cap_inr",
        "alert_pct",
        "fx_inr_per_usd",
        "budget_p1_reserve_inr",
        "places_billing_region",
        "places_details_daily_cap",
        "places_details_cap_in",
        "places_details_daily_cap_global",
        "places_details_cap_global",
        "places_reviews_daily_cap",
        "places_reviews_daily_cap_global",
        "grounding_daily_cap",
        "grounded_search.per_day",
        "pagespeed_daily_cap",
    )

    def _setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if self._settings is None:
                rows = db.fetch_all(
                    "select key, value from public.settings where key = any(%s)", [list(self.SETTING_KEYS)]
                )
                self._settings = {r["key"]: r["value"] for r in rows}
            value = self._settings.get(key)
        return default if value is None else value

    def reload_settings(self) -> None:
        with self._lock:
            self._settings = None

    @property
    def cap_inr(self) -> float:
        return float(self._setting("daily_cap_inr", 750))

    @property
    def alert_share(self) -> float:
        return float(self._setting("alert_pct", 80)) / 100

    @property
    def fx(self) -> float:
        return float(self._setting("fx_inr_per_usd", self.prices.fx_inr_per_usd))

    @property
    def p1_reserve_inr(self) -> float:
        return float(self._setting("budget_p1_reserve_inr", 0))

    def usd_to_inr(self, usd: float) -> float:
        return usd * self.fx

    # ---- spend ------------------------------------------------------------

    def _read_snapshot(self) -> _Snapshot:
        now = self.clock()
        day_start = ist_day_start(now)
        # Sums use usd: costs.inr is stored with 2 decimals, which rounds tiny calls the same way every time.
        row = db.fetch_one(
            """
            select
              (select coalesce(sum(usd), 0) from public.costs where at >= %(day)s) as usd_today,
              (select coalesce(sum(reserved_inr), 0) from public.llm_batch_reservations
                where released = false and created_at >= %(day)s) as reserved,
              (select coalesce(sum(usd), 0) from public.costs
                where %(run)s::uuid is not null and run_id = %(run)s::uuid and at >= %(day)s) as usd_run
            """,
            {"day": day_start, "run": self.run_id},
        )
        assert row is not None
        return _Snapshot(
            spent_today=float(row["usd_today"]) * self.fx,
            reserved=float(row["reserved"]),
            spent_run=float(row["usd_run"]) * self.fx,
            day=ist_today(now),
            read_at=self._monotonic(),
        )

    def _snapshot(self) -> _Snapshot:
        with self._lock:
            snap = self._snap
            stale = (
                snap is None
                or self._monotonic() - snap.read_at >= self.refresh_s
                or snap.day != ist_today(self.clock())
            )
            if stale:
                self._snap = snap = self._read_snapshot()
            assert snap is not None
            return snap

    def refresh(self) -> None:
        """Forget the cached snapshot; the next check reads the database."""
        with self._lock:
            self._snap = None

    def spent_today_inr(self) -> float:
        return self._snapshot().spent_today

    def reserved_inr(self) -> float:
        return self._snapshot().reserved

    def spent_this_run_inr(self) -> float:
        return self._snapshot().spent_run

    def committed_inr(self) -> float:
        """Spent today plus money held for batches that are not collected yet."""
        snap = self._snapshot()
        return snap.spent_today + snap.reserved

    def share_used(self) -> float:
        cap = self.cap_inr
        return self.committed_inr() / cap if cap > 0 else 1.0

    # ---- decisions --------------------------------------------------------

    def _limit_for(self, stop_at: float, priority: int | None) -> float:
        limit = stop_at * self.cap_inr
        if priority == 1:
            limit += self.p1_reserve_inr
        return limit

    def check(self, task: str, priority: int, est_inr: float) -> None:
        """Before a paid call: raise BudgetExceeded if it would cross the run cap or its priority's limit."""
        if priority not in PRIORITY_STOP_AT:
            raise ValueError(f"{task}: priority must be 1 to 6, got {priority}")
        with self._lock:
            snap = self._snapshot()
            if self.max_spend_inr is not None and snap.spent_run + est_inr > self.max_spend_inr:
                raise BudgetExceeded(task, f"run cap --max-spend-inr {self.max_spend_inr:g} reached")
            committed = snap.spent_today + snap.reserved
            stop_at = PRIORITY_STOP_AT[priority]
            limit = self._limit_for(stop_at, priority)
            self._maybe_alert(committed + est_inr)
            if committed >= limit or committed + est_inr > limit:
                raise BudgetExceeded(
                    task,
                    f"priority {priority} stops at {stop_at:.0%} of the daily cap "
                    f"(₹{committed:.2f} committed of ₹{self.cap_inr:.0f})",
                )

    def allow_phase(self, phase: str) -> bool:
        """May a pipeline phase start now (Step 19.6)? Unknown phases are a programming error."""
        if phase not in PHASE_STOP_AT:
            raise ValueError(f"unknown budget phase {phase!r}; expected one of {', '.join(PHASE_STOP_AT)}")
        committed = self.committed_inr()
        if self.max_spend_inr is not None and self.spent_this_run_inr() >= self.max_spend_inr:
            return False
        return committed < self._limit_for(PHASE_STOP_AT[phase], None)

    def check_phase(self, phase: str) -> None:
        """Like allow_phase, but raises BudgetExceeded so a phase can stop cleanly."""
        if not self.allow_phase(phase):
            raise BudgetExceeded(phase, f"phase stops at {PHASE_STOP_AT[phase]:.0%} of the daily cap")

    def affordable(self, task: str, priority: int, estimates_inr: Iterable[float]) -> int:
        """How many items (in the order given, best first) fit under the run cap and the priority limit."""
        with self._lock:
            snap = self._snapshot()
            run_room = float("inf") if self.max_spend_inr is None else self.max_spend_inr - snap.spent_run
            limit_room = self._limit_for(PRIORITY_STOP_AT[priority], priority) - (snap.spent_today + snap.reserved)
            room = min(run_room, limit_room)
            count, total = 0, 0.0
            for est in estimates_inr:
                if total + est > room:
                    break
                total += est
                count += 1
            if count:
                self._maybe_alert(snap.spent_today + snap.reserved + total)
            return count

    # ---- alerts -----------------------------------------------------------

    def _maybe_alert(self, projected_inr: float) -> None:
        """At alert_pct of the cap, raise the alert once per IST day (settings.budget_alert_day)."""
        cap = self.cap_inr
        if cap <= 0 or projected_inr < self.alert_share * cap:
            return
        day = ist_today(self.clock())
        with self._lock:
            if self._alerted_day == day:
                return
            self._alerted_day = day
        today = day.isoformat()
        claimed = db.fetch_one(
            "update public.settings set value = to_jsonb(%s::text) "
            "where key = 'budget_alert_day' and value is distinct from to_jsonb(%s::text) returning key",
            [today, today],
        )
        if claimed is None:
            return
        message = (
            f"AI and API spend is at {projected_inr / cap:.0%} of the daily cap "
            f"(₹{projected_inr:.0f} of ₹{cap:.0f}). Lower-priority work stops first."
        )
        with self._lock:
            self.stats.setdefault("alerts", []).append(message)
        log.warning("budget.alert", projected_inr=round(projected_inr, 2), cap_inr=cap, day=today)

    # ---- recording --------------------------------------------------------

    def record(
        self,
        provider: str,
        model: str | None,
        task: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        calls: int = 1,
        usd: float = 0.0,
        fallback_from: str | None = None,
        conn: Any = None,
    ) -> float:
        """Insert one `costs` row and return its INR amount. Called after every paid or quota-limited call."""
        inr = round(usd * self.fx, 4)
        db.execute(
            "insert into public.costs (run_id, provider, model, task, input_tokens, output_tokens, calls, usd, inr,"
            " fallback_from, at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                self.run_id,
                provider,
                model,
                task,
                input_tokens,
                output_tokens,
                calls,
                round(usd, 6),
                inr,
                fallback_from,
                self.clock(),
            ],
            conn=conn,
        )
        self._add_spend(inr)
        return inr

    def record_many(self, rows: Iterable[Mapping[str, Any]]) -> float:
        """Insert several cost rows in one transaction (batch results). Returns the INR total."""
        values = []
        total = 0.0
        for r in rows:
            usd = float(r.get("usd", 0.0))
            inr = round(usd * self.fx, 4)
            total += inr
            values.append(
                [
                    self.run_id,
                    r["provider"],
                    r.get("model"),
                    r["task"],
                    int(r.get("input_tokens", 0)),
                    int(r.get("output_tokens", 0)),
                    int(r.get("calls", 1)),
                    round(usd, 6),
                    inr,
                    r.get("fallback_from"),
                    self.clock(),
                ]
            )
        if not values:
            return 0.0
        with db.tx() as conn, conn.cursor() as cur:
            cur.executemany(
                "insert into public.costs (run_id, provider, model, task, input_tokens, output_tokens, calls, usd,"
                " inr, fallback_from, at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                values,
            )
        self._add_spend(total)
        return total

    def _add_spend(self, inr: float) -> None:
        with self._lock:
            if self._snap is not None:
                self._snap.spent_today += inr
                self._snap.spent_run += inr

    # ---- batch reservations -----------------------------------------------

    def reserve(self, llm_batch_id: str, inr: float, *, conn: Any = None) -> None:
        """Hold money for a submitted batch until its results are collected (counts against the cap)."""
        inr = round(inr, 4)
        db.execute(
            "insert into public.llm_batch_reservations (llm_batch_id, reserved_inr, created_at) values (%s, %s, %s)",
            [llm_batch_id, inr, self.clock()],
            conn=conn,
        )
        with self._lock:
            if self._snap is not None:
                self._snap.reserved += inr

    def release(self, llm_batch_id: str, *, conn: Any = None) -> float:
        """Release a batch's reservation (its real cost is logged as it is collected)."""
        row = db.fetch_one(
            "with r as (update public.llm_batch_reservations set released = true "
            "where llm_batch_id = %s and released = false returning reserved_inr, created_at) "
            "select coalesce(sum(reserved_inr), 0) as inr, coalesce(bool_or(created_at >= %s), false) as today from r",
            [llm_batch_id, ist_day_start(self.clock())],
            conn=conn,
        )
        released = float(row["inr"]) if row else 0.0
        with self._lock:
            if self._snap is not None and row and row["today"]:
                self._snap.reserved = max(0.0, self._snap.reserved - released)
        return released

    # ---- quotas -----------------------------------------------------------

    def calls_today(self, provider: str | None, tasks: Iterable[str]) -> int:
        """Calls logged today (IST) for these tasks; provider None means every provider except the cache."""
        task_list = list(tasks)
        value = db.scalar(
            "select coalesce(sum(calls), 0) from public.costs where at >= %s and task = any(%s) "
            "and (%s::text is null and provider <> 'cache' or provider = %s::text)",
            [ist_day_start(self.clock()), task_list, provider, provider],
        )
        return int(value or 0)

    def calls_this_month(self, provider: str | None, tasks: Iterable[str]) -> int:
        task_list = list(tasks)
        value = db.scalar(
            "select coalesce(sum(calls), 0) from public.costs where at >= %s and task = any(%s) "
            "and (%s::text is null and provider <> 'cache' or provider = %s::text)",
            [ist_month_start(self.clock()), task_list, provider, provider],
        )
        return int(value or 0)

    def quota_left(
        self, provider: str | None, task: str | Iterable[str], *, per_day: int | None, per_month: int | None
    ) -> int:
        """Calls still allowed today: the smaller of the daily and monthly room. No limits means a large number."""
        tasks = [task] if isinstance(task, str) else list(task)
        room: list[int] = []
        if per_day is not None:
            room.append(per_day - self.calls_today(provider, tasks))
        if per_month is not None:
            room.append(per_month - self.calls_this_month(provider, tasks))
        return max(0, min(room)) if room else 1_000_000_000

    def _first_setting(self, keys: Iterable[str], default: int | None) -> int | None:
        for key in keys:
            value = self._setting(key)
            if value is not None:
                return int(value)
        return default

    def places_billing_region(self) -> Literal["india", "global"]:
        return "global" if str(self._setting("places_billing_region", "india")) == "global" else "india"

    def places_quota_left(self, kind: PlacesKind, country: str) -> int:
        """Places calls of this kind still allowed today for a business in `country` (Step 19.7).

        The daily cap is ours (settings, per region of the business). The monthly free allowance is per SKU
        and billing account, so it counts calls for every country together.
        """
        keys, default_cap = PLACES_DAILY_CAP_KEYS[(kind, _region(country))]
        per_day = self._first_setting(keys, default_cap)
        sku = PLACES_SKUS[kind]
        free = self.prices.google_places.get(self.places_billing_region(), {}).get(sku)
        per_month = free.free_per_month if free else 0
        room: list[int] = []
        if per_day is not None:
            room.append(per_day - self.calls_today("google_places", [places_task(kind, country)]))
        if per_month is not None:
            room.append(per_month - self.calls_this_month("google_places", places_tasks_all(kind)))
        return max(0, min(room)) if room else 1_000_000_000

    def record_places(self, kind: PlacesKind, country: str, calls: int = 1) -> float:
        """Log Places calls (usd 0 inside the free allowance). Returns INR."""
        sku = PLACES_SKUS[kind]
        used = self.calls_this_month("google_places", places_tasks_all(kind))
        usd = places_cost_usd(sku, calls, used_this_month=used, region=self.places_billing_region(), prices=self.prices)
        return self.record("google_places", sku, places_task(kind, country), calls=calls, usd=usd)

    def grounding_quota_left(self) -> int:
        """Grounded-search queries still allowed today: settings cap per day, free allowance per month."""
        g = self.prices.search.gemini_grounding
        per_day = self._first_setting(("grounding_daily_cap", "grounded_search.per_day"), 160)
        assert per_day is not None
        return self.quota_left(
            "google_search", GROUNDING_TASK, per_day=min(per_day, g.daily_limit), per_month=g.free_per_month
        )

    def record_search(
        self, provider: str, model: str | None, queries: int, *, fallback_from: str | None = None
    ) -> float:
        """Log the web-search queries of one call as provider google_search. Returns INR."""
        if queries <= 0:
            return 0.0
        used = self.calls_this_month("google_search", [GROUNDING_TASK]) if provider == "gemini" else 0
        usd = search_cost_usd(provider, queries, used_this_month=used, prices=self.prices)
        return self.record("google_search", model, GROUNDING_TASK, calls=queries, usd=usd, fallback_from=fallback_from)

    def pagespeed_quota_left(self) -> int:
        per_day = self._first_setting(("pagespeed_daily_cap",), 600)
        assert per_day is not None
        return self.quota_left(
            "pagespeed", "pagespeed", per_day=min(per_day, self.prices.pagespeed.daily_free), per_month=None
        )

    def record_pagespeed(self, calls: int = 1) -> float:
        return self.record("pagespeed", None, "pagespeed", calls=calls, usd=0.0)

    # ---- AI estimates -----------------------------------------------------

    def estimate_llm_inr(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        batch: bool = False,
        flex: bool = False,
    ) -> float:
        usd = llm_cost_usd(
            model,
            input_tokens,
            output_tokens,
            batch=batch,
            flex=flex,
            on=ist_today(self.clock()),
            prices=self.prices,
        )
        return self.usd_to_inr(usd)

    def llm_cost_usd(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cached_tokens: int = 0,
        batch: bool = False,
        flex: bool = False,
    ) -> float:
        return llm_cost_usd(
            model,
            input_tokens,
            output_tokens,
            cached_tokens=cached_tokens,
            batch=batch,
            flex=flex,
            on=ist_today(self.clock()),
            prices=self.prices,
        )


def summary_today(now: datetime | None = None) -> dict[str, Any]:
    """Spend today by provider and task, for job summaries and `nlead health` (Step 19.8)."""
    rows = db.fetch_all(
        "select provider, task, sum(calls)::int as calls, sum(inr)::numeric(12,2) as inr from public.costs "
        "where at >= %s group by provider, task order by sum(inr) desc",
        [ist_day_start(now)],
    )
    total = sum(float(r["inr"]) for r in rows)
    return {"total_inr": round(total, 2), "rows": rows, "day": ist_today(now).isoformat()}
