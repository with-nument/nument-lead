"""Mailbox health and the outreach switches: warm-up maths, the bounce and auth guard, counters, pause and
resume, the pg_cron schedule and `nlead outreach` (lane E5a). Test database only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from typer.testing import CliRunner

from nument_engine.cli import app
from nument_engine.outreach import mailbox as m
from nument_engine.outreach.gmail import MailboxError

from .cli_text import plain
from .outreach_seed import T0, World, rc

runner = CliRunner()
SCHEDULE = [10, 15, 20, 25, 30, 35, 40]


@pytest.fixture
def world(engine_db: str) -> Iterator[World]:
    w = World(engine_db)
    snapshot = w.snapshot()
    try:
        yield w
    finally:
        w.restore(snapshot)


# ---------------------------------------------------------------------------
# Warm-up maths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days_since_start", "week", "cap"),
    [
        (0, 1, 10),
        (6, 1, 10),
        (7, 2, 15),
        (13, 2, 15),
        (14, 3, 20),
        (41, 6, 35),
        (42, 7, 40),
        (300, 43, 40),  # the last value holds
    ],
)
def test_warmup_week_and_cap(days_since_start: int, week: int, cap: int) -> None:
    start = date(2026, 11, 2)
    today = start + timedelta(days=days_since_start)
    assert m.warmup_week(start, today) == week
    assert m.daily_cap(start, today, SCHEDULE) == cap


def test_warmup_before_the_first_send_and_before_a_future_start() -> None:
    assert m.warmup_week(None, date(2026, 11, 17)) == 1 and m.daily_cap(None, date(2026, 11, 17), SCHEDULE) == 10
    assert m.daily_cap(date(2026, 11, 20), date(2026, 11, 17), SCHEDULE) == 0
    assert m.daily_cap(date(2026, 11, 2), date(2026, 11, 17), []) == 0


def test_warmup_done_from_the_last_week() -> None:
    start = date(2026, 10, 1)
    assert not m.warmup_done(None, date(2026, 11, 17), SCHEDULE)
    assert not m.warmup_done(start, start + timedelta(days=41), SCHEDULE)
    assert m.warmup_done(start, start + timedelta(days=42), SCHEDULE)


def test_warmup_schedule_setting_and_fallback(world: World) -> None:
    assert m.warmup_schedule() == SCHEDULE  # the migration default
    world.setting("outreach.warmup", [5, "8", 12])
    assert m.warmup_schedule() == [5, 8, 12]
    world.setting("outreach.warmup", ["lots"])
    assert m.warmup_schedule() == SCHEDULE  # config/outreach.yaml
    world.setting("outreach.warmup", [])
    assert m.warmup_schedule() == SCHEDULE


@pytest.mark.parametrize(("value", "paused"), [(True, True), ("true", True), (1, True), (False, False), ("no", False)])
def test_paused_setting_values(world: World, value: Any, paused: bool) -> None:
    world.setting("outreach.paused", value)
    assert m.is_paused() is paused


# ---------------------------------------------------------------------------
# Pause, resume, errors
# ---------------------------------------------------------------------------


def test_resume_brings_a_paused_mailbox_back(world: World) -> None:
    box = world.mailbox(status="paused", started=date(2026, 11, 10))
    world.update("update public.mailboxes set paused_reason = 'bounce_rate' where id = %s", [box])
    world.setting("outreach.paused", True)
    resumed = m.resume(now=T0)
    assert resumed is not None and (resumed.status, resumed.paused_reason) == ("warming", None)
    assert not m.is_paused()
    world.update(
        "update public.mailboxes set status = 'paused', warmup_started_on = %s where id = %s", [date(2026, 9, 1), box]
    )
    resumed = m.resume(now=T0)
    assert resumed is not None and resumed.status == "active"  # the warm-up is over


def test_resume_leaves_a_broken_mailbox_alone(world: World) -> None:
    world.mailbox(status="error")
    world.setting("outreach.paused", True)
    resumed = m.resume(now=T0)
    assert resumed is not None and resumed.status == "error" and not m.is_paused()


@pytest.mark.parametrize(
    ("kind", "action", "status", "paused"),
    [
        ("auth", "auth_error", "error", False),
        ("rate_limit", "paused", "paused", True),
        ("quota", "paused", "paused", True),
        ("invalid", "noted", "warming", False),
        ("transient", "noted", "warming", False),
    ],
)
def test_record_error(world: World, kind: str, action: str, status: str, paused: bool) -> None:
    box_id = world.mailbox()
    box = m.current()
    assert box is not None and box.id == box_id
    assert m.record_error(box, MailboxError(kind, "gmail 429: slow down")) == action
    row = world.one("select status, last_error from public.mailboxes where id = %s", [box_id])
    assert row["status"] == status and row["last_error"].startswith(f"{kind}: gmail 429")
    assert m.is_paused() is paused


def test_current_prefers_a_usable_mailbox(world: World) -> None:
    world.mailbox(status="disconnected", email="old.nument@gmail.com")
    world.mailbox(status="active")
    box = m.current()
    assert box is not None and box.email == "hello.nument@gmail.com" and box.usable


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def _sends(world: World, n: int, *, bounced: int = 0, at: Any = None) -> list[str]:
    ids = []
    for i in range(n):
        t = world.thread(world.lead(), day0="sent", followups="cancelled", status="stopped", steps=(0,))
        world.update(
            "update public.email_messages set sent_at = %s, error = %s where id = %s",
            [at or T0 - timedelta(hours=2 + i), "bounced" if i < bounced else None, t["steps"][0]],
        )
        ids.append(t["steps"][0])
    return ids


def test_guard_does_nothing_while_outreach_is_off(world: World) -> None:
    world.mailbox()
    assert m.run(rc(), now=T0) == {"skipped": "outreach off"}


def test_guard_without_a_mailbox(world: World) -> None:
    world.outreach_on()
    assert m.run(rc(), now=T0) == {"skipped": "no mailbox"}


def test_guard_pauses_at_the_bounce_limit(world: World) -> None:
    world.outreach_on()
    box = world.mailbox()
    _sends(world, 50, bounced=1)  # 2 percent
    out = m.run(rc(), token_check=lambda _a: None, now=T0)
    assert out["bounces"] == {"bounced": 1, "of": 50, "limit_pct": 3.0} and not m.is_paused()
    _sends(world, 1, bounced=1, at=T0 - timedelta(minutes=30))  # the newest 50 now hold 2 bounces: 4 percent
    out = m.run(rc(), token_check=lambda _a: None, now=T0)
    assert out["bounces"]["over_limit"] and out["bounces"]["paused"]
    assert m.is_paused()
    row = world.one("select status, paused_reason from public.mailboxes where id = %s", [box])
    assert row == {"status": "paused", "paused_reason": "bounce_rate"}


def test_bounces_before_a_pause_never_pause_twice(world: World) -> None:
    world.outreach_on()
    world.mailbox()
    _sends(world, 10, bounced=2)
    m.run(rc(), token_check=lambda _a: None, now=T0)
    assert m.is_paused()
    m.resume(now=T0)
    later = T0 + timedelta(hours=1)
    out = m.run(rc(), token_check=lambda _a: None, now=later)
    assert out["bounces"]["of"] == 0 and not m.is_paused()
    _sends(world, 4, at=later + timedelta(minutes=5))
    _sends(world, 1, bounced=1, at=later + timedelta(minutes=6))
    out = m.run(rc(), token_check=lambda _a: None, now=later + timedelta(minutes=30))
    assert out["bounces"]["bounced"] == 1 and out["bounces"]["of"] == 5 and m.is_paused()


def test_the_bounce_limit_is_a_setting(world: World) -> None:
    world.outreach_on(bounce_pause_pct=25)
    world.mailbox()
    _sends(world, 10, bounced=2)
    out = m.run(rc(), token_check=lambda _a: None, now=T0)
    assert out["bounces"]["limit_pct"] == 25.0 and not m.is_paused()


def test_guard_marks_a_revoked_token(world: World) -> None:
    world.outreach_on()
    box = world.mailbox()

    def revoked(address: str) -> None:
        assert address == "hello.nument@gmail.com"
        raise MailboxError("auth", "oauth 400: invalid_grant Token has been expired or revoked.")

    out = m.run(rc(), token_check=revoked, now=T0)
    assert out["auth"] == "failed" and out["mailbox"] == "error"
    row = world.one("select status, paused_reason, last_error from public.mailboxes where id = %s", [box])
    assert row["status"] == "error" and row["paused_reason"] == "auth" and "invalid_grant" in row["last_error"]


def test_guard_ignores_a_passing_network_problem(world: World) -> None:
    world.outreach_on()
    world.mailbox()

    def down(_address: str) -> None:
        raise MailboxError("transient", "token refresh failed: ConnectError")

    out = m.run(rc(), token_check=down, now=T0)
    assert out["auth"] == "unchecked: transient" and out["mailbox"] == "warming"


def test_guard_without_gmail_settings_reports_auth(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.outreach_on()
    world.mailbox()
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    out = m.run(rc(), now=T0)  # the real check: no OAuth client configured
    assert out["auth"] == "failed" and out["mailbox"] == "error"


def test_guard_counts_today_in_india_and_finishes_the_warmup(world: World) -> None:
    world.outreach_on()
    box = world.mailbox(started=T0.date() - timedelta(days=42))
    _sends(world, 2, at=T0 - timedelta(hours=2))  # 18:30 IST today
    _sends(world, 1, at=T0 - timedelta(hours=16))  # 04:30 IST today
    _sends(world, 1, at=T0 - timedelta(hours=21))  # 23:30 IST yesterday
    out = m.run(rc(), token_check=lambda _a: None, now=T0)
    assert out["sent_today"] == 3 and out["warmup"] == "done" and out["mailbox"] == "active"
    row = world.one("select sent_today, sent_day from public.mailboxes where id = %s", [box])
    assert row == {"sent_today": 3, "sent_day": date(2026, 11, 17)}


def test_guard_dry_run_changes_nothing(world: World) -> None:
    world.outreach_on()
    box = world.mailbox()
    _sends(world, 5, bounced=3)

    def revoked(_address: str) -> None:
        raise MailboxError("auth", "invalid_grant")

    out = m.run(rc(dry_run=True), token_check=revoked, now=T0)
    assert out["dry_run"] and out["bounces"]["over_limit"] and "paused" not in out["bounces"]
    assert not m.is_paused()
    assert world.one("select status from public.mailboxes where id = %s", [box])["status"] == "warming"


# ---------------------------------------------------------------------------
# The pg_cron schedule (a stand-in for pg_cron, inside a rolled-back transaction)
# ---------------------------------------------------------------------------

CRON_STUB = """
create schema cron;
create table cron.job (jobid bigserial primary key, jobname text unique, schedule text, command text,
                       active boolean not null default true);
