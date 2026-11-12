"""ART registry (Step 5.6) and OpenStreetMap gaps (Step 5.12)."""

from __future__ import annotations

import pytest

from nument_engine.sources.art_registry import ArtRegistryAdapter, RegistryFormatChanged, parse_rows
from nument_engine.sources.osm import OsmAdapter, build_query, code_for, tiles

from .sources_helpers import ctx, fixture_json, fixture_text, mock_transport, no_network, segment

__all__ = ["no_network"]

ART_URL = "https://registry.artsurrogacy.gov.in/clinic/list?type=register-clinic"


def test_registry_rows_are_parsed_and_emails_decoded() -> None:
    rows = parse_rows(fixture_text("art_registry", "list.html"))
    assert len(rows) == 7
    lotus = rows[1]
    assert lotus["name"] == "Lotus IVF Clinic"
    assert lotus["email"] == "lotus@lotusivf-nlead.in"
    assert lotus["registration_no"] == "MH/AC/2023/20002/L2/02"
    assert lotus["certificate_url"] == (
        "https://registry.artsurrogacy.gov.in/webprodfiles/clinic_registration_certificate/1002/certificate_2.pdf"
    )
    assert rows[3]["email"] is None  # blank cell


def test_only_rows_in_segment_cities_become_records() -> None:
    seg = segment()
    rows = parse_rows(fixture_text("art_registry", "list.html"))
    records = ArtRegistryAdapter.to_records(rows, seg, "ivf_fertility")
    by_name = {r.name: r for r in records}
    assert set(by_name) == {
        "Lotus IVF Clinic",
        "Navi Hope Fertility",
        "Andheri Women's Clinic",
        "Green Valley Hospital IVF",
        "Banjara Fertility Institute",
    }  # Kolkata and Narasaraopet are outside the segment's cities
    assert by_name["Navi Hope Fertility"].city == "Thane and Navi Mumbai"  # not Mumbai
    assert by_name["Green Valley Hospital IVF"].city == "Gurugram"
    lotus = by_name["Lotus IVF Clinic"]
    assert lotus.city == "Pune" and lotus.locality == "Baner"
    assert lotus.source == "art_registry" and lotus.source_key == "MH/AC/2023/20002/L2/02"
    assert lotus.subcategory == "ivf_fertility" and lotus.category == "fertility_clinic"  # A.13.5 rule 7
    assert lotus.emails == ["lotus@lotusivf-nlead.in"] and lotus.emails_are_registry
    assert lotus.phones_raw == []  # the registry has no phones
    assert lotus.payload["email"] == "lotus@lotusivf-nlead.in"


def test_a_changed_page_fails_loudly() -> None:
    with pytest.raises(RegistryFormatChanged):
        parse_rows("<html><body><p>Under maintenance</p></body></html>")
    with pytest.raises(RegistryFormatChanged):
        parse_rows("<table><thead><tr><th>Foo</th><th>Bar</th></tr></thead><tbody></tbody></table>")


async def test_pull_fetches_once_and_maps() -> None:
    transport, seen = mock_transport(
        {
            "https://registry.artsurrogacy.gov.in/robots.txt": (404, "not found"),
            "https://registry.artsurrogacy.gov.in/clinic/list": (200, fixture_text("art_registry", "list.html")),
        }
    )
    context = ctx()
    async with ArtRegistryAdapter(context, transport=transport) as art:
        records = await art.pull(segment())
    assert len(records) == 5 and context.stats["art_registry.rows"] == 7
    assert [r.url.path for r in seen] == ["/robots.txt", "/clinic/list"]


def test_overpass_query_and_tiles() -> None:
    q = build_query(['["amenity"="dentist"]', '["amenity"="clinic"]'], (73.7, 18.4, 73.95, 18.65))
    assert q == (
        '[out:json][timeout:90];(nwr["amenity"="dentist"](18.4,73.7,18.65,73.95);'
        'nwr["amenity"="clinic"](18.4,73.7,18.65,73.95););out center tags;'
    )
    grid = tiles((76.84, 28.40, 77.35, 28.88))
    assert len(grid) == 6 and all(b[2] - b[0] <= 0.25 + 1e-9 and b[3] - b[1] <= 0.25 + 1e-9 for b in grid)
    assert grid[0][:2] == (76.84, 28.40) and grid[-1][2:] == (77.35, 28.88)


def test_osm_mapping() -> None:
    seg = segment()
    city = seg.cities[[c.name for c in seg.cities].index("Pune")]
    elements = fixture_json("osm", "overpass.json")["elements"]
    dentist = OsmAdapter.to_record(elements[0], seg, city)
    assert dentist is not None
    assert dentist.source_key == "node/101" and dentist.category == "dental_clinic" and dentist.subcategory == "dental"
    assert dentist.website == "https://brightsmile-nlead.in/" and dentist.phones_raw == ["+91 20 2551 1111"]
    assert dentist.lat == 18.56 and dentist.locality == "Baner"
    derma = OsmAdapter.to_record(elements[1], seg, city)
    assert derma is not None and derma.source_key == "way/202" and derma.lat == 18.52
    assert derma.category == "dermatology"
    assert OsmAdapter.to_record(elements[2], seg, city) is None  # no name
    assert code_for({"amenity": "dentist"}) == "dental_clinic"
    assert code_for({"shop": "bakery"}) is None


async def test_osm_pull_reads_each_tile(monkeypatch: pytest.MonkeyPatch) -> None:
    seg = segment()
    seg = seg.model_copy(update={"cities": [c for c in seg.cities if c.name == "Pune"]})
    transport, seen = mock_transport(
        {"https://overpass-api.de/api/interpreter": (200, fixture_json("osm", "overpass.json"))}
    )
    monkeypatch.setattr(OsmAdapter, "min_gap_s", 0.0)
    async with OsmAdapter(ctx(), transport=transport) as osm:
        records = await osm.pull(seg)
    assert len(seen) == 4  # Pune's box is split into 4 tiles
    assert {r.source_key for r in records} == {"node/101", "way/202"}  # duplicates across tiles removed
