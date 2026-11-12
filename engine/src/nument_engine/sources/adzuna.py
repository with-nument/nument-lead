"""Adzuna jobs API: an official, rule-compliant job feed (Step 5.13). Optional and off by default.

Needs `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` from the founder's free Adzuna developer account (we never create
accounts). It runs only for segments with `adzuna_enabled: true` and when `settings.sources_enabled.adzuna` is on.
Country coverage must be checked before enabling a segment (Step 5.13: verify India and the UAE at build).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ..segments import Segment
from .base import Signal, SourceAdapter
from .jobs import JobPost, classify_job, has_domain_hint, parse_date, role_from_keywords

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
RESULTS_PER_PAGE = 50
MAX_DAYS_OLD = 7


def credentials() -> tuple[str, str] | None:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID", ""), os.environ.get("ADZUNA_APP_KEY", "")
    return (app_id, app_key) if app_id and app_key else None


def to_post(item: Mapping[str, Any]) -> JobPost | None:
    job_id = str(item.get("id") or "")
    title = str(item.get("title") or "").strip()
    if not job_id or not title:
        return None
    return JobPost(
        source="adzuna",
        job_id=job_id,
        url=str(item.get("redirect_url") or ""),
        title=title,
        employer=((item.get("company") or {}).get("display_name") or None),
        description=str(item.get("description") or ""),
        posted_at=parse_date(item.get("created")),
        location_text=str((item.get("location") or {}).get("display_name") or ""),
    )


class AdzunaAdapter(SourceAdapter):
    name = "adzuna"
    policy = "official_api"
    min_gap_s = 1.0

    def status(self) -> tuple[bool, str]:
        if credentials() is None:
            return False, "ADZUNA_APP_ID and ADZUNA_APP_KEY are not set"
        return super().status()

    async def search(self, seg: Segment, what: str, where: str, page: int = 1) -> list[dict[str, Any]]:
        creds = credentials()
        if creds is None:
            return []
        params = {
            "app_id": creds[0],
            "app_key": creds[1],
            "what": what,
            "where": where,
            "max_days_old": MAX_DAYS_OLD,
            "results_per_page": RESULTS_PER_PAGE,
            "content-type": "application/json",
        }
        res = await self.http.get(API.format(country=seg.country, page=page), params=params, check_robots=False)
        self.ctx.budget.record("other", None, "adzuna_search")  # free, counted like every API call
        if not res.ok:
            self.ctx.add("adzuna.errors")
            return []
        results: list[dict[str, Any]] = res.json().get("results", [])
        return results

    async def signals_for(self, segments: Mapping[str, Segment], *, limit: int | None = None) -> list[Signal]:
        out: list[Signal] = []
        for seg in segments.values():
            if not seg.adzuna_enabled:
                continue
            terms = [*seg.job_keywords.frontdesk[:4], *seg.job_keywords.builder[:2]]
            for city in seg.cities:
                for term in terms:
                    for item in await self.search(seg, term, city.name):
                        post = to_post(item)
                        if post is None or role_from_keywords(post.title, seg) is None:
                            continue
                        if not has_domain_hint(f"{post.title} {post.employer} {post.description}", [seg.domain]):
                            continue
                        sig = classify_job(self.ctx, post, segments, country=seg.country, default_segment=seg)
                        if sig is not None:
                            out.append(sig)
                        if limit and len(out) >= limit:
                            return out
        return out
