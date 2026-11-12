"""`nlead` command line: every A.12.6 command exists, has help, and fails clearly when it cannot run."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from nument_engine import db
from nument_engine.cli import app, hoist_global_options

from .cli_text import plain

runner = CliRunner()


TOP_LEVEL = [
    "universe",
    "signals",
    "prefilter",
    "research",
    "extract",
    "verify",
    "score",
    "judge",
    "message",
    "sheet",
    "learn",
    "report",
    "audit",
    "eval",
    "health",
    "backup",
    "migrate-legacy",
    "run",
    "db",
]
EVERY_COMMAND = [
    ["universe"],
    ["signals"],
    ["prefilter"],
    ["research"],
    ["extract", "submit"],
    ["extract", "collect"],
    ["verify"],
    ["score"],
    ["judge"],
    ["message"],
    ["sheet", "push"],
    ["sheet", "pull"],
    ["sheet", "sync"],
    ["learn"],
    ["report", "weekly"],
    ["audit"],
    ["eval"],
    ["health"],
    ["backup"],
    ["migrate-legacy"],
    ["run", "night"],
    ["run", "morning"],
    ["run", "sheet"],
    ["run", "weekly"],
    ["run", "monthly"],
    ["db", "migrate"],
    ["db", "status"],
    ["db", "sync-segments"],
]


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = plain(result.stdout)
    for name in TOP_LEVEL:
        assert name in out
    for flag in ("--env", "--segment", "--limit", "--dry-run", "--max-spend-inr"):
        assert flag in out


def test_run_help_lists_every_orchestrated_run() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    out = plain(result.stdout)
    for name in ("night", "morning", "sheet", "weekly", "monthly"):
        assert name in out


@pytest.mark.parametrize("command", EVERY_COMMAND, ids=" ".join)
def test_every_command_has_help_without_any_configuration(command: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    result = runner.invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage" in plain(result.stdout)


def test_dev_refuses_live_sheet_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from nument_engine.settings import Settings

    with pytest.raises(ValidationError):
        Settings(app_env="dev", database_url="postgresql://x", sheet_master_id="LIVE")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--env", "staging", "signals"], "staging"),
        (["--segment", "Clinics India", "signals"], "not a segment id"),
        (["--limit", "0", "signals"], "--limit"),
        (["--max-spend-inr", "-5", "signals"], "--max-spend-inr"),
    ],
)
def test_bad_global_flags_are_rejected(args: list[str], message: str) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert message in plain(result.output)


def test_configuration_errors_are_clear_and_never_echo_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("SHEET_MASTER_ID", "secret-sheet-id-123")
    result = runner.invoke(app, ["signals"])
    assert result.exit_code == 2
    out = plain(result.output)
    assert "Configuration error for APP_ENV=dev" in out
    assert "database_url" in out
    assert "secret-sheet-id-123" not in result.output


def test_unreachable_database_is_reported_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "POOL_TIMEOUT_S", 1.0)
    result = runner.invoke(app, ["signals"])
    assert result.exit_code == 1
    assert "cannot reach the database" in plain(result.output)
    assert "nlead-test-guard" not in result.output  # the connection string is never printed


def test_unbuilt_stage_says_so_and_records_a_failed_run(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import nument_engine.pipeline.universe as stage

    def unbuilt(rc: object, monthly: bool = False) -> None:
        raise NotImplementedError("Built in Step 6")

    monkeypatch.setattr(stage, "run", unbuilt)  # the real stage exists now and would go to the network
    result = runner.invoke(app, ["--segment", "clinics-in", "--limit", "5", "universe", "--monthly"])
    assert result.exit_code == 2
    assert "not built yet (Built in Step 6)" in result.output
    row = db.fetch_one("select kind, status, error, stats from public.runs order by started_at desc limit 1")
    assert row is not None
    assert (row["kind"], row["status"]) == ("manual", "failed")
    assert "NotImplementedError" in row["error"]
    assert row["stats"]["segments"] == ["clinics-in"] and row["stats"]["limit"] == 5


def test_eval_finds_the_evals_package(
    engine_db: str, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    import evals.run_eval

    monkeypatch.setattr(evals.run_eval, "GOLDEN_DIR", tmp_path_factory.mktemp("no-golden-set"))
    result = runner.invoke(app, ["eval", "--subset", "10"])
    assert result.exit_code == 2
    assert "golden set" in result.output and "no labels yet" in result.output


def test_orchestrated_runs_record_their_kind(engine_db: str) -> None:
    """The night run starts with the essential health phase: a FAIL (no Gemini key here) stops it, exit 1."""
    result = runner.invoke(app, ["run", "night"])
    assert result.exit_code == 1 and "essential phase 'health' failed" in plain(result.output)
    row = db.fetch_one("select kind, status, stats, error from public.runs order by started_at desc limit 1")
    assert row is not None and (row["kind"], row["status"]) == ("night", "failed")
    assert "HealthCheckFailed" in row["stats"]["phases"]["health"]["error"] and "GEMINI_API_KEY" in row["error"]


def test_a_healthy_night_run_runs_every_phase(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """All night stages exist now. The ones that go to the internet are stubbed; the pre-filter runs for real."""
    from nument_engine.pipeline import extract, research, signals, universe

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    for module, name in ((universe, "run"), (signals, "run"), (research, "run"), (extract, "submit")):
        monkeypatch.setattr(module, name, lambda rc, _n=name, **kw: {"stubbed": _n})
    result = runner.invoke(app, ["run", "night"])
    assert result.exit_code == 0, plain(result.output)
    phases = db.scalar("select stats -> 'phases' from public.runs order by started_at desc limit 1")
    assert phases["health"]["status"] in ("ok", "info", "warn", "alert")
    assert phases["universe"]["stubbed"] == "run" and phases["extract_submit"]["stubbed"] == "submit"
    assert "queued" in phases["prefilter"] and "slots" in phases["prefilter"]


def test_db_commands(engine_db: str) -> None:
    status = runner.invoke(app, ["db", "status"])
    assert status.exit_code == 0 and "applied  0001_core.sql" in status.stdout and "pending" not in status.stdout
    migrate = runner.invoke(app, ["--dry-run", "db", "migrate"])
    assert migrate.exit_code == 0 and "Database is up to date." in migrate.stdout
    dry = runner.invoke(app, ["--dry-run", "db", "sync-segments"])
    assert dry.exit_code == 0 and "dry run, nothing written" in dry.stdout
    synced = runner.invoke(app, ["db", "sync-segments"])
    assert synced.exit_code == 0 and "Synced 6 segments" in synced.stdout
    assert db.scalar("select count(*) from public.segments where config_version is not null") == 6


def test_global_flags_work_after_the_command_too(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The plan and the workflows call `nlead run monthly --env prod --segment X`; both positions must work."""
    import nument_engine.pipeline.universe as stage

    monkeypatch.setattr(stage, "run", lambda rc, monthly=False: rc.stats.update(universe={"stub": True}))
    result = runner.invoke(app, ["universe", "--segment", "clinics-ae", "--limit=7", "--dry-run", "--env", "dev"])
    assert result.exit_code == 0, result.output
    row = db.fetch_one("select stats from public.runs order by started_at desc limit 1")
    assert row is not None
    assert (row["stats"]["segments"], row["stats"]["limit"], row["stats"]["dry_run"]) == (["clinics-ae"], 7, True)


def test_hoist_global_options() -> None:
    assert hoist_global_options(["run", "monthly", "--env", "prod", "--segment", "clinics-in"]) == [
        "--env", "prod", "--segment", "clinics-in", "run", "monthly",
    ]  # fmt: skip
    assert hoist_global_options(["--env", "dev", "universe", "--monthly"]) == ["--env", "dev", "universe", "--monthly"]
    assert hoist_global_options(["eval", "--subset", "5", "--dry-run"]) == ["--dry-run", "eval", "--subset", "5"]
    assert hoist_global_options(["health", "--", "--env", "x"]) == ["health", "--", "--env", "x"]
    assert hoist_global_options(["signals", "--limit"]) == ["signals", "--limit"]  # missing value: Click reports it
