"""Shared helpers for the collect and research tests (Steps 5 to 9): a fake AI router, a clean database
fixture and segment factories. Import the fixtures you use into the test module.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine import db, http
from nument_engine.pipeline.runs import Options, RunContext
from nument_engine.segments import City, Segment, load_segments
from nument_engine.sources.base import SourceContext

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"


def fixture_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def fixture_json(*parts: str) -> Any:
    return json.loads(fixture_text(*parts))


# ---------------------------------------------------------------------------------------------------
# Fake AI router (the real one is llm/router.py, Step 4)
# ---------------------------------------------------------------------------------------------------


Reply = Any | Callable[[dict[str, Any]], Any]


@dataclass
class FakeRouter:
    """Answers `run(task, inputs)` from `replies[task]`: a list (popped in order) or a function of the inputs.
    An exception instance in a list is raised. Batch calls are recorded and answered from `batch_results`."""

    replies: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    submitted: list[tuple[str, list[dict[str, Any]]]] = field(default_factory=list)
    batch_results: list[dict[str, Any]] = field(default_factory=list)
    sync_results: list[dict[str, Any]] = field(default_factory=list)

    def run(self, task: str, inputs: dict[str, Any], *, lead_id: str | None = None, cache_extra: str = "") -> Any:
        self.calls.append((task, inputs))
        reply = self.replies[task]
        out = reply(inputs) if callable(reply) else reply.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    def submit_batch(self, task: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        self.submitted.append((task, items))
        return {
            "provider": "gemini",
            "batch_id": "batches/fake-1",
            "submitted": len(items),
            "results": self.sync_results,
        }

    def collect_batches(self, task: str) -> list[dict[str, Any]]:
        out, self.batch_results = self.batch_results, []
        return out

    def tasks(self) -> list[str]:
        return [t for t, _ in self.calls]


class BudgetExceeded(Exception):
    """Same name as the router's error: stages match it by name."""


# ---------------------------------------------------------------------------------------------------
# Segments and contexts
# ---------------------------------------------------------------------------------------------------


def segment(seg_id: str = "clinics-in", **changes: Any) -> Segment:
    seg = load_segments()[seg_id]
    return seg.model_copy(update=changes) if changes else seg


def make_city(name: str = "Pune", bbox: tuple[float, float, float, float] = (73.70, 18.40, 74.05, 18.70)) -> City:
    return City(name=name, aliases=[], bbox=bbox, localities=["Baner", "Aundh", "Kothrud"])


def ctx(router: Any = None, *, dry_run: bool = False, limit: int | None = None) -> SourceContext:
    return SourceContext(run_id=None, dry_run=dry_run, limit=limit, router=router)


def run_context(*, segments: list[str] | None = None, dry_run: bool = False, limit: int | None = None) -> RunContext:
    """A run context with a real `runs` row (costs rows reference it). Needs the `clean_db` fixture."""
    import uuid
    from datetime import UTC, datetime

    run_id = str(uuid.uuid4())
    db.execute("insert into public.runs (id, kind, status) values (%s, 'manual', 'running')", [run_id])
    opts = Options(segments=segments or ["clinics-in"], dry_run=dry_run, limit=limit)
    return RunContext(run_id=run_id, kind="manual", opts=opts, started_at=datetime.now(UTC))


def mock_transport(routes: dict[str, Any]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """A transport answering `routes[url]` (exact URL without query, or a callable(request) for every URL).
    Values: an httpx.Response, a (status, text) tuple, or a callable(request) returning a Response."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url).split("?", 1)[0]
        target = routes.get(url, routes.get("*"))
        if target is None:
            return httpx.Response(404, text="not found")
        if callable(target):
            result = target(request)
            return result if isinstance(result, httpx.Response) else httpx.Response(result[0], text=result[1])
        if isinstance(target, httpx.Response):
            return target
        status, body = target
        if isinstance(body, dict | list):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})

    return httpx.MockTransport(handler), seen


# ---------------------------------------------------------------------------------------------------
# No real network in tests
# ---------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_network() -> Iterator[None]:
    """Any request from a client without a mock transport fails the test instead of reaching the internet."""
    import respx

    with respx.mock(assert_all_called=False, assert_all_mocked=True):
        yield


# ---------------------------------------------------------------------------------------------------
# Database fixture: everything a test writes is removed afterwards, seeds are restored
# ---------------------------------------------------------------------------------------------------


@pytest.fixture
def clean_db(engine_db: str) -> Iterator[str]:
    """The engine database for one test. Rows created during the test are deleted at the end, and the seeded
    settings, source_health and segments rows are restored, so other test modules see the seed unchanged."""
    http.reset_caches()
    start = db.scalar("select clock_timestamp()")
    settings = db.fetch_all("select key, value from public.settings")
    health = db.fetch_all("select * from public.source_health")
    segments = db.fetch_all("select id, enabled, daily_quota from public.segments")
    try:
        yield engine_db
    finally:
        with db.tx() as conn:
            conn.execute("delete from public.leads where created_at >= %s", [start])
            conn.execute("delete from public.source_records where fetched_at >= %s", [start])
            conn.execute("delete from public.businesses where created_at >= %s", [start])
            conn.execute("delete from public.costs where at >= %s", [start])
            conn.execute("delete from public.inbox_posts where created_at >= %s", [start])
            conn.execute("delete from public.suppression where added_at >= %s", [start])
            conn.execute("delete from public.settings")
            for row in settings:
                conn.execute(
                    "insert into public.settings (key, value) values (%s, %s)", [row["key"], db.Jsonb(row["value"])]
                )
            conn.execute("delete from public.source_health")
            for row in health:
                cols = list(row)
                conn.execute(
                    f"insert into public.source_health ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})",
                    [row[c] for c in cols],
                )
            for row in segments:
                conn.execute(
                    "update public.segments set enabled = %s, daily_quota = %s where id = %s",
                    [row["enabled"], row["daily_quota"], row["id"]],
                )
        http.reset_caches()


def insert_business(**values: Any) -> str:
    """Insert one business directly (tests that do not go through the resolver). Returns its id."""
    from nument_engine.normalize import norm_name

    row = {
        "segment_id": "clinics-in",
        "country": "in",
        "city": "Pune",
        "status": "candidate",
        **values,
    }
    row.setdefault("norm_name", norm_name(row["name"]))
    if "extra" in row:
        row["extra"] = db.Jsonb(row["extra"])
    cols = list(row)
    return str(
        db.scalar(
            f"insert into public.businesses ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) returning id",
            [row[c] for c in cols],
        )
    )
