"""Structured logs carry the run id, kind and environment on every line."""

from __future__ import annotations

import json

import pytest
import structlog

from nument_engine.logging import bind_run, get_logger, mask_text, setup_logging


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_json_lines_include_run_context(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(json_output=True)
    bind_run("run-123", "night", "dev")
    get_logger("test").info("stage.done", rows=3)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "stage.done" and line["rows"] == 3
    assert (line["run_id"], line["run_kind"], line["env"], line["level"]) == ("run-123", "night", "dev", "info")
    assert line["timestamp"].endswith("Z")


def test_level_filter(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(level="warning", json_output=True)
    log = get_logger("test")
    log.info("hidden")
    log.warning("shown")
    out = capsys.readouterr().out
    assert "hidden" not in out and "shown" in out


def test_bad_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="log level"):
        setup_logging(level="LOUD")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail jane.doe@acme.co.uk now", "mail j***@acme.co.uk now"),
        ("to=Founder+x@startup.io", "to=F***@startup.io"),
        ("call +919876543210", "call +91********10"),
        ("call (415) 555-1234 today", "call (415********34 today"),
        ("on 2026-11-15 at 02:00:00", "on 2026-11-15 at 02:00:00"),
        ("run 6f1c2a90-1234-4abc-8def-1234567890ab", "run 6f1c2a90-1234-4abc-8def-1234567890ab"),
        ("rows 123456 in 4.5s", "rows 123456 in 4.5s"),
        ("no personal data here", "no personal data here"),
    ],
)
def test_mask_text(text: str, expected: str) -> None:
    assert mask_text(text) == expected


def test_log_lines_mask_emails_and_phones(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(json_output=True)
    bind_run("run-123", "outreach", "dev")
    get_logger("test").info(
        "email.sent", to="jane@acme.com", phones=["+14155551234"], detail={"from": "Jane <jane@acme.com>"}
    )
    out = capsys.readouterr().out
    assert "jane@acme.com" not in out and "+14155551234" not in out
    line = json.loads(out.strip().splitlines()[-1])
    assert line["to"] == "j***@acme.com" and line["detail"]["from"] == "Jane <j***@acme.com>"
    assert line["phones"] == ["+14*******34"] and line["run_id"] == "run-123"


def test_exception_text_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(json_output=True)
    try:
        raise ValueError("duplicate contact founder@acme.com")
    except ValueError:
        get_logger("test").exception("lookup.failed")
    out = capsys.readouterr().out
    assert "founder@acme.com" not in out and "f***@acme.com" in out
