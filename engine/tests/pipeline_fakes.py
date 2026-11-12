"""Test doubles and seed helpers for Steps 10 to 12 (verify, score, judge, message).

`FakeRouter` stands in for the Step 4 router: scripted answers per task, every call recorded, and the
`last_meta` the pipeline reads to tag stored outputs. No test here touches a real AI provider.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from nument_engine.pipeline.runs import Options, RunContext

TEST_SEGMENT = "education-ae"  # DB tests own this segment; other test files use clinics-in


class BudgetExceeded(Exception):
    """Same class name as the Step 4 budget guard's exception."""


class AllProvidersDown(Exception):
    """Same class name as the Step 4 router's exception."""


@dataclass
class Call:
    task: str
    inputs: dict[str, Any]
    lead_id: str | None
    exclude_model: str | None


@dataclass
class FakeRouter:
    answers: dict[str, list[Any] | Callable[[dict[str, Any]], Any]]
    models: dict[str, str] = field(
        default_factory=lambda: {"write_message": "gemini-3-flash", "check_message": "gemini-3.1-pro"}
    )
    calls: list[Call] = field(default_factory=list)
    last_meta: dict[str, Any] | None = None

    def run(
        self,
        task: str,
        inputs: dict[str, Any],
        *,
        lead_id: str | None = None,
        cache_extra: str = "",
        exclude_model: str | None = None,
    ) -> Any:
        self.calls.append(Call(task, inputs, lead_id, exclude_model))
        model = self.models.get(task, "gemini-3-flash")
        if exclude_model and model == exclude_model:
            model = "gemini-3.1-pro" if model != "gemini-3.1-pro" else "gemini-3-flash"
        self.last_meta = {"task": task, "provider": "gemini", "model": model, "prompt_version": 1}
        source = self.answers[task]
        reply = source(inputs) if callable(source) else source.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def tasks(self) -> list[str]:
        return [c.task for c in self.calls]


class SameModelRouter(FakeRouter):
    """A router without `exclude_model` support: the critic may be the writer's own model."""

    def run(  # type: ignore[override]
        self, task: str, inputs: dict[str, Any], *, lead_id: str | None = None, cache_extra: str = ""
    ) -> Any:
        return super().run(task, inputs, lead_id=lead_id, cache_extra=cache_extra)


NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


def rc_for(dry_run: bool = False, limit: int | None = None, segments: list[str] | None = None) -> RunContext:
    return RunContext(
        run_id=str(uuid.uuid4()),
        kind="manual",
        opts=Options(segments=segments or [TEST_SEGMENT], limit=limit, dry_run=dry_run),
        started_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Seeding a throwaway database (committed rows; the pipeline_db fixture wipes the test segment first)
# ---------------------------------------------------------------------------


@contextmanager
def connect(dsn: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with psycopg.connect(dsn, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def wipe_segment(dsn: str, segment: str = TEST_SEGMENT) -> None:
    with connect(dsn) as conn:
        conn.execute(
            "delete from public.leads where business_id in (select id from public.businesses where segment_id = %s)",
            [segment],
        )
        conn.execute(
            "delete from public.source_records where business_id in "
            "(select id from public.businesses where segment_id = %s)",
            [segment],
        )
        conn.execute("delete from public.businesses where segment_id = %s", [segment])


def insert(conn: psycopg.Connection[dict[str, Any]], table: str, values: dict[str, Any]) -> str:
    cols = list(values)
    params = [Jsonb(v) if isinstance(v, dict | list) else v for v in values.values()]
    row = conn.execute(
        f"insert into public.{table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) returning *",
        params,
    ).fetchone()
    assert row is not None
    return str(row["id"]) if "id" in row else ""


def business(conn: psycopg.Connection[dict[str, Any]], **over: Any) -> str:
    tag = uuid.uuid4().hex[:8]
    values: dict[str, Any] = {
        "segment_id": TEST_SEGMENT,
        "name": f"Bright Minds Academy {tag}",
        "norm_name": f"bright minds academy {tag}",
        "website": f"https://brightminds-{tag}.ae",
        "web_domain": f"brightminds-{tag}.ae",
        "country": "ae",
        "city": "Dubai",
        "category": "education",
        "subcategory": "coaching_institute",
        "review_count": 180,
        "status": "researched",
        "researched_at": NOW - timedelta(hours=3),
    }
    values.update(over)
    return insert(conn, "businesses", values)


def page(conn: psycopg.Connection[dict[str, Any]], business_id: str, url: str, text: str, **over: Any) -> str:
    values: dict[str, Any] = {
        "business_id": business_id,
        "url": url,
        "text": text,
        "http_status": 200,
        "fetched_at": datetime.now(UTC) - timedelta(hours=4),
    }
    values.update(over)
    return insert(conn, "pages", values)


def fact(
    conn: psycopg.Connection[dict[str, Any]],
    business_id: str,
    field_name: str,
    value: Any,
    quote: str | None,
    url: str | None,
    **over: Any,
) -> str:
    values: dict[str, Any] = {
        "business_id": business_id,
        "field": field_name,
        "value": value,
        "quote": quote,
        "url": url,
        "model": "gemini:gemini-3-flash#extract_facts.v1",
    }
    values.update(over)
    return insert(conn, "facts", values)


def signal(
    conn: psycopg.Connection[dict[str, Any]],
    business_id: str,
    kind: str,
    category: str,
    points: float,
    age_days: float,
    window_days: float,
    **over: Any,
) -> str:
    observed = datetime.now(UTC) - timedelta(days=age_days)
    values: dict[str, Any] = {
        "business_id": business_id,
        "type": kind,
        "category": category,
        "points": points,
        "observed_at": observed,
        "expires_at": observed + timedelta(days=window_days),
        "source": "careers_watch",
        "dedupe_key": f"test:{uuid.uuid4().hex}",
    }
    values.update(over)
    return insert(conn, "signals", values)


def contact(conn: psycopg.Connection[dict[str, Any]], business_id: str, **over: Any) -> str:
    values: dict[str, Any] = {
        "business_id": business_id,
        "phone_type": "mobile",
        "source": "website",
        "verified": True,
        "verified_at": datetime.now(UTC) - timedelta(hours=4),
    }
    values.update(over)
    return insert(conn, "contacts", values)
