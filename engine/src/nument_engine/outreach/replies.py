"""Sort replies (classify_reply), act on them, and draft the answers the founder approves (draft_reply).

Contract 4.6, phase `replies`, after `inbox`. Every received message gets a classification and a confidence;
the ones that deserve an answer get `suggested_reply` and a new outgoing message (`step` NULL) waiting in
`review`. What happens by category:

- unsubscribe: always honoured, at any confidence and without AI when the words are unmistakable ("please
  remove me"): suppression, `do_not_contact`, thread `done`, everything unsent cancelled. The lead closes as lost.
- out_of_office (confidence 0.85 or more, and no person has answered): the thread opens again with the steps
  the reply cancelled, paused until the day after the return date (or 7 days); the remaining steps move with it.
- not_now (0.85 or more): the lead closes as not now and comes back in 60 days (`due_at`, thread `paused_until`).
- interested, send_plan, question, wrong_person, not_now: a draft in the voice of Team Nument. Buyers get the
  Cal.com link prefilled with their name and email and three times that suit both sides in their time zone.
  An `interested` or `send_plan` reply also emails the founder at once (the alert path of `ops.emails`).
- Any person's answer (not an auto-reply, not "other") moves a contacted lead to talking, like the app's
  one-tap Replied.

Nothing is sent from here. A draft waits for the founder in `review`; only with `settings outreach.auto_replies`
on, outreach in auto mode, a confidence of 0.85 or more and a founder-approved template in
`settings outreach.reply_templates` for send_plan, not_now or wrong_person does a reply go out as `approved`.
A draft never names a person at Nument: it is signed "Team Nument".
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from typing import Any, Final
from urllib.parse import quote, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jinja2
from psycopg import Connection, errors

from .. import db
from ..logging import get_logger
from ..models import ReplyClassification, ReplyDraft
from ..ops import emails, notify
from ..pipeline import ai
from ..pipeline.runs import RunContext, outreach_mode
from ..settings import get_settings
from .inbox import activity, addr, honour_unsubscribe, new_text, our_addresses

log = get_logger()

BOOKING_URL: Final = "https://cal.com/abhigyan-numentai/intro-call"
SIGN_OFF: Final = "Team Nument"
SAFE_CONFIDENCE: Final = 0.85
DRAFT_CATEGORIES: Final = ("interested", "send_plan", "question", "not_now", "wrong_person")
ALWAYS_LINK: Final = ("interested", "send_plan")
ALERT_CATEGORIES: Final = ("interested", "send_plan")
TEMPLATE_CATEGORIES: Final = ("send_plan", "not_now", "wrong_person")  # the plan's safe types with a template
REPLIED: Final = ("interested", "send_plan", "question", "not_now", "wrong_person", "unsubscribe")
NOT_NOW_DAYS: Final = 60
OOO_DEFAULT_DAYS: Final = 7
OOO_MAX_DAYS: Final = 60
REPLY_MAX_CHARS: Final = 4000
OUR_EMAIL_MAX_CHARS: Final = 2000
RULE_MAX_CHARS: Final = 600  # an opt-out rule decides only short replies; longer ones go to the classifier
AI_FAILURES_BEFORE_STOP: Final = 3
ALERT_WITHIN: Final = timedelta(days=2)
DRAFT_RETRY_WITHIN: Final = timedelta(days=7)
PLAN_PLACEHOLDER: Final = "{plan_link}"
DEFAULT_CALL_HOURS: Final[dict[str, Any]] = {
    "zone": "Asia/Kolkata",
    "days": [0, 1, 2, 3, 4],
    "windows": [["08:00", "10:00"], ["18:00", "23:00"]],
}
CATEGORY_LABEL: Final[dict[str, str]] = {
    "interested": "interested",
    "send_plan": "wants the plan",
    "question": "has a question",
    "not_now": "not now",
    "out_of_office": "out of office",
    "wrong_person": "wrong person",
    "unsubscribe": "asked to stop",
    "other": "other",
}

_OPT_OUT: Final = re.compile(
    r"\bunsubscribe\b"
    r"|\bremove (?:me|us|my (?:email|address)|our (?:email|address))\b.{0,40}\b(?:list|lists|mailing|emails?)\b"
    r"|\btake (?:me|us) off\b"
    r"|\bstop (?:emailing|e-?mailing|messaging|contacting|spamming|writing to) (?:me|us)\b"
    r"|\b(?:do not|don't|dont) (?:email|e-?mail|contact|message|write to) (?:me|us) (?:again|anymore|any more)\b"
    r"|\bopt (?:me |us )?out\b",
    re.I,
)
_URL: Final = re.compile(r"https?://[^\s<>()\"']+")
_PLACEHOLDER: Final = re.compile(r"\{[a-z_]+\}")
_DASH: Final = re.compile("\\s*[\u2013\u2014]\\s*")


# ---------------------------------------------------------------------------
# The recipient's time zone and three call times that suit both sides
# ---------------------------------------------------------------------------

COUNTRY_ZONES: Final[dict[str, str]] = {
    "in": "Asia/Kolkata",
    "ae": "Asia/Dubai",
    "us": "America/New_York",
    "gb": "Europe/London",
    "ie": "Europe/Dublin",
    "nl": "Europe/Amsterdam",
    "fr": "Europe/Paris",
    "se": "Europe/Stockholm",
    "fi": "Europe/Helsinki",
    "be": "Europe/Brussels",
    "pt": "Europe/Lisbon",
    "au": "Australia/Sydney",
    "nz": "Pacific/Auckland",
    "ca": "America/Toronto",
    "sg": "Asia/Singapore",
    "br": "America/Sao_Paulo",
    "mx": "America/Mexico_City",
    "ph": "Asia/Manila",
    "my": "Asia/Kuala_Lumpur",
    "id": "Asia/Jakarta",
}
# Countries with more than one zone: the cities startups are in.
CITY_ZONES: Final[dict[str, str]] = {
    **dict.fromkeys(
        (
            "san francisco", "los angeles", "seattle", "portland", "san diego", "san jose", "palo alto",
            "mountain view", "oakland", "santa monica", "las vegas", "sacramento", "irvine", "berkeley",
            "menlo park", "sunnyvale", "redwood city", "santa clara", "bellevue", "pasadena",
        ),
        "America/Los_Angeles",
    ),
    **dict.fromkeys(("denver", "boulder", "salt lake city", "albuquerque"), "America/Denver"),
    **dict.fromkeys(("phoenix", "scottsdale", "tempe"), "America/Phoenix"),
    **dict.fromkeys(
        (
            "austin", "dallas", "houston", "chicago", "minneapolis", "nashville", "kansas city", "st. louis",
            "st louis", "san antonio", "new orleans", "madison", "milwaukee", "oklahoma city", "omaha",
        ),
        "America/Chicago",
    ),
    **dict.fromkeys(("honolulu",), "Pacific/Honolulu"),
    **dict.fromkeys(("anchorage",), "America/Anchorage"),
    **dict.fromkeys(("vancouver", "victoria"), "America/Vancouver"),
    **dict.fromkeys(("calgary", "edmonton"), "America/Edmonton"),
    **dict.fromkeys(("winnipeg",), "America/Winnipeg"),
    **dict.fromkeys(("halifax",), "America/Halifax"),
    **dict.fromkeys(("perth",), "Australia/Perth"),
    **dict.fromkeys(("brisbane", "gold coast"), "Australia/Brisbane"),
    **dict.fromkeys(("adelaide",), "Australia/Adelaide"),
    **dict.fromkeys(("melbourne",), "Australia/Melbourne"),
    **dict.fromkeys(("darwin",), "Australia/Darwin"),
    **dict.fromkeys(("hobart",), "Australia/Hobart"),
    **dict.fromkeys(("tijuana",), "America/Tijuana"),
    **dict.fromkeys(("manaus",), "America/Manaus"),
    **dict.fromkeys(("bali", "denpasar"), "Asia/Makassar"),
}  # fmt: skip


def recipient_zone(country: str | None, city: str | None) -> ZoneInfo:
    """The recipient's zone: their city where a country has several zones, else the country's main zone (UTC
    when the country is unknown)."""
    name = CITY_ZONES.get((city or "").strip().lower()) or COUNTRY_ZONES.get((country or "").strip().lower(), "UTC")
    return ZoneInfo(name)


def zone_label(zone: ZoneInfo) -> str:
    """'New York time', 'London time', 'India time'."""
    key = str(zone.key)
    if key == "Asia/Kolkata":
        return "India time"
    if key == "UTC":
        return "UTC"
    return f"{key.rsplit('/', 1)[-1].replace('_', ' ')} time"


@dataclass(frozen=True)
class CallHours:
    """When the founder takes calls: weekdays and windows in his zone (settings outreach.call_hours)."""

    zone: ZoneInfo
    days: frozenset[int]
    windows: tuple[tuple[time, time], ...]

    def open_at(self, t: datetime, length: timedelta) -> bool:
        local = t.astimezone(self.zone)
        if local.weekday() not in self.days:
            return False
        start = local.time().replace(tzinfo=None)
        end = (local + length).time().replace(tzinfo=None)
        for a, b in self.windows:
            if a <= b and a <= start and (local + length).date() == local.date() and end <= b:
                return True
            if a > b and (start >= a or end <= b):  # a window over midnight
                return True
        return False


def _hhmm(text: Any) -> time | None:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(text).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def call_hours(raw: Any = None) -> CallHours:
    """settings outreach.call_hours, falling back to the default for anything missing or malformed."""
    cfg = raw if isinstance(raw, Mapping) else {}
    try:
        zone = ZoneInfo(str(cfg.get("zone") or DEFAULT_CALL_HOURS["zone"]))
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(DEFAULT_CALL_HOURS["zone"])
    days_raw = cfg.get("days")
    days = frozenset(int(d) for d in days_raw if str(d).isdigit() and int(d) < 7) if isinstance(days_raw, list) else ()
    windows: list[tuple[time, time]] = []
    raw_windows = cfg.get("windows")
    for pair in raw_windows if isinstance(raw_windows, list) else []:
        if isinstance(pair, list | tuple) and len(pair) == 2:
            a, b = _hhmm(pair[0]), _hhmm(pair[1])
            if a is not None and b is not None and a != b:
                windows.append((a, b))
    if not windows:
        windows = [(_hhmm(a) or time(9), _hhmm(b) or time(17)) for a, b in DEFAULT_CALL_HOURS["windows"]]
    return CallHours(zone, frozenset(days) or frozenset(DEFAULT_CALL_HOURS["days"]), tuple(windows))


def suggest_times(
    now: datetime,
    their_zone: ZoneInfo,
    hours: CallHours,
    *,
    count: int = 3,
    length: timedelta = timedelta(minutes=30),
    lead_time: timedelta = timedelta(hours=18),
    horizon: timedelta = timedelta(days=9),
) -> list[datetime]:
    """Up to `count` call starts on different weekdays of theirs, inside the founder's call hours and their
    working day (09:00 to 18:00; 08:00 to 20:00 when that finds too few), at least `lead_time` away so the
    founder can approve the reply first. Half-hour marks, UTC."""
    first = now.astimezone(UTC) + lead_time
    first = first.replace(second=0, microsecond=0)
    first += timedelta(minutes=(30 - first.minute % 30) % 30)
    best: list[datetime] = []
    for day_start, day_end in ((time(9), time(18)), (time(8), time(20))):
        picks: list[datetime] = []
        days: set[date] = set()
        t = first
        while t < now + horizon and len(picks) < count:
            local = t.astimezone(their_zone)
            end = local + length
            if (
                local.weekday() < 5
                and local.date() not in days
                and local.time() >= day_start
                and end.date() == local.date()
                and end.time() <= day_end
                and hours.open_at(t, length)
            ):
                picks.append(t)
                days.add(local.date())
            t += timedelta(minutes=30)
        if len(picks) >= count:
            return picks
        best = picks if len(picks) > len(best) else best
    return best


def time_text(t: datetime, zone: ZoneInfo) -> str:
    """'Wed 18 Nov, 9:30 am' in that zone."""
    local = t.astimezone(zone)
    hour = local.hour % 12 or 12
    return f"{local:%a} {local.day} {local:%b}, {hour}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"


def booking_link(base: str, *, email: str | None, name: str | None) -> str:
    """The Cal.com page with the person's name and email filled in (URL-encoded), so booking takes one click."""
    params = {k: v for k, v in (("name", (name or "").strip()), ("email", addr(email))) if v}
    if not params:
        return base
    return f"{base}{'&' if '?' in base else '?'}{urlencode(params, quote_via=quote)}"


