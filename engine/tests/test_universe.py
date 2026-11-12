"""The universe stage (Step 6.7): locality rotation, the monthly Overture diff with new_place signals, registries,
the daily Places part (with and without a key) and the targeted lookup of signal-born businesses."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from nument_engine import db
from nument_engine.pipeline import universe
from nument_engine.settings import get_settings
from nument_engine.sources.art_registry import ArtRegistryAdapter
from nument_engine.sources.base import SourceRecord
from nument_engine.sources.osm import OsmAdapter
from nument_engine.sources.overture import OvertureAdapter
from nument_engine.sources.places import PlacesAdapter

from .sources_helpers import clean_db, fixture_json, insert_business, mock_transport, no_network, run_context, segment

__all__ = ["clean_db", "no_network"]

SEG = segment()


def test_every_locality_is_searched_once_in_14_days() -> None:
    pairs = [(c.name, loc) for c in SEG.cities for loc in c.localities]
    seen = [(c.name, loc) for day in range(14) for c, loc in universe.locality_slice(SEG, day)]
    assert sorted(seen) == sorted(pairs)
    assert universe.locality_slice(SEG, 0) == universe.locality_slice(SEG, 14)


def test_city_wide_queries_run_once_per_rotation() -> None:
    seg = segment("realestate-in")
    city = seg.cities[0]
    first = universe.search_queries(seg, [(city, city.localities[0])])
    later = universe.search_queries(seg, [(city, city.localities[1])])
    assert any("{" not in q and city.localities[0] not in q for q, _ in first)  # "developer in {city}"
    assert all(city.localities[1] in q for q, _ in later)


def record(i: int, name: str, conf: float = 0.9) -> SourceRecord:
    return SourceRecord(
        source="overture",
        source_key=f"ov-u{i}",
        segment_id=SEG.id,
        name=name,
        city="Pune",
        locality="Baner",
        lat=18.45 + i * 0.01,
        lng=73.75,
        category="dermatology",
        subcategory="dermatology",
        overture_id=f"ov-u{i}",
        website=f"https://universe{i}-nlead.in/",
        payload={"release": "2026-10-21.0", "confidence": conf},
    )


@pytest.fixture
def fake_month(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"pulls": 0}

    async def latest(self: OvertureAdapter) -> str:
        return "2026-10-21.0"

    async def releases(self: OvertureAdapter) -> list[str]:
        return ["2026-09-23.1", "2026-10-21.0"]

    async def pull(self: OvertureAdapter, seg: Any, release: str, **kw: Any) -> list[SourceRecord]:
        state["pulls"] += 1
        return [record(1, "Old Skin Clinic"), record(2, "Brand New Skin Clinic"), record(3, "Unsure New Clinic", 0.65)]

    async def ids(self: OvertureAdapter, seg: Any, release: str, **kw: Any) -> set[str]:
        return {"ov-u1"}

    async def art(self: ArtRegistryAdapter, seg: Any, **kw: Any) -> list[SourceRecord]:
        return [
            SourceRecord(
                source="art_registry",
                source_key="MH/AC/U1",
                segment_id=SEG.id,
                name="Registry IVF Centre",
                city="Pune",
                category="fertility_clinic",
                subcategory="ivf_fertility",
                emails=["ivf@registryivf-nlead.in"],
                emails_are_registry=True,
            )
        ]

    async def osm(self: OsmAdapter, seg: Any, **kw: Any) -> list[SourceRecord]:
        return []

    monkeypatch.setattr(OvertureAdapter, "latest_release", latest)
    monkeypatch.setattr(OvertureAdapter, "releases", releases)
    monkeypatch.setattr(OvertureAdapter, "pull", pull)
    monkeypatch.setattr(OvertureAdapter, "ids", ids)
    monkeypatch.setattr(ArtRegistryAdapter, "pull", art)
    monkeypatch.setattr(OsmAdapter, "pull", osm)
    return state


def test_monthly_build_with_the_release_diff(clean_db: str, fake_month: dict[str, Any]) -> None:
    db.set_setting("overture_release", "2026-09-23.1")
    rc = run_context(segments=["clinics-in"])
    stats = universe.run(rc, monthly=True)
    s = stats["clinics-in"]
    assert s["overture_created"] == 3 and s["registry_created"] == 1
    assert stats["overture_release"] == "2026-10-21.0" and db.get_setting("overture_release") == "2026-10-21.0"
    new_places = db.fetch_all(
        "select b.name, s.observed_at, s.quote from public.signals s join public.businesses b on b.id = s.business_id "
        "where s.type = 'new_place'"
    )
    assert [r["name"] for r in new_places] == ["Brand New Skin Clinic"]  # in the old release, or not sure enough
    assert new_places[0]["observed_at"].date().isoformat() == "2026-10-21"
    assert "New in Overture release 2026-10-21.0" in new_places[0]["quote"]
    email = db.scalar(
        "select c.email from public.contacts c join public.businesses b on b.id = c.business_id "
        "where b.name = 'Registry IVF Centre'"
    )
    assert email == "ivf@registryivf-nlead.in"
    again = universe.run(run_context(segments=["clinics-in"]), monthly=True)
    assert again["clinics-in"]["overture_already_done"] == 1 and fake_month["pulls"] == 1


def test_first_month_makes_no_new_place_signals(clean_db: str, fake_month: dict[str, Any]) -> None:
    db.set_setting("overture_release", None)
    universe.run(run_context(segments=["clinics-in"]), monthly=True)
    assert db.scalar("select count(*) from public.signals where type = 'new_place'") == 0


def test_daily_part_without_a_key_is_skipped_and_explained(clean_db: str) -> None:
    rc = run_context(segments=["clinics-in"])
    stats = universe.run(rc)
    assert stats["clinics-in"]["places_skipped"] == 1
    assert "GOOGLE_MAPS_API_KEY" in stats["skip_reasons"]["places"]
    assert "GOOGLE_MAPS_API_KEY" in db.scalar("select last_error from public.source_health where source = 'places'")


def test_daily_part_with_a_key(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "google_maps_api_key", SecretStr("test-key"))
    details = fixture_json("places", "details.json")
    born = insert_business(
        name="Lotus Skin & Hair Clinic", city="Pune", locality="Baner", extra={"born_from": "apna"}, status="candidate"
    )
    searches: list[str] = []

    def search(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        searches.append(body["textQuery"])
        if body["textQuery"].startswith("Lotus Skin"):
            return httpx.Response(200, json={"places": [{"id": "ChIJlotus"}]})
        return httpx.Response(200, json={"places": [{"id": "ChIJnew-1"}]})

    def place(request: httpx.Request) -> httpx.Response:
        pid = request.url.path.rsplit("/", 1)[-1]
        data = {**details, "id": pid}
        if pid == "ChIJnew-1":
            data.update(
                displayName={"text": "New Dental Studio"},
                websiteUri="https://newdental-nlead.in/",
                location={"latitude": 18.52, "longitude": 73.85},
                primaryType="dentist",
                internationalPhoneNumber="+91 98111 22233",
            )
        return httpx.Response(200, json=data)

    transport, _ = mock_transport({"https://places.googleapis.com/v1/places:searchText": search, "*": place})
    real = PlacesAdapter.__init__

    def init(self: PlacesAdapter, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real(self, *args, **kwargs)

    monkeypatch.setattr(PlacesAdapter, "__init__", init)
    monkeypatch.setattr(PlacesAdapter, "min_gap_s", 0.0)
    monkeypatch.setattr(universe, "locality_slice", lambda seg, day=None: [(seg.cities[-2], "Baner")])
    stats = universe.run(run_context(segments=["clinics-in"]))
    s = stats["clinics-in"]
    assert s["signal_born_found"] == 1 and s["places_new_ids"] == 1 and s["places_details"] == 2
    found = db.fetch_one("select place_id, website, review_count from public.businesses where id = %s", [born])
    assert found == {"place_id": "ChIJlotus", "website": "https://lotusskin-nlead.in/", "review_count": 312}
    new = db.fetch_one("select id::text, name, city from public.businesses where place_id = 'ChIJnew-1'")
    assert new is not None and new["name"] == "New Dental Studio" and new["city"] == "Pune"
    contact = db.fetch_one(
        "select phone_e164, source, verified from public.contacts where business_id = %s", [new["id"]]
    )
    assert contact == {"phone_e164": "+919811122233", "source": "google_listing", "verified": True}
    assert db.scalar("select extra ? 'places_lookup_at' from public.businesses where id = %s", [born])
    assert any(q.startswith("Lotus Skin & Hair Clinic Baner Pune") for q in searches)


def test_a_limited_monthly_run_never_marks_the_release_done(clean_db: str, fake_month: dict[str, Any]) -> None:
    """A small test run (--limit) must not make the next full monthly run skip the segment or move the baseline."""
    db.set_setting("overture_release", "2026-09-23.1")
    db.set_setting(universe.OVERTURE_DONE_KEY, {})
    limited = universe.run(run_context(segments=["clinics-in"], limit=2), monthly=True)
    assert limited["clinics-in"]["overture_partial_not_marked"] == 1
    assert "dormant" not in limited["clinics-in"]
    assert db.get_setting("overture_release") == "2026-09-23.1"
    assert db.get_setting(universe.OVERTURE_DONE_KEY) == {}
    full = universe.run(run_context(segments=["clinics-in"]), monthly=True)
    assert "overture_already_done" not in full["clinics-in"] and fake_month["pulls"] == 2
    assert db.get_setting(universe.OVERTURE_DONE_KEY) == {"clinics-in": "2026-10-21.0"}
    assert db.get_setting("overture_release") == "2026-10-21.0"
