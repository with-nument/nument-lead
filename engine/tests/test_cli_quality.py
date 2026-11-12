"""Command line for the learning loop, the report, the audit, the eval and health: options and exit codes."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.cli import app

from .cli_text import plain

runner = CliRunner()


def test_report_weekly_dry_run_prints_without_storing(engine_db: str) -> None:
    before = db.scalar("select count(*) from public.reports where kind = 'weekly'")
    result = runner.invoke(app, ["report", "weekly", "--dry-run", "--week-start", "2026-12-07"])
    assert result.exit_code == 0, result.output
    assert "# Weekly report: 7 to 13 Dec 2026" in plain(result.output)
    assert db.scalar("select count(*) from public.reports where kind = 'weekly'") == before
    bad = runner.invoke(app, ["report", "weekly", "--week-start", "2026-12-08"])
    assert bad.exit_code == 2 and "not a Monday" in bad.output


def test_learn_dry_run_and_rollback_errors(engine_db: str) -> None:
    result = runner.invoke(app, ["learn", "--dry-run", "--segment", "education-ae"])
    assert result.exit_code == 0, result.output
    assert "Re-weighting: no_change, 0 change(s)." in plain(result.output)
    missing = runner.invoke(app, ["learn", "--rollback", "999"])
    assert missing.exit_code == 1 and "weight version 999 does not exist" in missing.output


def test_audit_dry_run_with_nothing_to_audit(engine_db: str) -> None:
    result = runner.invoke(app, ["audit", "--dry-run", "--segment", "education-ae"])
    assert result.exit_code == 0, result.output
    assert "# Weekly audit" in plain(result.output)


def _golden(tmp_path: Path, passed: bool) -> Path:
    outcomes, labels = [], []
    for i in range(20):
        good = i < 10
        business_id = str(uuid.UUID(int=5000 + i))
        labels.append(
            {
                "business_id": business_id,
                "segment": "clinics-in",
                "label": "good" if good else "bad",
                "reasons": [],
                "labeled_at": date(2026, 12, 1).isoformat(),
            }
        )
        grade = ("A" if good else "D") if passed else "B"
        outcomes.append(
            {"business_id": business_id, "segment": "clinics-in", "total": 90 - i, "grade": grade, "facts": []}
        )
    (tmp_path / "labels.jsonl").write_text("".join(json.dumps(x) + "\n" for x in labels))
    replay = tmp_path / "outcomes.jsonl"
    replay.write_text("".join(json.dumps(x) + "\n" for x in outcomes))
    return replay


@pytest.mark.parametrize(("passed", "code"), [(True, 0), (False, 1)])
def test_eval_exit_codes(
    engine_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passed: bool, code: int
) -> None:
    import evals.run_eval

    monkeypatch.setattr(evals.run_eval, "GOLDEN_DIR", tmp_path)
    replay = _golden(tmp_path, passed)
    result = runner.invoke(app, ["eval", "--subset", "20", "--replay", str(replay)])
    assert result.exit_code == code, result.output
    assert ("PASSED" if passed else "eval failed") in plain(result.output)


def test_eval_skipped_for_budget_exits_3(engine_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import evals.run_eval

    monkeypatch.setattr(evals.run_eval, "GOLDEN_DIR", tmp_path)
    monkeypatch.setattr(evals.run_eval, "budget_check", lambda n: (False, "over the cap"))
    _golden(tmp_path, True)
    result = runner.invoke(app, ["eval", "--subset", "20"])
    assert result.exit_code == 3 and "eval skipped: budget (over the cap)" in plain(result.output)


def test_health_exit_codes_and_summary(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    failing = runner.invoke(app, ["health"])  # no GEMINI_API_KEY in tests: Gemini cannot run
    assert failing.exit_code == 1 and "FAIL" in failing.output and "GEMINI_API_KEY is not set" in failing.output
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    settings_module.get_settings.cache_clear()
    healthy = runner.invoke(app, ["health"])
    assert healthy.exit_code == 0, healthy.output
    assert healthy.output.splitlines()[0].startswith("check")
    summary = runner.invoke(app, ["health", "--summary"])
    assert summary.exit_code == 0 and summary.output.startswith("### Nument Leads health")


def test_health_prune_dry_run_records_a_run(engine_db: str) -> None:
    result = runner.invoke(app, ["health", "--prune", "--dry-run"])
    assert result.exit_code == 0, result.output
    stats = db.scalar("select stats -> 'prune' from public.runs order by started_at desc limit 1")
    assert stats["dry_run"] is True and "places_content" in stats


def test_new_options_have_help() -> None:
    for command, flag in (
        (["learn"], "--rollback"),
        (["report", "weekly"], "--week-start"),
        (["eval"], "--export-golden"),
        (["eval"], "--replay"),
        (["health"], "--prune"),
        (["health"], "--summary"),
        (["health"], "--notify"),
    ):
        result = runner.invoke(app, [*command, "--help"])
        assert result.exit_code == 0 and flag in plain(result.output), (command, flag)