def first_name(name: str | None) -> str:
    """'Maya' from 'Maya Chen'; '' when the name is an address, a company or too short to trust."""
    raw = (name or "").strip().strip('"')
    if not raw or "@" in raw:
        return ""
    word = re.split(r"[\s,]+", raw)[0].strip(".")
    if len(word) < 2 or not word.replace("-", "").replace("'", "").isalpha():
        return ""
    return word.capitalize() if word.islower() or word.isupper() else word


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def opt_out_rule(text: str) -> bool:
    """Unmistakable opt-out words in a short reply ("please remove me from your list")."""
    clean = new_text(text)
    return bool(clean) and len(clean) <= RULE_MAX_CHARS and bool(_OPT_OUT.search(clean))


def tidy_classification(out: ReplyClassification, reply_text: str, ours: set[str]) -> ReplyClassification:
    """Keep only what the reply really says: a return date that parses, a referral name and address that are
    written in it (never one of ours)."""
    lowered = reply_text.lower()
    ret: str | None = None
    if out.return_date:
        try:
            ret = date.fromisoformat(out.return_date.strip()).isoformat()
        except ValueError:
            ret = None
    email = addr(out.referral_email)
    if not email or email not in lowered or email in ours or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email):
        email = ""
    name = (out.referral_name or "").strip()
    if name and name.lower() not in lowered:
        name = ""
    return out.model_copy(
        update={
            "confidence": min(1.0, max(0.0, float(out.confidence))),
            "return_date": ret,
            "referral_email": email or None,
            "referral_name": name or None,
        }
    )


