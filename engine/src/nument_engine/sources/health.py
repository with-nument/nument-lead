"""Kill switches and `source_health` bookkeeping shared by every adapter (Steps 5.3, 18.1.5, 18.1.7).

Costs and quotas are not here: every paid or counted call goes through the budget guard (`budget.Budget`).

A source is usable only when all three switches allow it (Step 18.1.7):
1. `settings.sources_enabled[source]` is not false (the founder's switch on the Engine page),
2. `source_health.enabled` is not false (set by the engine after repeated blocks of a grey source),
3. `source_health.blocked_until` is in the past.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from psycopg import Connection

from .. import db
from ..logging import get_logger

log = get_logger()

IST = ZoneInfo("Asia/Kolkata")
BACKOFF = (timedelta(hours=24), timedelta(hours=72), timedelta(days=7))  # Step 5.3.2
GREY_DISABLE_WINDOW = timedelta(days=7)  # two blocks of a grey source inside 7 days switch it off (18.1.5)


def now_utc() -> datetime:
    return datetime.now(UTC)


def ist_day_start(at: datetime | None = None) -> datetime:
    """Midnight IST of the day containing `at` (default now), as an aware datetime."""
    local = (at or now_utc()).astimezone(IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def next_ist_midnight(at: datetime | None = None) -> datetime:
    return ist_day_start(at) + timedelta(days=1)


def ist_month_start(at: datetime | None = None) -> datetime:
    return ist_day_start(at).replace(day=1)


# ---------------------------------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------------------------------


def source_flags(conn: Connection[Any] | None = None) -> dict[str, bool]:
    """`settings.sources_enabled` as a dict (missing keys mean enabled)."""
    value = db.get_setting("sources_enabled", {}, conn=conn) or {}
    return {str(k): bool(v) for k, v in value.items()} if isinstance(value, dict) else {}


def source_status(source: str, conn: Connection[Any] | None = None) -> tuple[bool, str]:
    """(usable, reason). The reason explains a skip in plain words for run stats and the Engine page."""
    if source_flags(conn).get(source) is False:
        return False, "switched off in settings.sources_enabled"
    row = db.fetch_one("select enabled, blocked_until from public.source_health where source = %s", [source], conn=conn)
    if row is None:
        return True, ""
    if row["enabled"] is False:
        return False, "disabled in source_health (repeated blocks; the founder turns it back on)"
    until = row["blocked_until"]
    if until is not None and until > now_utc():
        return False, f"blocked until {until.astimezone(IST):%Y-%m-%d %H:%M} IST"
    return True, ""


def setting_int(key: str, default: int, conn: Connection[Any] | None = None) -> int:
    """An integer setting (per-source daily caps and similar), falling back to `default`."""
    value = db.get_setting(key, default, conn=conn)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------------------------------
# source_health writes
# ---------------------------------------------------------------------------------------------------

_UPSERT_COUNTS = """
insert into public.source_health as h (source, last_ok_at, requests_today, requests_day)
values (%(source)s, %(ok_at)s, %(n)s, (now() at time zone 'Asia/Kolkata')::date)
on conflict (source) do update set
  last_ok_at     = coalesce(excluded.last_ok_at, h.last_ok_at),
  requests_today = case when h.requests_day = excluded.requests_day
                        then h.requests_today + excluded.requests_today else excluded.requests_today end,
  requests_day   = excluded.requests_day
"""


def mark_ok(source: str, *, requests: int = 0, conn: Connection[Any] | None = None) -> None:
    """A successful run of the source: last_ok_at = now, and add today's request count."""
    db.execute(_UPSERT_COUNTS, {"source": source, "ok_at": now_utc(), "n": requests}, conn=conn)


def add_requests(source: str, requests: int, conn: Connection[Any] | None = None) -> None:
    """Count requests without touching last_ok_at (the run had an error)."""
    if requests:
        db.execute(_UPSERT_COUNTS, {"source": source, "ok_at": None, "n": requests}, conn=conn)


def mark_error(
    source: str,
    error: str,
    *,
    blocked_until: datetime | None = None,
    requests: int = 0,
    conn: Connection[Any] | None = None,
) -> None:
    """Record an error (a short message, never a secret) and optionally pause the source."""
    db.execute(
        """
        insert into public.source_health as h (source, last_error_at, last_error, blocked_until)
        values (%(source)s, now(), %(error)s, %(until)s)
        on conflict (source) do update set
          last_error_at = now(), last_error = excluded.last_error,
          blocked_until = coalesce(excluded.blocked_until, h.blocked_until)
        """,
        {"source": source, "error": error[:500], "until": blocked_until},
        conn=conn,
    )
    add_requests(source, requests, conn=conn)


def record_block(
    source: str,
    reason: str,
    *,
    grey: bool,
    until: datetime | None = None,
    requests: int = 0,
    conn: Connection[Any] | None = None,
) -> datetime:
    """A block: pause the source with the backoff ladder (24 h, 72 h, 7 days by blocks in the last 30 days),
    or until `until` when the caller knows better (an API quota resets at midnight). A grey source blocked twice
    inside 7 days is switched off until the founder turns it back on (Step 18.1.5). Returns the pause end."""
    now = now_utc()
    row = db.fetch_one("select recent_blocks from public.source_health where source = %s", [source], conn=conn)
    recent: list[datetime] = list(row["recent_blocks"] or []) if row else []
    in_30_days = [t for t in recent if t > now - timedelta(days=30)]
    pause_end = until or now + BACKOFF[min(len(in_30_days), len(BACKOFF) - 1)]
    disable = grey and any(t > now - GREY_DISABLE_WINDOW for t in recent)
    db.execute(
        """
        insert into public.source_health as h (source, enabled, last_error_at, last_error, blocked_until, recent_blocks)
        values (%(source)s, %(enabled)s, now(), %(error)s, %(until)s, array[now()])
        on conflict (source) do update set
          enabled = h.enabled and excluded.enabled,
          last_error_at = now(), last_error = excluded.last_error,
          blocked_until = greatest(coalesce(h.blocked_until, excluded.blocked_until), excluded.blocked_until),
          recent_blocks = (array[now()] || h.recent_blocks)[1:10]
        """,
        {"source": source, "enabled": not disable, "error": f"blocked: {reason}"[:500], "until": pause_end},
        conn=conn,
    )
    add_requests(source, requests, conn=conn)
    log.warning("source.blocked", source=source, reason=reason, until=pause_end.isoformat(), disabled=disable)
    return pause_end
