"""Google Maps reviews (grey source): parsing what the page shows, confirming the listing, stopping on any wall,
and the night stage that stores numbers like Places data. A fake page stands in for Chromium; no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import ReviewPainClassification
from nument_engine.pipeline import maps_reviews as stage
from nument_engine.pipeline import reviews
from nument_engine.sources import maps_reviews as mr
from nument_engine.sources.maps_reviews import MapsReviewsAdapter

from .sources_helpers import (
    FakeRouter,
    clean_db,
    ctx,
    fixture_json,
    insert_business,
    mock_transport,
    no_network,
    run_context,
)

__all__ = ["clean_db", "no_network"]

LISTING = fixture_json("maps", "listing.json")
RESULTS = fixture_json("maps", "results.json")
GOOGLE_ROBOTS = "User-agent: *\nDisallow: /search\nDisallow: /maps/\nAllow: /maps/search/\nAllow: /maps/place/\n"


def lotus(**over: Any) -> dict[str, Any]:
    return {
        "id": "b-maps",
        "segment_id": "clinics-in",
        "name": "Lotus Skin & Hair Clinic",
        "city": "Pune",
        "locality": "Baner",
        "address": "Office 2, Baner Road",
        "website": "https://lotusskin-nlead.in/",
        "web_domain": "lotusskin-nlead.in",
        "lat": 18.5592,
        "lng": 73.7866,
        **over,
    }


# ---- parsing ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("3 weeks ago", 21),
        ("a month ago", 30),
        ("Edited 2 years ago", 730),
        ("5 days ago", 5),
        ("an hour ago", 0),
        ("yesterday", 1),
        ("last summer", None),
    ],
)
def test_relative_review_dates(text: str, days: int | None) -> None:
    assert mr.age_days(text) == days


def test_the_listing_numbers_place_and_reviews() -> None:
    listing = mr.listing_from(LISTING)
    assert (listing.name, listing.rating, listing.review_count) == ("Lotus Skin & Hair Clinic", 4.6, 1204)
    assert listing.website == "https://www.lotusskin-nlead.in/"  # the Google redirect unwrapped
    assert listing.address == "Office 2, Baner Road, Baner, Pune, Maharashtra 411045"
    assert (listing.lat, listing.lng) == (18.5591, 73.7869) and "?" not in mr.listing_from(
        {**LISTING, "url": LISTING["url"] + "?hl=en&entry=ttu"}
    ).url
    assert [(r.age_days, r.rating) for r in listing.reviews] == [(21, 1.0), (60, 5.0), (365, 4.0)]
    assert mr.parse_count("(515)") == 515 and mr.parse_count("12,345 reviews") == 12345 and mr.parse_count("") is None
    assert mr.parse_rating("4.9 stars ") == 4.9 and mr.parse_rating("7 stars") is None


def test_the_search_query_names_the_locality_once() -> None:
    assert mr.query_for(lotus()) == "Lotus Skin & Hair Clinic, Baner, Pune"
    assert mr.query_for(lotus(locality="Pune")) == "Lotus Skin & Hair Clinic, Pune"
    assert mr.query_for(lotus(name="Clear Skin - Baner")) == "Clear Skin - Baner, Pune"
    assert (
        mr.query_for(lotus(city="Thane and Navi Mumbai", locality="Vashi")) == "Lotus Skin & Hair Clinic, Vashi, Thane"
    )
    assert mr.search_url(lotus()).startswith("https://www.google.com/maps/search/Lotus%20Skin%20%26%20Hair")


@pytest.mark.parametrize(
    ("url", "text", "dialog", "listing", "expected"),
    [
        ("https://consent.google.com/ml?continue=x", "", "", False, "consent wall"),
        ("https://www.google.com/sorry/index?continue=x", "", "", False, "bot check (sorry page)"),
        ("https://accounts.google.com/signin", "", "", False, "sign-in wall"),
        ("https://www.google.com/maps/search/x", "Our systems have detected unusual traffic", "", False, "wall"),
        ("https://www.google.com/maps/place/x", "Sorry, unusual traffic near the clinic", "", True, None),
        ("https://www.google.com/maps/place/x", "", "Sign-in to get the best of Google Maps", True, "wall"),
        ("https://www.google.com/maps/place/x", "Lotus Skin & Hair Clinic 4.6", "", True, None),
    ],
)
def test_walls_are_recognised_but_a_review_text_is_not_one(
    url: str, text: str, dialog: str, listing: bool, expected: str | None
) -> None:
    why = mr.wall_reason(url, text, dialog, listing)
    assert (why is None) if expected is None else (why is not None and why.startswith(expected))


@pytest.mark.parametrize(
    ("over", "listing_over", "expected"),
    [
        ({}, {}, "website"),
        ({"web_domain": "other-clinic.in"}, {}, None),
        ({"web_domain": None, "website": None}, {}, "distance"),
        ({"web_domain": None, "website": None}, {"lat": 18.62, "lng": 73.70}, None),
        ({"web_domain": None, "website": None, "lat": None, "lng": None}, {}, "address"),
        ({"web_domain": None, "website": None, "name": "Lotus Dental Care"}, {}, None),
        ({"web_domain": None}, {"website": None, "name": "Lotus Skin & Hair Clinic - Baner"}, "distance"),
    ],
)
def test_a_listing_counts_only_when_confirmed(
    over: dict[str, Any], listing_over: dict[str, Any], expected: str | None
) -> None:
    listing = mr.listing_from(LISTING)
    for key, value in listing_over.items():
        setattr(listing, key, value)
    assert mr.confirms(lotus(**over), listing) == expected


# ---- the adapter with a fake page --------------------------------------------------------------------------


class FakePage:
    """Answers the module's scripts from fixtures; navigations change `url`."""

    def __init__(self, browser: FakeBrowser) -> None:
        self.b = browser
        self.url = "about:blank"
        self.clicked: list[str] = []

    async def goto(self, url: str, **_: Any) -> None:
        self.b.visited.append(url)
        self.url = self.b.redirect.get("search", url) if "/maps/search/" in url else url

    async def wait_for_selector(self, selector: str, **_: Any) -> None:
        if self.b.nothing:
            raise TimeoutError(selector)

    async def wait_for_function(self, expression: str, **_: Any) -> None:
        if self.b.nothing:
            raise TimeoutError(expression)

    async def wait_for_timeout(self, timeout: float) -> None:
        return None

    async def click(self, selector: str, **_: Any) -> None:
        self.clicked.append(selector)
        if self.b.dialog_after_click:
            self.b.dialog = "Sign-in to get the best of Google Maps"

    async def evaluate(self, expression: str) -> Any:
        if expression == mr.PAGE_STATE_JS:
            return {"has_listing": not self.b.nothing, "dialog": self.b.dialog, "text": self.b.text}
        if expression == mr.RESULTS_JS:
            return RESULTS
        if expression == mr.READ_LISTING_JS:
            return {**self.b.listing, "url": self.url if "/maps/place/" in self.url else self.b.listing["url"]}
        return 0

    async def close(self) -> None:
        self.b.closed += 1


