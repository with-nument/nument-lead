"""Structured logs carry the run id, kind and environment on every line."""

from __future__ import annotations

import json

import pytest
import structlog

from nument_engine.logging import bind_run, get_logger, setup_logging


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
