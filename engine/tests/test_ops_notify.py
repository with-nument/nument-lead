"""Email delivery: recipients per kind, one email per recipient, quiet without a key, never breaks a run."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
import respx

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.ops import notify

EMAIL = notify.Email("Subject", "<p>Hi</p>", "Hi")


def configure(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings_module.get_settings.cache_clear()


def sent_payloads(route: respx.Route) -> list[dict[str, Any]]:
    return [json.loads(call.request.content) for call in route.calls]


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def test_nothing_is_sent_without_a_key() -> None:
    assert not notify.email_configured()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        assert notify.send(EMAIL, ["founder@example.com"]) == 0
    assert not route.called


def test_each_recipient_gets_their_own_email(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RESEND_API_KEY="re_test_not_real")
    to = [notify.Recipient("a@example.com"), notify.Recipient("b@example.com", admin=True), "c@example.com"]
    with respx.mock() as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        assert notify.send(EMAIL, to) == 3
    payloads = sent_payloads(route)
    assert [p["to"] for p in payloads] == [["a@example.com"], ["b@example.com"], ["c@example.com"]]
    first = payloads[0]
    assert first["from"] == "Nument Leads <leads@nument.in>" and first["reply_to"] == "heyy.abhigyan@gmail.com"
    assert first["subject"] == "Subject" and first["html"] == "<p>Hi</p>" and first["text"] == "Hi"
    assert "cc" not in first and "bcc" not in first
    assert route.calls.last.request.headers["authorization"] == "Bearer re_test_not_real"


def test_sender_and_reply_to_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(
        monkeypatch,
        RESEND_API_KEY="re_test_not_real",
        ALERT_EMAIL_FROM="Leads <x@nument.in>",
        ALERT_REPLY_TO="team@nument.in",
    )
    with respx.mock() as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        notify.send(EMAIL, ["a@example.com"])
    payload = sent_payloads(route)[0]
    assert payload["from"] == "Leads <x@nument.in>" and payload["reply_to"] == "team@nument.in"
    # GitHub passes an unset repository variable as an empty string: the defaults apply.
    configure(monkeypatch, ALERT_EMAIL_FROM="", ALERT_REPLY_TO=" ", APP_URL="")
    with respx.mock() as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        notify.send(EMAIL, ["a@example.com"])
    payload = sent_payloads(route)[0]
    assert payload["from"] == notify.DEFAULT_SENDER and payload["reply_to"] == "heyy.abhigyan@gmail.com"
    assert settings_module.get_settings().app_url == "https://nument-leads-web.onrender.com"


def test_one_failure_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, RESEND_API_KEY="re_test_not_real")
    with respx.mock() as mock:
        mock.post(notify.RESEND_URL).mock(
            side_effect=[httpx.ConnectError("down"), httpx.Response(422, json={}), httpx.Response(200, json={})]
        )
        assert notify.send(EMAIL, ["a@example.com", "b@example.com", "c@example.com"]) == 1


def test_step_summary_appends_only_inside_actions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert notify.step_summary("# Hi") is False
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert notify.step_summary("# Hi") and notify.step_summary("# Again")
    assert target.read_text() == "# Hi\n\n# Again\n\n"


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------


@pytest.fixture
def recipients_table(engine_db: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(engine_db, autocommit=True) as conn:
        conn.execute("delete from public.notify_recipients")
        yield conn
        conn.execute("delete from public.notify_recipients")
        conn.execute("delete from auth.users where email = 'boss@example.com'")


def test_empty_table_falls_back_to_alert_email(
    recipients_table: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert notify.recipients("morning") == []  # no table rows and no ALERT_EMAIL: nobody
    configure(monkeypatch, ALERT_EMAIL="Founder@Example.com")
    for kind in notify.KINDS:
        assert notify.recipients(kind) == [notify.Recipient("founder@example.com", admin=True)]  # type: ignore[arg-type]


def test_recipients_follow_each_persons_choices(
    recipients_table: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, ALERT_EMAIL="founder@example.com")
    conn = recipients_table
    conn.execute(
        "insert into public.notify_recipients (email, name, morning, alerts, weekly, active) values "
        "('boss@example.com', 'Boss', true, true, true, true),"
        "('caller@example.com', 'Caller', true, false, true, true),"
        "('weekly@example.com', null, false, false, true, true),"
        "('gone@example.com', 'Gone', true, true, true, false)"
    )
    user = conn.execute("insert into auth.users (email) values ('boss@example.com') returning id").fetchone()
    assert user is not None
    conn.execute("update public.profiles set role = 'admin' where user_id = %s", [user[0]])

    def emails(kind: notify.Kind) -> list[str]:
        return [r.email for r in notify.recipients(kind)]

    assert emails("morning") == ["boss@example.com", "caller@example.com"]
    assert emails("alerts") == ["boss@example.com"]
    assert emails("weekly") == ["boss@example.com", "caller@example.com", "weekly@example.com"]
    by_email = {r.email: r for r in notify.recipients("weekly")}
    assert by_email["boss@example.com"].admin and by_email["boss@example.com"].name == "Boss"
    assert not by_email["caller@example.com"].admin and not by_email["weekly@example.com"].admin
    # The founder's fallback is not added while the table has rows.
    assert "founder@example.com" not in emails("alerts")
    with pytest.raises(ValueError, match="unknown email kind"):
        notify.recipients("daily")  # type: ignore[arg-type]


def test_unreadable_table_still_reaches_the_founder(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, ALERT_EMAIL="founder@example.com")

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise psycopg.OperationalError("database is down")

    monkeypatch.setattr(db, "fetch_all", broken)
    assert notify.recipients("alerts") == [notify.Recipient("founder@example.com", admin=True)]