# ---------------------------------------------------------------------------
# Loading what a reply needs
# ---------------------------------------------------------------------------

_PENDING: Final = """
select m.id::text as id, m.thread_id::text as thread_id, m.subject, m.body, m.sent_at as received_at, m.created_at,
       m.classification, m.classification_confidence, m.suggested_reply,
       t.lead_id::text as lead_id, t.status as thread_status, t.stop_reason, t.to_email, t.to_domain,
       t.contact_id::text as contact_id,
       l.stage, l.business_id::text as business_id, b.name as company, b.country, b.city,
       c.name as contact_name,
       er.payload as received
  from public.email_messages m
  join public.email_threads t on t.id = m.thread_id
  join public.leads l on l.id = t.lead_id
  join public.businesses b on b.id = l.business_id
  left join public.contacts c on c.id = t.contact_id
  left join lateral (
      select a.payload from public.activities a
       where a.lead_id = t.lead_id and a.type = 'email_received' and a.payload ->> 'message_id' = m.id::text
       order by a.at desc limit 1
  ) er on true
 where m.direction = 'in' and m.status = 'received'
"""


@dataclass
class Reply:
    """One received message with its thread, lead and sender."""

    row: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def lead_id(self) -> str:
        return str(self.row["lead_id"])

    @property
    def thread_id(self) -> str:
        return str(self.row["thread_id"])

    @property
    def text(self) -> str:
        """What they wrote (quoted history removed), or the whole body when nothing is left."""
        body = str(self.row.get("body") or "")
        return (new_text(body) or body.strip())[:REPLY_MAX_CHARS]

    @property
    def sender(self) -> str:
        received = self.row.get("received") or {}
        return addr(received.get("from_email")) or addr(self.row.get("to_email"))

    @property
    def name(self) -> str | None:
        """The sender's name: the contact's when the contact wrote, else the name in their From line."""
        received = self.row.get("received") or {}
        if self.sender == addr(self.row.get("to_email")) and self.row.get("contact_name"):
            return str(self.row["contact_name"])
        return received.get("from_name") or None


def our_last_email(conn: Connection[Any] | None, reply: Reply) -> str:
    """The last email we sent in the thread before this reply (day 0 when nothing else)."""
    row = db.fetch_one(
        """
        select body from public.email_messages
         where thread_id = %s and direction = 'out' and status = 'sent'
           and (sent_at is null or %s::timestamptz is null or sent_at <= %s)
         order by sent_at desc nulls last, step desc nulls last limit 1
        """,
        [reply.thread_id, reply.row.get("received_at"), reply.row.get("received_at")],
        conn=conn,
    )
    return str((row or {}).get("body") or "")[:OUR_EMAIL_MAX_CHARS]


def offer_for(conn: Connection[Any] | None, lead_id: str) -> dict[str, Any] | None:
    return db.fetch_one(
        """
        select o.key, o.name, o.promise, o.timeline, o.typical_range, lo.why_now
          from public.lead_offers lo join public.offers o on o.key = lo.offer_key
         where lo.lead_id = %s order by lo.rank limit 1
        """,
        [lead_id],
        conn=conn,
    )


