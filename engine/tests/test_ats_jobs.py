"""Public job boards (lane E1b, 15 Nov 2026): a startup's own Greenhouse, Lever, Ashby or Workable board, found by
slug and checked against the board's own API; founding-engineer and CTO roles become hiring_builder signals.
Fixtures are trimmed from real responses of the four public APIs (tests/fixtures/e1b)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nument_engine import db
from nument_engine.segments import load_segments, sync_segments_to_db
from nument_engine.sources import ats_jobs as ats
from nument_engine.sources.ats_jobs import AtsJobsAdapter, Board, Job

from .sources_helpers import clean_db, ctx, insert_business, mock_transport, no_network

__all__ = ["clean_db", "no_network"]

FIX = Path(__file__).resolve().parent / "fixtures" / "e1b"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
SEGMENTS = load_segments()


def data(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AtsJobsAdapter, "min_gap_s", 0.0)


# ---- pure helpers ----------------------------------------------------------------------------------------


def test_slugs_come_from_the_domain_and_the_name() -> None:
    assert ats.slugs_for("Brightcart, Inc.", "brightcart.io") == ["brightcart"]
    assert ats.slugs_for("Lithe Medical, Inc.", "getlithe.com") == ["getlithe", "lithe", "lithemedical"]
    assert ats.slugs_for("Care Nimble", "carenimble.com") == ["carenimble", "care-nimble"]


@pytest.mark.parametrize(
    ("title", "founding", "software"),
    [
        ("Founding Full-Stack Engineer", True, True),
        ("Founding Engineer (AI)", True, True),
        ("Our first engineering hire", True, True),
        ("CTO & Co-founder", True, True),
        ("Technical Co-founder", True, False),
        ("Chief Technology Officer", True, False),
        ("Senior Backend Engineer", False, True),
        ("Founding Account Executive", False, False),
        ("Founding Solutions Engineer", False, False),  # customer-facing, not a builder
        ("Mechanical Engineer", False, False),
    ],
)
def test_roles(title: str, founding: bool, software: bool) -> None:
    assert ats.is_founding_role(title) is founding
    assert ats.is_software_role(title) is software


def test_each_board_api_is_parsed() -> None:
    gh = ats.parse_greenhouse("brightcart", data("ats_greenhouse.json"))
    assert (
        gh is not None and gh.name == "Brightcart" and [j.title for j in gh.jobs][0] == "Founding Full-Stack Engineer"
    )
    assert gh.jobs[0].url == "https://job-boards.greenhouse.io/brightcart/jobs/6231864004"
    assert gh.jobs[0].posted == datetime(2026, 11, 6, 15, 22, 1, tzinfo=UTC)
    lever = ats.parse_lever("lithemedical", data("ats_lever.json"))
    assert lever is not None and lever.name is None and lever.jobs[0].title == "CTO & Co-founder"
    assert lever.jobs[0].posted == datetime(2025, 11, 11, 16, 0, tzinfo=UTC)
    ashby = ats.parse_ashby("orcosa", data("ats_ashby.json"))
    assert ashby is not None and [j.title for j in ashby.jobs] == ["Senior Backend Engineer"]  # unlisted dropped
    wk = ats.parse_workable("carenimble", data("ats_workable.json"))
    assert wk is not None and wk.name == "Care Nimble" and wk.jobs[0].id == "81B46579FE"
    for parse in ats.PARSERS.values():
        assert parse("x", {"error": "not found"}) is None or parse("x", {"error": "not found"}).jobs == []  # type: ignore[union-attr]
        assert parse("x", "garbage") is None


def test_a_board_must_be_the_companys_own() -> None:
    gh = ats.parse_greenhouse("brightcart", data("ats_greenhouse.json"))
    assert gh is not None and ats.board_is_theirs(gh, "Brightcart, Inc.", "brightcart.io")
    assert not ats.board_is_theirs(gh, "Bright Cartography Ltd", "brightcartography.com")
    lever = ats.parse_lever("lithemedical", data("ats_lever.json"))
    assert lever is not None and ats.board_is_theirs(lever, "Lithe Medical, Inc.", "lithemedical.com")
    assert not ats.board_is_theirs(lever, "Nova Robotics", "nova.ai")  # no name on Lever: the text must show it
    assert not ats.same_company("Nova Inc", "Innovations Hub")


def test_founding_roles_become_signals_and_too_many_roles_do_not() -> None:
    gh = ats.parse_greenhouse("brightcart", data("ats_greenhouse.json"))
    assert gh is not None
    sigs, verdict = ats.board_signals(gh, {"id": "b1", "segment_id": "firms-us"}, 10, NOW)
    assert verdict == "signal" and len(sigs) == 1
    sig = sigs[0]
    assert (sig.type, sig.source, sig.business_id, sig.segment_id) == ("hiring_builder", "ats_jobs", "b1", "firms-us")
    assert sig.quote == "Founding Full-Stack Engineer" and sig.evidence_key == "greenhouse:brightcart:6231864004"
    assert sig.details["engineering_roles"] == 1 and sig.details["open_roles"] == 2
    many = Board("greenhouse", "x", "X", [Job(str(i), "Founding Engineer", None, None) for i in range(11)])
    assert ats.board_signals(many, {"id": "b1"}, 10, NOW) == ([], "too_many_roles")
    ashby = ats.parse_ashby("orcosa", data("ats_ashby.json"))
    assert ashby is not None and ats.board_signals(ashby, {"id": "b1"}, 10, NOW) == ([], "no_founding_role")


# ---- the whole source --------------------------------------------------------------------------------------


GH = "https://boards-api.greenhouse.io/v1/boards/"
LEVER = "https://api.lever.co/v0/postings/"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/"
WORKABLE = "https://apply.workable.com/api/v1/widget/accounts/"


def board_routes(**extra: Any) -> dict[str, Any]:
    return {
        GH + "brightcart/jobs": (200, data("ats_greenhouse.json")),
        LEVER + "lithemedical": (200, data("ats_lever.json")),
        ASHBY + "orcosa": (200, data("ats_ashby.json")),
        WORKABLE + "carenimble": (200, data("ats_workable.json")),
        "https://apply.workable.com/robots.txt": (200, "User-agent: *\nDisallow: /admin\n"),
        "*": (404, '{"status": 404}'),
        **extra,
    }


def startups() -> dict[str, str]:
    with db.tx() as conn:
        sync_segments_to_db(conn, {"firms-us": SEGMENTS["firms-us"]})
    made = {}
    for name, domain in [("Brightcart, Inc.", "brightcart.io"), ("Lithe Medical, Inc.", "lithemedical.com"),
                         ("Orcosa Inc.", "orcosa.com"), ("Care Nimble, Inc.", "carenimble.com"),
                         ("Quiet Startup LLC", "quietstartup.com")]:  # fmt: skip
        made[name] = insert_business(
            name=name, segment_id="firms-us", country="us", city=None, website=f"https://{domain}/", web_domain=domain
        )
    return made


async def run(transport: Any, context: Any = None) -> tuple[list[Any], Any, AtsJobsAdapter]:
    context = context or ctx()
    async with AtsJobsAdapter(context, transport=transport) as a:
        a.clock = lambda: NOW
        sigs = await a.signals_for(SEGMENTS)
    return sigs, context, a


async def test_startups_boards_are_found_and_read(clean_db: str) -> None:
    ids = startups()
    transport, seen = mock_transport(board_routes())
    sigs, context, _ = await run(transport)
    by_business = {s.business_id: s for s in sigs}
    assert set(by_business) == {ids["Brightcart, Inc."], ids["Lithe Medical, Inc."], ids["Care Nimble, Inc."]}
    assert by_business[ids["Care Nimble, Inc."]].url == "https://apply.workable.com/j/81B46579FE"
    assert by_business[ids["Lithe Medical, Inc."]].details["board"] == "lever"
    assert context.stats["ats_jobs.no_founding_role"] == 1 and context.stats["ats_jobs.no_board"] == 1
    assert any(str(r.url).startswith("https://apply.workable.com/robots.txt") for r in seen)
    assert not any("boards-api.greenhouse.io/robots.txt" in str(r.url) for r in seen)  # an official API
    checks = db.scalar(
        "select count(*) from public.source_records where source = 'ats_jobs' and source_key like 'check:%'"
    )
    assert checks == 5
    transport2, seen2 = mock_transport(board_routes())
    again, _, _ = await run(transport2)
    assert again == [] and seen2 == []  # every business was checked in the last 14 days


async def test_the_daily_cap(clean_db: str) -> None:
    startups()
    db.set_setting("ats_jobs.companies_per_day", 2)
    transport, _ = mock_transport(board_routes())
    await run(transport)
    assert db.scalar("select count(*) from public.source_records where source = 'ats_jobs'") == 2
    transport, seen = mock_transport(board_routes())
    _, context, _ = await run(transport)
    assert context.stats["ats_jobs.daily_cap_reached"] == 1 and seen == []


async def test_a_block_pauses_the_source_and_keeps_what_was_found(clean_db: str) -> None:
    startups()
    transport, _ = mock_transport(board_routes(**{LEVER + "orcosa": (429, "slow down")}))
    sigs, context, adapter = await run(transport)
    assert adapter.blocked and context.alerts
    assert len(sigs) >= 1  # Care Nimble and Lithe come before Orcosa (newest first)
    row = db.fetch_one("select blocked_until from public.source_health where source = 'ats_jobs'")
    assert row is not None and row["blocked_until"] is not None


async def test_bad_json_and_server_errors_are_not_a_board(clean_db: str) -> None:
    startups()
    transport, _ = mock_transport(board_routes(**{GH + "brightcart/jobs": (200, "{oops"), ASHBY + "orcosa": (500, "")}))
    sigs, context, _ = await run(transport)
    assert context.stats["ats_jobs.greenhouse_bad_json"] == 1 and context.stats["ats_jobs.ashby_http_500"] == 1
    assert all(s.details["board"] != "greenhouse" for s in sigs)
