"""Run bookkeeping: every run leaves one `runs` row with the right status."""

from __future__ import annotations

import pytest

from nument_engine import db
from nument_engine.pipeline.runs import Options, run_context


def _run(run_id: str) -> dict[str, object]:
    row = db.fetch_one("select kind, status, stats, error, finished_at from public.runs where id = %s", [run_id])
    assert row is not None
    return row


def test_ok_run(engine_db: str) -> None:
    opts = Options(segments=["clinics-in"], limit=5, dry_run=True, max_spend_inr=10)
    with run_context("manual", opts) as rc:
        rc.add("businesses")
        rc.add("businesses", 2)
    row = _run(rc.run_id)
    assert row["kind"] == "manual" and row["status"] == "ok" and row["finished_at"] is not None
    assert row["stats"] == {
        "businesses": 3,
        "failed_stages": [],
        "skipped_stages": [],
        "dry_run": True,
        "limit": 5,
        "segments": ["clinics-in"],
        "max_spend_inr": 10,
    }


def test_partial_run(engine_db: str) -> None:
    with run_context("night", Options()) as rc:
        rc.failed_stages.append("signals")
    assert _run(rc.run_id)["status"] == "partial"


def test_failed_run_keeps_the_error(engine_db: str) -> None:
    with pytest.raises(ZeroDivisionError), run_context("morning", Options()) as rc:
        rc.add("before_crash")
        _ = 1 / 0
    row = _run(rc.run_id)
    assert row["status"] == "failed"
    assert "ZeroDivisionError" in str(row["error"])
    assert row["stats"]["before_crash"] == 1  # type: ignore[index]


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown run kind"), run_context("hourly", Options()):
        pass