def typical_range_text(typical: Any) -> str:
    """'usually $3,000 to $12,000' from the offer's typical_range (USD), or ''."""
    if not isinstance(typical, Mapping):
        return ""
    for key, suffix in (("usd", ""), ("usd_month", " a month")):
        pair = typical.get(key)
        if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, int | float) for x in pair):
            return f"usually ${pair[0]:,.0f} to ${pair[1]:,.0f}{suffix}"
    return ""


def plan_url(conn: Connection[Any] | None, lead_id: str) -> str | None:
    """The lead's live plan page, `{APP_URL}/p/{token}` (contract 4.7), when E4 has written one."""
    row = db.fetch_one(
        "select token from public.plan_pages where lead_id = %s and kind = 'plan' and status = 'live' "
        "and expires_at > now() order by created_at desc limit 1",
        [lead_id],
        conn=conn,
    )
    return f"{get_settings().app_url.rstrip('/')}/p/{row['token']}" if row else None


# ---------------------------------------------------------------------------
# Acting on a classification
# ---------------------------------------------------------------------------


def mark_replied(conn: Connection[Any], lead_id: str) -> None:
    """A person answered: a new or contacted lead is now talking (the app's one-tap Replied)."""
    conn.execute("update public.leads set stage = 'talking' where id = %s and stage in ('new', 'contacted')", [lead_id])


def return_after(ret: str | None, zone: ZoneInfo, now: datetime) -> datetime:
    """09:00 their time on the day after the return date; 7 days from now without one; never over 60 days."""
    if ret:
        try:
            back = date.fromisoformat(ret) + timedelta(days=1)
            when = datetime.combine(back, time(9), tzinfo=zone).astimezone(UTC)
            if when > now:
                return min(when, now + timedelta(days=OOO_MAX_DAYS))
        except ValueError:
            pass
    return now + timedelta(days=OOO_DEFAULT_DAYS)


def reopen_after_auto_reply(conn: Connection[Any], reply: Reply, until: datetime) -> bool:
    """Put back the steps an auto-reply cancelled and open the thread again, paused until `until`.

    Only when the thread was stopped by a reply and every message received since then is an auto-reply; the
    remaining steps keep their spacing, the first one moved to `until` at the earliest.
    """
    thread = db.fetch_one(
        "select id, status, stop_reason from public.email_threads where id = %s for update",
        [reply.thread_id],
        conn=conn,
    )
    if thread is None or thread["status"] != "stopped" or thread["stop_reason"] != "reply":
        return False
    stop = db.fetch_one(
        "select at, payload from public.activities where lead_id = %s and type = 'sequence_stopped' "
        "and payload ->> 'thread_id' = %s and payload ->> 'reason' = 'reply' order by at desc, id desc limit 1",
        [reply.lead_id, reply.thread_id],
        conn=conn,
    )
    if stop is None:
        return False
    people = db.fetch_one(
        "select count(*) as n from public.email_messages where thread_id = %s and direction = 'in' and id <> %s "
        "and created_at >= %s - interval '1 second' and coalesce(classification, '') <> 'out_of_office'",
        [reply.thread_id, reply.id, stop["at"]],
        conn=conn,
    )
    if people and people["n"]:
        return False
    ids = [str(c["id"]) for c in (stop["payload"] or {}).get("cancelled", [])]
    previous = {str(c["id"]): str(c["status"]) for c in (stop["payload"] or {}).get("cancelled", [])}
    try:
        with conn.transaction():
            restored = db.fetch_all(
                "select id::text as id, scheduled_for from public.email_messages "
                "where id = any(%s::uuid[]) and status = 'cancelled' for update",
                [ids],
                conn=conn,
            )
            for r in restored:
                conn.execute(
                    "update public.email_messages set status = %s, updated_at = now() where id = %s",
                    [previous[r["id"]], r["id"]],
                )
            scheduled = [r["scheduled_for"] for r in restored if r["scheduled_for"] is not None]
            if scheduled and min(scheduled) < until:
                conn.execute(
                    "update public.email_messages set scheduled_for = scheduled_for + %s "
                    "where id = any(%s::uuid[]) and scheduled_for is not null",
                    [until - min(scheduled), [r["id"] for r in restored]],
                )
            conn.execute(
                "update public.email_threads set status = 'open', stop_reason = null, paused_until = %s, "
                "updated_at = now() where id = %s",
                [until, reply.thread_id],
            )
    except errors.UniqueViolation:  # the lead has another open thread: leave this one stopped
        return False
    return True


