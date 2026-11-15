"""Mailbox health and the outreach switches: warm-up caps, the bounce and auth guard, daily counters, pause,
resume and the 15-minute schedule (contract 4.6, lane E5a).

- Warm-up: the daily cap comes from settings `outreach.warmup` (default from config/outreach.yaml, 10, 15, 20
  ... 40), one value per week since `mailboxes.warmup_started_on` (the first send sets it); the last value holds.
  The cap counts every send in the last 24 hours, so a recipient's working day that spans two Indian dates
  never doubles it.
- Guard (phase `mailbox_guard`, after the sends of every outreach run): over the last `bounce_pause.last_sends`
  sent messages since the last bounce pause, the share with error 'bounced'; at `outreach.bounce_pause_pct` or
  more the mailbox is paused and settings `outreach.paused` is true until a person resumes. A Gmail token that
  no longer works puts the mailbox in 'error' (connect Gmail again in the app). The daily counters are
  recounted from the messages themselves.
- Switches: `nlead outreach pause|resume|schedule on|off|status` call the functions at the end of this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from psycopg import Connection

from .. import db
from ..logging import get_logger
from ..pipeline.runs import RunContext, outreach_mode
from .gmail import MailboxError
from .net import outreach_config

log = get_logger()

IST: Final = ZoneInfo("Asia/Kolkata")
USABLE: Final = ("warming", "active")
CRON_JOB: Final = "nlead-outreach"
CRON_EVERY: Final = "*/15 * * * *"
PAUSED_KEY: Final = "outreach.paused"
BOUNCE_PAUSED_AT_KEY: Final = "outreach.bounce_paused_at"
MAILBOX_COLUMNS: Final = (
    "id::text as id, email, display_name, status, paused_reason, warmup_started_on, sent_today, sent_day, "
    "last_error, connected_at"
)


@dataclass(frozen=True)
class Mailbox:
    id: str
    email: str
    display_name: str
    status: str
    paused_reason: str | None
    warmup_started_on: date | None
    sent_today: int
    sent_day: date | None
    last_error: str | None = None
    connected_at: datetime | None = None

    @property
    def usable(self) -> bool:
        return self.status in USABLE


def truthy(value: Any) -> bool:
    """A settings value as a boolean (true, "true", 1 and "yes" are true)."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def is_paused(*, conn: Connection[Any] | None = None) -> bool:
    return truthy(db.get_setting(PAUSED_KEY, False, conn=conn))


def current(*, conn: Connection[Any] | None = None) -> Mailbox | None:
    """The outreach mailbox: a usable one first, else the most recently connected one."""
    row = db.fetch_one(
        f"select {MAILBOX_COLUMNS} from public.mailboxes "
        "order by (status in ('warming','active')) desc, connected_at desc nulls last, updated_at desc limit 1",
        conn=conn,
    )
    return Mailbox(**row) if row else None


def ist_day(at: datetime) -> date:
    return at.astimezone(IST).date()


# ---------------------------------------------------------------------------
# Warm-up maths
# ---------------------------------------------------------------------------


def warmup_schedule(*, conn: Connection[Any] | None = None) -> list[int]:
    """Daily caps per warm-up week: settings `outreach.warmup`, else config/outreach.yaml."""
    fallback = [int(v) for v in outreach_config().get("warmup") or [10]]
    raw = db.get_setting("outreach.warmup", None, conn=conn)
    if raw is None:
        return fallback
    try:
        caps = [max(int(v), 0) for v in raw]
    except (TypeError, ValueError):
        log.warning("mailbox.bad_warmup_setting")
        return fallback
    return caps or fallback


def warmup_week(started_on: date | None, today: date) -> int:
    """Week number of the warm-up, from 1. A mailbox that never sent is in week 1; 0 before a future start."""
    if started_on is None:
        return 1
    if today < started_on:
        return 0
    return (today - started_on).days // 7 + 1


def daily_cap(started_on: date | None, today: date, schedule: list[int]) -> int:
    """How many emails the mailbox may send in 24 hours this week; the last value of the schedule holds."""
    week = warmup_week(started_on, today)
    if week == 0 or not schedule:
        return 0
    return schedule[min(week, len(schedule)) - 1]


def warmup_done(started_on: date | None, today: date, schedule: list[int]) -> bool:
    """True from the week the schedule reaches its last value."""
    return started_on is not None and warmup_week(started_on, today) >= len(schedule)


