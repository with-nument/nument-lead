"""Database access for the AI router: answer cache, batch bookkeeping, breaker state, ai_output activities.

Tables (Step 2 and 0008_llm.sql): `llm_cache`, `llm_batches`, `llm_batch_reservations` (through budget.py),
`source_health` rows `llm:gemini` and `llm:openai`, and `activities`.

`llm_cache` also holds two kinds of bookkeeping rows for batches, told apart by a key prefix that can never
collide with an answer key (answer keys are 64 hex characters):

- `batch:<task>:<item key>`: the item is in a submitted batch. Submitting the same item again while this
  row is alive is refused (Step 4.10.2: never submit the same key twice on the same day).
- `batchjob:<llm_batches.id>`: model, prompt version and fallback_from of a submitted batch, read back when
  the batch is collected, possibly by another process the next morning.

Both expire after 48 hours, the longest a provider keeps a batch, and the night run prunes expired rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .. import db

BATCH_MARKER_TTL = timedelta(hours=48)


# ---- answer cache ----------------------------------------------------------


def cache_get(key: str) -> dict[str, Any] | None:
    row = db.fetch_one("select response from public.llm_cache where key = %s and expires_at > now()", [key])
    return dict(row["response"]) if row else None


def cache_put(key: str, task: str, model: str, response: dict[str, Any], ttl_days: int) -> None:
    db.execute(
        "insert into public.llm_cache (key, task, model, response, expires_at) "
        "values (%s, %s, %s, %s, now() + make_interval(days => %s)) "
        "on conflict (key) do update set task = excluded.task, model = excluded.model, "
        "response = excluded.response, created_at = now(), expires_at = excluded.expires_at",
        [key, task, model, db.Jsonb(response), ttl_days],
    )


def cache_prune() -> int:
    """Delete expired cache and batch rows. Called by the night run."""
    return db.execute("delete from public.llm_cache where expires_at <= now()")


# ---- batches ---------------------------------------------------------------


def item_marker(task: str, key: str) -> str:
    return f"batch:{task}:{key}"


def job_marker(llm_batch_id: str) -> str:
    return f"batchjob:{llm_batch_id}"


def items_in_flight(task: str, keys: list[str]) -> set[str]:
    """Item keys of this task that are already in a live (not collected, not expired) batch."""
    if not keys:
        return set()
    markers = [item_marker(task, k) for k in keys]
    rows = db.fetch_all(
        "select key from public.llm_cache where key = any(%s) and expires_at > now()",
        [markers],
    )
    prefix = f"batch:{task}:"
    return {r["key"][len(prefix) :] for r in rows}


def insert_batch(
    *,
    provider: str,
    provider_batch_id: str,
    task: str,
    keys: list[str],
    model: str,
    prompt_version: int,
    fallback_from: str | None,
    reserved_inr: float,
    conn: Any = None,
) -> str:
    """Record a submitted batch, its metadata and its item markers in one transaction. Returns llm_batches.id."""

    def _write(c: Any) -> str:
        row = db.fetch_one(
            "insert into public.llm_batches (provider, provider_batch_id, task, status, item_count) "
            "values (%s, %s, %s, 'submitted', %s) returning id",
            [provider, provider_batch_id, task, len(keys)],
            conn=c,
        )
        assert row is not None
        batch_id = str(row["id"])
        expires = datetime.now().astimezone() + BATCH_MARKER_TTL
        meta = {
            "provider": provider,
            "provider_batch_id": provider_batch_id,
            "task": task,
            "model": model,
            "prompt_version": prompt_version,
            "fallback_from": fallback_from,
            "reserved_inr": round(reserved_inr, 4),
            "keys": keys,
        }
        rows = [(job_marker(batch_id), task, model, db.Jsonb(meta), expires)]
        rows += [(item_marker(task, k), task, model, db.Jsonb({"llm_batch_id": batch_id}), expires) for k in keys]
        with c.cursor() as cur:
            cur.executemany(
                "insert into public.llm_cache (key, task, model, response, expires_at) values (%s, %s, %s, %s, %s) "
                "on conflict (key) do update set response = excluded.response, expires_at = excluded.expires_at",
                rows,
            )
        return batch_id

    if conn is not None:
        return _write(conn)
    with db.tx() as c:
        return _write(c)


def batch_meta(llm_batch_id: str) -> dict[str, Any] | None:
    row = db.fetch_one("select response from public.llm_cache where key = %s", [job_marker(llm_batch_id)])
    return dict(row["response"]) if row else None


def open_batches(task: str | None = None) -> list[dict[str, Any]]:
    """Batches still waiting to be collected, oldest first."""
    return db.fetch_all(
        "select id::text as id, provider, provider_batch_id, task, status, item_count, submitted_at "
        "from public.llm_batches where status in ('submitted', 'running') and (%s::text is null or task = %s::text) "
        "order by submitted_at",
        [task, task],
    )


def set_batch_status(llm_batch_id: str, status: str, *, result_ref: str | None = None, conn: Any = None) -> None:
    finished = status in ("completed", "failed", "expired", "cancelled")
    db.execute(
        "update public.llm_batches set status = %s, completed_at = case when %s then now() else completed_at end, "
        "result_ref = coalesce(%s, result_ref) where id = %s",
        [status, finished, result_ref, llm_batch_id],
        conn=conn,
    )


def clear_batch_markers(llm_batch_id: str, task: str, keys: list[str], *, conn: Any = None) -> None:
    markers = [job_marker(llm_batch_id), *(item_marker(task, k) for k in keys)]
    db.execute("delete from public.llm_cache where key = any(%s)", [markers], conn=conn)


# ---- breaker state ----------------------------------------------------------


def health_rows(sources: list[str]) -> dict[str, dict[str, Any]]:
    rows = db.fetch_all(
        "select source, enabled, last_ok_at, last_error_at, last_error, blocked_until "
        "from public.source_health where source = any(%s)",
        [sources],
    )
    return {r["source"]: r for r in rows}


def health_ok(source: str) -> None:
    db.execute(
        "insert into public.source_health (source, last_ok_at) values (%s, now()) "
        "on conflict (source) do update set last_ok_at = now(), blocked_until = null",
        [source],
    )


def health_error(source: str, error: str, blocked_until: datetime | None) -> None:
    db.execute(
        "insert into public.source_health (source, last_error_at, last_error, blocked_until) "
        "values (%s, now(), %s, %s) on conflict (source) do update set last_error_at = now(), "
        "last_error = excluded.last_error, blocked_until = excluded.blocked_until",
        [source, error[:500], blocked_until],
    )


def health_set_enabled(source: str, enabled: bool) -> None:
    db.execute(
        "insert into public.source_health (source, enabled) values (%s, %s) "
        "on conflict (source) do update set enabled = excluded.enabled "
        "where public.source_health.enabled is distinct from excluded.enabled",
        [source, enabled],
    )


# ---- activities --------------------------------------------------------------


def insert_ai_output(lead_id: str, payload: dict[str, Any]) -> None:
    """`activities` row type ai_output for lead-level outputs (write_message, judge_lead), Step 4.5.3."""
    db.execute(
        "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'ai_output', %s)",
        [lead_id, db.Jsonb(payload)],
    )


def get_setting(key: str, default: Any = None) -> Any:
    return db.get_setting(key, default)
