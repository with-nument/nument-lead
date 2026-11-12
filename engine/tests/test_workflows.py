"""GitHub Actions workflows (Step 14.5): schedules, inputs, safety rules and the minutes budget."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from nument_engine.settings import REPO_DIR

WORKFLOWS = REPO_DIR / ".github" / "workflows"
ACTIONS = REPO_DIR / ".github" / "actions"
SCHEDULED = {
    "night.yml": ("30 20 * * *", 45),
    "morning.yml": ("30 0 * * *", 30),
    "sheet-sync.yml": ("30 3-15/2 * * *", 10),
    "weekly.yml": ("30 1 * * 1", 30),
    "monthly.yml": ("0 17 1 * *", 60),
    "backup.yml": ("30 17 * * 0", 15),
}
PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    if True in data:  # YAML 1.1 reads the key `on` as True
        data["on"] = data.pop(True)
    return data


def steps(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for job in data["jobs"].values() for s in job.get("steps", [])]


@pytest.mark.parametrize(("name", "expected"), SCHEDULED.items())
def test_schedule_timeout_and_gate(name: str, expected: tuple[str, int]) -> None:
    cron, timeout = expected
    data = load(WORKFLOWS / name)
    assert data["on"]["schedule"] == [{"cron": cron}]
    assert "workflow_dispatch" in data["on"]
    assert data["permissions"] == {"contents": "read"}
    for job in data["jobs"].values():
        assert job["timeout-minutes"] == timeout
        # schedules stay off until go-live (Step 21); manual runs always work
        assert job["if"] == "github.event_name == 'workflow_dispatch' || vars.SCHEDULES_ENABLED == 'true'"
        assert job["permissions"] == {"contents": "read", "issues": "write"}  # issues: the failure report
    assert data["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("name", ["night.yml", "morning.yml", "sheet-sync.yml"])
def test_the_apps_run_now_inputs_are_accepted(name: str) -> None:
    """The Engine page dispatches with dry_run, limit and segment (Step 15.6.8); GitHub rejects unknown inputs."""
    inputs = load(WORKFLOWS / name)["on"]["workflow_dispatch"]["inputs"]
    assert {"dry_run", "limit", "segment", "env"} <= set(inputs)
    assert inputs["env"]["default"] == "prod" and inputs["dry_run"]["type"] == "boolean"


@pytest.mark.parametrize(
    "path",
    [*sorted(WORKFLOWS.glob("*.yml")), *sorted(ACTIONS.glob("*/action.yml"))],
    ids=lambda p: p.name if p.name != "action.yml" else p.parent.name,
)
def test_no_expression_is_pasted_into_a_script(path: Path) -> None:
    """Inputs and secrets reach scripts through env only (script injection, 14.5.1)."""
    data = load(path)
    all_steps = steps(data) if "jobs" in data else data["runs"]["steps"]
    for step in all_steps:
        assert "${{" not in step.get("run", ""), f"{path.name}: {step.get('name')}"


@pytest.mark.parametrize(
    "path",
    [*(WORKFLOWS / name for name in SCHEDULED), *sorted(ACTIONS.glob("*/action.yml"))],
    ids=lambda p: p.name if p.name != "action.yml" else p.parent.name,
)
def test_third_party_actions_are_pinned_to_a_commit(path: Path) -> None:
    """The scheduled runs hold every production secret: their actions are pinned to a commit (dependabot bumps them)."""
    data = load(path)
    all_steps = steps(data) if "jobs" in data else data["runs"]["steps"]
    for step in all_steps:
        uses = step.get("uses", "")
        if uses and not uses.startswith("./"):
            assert PINNED.match(uses), uses


def test_secrets_are_never_echoed() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        for step in steps(load(path)):
            run = step.get("run", "")
            assert not re.search(r"echo\s+\"?\$(DATABASE_URL|GEMINI|OPENAI|GOOGLE|SUPABASE_SERVICE|BACKUP)", run), (
                path.name
            )


def test_every_engine_job_uses_the_shared_setup() -> None:
    for name in SCHEDULED:
        uses = [s.get("uses") for s in steps(load(WORKFLOWS / name))]
        assert "./.github/actions/setup-engine" in uses, name
    night = [s for s in steps(load(WORKFLOWS / "night.yml")) if s.get("uses") == "./.github/actions/setup-engine"]
    assert night[0]["with"] == {"playwright": "true"}  # only the night run crawls


def test_failure_is_reported_on_scheduled_runs() -> None:
    for name in SCHEDULED:
        notify = [s for s in steps(load(WORKFLOWS / name)) if s.get("uses") == "./.github/actions/notify-failure"]
        assert len(notify) == 1 and notify[0]["if"] == "failure() && github.event_name == 'schedule'", name


def test_monthly_minutes_stay_under_the_free_allowance() -> None:
    """14.6: billed minutes a month at the expected run lengths (each job rounds up to a whole minute)."""
    runs_a_month = {
        "night.yml": 30,
        "morning.yml": 30,
        "sheet-sync.yml": 30 * 7,
        "weekly.yml": 4.3,
        "monthly.yml": 1,
        "backup.yml": 4.3,
    }
    minutes_a_run = {
        "night.yml": 31,  # 27, plus at most 4 minutes of Google Maps lookups (maps_reviews.minutes_per_run)
        "morning.yml": 12,
        "sheet-sync.yml": 2,
        "weekly.yml": 8,
        "monthly.yml": 35,
        "backup.yml": 3,
    }
    ci = 160  # Step 17, about 40 pushes
    total = sum(runs_a_month[k] * minutes_a_run[k] for k in runs_a_month) + ci
    assert total < 2000, total
    sheet_cron = load(WORKFLOWS / "sheet-sync.yml")["on"]["schedule"][0]["cron"]
    hours = range(3, 16, 2)
    assert sheet_cron == "30 3-15/2 * * *" and len(hours) == 7
