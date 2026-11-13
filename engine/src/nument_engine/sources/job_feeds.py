"""Global job feeds: companies in any industry that are hiring someone to build software (13 Nov 2026).

The need-first track: a small company that posts a developer, AI engineer or founding engineer role has a
budget and a need right now, and a studio can ship that work for less than one salary. Three free feeds:

- **Hacker News "Ask HN: Who is hiring?"**: the monthly thread, read with the official Algolia API
  (`hn.algolia.com/api/v1`, no robots.txt). Each top-level comment is one company. November 2026 had 355; a
  sample of 110 held 18 contract or freelance roles and 8 founding engineers, most with their own website.
- **Himalayas** (`himalayas.app/jobs/api/search`, public JSON API, robots.txt allows it): contractor builder
  roles only.
- **We Work Remotely** RSS (programming categories, robots.txt allows it).

RemoteOK is not used (its API terms ask for a public link back) and Remotive's robots.txt disallows its API.

Only posts whose text names a builder role reach the AI. One `classify_feed_job` call per post (g_lite) says who
the company is, what kind of company, and its home country. Code then routes it:

- product companies and small businesses go to `firms-{country}`;
- marketing and design agencies go to `partners-{country}` (white-label partners) when that segment is on;
- software agencies, IT services, staffing firms, marketplaces, enterprises and public bodies are dropped;
- companies that say they have more than 200 staff are dropped (a young studio rarely wins them);
- countries without an enabled segment are dropped.

The post itself is the evidence; its URL is never fetched again. Each post is read once (`source_records`).
"""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db
from ..http import host_blocked
from ..normalize import city_for_text, clean_text, web_domain
from ..segments import Segment
from . import health
from .base import QUOTE_MAX, Signal, SourceAdapter, field_of
from .jobs import _phrase_in, mask_contacts, parse_date, quote_in

HN_SEARCH = "https://hn.algolia.com/api/v1/search"
HN_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM = "https://news.ycombinator.com/item?id={id}"
HIMALAYAS_SEARCH = "https://himalayas.app/jobs/api/search"
WWR_FEEDS = (
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
)
HIMALAYAS_QUERIES = ("full stack developer", "react developer", "mobile app developer", "ai engineer",
                     "automation engineer", "web developer")  # fmt: skip
TASK = "classify_feed_job"
SETTING = "job_feeds.posts_per_day"
DEFAULT_PER_DAY = 80
MAX_AGE_DAYS = 21
TEXT_CHARS = 2500
MIN_CONFIDENCE = 0.6
MAX_TEAM = 200
CONTRACT_POINTS = 10.0  # a contract or freelance role is as strong as a public ask
# Words every builder post contains in some form; a post with none of them is not sent to the AI.
BUILDER_WORDS: tuple[str, ...] = (
    "developer", "engineer", "full stack", "full-stack", "fullstack", "frontend", "front-end", "backend",
    "back-end", "react", "react native", "flutter", "ios", "android", "mobile", "node", "python", "django",
    "rails", "laravel", "shopify", "wordpress", "ai", "ml", "machine learning", "llm", "genai", "automation",
    "n8n", "zapier", "chatbot", "cto", "tech lead", "programmer", "software",
)  # fmt: skip
NOT_BUILDER: tuple[str, ...] = ("data entry", "annotation", "annotator", "ai training", "ai trainer",
                                "rater", "evaluator", "tutor", "recruiter", "sales")  # fmt: skip
KIND_TO_DOMAIN = {"product_company": "firms", "small_business": "firms", "other": "firms",
                  "marketing_or_design_agency": "partners"}  # fmt: skip
COUNTRY_ALIASES = {"uk": "gb", "england": "gb", "united kingdom": "gb", "usa": "us", "united states": "us",
                   "uae": "ae", "united arab emirates": "ae", "india": "in", "australia": "au", "canada": "ca",
                   "singapore": "sg"}  # fmt: skip
_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r"""href=["']([^"']+)["']""", re.I)
_ITEM = re.compile(r"<item>(.*?)</item>", re.S)


@dataclass
class FeedPost:
    feed: str  # hn, himalayas, wwr
    post_id: str
    url: str
    text: str
    title: str = ""
    company: str | None = None
    location: str = ""
    posted_at: datetime | None = None
    links: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.feed}:{self.post_id}"