def sent_last_24h(mailbox_id: str, now: datetime, *, conn: Connection[Any] | None = None) -> int:
    """Emails this mailbox sent in the 24 hours before `now`, plus any being sent right now."""
    return int(
        db.scalar(
            "select count(*) from public.email_messages m join public.email_threads t on t.id = m.thread_id "
            "where m.direction = 'out' and (t.mailbox_id = %(box)s or t.mailbox_id is null) "
            "and (m.status = 'sending' or (m.sent_at is not null and m.sent_at > %(since)s))",
            {"box": mailbox_id, "since": now - timedelta(hours=24)},
            conn=conn,
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Pausing, resuming and errors
# ---------------------------------------------------------------------------


def pause(reason: str, *, mailbox: Mailbox | None = None, conn: Connection[Any] | None = None) -> None:
    """Stop all sending: settings outreach.paused, and the mailbox paused with the reason."""
    db.set_setting(PAUSED_KEY, True, conn=conn)
    if mailbox is not None:
        db.execute(
            "update public.mailboxes set status = 'paused', paused_reason = %s, updated_at = now() "
            "where id = %s and status in ('warming', 'active', 'paused')",
            [reason, mailbox.id],
            conn=conn,
        )
    log.warning("mailbox.paused", reason=reason)


def resume(*, now: datetime | None = None, conn: Connection[Any] | None = None) -> Mailbox | None:
    """Sending may go on: outreach.paused false, and a paused mailbox back to warming or active. A mailbox in
    'error' or 'disconnected' needs Gmail connected again in the app, so it stays as it is."""
    today = ist_day(now or datetime.now(UTC))
    db.set_setting(PAUSED_KEY, False, conn=conn)
    box = current(conn=conn)
    if box is not None and box.status == "paused":
        status = "active" if warmup_done(box.warmup_started_on, today, warmup_schedule(conn=conn)) else "warming"
        db.execute(
            "update public.mailboxes set status = %s, paused_reason = null, updated_at = now() where id = %s",
            [status, box.id],
            conn=conn,
        )
        box = current(conn=conn)
    log.info("mailbox.resumed")
    return box


def record_error(mailbox: Mailbox, err: MailboxError, *, conn: Connection[Any] | None = None) -> str:
    """What a Gmail error does to the mailbox: auth puts it in 'error' (connect again); a rate limit or the daily
    quota pauses all sending until a person resumes; anything else is only noted. Returns the action taken.
    The reply side (inbox) may call this too."""
    note = f"{err.kind}: {err}"[:500]
    if err.kind == "auth":
        db.execute(
            "update public.mailboxes set status = 'error', paused_reason = 'auth', last_error = %s, "
            "updated_at = now() where id = %s",
            [note, mailbox.id],
            conn=conn,
        )
        log.error("mailbox.auth_failed", kind=err.kind)
        return "auth_error"
    db.execute(
        "update public.mailboxes set last_error = %s, updated_at = now() where id = %s", [note, mailbox.id], conn=conn
    )
    if err.kind in ("rate_limit", "quota"):
        pause(f"gmail_{err.kind}", mailbox=mailbox, conn=conn)
        return "paused"
    return "noted"


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def bounce_settings(*, conn: Connection[Any] | None = None) -> tuple[float, int]:
    """(percent that pauses, how many recent sends are looked at)."""
    cfg = outreach_config().get("bounce_pause") or {}
    default = cfg.get("percent", 3)
    pct = float(db.get_setting("outreach.bounce_pause_pct", default, conn=conn) or default)
    return pct, int(cfg.get("last_sends", 50))


def bounce_window(*, conn: Connection[Any] | None = None) -> tuple[int, int]:
    """(bounced, sent) over the last N sent messages since the last bounce pause. Bounces before that pause were
    seen by a person who resumed, so they never pause the mailbox twice."""
    _pct, last = bounce_settings(conn=conn)
    since = db.get_setting(BOUNCE_PAUSED_AT_KEY, None, conn=conn)
    row = db.fetch_one(
        "select count(*) as sent, count(*) filter (where error = 'bounced') as bounced from ("
        "select error from public.email_messages where direction = 'out' and status = 'sent' "
        "and sent_at > coalesce(%s::timestamptz, '-infinity') order by sent_at desc limit %s) recent",
        [since, last],
        conn=conn,
    )
    return (int(row["bounced"]), int(row["sent"])) if row else (0, 0)


def check_bounces(
    mailbox: Mailbox | None, now: datetime, *, dry_run: bool = False, conn: Connection[Any] | None = None
) -> dict[str, Any]:
    """Pause at the bounce limit. The send phase calls this too, before it sends anything."""
    pct, _last = bounce_settings(conn=conn)
    bounced, sent = bounce_window(conn=conn)
    out: dict[str, Any] = {"bounced": bounced, "of": sent, "limit_pct": pct}
    if sent and bounced * 100 >= pct * sent:
        out["over_limit"] = True
        if not dry_run:
            pause("bounce_rate", mailbox=mailbox, conn=conn)
            db.set_setting(BOUNCE_PAUSED_AT_KEY, now.isoformat(), conn=conn)
            out["paused"] = True
    return out


def refresh_counters(mailbox: Mailbox, now: datetime, *, conn: Connection[Any] | None = None) -> int:
    """Recount today's sends (Indian date, for the app) from the messages themselves."""
    today = ist_day(now)
    start = datetime.combine(today, time(0), tzinfo=IST)
    count = int(
        db.scalar(
            "select count(*) from public.email_messages m join public.email_threads t on t.id = m.thread_id "
            "where m.direction = 'out' and m.sent_at >= %s and m.sent_at <= %s "
            "and (t.mailbox_id = %s or t.mailbox_id is null)",
            [start, now, mailbox.id],
            conn=conn,
        )
        or 0
    )
    db.execute(
        "update public.mailboxes set sent_today = %s, sent_day = %s, updated_at = now() where id = %s",
        [count, today, mailbox.id],
        conn=conn,
    )
    return count


def check_token(address: str) -> None:
    """Refresh the Gmail access token once (MailboxError when Gmail refuses it)."""
    from .gmail import connect

    with connect(address) as client:
        client.access_token()


def run(
    rc: RunContext,
    *,
    token_check: Callable[[str], None] | None = None,
    now: datetime | None = None,
    **_: Any,
) -> dict[str, Any]:
    """The guard: bounce rate, Gmail auth and today's counters (phase mailbox_guard)."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    box = current()
    if box is None:
        return {"skipped": "no mailbox"}
    now = now or datetime.now(UTC)
    dry = rc.opts.dry_run
    out: dict[str, Any] = {"mailbox": box.status}
    out["bounces"] = check_bounces(box, now, dry_run=dry)
    if box.usable:
        try:
            (token_check or check_token)(box.email)
        except MailboxError as err:
            out["auth"] = "failed" if err.kind == "auth" else f"unchecked: {err.kind}"
            if err.kind == "auth" and not dry:
                record_error(box, err)
    if dry:
        out["dry_run"] = True
        return out
    out["sent_today"] = refresh_counters(box, now)
    box = current() or box
    if box.status == "warming" and warmup_done(box.warmup_started_on, ist_day(now), warmup_schedule()):
        db.execute("update public.mailboxes set status = 'active', updated_at = now() where id = %s", [box.id])
        out["warmup"] = "done"
    out["mailbox"] = (current() or box).status
    return out


# ---------------------------------------------------------------------------
# Switches for `nlead outreach`
# ---------------------------------------------------------------------------


def cron_available(*, conn: Connection[Any] | None = None) -> bool:
    """pg_cron and the dispatch function from 0013 exist (Supabase only)."""
    return bool(
        db.scalar(
            "select to_regprocedure('cron.schedule(text,text,text)') is not null "
            "and to_regprocedure('public.dispatch_workflow(text,jsonb)') is not null",
            conn=conn,
        )
    )


def cron_command(env: str) -> str:
    """The SQL pg_cron runs: start outreach.yml for this environment through GitHub's dispatch API."""
    if env not in ("dev", "prod"):
        raise ValueError(f"unknown environment {env!r}")
    return f"""select public.dispatch_workflow('outreach.yml', '{{"env": "{env}"}}'::jsonb)"""


def schedule_state(*, conn: Connection[Any] | None = None) -> dict[str, Any] | None:
    """The pg_cron job, or None when it does not exist (or pg_cron is not here)."""
    if not cron_available(conn=conn):
        return None
    row = db.fetch_one(
        "select schedule, command, active from cron.job where jobname = %s limit 1", [CRON_JOB], conn=conn
    )
    return dict(row) if row else None


def schedule(on: bool, env: str, *, conn: Connection[Any] | None = None) -> str:
    """Create (every 15 minutes) or drop the pg_cron job that starts the outreach run. Returns what changed."""
    if not cron_available(conn=conn):
        raise RuntimeError("pg_cron or public.dispatch_workflow is not available in this database (Supabase only)")
    command = cron_command(env)
    had = schedule_state(conn=conn) is not None
    if had:
        db.execute("select cron.unschedule(%s)", [CRON_JOB], conn=conn)
    if on:
        db.execute("select cron.schedule(%s, %s, %s)", [CRON_JOB, CRON_EVERY, command], conn=conn)
        return "replaced" if had else "created"
    return "dropped" if had else "absent"


def status(*, now: datetime | None = None, conn: Connection[Any] | None = None) -> dict[str, Any]:
    """Everything `nlead outreach status` prints."""
    now = now or datetime.now(UTC)
    box = current(conn=conn)
    queue = {
        r["status"]: int(r["n"])
        for r in db.fetch_all(
            "select status, count(*) as n from public.email_messages where direction = 'out' group by status "
            "order by status",
            conn=conn,
        )
    }
    bounced, of = bounce_window(conn=conn)
    info: dict[str, Any] = {
        "mode": outreach_mode(),
        "paused": is_paused(conn=conn),
        "sandbox_to": db.get_setting("outreach.sandbox_to", None, conn=conn),
        "postal_address_set": bool(str(db.get_setting("outreach.postal_address", "", conn=conn) or "").strip()),
        "queue": queue,
        "bounces": {"bounced": bounced, "of": of},
        "schedule": schedule_state(conn=conn),
        "mailbox": None,
    }
    if box is not None:
        today = ist_day(now)
        info["mailbox"] = {
            "email": box.email,
            "status": box.status,
            "paused_reason": box.paused_reason,
            "warmup_week": warmup_week(box.warmup_started_on, today),
            "cap_24h": daily_cap(box.warmup_started_on, today, warmup_schedule(conn=conn)),
            "sent_24h": sent_last_24h(box.id, now, conn=conn),
            "last_error": box.last_error,
        }
    return info