def apply_classification(
    conn: Connection[Any],
    reply: Reply,
    out: ReplyClassification,
    *,
    tag: str,
    now: datetime,
    ours: set[str],
) -> dict[str, Any]:
    """Store the classification and do what it means (module docstring). Returns what was done."""
    done: dict[str, Any] = {}
    conn.execute(
        "update public.email_messages set classification = %s, classification_confidence = %s, updated_at = now() "
        "where id = %s",
        [out.category, round(out.confidence, 2), reply.id],
    )
    sure = out.confidence >= SAFE_CONFIDENCE
    if out.category in REPLIED:
        mark_replied(conn, reply.lead_id)
    if out.category == "unsubscribe":
        thread = {**reply.row, "id": reply.thread_id, "lead_id": reply.lead_id}
        if reply.row.get("thread_status") != "done" or reply.row.get("stop_reason") != "unsubscribe":
            honour_unsubscribe(conn, thread, [reply.sender], how="reply", message_id=reply.id)
        conn.execute(
            "update public.leads set stage = 'lost', lost_reason = 'other', next_step = null, due_at = null "
            "where id = %s and stage in ('new', 'contacted', 'talking')",
            [reply.lead_id],
        )
        done["unsubscribed"] = True
    elif out.category == "out_of_office" and sure:
        zone = recipient_zone(reply.row.get("country"), reply.row.get("city"))
        until = return_after(out.return_date, zone, now)
        done["resumed"] = reopen_after_auto_reply(conn, reply, until)
        done["paused_until"] = until.isoformat()
    elif out.category == "not_now" and sure:
        back = now + timedelta(days=NOT_NOW_DAYS)
        conn.execute(
            "update public.leads set stage = 'not_now', lost_reason = 'no_need_now', "
            "next_step = 'Check back: they said not now', due_at = %s "
            "where id = %s and stage in ('new', 'contacted', 'talking')",
            [back.date(), reply.lead_id],
        )
        conn.execute(
            "update public.email_threads set paused_until = %s, updated_at = now() where id = %s and status <> 'done'",
            [back, reply.thread_id],
        )
        done["check_back"] = back.date().isoformat()
    activity(
        conn,
        reply.lead_id,
        "ai_output",
        {
            "kind": "reply_classified",
            "message_id": reply.id,
            "thread_id": reply.thread_id,
            "category": out.category,
            "confidence": round(out.confidence, 2),
            "summary": out.summary,
            "return_date": out.return_date,
            "referral_name": out.referral_name,
            "referral_email": out.referral_email,
            "model": tag,
            **done,
        },
    )
    return done


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------


@dataclass
class DraftContext:
    """What a draft for one reply may contain."""

    category: str
    first: str
    company: str
    link: str  # the prefilled booking link, or "" when this answer should not offer a call
    base_link: str
    times: list[str] = field(default_factory=list)
    zone_label: str = ""
    plan_link: str | None = None
    plan_pending: bool = False
    referral_name: str | None = None
    referral_email: str | None = None

    @property
    def private_words(self) -> list[str]:
        """Words of the Cal.com page name (a person's name) that must never appear outside the link itself."""
        path = urlsplit(self.base_link).path.strip("/").split("/")[0]
        return [w for w in re.split(r"[-_.]", path) if len(w) >= 3 and w.lower() not in ("nument", "numentai", "team")]


def draft_problems(body: str, ctx: DraftContext) -> list[str]:
    """What is wrong with a draft, in words a writer can fix."""
    problems: list[str] = []
    allowed = {ctx.link, ctx.plan_link} - {"", None}
    for url in _URL.findall(body):
        clean = url.rstrip(".,;:!?")
        if clean not in allowed and clean != ctx.base_link:
            problems.append(f"remove the link {clean}: only the booking link or the plan link may appear")
    outside = _URL.sub(" ", body).lower()
    for word in ctx.private_words:
        if re.search(rf"\b{re.escape(word.lower())}\b", outside):
            problems.append("never name a person at Nument: sign as Team Nument only")
    for ph in _PLACEHOLDER.findall(body):
        if not (ph == PLAN_PLACEHOLDER and ctx.plan_pending):
            problems.append(f"remove the placeholder {ph}")
    if ctx.plan_link and ctx.category == "send_plan" and ctx.plan_link not in body:
        problems.append(f"include the plan link exactly: {ctx.plan_link}")
    words = len(body.split())
    if words > 170:
        problems.append(f"too long ({words} words): keep it under 110 words")
    return problems


def finish(body: str, ctx: DraftContext) -> str:
    """The code's part of every draft: plain dashes, the prefilled link, the times, one Team Nument sign-off."""
    text = _DASH.sub(", ", body.replace("\r\n", "\n")).strip()
    if ctx.link:
        text = re.sub(rf"{re.escape(ctx.base_link)}(?![?\w/-])", ctx.link, text)
    lines = text.split("\n")
    while lines and lines[-1].strip().lower().rstrip(",.") in ("", "team nument", "the nument team", "nument"):
        lines.pop()
    while lines and lines[-1].strip().lower().rstrip(",") in ("best", "thanks", "cheers", "regards", "best regards"):
        lines.pop()
    text = "\n".join(lines).rstrip()
    extra: list[str] = []
    if ctx.link and ctx.times and not any(t in text for t in ctx.times):
        extra.append(f"A few times that work on our side ({ctx.zone_label}): {join_or(ctx.times)}.")
    if ctx.link and ctx.link not in text:
        extra.append(f"You can pick any time that suits you here: {ctx.link}")
    if ctx.plan_link and ctx.category == "send_plan" and ctx.plan_link not in text:
        extra.insert(0, f"Here's the 1-page plan for {ctx.company}: {ctx.plan_link}")
    return "\n\n".join([text, *extra, SIGN_OFF]).strip()


