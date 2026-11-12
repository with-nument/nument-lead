"""Practo (Step 5.7, 9.10): the profile index from the sitemaps, a match only when the page confirms it, the
facts code reads, recent stories, the daily cap and a block. Fixtures only, no network."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine.http import PoliteClient
from nument_engine.models import ReviewPainClassification, SignalClassification
from nument_engine.pipeline import research
from nument_engine.sources import practo
from nument_engine.sources.practo import PractoAdapter, Profile

from .sources_helpers import (
    FakeRouter,
    clean_db,
    ctx,
    fixture_text,
    insert_business,
    mock_transport,
    no_network,
    segment,
)

__all__ = ["clean_db", "no_network"]

SEG = segment()
BASE = "https://www.practo.com"
PROFILE = f"{BASE}/pune/clinic/lotus-skin-and-hair-clinic-baner"
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
CLINIC = fixture_text("practo", "clinic.html")


def recent_page(days_ago: int = 10) -> str:
    when = (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    return fixture_text("practo", "recent.html").replace("{RECENT}", when)


def gz(text: str) -> httpx.Response:
    return httpx.Response(200, content=gzip.compress(text.encode()), headers={"content-type": "application/x-gzip"})


def practo_routes(**over: Any) -> dict[str, Any]:
    routes: dict[str, Any] = {
        f"{BASE}/robots.txt": (200, fixture_text("practo", "robots.txt")),
        f"{BASE}/profiles-sitemap.xml": (200, fixture_text("practo", "profiles-sitemap.xml")),
        f"{BASE}/titan-india-clinic-profiles-0-sitemap.xml.gz": gz(fixture_text("practo", "clinic-profiles-0.xml")),
        PROFILE: (200, CLINIC),
        f"{PROFILE}/recent": (200, recent_page()),
    }
    routes.update(over)
    return routes


def lotus(**over: Any) -> dict[str, Any]:
    return {
        "id": "b-practo",
        "segment_id": "clinics-in",
        "name": "Lotus Skin & Hair Clinic",
        "city": "Pune",
        "locality": "Baner",
        "address": "Office 2, Baner Road, Baner, Pune",
        "website": "https://lotusskin-nlead.in/",
        "web_domain": "lotusskin-nlead.in",
        "lat": 18.5592,
        "lng": 73.7866,
        **over,
    }


@pytest.fixture
def index_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "practo" / "clinic-profiles.json.gz"
    monkeypatch.setattr(practo, "index_path", lambda: path)
    return path


def adapter(routes: dict[str, Any], router: Any = None) -> tuple[PractoAdapter, list[httpx.Request]]:
    transport, seen = mock_transport(routes)
    ad = PractoAdapter(ctx(router), transport=transport)
    ad.min_gap_s = 0.0  # type: ignore[misc]
    return ad, seen


# ---- the page --------------------------------------------------------------------------------------------


def test_the_page_gives_rating_stories_doctors_fees_claim_and_place() -> None:
    page = practo.parse_page(CLINIC, PROFILE, NOW)
    assert (page.name, page.locality, page.city) == ("Lotus Skin & Hair Clinic", "Baner", "Pune")
    assert (page.rating, page.stories, page.doctors) == (4.8, 312, 2)
    assert (page.fee_min, page.fee_max, page.claimed, page.website) == (800, 1200, True, "www.lotusskin-nlead.in")
    assert page.lat == pytest.approx(18.559) and page.lng == pytest.approx(73.7868)
    assert len(page.reviews) == 1 and page.reviews[0].age_days > 1800  # a helpful story from 2021, dated


def test_the_facts_code_writes_from_a_profile() -> None:
    facts = {name: (value, quote) for name, value, quote in practo.facts(practo.parse_page(CLINIC, PROFILE, NOW))}
    assert facts["practo_reviews"] == ({"stories": 312, "rating": 4.8, "source": "practo"}, "4.8 (312 patient stories)")
    assert facts["staff_or_doctors"] == ({"count": 2, "source": "practo"}, "Doctors (2)")
    assert facts["practo_fees"] == ({"min": 800, "max": 1200, "currency": "INR"}, "₹800 - ₹1200")
    assert facts["practo_claimed"][0] == {"claimed": True}
    unclaimed = practo.PractoPage(url=PROFILE, stories=3, claimed=False)
    assert [f[0] for f in practo.facts(unclaimed)] == ["practo_reviews"]


def test_recent_stories_skip_votes_without_text() -> None:
    stories = practo.stories_from_state(practo.redux_state(recent_page(10)))
    assert len(stories) == 2 and all(s.age_days in (9, 10) for s in stories)
    assert "nobody picked up the phone" in stories[0].text
    assert practo.redux_state("<html>no state</html>") == {}


# ---- the match ------------------------------------------------------------------------------------------


def profiles(*slugs: str, city: str = "pune") -> list[Profile]:
    return [Profile(f"{BASE}/{city}/clinic/{s}", city, s) for s in slugs]


def test_candidates_need_every_word_of_the_name() -> None:
    found = practo.candidates(
        "Clear Skin - Baner",
        "Pune",
        profiles("skin-clinic-baner", "clear-skin-hairmd-clinic-baner-baner", "clear-skin-kharadi-kharadi"),
    )
    assert [p.slug for p in found] == ["clear-skin-hairmd-clinic-baner-baner"]
    one_word = practo.candidates("Dralisdentacare", None, profiles("dr-ali-s-dentacare-kammana-halli", "ali-dental"))
    assert [p.slug for p in one_word] == ["dr-ali-s-dentacare-kammana-halli"]
    assert practo.candidates("Smile", None, profiles("smile-dental-baner", "smile-care-aundh")) == []
    spelled = practo.candidates("Lotus Skinn and Hair Clinic", "Baner", profiles("lotus-skin-hair-clinic-baner-1"))
    assert len(spelled) == 1  # small spelling differences and a trailing number are fine


def test_closest_slug_first_and_at_most_three() -> None:
    slugs = [f"lotus-skin-and-hair-clinic-{loc}" for loc in ("aundh", "baner", "wakad", "kothrud")]
    found = practo.candidates("Lotus Skin and Hair Clinic", "Baner", profiles(*slugs))
    assert len(found) == 3 and found[0].slug.endswith("baner")


def test_city_slugs_follow_the_segment_aliases() -> None:
    assert practo.city_slugs(SEG, "Bengaluru") >= {"bengaluru", "bangalore"}
    assert practo.city_slugs(SEG, "Thane and Navi Mumbai") >= {"thane", "navi-mumbai"}
    assert practo.city_slugs(SEG, "Gurugram") >= {"gurgaon"}


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, "website"),
        ({"web_domain": "another-clinic.in", "website": "https://another-clinic.in/"}, None),
        ({"web_domain": None, "website": None}, "distance"),
        ({"web_domain": None, "website": None, "lat": 18.60, "lng": 73.70}, None),  # about 10 km away
        ({"web_domain": None, "website": None, "lat": None, "lng": None}, "locality"),
        (
            {"web_domain": None, "website": None, "lat": None, "lng": None, "address": "FC Road", "locality": "Deccan"},
            None,
        ),
        ({"web_domain": None, "website": None, "name": "Lotus Dental Care"}, None),  # the name is not Practo's
    ],
)
def test_a_profile_counts_only_when_its_page_confirms_it(over: dict[str, Any], expected: str | None) -> None:
    assert practo.confirms(lotus(**over), practo.parse_page(CLINIC, PROFILE, NOW)) == expected


# ---- the index ------------------------------------------------------------------------------------------


async def test_the_index_keeps_profile_roots_of_segment_cities(index_file: Path) -> None:
    ad, seen = adapter(practo_routes())
    try:
        index = await ad.index(SEG)
    finally:
        await ad.aclose()
    assert index == {
        "bangalore": ["dr-ali-s-dentacare-kammana-halli"],
        "pune": ["lotus-dental-care-aundh-1", "lotus-skin-and-hair-clinic-baner", "skin-clinic-baner"],
    }  # sub-pages and Chennai dropped
    fetched = {str(r.url) for r in seen}
    assert f"{BASE}/titan-india-provider-profiles-0-sitemap.xml.gz" not in fetched  # doctors, not clinics
    assert f"{BASE}/listings-sitemap.xml" not in fetched
    assert practo.load_index(index_file) == index
    assert practo.load_index(index_file, datetime.now(UTC) + timedelta(days=31)) is None  # rebuilt monthly


async def test_a_cached_index_is_used_without_any_request(index_file: Path) -> None:
    practo.save_index(index_file, {"pune": ["lotus-skin-and-hair-clinic-baner"]})
    ad, seen = adapter({})
    try:
        found = await ad.profiles_for(SEG, "Pune")
    finally:
        await ad.aclose()
    assert [p.url for p in found] == [PROFILE] and seen == []


# ---- one clinic end to end (needs the settings table for the daily cap) ---------------------------------


async def test_match_stores_nothing_but_returns_the_confirmed_profile_and_recent_stories(
    clean_db: str, index_file: Path
) -> None:
    ad, seen = adapter(practo_routes())
    try:
        found = await ad.safe_call(ad.match, lotus(), SEG)
    finally:
        await ad.aclose()
    assert found is not None and found.how == "website" and found.page.stories == 312
    assert [s.text[:16] for s in found.stories] == ["Very good doctor", "The doctor is go", "Great results, f"]
    assert ad.pages == 2 and ad.ctx.stats["practo.matched_website"] == 1
    assert f"{BASE}/pune/clinic/skin-clinic-baner" not in {str(r.url) for r in seen}


async def test_a_rejected_profile_is_skipped_and_no_match_means_none(clean_db: str, index_file: Path) -> None:
    ad, _ = adapter(practo_routes())
    try:
        found = await ad.safe_call(ad.match, lotus(web_domain="another-clinic.in", website=None), SEG)
    finally:
        await ad.aclose()
    assert found is None and ad.ctx.stats["practo.not_confirmed"] == 1 and ad.ctx.stats["practo.no_match"] == 1


async def test_the_daily_cap_stops_page_requests(clean_db: str, index_file: Path) -> None:
    db.set_setting("practo.pages_per_day", 1)
    ad, seen = adapter(practo_routes())
    try:
        found = await ad.safe_call(ad.match, lotus(), SEG)
        again = await ad.safe_call(ad.match, lotus(), SEG)
    finally:
        await ad.aclose()
    assert found is not None and found.stories[1:] == []  # the recent tab was not fetched
    assert again is None and ad.ctx.stats["practo.cap_reached"] >= 1
    assert f"{PROFILE}/recent" not in {str(r.url) for r in seen}


async def test_a_block_pauses_practo(clean_db: str, index_file: Path) -> None:
    ad, _ = adapter(practo_routes(**{PROFILE: (403, "Forbidden")}))
    try:
        assert await ad.safe_call(ad.match, lotus(), SEG) is None
    finally:
        await ad.aclose()
    row = db.fetch_one("select blocked_until, last_error from public.source_health where source = 'practo'")
    assert row is not None and row["blocked_until"] > datetime.now(UTC) and "403" in row["last_error"]
    assert ad.status()[0] is False


def test_off_in_settings_means_no_practo_request(clean_db: str, index_file: Path) -> None:
    flags = db.get_setting("sources_enabled")
    db.set_setting("sources_enabled", {**flags, "practo": False})
    assert PractoAdapter(ctx()).enabled() is False


# ---- research: the profile page, the facts, the signal ---------------------------------------------------


def test_research_stores_the_profile_its_facts_and_review_pain(
    clean_db: str, index_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_research import SITE, FakeBrowser, site_routes

    bid = insert_business(
        name="Lotus Skin & Hair Clinic",
        website=f"{SITE}/",
        web_domain="lotusskin-nlead.in",
        locality="Baner",
        address="Office 2, Baner Road, Baner, Pune",
        status="queued",
        queued_at=datetime.now(UTC),
    )
    transport, _ = mock_transport({**site_routes(), **practo_routes()})
    real = PoliteClient.__init__

    def init(self: PoliteClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        kwargs["min_gap_s"] = 0.0
        real(self, *args, **kwargs)

    monkeypatch.setattr(PoliteClient, "__init__", init)
    monkeypatch.setattr(research, "Browser", lambda cap: FakeBrowser(cap=0))
    no_job = SignalClassification(
        is_relevant=False,
        role_category="other",
        employer_name=None,
        employer_website=None,
        employer_domain="clinics",
        city=None,
        evidence_quote="Front Desk Executive",
        confidence=0.2,
    )
    pain = ReviewPainClassification(
        has_pain=True,
        flags=["unanswered_calls", "booking_trouble"],
        complaining_reviews=[1],
        quote="Called the clinic four times to book a slot and nobody picked up the phone.",
    )
    router = FakeRouter({"classify_signal": lambda _: no_job, "classify_reviews": [pain]})
    from .sources_helpers import run_context

    stats = research.run(run_context(segments=["clinics-in"]), router=router)
    assert stats["practo_matched"] == 1 and stats["practo_review_pain"] == 1
    page = db.fetch_one("select url, text from public.pages where business_id = %s and url like %s", [bid, "%practo%"])
    assert page is not None and "Doctors (2)" in page["text"]
    facts = {
        f["field"]: f
        for f in db.fetch_all("select * from public.facts where business_id = %s and url like %s", [bid, "%practo%"])
    }
    assert set(facts) == {"practo_reviews", "staff_or_doctors", "practo_fees", "practo_claimed"}
    assert all(f["verified"] and f["model"] == "rule" for f in facts.values())
    assert facts["staff_or_doctors"]["page_id"] is not None
    extra = db.scalar("select extra from public.businesses where id = %s", [bid])
    assert extra["practo"]["url"] == PROFILE and extra["practo"]["how"] == "website"
    assert extra["crawl"]["pages"]["practo"].endswith("/pune/clinic/lotus-skin-and-hair-clinic-baner")
    sig = db.fetch_one("select * from public.signals where business_id = %s and type = 'review_pain'", [bid])
    assert sig is not None and sig["source"] == "practo" and sig["url"] == PROFILE
    assert sig["quote"] == "Called the clinic four times to book a slot and nobody picked up the phone."
    assert sig["details"]["flags"] == ["booking_trouble", "unanswered_calls"]