class FakeBrowser:
    def __init__(self, **kw: Any) -> None:
        self.visited: list[str] = []
        self.redirect: dict[str, str] = kw.get("redirect", {"search": LISTING["url"]})
        self.listing: dict[str, Any] = kw.get("listing", LISTING)
        self.nothing: bool = kw.get("nothing", False)
        self.dialog: str = ""
        self.text: str = kw.get("text", "")
        self.dialog_after_click: bool = kw.get("dialog_after_click", False)
        self.closed = 0

    async def page(self) -> FakePage:
        return FakePage(self)

    async def aclose(self) -> None:
        return None


def maps_adapter(browser: FakeBrowser, router: Any = None, robots: str = GOOGLE_ROBOTS) -> MapsReviewsAdapter:
    transport, _ = mock_transport({"https://www.google.com/robots.txt": (200, robots)})
    ad = MapsReviewsAdapter(ctx(router), transport=transport, browser=browser)
    ad.min_gap_s = 0.0  # type: ignore[misc]
    return ad


async def test_a_direct_listing_is_read_and_confirmed() -> None:
    browser = FakeBrowser()
    ad = maps_adapter(browser)
    try:
        found = await ad.lookup(lotus())
        requests = ad.http.requests
    finally:
        await ad.aclose()
    assert found.how == "website" and found.listing is not None and found.listing.review_count == 1204
    assert len(found.listing.reviews) == 3 and browser.closed == 1
    assert requests == 2  # robots.txt and the search page, both through the polite client