def join_or(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def fallback(ctx: DraftContext) -> str:
    """A plain, safe answer when the writer is unavailable or keeps breaking the rules."""
    hi = f"Hi {ctx.first}," if ctx.first else "Hi,"
    plan = ctx.plan_link or (PLAN_PLACEHOLDER if ctx.plan_pending else "")
    times = f"\n\nA few times that work on our side ({ctx.zone_label}): {join_or(ctx.times)}." if ctx.times else ""
    pick = f"\n\nOr pick any slot here: {ctx.link}" if ctx.link else ""
    body = {
        "interested": "Great to hear from you. The easiest next step is a 20-minute call, so we understand what "
        f"you're building and where we can help.{times}{pick}",
        "send_plan": (f"Here's the 1-page plan for {ctx.company}: {plan}" if plan else "Glad you'd like the plan.")
        + f"\n\nHappy to walk you through it on a 20-minute call.{times}{pick}",
        "question": f"Good question. It depends a little on scope, so the quickest way to a real answer is a short "
        f"call.{times}{pick}",
        "not_now": "No problem at all, thanks for letting us know. We'll check back in a couple of months.",
        "wrong_person": (
            f"Thanks for pointing us to {ctx.referral_name or ctx.referral_email}. We'll reach out to them directly."
            if ctx.referral_name or ctx.referral_email
            else f"Thanks for letting us know. Who would be the right person to talk to about product at {ctx.company}?"
        ),
    }.get(ctx.category, "Thanks for your reply.")
    return f"{hi}\n\n{body}\n\n{SIGN_OFF}"


def from_template(template: str, ctx: DraftContext) -> str | None:
    """A founder-approved template with {first_name}, {company}, {plan_link} and {booking_link} filled in; None
    when it needs something we do not have."""
    values = {
        "first_name": ctx.first or "there",
        "company": ctx.company,
        "plan_link": ctx.plan_link or "",
        "booking_link": ctx.link or ctx.base_link,
    }
    for name in _PLACEHOLDER.findall(template):
        key = name.strip("{}")
        if key not in values or not values[key]:
            return None
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text.strip()


def draft_inputs(reply: Reply, ctx: DraftContext, out: ReplyClassification, extra: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "founder_name": reply.name or "",
        "first_name": ctx.first,
        "company": ctx.company,
        "reply": reply.text,
        "category": ctx.category,
        "summary": out.summary,
        "booking_link": ctx.link,
        "suggested_times": ctx.times,
        "time_zone": ctx.zone_label,
        "plan_link": ctx.plan_link or (PLAN_PLACEHOLDER if ctx.plan_pending else ""),
        "referral_name": ctx.referral_name or "",
        "referral_email": ctx.referral_email or "",
        **extra,
    }


# ---------------------------------------------------------------------------
# The founder's alert
# ---------------------------------------------------------------------------

ALERT_HTML: Final = """{% extends "base.html" %}
{% set sans = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif" %}
{% block body %}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr><td class="pad" style="padding:32px 36px 8px 36px;">
    <div style="font:600 12px/16px {{ sans }};letter-spacing:.08em;text-transform:uppercase;color:#496D21;">{{ label }}</div>
    <div class="h1" style="font:400 30px/38px Georgia,'Times New Roman',serif;color:#1f1f1f;margin:10px 0 8px 0;">{{ headline }}</div>
    <div style="font:400 15px/23px {{ sans }};color:#666666;">{{ summary }}</div>
  </td></tr>
  <tr><td class="pad" style="padding:20px 36px 0 36px;">
    <div style="font:600 13px/20px {{ sans }};color:#999999;">What they wrote</div>
    <div style="font:400 15px/23px {{ sans }};color:#1f1f1f;white-space:pre-wrap;border-left:3px solid #ececec;padding:4px 0 4px 14px;margin-top:6px;">{{ reply }}</div>
  </td></tr>
  {% if draft %}
  <tr><td class="pad" style="padding:20px 36px 0 36px;">
    <div style="font:600 13px/20px {{ sans }};color:#999999;">Our drafted answer, waiting for you</div>
    <div style="font:400 15px/23px {{ sans }};color:#1f1f1f;white-space:pre-wrap;border-left:3px solid #E3F1D8;padding:4px 0 4px 14px;margin-top:6px;">{{ draft }}</div>
  </td></tr>
  {% endif %}
  <tr><td class="pad" style="padding:20px 36px 32px 36px;">
    <a class="btn" href="{{ lead_url }}" style="display:inline-block;background:#2a2c33;color:#ffffff;font:600 14px/20px {{ sans }};text-decoration:none;padding:10px 18px;border-radius:10px;">Review and send</a>
  </td></tr>
</table>
{% endblock %}
{% block footer %}Sent when a founder replies with interest.{% endblock %}
"""


@lru_cache
def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(emails.TEMPLATES),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


@lru_cache(maxsize=8)
def _template(source: str) -> jinja2.Template:
    return _env().from_string(source)


def render(source: str, **context: Any) -> str:
    """An email body that extends the founder-approved base.html (the same look as every engine email)."""
    base = {"app_url": emails.app_url(), "preheader": "", "date_label": ""}
    return _template(source).render(**{**base, **context})


def alert_email(reply: Reply, category: str, summary: str, draft: str | None) -> notify.Email:
    who = first_name(reply.name) or "A founder"
    company = str(reply.row.get("company") or "a startup")
    label = CATEGORY_LABEL.get(category, category)
    subject = f"{who} at {company} replied: {label}"
    lead_url = f"{emails.app_url()}/leads/{reply.lead_id}"
    text = reply.text
    html = render(
        ALERT_HTML,
        subject=subject,
        preheader=emails.cut(text, 120),
        date_label=emails.day_label(datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()),
        label=label,
        headline=f"{who} at {company} replied",
        summary=summary,
        reply=text,
        draft=draft or "",
        lead_url=lead_url,
    )
    lines = [f"{who} at {company} replied ({label}).", summary, "", "What they wrote:", text, ""]
    if draft:
        lines += ["Our drafted answer, waiting for you:", draft, ""]
    lines += [f"Review and send: {lead_url}"]
    return notify.Email(subject, html, "\n".join(lines) + "\n")


def send_alert(reply: Reply, category: str, summary: str, draft: str | None) -> int:
    """Email the founder (alert recipients) through Resend; 0 when email is not set up."""
    email = alert_email(reply, category, summary, draft)
    return emails.deliver("alerts", lambda admin: email)


# ---------------------------------------------------------------------------
# The phase
# ---------------------------------------------------------------------------


@dataclass
class Replier:
    rc: RunContext
    router: ai.AIRouter | None
    now: datetime
    ours: set[str]
    stats: Counter[str] = field(default_factory=Counter)
    failures: int = 0
    stopped: bool = False

    # -- classification ----------------------------------------------------
    def classify(self, reply: Reply) -> tuple[ReplyClassification, str] | None:
        if opt_out_rule(reply.text):
            self.stats["rule.unsubscribe"] += 1
            return (
                ReplyClassification(category="unsubscribe", confidence=1.0, summary="Asked us to stop writing."),
                "rule",
            )
        if self.router is None or self.stopped:
            return None
        inputs = {
            "our_last_email": our_last_email(None, reply),
            "reply": reply.text,
            "subject": str(reply.row.get("subject") or ""),
            "company": str(reply.row.get("company") or ""),
            "sender_name": reply.name or "",
        }
        try:
            res = ai.call(
                self.router, "classify_reply", inputs, ReplyClassification, run_id=self.rc.run_id, lead_id=reply.lead_id
            )
        except ai.AIBudgetStop:
            self.stats["stopped.budget"] += 1
            self.stopped = True
            return None
        except ai.AIUnavailable:
            self.stats["ai.failed"] += 1
            self.failures += 1
            if self.failures >= AI_FAILURES_BEFORE_STOP:
                self.stats["stopped.ai_down"] += 1
                self.stopped = True
            return None
        self.failures = 0
        return tidy_classification(res.output, reply.text, self.ours), res.tag

    # -- drafting ----------------------------------------------------------
    def context(self, reply: Reply, out: ReplyClassification, wants_call: bool) -> DraftContext:
        base = str(db.get_setting("outreach.booking_url", BOOKING_URL) or BOOKING_URL)
        zone = recipient_zone(reply.row.get("country"), reply.row.get("city"))
        link = booking_link(base, email=reply.sender, name=reply.name) if wants_call else ""
        times = (
            [
                time_text(t, zone)
                for t in suggest_times(self.now, zone, call_hours(db.get_setting("outreach.call_hours")))
            ]
            if wants_call
            else []
        )
        plan = plan_url(None, reply.lead_id) if out.category == "send_plan" else None
        return DraftContext(
            category=out.category,
            first=first_name(reply.name),
            company=str(reply.row.get("company") or ""),
            link=link,
            base_link=base,
            times=times,
            zone_label=zone_label(zone),
            plan_link=plan,
            plan_pending=out.category == "send_plan" and plan is None,
            referral_name=out.referral_name,
            referral_email=out.referral_email,
        )

    def write(self, reply: Reply, out: ReplyClassification, ctx: DraftContext) -> tuple[str, str]:
        """(body, how): the writer's draft checked by code, one rewrite on problems, else the safe fallback."""
        if self.router is None or self.stopped:
            return finish(fallback(ctx), ctx), "fallback"
        offer = offer_for(None, reply.lead_id) or {}
        extra = {
            "our_last_email": our_last_email(None, reply),
            "offer": str(offer.get("name") or ""),
            "typical_range": typical_range_text(offer.get("typical_range")),
            "feedback": [],
        }
        for attempt in range(2):
            try:
                res = ai.call(
                    self.router,
                    "draft_reply",
                    draft_inputs(reply, ctx, out, extra),
                    ReplyDraft,
                    run_id=self.rc.run_id,
                    lead_id=reply.lead_id,
                )
            except ai.AIBudgetStop:
                self.stats["stopped.budget"] += 1
                self.stopped = True
                break
            except ai.AIUnavailable:
                self.stats["ai.failed"] += 1
                break
            if out.category == "question" and not res.output.include_booking_link and ctx.link:
                ctx.link, ctx.times = "", []
            body = finish(res.output.body, ctx)
            problems = draft_problems(body, ctx)
            if not problems:
                return body, res.tag
            self.stats[f"draft.rewrite.{attempt + 1}"] += 1
            extra["feedback"] = problems
        return finish(fallback(ctx), ctx), "fallback"

    def draft(self, reply: Reply, out: ReplyClassification) -> str | None:
        """Write and store the answer: a `review` message (or `approved` from a founder template). Returns it."""
        wants_call = out.category in ALWAYS_LINK or out.category == "question"
        ctx = self.context(reply, out, wants_call)
        how, status = "", "review"
        body: str | None = None
        templates = db.get_setting("outreach.reply_templates", {}) or {}
        if (
            out.category in TEMPLATE_CATEGORIES
            and out.confidence >= SAFE_CONFIDENCE
            and bool(db.get_setting("outreach.auto_replies", False))
            and outreach_mode() == "auto"
            and isinstance(templates, Mapping)
            and isinstance(templates.get(out.category), str)
        ):
            filled = from_template(str(templates[out.category]), ctx)
            if filled is not None and not draft_problems(filled, ctx):
                body, how, status = filled, "template", "approved"
        if body is None:
            body, how = self.write(reply, out, ctx)
        with db.tx("engine", {"run_id": self.rc.run_id, "stage": "replies"}) as conn:
            live = db.fetch_one(
                "select t.status from public.email_threads t where t.id = %s for update", [reply.thread_id], conn=conn
            )
            if live is None or live["status"] == "done":
                return None
            conn.execute(
                "update public.email_messages set suggested_reply = %s, updated_at = now() where id = %s",
                [body, reply.id],
            )
            row = db.fetch_one(
                "insert into public.email_messages (thread_id, direction, step, subject, body, status) "
                "values (%s, 'out', null, null, %s, %s) returning id::text as id",
                [reply.thread_id, body, status],
                conn=conn,
            )
            activity(
                conn,
                reply.lead_id,
                "ai_output",
                {
                    "kind": "reply_drafted",
                    "message_id": reply.id,
                    "draft_id": row["id"] if row else None,
                    "status": status,
                    "how": how,
                    "category": out.category,
                    "booking_link": bool(ctx.link),
                    "plan_pending": ctx.plan_pending,
                },
            )
        self.stats[f"drafted.{status}"] += 1
        return body

    # -- one reply -----------------------------------------------------------
    def handle(self, reply: Reply) -> None:
        got = self.classify(reply)
        if got is None:
            self.stats["waiting"] += 1
            return
        out, tag = got
        with db.tx("engine", {"run_id": self.rc.run_id, "stage": "replies"}) as conn:
            current = db.fetch_one(
                "select classification from public.email_messages where id = %s for update", [reply.id], conn=conn
            )
            if current is None or current["classification"] is not None:
                self.stats["skipped.classified_meanwhile"] += 1
                return
            done = apply_classification(conn, reply, out, tag=tag, now=self.now, ours=self.ours)
            fresh = db.fetch_one("select status from public.email_threads where id = %s", [reply.thread_id], conn=conn)
        reply.row["thread_status"] = (fresh or {}).get("status")
        self.stats[f"classified.{out.category}"] += 1
        for key, value in done.items():
            if value is True:
                self.stats[key] += 1
        draft = None
        if out.category in DRAFT_CATEGORIES and reply.row["thread_status"] != "done":
            draft = self.draft(reply, out)
        if out.category in ALERT_CATEGORIES:
            self.alert(reply, out.category, out.summary, draft)

    def alert(self, reply: Reply, category: str, summary: str, draft: str | None) -> None:
        if not notify.email_configured():
            self.stats["alert.skipped_no_email"] += 1
            return
        sent = send_alert(reply, category, summary, draft)
        with db.tx("engine", {"run_id": self.rc.run_id, "stage": "replies"}) as conn:
            activity(conn, reply.lead_id, "ai_output", {"kind": "reply_alert", "message_id": reply.id, "sent": sent})
        self.stats["alert.sent" if sent else "alert.failed"] += 1


def fill_plan_links(run_id: str) -> int:
    """Put the plan link into drafted replies that were waiting for it, once the lead has a live plan page."""
    rows = db.fetch_all(
        """
        select m.id::text as id, t.lead_id::text as lead_id from public.email_messages m
          join public.email_threads t on t.id = m.thread_id
         where m.direction = 'out' and m.step is null and m.status in ('draft', 'review', 'approved')
           and position('{plan_link}' in coalesce(m.body, '')) > 0
        """
    )
    filled = 0
    for r in rows:
        url = plan_url(None, r["lead_id"])
        if url is None:
            continue
        with db.tx("engine", {"run_id": run_id, "stage": "replies"}) as conn:
            filled += db.execute(
                "update public.email_messages set body = replace(body, '{plan_link}', %s), updated_at = now() "
                "where id = %s and status in ('draft', 'review', 'approved')",
                [url, r["id"]],
                conn=conn,
            )
    return filled


def _pending(limit: int | None) -> list[Reply]:
    rows = db.fetch_all(
        _PENDING + " and m.classification is null order by coalesce(m.sent_at, m.created_at), m.id limit %s",
        [limit],
    )
    return [Reply(r) for r in rows]


def _needing_drafts(now: datetime) -> list[tuple[Reply, ReplyClassification]]:
    """Classified replies whose draft failed earlier (the writer was down), still worth answering."""
    rows = db.fetch_all(
        _PENDING
        + """
           and m.classification = any(%s) and m.suggested_reply is null and t.status <> 'done'
           and coalesce(m.sent_at, m.created_at) > %s
           and not exists (
               select 1 from public.activities a
                where a.lead_id = t.lead_id and a.type = 'ai_output' and a.payload ->> 'kind' = 'reply_drafted'
                  and a.payload ->> 'message_id' = m.id::text)
         order by m.created_at
        """,
        [list(DRAFT_CATEGORIES), now - DRAFT_RETRY_WITHIN],
    )
    out: list[tuple[Reply, ReplyClassification]] = []
    for r in rows:
        meta = db.fetch_one(
            "select payload from public.activities where lead_id = %s and type = 'ai_output' "
            "and payload ->> 'kind' = 'reply_classified' and payload ->> 'message_id' = %s order by at desc limit 1",
            [r["lead_id"], r["id"]],
        )
        p = (meta or {}).get("payload") or {}
        out.append(
            (
                Reply(r),
                ReplyClassification(
                    category=r["classification"],
                    confidence=float(r["classification_confidence"] or 0),
                    summary=str(p.get("summary") or "")[:200],
                    return_date=p.get("return_date"),
                    referral_name=p.get("referral_name"),
                    referral_email=p.get("referral_email"),
                ),
            )
        )
    return out


def run(rc: RunContext, *, router: ai.AIRouter | None = None, now: datetime | None = None, **_: Any) -> dict[str, Any]:
    """Classify new replies, act on them, draft answers and alert the founder about interested ones."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    now = now or datetime.now(UTC)
    pending = _pending(rc.opts.limit)
    stats: Counter[str] = Counter(pending=len(pending))
    if rc.opts.dry_run:
        return {**stats, "skipped": "dry run"}
    stats["plan_links_filled"] = fill_plan_links(rc.run_id)
    retry = _needing_drafts(now)
    needs_ai = bool(retry) or any(not opt_out_rule(r.text) for r in pending)
    if router is None and needs_ai:
        try:
            router = ai.router_for(rc)
        except ai.AIUnavailable as exc:
            stats["ai.unavailable"] += 1
            log.warning("replies.no_ai", reason=exc.reason)
    replier = Replier(rc, router, now, our_addresses(""), stats)
    for reply in pending:
        try:
            replier.handle(reply)
        except Exception as exc:  # one bad reply must not stop the others; it stays unclassified for next time
            stats["errors"] += 1
            log.error("replies.failed", message_id=reply.id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
    for reply, out in retry:
        if replier.stopped or replier.router is None:
            break
        try:
            replier.draft(reply, out)
        except Exception as exc:
            stats["errors"] += 1
            log.error("replies.draft_failed", message_id=reply.id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
    result = {k: v for k, v in sorted(stats.items()) if v or k == "pending"}
    rc.stats["replies"] = result
    log.info("replies.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
