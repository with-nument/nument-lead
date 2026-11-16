"""The startup backlog (lane E1a): each source's backlog pass with the 60-day window, the per-source cap, the
deadline and budget stops, and signals written source by source."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from nument_engine import db
from nument_engine.pipeline import backlog as bk
from nument_engine.pipeline import runs
from nument_engine.segments import load_segments, sync_segments_to_db
from nument_engine.sources.base import Signal
from nument_engine.sources.rss import Pass

from .sources_helpers import clean_db, no_network, run_context

__all__ = ["clean_db", "no_network"]


def launch(name: str, days_ago: float = 2) -> Signal:
    return Signal(
        type="launch",
        source="startup_lists",
        observed_at=datetime.now(UTC) - timedelta(days=days_ago),
        url=f"https://www.ycombinator.com/companies/{name.lower()}",
        quote=f"{name} builds things",
        evidence_key=f"yc:{name}",
        business_hint={"name": name},
        segment_id="firms-us",
    )


class Fake:
    """A source module with a backlog pass that records its Pass and adds the given signals."""

    def __init__(self, *sigs: Signal, error: Exception | None = None) -> None:
        self.passes: list[Pass] = []
        self.sigs = sigs
        self.error = error

    async def backlog(self, ctx: Any, segments: Any, sink: Any, run: Pass) -> None:
        self.passes.append(run)
        for sig in self.sigs:
            sink.add(sig, segments[sig.segment_id])
        if self.error:
            raise self.error


@pytest.fixture
def world(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    with db.tx() as conn:
        sync_segments_to_db(conn, load_segments())
    modules: dict[str, Any] = {name: SimpleNamespace() for name in bk.SOURCES}  # no backlog pass by default
    monkeypatch.setattr(bk, "load", lambda name: modules[name])
    return modules


def test_the_backlog_phase_is_registered() -> None:
    assert [p.name for p in runs.backlog_phases()] == ["backlog"]
    assert runs.backlog_phases()[0].budget == "low_priority_research" and runs.DEADLINE_MIN["backlog"] == 280


def test_each_source_gets_a_60_day_backlog_pass_and_signals_are_stored(world: dict[str, Any]) -> None:
    db.set_setting("backlog.items_per_source", 300)
    lists = Fake(launch("Tidepool"), launch("Lumen"))
    feeds = Fake()
    world["startup_lists"], world["funding_rss"] = lists, feeds
    rc = run_context(segments=["firms-us", "firms-gb"])
    rc.deadline = datetime.now(UTC) + timedelta(minutes=280)
    stats = bk.run(rc)

    run = feeds.passes[0]
    assert run.days == 60 and run.cap == 300 and run.backlog is True
    assert run.stop_at is not None and run.stop_at - time.monotonic() == pytest.approx(
        280 * 60 - bk.WRITE_MARGIN_S, abs=30
    )
    assert stats["sources"]["startup_lists"]["by_segment"]["firms-us"]["launch"] == 2
    assert stats["sources"]["sec_edgar"] == {"skipped": "no backlog pass"}
    names = {
        r["name"]
        for r in db.fetch_all("select b.name from public.signals s join public.businesses b on b.id = s.business_id")
    }
    assert names == {"Tidepool", "Lumen"} and rc.stats["backlog"] is stats


def test_one_failing_source_keeps_what_it_found_and_the_others_run(world: dict[str, Any]) -> None:
    world["funding_rss"] = Fake(launch("Halfway"), error=RuntimeError("feed parser crashed"))
    world["startup_lists"] = Fake(launch("After"))
    stats = bk.run(run_context(segments=["firms-us"]))
    assert stats["sources"]["funding_rss"]["error"] == "RuntimeError: feed parser crashed"
    assert stats["errors.funding_rss"] == 1
    names = {r["name"] for r in db.fetch_all("select name from public.businesses where segment_id = 'firms-us'")}
    assert names == {"Halfway", "After"}
    row = db.fetch_one("select last_error from public.source_health where source = 'funding_rss'")
    assert row is not None and "feed parser crashed" in row["last_error"]


def test_deadline_budget_switches_and_dry_run_limits(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("funding_rss", "hn_launches"):
        world[name] = Fake()
    rc = run_context(segments=["firms-us"])
    rc.deadline = datetime.now(UTC) + timedelta(seconds=10)  # inside the writing margin already
    stats = bk.run(rc)
    assert all(v == {"skipped": "deadline"} for v in stats["sources"].values())
    assert world["funding_rss"].passes == []

    db.set_setting("sources_enabled", {"funding_rss": False})
    stats = bk.run(run_context(segments=["firms-us"], limit=5))
    assert stats["sources"]["funding_rss"]["skipped"].startswith("switched off")
    assert world["hn_launches"].passes[0].cap == 5  # --limit (and dry runs) cap every source

    from nument_engine.budget import Budget

    monkeypatch.setattr(Budget, "allow_phase", lambda self, phase: phase != "low_priority_research")
    stats = bk.run(run_context(segments=["firms-us"]))
    assert all(v == {"skipped": "budget"} for v in stats["sources"].values())


def test_the_real_sources_have_backlog_passes() -> None:
    for name in ("funding_rss", "hn_launches", "betalist", "startup_lists"):
        assert callable(getattr(bk.load(name), "backlog", None)), name
