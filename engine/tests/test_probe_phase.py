"""The night `probes` phase (E2a, 15 Nov 2026): which startups are probed, the contract 4.2 facts it writes, the
per-probe schedule in `extra.probes`, failures that write nothing, the per-run cap and the time stop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.pipeline import probe
from nument_engine.research import probes as pr
from nument_engine.segments import load_segments, sync_segments_to_db

from .sources_helpers import clean_db, insert_business, no_network, run_context

__all__ = ["clean_db", "no_network"]

NOW = datetime(2026, 11, 16, 2, 0, tzinfo=UTC)

ANSWERS: dict[str, pr.Outcome] = {
    "domain_created": pr.ok({"date": "2024-03-01", "registrar": "SafeNames Ltd."}, "https://rdap.example/d", "q1"),
    "first_cert": pr.Outcome("robots", reason="disallowed by robots.txt"),
    "first_capture": pr.ok({"date": "2024-03-05"}, "https://web.archive.org/cdx/search/cdx?url=x", "q3"),
    "dns": pr.ok({"mx_provider": "google", "txt_hints": ["stripe"]}, "dns:tally-nlead.io", "q4"),
    "github": pr.none("no GitHub organisation of this startup"),
    "app_links": pr.error("malformed JSON from tally-nlead.io"),
    "app_store": pr.ok(
        {
            "name": "Tally",
            "seller": "Tally Ltd",
            "url": "https://apps.apple.com/in/app/tally/id1",
            "released": "2025-01-01",
        },
        "https://itunes.apple.com/search?term=Tally",
        "q7",
    ),
}


class FakeProbes:
    """Answers every due probe from `answers`, after `delay` seconds each startup."""

    def __init__(self, answers: dict[str, pr.Outcome] | None = None, delay: float = 0.0) -> None:
        self.answers = answers or ANSWERS
        self.delay = delay
        self.calls: list[tuple[str, set[str]]] = []
        self.requests = 0

    async def __aenter__(self) -> FakeProbes:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def probe(self, target: pr.Target, due: set[str], time_left: Callable[[], float]) -> dict[str, pr.Outcome]:
        self.calls.append((target.business_id, set(due)))
        if self.delay:
            try:
                await asyncio.wait_for(asyncio.sleep(self.delay), timeout=max(time_left(), 0.0))
            except TimeoutError:
                return {}
        return {name: self.answers[name] for name in due if name in self.answers}


@pytest.fixture
def firms(clean_db: str) -> str:
    with db.tx() as conn:
        sync_segments_to_db(conn, {k: v for k, v in load_segments().items() if k in ("firms-in", "firms-us")})
    return clean_db


def startup(name: str, *, crawled_days_ago: float = 0.5, probes_state: dict[str, Any] | None = None, **kw: Any) -> str:
    domain = f"{name.lower().replace(' ', '')}-nlead.io"
    extra: dict[str, Any] = {"crawl": {"at": (datetime.now(UTC) - timedelta(days=crawled_days_ago)).isoformat(),
                                       "final_url": f"https://{domain}/"}}  # fmt: skip
    if probes_state is not None:
        extra["probes"] = probes_state
    values = {
        "name": name,
        "segment_id": "firms-in",
        "website": f"https://{domain}/",
        "web_domain": domain,
        "status": "queued",
        "extra": extra,
        **kw,
    }
    return insert_business(**values)


def run(
    fake: FakeProbes | None = None, *, budget_s: float | None = None, **ctx: Any
) -> tuple[dict[str, Any], FakeProbes]:
    fake = fake or FakeProbes()
    rc = run_context(segments=["firms-in", "firms-us", "clinics-in"], **ctx)
    stats = probe.run(rc, make_probes=lambda: fake, budget_s=budget_s)  # type: ignore[arg-type,return-value]
    return stats, fake


# ---- the schedule (pure) ---------------------------------------------------------------------------------


def test_due_probes_and_next_at() -> None:
    assert probe.due_probes({}, NOW) == set(pr.PROBES)
    state = {
        "domain_created": {"at": (NOW - timedelta(days=31)).isoformat(), "state": "ok"},
        "first_cert": {"at": (NOW - timedelta(days=3)).isoformat(), "state": "robots"},
        "first_capture": {"at": (NOW - timedelta(days=3)).isoformat(), "state": "none"},
        "dns": {"at": (NOW - timedelta(hours=21)).isoformat(), "state": "error"},
        "github": {"at": (NOW - timedelta(hours=2)).isoformat(), "state": "skipped"},
        "app_links": {"at": (NOW - timedelta(days=1)).isoformat(), "state": "ok"},
        "app_store": {"at": (NOW - timedelta(days=1)).isoformat(), "state": "ok"},
    }
    assert probe.due_probes(state, NOW) == {"domain_created", "dns"}
    later = {k: v for k, v in state.items() if k not in ("domain_created", "dns")}
    later.update({n: {"at": NOW.isoformat(), "state": "ok"} for n in ("domain_created", "dns")})
    assert probe.next_at(later, NOW) == NOW - timedelta(hours=2) + probe.RETRY_AFTER  # the skipped GitHub probe


def test_record_keeps_every_probes_last_run() -> None:
    state = probe.record({}, ANSWERS, NOW)
    assert state["domain_created"] == {"at": NOW.isoformat(), "state": "ok"}
    assert state["app_links"]["state"] == "error" and "malformed" in state["app_links"]["reason"]
    assert state["next_at"] == (NOW + probe.RETRY_AFTER).isoformat()  # the failed app links, next night
    partial = probe.record({}, {"dns": ANSWERS["dns"]}, NOW)
    assert partial["next_at"] == NOW.isoformat()  # probes that never ran are due at once


# ---- the phase -----------------------------------------------------------------------------------------------


def test_the_phase_writes_the_contract_facts(firms: str) -> None:
    bid = startup("Tally")
    stats, fake = run()
    assert stats["selected"] == 1 and stats["probed"] == 1 and stats["facts"] == 4
    assert stats["probes.app_links.error"] == 1 and stats["probes.first_cert.robots"] == 1
    assert fake.calls == [(bid, set(pr.PROBES))]
    rows = db.fetch_all(
        "select field, value, quote, url, model, verified, verify_score, verified_at from public.facts "
        "where business_id = %s order by field",
        [bid],
    )
    assert [r["field"] for r in rows] == ["probe.app_store", "probe.dns", "probe.domain_created", "probe.first_capture"]
    by_field = {r["field"]: r for r in rows}
    assert by_field["probe.domain_created"]["value"] == {"date": "2024-03-01", "registrar": "SafeNames Ltd."}
    assert by_field["probe.dns"]["url"] == "dns:tally-nlead.io" and by_field["probe.dns"]["quote"] == "q4"
    assert all(r["model"] == "rule" and r["verified"] and r["verified_at"] is not None for r in rows)
    extra = db.scalar("select extra from public.businesses where id = %s", [bid])
    assert extra["probes"]["github"]["state"] == "none" and extra["probes"]["dns"]["state"] == "ok"
    assert datetime.fromisoformat(extra["probes"]["next_at"]) > datetime.now(UTC) + timedelta(hours=19)
    again, fake2 = run()
    assert again["selected"] == 0 and fake2.calls == []  # nothing is due before the failed probe's retry


def test_reprobing_replaces_facts_and_a_none_removes_the_old_one(firms: str) -> None:
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    state = {name: {"at": old, "state": "ok"} for name in pr.PROBES} | {"next_at": old}
    bid = startup("Tally", probes_state=state)
    for field in ("probe.dns", "probe.github", "probe.app_links"):
        db.execute(
            "insert into public.facts (business_id, field, value, quote, url, model, verified, verified_at) "
            "values (%s, %s, '{\"old\": true}', 'old', 'https://old.example', 'rule', true, now())",
            [bid, field],
        )
    run()
    facts = {
        r["field"]: r["value"]
        for r in db.fetch_all("select field, value from public.facts where business_id = %s", [bid])
    }
    assert facts["probe.dns"] == {"mx_provider": "google", "txt_hints": ["stripe"]}  # replaced, one row
    assert "probe.github" not in facts  # GitHub answered "no organisation": the old row goes
    assert facts["probe.app_links"] == {"old": True}  # the probe failed: the old row stays
    assert db.scalar("select count(*) from public.facts where business_id = %s and field = 'probe.dns'", [bid]) == 1


def test_which_startups_are_probed(firms: str) -> None:
    fresh = startup("Fresh One", queue_priority=10)
    due_again = startup(
        "Due Again",
        queue_priority=90,
        probes_state={"next_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    )
    startup("Probed Lately", probes_state={"next_at": (datetime.now(UTC) + timedelta(days=20)).isoformat()})
    startup("Crawled Long Ago", crawled_days_ago=10)
    startup("Rejected One", status="rejected")
    startup("No Site", website=None, web_domain=None)
    insert_business(
        name="A Clinic",
        segment_id="clinics-in",
        website="https://aclinic-nlead.in/",
        web_domain="aclinic-nlead.in",
        extra={"crawl": {"at": datetime.now(UTC).isoformat()}},
    )
    stats, fake = run()
    assert stats["selected"] == 2
    assert [bid for bid, _ in fake.calls] == [fresh, due_again]  # never probed first, then by priority


def test_the_per_run_cap_is_a_setting(firms: str) -> None:
    for i in range(3):
        startup(f"Capped {i}")
    db.set_setting("probes.per_run", 2)
    stats, _ = run()
    assert stats["selected"] == 2


def test_the_phase_stops_at_its_time_budget(firms: str) -> None:
    for i in range(3):
        startup(f"Slow {i}")
    stats, fake = run(FakeProbes(delay=5.0), budget_s=0.3)
    assert stats.get("probed", 0) == 0 and stats["time_skipped"] == 3
    states = db.fetch_all("select extra from public.businesses where name like 'Slow %%'")
    assert all("probes" not in s["extra"] for s in states)  # nothing recorded: all due again next night
    stats, fake = run(FakeProbes(), budget_s=0.0)
    assert fake.calls == [] and stats["time_skipped"] == 3


def test_a_dry_run_writes_nothing(firms: str) -> None:
    bid = startup("Dry")
    stats, _ = run(dry_run=True)
    assert stats["probed"] == 1 and stats["facts"] == 0
    assert db.scalar("select count(*) from public.facts where business_id = %s", [bid]) == 0
    assert "probes" not in db.scalar("select extra from public.businesses where id = %s", [bid])


def test_without_startup_segments_the_phase_does_nothing(firms: str) -> None:
    rc = run_context(segments=["clinics-in"])
    assert probe.run(rc, make_probes=FakeProbes) == {"skipped": "no startup segment is on"}  # type: ignore[arg-type]