async def test_a_result_list_opens_the_listing_whose_name_matches() -> None:
    browser = FakeBrowser(redirect={"search": "https://www.google.com/maps/search/lotus"})
    ad = maps_adapter(browser)
    try:
        found = await ad.lookup(lotus())
    finally:
        await ad.aclose()
    assert browser.visited[-1] == RESULTS[1]["href"] and found.how == "website"


async def test_no_listing_is_not_a_match() -> None:
    ad = maps_adapter(FakeBrowser(nothing=True))
    try:
        found = await ad.lookup(lotus())
    finally:
        await ad.aclose()
    assert found.listing is None and found.how is None and found.why == "nothing found"


@pytest.mark.parametrize(
    "browser",
    [
        FakeBrowser(redirect={"search": "https://consent.google.com/ml"}),
        FakeBrowser(redirect={"search": "https://www.google.com/sorry/index"}, nothing=True),
        FakeBrowser(dialog_after_click=True),
    ],
    ids=["consent", "captcha", "sign-in"],
)
async def test_any_wall_raises_a_block(browser: FakeBrowser) -> None:
    from nument_engine.http import SourceBlocked

    ad = maps_adapter(browser)
    try:
        with pytest.raises(SourceBlocked):
            await ad.lookup(lotus())
    finally:
        await ad.aclose()


async def test_robots_txt_still_decides() -> None:
    from nument_engine.http import SourceBlocked

    browser = FakeBrowser()
    ad = maps_adapter(browser, robots="User-agent: *\nDisallow: /maps/\n")
    try:
        with pytest.raises(SourceBlocked, match="robots"):
            await ad.lookup(lotus())
    finally:
        await ad.aclose()
    assert browser.visited == []


# ---- the night stage --------------------------------------------------------------------------------------


def pain() -> ReviewPainClassification:
    return ReviewPainClassification(
        has_pain=True,
        flags=["unanswered_calls"],
        complaining_reviews=[1],
        quote="I called six times to reschedule and gave up.",
    )


def queued(**over: Any) -> str:
    values: dict[str, Any] = {
        "name": "Lotus Skin & Hair Clinic",
        "website": "https://lotusskin-nlead.in/",
        "web_domain": "lotusskin-nlead.in",
        "locality": "Baner",
        "lat": 18.5592,
        "lng": 73.7866,
        "status": "queued",
        "queued_at": datetime.now(UTC),
    }
    values.update(over)
    return insert_business(**values)


def run_stage(browser: FakeBrowser, router: Any = None, limit: int | None = None) -> dict[str, Any]:
    ad = maps_adapter(browser, router)
    return stage.run(run_context(segments=["clinics-in"], limit=limit), router=router, adapter=ad)


def test_the_stage_stores_numbers_a_fact_and_review_pain(clean_db: str) -> None:
    bid = queued()
    places = queued(name="Lotus Places Clinic", web_domain="lotus-places.in", places_fetched_at=datetime.now(UTC))
    stats = run_stage(FakeBrowser(), FakeRouter({"classify_reviews": [pain()]}))
    assert stats["looked_up"] == 1 and stats["matched"] == 1 and stats["review_pain"] == 1
    row = db.fetch_one("select review_count, rating, extra from public.businesses where id = %s", [bid])
    assert row is not None and row["review_count"] == 1204 and float(row["rating"]) == 4.6
    assert row["extra"]["reviews_src"] == "maps_reviews" and row["extra"]["maps_reviews"]["how"] == "website"
    fact = db.fetch_one("select * from public.facts where business_id = %s and field = 'google_reviews'", [bid])
    assert fact is not None and fact["verified"] and fact["value"]["source"] == "maps_reviews"
    assert fact["quote"] == "4.6 stars, 1204 reviews on Google Maps"
    sig = db.fetch_one("select * from public.signals where business_id = %s", [bid])
    assert sig is not None and sig["type"] == "review_pain" and sig["source"] == "maps_reviews"
    assert sig["quote"] == "I called six times to reschedule and gave up." and sig["url"] == LISTING["url"]
    assert db.scalar("select review_count from public.businesses where id = %s", [places]) is None  # never looked up
    assert run_stage(FakeBrowser())["candidates"] == 0  # looked up: not again for 30 days


