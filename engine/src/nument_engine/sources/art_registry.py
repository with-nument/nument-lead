"""India ART and Surrogacy Registry: the official list of registered IVF (ART) clinics (Step 5.6).

One public HTML page, no login and no CAPTCHA (checked 12 Nov 2026: 4,767 rows; robots.txt is absent, which
means everything is allowed). Fetched once a month. Columns: ID, name, address, state, email (written as
`name[at]domain[dot]com`), registration number and a certificate PDF link.

Rows are kept only when the address names one of the segment's cities (aliases included). The subcategory comes
from the segment's `registries[].subcategory` (A.13.5 rule 7), never a hard-coded value.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from ..normalize import city_for_text, clean_text, decode_email, locality_for
from ..segments import Segment
from .base import SourceAdapter, SourceRecord

DEFAULT_URL = "https://registry.artsurrogacy.gov.in/clinic/list?type=register-clinic"
REGISTRY_KEY = "art_registry"
CATEGORY = "fertility_clinic"  # the Overture code for ART clinics, listed in the clinics segments' fit categories
EXPECTED_HEADERS = ("id", "name", "address", "state", "email", "registration")


class RegistryFormatChanged(RuntimeError):
    """The page no longer has the table we know. Fail loudly instead of importing garbage."""


def parse_rows(html: str, base_url: str = DEFAULT_URL) -> list[dict[str, Any]]:
    """Every clinic row as a dict: name, address, state, email, registration_no, certificate_url."""
    tree = LexborHTMLParser(html)
    table = tree.css_first("table#example3") or tree.css_first("table")
    if table is None:
        raise RegistryFormatChanged("no table on the ART registry page")
    headers = [clean_text(th.text()).lower() for th in table.css("thead th")]
    if headers and not all(any(h.startswith(want) or want in h for h in headers) for want in EXPECTED_HEADERS):
        raise RegistryFormatChanged(f"unexpected ART registry columns: {headers}")
    rows: list[dict[str, Any]] = []
    for tr in table.css("tbody tr"):
        cells = tr.css("td")
        if len(cells) < 6:
            continue
        link = cells[6].css_first("a") if len(cells) > 6 else None
        href = link.attributes.get("href") if link is not None else None
        rows.append(
            {
                "name": clean_text(cells[1].text()),
                "address": clean_text(cells[2].text()),
                "state": clean_text(cells[3].text()),
                "email": decode_email(cells[4].text()),
                "registration_no": clean_text(cells[5].text()),
                "certificate_url": urljoin(base_url, href) if href else None,
            }
        )
    return rows


class ArtRegistryAdapter(SourceAdapter):
    name = "art_registry"
    policy = "open_data"
    min_gap_s = 3.0  # registries: one request every 3 seconds (Step 18.1.3)

    async def fetch_rows(self, url: str = DEFAULT_URL) -> list[dict[str, Any]]:
        res = await self.http.get(url, retries=1)
        if not res.ok:
            raise RuntimeError(f"ART registry fetch failed: {res.state} {res.reason}")
        return parse_rows(res.text, url)

    @staticmethod
    def to_records(rows: list[dict[str, Any]], seg: Segment, subcategory: str | None) -> list[SourceRecord]:
        out: list[SourceRecord] = []
        for row in rows:
            name, reg_no = row["name"], row["registration_no"]
            if not name or not reg_no:
                continue
            city = city_for_text(f"{row['address']} {name}", seg.cities)
            if city is None:
                continue
            localities = next((c.localities for c in seg.cities if c.name == city), [])
            out.append(
                SourceRecord(
                    source=REGISTRY_KEY,
                    source_key=reg_no,
                    segment_id=seg.id,
                    name=name,
                    emails=[row["email"]] if row["email"] else [],
                    emails_are_registry=True,
                    address=row["address"],
                    city=city,
                    locality=locality_for(row["address"], localities),
                    category=CATEGORY,
                    subcategory=subcategory,
                    payload={
                        "registration_no": reg_no,
                        "state": row["state"],
                        "email": row["email"],
                        "url": DEFAULT_URL,
                        "certificate_url": row["certificate_url"],
                    },
                )
            )
        return out

    async def pull(self, seg: Segment, *, limit: int | None = None) -> list[SourceRecord]:
        """Registered clinics in the segment's cities."""
        entry = next((r for r in seg.registries if r.key == REGISTRY_KEY), None)
        if entry is None or entry.status != "ready":
            return []
        rows = await self.fetch_rows(entry.url or DEFAULT_URL)
        self.ctx.add("art_registry.rows", len(rows))
        records = self.to_records(rows, seg, entry.subcategory)
        return records[:limit] if limit else records