create function cron.schedule(job_name text, schedule text, command text) returns bigint language sql as
  $$ insert into cron.job (jobname, schedule, command) values (job_name, schedule, command) returning jobid $$;
create function cron.unschedule(job_name text) returns boolean language sql as
  $$ delete from cron.job where jobname = job_name returning true $$;
create function public.dispatch_workflow(workflow text, inputs jsonb default '{}'::jsonb) returns bigint
  language sql as $$ select 1::bigint $$;
"""


def test_schedule_on_and_off(db_conn: Any) -> None:
    assert not m.cron_available(conn=db_conn)
    with pytest.raises(RuntimeError, match="pg_cron"):
        m.schedule(True, "prod", conn=db_conn)
    db_conn.execute(CRON_STUB)
    assert m.cron_available(conn=db_conn) and m.schedule_state(conn=db_conn) is None
    assert m.schedule(True, "prod", conn=db_conn) == "created"
    job = m.schedule_state(conn=db_conn)
    assert job == {
        "schedule": "*/15 * * * *",
        "command": """select public.dispatch_workflow('outreach.yml', '{"env": "prod"}'::jsonb)""",
        "active": True,
    }
    db_conn.execute(job["command"])  # the command pg_cron runs is valid SQL
    assert m.schedule(True, "dev", conn=db_conn) == "replaced"
    assert '"env": "dev"' in m.schedule_state(conn=db_conn)["command"]
    assert db_conn.execute("select count(*) as n from cron.job").fetchone()["n"] == 1
    assert m.schedule(False, "dev", conn=db_conn) == "dropped"
    assert m.schedule(False, "dev", conn=db_conn) == "absent"
    assert m.schedule_state(conn=db_conn) is None


def test_cron_command_only_for_known_environments() -> None:
    with pytest.raises(ValueError, match="unknown environment"):
        m.cron_command("prod'); drop table x; --")


# ---------------------------------------------------------------------------
# Status and the command line
# ---------------------------------------------------------------------------


def test_status_and_its_lines(world: World) -> None:
    world.outreach_on("manual")
    world.mailbox(started=T0.date() - timedelta(days=8))
    _sends(world, 2, bounced=1)
    world.thread(world.lead(), day0="review")
    info = m.status(now=T0)
    assert info["mode"] == "manual" and info["paused"] is False and info["postal_address_set"]
    assert info["mailbox"]["warmup_week"] == 2 and info["mailbox"]["cap_24h"] == 15
    assert info["mailbox"]["sent_24h"] == 2 and info["bounces"] == {"bounced": 1, "of": 2}
    assert info["queue"] == {"draft": 3, "review": 1, "sent": 2} and info["schedule"] is None
    lines = m.status_lines(info)
    assert lines[0] == "mode: manual"
    assert "dev sandbox: not set (dev sends nothing)" in lines
    assert any(line.startswith("mailbox: hello.nument@gmail.com, warming, warm-up week 2, 2 of 15") for line in lines)
    assert "bounces: 1 of the last 2 sends" in lines and "schedule: off" in lines


def test_status_lines_without_a_mailbox_or_address() -> None:
    info = {
        "mode": "off",
        "paused": True,
        "sandbox_to": "sandbox@example.com",
        "postal_address_set": False,
        "queue": {},
        "bounces": {"bounced": 0, "of": 0},
        "schedule": {"schedule": "*/15 * * * *", "active": True},
        "mailbox": None,
    }
    lines = m.status_lines(info)
    assert lines[0] == "mode: off (paused)" and "dev sandbox: sandbox@example.com" in lines
    assert any("postal address: missing" in line for line in lines)
    assert "mailbox: none connected (connect Gmail in the app)" in lines
    assert "queue: empty" in lines and "schedule: */15 * * * * (active)" in lines


def test_cli_status(world: World) -> None:
    world.outreach_on("auto")
    world.mailbox()
    result = runner.invoke(app, ["outreach", "status"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "mode: auto"
    assert "mailbox: hello.nument@gmail.com, warming, warm-up week 1, 0 of 10 in the last 24 hours" in result.output


def test_cli_pause_and_resume(world: World) -> None:
    world.outreach_on()
    world.mailbox(status="paused")
    dry = runner.invoke(app, ["outreach", "pause", "--dry-run"])
    assert dry.exit_code == 0 and "nothing changed" in dry.output and not m.is_paused()
    paused = runner.invoke(app, ["outreach", "pause"])
    assert paused.exit_code == 0, paused.output
    assert m.is_paused()
    resumed = runner.invoke(app, ["outreach", "resume"])
    assert resumed.exit_code == 0, resumed.output
    assert "mailbox hello.nument@gmail.com is warming" in plain(resumed.output) and not m.is_paused()


def test_cli_resume_warns_about_a_broken_mailbox(world: World) -> None:
    world.mailbox(status="error")
    result = runner.invoke(app, ["outreach", "resume"])
    assert result.exit_code == 0 and "connected again" in plain(result.output)


def test_cli_schedule_needs_pg_cron(world: World) -> None:
    dry = runner.invoke(app, ["outreach", "schedule", "on", "--dry-run"])
    assert dry.exit_code == 0 and "Would create the pg_cron job nlead-outreach (dev)" in plain(dry.output)
    result = runner.invoke(app, ["outreach", "schedule", "on"])
    assert result.exit_code == 1 and "pg_cron or public.dispatch_workflow is not available" in plain(result.output)
    bad = runner.invoke(app, ["outreach", "schedule", "sometimes"])
    assert bad.exit_code == 2


def test_cli_outreach_help() -> None:
    result = runner.invoke(app, ["outreach", "--help"])
    assert result.exit_code == 0
    text = plain(result.output)
    for command in ("status", "schedule", "pause", "resume"):
        assert command in text
