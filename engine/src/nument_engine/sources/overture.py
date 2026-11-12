"""Overture Maps places: the free world map of businesses (Step 5.4). Open data, CDLA Permissive 2.0 / Apache 2.0.

The release id is read from the STAC catalog (`https://stac.overturemaps.org/catalog.json`), never hard-coded,
because the S3 bucket keeps only about two releases. The catalog also lists every GeoParquet file of the places
theme with its bounding box, so a city query reads only the one or two files that cover the city, and inside them
DuckDB skips row groups by the `bbox` column statistics.

Schema checked against release 2026-10-21.0 (schema v2.0.0): `names.primary`, `taxonomy.primary`,
`taxonomy.hierarchy`, `addresses[].{freeform, locality, region, postcode, country}`, `websites`, `phones`,
`emails`, `socials`, `confidence`, `operating_status`, `bbox.{xmin, xmax, ymin, ymax}`. The old `categories`
column no longer exists. Every column we read is listed in `COLUMNS`, so a schema change fails in one place.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import duckdb

from ..normalize import homepage, is_ignored_host
from ..segments import Segment
from .base import SourceAdapter, SourceRecord

STAC_ROOT = "https://stac.overturemaps.org/catalog.json"
S3_GLOB = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
S3_REGION = "us-west-2"
MIN_CONFIDENCE = 0.6  # Step 6.7.3; verify against India data in week 1
NEW_PLACE_MIN_CONFIDENCE = 0.7  # Step 5.4.5

# The only columns we read (Step 5.17 pitfall: pin the column list in one place).
COLUMNS = (
    "id",
    "names.primary AS name",
    "taxonomy.primary AS category",
    "taxonomy.hierarchy AS hierarchy",
    "websites",
    "phones",
    "emails",
    "socials",
    "addresses",
    "confidence",
    "operating_status",
    "bbox",  # the whole struct: projecting bbox.xmin with ORDER BY + LIMIT trips a DuckDB 2.0 internal error
)


def smallest_city(seg: Segment, lat: float, lng: float) -> str | None:
    """The segment city whose box contains the point; the smallest box wins where boxes overlap."""
    best: tuple[float, str] | None = None
    for c in seg.cities:
        min_lng, min_lat, max_lng, max_lat = c.bbox
        if min_lng <= lng <= max_lng and min_lat <= lat <= max_lat:
            area = (max_lng - min_lng) * (max_lat - min_lat)
            if best is None or area < best[0]:
                best = (area, c.name)
    return best[1] if best else None


@dataclass(frozen=True)
class ReleaseFile:
    href: str  # s3:// URL of one GeoParquet file
    bbox: tuple[float, float, float, float]  # min_lng, min_lat, max_lng, max_lat


def _intersects(a: Sequence[float], b: Sequence[float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def release_date(release: str) -> datetime:
    """`2026-10-21.0` to its date (midnight UTC): the observed date of a new_place signal (Step 7.5.8)."""
    return datetime.strptime(release.split(".", 1)[0], "%Y-%m-%d").replace(tzinfo=UTC)


class OvertureAdapter(SourceAdapter):
    name = "overture"
    policy = "open_data"
    min_gap_s = 0.5  # STAC catalog files are small static JSON on a CDN

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._files: dict[str, list[ReleaseFile]] = {}

    # ---- release discovery ----------------------------------------------------------------------------
    async def catalog(self) -> dict[str, Any]:
        res = await self.http.get(STAC_ROOT, check_robots=False)
        if not res.ok:
            raise RuntimeError(f"Overture STAC catalog unavailable: {res.reason}")
        data: dict[str, Any] = res.json()
        return data

    async def latest_release(self) -> str:
        data = await self.catalog()
        latest = data.get("latest")
        if not latest:
            flagged = [link.get("title", "") for link in data.get("links", []) if link.get("latest")]
            latest = flagged[0].split(" ", 1)[0] if flagged else None
        if not latest:
            raise RuntimeError("Overture STAC catalog has no latest release")
        return str(latest)

    async def releases(self) -> list[str]:
        """Release ids listed in the catalog, oldest first."""
        data = await self.catalog()
        ids = []
        for link in data.get("links", []):
            if link.get("rel") == "child":
                href = str(link.get("href", ""))
                part = href.rstrip("/").split("/")[-2] if href.endswith("catalog.json") else ""
                if part:
                    ids.append(part)
        return sorted(set(ids))

    async def release_files(self, release: str, bbox: Sequence[float] | None = None) -> list[ReleaseFile]:
        """GeoParquet files of the places theme (read once per release), optionally only those meeting `bbox`."""
        files = self._files.get(release)
        if files is None:
            base = f"https://stac.overturemaps.org/{release}/places/place/collection.json"
            res = await self.http.get(base, check_robots=False)
            if not res.ok:
                raise RuntimeError(f"Overture place collection for {release} unavailable: {res.reason}")
            items = [link["href"] for link in res.json().get("links", []) if link.get("rel") == "item"]
            files = []
            for href in items:
                item_res = await self.http.get(href, check_robots=False)
                if not item_res.ok:
                    raise RuntimeError(f"Overture STAC item unavailable: {href} ({item_res.reason})")
                item = item_res.json()
                b = [float(x) for x in item["bbox"]]
                aws = item["assets"]["aws"]
                href_s3 = aws.get("alternate", {}).get("s3", {}).get("href") or aws["href"]
                files.append(ReleaseFile(href=href_s3, bbox=(b[0], b[1], b[2], b[3])))
            self._files[release] = files
        return [f for f in files if bbox is None or _intersects(f.bbox, bbox)]

    # ---- queries ---------------------------------------------------------------------------------------
    @staticmethod
    def _connect(paths: Iterable[str]) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        if any(p.startswith(("s3://", "http://", "https://")) for p in paths):
            con.execute("INSTALL httpfs; LOAD httpfs;")
            con.execute(f"SET s3_region = {_sql_str(S3_REGION)};")
        return con

    @classmethod
    def query(
        cls,
        paths: Sequence[str],
        bbox: Sequence[float],
        codes: Sequence[str],
        *,
        min_confidence: float = MIN_CONFIDENCE,
        ids_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Open places inside `bbox` (min_lng, min_lat, max_lng, max_lat) whose taxonomy hierarchy contains any
        of `codes`. Blocking (DuckDB); call it from a worker thread inside async code."""
        if not paths or not codes:
            return []
        min_lng, min_lat, max_lng, max_lat = (float(v) for v in bbox)
        files = "[" + ", ".join(_sql_str(p) for p in paths) + "]"
        select = "id, confidence" if ids_only else ", ".join(COLUMNS)
        sql = f"""
            SELECT {select}
            FROM read_parquet({files}, hive_partitioning = false)
            WHERE bbox.xmin BETWEEN ? AND ? AND bbox.ymin BETWEEN ? AND ?
              AND list_has_any(taxonomy.hierarchy, ?::VARCHAR[])
              AND coalesce(operating_status, 'open') = 'open'
              AND confidence >= ?
              AND coalesce(names.primary, '') <> ''
            ORDER BY id
        """
        params: list[Any] = [min_lng, max_lng, min_lat, max_lat, list(codes), min_confidence]
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        con = cls._connect(paths)
        try:
            cur = con.execute(sql, params)
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
        finally:
            con.close()
        for row in rows:  # places are points: the bbox corners are the coordinates
            if "bbox" in row:
                bbox_value = row.pop("bbox") or {}
                row["lng"], row["lat"] = bbox_value.get("xmin"), bbox_value.get("ymin")
        return rows

    # ---- mapping (Step 5.4.4) --------------------------------------------------------------------------
    @staticmethod
    def segment_code(hierarchy: Sequence[str] | None, codes: Sequence[str]) -> str | None:
        """The most specific level of the place's taxonomy hierarchy that the segment lists."""
        wanted = set(codes)
        for code in reversed(list(hierarchy or [])):
            if code in wanted:
                return code
        return None

    @classmethod
    def to_record(cls, row: dict[str, Any], seg: Segment, city: str, release: str) -> SourceRecord | None:
        name = (row.get("name") or "").strip()
        if not name:
            return None
        hierarchy = list(row.get("hierarchy") or [])
        code = cls.segment_code(hierarchy, seg.overture.categories) or row.get("category")
        subcategory = None
        for level in [code, *reversed(hierarchy)]:
            subcategory = seg.subcategory_for(level, "")
            if subcategory:
                break
        subcategory = subcategory or seg.subcategory_for(None, name)
        website = next((w for w in (row.get("websites") or []) if w and not is_ignored_host(w)), None)
        addresses = row.get("addresses") or []
        first = addresses[0] if addresses else {}
        return SourceRecord(
            source="overture",
            source_key=str(row["id"]),
            segment_id=seg.id,
            name=name,
            website=homepage(website) if website else None,
            phones_raw=[p for p in (row.get("phones") or []) if p],  # hints only (A.4.3)
            emails=[e for e in (row.get("emails") or []) if e],  # hints only
            address=(first or {}).get("freeform"),
            city=city,
            locality=(first or {}).get("locality"),
            lat=row.get("lat"),
            lng=row.get("lng"),
            category=code,
            subcategory=subcategory,
            overture_id=str(row["id"]),
            payload={
                "release": release,
                "confidence": row.get("confidence"),
                "taxonomy": row.get("category"),
                "socials": list(row.get("socials") or [])[:5],
                "websites": list(row.get("websites") or [])[:3],
                "lat": row.get("lat"),
                "lng": row.get("lng"),
            },
        )

    # ---- adapter API -------------------------------------------------------------------------------------
    async def pull(
        self, seg: Segment, release: str, *, limit: int | None = None, cities: Sequence[str] | None = None
    ) -> list[SourceRecord]:
        """Places of the segment's categories in each segment city, mapped to records.

        City boxes overlap (Delhi's box covers parts of Gurugram and Noida), so a place can come back from two
        city queries: it is kept once, filed under the smallest box that contains it.
        """
        out: list[SourceRecord] = []
        seen: set[str] = set()
        for city in seg.cities:
            if cities and city.name not in cities:
                continue
            files = [f.href for f in await self.release_files(release, city.bbox)]
            remaining = None if limit is None else max(0, limit - len(out))
            if remaining == 0:
                break
            rows = await asyncio.to_thread(self.query, files, city.bbox, seg.overture.categories, limit=remaining)
            for row in rows:
                rec = self.to_record(row, seg, city.name, release)
                if rec is None or (rec.overture_id and rec.overture_id in seen):
                    continue
                if rec.overture_id:
                    seen.add(rec.overture_id)
                if rec.lat is not None and rec.lng is not None:
                    rec.city = smallest_city(seg, rec.lat, rec.lng) or rec.city
                out.append(rec)
        return out

    async def ids(self, seg: Segment, release: str, *, min_confidence: float = 0.0) -> set[str] | None:
        """Every place id of the segment's categories in its cities for one release, or None when that release
        is no longer on S3 (the monthly diff then makes no new_place signals rather than false ones)."""
        found: set[str] = set()
        try:
            for city in seg.cities:
                files = [f.href for f in await self.release_files(release, city.bbox)]
                rows = await asyncio.to_thread(
                    self.query, files, city.bbox, seg.overture.categories, min_confidence=min_confidence, ids_only=True
                )
                found.update(str(r["id"]) for r in rows)
        except (RuntimeError, duckdb.Error) as exc:
            self.ctx.add("overture.previous_release_unavailable")
            self.health_error(f"previous release {release} unreadable: {exc}"[:300])
            return None
        return found
