"""Public job boards (Greenhouse, Lever, Ashby, Workable): founding-engineer and CTO roles at startups.

For businesses of the startup segments (`firms-<country>`) that have a website, this source looks for their own
public job board and reads its open roles (15 Nov 2026):

- **Finding the board.** A board's address is a slug the company chose, almost always its domain or its name:
  brightcart.io is `brightcart` on every board. At most three slugs are tried (the domain's first label, without
  a "get", "try" or "use" prefix, and the name joined), each against the four boards' own public APIs:
  `boards-api.greenhouse.io`, `api.lever.co`, `api.ashbyhq.com` (official job-board APIs, no robots.txt) and
  `apply.workable.com` (its widget API; robots.txt is read). A board counts only when it shows it is the
  company's: its own name (Greenhouse, Workable) names the company, or (Lever, Ashby, which give no name) a
  role's description mentions the company's domain or name.
- **Reading the roles.** A founding engineer, first engineer, CTO or technical co-founder role means the
  company has no tech team yet: each becomes a `hiring_builder` signal with the role title as the quote and the
  role's own page as the URL. Every signal carries `details.engineering_roles` (software roles open on the
  board: many of them is evidence of a tech team, for qualification) and `details.open_roles`. A company with
  more open roles than `startup.max_team` people is not a 2 to 10 person startup and gets no signal.

Each business is checked at most once every 14 days (`source_records` key `check:<business id>`), and at most
`ats_jobs.companies_per_day` businesses a day. A board that blocks us (403, 429) pauses the source; what was
found before the block is kept.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from cleanco import basename

from .. import db
from ..http import SourceBlocked
from ..logging import get_logger
from ..normalize import clean_text
from ..segments import Segment
from . import health, startup
from .base import QUOTE_MAX, Signal, SourceAdapter, SourceContext

log = get_logger()

NAME = "ats_jobs"
SETTING = "ats_jobs.companies_per_day"
DEFAULT_PER_DAY = 100
RECHECK_DAYS = 14
MAX_SLUGS = 3
GAP_S = 0.2
BOARD_BYTES = 3_000_000
TEXT_CHARS = 20_000
GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER = "https://api.lever.co/v0/postings/{slug}"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
WORKABLE = "https://apply.workable.com/api/v1/widget/accounts/{slug}"
BOARDS = ("greenhouse", "lever", "ashby", "workable")

# A role that means there is no tech team yet. Checked on the title only.
FOUNDING_ROLE = re.compile(
    r"\bfounding\b.{0,40}\b(?:engineer|developer|programmer|full[\s-]?stack|cto)\b"
    r"|\bfirst\b.{0,20}\b(?:engineer|engineering hire|developer)\b|\bengineer\s*#\s*1\b"
    r"|\bcto\b|\bchief (?:technology|technical) officer\b|\btechnical co-?founder\b"
    r"|\bco-?founder\b.{0,20}\b(?:cto|technical|engineering)\b",
    re.I,
)
SOFTWARE_ROLE = re.compile(
    r"\b(?:engineer|engineering|developer|programmer|software|sre|devops|full[\s-]?stack|front[\s-]?end|"
    r"back[\s-]?end|ios|android|mobile|machine learning|ml|data scientist|architect|cto)\b",
    re.I,
)
# Engineers whose work is not building the company's software.
NOT_SOFTWARE = re.compile(
    r"\b(?:sales|solutions?|support|customer|success|mechanical|electrical|civil|chemical|manufacturing|"
    r"process|quality|field|hardware|structural|construction|recruit\w*|talent)\b",
    re.I,
)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
_FILLER = frozenset(["the", "and", "of", "a", "an", "pbc", "company", "co", "inc", "llc", "ltd"])
_GENERIC = frozenset(["labs", "technologies", "technology", "tech", "software", "systems", "solutions", "ai", "app"])
_PREFIXES = ("get", "try", "use", "join", "hello", "with")

CANDIDATES_SQL = """
select b.id::text as id, b.name, b.web_domain, b.segment_id
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.web_domain is not null
   and b.status in ('candidate', 'queued', 'researched', 'qualified')
   and not exists (select 1 from public.source_records r
                    where r.source = 'ats_jobs' and r.source_key = 'check:' || b.id::text
                      and r.fetched_at > now() - make_interval(days => %(days)s))
 order by b.created_at desc
 limit %(limit)s
