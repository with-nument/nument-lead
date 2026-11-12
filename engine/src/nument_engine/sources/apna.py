"""Apna job posts: hiring signals in India (Step 5.8). Grey source.

Apna's terms ban robots, but its robots.txt allows job pages and the founder approved slow fetching of public
pages on 12 Nov 2026 (A.4.1). So: one request every 6 seconds, our honest User-Agent, robots.txt obeyed, at most
300 pages a day across segments, and the whole source stops on the first block (24 hours, then 72 hours, then
7 days; two blocks in 7 days switch it off until the founder turns it back on).

Discovery reads the job sitemaps (checked 12 Nov 2026): `api/sitemap-index.xml` lists
`api/job-listing-sitemap.xml`, which lists `active-job-listings-N.xml` files of about 10,000 job URLs each,
shaped `https://apna.co/job/<city-slug>/<title-slug>-<job id>`. URLs are filtered by city slug and title words
before any job page is fetched.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .. import db
from ..normalize import city_for_text
from ..segments import Segment
from . import health
from .base import Signal, SourceAdapter
from .jobs import JobPost, classify_job, has_domain_hint, job_from_html, role_from_keywords

SITEMAP_INDEX = "https://apna.co/api/sitemap-index.xml"
JOB_URL = re.compile(r"^https://apna\.co/job/(?P<city>[a-z0-9-]+)/(?P<slug>[a-z0-9-]+)-(?P<id>\d{5,})/?$")
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
DAILY_PAGE_CAP = 300  # all segments together (Step 18.1.3)


@dataclass(frozen=True)
class JobUrl:
    url: str
    job_id: str
    city_slug: str
    title_slug: str
    segment_id: str  # the segment whose keywords matched (routing is decided after classification)
    role: str  # frontdesk | builder


def parse_locs(xml: str) -> list[str]:
    return LOC.findall(xml or "")


def match_job_url(url: str, segments: Sequence[Segment]) -> JobUrl | None:
    """A job URL in one of the segments' cities whose title matches a front-desk or builder keyword."""
    m = JOB_URL.match(url.strip())
    if not m:
        return None
    city_text, title = m.group("city").replace("-", " "), m.group("slug").replace("-", " ")
    for seg in segments:
        if city_for_text(city_text, seg.cities) is None:
            continue
        role = role_from_keywords(title, seg)
        if role:
            return JobUrl(url.strip(), m.group("id"), m.group("city"), m.group("slug"), seg.id, role)
    return None


class ApnaAdapter(SourceAdapter):
    name = "apna"
    policy = "grey"
    min_gap_s = 6.0

    async def job_sitemaps(self) -> list[str]:
        index = await self.http.get(SITEMAP_INDEX)
        if not index.ok:
            raise RuntimeError(f"Apna sitemap index unavailable: {index.reason}")
        listing = [u for u in parse_locs(index.text) if "job-listing" in u]
        out: list[str] = []
        for url in listing:
            res = await self.http.get(url)
            if res.ok:
                out += [u for u in parse_locs(res.text) if "active-job-listings" in u]
        return out

    async def candidate_urls(self, segments: Sequence[Segment]) -> list[JobUrl]:
        found: dict[str, JobUrl] = {}
        for sitemap in await self.job_sitemaps():
            res = await self.http.get(sitemap)
            if not res.ok:
                self.ctx.add("apna.sitemap_errors")
                continue
            for url in parse_locs(res.text):
                job = match_job_url(url, segments)
                if job and job.job_id not in found:
                    found[job.job_id] = job
        return list(found.values())

    @staticmethod
    def unseen(jobs: Sequence[JobUrl]) -> list[JobUrl]:
        """Drop jobs already read on an earlier day (source_records where source = 'apna')."""
        if not jobs:
            return []
        seen = {
            r["source_key"]
            for r in db.fetch_all(
                "select source_key from public.source_records where source = 'apna' and source_key = any(%s)",
                [[f"apna:{j.job_id}" for j in jobs]],
            )
        }
        return [j for j in jobs if f"apna:{j.job_id}" not in seen]

    @staticmethod
    def budget(segments: Sequence[Segment]) -> int:
        """Pages left today: the segments' caps (at most 300 in all) minus what was fetched today."""
        cap = min(DAILY_PAGE_CAP, sum(s.apna.pages_per_day for s in segments))
        row = db.fetch_one(
            "select requests_today, requests_day = (now() at time zone 'Asia/Kolkata')::date as today "
            "from public.source_health where source = 'apna'"
        )
        used = int(row["requests_today"]) if row and row["today"] else 0
        return max(0, cap - used)

    @staticmethod
    def order(jobs: Sequence[JobUrl], segments: Sequence[Segment]) -> list[JobUrl]:
        """Share the day's pages between segments by their caps, keeping URL order inside a segment."""
        caps = {s.id: s.apna.pages_per_day for s in segments}
        by_seg: dict[str, list[JobUrl]] = {}
        for job in jobs:
            by_seg.setdefault(job.segment_id, []).append(job)
        out: list[JobUrl] = []
        while any(by_seg.values()):
            for seg_id in sorted(by_seg, key=lambda k: -caps.get(k, 0)):
                take = max(1, caps.get(seg_id, 0) // 20)
                out += by_seg[seg_id][:take]
                by_seg[seg_id] = by_seg[seg_id][take:]
        return out

    async def read_job(self, job: JobUrl) -> JobPost | None:
        res = await self.http.get(job.url)
        if not res.ok:
            self.ctx.add(f"apna.page_{res.state}")
            return None
        return job_from_html(res.text, source="apna", job_id=job.job_id, url=job.url)

    async def signals_for(self, segments: Mapping[str, Segment], *, limit: int | None = None) -> list[Signal]:
        """New hiring signals from Apna for every enabled India segment (one pass, routed by the classifier)."""
        india = [s for s in segments.values() if s.country == "in" and s.apna.pages_per_day > 0]
        if not india:
            return []
        budget = self.budget(india)
        if budget <= 0:
            self.ctx.add("apna.daily_cap_reached")
            return []
        jobs = self.order(self.unseen(await self.candidate_urls(india)), india)
        self.ctx.add("apna.candidate_urls", len(jobs))
        budget = max(0, budget - self.http.requests)  # sitemaps count against the day's requests
        if limit:
            budget = min(budget, limit)
        out: list[Signal] = []
        for job in jobs[:budget]:
            post = await self.read_job(job)
            if post is None:
                continue
            self.ctx.add("apna.pages_read")
            if not self.ctx.dry_run:
                record_seen(post)
            hint_text = f"{post.title} {post.employer or ''} {post.description}"
            if not has_domain_hint(hint_text, [s.domain for s in india]):
                self.ctx.add("apna.no_domain_hint")
                continue
            sig = classify_job(self.ctx, post, segments, country="in", default_segment=segments[job.segment_id])
            if sig is not None:
                out.append(sig)
        return out


def record_seen(post: JobPost) -> None:
    """Remember a job page so it is not fetched again (the signal itself is written by the signals stage)."""
    db.upsert(
        "source_records",
        [
            {
                "source": "apna",
                "source_key": f"apna:{post.job_id}",
                "payload": {
                    "url": post.url,
                    "title": post.title,
                    "employer": post.employer,
                    "posted": post.posted_at.isoformat() if post.posted_at else None,
                },
                "fetched_at": health.now_utc(),
            }
        ],
        conflict=["source", "source_key"],
        update=["payload", "fetched_at"],
    )
