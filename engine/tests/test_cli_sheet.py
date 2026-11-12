"""CLI wiring of the sheet, run, backup and migration commands added in Steps 13, 14 and 20."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.cli import app
from nument_engine.sheet import client

from .cli_text import plain
from .sheets_fake import FakeSheets

runner = CliRunner()


@pytest.mark.parametrize(
    ("command", "options"),
    [
        (["sheet", "push"], ["--light", "--resort"]),
        (["sheet", "pull"], ["--seed-snapshots", "--legacy-root"]),
        (["sheet", "sync"], ["--light"]),
        (["sheet", "render"], ["--out"]),
        (["sheet", "check"], []),
        (["run", "sheet"], ["--light"]),
        (["backup"], ["--out"]),
        (["migrate-legacy"], ["--root"]),
    ],
)
def test_new_options_have_help(command: list[str], options: list[str]) -> None:
    result = runner.invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    for option in options:
        assert option in text


@pytest.fixture
def staging(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSheets]:
    monkeypatch.setenv("SHEET_STAGING_ID", "cli-book")
    settings_module.get_settings.cache_clear()
    fake = FakeSheets()
    fake.add_book("cli-book")
    client.use_api(lambda: fake)
    saved = db.get_setting("sheet_state")
    db.execute("delete from public.sheet_snapshots")
    yield fake
    client.use_api(None)
    db.set_setting("sheet_state", saved)
    db.execute("delete from public.sheet_snapshots")


def test_sheet_push_dry_run_prints_stats_and_records_the_run(staging: FakeSheets) -> None:
    result = runner.invoke(app, ["--pretty-logs", "sheet", "push", "--dry-run"])
    assert result.exit_code == 0, result.output
    lines = [json.loads(x) for x in result.stdout.splitlines() if x.startswith("{")]
    stats = next(x for x in lines if "views" in x)
    assert set(stats["views"]) == {"staging_master", "staging_caller"} and staging.batches == []
    row = db.fetch_one("select kind, status, stats from public.runs order by started_at desc limit 1")
    assert row is not None and (row["kind"], row["status"]) == ("sheet_sync", "ok")
    assert row["stats"]["push"]["rows"] == stats["rows"]


def test_unadopted_live_sheet_fails_with_a_clear_message(staging: FakeSheets, monkeypatch: pytest.MonkeyPatch) -> None:
    staging.add_book("live-book", ("Today", "Pipeline", "Lead details"))
    monkeypatch.setenv("SHEET_STAGING_ID", "live-book")
    settings_module.get_settings.cache_clear()
    db.execute(
        "update public.settings set value = value - 'staging_master' - 'staging_caller' where key = 'sheet_state'"
    )
    result = runner.invoke(app, ["sheet", "sync"])
    assert result.exit_code == 1 and "seed-snapshots" in plain(result.output)
