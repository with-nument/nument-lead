"""The people stage against the test database: free founder names first for startups, then grounded searches
within the `people` allowance (lane E3, 15 Nov 2026)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import DecisionMakerLookup
from nument_engine.pipeline import people
from nument_engine.pipeline.runs import Options, RunContext
from nument_engine.segments import load_segments, sync_segments_to_db

from .sources_helpers import clean_db, no_network

__all__ = ["clean_db", "no_network"]

ARTICLE = "https://news.example.com/brightcart-raises"


@pytest.fixture
def seg_db(clean_db: str) -> Iterator[str]:
    with db.tx() as conn:
        sync_segments_to_db(conn, load_segments())
    yield clean_db


class Router:
    """find_decision_maker answers: Maya Chen, backed, for every business."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.budget = None

    def run_result(self, task: str, inputs: dict[str, Any]) -> Any:
        assert task == people.TASK
        self.calls.append(inputs)
        name = inputs["name"]
        line = f"Decision maker: Maya Chen, Founder at {name}"
        ground = {"queries": [f"{name} founder"], "sources": [{"uri": ARTICLE, "title": "news"}],
                  "supports": [{"text": f"Maya Chen, Founder at {name}", "chunks": [0]}]}  # fmt: skip
        return SimpleNamespace(output=DecisionMakerLookup(name="Maya Chen", role="Founder", line=line),
                               grounding=ground, inr=0.1)  # fmt: skip


def lead(segment: str, *, name: str | None = None) -> str:
    tag = uuid.uuid4().hex[:6]
    with db.tx() as conn:
        biz = conn.execute(
            "insert into public.businesses (segment_id, name, norm_name, country, city, status) "
            "values (%s, %s, %s, %s, 'Austin', 'researched') returning id",
            [segment, name or f"Brightcart {tag}", (name or f"brightcart {tag}").lower(), segment[-2:]],
        ).fetchone()
        assert biz is not None
        conn.execute(
            "insert into public.leads (business_id, segment_id, grade, pitch_mode) values (%s, %s, 'A', 'fit_only')",
            [biz["id"], segment],
        )
    return str(biz["id"])


def founders_signal(business_id: str, founders: list[dict[str, Any]], quote: str | None) -> None:
    now = datetime.now(UTC)
    db.execute(
        "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, url, "
        "quote, details, dedupe_key) values (%s, 'funding', 'money', 10, %s, %s + interval '60 days', "
        "'funding_rss', %s, %s, %s, %s)",
        [business_id, now, now, ARTICLE, quote, db.Jsonb({"founders": founders}), f"test:{uuid.uuid4().hex}"],
    )


def owners(business_id: str) -> list[dict[str, Any]]:
    return db.fetch_all(
        "select name, role, source, source_url, quote, verified, line, line_why, is_decision_maker "
        "from public.contacts where business_id = %s order by created_at",
        [business_id],
    )


def rc(*segments: str) -> RunContext:
    return RunContext(run_id=str(uuid.uuid4()), kind="manual", opts=Options(segments=list(segments)),
                      started_at=datetime.now(UTC))  # fmt: skip


def test_startup_founders_from_signals_cost_no_search(seg_db: str) -> None:
    bid = lead("firms-us")
    founders_signal(bid, [{"name": "Maya Chen", "role": "CEO", "source_url": ARTICLE}],
                    "Brightcart, founded by Maya Chen, raised $600K.")  # fmt: skip
    router = Router()
    stats = people.run(rc("firms-us"), router=router)
    assert router.calls == [] and stats["founders.signals"] == 1 and stats["named_free"] == 1
    [row] = owners(bid)
    assert (row["name"], row["source"], row["line"], row["verified"], row["is_decision_maker"]) == (
        "Maya Chen", "other", "owner", True, True
    )  # fmt: skip
    assert "Maya Chen" in row["quote"] and row["source_url"] == ARTICLE
    assert people.run(rc("firms-us"), router=router)["candidates"] == 0  # a named founder: done


def test_grounded_searches_stay_within_the_allowance(seg_db: str) -> None:
    db.set_setting("grounding.people_per_day", 1)
    first, second = lead("firms-us"), lead("firms-us")
    router = Router()
    stats = people.run(rc("firms-us"), router=router)
    assert len(router.calls) == 1 and stats["stopped_allowance"] == 1 and stats["found"] == 1
    searched = [b for b in (first, second) if owners(b)]
    assert len(searched) == 1
    [row] = owners(searched[0])
    assert (row["source"], row["line"], row["line_why"]) == ("other", "owner", people.SEARCH_WHY)


def test_a_searched_startup_is_read_again_only_when_a_new_founder_signal_arrives(seg_db: str) -> None:
    db.set_setting("grounding.people_per_day", 0)
    bid = lead("firms-us")
    router = Router()
    people.run(rc("firms-us"), router=router)  # no allowance: nothing searched, nothing named
    db.execute(
        "update public.businesses set extra = extra || jsonb_build_object('dm_lookup_at', now()::text) where id = %s",
        [bid],
    )
    assert people.run(rc("firms-us"), router=router)["candidates"] == 0  # read already, nothing new since
    founders_signal(bid, [{"name": "Leo Park", "role": "Co-founder"}], "Leo Park started Brightcart in 2025.")
    stats = people.run(rc("firms-us"), router=router)
    assert stats["founders.signals"] == 1 and [r["name"] for r in owners(bid)] == ["Leo Park"]


def test_a_do_not_contact_founder_is_never_added_back(seg_db: str) -> None:
    bid = lead("firms-us")
    db.execute(
        "insert into public.contacts (business_id, name, role, source, is_decision_maker, do_not_contact) "
        "values (%s, 'Maya Chen', 'CEO', 'other', true, true)",
        [bid],
    )
    founders_signal(bid, [{"name": "Maya Chen", "role": "CEO"}], "Maya Chen founded Brightcart.")
    db.set_setting("grounding.people_per_day", 0)
    stats = people.run(rc("firms-us"), router=Router())
    assert stats.get("founders.signals", 0) == 0 and len(owners(bid)) == 1


def test_other_segments_still_search_and_without_a_router_nothing_breaks(seg_db: str, monkeypatch: Any) -> None:
    clinic = lead("clinics-in", name=f"Sunrise Dental {uuid.uuid4().hex[:4]}")
    router = Router()
    stats = people.run(rc("clinics-in"), router=router)
    assert len(router.calls) == 1 and stats["found"] == 1 and owners(clinic)[0]["name"] == "Maya Chen"

    from nument_engine.pipeline import ai

    def no_router(rc: RunContext) -> Any:
        raise ai.AIUnavailable("router", "no key")

    monkeypatch.setattr(ai, "router_for", no_router)
    startup = lead("firms-us")
    founders_signal(startup, [{"name": "Maya Chen", "role": "CEO"}], "Maya Chen founded it.")
    other = lead("firms-us")
    stats = people.run(rc("firms-us"))
    assert stats["founders.signals"] == 1 and stats["skipped_no_router"] == 1 and owners(other) == []
