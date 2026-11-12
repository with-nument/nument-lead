"""Overture places (Step 5.4): STAC release discovery, the DuckDB query and the mapping to records.

The query runs against a 20-row GeoParquet-shaped file written here with the release schema (v2.0.0, checked on
2026-10-21.0), so no test touches S3 and no binary fixture lives in git.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nument_engine.sources.overture import OvertureAdapter, ReleaseFile, release_date

from .sources_helpers import ctx, mock_transport, no_network, segment

__all__ = ["no_network"]

ADDRESS = pa.struct(
    [
        ("freeform", pa.string()),
        ("locality", pa.string()),
        ("postcode", pa.string()),
        ("region", pa.string()),
        ("country", pa.string()),
    ]
)
SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("names", pa.struct([("primary", pa.string())])),
        (
            "taxonomy",
            pa.struct(
                [("primary", pa.string()), ("hierarchy", pa.list_(pa.string())), ("alternates", pa.list_(pa.string()))]
            ),
        ),
        ("websites", pa.list_(pa.string())),
        ("phones", pa.list_(pa.string())),
        ("emails", pa.list_(pa.string())),
        ("socials", pa.list_(pa.string())),
        ("addresses", pa.list_(ADDRESS)),
        ("confidence", pa.float64()),
        ("operating_status", pa.string()),
        (
            "bbox",
            pa.struct([("xmin", pa.float64()), ("xmax", pa.float64()), ("ymin", pa.float64()), ("ymax", pa.float64())]),
        ),
    ]
)
DENTAL = ["health_care", "outpatient_care_facility", "dental_clinic", "general_dentistry"]
SKIN = ["health_care", "outpatient_care_facility", "specialized_health_care", "medical_skin_care", "dermatology"]
HOSPITAL = ["health_care", "hospital"]
PUNE = (73.70, 18.40, 74.05, 18.70)


def place(i: int, name: str, hierarchy: list[str], lng: float, lat: float, **kw: Any) -> dict[str, Any]:
    return {
        "id": f"08f{i:013d}",
        "names": {"primary": name},
        "taxonomy": {"primary": hierarchy[-1], "hierarchy": hierarchy, "alternates": []},
        "websites": kw.get("websites", []),
        "phones": kw.get("phones", []),
        "emails": kw.get("emails", []),
        "socials": kw.get("socials", []),
        "addresses": [
            {
                "freeform": kw.get("address", "Baner Road"),
                "locality": kw.get("locality", "Baner"),
                "postcode": "411045",
                "region": "MH",
                "country": "IN",
            }
        ],
        "confidence": kw.get("confidence", 0.9),
        "operating_status": kw.get("status", "open"),
        "bbox": {"xmin": lng, "xmax": lng, "ymin": lat, "ymax": lat},
    }


ROWS = [
    place(
        1,
        "Smile Dental Studio",
        DENTAL,
        73.78,
        18.56,
        websites=["https://www.smiledental.in/"],
        phones=["+91 98765 43210"],
    ),
    place(2, "Skin Glow Clinic", SKIN, 73.79, 18.55, websites=["https://www.practo.com/pune/clinic/skin-glow"]),
    place(3, "City Hospital", HOSPITAL, 73.80, 18.55),
    place(4, "Low Confidence Dental", DENTAL, 73.80, 18.56, confidence=0.4),
    place(5, "Closed Dental", DENTAL, 73.80, 18.57, status="permanently_closed"),
    place(6, "Mumbai Dental", DENTAL, 72.85, 19.10),
    place(7, "", DENTAL, 73.81, 18.56),
    *[place(10 + i, f"Dental Care {i}", DENTAL, 73.75 + i * 0.01, 18.45 + i * 0.01) for i in range(13)],
]


@pytest.fixture
def parquet(tmp_path: Path) -> str:
    path = tmp_path / "places.parquet"
    pq.write_table(pa.Table.from_pylist(ROWS, schema=SCHEMA), path)
    assert len(ROWS) == 20
    return str(path)


def test_query_filters_box_categories_status_and_confidence(parquet: str) -> None:
    seg = segment()
    rows = OvertureAdapter.query([parquet], PUNE, seg.overture.categories)
    names = {r["name"] for r in rows}
    assert "Smile Dental Studio" in names and "Skin Glow Clinic" in names
    assert "City Hospital" not in names  # category not listed
    assert "Low Confidence Dental" not in names and "Closed Dental" not in names and "Mumbai Dental" not in names
    assert len(rows) == 15  # 2 + 13 generated; a place without a name is skipped
    assert OvertureAdapter.query([parquet], PUNE, seg.overture.categories, limit=3).__len__() == 3
    ids = OvertureAdapter.query([parquet], PUNE, seg.overture.categories, ids_only=True)
    assert set(ids[0]) == {"id", "confidence"}


def test_mapping_to_records(parquet: str) -> None:
    seg = segment()
    rows = {r["name"]: r for r in OvertureAdapter.query([parquet], PUNE, seg.overture.categories)}
    rec = OvertureAdapter.to_record(rows["Smile Dental Studio"], seg, "Pune", "2026-10-21.0")
    assert rec is not None
    assert rec.source == "overture" and rec.source_key == rec.overture_id == "08f0000000000001"
    assert rec.website == "https://smiledental.in/"
    assert rec.phones_raw == ["+91 98765 43210"] and not rec.phones_are_listing  # a hint only (A.4.3)
    assert rec.category == "dental_clinic" and rec.subcategory == "dental"
    assert rec.city == "Pune" and rec.locality == "Baner"
    assert rec.lat == pytest.approx(18.56) and rec.lng == pytest.approx(73.78)
    assert rec.payload["release"] == "2026-10-21.0" and rec.payload["confidence"] == 0.9
    skin = OvertureAdapter.to_record(rows["Skin Glow Clinic"], seg, "Pune", "2026-10-21.0")
    assert skin is not None and skin.website is None  # a Practo page is not their own site
    assert skin.category == "dermatology" and skin.subcategory == "dermatology"
    nameless = {**rows["Smile Dental Studio"], "name": ""}
    assert OvertureAdapter.to_record(nameless, seg, "Pune", "2026-10-21.0") is None


def test_segment_code_picks_the_most_specific_listed_level() -> None:
    codes = ["dental_clinic", "dermatology", "medical_skin_care"]
    assert OvertureAdapter.segment_code(DENTAL, codes) == "dental_clinic"
    assert OvertureAdapter.segment_code(SKIN, codes) == "dermatology"
    assert OvertureAdapter.segment_code(HOSPITAL, codes) is None


def test_release_date() -> None:
    assert release_date("2026-10-21.0").isoformat() == "2026-10-21T00:00:00+00:00"


STAC = {
    "latest": "2026-10-21.0",
    "links": [
        {"rel": "child", "href": "https://stac.overturemaps.org/2026-09-23.1/catalog.json"},
        {"rel": "child", "href": "https://stac.overturemaps.org/2026-10-21.0/catalog.json", "latest": True},
    ],
}
COLLECTION = {
    "links": [
        {"rel": "item", "href": "https://stac.overturemaps.org/2026-10-21.0/places/place/00012/00012.json"},
        {"rel": "item", "href": "https://stac.overturemaps.org/2026-10-21.0/places/place/00014/00014.json"},
    ]
}


def item(n: str, bbox: list[float]) -> dict[str, Any]:
    s3 = f"s3://overturemaps-us-west-2/release/2026-10-21.0/theme=places/type=place/part-{n}.zstd.parquet"
    return {"bbox": bbox, "assets": {"aws": {"href": f"https://x/{n}", "alternate": {"s3": {"href": s3}}}}}


async def test_release_discovery_from_stac() -> None:
    routes = {
        "https://stac.overturemaps.org/catalog.json": (200, STAC),
        "https://stac.overturemaps.org/2026-10-21.0/places/place/collection.json": (200, COLLECTION),
        "https://stac.overturemaps.org/2026-10-21.0/places/place/00012/00012.json": (
            200,
            item("00012", [35.85, -84.98, 106.46, 18.79]),
        ),
        "https://stac.overturemaps.org/2026-10-21.0/places/place/00014/00014.json": (
            200,
            item("00014", [35.85, 18.79, 104.27, 81.84]),
        ),
    }
    transport, seen = mock_transport(routes)
    async with OvertureAdapter(ctx(), transport=transport) as ov:
        assert await ov.latest_release() == "2026-10-21.0"
        assert await ov.releases() == ["2026-09-23.1", "2026-10-21.0"]
        pune = await ov.release_files("2026-10-21.0", PUNE)
        delhi = await ov.release_files("2026-10-21.0", (76.84, 28.40, 77.35, 28.88))
    assert [f.href.rsplit("/", 1)[-1] for f in pune] == ["part-00012.zstd.parquet"]
    assert [f.href.rsplit("/", 1)[-1] for f in delhi] == ["part-00014.zstd.parquet"]
    assert sum(1 for r in seen if "collection.json" in str(r.url)) == 1  # file list cached per release


async def test_pull_maps_every_city(parquet: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seg = segment()

    async def files(self: OvertureAdapter, release: str, bbox: Any = None) -> list[ReleaseFile]:
        return [ReleaseFile(parquet, PUNE)]

    monkeypatch.setattr(OvertureAdapter, "release_files", files)
    async with OvertureAdapter(ctx()) as ov:
        records = await ov.pull(seg, "2026-10-21.0", cities=["Pune"])
        limited = await ov.pull(seg, "2026-10-21.0", cities=["Pune"], limit=5)
        ids = await ov.ids(seg, "2026-10-21.0")
    assert len(records) == 15 and all(r.city == "Pune" for r in records)
    assert len(limited) == 5
    assert ids is not None and "08f0000000000001" in ids
