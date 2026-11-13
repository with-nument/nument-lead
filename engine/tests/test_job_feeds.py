"""Global job feeds (13 Nov 2026): Hacker News "Who is hiring?", Himalayas and We Work Remotely posts become
need-first `hiring_builder` signals in the company's own country segment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import FeedJobClassification
from nument_engine.pipeline.signals import SignalSink
from nument_engine.segments import load_segments, sync_segments_to_db
from nument_engine.sources import job_feeds as jf
from nument_engine.sources.job_feeds import FeedPost, JobFeedsAdapter

from .sources_helpers import FakeRouter, clean_db, ctx, mock_transport, no_network

__all__ = ["clean_db", "no_network"]

NOW = datetime.now(UTC)
THREAD = "50338728"
HN_TEXT = (
    "Brightcart | Full-stack engineer (contract) | Austin, TX | REMOTE (US)<p>We are a 9-person team building "
    'ordering software for grocers. Apply at <a href="https://brightcart.io/jobs">brightcart.io/jobs</a>'
)


def hn_hit(object_id: str, text: str, parent: str = THREAD, age_days: int = 2) -> dict[str, Any]:
    return {
        "objectID": object_id,
        "parent_id": int(parent),
        "comment_text": text,
        "created_at_i": int((NOW - timedelta(days=age_days)).timestamp()),
    }


def answer(**changes: Any) -> FeedJobClassification:
    base: dict[str, Any] = {
        "is_relevant": True,
        "company_name": "Brightcart",
        "company_website": "brightcart.io",
        "company_kind": "product_company",
        "hq_country": "us",
        "city": "Austin",
        "role": "Full-stack engineer",
        "contract": True,
        "team_size": 9,
        "evidence_quote": "Full-stack engineer (contract)",
        "confidence": 0.9,
    }
    return FeedJobClassification(**{**base, **changes})


def post(text: str = HN_TEXT, **changes: Any) -> FeedPost:
    return jf.hn_posts({"hits": [hn_hit("1", text)]}, THREAD)[0] if not changes else FeedPost(**changes)


# ---- parsers -------------------------------------------------------------------------------------------


def test_hn_keeps_only_top_level_posts_and_reads_company_role_and_links() -> None:
    data = {"hits": [hn_hit("1", HN_TEXT), hn_hit("2", "Great post, thanks!", parent="1")]}
    posts = jf.hn_posts(data, THREAD)
    assert [p.post_id for p in posts] == ["1"]
    p = posts[0]
    assert p.company == "Brightcart" and p.title.startswith("Full-stack engineer (contract)")
    assert p.location == "Austin, TX" and p.url == "https://news.ycombinator.com/item?id=1"
    assert p.links == ["https://brightcart.io/jobs"] and "9-person team" in p.text
    assert jf.hn_thread_id({"hits": [{"title": "Ask HN: Who wants to be hired?", "objectID": "9"},
                                     {"title": "Ask HN: Who is hiring? (November 2026)", "objectID": THREAD}]}) == THREAD  # fmt: skip


def test_himalayas_and_wwr_parsers() -> None:
    him = jf.himalayas_posts(
        {
            "jobs": [
                {
                    "title": "React Developer",
                    "companyName": "Leafly Studio",
                    "description": "<p>Contract role building our booking app.</p>",
                    "pubDate": str(int(NOW.timestamp())),
                    "locationRestrictions": ["United Kingdom"],
                    "guid": "https://himalayas.app/companies/leafly/jobs/react-developer-1",
                }
            ]
        }
    )
    assert him[0].post_id == "react-developer-1" and him[0].company == "Leafly Studio"
    assert him[0].location == "United Kingdom" and "booking app" in him[0].text
    xml = (
        "<rss><channel><item><title>Acme Robotics: Senior Backend Engineer</title>"
        "<region>USA Only</region><type>Contract</type><pubDate>Thu, 12 Nov 2026 17:02:18 +0000</pubDate>"
        "<link>https://weworkremotely.com/remote-jobs/acme-senior-backend-engineer</link>"
        "<description><![CDATA[<p>Join Acme at <a href='https://acme.example'>acme.example</a></p>]]></description>"
        "</item></channel></rss>"
    )
    wwr = jf.wwr_posts(xml)
    assert wwr[0].company == "Acme Robotics" and wwr[0].title == "Senior Backend Engineer"
    assert wwr[0].links == ["https://acme.example"] and "Contract" in wwr[0].text


def test_builder_words_and_website_choice() -> None:
    assert jf.is_builder_post("Full-stack engineer (contract)")
    assert not jf.is_builder_post("Head of Customer Success")
    p = post()
    assert jf.website_from(p, "brightcart.io") == "https://brightcart.io"
    assert jf.website_from(p, "made-up.io") == "https://brightcart.io"  # a guess is never kept
    ats = FeedPost(feed="hn", post_id="3", url="u", text="Apply", links=["https://jobs.lever.co/brightcart/1"])
    assert jf.website_from(ats, None) is None
    assert jf.country_code("UK") == "gb" and jf.country_code("United States") == "us" and jf.country_code("") is None


# ---- routing -------------------------------------------------------------------------------------------


def classify(*answers: FeedJobClassification, p: FeedPost | None = None) -> tuple[Any, str]:
    adapter = JobFeedsAdapter(ctx(FakeRouter({"classify_feed_job": list(answers)})))
    return adapter.classify(p or post(), load_segments())


def test_a_us_product_company_hiring_a_contract_developer_is_a_strong_us_lead() -> None:
    sig, why = classify(answer())
    assert why == "signal" and sig is not None
    assert sig.segment_id == "firms-us" and sig.type == "hiring_builder" and sig.points == jf.CONTRACT_POINTS
    assert sig.business_hint == {"name": "Brightcart", "city": "Austin", "website": "https://brightcart.io"}
    assert sig.quote == "Full-stack engineer (contract)" and sig.evidence_key == "hn:1"
    assert sig.details["contract"] is True and sig.details["team_size"] == 9


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"company_kind": "software_agency_or_it_services"}, "kind_software_agency_or_it_services"),
        ({"company_kind": "staffing_or_marketplace"}, "kind_staffing_or_marketplace"),
        ({"company_kind": "enterprise"}, "kind_enterprise"),
        ({"team_size": 900}, "too_big"),
        ({"hq_country": "de"}, "country_not_enabled"),
        ({"hq_country": None}, "country_not_enabled"),
        ({"is_relevant": False}, "not_relevant"),
        ({"confidence": 0.3}, "low_confidence"),
        ({"company_kind": "marketing_or_design_agency"}, "partners_off"),
    ],
)
def test_posts_that_are_not_our_clients_are_dropped(changes: dict[str, Any], why: str) -> None:
    sig, got = classify(answer(**changes))
    assert sig is None and got == why


def test_uk_and_full_time_roles_route_with_the_segment_points() -> None:
    sig, why = classify(answer(hq_country="UK", city="London", contract=False, team_size=None))
    assert why == "signal" and sig is not None
    assert sig.segment_id == "firms-gb" and sig.points is None and "team_size" not in sig.details


# ---- the whole watcher ---------------------------------------------------------------------------------


async def test_signals_for_reads_hn_once_and_links_a_remote_company_by_name(
    clean_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = [
        hn_hit("1", HN_TEXT),
        hn_hit("2", "Lumen Health | Head of Customer Success | NYC"),  # no builder words: never sent to the AI
        hn_hit("3", "Nimbus | Founding engineer | REMOTE<p>We are hiring our first engineer.", age_days=40),  # old
        hn_hit("4", "Driftwood | Mobile developer (Flutter) | REMOTE<p>Small team, contract welcome."),
    ]
    routes: dict[str, Any] = {
        jf.HN_BY_DATE: (200, {"hits": [{"title": "Ask HN: Who is hiring? (November 2026)", "objectID": THREAD}]}),
        jf.HN_SEARCH: (200, {"hits": hits}),
        jf.HIMALAYAS_SEARCH: (200, {"jobs": []}),
        "https://himalayas.app/robots.txt": (404, ""),
        "https://weworkremotely.com/robots.txt": (404, ""),
        "*": (200, "<rss><channel></channel></rss>"),
    }
    transport, _ = mock_transport(routes)
    monkeypatch.setattr(JobFeedsAdapter, "min_gap_s", 0.0)
    router = FakeRouter(
        {
            "classify_feed_job": [
                answer(),
                answer(company_name="Driftwood", company_website=None, city=None, hq_country="au", contract=True),
            ]
        }
    )
    segments = load_segments()
    context = ctx(router)
    async with JobFeedsAdapter(context, transport=transport) as adapter:
        sigs = await adapter.signals_for(segments)
    assert [s.segment_id for s in sigs] == ["firms-us", "firms-au"]
    assert context.stats["job_feeds.no_builder_words"] == 1 and len(router.calls) == 2
    seen = {r["source_key"] for r in db.fetch_all("select source_key from public.source_records")}
    assert seen == {"hn:1", "hn:2", "hn:4"}  # the 40-day-old post is skipped, not remembered

    with db.tx() as conn:
        sync_segments_to_db(conn, segments)  # firms-us and firms-au rows for the businesses' foreign key
    sink = SignalSink(segments, context)
    for sig in sigs:
        sink.add(sig, segments[sig.segment_id or ""])
    sink.flush()
    rows = db.fetch_all(
        "select b.name, b.segment_id, b.website, s.points from public.signals s "
        "join public.businesses b on b.id = s.business_id order by b.name"
    )
    assert [(r["name"], r["segment_id"], r["website"]) for r in rows] == [
        ("Brightcart", "firms-us", "https://brightcart.io/"),
        ("Driftwood", "firms-au", None),  # a remote company with no site or city: linked by name
    ]
    assert all(float(r["points"]) == jf.CONTRACT_POINTS for r in rows)

    async with JobFeedsAdapter(ctx(FakeRouter({"classify_feed_job": []})), transport=transport) as again:
        assert await again.signals_for(segments) == []  # every post was read already
