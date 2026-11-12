"""Practo clinic profiles: size and price evidence for clinics in India (Step 5.7, Step 9.10).

Off by default (`settings.sources_enabled.practo = false`) until the founder has read Practo's terms. When on:
- The index of clinic profile URLs per city is built from the sitemaps that robots.txt lists (profile pages are
  allowed; search, appointment and API paths are not, and robots.txt is re-checked for every URL).
- A queued clinic is matched to a profile only with the same city, a name match of at least 90
  (`token_set_ratio` on match keys) and the locality in the profile URL. No match means no Practo data.
- The profile page is stored as one of the business's pages, so AI extraction (Step 9.11) quotes doctors,
  fees and "Profile is claimed" with the Practo URL. Practo shows masked numbers, so no phone is ever taken.
- One request every 5 seconds, at most `practo.pages_per_day` profiles a day.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from ..http import FetchResult
from ..normalize import match_key
from ..segments import Segment
from . import health
from .base import SourceAdapter

ROBOTS = "https://www.practo.com/robots.txt"
PROFILE = re.compile(r"^https://www\.practo\.com/(?P<city>[a-z-]+)/clinic/(?P<slug>[a-z0-9-]+)/?$")
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
DOCTORS = re.compile(r"\bDoctors?\s*\((\d{1,3})\)", re.I)
MIN_NAME_RATIO = 90
DEFAULT_PAGES_PER_DAY = 150


@dataclass(frozen=True)
class Profile:
    url: str
    city_slug: str
    slug: str


def parse_profile(url: str) -> Profile | None:
    m = PROFILE.match(url.strip())
    return Profile(url.strip(), m.group("city"), m.group("slug")) if m else None


def best_match(
    name: str, locality: str | None, city: str, profiles: Sequence[Profile], *, min_ratio: int = MIN_NAME_RATIO
) -> Profile | None:
    """The profile with the best name match in the same city whose slug names the locality (Step 9.10)."""
    if not locality:
        return None
    city_slug = city.lower().replace(" ", "-")
    loc_slug = locality.lower().replace(" ", "-")
    key = match_key(name)
    best: tuple[float, Profile] | None = None
    for prof in profiles:
        if city_slug not in prof.city_slug or loc_slug not in prof.slug:
            continue
        slug_name = prof.slug.replace(loc_slug, " ").replace("-", " ")
        ratio = fuzz.token_set_ratio(key, match_key(slug_name))
        if ratio >= min_ratio and (best is None or ratio > best[0]):
            best = (ratio, prof)
    return best[1] if best else None


def doctors_count(text: str) -> int | None:
    """Cross-check parser for "Doctors (N)" on a profile page."""
    m = DOCTORS.search(text or "")
    return int(m.group(1)) if m else None


class PractoAdapter(SourceAdapter):
    name = "practo"
    policy = "public"
    min_gap_s = 5.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._profiles: dict[str, list[Profile]] = {}

    async def sitemaps(self) -> list[str]:
        res = await self.http.get(ROBOTS, check_robots=False)
        if not res.ok:
            return []
        return [line.split(":", 1)[1].strip() for line in res.text.splitlines() if line.lower().startswith("sitemap:")]

    async def profiles_for(self, seg: Segment, city: str) -> list[Profile]:
        """Clinic profile URLs for one city (read once per run from the sitemaps that mention clinics)."""
        if city in self._profiles:
            return self._profiles[city]
        city_slug = city.lower().replace(" ", "-")
        found: list[Profile] = []
        for sitemap in await self.sitemaps():
            if "clinic" not in sitemap.lower():
                continue
            res = await self.http.get(sitemap)
            urls = LOC.findall(res.text) if res.ok else []
            nested = [u for u in urls if u.endswith(".xml") and city_slug in u.lower()]
            for child in nested[:20]:
                child_res = await self.http.get(child)
                urls += LOC.findall(child_res.text) if child_res.ok else []
            found += [p for p in (parse_profile(u) for u in urls) if p and city_slug in p.city_slug]
        self._profiles[city] = found
        return found

    async def profile_page(self, business: dict[str, Any], seg: Segment) -> FetchResult | None:
        """The matched profile page for one queued clinic, or None. Counts against the daily cap."""
        if seg.id != "clinics-in" or not business.get("city"):
            return None
        cap = health.setting_int("practo.pages_per_day", DEFAULT_PAGES_PER_DAY)
        if self.ctx.stats.get("practo.pages", 0) >= cap:
            return None
        prof = best_match(
            business["name"], business.get("locality"), business["city"], await self.profiles_for(seg, business["city"])
        )
        if prof is None:
            self.ctx.add("practo.no_match")
            return None
        res = await self.http.get(prof.url)
        self.ctx.add("practo.pages")
        return res if res.ok else None
