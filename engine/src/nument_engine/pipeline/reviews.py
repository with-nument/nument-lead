"""Public review numbers for businesses without Google Places data (the Places fallback, no billing account).

The official Places API needs a Google Cloud billing account. Without one, one Gemini call with Google Search
grounding per business reads the Google rating and review count (and, for clinics in India, Practo's numbers)
that public search results show. Code accepts a number only when a grounding support (a sentence of the answer
that the search results back) contains it; any other number is dropped, never guessed.

Stored the way Places data is: `businesses.review_count` and `rating` (never over Places numbers), the date in
`extra.reviews_at`, and one fact per source whose quote is the supported sentence. Grounded results are kept at
most 30 days, like Places content (A.4.4): older numbers are cleared and looked up again.

Runs in the morning between verify and score, so the businesses researched overnight are scored with them.
A lookup can take half a minute, so the stage stops after `reviews.minutes_per_run` minutes, and earlier when
the run needs the rest of its time for scoring, messages and the email (13 Nov 2026: 25 lookups took 16
minutes and the morning run skipped its messages and email).

Cheaper sources first: a business whose Google numbers the night's Maps lookup confirmed (`extra.maps_reviews`,
kept 30 days) is skipped, and one whose Practo profile research matched (`extra.practo`) is asked for its Google
numbers only. Maps numbers expire after 30 days exactly like grounded ones.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from dateutil import parser as dateparser
from rapidfuzz import fuzz

from .. import db
from ..http import PoliteClient, host_of
from ..logging import get_logger
from ..segments import Segment
from ..sources.base import QUOTE_MAX, Signal, SourceContext
from ..sources.grounded_search import REDIRECT_HOSTS
from . import ai, score
from .runs import RunContext
from .signals import SignalSink

log = get_logger()

TASK: Final = "lookup_reviews"
SETTING: Final = "reviews.lookups_per_day"
DEFAULT_PER_DAY: Final = 120
SETTING_MINUTES: Final = "reviews.minutes_per_run"
DEFAULT_MINUTES: Final = 8
RESERVE_S: Final = 600.0  # kept for score, judge, message and email after this stage
WORKERS: Final = 4  # lookups at once (the router is thread-safe; results are written in the main thread)
MAX_DOWN_STREAK: Final = 3  # consecutive "no usable provider" answers before the stage stops
KEEP_DAYS: Final = 30
SOURCE: Final = "grounded_search"
EXPIRING_SOURCES: Final = (SOURCE, "maps_reviews")  # review numbers kept 30 days like Places content
COUNTRY_NAMES: Final[dict[str, str]] = {"in": "India", "ae": "the UAE", "sa": "Saudi Arabia", "qa": "Qatar"}
KINDS: Final[dict[str, str]] = {
    "clinics": "clinic",
    "realestate": "real estate business",
    "education": "coaching or education",
}

CANDIDATES_SQL: Final = """
select b.id, b.name, b.city, b.country, b.website, b.segment_id, b.extra
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.status in ('researched', 'qualified', 'dormant')
   and b.places_fetched_at is null
   and coalesce((b.extra->>'reviews_lookup_at')::timestamptz, 'epoch') < now() - make_interval(days => %(keep)s)
   and not (coalesce((b.extra #>> '{maps_reviews,matched}')::boolean, false)
            and (b.extra #>> '{maps_reviews,at}')::timestamptz > now() - make_interval(days => %(keep)s)
            and b.review_count is not null)
 order by (b.status = 'researched') desc,
          exists (select 1 from public.signals s where s.business_id = b.id and s.expires_at > now()) desc,
          coalesce(b.branches_count, 1) desc,
          b.researched_at desc nulls last
 limit %(limit)s
"""


def number_supported(value: float | int, texts: list[str]) -> bool:
    """True when the number appears, as a whole number, in a sentence the search results back."""
    variants = {f"{value:g}"}
    if float(value).is_integer():
        n = int(value)
        variants |= {str(n), f"{n:,}", _indian(n)}
    else:
        variants.add(f"{value:.1f}")
    for v in variants:
        pattern = re.compile(rf"(?<![\d.,]){re.escape(v)}(?![\d]|[.,]\d)")
        if any(pattern.search(t) for t in texts):
            return True
    return False


def _indian(n: int) -> str:
    """12,34,567 style grouping (Indian sites write counts this way)."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def supporting_sentence(value: float | int, texts: list[str]) -> str | None:
    for t in texts:
        if number_supported(value, [t]):
            return t.strip()[:300]
    return None


def accepted(output: Any, grounding: dict[str, Any] | None) -> dict[str, Any]:
    """The numbers code can stand behind: in range and backed by a grounding support."""
    texts = [str(s.get("text") or "") for s in (grounding or {}).get("supports") or [] if s.get("text")]
    if not texts or not (grounding or {}).get("sources"):
        return {}
    out: dict[str, Any] = {}
    count, rating = output.google_review_count, output.google_rating
    if count is not None and count >= 1 and number_supported(count, texts):
        out["google"] = {"count": int(count), "quote": supporting_sentence(count, texts)}
        if rating is not None and 1.0 <= rating <= 5.0 and number_supported(rating, texts):
            out["google"]["rating"] = round(float(rating), 1)
    stories, p_rating = output.practo_story_count, output.practo_rating
    if stories is not None and stories >= 1 and number_supported(stories, texts):
        out["practo"] = {"stories": int(stories), "quote": supporting_sentence(stories, texts)}
        if p_rating is not None and 0 < p_rating <= 100 and number_supported(p_rating, texts):
            out["practo"]["rating"] = float(p_rating)
    return out


def expire_old(conn: Any) -> int:
    """Grounded and Maps review numbers older than KEEP_DAYS are cleared, like Places content (A.4.4)."""
    n = conn.execute(
        """update public.businesses
              set review_count = null, rating = null, extra = extra - 'reviews_at' - 'reviews_src'
            where extra->>'reviews_src' = any(%s)
              and places_fetched_at is null
              and (extra->>'reviews_at')::timestamptz < now() - make_interval(days => %s)""",
        [list(EXPIRING_SOURCES), KEEP_DAYS],
    ).rowcount
    conn.execute(
        "delete from public.facts where field in ('google_reviews', 'practo_reviews') "
        "and (model like %s or value->>'source' = 'maps_reviews') "
        "and created_at < now() - make_interval(days => %s)",
        [f"%#{TASK}.%", KEEP_DAYS],
    )
    return int(n or 0)


def practo_covered(b: dict[str, Any], now: datetime) -> bool:
    """Research matched the clinic's Practo profile in the last KEEP_DAYS days (its numbers are facts already)."""
    at = ((b.get("extra") or {}).get("practo") or {}).get("at")
    try:
        return at is not None and (now - datetime.fromisoformat(str(at))).days < KEEP_DAYS
    except ValueError:
        return False


def _inputs(b: dict[str, Any], seg: Segment, now: datetime | None = None) -> dict[str, Any]:
    practo = seg.domain == "clinics" and seg.country == "in" and not practo_covered(b, now or datetime.now(UTC))
    return {
        "name": b["name"],
        "city": b.get("city") or "",
        "country": COUNTRY_NAMES.get(seg.country, seg.country.upper()),
        "kind": KINDS.get(seg.domain, seg.domain),
        "website": b.get("website") or "",
        "practo": practo,
        "roles": seg.job_keywords.frontdesk[:8],  # the intent hunt: front-desk job posts (13 Nov 2026)
    }


def store(conn: Any, b: dict[str, Any], found: dict[str, Any], tag: str, url: str | None, now: datetime) -> None:
    extra = dict(b.get("extra") or {})
    extra["reviews_lookup_at"] = now.isoformat()
    google = found.get("google")
    if google:
        extra["reviews_at"], extra["reviews_src"] = now.isoformat(), SOURCE
        conn.execute(
            "update public.businesses set review_count = %s, rating = coalesce(%s, rating), extra = %s "
            "where id = %s and places_fetched_at is null",
            [google["count"], google.get("rating"), db.Jsonb(extra), b["id"]],
        )
    else:
        conn.execute("update public.businesses set extra = %s where id = %s", [db.Jsonb(extra), b["id"]])
    for field, data in (("google_reviews", google), ("practo_reviews", found.get("practo"))):
        if not data:
            continue
        value = {k: v for k, v in data.items() if k != "quote"} | {"source": SOURCE}
        conn.execute(
            "insert into public.facts (business_id, field, value, quote, url, model, verified, verify_score, verified_at) "
            "values (%s, %s, %s, %s, %s, %s, true, 100, %s)",
            [b["id"], field, db.Jsonb(value), data.get("quote"), url, tag, now],
        )


# ---------------------------------------------------------------------------
# The intent hunt (13 Nov 2026): the same grounded call reports dated signs of need
# ---------------------------------------------------------------------------

SIGNAL_MAX_AGE: Final = timedelta(days=60)
# A search snippet is weaker evidence than a page we read ourselves: below the type's default points.
SNIPPET_POINTS: Final[dict[str, float]] = {"hiring_frontdesk": 6.0, "review_pain": 5.0, "new_branch": 4.0}
LINE_MATCH_MIN: Final = 90  # how closely a line of the answer must match a sentence the search results back
NOTHING: Final = re.compile(r"^\s*(?:none|unknown|not found|no\b|n/?a\b)", re.I)
BRANCH_WORDS: Final = re.compile(
    r"new (?:branch|centre|center|clinic|campus|location)|open(?:s|ed|ing)|launch|inaugurat|second (?:branch|centre)",
    re.I,
)
PAIN_FLAGS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("unanswered_calls", re.compile(r"call|phone|not (?:pick|answer)|unreachable", re.I)),
    ("slow_replies", re.compile(r"repl|respon|whatsapp|message|enquir", re.I)),
    ("booking_trouble", re.compile(r"book|appointment|slot|schedul", re.I)),
    ("long_wait", re.compile(r"wait|delay|late", re.I)),
    ("rude_front_desk", re.compile(r"rude|reception|front desk|staff behaviou?r", re.I)),
)


def _body(line: str | None) -> str:
    """The text after "Hiring:", "New branch:" or "Complaint:"; empty when the answer said none."""
    text = str(line or "").strip()
    head, sep, rest = text.partition(":")
    body = rest.strip() if sep and len(head) <= 12 else text
    return "" if not body or NOTHING.match(body) else body


def supported_line(line: str | None, grounding: dict[str, Any] | None) -> tuple[str, str | None] | None:
    """(the backing sentence, the cited source URI) when a sentence the search results back contains the line."""
    body = _body(line)
    if len(body) < 8 or not grounding or not grounding.get("sources"):
        return None
    sources = grounding.get("sources") or []
    for sup in grounding.get("supports") or []:
        text = str(sup.get("text") or "")
        if text and fuzz.partial_ratio(body.lower(), text.lower()) >= LINE_MATCH_MIN:
            uris = [
                str(sources[i].get("uri"))
                for i in sup.get("chunks") or []
                if isinstance(i, int) and 0 <= i < len(sources) and sources[i].get("uri")
            ]
            return text.strip()[:QUOTE_MAX], (uris[0] if uris else None)
    return None


def _when(text: str | None, now: datetime) -> datetime | None:
    if not text or NOTHING.match(text):
        return None
    try:
        when = dateparser.parse(text, fuzzy=True, default=now.replace(day=1, hour=0, minute=0, second=0))
    except (ValueError, OverflowError):
        return None
    when = when if when.tzinfo else when.replace(tzinfo=UTC)
    return when if when <= now else None


def resolve_citations(signals: list[Signal]) -> list[Signal]:
    """Grounding redirects become the pages they point at, read from the Location header only (nothing at the
    target is fetched, so LinkedIn and job boards stay snippet-only). A redirect that fails is kept as it is."""
    todo = [s for s in signals if s.url and host_of(s.url) in REDIRECT_HOSTS]
    if not todo:
        return signals

    async def resolve() -> dict[str, str]:
        found: dict[str, str] = {}
        async with PoliteClient("review_citations", policy="public", min_gap_s=0.2) as http:
            for sig in todo:
                url = str(sig.url)
                if url not in found:
                    found[url] = await http.location(url) or url
        return found

    try:
        resolved = asyncio.run(resolve())
    except Exception as exc:  # citations are a nicety: never lose the signals over them
        log.warning("reviews.citations_unresolved", error=f"{type(exc).__name__}: {exc}"[:200])
        return signals
    return [replace(s, url=resolved.get(str(s.url), s.url)) if s in todo else s for s in signals]


def intent_signals(
    output: Any, grounding: dict[str, Any] | None, b: dict[str, Any], seg: Segment, now: datetime
) -> list[Signal]:
    """Signals from the lookup answer, each backed by a sentence of the search results; never from memory."""
    out: list[Signal] = []
    key = str(b.get("web_domain") or b["id"])

    def make(kind: str, hit: tuple[str, str | None], when: datetime | None, details: dict[str, Any]) -> Signal:
        observed = when or now
        return Signal(
            type=kind,
            source=SOURCE,
            observed_at=observed,
            url=hit[1],
            quote=hit[0],
            evidence_key=f"{key}|{kind}|{details.get('role') or 'lookup'}|{observed:%Y-%m}".lower(),
            business_id=str(b["id"]),
            details={**details, "snippet_only": True, "date_estimated": when is None, "from": "review_lookup"},
            points=SNIPPET_POINTS[kind],
        )

    role = str(getattr(output, "hiring_role", None) or "").strip()
    frontdesk = [k.lower() for k in seg.job_keywords.frontdesk]
    if role and any(k in role.lower() for k in frontdesk):
        hit = supported_line(getattr(output, "hiring_line", None), grounding)
        posted = _when(getattr(output, "hiring_posted", None), now)
        if hit and (posted is None or now - posted <= SIGNAL_MAX_AGE):
            out.append(make("hiring_frontdesk", hit, posted, {"role": role[:80]}))
    complaint = _body(getattr(output, "complaint_line", None))
    flags = [flag for flag, pattern in PAIN_FLAGS if pattern.search(complaint)]
    if flags:
        hit = supported_line(getattr(output, "complaint_line", None), grounding)
        if hit:
            out.append(make("review_pain", hit, None, {"flags": flags}))
    branch = _body(getattr(output, "branch_line", None))
    if BRANCH_WORDS.search(branch):
        hit = supported_line(getattr(output, "branch_line", None), grounding)
        opened = _when(branch, now)
        if hit and opened is not None and now - opened <= SIGNAL_MAX_AGE:
            out.append(make("new_branch", hit, opened, {}))
    return out


def _lookup(run_result: Any, b: dict[str, Any], seg: Segment, now: datetime) -> tuple[dict[str, Any], Any]:
    inputs = _inputs(b, seg, now)
    return inputs, run_result(TASK, inputs)


def run(rc: RunContext, router: Any = None) -> dict[str, Any]:
    """`nlead reviews`: public review numbers (and dated signs of need) for researched businesses without Places
    data. Up to WORKERS lookups run at once; results are written one at a time in this thread."""
    now = datetime.now(UTC)
    stats: Counter[str] = Counter()
    segments = score.enabled_segments(rc)
    per_day = db.get_setting(SETTING, DEFAULT_PER_DAY)
    limit = int(per_day) if isinstance(per_day, int | float) else DEFAULT_PER_DAY
    if rc.opts.limit:
        limit = min(limit, rc.opts.limit)
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "keep": KEEP_DAYS, "limit": limit})
    stats["candidates"] = len(rows)
    if not rc.opts.dry_run:  # every morning, also when nothing needs a lookup (Maps numbers expire here too)
        with db.tx("engine", {"run_id": rc.run_id, "stage": "reviews"}) as conn:
            stats["expired"] = expire_old(conn)
    if rc.opts.dry_run or not rows:
        rc.stats["reviews"] = dict(stats)
        return dict(stats)
    router = router or ai.router_for(rc)
    run_result = getattr(router, "run_result", None) if router is not None else None
    if run_result is None:
        stats["skipped_no_router"] = len(rows)
        rc.stats["reviews"] = dict(stats)
        return dict(stats)
    budget = getattr(router, "budget", None)
    spent = 0.0
    down_streak = 0
    minutes = db.get_setting(SETTING_MINUTES, DEFAULT_MINUTES)
    stop_at = time.monotonic() + min(
        float(minutes) * 60.0 if isinstance(minutes, int | float) else DEFAULT_MINUTES * 60.0,
        max(0.0, rc.time_left() - RESERVE_S),
    )
    found_signals: list[tuple[Signal, Segment]] = []
    pending = deque(rows)
    running: dict[Future[tuple[dict[str, Any], Any]], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="reviews") as pool:
        while pending or running:
            while pending and len(running) < WORKERS:
                if time.monotonic() >= stop_at:
                    stats["stopped_time"] = len(pending)  # left for the next morning
                    pending.clear()
                    break
                quota = (
                    budget.grounding_quota_left()
                    if budget is not None and hasattr(budget, "grounding_quota_left")
                    else 1
                )
                if quota is not None and quota <= len(running):
                    stats["stopped_quota"] += 1
                    pending.clear()
                    break
                b = pending.popleft()
                running[pool.submit(_lookup, run_result, b, segments[b["segment_id"]], now)] = b
            if not running:
                break
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                b = running.pop(fut)
                seg = segments[b["segment_id"]]
                try:
                    inputs, res = fut.result()
                except Exception as exc:  # typed router errors: stop on budget, skip one stubborn business
                    name = type(exc).__name__
                    stats[f"error.{name}"] += 1
                    down_streak += name == "AllProvidersDown"
                    # One business whose answers never cite a search must not stop the stage (live run 12 Nov);
                    # three in a row look like a real outage.
                    if name in ("BudgetExceeded", "BudgetStop") or down_streak >= MAX_DOWN_STREAK:
                        log.warning("reviews.stopped", reason=f"{name}: {str(exc)[:200]}")
                        pending.clear()
                    continue
                down_streak = 0
                stats["practo_covered"] += seg.domain == "clinics" and seg.country == "in" and not inputs["practo"]
                found = accepted(res.output, res.grounding)
                sources = (res.grounding or {}).get("sources") or []
                url = str(sources[0].get("uri")) if sources else None
                with db.tx("engine", {"run_id": rc.run_id, "stage": "reviews"}) as conn:
                    store(conn, b, found, res.tag, url, now)
                for sig in intent_signals(res.output, res.grounding, b, seg, now):
                    found_signals.append((sig, seg))
                    stats[f"signal.{sig.type}"] += 1
                stats["looked_up"] += 1
                stats["google_found"] += "google" in found
                stats["practo_found"] += "practo" in found
                spent += float(getattr(res, "inr", 0) or 0)
    if found_signals:
        sink = SignalSink(segments, SourceContext.from_run(rc, router))
        urls = resolve_citations([sig for sig, _ in found_signals])
        for sig, (_, seg) in zip(urls, found_signals, strict=True):
            sink.add(sig, seg)
        sink.flush()
    result: dict[str, Any] = {**stats, "inr": round(spent, 2)}
    rc.stats["reviews"] = result
    log.info("reviews.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