"""


@dataclass
class Job:
    id: str
    title: str
    url: str | None
    posted: datetime | None
    text: str = ""


@dataclass
class Board:
    board: str
    slug: str
    name: str | None
    jobs: list[Job] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------------


def name_words(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", basename(name or "").lower()) if w not in _FILLER]


def slugs_for(name: str, domain: str) -> list[str]:
    """Board slugs the company would have chosen, most likely first: its domain's first label (also without a
    "get"/"try"/"use" prefix), then its name joined and hyphenated."""
    label = (domain or "").split(".", 1)[0].lower()
    out = [label]
    for prefix in _PREFIXES:
        if label.startswith(prefix) and len(label) - len(prefix) >= 3:
            out.append(label[len(prefix) :])
    words = name_words(name)
    out += ["".join(words), "-".join(words)]
    unique: list[str] = []
    for slug in out:
        if _SLUG.match(slug) and len(slug) >= 3 and slug not in unique:
            unique.append(slug)
    return unique[:MAX_SLUGS]


def _named(words: Sequence[str], text: str) -> bool:
    if not words:
        return False
    pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]{0,3}".join(re.escape(w) for w in words) + r"(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


def same_company(name: str, other: str | None) -> bool:
    """Does `other` (a board's own name) name this company? Either name in the other, as whole words."""
    if not other:
        return False
    words = name_words(name)
    core = [w for w in words if w not in _GENERIC] or words
    theirs = name_words(other)
    their_core = [w for w in theirs if w not in _GENERIC] or theirs
    return _named(words, other) or _named(core, other) or _named(their_core, " ".join(words))


def board_is_theirs(board: Board, name: str, domain: str) -> bool:
    """The board belongs to the company: its own name names the company, or (no name given) a role's text
    mentions the company's domain or name."""
    if board.name:
        return same_company(name, board.name)
    words = name_words(name)
    return any(domain.lower() in job.text.lower() or _named(words, job.text) for job in board.jobs)


def is_software_role(title: str) -> bool:
    return bool(SOFTWARE_ROLE.search(title)) and not NOT_SOFTWARE.search(title)


def is_founding_role(title: str) -> bool:
    return bool(FOUNDING_ROLE.search(title)) and not NOT_SOFTWARE.search(title)


def _when(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(float(value) / (1000 if value > 10**11 else 1), UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _plain(value: Any) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", str(value or "")))[:TEXT_CHARS]


def parse_greenhouse(slug: str, data: Any) -> Board | None:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return None
    jobs = [
        Job(
            id=str(j.get("id")),
            title=clean_text(str(j.get("title") or "")),
            url=j.get("absolute_url"),
            posted=_when(j.get("first_published") or j.get("updated_at")),
            text=_plain(j.get("content")),
        )
        for j in data["jobs"]
        if isinstance(j, dict) and j.get("id") and j.get("title")
    ]
    names = {str(j.get("company_name")) for j in data["jobs"] if isinstance(j, dict) and j.get("company_name")}
    return Board("greenhouse", slug, next(iter(names)) if len(names) == 1 else None, jobs)


def parse_lever(slug: str, data: Any) -> Board | None:
    if not isinstance(data, list):
        return None
    jobs = [
        Job(
            id=str(j.get("id")),
            title=clean_text(str(j.get("text") or "")),
            url=j.get("hostedUrl"),
            posted=_when(j.get("createdAt")),
            text=_plain(j.get("descriptionPlain") or j.get("description")),
        )
        for j in data
        if isinstance(j, dict) and j.get("id") and j.get("text")
    ]
    return Board("lever", slug, None, jobs)


def parse_ashby(slug: str, data: Any) -> Board | None:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return None
    jobs = [
        Job(
            id=str(j.get("id")),
            title=clean_text(str(j.get("title") or "")),
            url=j.get("jobUrl"),
            posted=_when(j.get("publishedAt")),
            text=_plain(j.get("descriptionPlain") or j.get("descriptionHtml")),
        )
        for j in data["jobs"]
        if isinstance(j, dict) and j.get("id") and j.get("title") and j.get("isListed", True) is not False
    ]
    return Board("ashby", slug, None, jobs)


def parse_workable(slug: str, data: Any) -> Board | None:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return None
    jobs = [
        Job(
            id=str(j.get("shortcode")),
            title=clean_text(str(j.get("title") or "")),
            url=j.get("url") or j.get("shortlink"),
            posted=_when(j.get("published_on") or j.get("created_at")),
        )
        for j in data["jobs"]
        if isinstance(j, dict) and j.get("shortcode") and j.get("title")
    ]
    return Board("workable", slug, clean_text(str(data.get("name") or "")) or None, jobs)


PARSERS: dict[str, Callable[[str, Any], Board | None]] = {
    "greenhouse": parse_greenhouse,
    "lever": parse_lever,
    "ashby": parse_ashby,
    "workable": parse_workable,
}


def board_signals(board: Board, business: Mapping[str, Any], max_team: int, now: datetime) -> tuple[list[Signal], str]:
    """(hiring_builder signals, verdict) for a company's own board."""
    software = [j for j in board.jobs if is_software_role(j.title)]
    founding = [j for j in board.jobs if is_founding_role(j.title)]
    if not founding:
        return [], "no_founding_role"
    if len(board.jobs) > max_team:
        return [], "too_many_roles"  # hiring more people than a 2 to 10 person startup has
    out = []
    for job in founding:
        details: dict[str, Any] = {
            "board": board.board,
            "board_slug": board.slug,
            "role": job.title,
            "role_category": "builder",
            "founding_role": True,
            "engineering_roles": len(software),
            "open_roles": len(board.jobs),
        }
        if job.posted is None:
            details["date_estimated"] = True
        out.append(
            Signal(
                type="hiring_builder",
                source=NAME,
                observed_at=job.posted or now,
                url=job.url,
                quote=clean_text(job.title, QUOTE_MAX),
                evidence_key=f"{board.board}:{board.slug}:{job.id}",
                business_id=str(business["id"]),
                details=details,
                segment_id=business.get("segment_id"),
            )
        )
    return out, "signal"


# ---------------------------------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------------------------------


class AtsJobsAdapter(SourceAdapter):
    name = NAME
    policy = "official_api"
    min_gap_s = GAP_S

    def __init__(self, ctx: SourceContext, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(ctx, transport=transport)
        self.blocked = False
        self.clock: Callable[[], datetime] = health.now_utc

    def companies_left(self) -> int:
        """Businesses still allowed a board check today (settings ats_jobs.companies_per_day, IST day)."""
        used = db.scalar(
            "select count(*) from public.source_records where source = %s and source_key like 'check:%%' "
            "and fetched_at >= %s",
            [NAME, health.ist_day_start()],
        )
        return max(0, health.setting_int(SETTING, DEFAULT_PER_DAY) - int(used or 0))

    def record(self, business_id: str, payload: dict[str, Any]) -> None:
        if self.ctx.dry_run:
            return
        db.upsert(
            "source_records",
            [
                {
                    "source": NAME,
                    "source_key": f"check:{business_id}",
                    "business_id": business_id,
                    "payload": payload,
                    "fetched_at": health.now_utc(),
                }
            ],
            conflict=["source", "source_key"],
            update=["business_id", "payload", "fetched_at"],
        )

    async def fetch(self, board: str, slug: str) -> Board | None:
        """The board at this slug, or None when there is none (404, an empty or foreign answer)."""
        url = {"greenhouse": GREENHOUSE, "lever": LEVER, "ashby": ASHBY, "workable": WORKABLE}[board]
        res = await self.http.get(
            url.format(slug=slug),
            params={"mode": "json"} if board == "lever" else None,
            check_robots=board == "workable",
            max_bytes=BOARD_BYTES,
            retries=1,
        )
        if res.status != 200:
            if res.status not in (404, None):
                self.ctx.add(f"ats_jobs.{board}_http_{res.status}")
            return None
        try:
            return PARSERS[board](slug, res.json())
        except ValueError:
            self.ctx.add(f"ats_jobs.{board}_bad_json")
            return None

    async def find_board(self, name: str, domain: str) -> Board | None:
        """The company's own board: each slug against the four boards at once, first match wins."""
        for slug in slugs_for(name, domain):
            found = await asyncio.gather(*(self.fetch(b, slug) for b in BOARDS), return_exceptions=True)
            for result in found:
                if isinstance(result, SourceBlocked):
                    raise result
                if isinstance(result, BaseException):
                    log.info("ats_jobs.fetch_failed", error=type(result).__name__)
                    continue
                if result is not None and board_is_theirs(result, name, domain):
                    return result
        return None

    async def signals_for(self, segments: Mapping[str, Segment], *, limit: int | None = None) -> list[Signal]:
        """Founding-role signals for startup businesses with a website. A block keeps what was found before."""
        out: list[Signal] = []
        startup_ids = [s.id for s in segments.values() if s.domain == "firms" and s.universe == "signals_only"]
        if not startup_ids:
            return out
        left = self.companies_left()
        if limit:
            left = min(left, limit)
        if left <= 0:
            self.ctx.add("ats_jobs.daily_cap_reached")
            return out
        max_team, _ = startup.limits()
        now = self.clock()
        rows = db.fetch_all(CANDIDATES_SQL, {"segments": startup_ids, "days": RECHECK_DAYS, "limit": left})
        try:
            for b in rows:
                board = await self.find_board(str(b["name"]), str(b["web_domain"]))
                if board is None:
                    self.record(b["id"], {"verdict": "no_board"})
                    self.ctx.add("ats_jobs.no_board")
                    continue
                sigs, verdict = board_signals(board, b, max_team, now)
                self.record(b["id"], {"verdict": verdict, "board": board.board, "slug": board.slug,
                                      "open_roles": len(board.jobs)})  # fmt: skip
                self.ctx.add(f"ats_jobs.{verdict}")
                out += sigs
        except SourceBlocked as err:
            self.blocked = True
            self.health_blocked(err)
        return out


async def watch(ctx: SourceContext, segments: dict[str, Segment], sink: Any) -> None:
    """Add this source's signals for the enabled segments to the sink."""
    async with AtsJobsAdapter(ctx) as adapter:
        sigs = await adapter.signals_for(segments, limit=ctx.limit)
        if not adapter.blocked:
            adapter.health_ok()
    for sig in sigs:
        seg = segments.get(sig.segment_id or "")
        if seg is not None:
            sink.add(sig, seg)