def test_an_unconfirmed_listing_is_recorded_without_numbers(clean_db: str) -> None:
    bid = queued(web_domain="other-clinic.in", website="https://other-clinic.in/")
    stats = run_stage(FakeBrowser())
    assert stats["not_matched"] == 1
    row = db.fetch_one("select review_count, extra from public.businesses where id = %s", [bid])
    assert row is not None and row["review_count"] is None
    assert row["extra"]["maps_reviews"] | {"at": None} == {
        "at": None,
        "matched": False,
        "url": LISTING["url"],
        "why": "listing not confirmed",
    }


def test_a_block_stops_the_stage_and_pauses_the_source(clean_db: str) -> None:
    queued()
    queued(name="Lotus Skin & Hair Clinic Two", web_domain="lotus-two.in")
    stats = run_stage(FakeBrowser(redirect={"search": "https://consent.google.com/ml"}))
    assert stats["blocked"] == 1 and stats.get("looked_up", 0) == 0
    row = db.fetch_one("select blocked_until, last_error from public.source_health where source = 'maps_reviews'")
    assert row is not None and row["blocked_until"] > datetime.now(UTC) + timedelta(hours=23)
    assert "consent wall" in row["last_error"]
    assert run_stage(FakeBrowser())["skipped"].startswith("blocked until")


def test_the_daily_cap_and_the_kill_switch(clean_db: str) -> None:
    for i in range(3):
        queued(name=f"Lotus Skin & Hair Clinic {i}", web_domain=f"lotus-{i}.in")
    db.set_setting("maps_reviews.lookups_per_day", 2)
    assert run_stage(FakeBrowser())["looked_up"] == 2
    assert run_stage(FakeBrowser())["candidates"] == 0  # today's two are used
    flags = db.get_setting("sources_enabled")
    db.set_setting("sources_enabled", {**flags, "maps_reviews": False})
    assert "sources_enabled" in run_stage(FakeBrowser())["skipped"]


def test_repeated_page_failures_stop_the_stage(clean_db: str) -> None:
    for i in range(4):
        queued(name=f"Lotus Skin & Hair Clinic {i}", web_domain=f"lotus-{i}.in")

    class Broken(FakeBrowser):
        async def page(self) -> FakePage:
            raise RuntimeError("Executable doesn't exist: chromium")

    stats = run_stage(Broken())
    assert stats["errors"] == 3 and stats.get("looked_up", 0) == 0
    assert "failed" in str(db.scalar("select last_error from public.source_health where source = 'maps_reviews'"))


# ---- the grounded lookup skips what Maps and Practo covered ------------------------------------------------


def test_the_grounded_lookup_skips_maps_and_asks_practo_less(clean_db: str) -> None:
    now = datetime.now(UTC)
    researched = {"status": "researched", "researched_at": now}
    maps_bid = insert_business(
        name="Covered By Maps",
        review_count=300,
        extra={"maps_reviews": {"at": now.isoformat(), "matched": True}, "reviews_src": "maps_reviews"},
        **researched,
    )
    practo_bid = insert_business(
        name="Covered By Practo", extra={"practo": {"at": now.isoformat(), "url": "x"}}, **researched
    )
    plain_bid = insert_business(name="Not Covered", **researched)
    rows = db.fetch_all(reviews.CANDIDATES_SQL, {"segments": ["clinics-in"], "keep": reviews.KEEP_DAYS, "limit": 50})
    ids = {r["id"] for r in rows}
    assert maps_bid not in {str(i) for i in ids} and {practo_bid, plain_bid} <= {str(i) for i in ids}
    seg = stage.active_segments(["clinics-in"])["clinics-in"]
    by_id = {str(r["id"]): r for r in rows}
    assert reviews._inputs(by_id[practo_bid], seg)["practo"] is False
    assert reviews._inputs(by_id[plain_bid], seg)["practo"] is True


def test_maps_numbers_expire_after_30_days_like_places_content(clean_db: str) -> None:
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    bid = insert_business(
        name="Old Maps Numbers", review_count=50, rating=4.1, extra={"reviews_at": old, "reviews_src": "maps_reviews"}
    )
    with db.tx() as conn:
        assert reviews.expire_old(conn) >= 1
    row = db.fetch_one("select review_count, rating, extra from public.businesses where id = %s", [bid])
    assert row is not None and row["review_count"] is None and "reviews_src" not in row["extra"]