def strip_html(raw: str) -> str:
    text = re.sub(r"<\s*(p|br|li|h\d)[^>]*>", "\n", raw or "", flags=re.I)
    return clean_text(htmllib.unescape(_TAG.sub(" ", text)).replace("\u00a0", " "))


def links_in(raw: str) -> list[str]:
    return [htmllib.unescape(u) for u in _HREF.findall(raw or "") if u.startswith(("http://", "https://"))]


def is_builder_post(text: str) -> bool:
    low = text.lower()
    return any(_phrase_in(w, low) for w in BUILDER_WORDS)


def country_code(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    raw = COUNTRY_ALIASES.get(raw, raw)
    return raw if re.fullmatch(r"[a-z]{2}", raw) else None


# ---- feed parsers (pure, tested with fixtures) ----------------------------------------------------------


def hn_thread_id(data: Mapping[str, Any]) -> str | None:
    """The newest "Ask HN: Who is hiring?" story from a search_by_date answer."""
    for hit in data.get("hits") or []:
        if str(hit.get("title") or "").lower().startswith("ask hn: who is hiring"):
            return str(hit.get("objectID"))
    return None


def hn_posts(data: Mapping[str, Any], thread_id: str) -> list[FeedPost]:
    """Top-level comments of the thread (replies are discussion, not posts)."""
    out = []
    for hit in data.get("hits") or []:
        if str(hit.get("parent_id")) != str(thread_id) or not hit.get("comment_text"):
            continue
        raw = str(hit["comment_text"])
        text = strip_html(raw)
        first = text.split("\n", 1)[0]
        parts = [p.strip() for p in first.split("|")]
        out.append(
            FeedPost(
                feed="hn",
                post_id=str(hit.get("objectID")),
                url=HN_ITEM.format(id=hit.get("objectID")),
                text=text,
                title=" | ".join(parts[1:3]) if len(parts) > 1 else first[:120],
                company=parts[0][:120] if len(parts) > 1 else None,
                location=parts[2] if len(parts) > 2 else "",
                posted_at=datetime.fromtimestamp(int(hit["created_at_i"]), UTC) if hit.get("created_at_i") else None,
                links=links_in(raw),
            )
        )
    return out


def himalayas_posts(data: Mapping[str, Any]) -> list[FeedPost]:
    out = []
    for job in data.get("jobs") or []:
        guid = str(job.get("guid") or job.get("applicationLink") or "")
        if not guid:
            continue
        posted = datetime.fromtimestamp(int(job["pubDate"]), UTC) if str(job.get("pubDate") or "").isdigit() else None
        where = ", ".join(job.get("locationRestrictions") or [])[:200]
        out.append(
            FeedPost(
                feed="himalayas",
                post_id=guid.rstrip("/").rsplit("/", 1)[-1],
                url=guid,
                text=strip_html(f"{job.get('title') or ''}\n{job.get('description') or job.get('excerpt') or ''}"),
                title=str(job.get("title") or ""),
                company=str(job.get("companyName") or "") or None,
                location=where,
                posted_at=posted,
                links=links_in(str(job.get("description") or "")),
            )
        )
    return out


def _tag(item: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", item, re.S)
    raw = (m.group(1) if m else "").strip()
    if raw.startswith("<![CDATA["):
        raw = raw[9:].removesuffix("]]>")
    return raw.strip()


def wwr_posts(xml: str) -> list[FeedPost]:
    out = []
    for item in _ITEM.findall(xml or ""):
        link = htmllib.unescape(_tag(item, "link") or _tag(item, "guid"))
        title = htmllib.unescape(_tag(item, "title"))
        if not link or not title:
            continue
        company, _, role = title.partition(":")
        description = htmllib.unescape(_tag(item, "description"))
        out.append(
            FeedPost(
                feed="wwr",
                post_id=link.rstrip("/").rsplit("/", 1)[-1],
                url=link,
                text=strip_html(f"{title}\n{_tag(item, 'type')}\n{description}"),
                title=role.strip() or title,
                company=company.strip() if role else None,
                location=htmllib.unescape(_tag(item, "region")),
                posted_at=parse_date(_tag(item, "pubDate")),
                links=links_in(description),
            )
        )
    return out


def website_from(post: FeedPost, answer: str | None) -> str | None:
    """The company's own site: the AI's answer when the post shows that domain, else the first link in the post
    that is not a job board, a social network or an applicant tracking system."""
    text = f"{post.text} {' '.join(post.links)}".lower()
    dom = web_domain(answer or "")
    if dom and dom in text and not host_blocked(f"https://{dom}"):
        return f"https://{dom}"
    for link in post.links:
        dom = web_domain(link)
        if not dom or host_blocked(link) or any(
            dom.endswith(h)
            for h in ("ycombinator.com", "himalayas.app", "weworkremotely.com", "greenhouse.io", "lever.co",
                      "ashbyhq.com", "workable.com", "notion.site", "google.com", "forms.gle", "github.com")
        ):  # fmt: skip
            continue
        return f"https://{dom}"
    return None


class JobFeedsAdapter(SourceAdapter):
    name = "job_feeds"
    policy = "official_api"

    async def _json(self, url: str, params: dict[str, Any] | None = None, *, robots: bool = False) -> Any:
        res = await self.http.get(url, params=params, check_robots=robots, raise_on_block=False, retries=1)
        if res.status != 200:
            self.ctx.add(f"job_feeds.http_{res.status}")
            return None
        try:
            return res.json()
        except ValueError:
            return None

    async def hn(self) -> list[FeedPost]:
        found = await self._json(HN_BY_DATE, {"tags": "story,author_whoishiring", "hitsPerPage": 5})
        thread = hn_thread_id(found or {})
        if not thread:
            self.ctx.add("job_feeds.hn_no_thread")
            return []
        data = await self._json(HN_SEARCH, {"tags": f"comment,story_{thread}", "hitsPerPage": 1000})
        return hn_posts(data or {}, thread)

    async def himalayas(self) -> list[FeedPost]:
        out: list[FeedPost] = []
        for q in HIMALAYAS_QUERIES:
            data = await self._json(
                HIMALAYAS_SEARCH, {"q": q, "employment_type": "Contractor", "limit": 20}, robots=True
            )
            out += himalayas_posts(data or {})
        return out

    async def wwr(self) -> list[FeedPost]:
        out: list[FeedPost] = []
        for url in WWR_FEEDS:
            res = await self.http.get(url, raise_on_block=False, retries=1)
            if res.status == 200:
                out += wwr_posts(res.text)
            else:
                self.ctx.add(f"job_feeds.wwr_{res.state}")
        return out

    @staticmethod
    def unseen(posts: Sequence[FeedPost]) -> list[FeedPost]:
        if not posts:
            return []
        seen = {
            r["source_key"]
            for r in db.fetch_all(
                "select source_key from public.source_records where source = 'job_feeds' and source_key = any(%s)",
                [[p.key for p in posts]],
            )
        }
        unique: dict[str, FeedPost] = {}
        for p in posts:
            if p.key not in seen:
                unique.setdefault(p.key, p)
        return list(unique.values())

    def record_seen(self, post: FeedPost, verdict: str) -> None:
        if self.ctx.dry_run:
            return
        db.upsert(
            "source_records",
            [
                {
                    "source": "job_feeds",
                    "source_key": post.key,
                    "payload": {
                        "url": post.url,
                        "company": post.company,
                        "title": post.title[:200],
                        "verdict": verdict,
                    },
                    "fetched_at": health.now_utc(),
                }
            ],
            conflict=["source", "source_key"],
            update=["payload", "fetched_at"],
        )

    def posts_left(self) -> int:
        cap = health.setting_int(SETTING, DEFAULT_PER_DAY)
        return max(0, cap - self.ctx.budget.calls_today(None, [TASK]))

    def classify(self, post: FeedPost, segments: Mapping[str, Segment]) -> tuple[Signal | None, str]:
        """(signal or None, why) for one post."""
        text = mask_contacts(post.text)[:TEXT_CHARS]
        result = self.ctx.ai(
            TASK,
            {
                "feed": post.feed,
                "url": post.url,
                "posted_date": post.posted_at.date().isoformat() if post.posted_at else None,
                "title": post.title,
                "company": post.company,
                "location": post.location,
                "text": text,
            },
        )
        if result is None:
            return None, "no_answer"
        if not field_of(result, "is_relevant"):
            return None, "not_relevant"
        if float(field_of(result, "confidence") or 0) < MIN_CONFIDENCE:
            return None, "low_confidence"
        kind = str(field_of(result, "company_kind") or "other")
        domain = KIND_TO_DOMAIN.get(kind)
        if domain is None:
            return None, f"kind_{kind}"
        team = field_of(result, "team_size")
        if isinstance(team, int) and team > MAX_TEAM:
            return None, "too_big"
        country = country_code(field_of(result, "hq_country"))
        seg = segments.get(f"{domain}-{country}") if country else None
        if seg is None:
            return None, "partners_off" if domain == "partners" and country else "country_not_enabled"
        name = clean_text(str(field_of(result, "company_name") or post.company or ""), 120)
        if not name:
            return None, "no_company"
        quote = str(field_of(result, "evidence_quote") or "")
        quote = (
            clean_text(quote, QUOTE_MAX) if quote_in(quote, text) else clean_text(post.title or text[:200], QUOTE_MAX)
        )
        contract = bool(field_of(result, "contract"))
        city = city_for_text(f"{field_of(result, 'city') or ''} {post.location}", seg.cities)
        details: dict[str, Any] = {
            "feed": post.feed,
            "role": clean_text(str(field_of(result, "role") or post.title), 160),
            "role_category": "builder",
            "contract": contract,
            "company_kind": kind,
            "fallback_segment": f"firms-{country}" if domain == "partners" else None,
        }
        if isinstance(team, int):
            details["team_size"] = team
        if post.posted_at is None:
            details["date_estimated"] = True
        sig = Signal(
            type="hiring_builder",
            source=self.name,
            observed_at=post.posted_at or datetime.now(UTC),
            url=post.url,
            quote=quote,
            evidence_key=post.key,
            business_hint={
                "name": name,
                "city": city,
                "website": website_from(post, field_of(result, "company_website")),
            },
            details={k: v for k, v in details.items() if v is not None},
            points=CONTRACT_POINTS if contract else None,
            segment_id=seg.id,
        )
        return sig, "signal"

    async def signals_for(self, segments: Mapping[str, Segment], *, limit: int | None = None) -> list[Signal]:
        """Builder hiring signals from the three feeds, routed to the enabled country segments."""
        if not any(s.domain in ("firms", "partners") for s in segments.values()):
            return []
        left = self.posts_left()
        if limit:
            left = min(left, limit)
        if left <= 0:
            self.ctx.add("job_feeds.daily_cap_reached")
            return []
        fresh_after = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)
        posts: list[FeedPost] = []
        for feed in (self.hn, self.himalayas, self.wwr):
            try:
                got = await feed()
            except Exception as exc:  # one feed failing never stops the others
                self.ctx.add(f"job_feeds.errors.{feed.__name__}")
                self.ctx.alert(f"job_feeds {feed.__name__} failed: {type(exc).__name__}")
                continue
            self.ctx.add(f"job_feeds.{feed.__name__}_posts", len(got))
            posts += [p for p in got if p.posted_at is None or p.posted_at >= fresh_after]
        candidates = []
        for p in self.unseen(posts):
            low = p.text.lower()
            if not is_builder_post(f"{p.title} {low[:600]}") or any(
                _phrase_in(w, p.title.lower()) for w in NOT_BUILDER
            ):
                self.record_seen(p, "no_builder_words")
                self.ctx.add("job_feeds.no_builder_words")
                continue
            candidates.append(p)
        candidates.sort(key=lambda p: (p.feed != "hn", -(p.posted_at or fresh_after).timestamp()))
        self.ctx.add("job_feeds.candidates", len(candidates))
        out: list[Signal] = []
        for post in candidates[:left]:
            if self.ctx.ai_stopped:
                break
            sig, why = self.classify(post, segments)
            self.ctx.add(f"job_feeds.{why}")
            if why != "no_answer":
                self.record_seen(post, why)
            if sig is not None:
                out.append(sig)
        return out
