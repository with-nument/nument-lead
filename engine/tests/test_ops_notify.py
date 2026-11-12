"""Optional email and job summary delivery: quiet when not configured, never breaks a run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from nument_engine import settings as settings_module
from nument_engine.ops import notify


def configure(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings_module.get_settings.cache_clear()


def test_email_is_a_no_op_until_configured() -> None:
    assert not notify.email_configured()
    assert notify.send_email("subject", "body") is False


def test_email_goes_to_resend_with_the_default_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, ALERT_EMAIL="founder@example.com", RESEND_API_KEY="re_test_not_real", ALERT_EMAIL_FROM="")
    with respx.mock() as mock:
        route = mock.post(notify.RESEND_URL).respond(200, json={"id": "1"})
        assert notify.send_email("Weekly report", "# Report") is True
    sent: dict[str, Any] = json.loads(route.calls.last.request.content)
    assert sent["from"] == notify.DEFAULT_SENDER and sent["to"] == ["founder@example.com"]
    assert route.calls.last.request.headers["authorization"] == "Bearer re_test_not_real"


def test_email_failures_are_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, ALERT_EMAIL="founder@example.com", RESEND_API_KEY="re_test_not_real")
    with respx.mock() as mock:
        mock.post(notify.RESEND_URL).mock(side_effect=httpx.ConnectError("down"))
        assert notify.send_email("Alert", "body") is False


def test_step_summary_appends_only_inside_actions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert notify.step_summary("# Hi") is False
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert notify.step_summary("# Hi") and notify.step_summary("# Again")
    assert target.read_text() == "# Hi\n\n# Again\n\n"
