"""The startup filters of the job and search sources (lane E1b, 15 Nov 2026): a startup segment (firms-<country>)
takes only startups of at most startup.max_team people; a small business only when it is a startup; countries
where cold email needs prior consent are never routed; grounded asks spend only their own share."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.budget import Budget
from nument_engine.models import FeedJobClassification, PublicAskItem, SignalClassification
from nument_engine.pipeline import grounding
from nument_engine.segments import load_segments
from nument_engine.sources import grounded_search as gs_module
from nument_engine.sources.grounded_search import GroundedSearchAdapter
from nument_engine.sources.job_feeds import FeedPost, JobFeedsAdapter
from nument_engine.sources.jobs import JobPost, classify_job, startup_fit

from .sources_helpers import FakeRouter, clean_db, ctx, mock_transport, no_network

__all__ = ["clean_db", "no_network"]

SEGMENTS = load_segments()
LIMITS = (10, 2_000_000.0)


# ---- the shared rule -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "stated", "expected"),
    [
        ({}, False, None),  # unknown passes: qualification decides
        ({"is_startup": True, "team_size": 6}, False, None),
        ({"team_size": 10}, False, None),
        ({"team_size": 11}, False, "too_big"),
        ({"is_startup": False}, False, "not_startup"),
        ({}, True, "not_startup"),  # another industry: only a clear yes
        ({"is_startup": True}, True, None),
        ({"is_startup": True, "team_size": 40}, True, "too_big"),
    ],
)
def test_startup_fit(fields: dict[str, Any], stated: bool, expected: str | None) -> None:
    assert startup_fit(fields, limits=LIMITS, stated=stated) == expected


def test_startup_fit_reads_the_settings_only_when_there_is_a_size(clean_db: str) -> None:
    db.set_setting("startup.max_team", 5)
    assert startup_fit({"team_size": 6}) == "too_big"
    assert startup_fit({"team_size": 5}) is None


# ---- job feeds -------------------------------------------------------------------------------------------


def feed_answer(**changes: Any) -> FeedJobClassification:
    base: dict[str, Any] = {
        "is_relevant": True,
        "company_name": "Brightcart",
        "company_website": None,
        "company_kind": "product_company",
        "hq_country": "us",
        "city": None,
        "role": "Founding engineer",
        "contract": False,
        "team_size": None,
        "evidence_quote": "Founding engineer",
        "confidence": 0.9,
        "is_startup": None,
    }
    return FeedJobClassification(**{**base, **changes})


def feed_classify(answer: FeedJobClassification) -> tuple[Any, str]:
    post = FeedPost(feed="hn", post_id="7", url="https://news.ycombinator.com/item?id=7", text="Founding engineer")
    return JobFeedsAdapter(ctx(FakeRouter({"classify_feed_job": [answer]}))).classify(post, SEGMENTS)


@pytest.mark.parametrize(
    ("changes", "why", "segment"),
    [
        ({}, "signal", "firms-us"),
        ({"team_size": 8, "is_startup": True}, "signal", "firms-us"),
        ({"team_size": 12}, "too_big", None),  # more than startup.max_team
        ({"is_startup": False}, "not_startup", None),  # an established product company
        ({"company_kind": "small_business"}, "not_startup", None),  # a shop hiring a developer: not a startup
        ({"company_kind": "small_business", "is_startup": True}, "signal", "firms-us"),
        ({"hq_country": "de"}, "country_not_enabled", None),  # cold email needs prior consent there
        ({"company_kind": "marketing_or_design_agency", "team_size": 40}, "signal", "partners-us"),
    ],
)
def test_job_feeds_keep_only_small_startups(changes: dict[str, Any], why: str, segment: str | None) -> None:
    sig, got = feed_classify(feed_answer(**changes))
    assert got == why
    assert (sig.segment_id if sig else None) == segment


def test_a_stated_team_size_is_kept_with_its_source() -> None:
    sig, _ = feed_classify(feed_answer(team_size=4))
    assert sig is not None and sig.details["team_size"] == 4 and sig.details["team_size_source"] == "post"


# ---- job posts (Apna, Adzuna, careers pages) ----------------------------------------------------------


def verdict(**over: Any) -> SignalClassification:
    base: dict[str, Any] = {
        "is_relevant": True,
        "role_category": "builder",
        "employer_name": "Brightcart",
        "employer_website": None,
        "employer_domain": "firms_startups",
        "city": None,
        "evidence_quote": "Full stack developer",
        "confidence": 0.9,
    }
    return SignalClassification(**{**base, **over})


def job_post() -> JobPost:
    return JobPost(source="apna", job_id="9", url="https://apna.co/job/9", title="Full stack developer")


@pytest.mark.parametrize(
    ("over", "segment", "reason"),
    [
        ({}, "firms-in", None),
        ({"team_size": 30}, None, "jobs.too_big"),
        ({"is_startup": False}, None, "jobs.not_startup"),
        ({"employer_domain": "hospitality"}, None, "jobs.not_startup"),  # a hotel hiring a developer
        ({"employer_domain": "hospitality", "is_startup": True}, "firms-in", None),  # a travel startup
        ({"employer_domain": "clinics"}, "clinics-in", None),  # its own segment is on: no startup rule
    ],
)
def test_job_posts_reach_the_startup_segment_only_from_startups(
    over: dict[str, Any], segment: str | None, reason: str | None
) -> None:
    context = ctx(FakeRouter({"classify_signal": [verdict(**over)]}))
    segments = {k: SEGMENTS[k] for k in ("clinics-in", "firms-in")}
    sig = classify_job(
        context, job_post(), segments, country="in", default_segment=segments["clinics-in"], limits=LIMITS
    )
    assert (sig.segment_id if sig else None) == segment
    if reason:
        assert context.stats[reason] == 1


# ---- grounded search ---------------------------------------------------------------------------------------


def ask(url: str, quote: str) -> PublicAskItem:
    return PublicAskItem(
        poster_business="Brightcart", poster_city=None, need="a founding engineer", quote=quote, url=url,
        posted_date=(datetime.now(UTC) - timedelta(days=2)).date().isoformat(),
    )  # fmt: skip


class Grounded:
    """What the router may return for a grounded call: the parsed items plus the citations."""

    def __init__(self, items: list[PublicAskItem], url: str) -> None:
        self.items = items
        self.grounding = {"sources": [{"uri": url, "title": "jobs-nlead.example"}], "queries": ["q"]}


async def search_firms(clean_db: str, answers: list[SignalClassification], queries: list[str]) -> tuple[Any, Any]:
    url = "https://jobs-nlead.example/brightcart-founding-engineer"
    page = "<html><body><p>Brightcart is hiring a founding engineer to build our app.</p></body></html>"
    transport, _ = mock_transport({"https://jobs-nlead.example/robots.txt": (404, ""), url: (200, page)})
    found = Grounded([ask(url, "hiring a founding engineer to build our app")], url)
    router = FakeRouter({"grounded_search": lambda _: found, "classify_signal": answers})
    context = ctx(router)
    seg = SEGMENTS["firms-us"]
    async with GroundedSearchAdapter(context, transport=transport) as gs:
        gs.pages.min_gap = 0.0
        gs.todays_queries = lambda _seg, day=None: queries  # type: ignore[method-assign]
        sigs = await gs.signals_for(seg, budget=len(queries))
    return sigs, context


async def test_grounded_asks_keep_startups_and_drop_big_companies(clean_db: str) -> None:
    sigs, context = await search_firms(clean_db, [verdict(team_size=7), verdict(team_size=300)], ["q1", "q2"])
    assert [s.segment_id for s in sigs] == [None]  # the first: firms-us itself; the second: too big
    assert context.stats["grounded_search.too_big"] == 1


async def test_another_industry_falls_back_to_the_startup_segment_only_when_it_is_a_startup(clean_db: str) -> None:
    sigs, _ = await search_firms(
        clean_db,
        [verdict(employer_domain="clinics"), verdict(employer_domain="clinics", is_startup=True)],
        ["q1", "q2"],
    )
    assert [s.segment_id for s in sigs] == ["clinics-us", "clinics-us"]
    assert [s.details.get("fallback_segment") for s in sigs] == [None, "firms-us"]


async def test_grounded_asks_stop_at_their_daily_share(clean_db: str) -> None:
    db.set_setting("grounding.asks_per_day", 5)
    budget = Budget()
    budget.record_search("gemini", "gemini-3.8-flash", 5, task="grounded_search")
    sigs, context = await search_firms(clean_db, [verdict()], ["q1"])
    assert sigs == [] and context.stats["grounded_search.allowance_used"] == 1
    assert grounding.allowance("asks", Budget()) == 0  # the stages' rule says the same


def test_the_asks_share_matches_the_grounding_table() -> None:
    assert grounding.USES["asks"] == gs_module.ASKS_PER_DAY
    assert grounding.USE_TASKS["asks"] == (gs_module.TASK,)
    assert gs_module.ASKS_SETTING == "grounding.asks_per_day"
    assert "2 to 10 people" in gs_module.DOMAIN_WORDS["firms"]
