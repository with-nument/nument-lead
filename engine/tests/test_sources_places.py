"""Google Places API (New) adapter (Step 5.5): no-key skip, ID search, details, caps, errors, storage rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from nument_engine import db
from nument_engine.settings import get_settings
from nument_engine.sources import health
from nument_engine.sources.places import (
    PlacesAdapter,
    PlacesApiError,
    QuotaReached,
    Review,
    cleanup_expired,
    listing_url,
    review_flags,
)

from .sources_helpers import clean_db, ctx, fixture_json, insert_business, mock_transport, no_network, segment

__all__ = ["clean_db", "no_network"]

PUNE = (73.70, 18.40, 74.05, 18.70)


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "google_maps_api_key", SecretStr("test-key"))


def test_without_a_key_places_is_skipped_with_a_clear_message(clean_db: str) -> None:
    places = PlacesAdapter(ctx())
    usable, why = places.status()
    assert not usable and "GOOGLE_MAPS_API_KEY is not set" in why
    places.report_missing_key()
    places.report_missing_key()  # once per run
    row = db.fetch_one("select last_error, blocked_until from public.source_health where source = 'places'")
    assert row is not None and "GOOGLE_MAPS_API_KEY" in row["last_error"] and row["blocked_until"] is None


async def test_search_ids_pages_through_and_sends_only_the_id_field_mask(clean_db: str, with_key: None) -> None:
    pages = iter([fixture_json("places", "search_page1.json"), fixture_json("places", "search_page2.json")])
    bodies: list[dict[str, object]] = []

    def search(request: httpx.Request) -> httpx.Response:
        import json

        bodies.append(json.loads(request.content))
        assert request.headers["x-goog-fieldmask"] == "places.id,nextPageToken"
        assert request.headers["x-goog-api-key"] == "test-key"
        return httpx.Response(200, json=next(pages))

    transport, seen = mock_transport({"https://places.googleapis.com/v1/places:searchText": search})
    async with PlacesAdapter(ctx(), transport=transport) as places:
        ids = await places.search_ids("dermatology clinic in Baner, Pune", segment(), PUNE)
    assert len(ids) == 25 and ids[0] == "ChIJpage1_0"
    assert bodies[0]["locationRestriction"] == {
        "rectangle": {"low": {"latitude": 18.40, "longitude": 73.70}, "high": {"latitude": 18.70, "longitude": 74.05}}
    }
    assert "pageToken" not in bodies[0] and bodies[1]["pageToken"] == "TOKEN2"
    assert bodies[0]["regionCode"] == "IN"
    assert all(r.url.host == "places.googleapis.com" for r in seen)  # no robots.txt for official APIs
    assert health.calls_today("google_places", "places_text_search", model="in") == 2


async def test_details_maps_to_a_listing_record(clean_db: str, with_key: None) -> None:
    transport, seen = mock_transport(
        {"https://places.googleapis.com/v1/places/ChIJlotus": (200, fixture_json("places", "details.json"))}
    )
    seg = segment()
    async with PlacesAdapter(ctx(), transport=transport) as places:
        data = await places.details("ChIJlotus", seg)
    assert "nationalPhoneNumber" in seen[0].headers["x-goog-fieldmask"]
    rec = PlacesAdapter.to_record(data, seg, "Pune")
    assert rec is not None
    assert rec.place_id == rec.source_key == "ChIJlotus"
    assert rec.name == "Lotus Skin & Hair Clinic" and rec.locality == "Baner"
    assert rec.website == "https://lotusskin-nlead.in/"
    assert rec.phones_raw == ["+91 98765 43210"] and rec.phones_are_listing
    assert rec.rating == 4.6 and rec.review_count == 312 and rec.subcategory == "dermatology"
    assert rec.business_status == "OPERATIONAL"
    assert health.calls_today("google_places", "places_details", model="in") == 1


async def test_the_231st_details_call_of_the_day_is_refused(clean_db: str, with_key: None) -> None:
    """Step 5.16 test 6: India cap 230 a day."""
    seg = segment(places=segment().places.model_copy(update={"details_per_day": 230}))
    db.execute(
        "insert into public.costs (provider, model, task, calls) values ('google_places', 'in', 'places_details', 230)"
    )
    transport, seen = mock_transport({"*": (200, fixture_json("places", "details.json"))})
    async with PlacesAdapter(ctx(), transport=transport) as places:
        assert places.details_left(seg) == 0
        with pytest.raises(QuotaReached):
            await places.details("ChIJlotus", seg)
    assert seen == []


async def test_the_segment_cap_applies_inside_a_run(clean_db: str, with_key: None) -> None:
    seg = segment(places=segment().places.model_copy(update={"details_per_day": 2}))
    transport, _ = mock_transport({"*": (200, fixture_json("places", "details.json"))})
    async with PlacesAdapter(ctx(), transport=transport) as places:
        await places.details("a", seg)
        await places.details("b", seg)
        with pytest.raises(QuotaReached):
            await places.details("c", seg)


@pytest.mark.parametrize(
    ("fixture", "status", "paused", "raises"),
    [("error_403.json", 403, True, False), ("error_429.json", 429, True, False), ("error_400.json", 400, False, True)],
)
async def test_api_errors(clean_db: str, with_key: None, fixture: str, status: int, paused: bool, raises: bool) -> None:
    transport, _ = mock_transport({"*": (status, fixture_json("places", fixture))})
    context = ctx()
    async with PlacesAdapter(context, transport=transport) as places:
        with pytest.raises(PlacesApiError) as err:
            await places.details("x", segment())
        if raises:
            with pytest.raises(PlacesApiError):
                places.handle_api_error(err.value)
            return
        places.handle_api_error(err.value)
    row = db.fetch_one("select blocked_until, last_error from public.source_health where source = 'places'")
    assert row is not None and (row["blocked_until"] is not None) is paused
    assert context.alerts


async def test_reviews_are_reduced_to_flags_without_text(clean_db: str, with_key: None) -> None:
    transport, _ = mock_transport({"*": (200, fixture_json("places", "reviews.json"))})
    async with PlacesAdapter(ctx(), transport=transport) as places:
        reviews = await places.reviews("ChIJlotus", segment())
    found = review_flags(reviews, now=datetime(2026, 11, 12, tzinfo=UTC))
    assert found == {
        "flags": ["long_wait", "unanswered_calls"],
        "matching_reviews": 2,
        "of_reviews": 3,
        "newest_flag_age_days": 10,
    }
    assert "picks up" not in str(found)  # nothing of the review text survives


def test_old_or_unrelated_reviews_make_no_signal() -> None:
    now = datetime(2026, 11, 12, tzinfo=UTC)
    old = Review("Nobody picks up the phone", 1, now - timedelta(days=200))
    happy = Review("Lovely staff, quick appointment", 5, now - timedelta(days=3))
    assert review_flags([old, happy], now=now) is None


def test_listing_url() -> None:
    assert listing_url("ChIJx") == "https://www.google.com/maps/place/?q=place_id:ChIJx"


def test_thirty_day_cleanup_keeps_only_the_place_id(clean_db: str) -> None:
    """Step 5.16 test 7 and A.4.4."""
    old = datetime.now(UTC) - timedelta(days=31)
    stale = insert_business(
        name="Stale Listing Clinic",
        place_id="ChIJstale-x1",
        rating=4.4,
        review_count=120,
        places_fetched_at=old,
        lat=18.5,
        lng=73.8,
        extra={"src": {"geo": "places"}},
    )
    fresh = insert_business(
        name="Fresh Listing Clinic",
        place_id="ChIJfresh-x1",
        rating=4.1,
        review_count=80,
        places_fetched_at=datetime.now(UTC),
    )
    db.execute(
        "insert into public.contacts (business_id, phone_e164, phone_type, source, verified, verified_at) "
        "values (%s, '+919800011122', 'mobile', 'google_listing', true, %s)",
        [stale, old],
    )
    db.execute(
        "insert into public.source_records (source, source_key, business_id, payload, fetched_at) "
        "values ('places', 'ChIJstale-x1', %s, %s, %s)",
        [stale, db.Jsonb({"nationalPhoneNumber": "098000 11122", "primary_type": "dentist"}), old],
    )
    out = cleanup_expired()
    assert out["places_content_cleared"] >= 1 and out["listing_phones_deleted"] >= 1
    row = db.fetch_one(
        "select place_id, rating, review_count, lat, extra from public.businesses where id = %s", [stale]
    )
    assert row is not None
    assert row["place_id"] == "ChIJstale-x1" and row["rating"] is None and row["review_count"] is None
    assert row["lat"] is None and "geo" not in row["extra"]["src"]
    assert db.scalar("select count(*) from public.contacts where business_id = %s", [stale]) == 0
    payload = db.scalar("select payload from public.source_records where source_key = 'ChIJstale-x1'")
    assert payload == {"primary_type": "dentist"}
    kept = db.fetch_one("select rating from public.businesses where id = %s", [fresh])
    assert kept is not None and float(kept["rating"]) == 4.1
