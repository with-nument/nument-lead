"""OpenStreetMap gap filling through the Overpass API (Step 5.12). Low trust, monthly, only where `osm.enabled`.

Overpass is a public API with its own usage policy (about 10,000 requests a day per user is tolerated). Its
robots.txt disallows `/api/` to keep crawlers from indexing query URLs; like the other official APIs we call it
directly, within the policy: a few requests per city per month, 10 seconds apart, on boxes of at most 0.25
degrees. Website and phone tags are hints only, like Overture's (A.4.3). OSM data is ODbL licensed; we keep
only the element id and a few tags in `source_records.payload`.
"""

from __future__ import annotations

from typing import Any

from ..normalize import homepage, is_ignored_host
from ..segments import City, Segment
from .base import SourceAdapter, SourceRecord

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Tag filters per domain (Step 5.12). Each entry is an Overpass filter on nodes, ways and relations.
DOMAIN_FILTERS: dict[str, list[str]] = {
    "clinics": [
        '["amenity"="dentist"]',
        '["amenity"="clinic"]',
        '["amenity"="doctors"]',
        '["healthcare"~"^(dentist|clinic|doctor|physiotherapist|psychotherapist|counselling|centre)$"]',
    ],
    "realestate": ['["office"="estate_agent"]', '["shop"="estate_agent"]'],
    "education": [
        '["amenity"="language_school"]',
        '["amenity"="training"]',
        '["office"="educational_institution"]',
        '["amenity"="college"]',
    ],
}

# OSM tags to the closest Overture taxonomy code, so rule R2 and the subcategory logic work the same way.
TAG_TO_CODE: tuple[tuple[str, str, str], ...] = (
    ("healthcare:speciality", "dermatology", "dermatology"),
    ("healthcare:speciality", "fertility", "fertility_clinic"),
    ("healthcare:speciality", "physiotherapy", "physical_therapy"),
    ("healthcare", "dentist", "dental_clinic"),
    ("amenity", "dentist", "dental_clinic"),
    ("healthcare", "physiotherapist", "physical_therapy"),
    ("healthcare", "psychotherapist", "psychotherapy"),
    ("healthcare", "counselling", "counseling"),
    ("office", "estate_agent", "real_estate_agent"),
    ("shop", "estate_agent", "real_estate_agent"),
    ("amenity", "language_school", "language_school"),
    ("office", "educational_institution", "educational_service"),
    ("amenity", "training", "vocational_and_technical_school"),
)


TILE_DEG = 0.25  # "small bboxes only" (Step 5.12): city boxes are split into tiles of at most this size


def tiles(bbox: tuple[float, float, float, float], size: float = TILE_DEG) -> list[tuple[float, float, float, float]]:
    """Split a box into a grid of boxes no larger than `size` degrees a side."""
    min_lng, min_lat, max_lng, max_lat = bbox
    cols = max(1, int(-(-(max_lng - min_lng) // size)))
    rows = max(1, int(-(-(max_lat - min_lat) // size)))
    w, h = (max_lng - min_lng) / cols, (max_lat - min_lat) / rows
    return [
        (min_lng + i * w, min_lat + j * h, min_lng + (i + 1) * w, min_lat + (j + 1) * h)
        for j in range(rows)
        for i in range(cols)
    ]


def build_query(filters: list[str], bbox: tuple[float, float, float, float], timeout_s: int = 90) -> str:
    """An Overpass QL query for every element matching any filter inside the city box."""
    min_lng, min_lat, max_lng, max_lat = bbox
    box = f"({min_lat},{min_lng},{max_lat},{max_lng})"  # Overpass order: south, west, north, east
    parts = "".join(f"nwr{f}{box};" for f in filters)
    return f"[out:json][timeout:{timeout_s}];({parts});out center tags;"


def code_for(tags: dict[str, str]) -> str | None:
    for key, value, code in TAG_TO_CODE:
        if value in (tags.get(key) or "").split(";"):
            return code
    return None


class OsmAdapter(SourceAdapter):
    name = "osm"
    policy = "open_data"
    min_gap_s = 10.0  # Overpass: at most one request every 10 seconds

    @staticmethod
    def to_record(element: dict[str, Any], seg: Segment, city: City) -> SourceRecord | None:
        tags: dict[str, str] = element.get("tags") or {}
        name = (tags.get("name:en") or tags.get("name") or "").strip()
        if not name:
            return None
        lat = element.get("lat", (element.get("center") or {}).get("lat"))
        lng = element.get("lon", (element.get("center") or {}).get("lon"))
        website = tags.get("website") or tags.get("contact:website")
        code = code_for(tags) or (seg.fit.categories[0] if seg.fit.categories else None)
        street = ", ".join(
            v for v in (tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:suburb")) if v
        )
        return SourceRecord(
            source="osm",
            source_key=f"{element.get('type')}/{element.get('id')}",
            segment_id=seg.id,
            name=name,
            website=homepage(website) if website and not is_ignored_host(website) else None,
            phones_raw=[p for p in (tags.get("phone"), tags.get("contact:phone")) if p][:2],  # hints only
            address=street or None,
            city=city.name,
            locality=tags.get("addr:suburb"),
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
            category=code,
            subcategory=seg.subcategory_for(code, name),
            payload={"tags": {k: tags[k] for k in ("amenity", "healthcare", "office", "shop") if k in tags}},
        )

    async def pull(self, seg: Segment, *, limit: int | None = None) -> list[SourceRecord]:
        filters = DOMAIN_FILTERS.get(seg.domain)
        if not filters or not seg.osm.enabled:
            return []
        out: list[SourceRecord] = []
        seen: set[str] = set()
        for city in seg.cities:
            for box in tiles(city.bbox):
                res = await self.http.get(OVERPASS_URL, params={"data": build_query(filters, box)}, check_robots=False)
                if not res.ok:
                    self.ctx.add("osm.tile_errors")
                    continue
                for element in res.json().get("elements", []):
                    rec = self.to_record(element, seg, city)
                    if rec is not None and rec.source_key not in seen:
                        seen.add(rec.source_key)
                        out.append(rec)
                if limit and len(out) >= limit:
                    return out[:limit]
        return out
