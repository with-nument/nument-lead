"""Cal.com booking invites read from the outreach mailbox (iCalendar, RFC 5545).

The founder forwards Cal.com's booking emails to the Nument mailbox with a mail filter; the Gmail client hands
each invite over as `Incoming.calendar_ics`. Cal.com builds the file with the `ics` package: times in UTC,
`METHOD:REQUEST` for a booking or a reschedule (same UID, higher SEQUENCE, new start) and `METHOD:CANCEL` with
`STATUS:CANCELLED` for a cancellation; older Cal.com versions gave a reschedule a new UID and cancelled the old
one. Other calendars (a founder who sends us a Google Calendar invite) use `DTSTART;TZID=...` local times.

Parsing is a small, strict subset of RFC 5545: line unfolding, quoted parameters, text escapes, UTC and TZID
date-times, DTEND or DURATION. No network, no third-party parser.

The booking rules (contract 4.6): a booking sets `leads.meeting_at`, moves the lead to `discovery_booked`, logs a
`booking` activity and stops the thread with `stop_reason='booking'`. A reschedule moves `meeting_at` (the
pre-call brief then goes out again for the new time); a cancellation clears it and moves a `discovery_booked`
lead back to `talking`. Each change is applied once, however many copies of the invite arrive.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg import Connection

from .. import db
from ..logging import get_logger
from ..pipeline.phones import is_freemail

log = get_logger()

# Stages a booking may move to discovery_booked. Later stages (discovery_done, proposal_sent, won, retainer) are
# never moved back; a lead closed as not now that books a call is open again.
BOOKABLE_STAGES: Final = ("new", "contacted", "talking", "not_now")
DOMAIN_MATCH_DAYS: Final = 180
# Outlook writes Windows zone names in TZID; the few a founder is likely to send.
WINDOWS_ZONES: Final[dict[str, str]] = {
    "utc": "UTC",
    "gmt standard time": "Europe/London",
    "greenwich standard time": "UTC",
    "eastern standard time": "America/New_York",
    "central standard time": "America/Chicago",
    "mountain standard time": "America/Denver",
    "pacific standard time": "America/Los_Angeles",
    "india standard time": "Asia/Kolkata",
    "arabian standard time": "Asia/Dubai",
    "singapore standard time": "Asia/Singapore",
    "aus eastern standard time": "Australia/Sydney",
    "w. europe standard time": "Europe/Berlin",
    "romance standard time": "Europe/Paris",
    "e. south america standard time": "America/Sao_Paulo",
}
_DURATION: Final = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Party:
    """An organizer or attendee: a lower-case email address and the CN name when there is one."""

    email: str
    name: str | None = None


@dataclass(frozen=True)
class CalendarEvent:
    """One VEVENT with what the booking rules need. `start` and `end` are aware UTC datetimes or None."""

    uid: str
    method: str  # REQUEST, CANCEL, PUBLISH, ... (upper case; "" when the file names none)
    status: str  # CONFIRMED, TENTATIVE, CANCELLED (upper case; "" when missing)
    sequence: int
    start: datetime | None
    end: datetime | None
    tzid: str | None  # the zone DTSTART was written in, when it named one
    organizer: Party | None
    attendees: tuple[Party, ...] = ()
    summary: str = ""
    description: str = ""
    location: str = ""

    @property
    def cancelled(self) -> bool:
        return self.method == "CANCEL" or self.status == "CANCELLED"

    def parties(self) -> list[Party]:
        """Attendees first, then the organizer: the people a booking can belong to."""
        return [*self.attendees, *([self.organizer] if self.organizer else [])]


def unfold(text: str) -> list[str]:
    """Content lines with folding undone: a line break followed by one space or tab continues the line."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def parse_line(line: str) -> tuple[str, dict[str, str], str]:
    """`NAME;PARAM=a;PARAM="b:c":value` as (NAME, {PARAM: value}, value). Quoted values may hold ; : and ,."""
    n, i = len(line), 0
    while i < n and line[i] not in ";:":
        i += 1
    name = line[:i].strip().upper()
    params: dict[str, str] = {}
    while i < n and line[i] == ";":
        j = i + 1
        while j < n and line[j] not in "=;:":
            j += 1
        key = line[i + 1 : j].strip().upper()
        values: list[str] = []
        if j < n and line[j] == "=":
            j += 1
            while True:
                if j < n and line[j] == '"':
                    end = line.find('"', j + 1)
                    end = n if end == -1 else end
                    values.append(line[j + 1 : end])
                    j = end + 1
                else:
                    end = j
                    while end < n and line[end] not in ",;:":
                        end += 1
                    values.append(line[j:end])
                    j = end
                if j < n and line[j] == ",":
                    j += 1
                    continue
                break
        params[key] = ",".join(values)
        i = j
    value = line[i + 1 :] if i < n and line[i] == ":" else ""
    return name, params, value


def unescape(text: str) -> str:
    """RFC 5545 TEXT escapes: \\n, \\N, \\, \\; and \\\\."""
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def zone_for(tzid: str | None) -> ZoneInfo | None:
    """The zone a TZID names (IANA, or a common Windows name), or None when it is unknown."""
    if not tzid:
        return None
    name = tzid.strip().strip('"')
    name = WINDOWS_ZONES.get(name.lower(), name)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def parse_datetime(value: str, params: Mapping[str, str], default_zone: ZoneInfo | None = None) -> datetime | None:
    """A DATE-TIME as an aware UTC datetime: `...Z` is UTC, a TZID is resolved, a floating time uses the
    calendar's X-WR-TIMEZONE when given. An all-day DATE or an unknown zone gives None (not a call time)."""
    raw = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", raw):
        return None
    m = re.fullmatch(r"(\d{8})T(\d{4})(\d{2})?(Z)?", raw)
    if not m:
        return None
    try:
        naive = datetime.strptime(m.group(1) + m.group(2) + (m.group(3) or "00"), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if m.group(4):
        return naive.replace(tzinfo=UTC)
    zone = zone_for(params.get("TZID")) if params.get("TZID") else default_zone
    if zone is None:
        return None
    return naive.replace(tzinfo=zone).astimezone(UTC)


def parse_duration(value: str) -> timedelta | None:
    m = _DURATION.match(value.strip().upper())
    if not m or value.strip().upper() in ("P", "PT"):
        return None
    parts = {k: int(v) for k, v in m.groupdict().items() if k != "sign" and v}
    delta = timedelta(
        weeks=parts.get("weeks", 0),
        days=parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )
    return -delta if m.group("sign") == "-" else delta


def _party(value: str, params: Mapping[str, str]) -> Party | None:
    address = value.strip()
    if address.lower().startswith("mailto:"):
        address = address[7:]
    address = address.strip().strip("<>").lower()
    if "@" not in address:
        address = params.get("EMAIL", "").strip().lower()
    if "@" not in address:
        return None
    name = unescape(params.get("CN", "")).strip() or None
    if name and name.lower() == address:
        name = None
    return Party(address, name)


@dataclass
class _Builder:
    props: list[tuple[str, dict[str, str], str]] = field(default_factory=list)


def parse_ics(text: str) -> list[CalendarEvent]:
    """Every VEVENT in an iCalendar file. A file that is not iCalendar gives an empty list, never an error."""
    method = ""
    default_zone: ZoneInfo | None = None
    events: list[_Builder] = []
    current: _Builder | None = None
    depth: list[str] = []
    for line in unfold(text or ""):
        name, params, value = parse_line(line)
        if name == "BEGIN":
            depth.append(value.strip().upper())
            if depth[-1] == "VEVENT":
                current = _Builder()
            continue
        if name == "END":
            ended = depth.pop() if depth else ""
            if ended == "VEVENT" and current is not None:
                events.append(current)
                current = None
            continue
        inside = depth[-1] if depth else ""
        if inside == "VCALENDAR":
            if name == "METHOD":
                method = value.strip().upper()
            elif name == "X-WR-TIMEZONE":
                default_zone = zone_for(value)
        elif inside == "VEVENT" and current is not None:
            current.props.append((name, params, value))
    return [ev for ev in (_event(b, method, default_zone) for b in events) if ev is not None]


def _event(b: _Builder, method: str, default_zone: ZoneInfo | None) -> CalendarEvent | None:
    first: dict[str, tuple[dict[str, str], str]] = {}
    attendees: list[Party] = []
    for name, params, value in b.props:
        if name == "ATTENDEE":
            party = _party(value, params)
            if party is not None and party not in attendees:
                attendees.append(party)
        else:
            first.setdefault(name, (params, value))
    uid = first.get("UID", ({}, ""))[1].strip()
    if not uid:
        return None
    start_p, start_v = first.get("DTSTART", ({}, ""))
    start = parse_datetime(start_v, start_p, default_zone) if start_v else None
    end: datetime | None = None
    if "DTEND" in first:
        end = parse_datetime(first["DTEND"][1], first["DTEND"][0], default_zone)
    elif "DURATION" in first and start is not None:
        delta = parse_duration(first["DURATION"][1])
        end = start + delta if delta is not None else None
    organizer = _party(first["ORGANIZER"][1], first["ORGANIZER"][0]) if "ORGANIZER" in first else None
    try:
        sequence = int(first.get("SEQUENCE", ({}, "0"))[1].strip() or 0)
    except ValueError:
        sequence = 0
    return CalendarEvent(
        uid=uid,
        method=method,
        status=first.get("STATUS", ({}, ""))[1].strip().upper(),
        sequence=sequence,
        start=start,
        end=end,
        tzid=start_p.get("TZID") or None,
        organizer=organizer,
        attendees=tuple(attendees),
        summary=unescape(first.get("SUMMARY", ({}, ""))[1]).strip(),
        description=unescape(first.get("DESCRIPTION", ({}, ""))[1]).strip(),
        location=unescape(first.get("LOCATION", ({}, ""))[1]).strip(),
    )


# ---------------------------------------------------------------------------
# Whose booking is it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BookingMatch:
    lead_id: str
    thread_id: str | None
    matched_by: str  # attendee_thread, attendee_contact, attendee_domain, mail_thread
    party: Party | None


def find_lead(
    conn: Connection[Any],
    event: CalendarEvent,
    ours: Iterable[str],
    *,
    thread: Mapping[str, Any] | None = None,
) -> BookingMatch | None:
    """The lead a booking belongs to: an attendee (or an organizer who is not us) whose address we wrote to,
    then a contact with that address, then an attendee at a company domain we wrote to in the last 180 days,
    then the Gmail thread the invite arrived in."""
    mine = {a.lower() for a in ours}
    people = [p for p in event.parties() if p.email not in mine]
    for p in people:
        row = db.fetch_one(
            "select id::text as thread_id, lead_id::text as lead_id from public.email_threads "
            "where lower(to_email) = %s order by created_at desc limit 1",
            [p.email],
            conn=conn,
        )
        if row:
            return BookingMatch(row["lead_id"], row["thread_id"], "attendee_thread", p)
    for p in people:
        row = db.fetch_one(
            """
            select l.id::text as lead_id from public.contacts c
              join public.leads l on l.business_id = c.business_id
             where lower(c.email) = %s
             order by (l.stage not in ('won','retainer','lost','not_now','not_a_fit','wrong_contact')) desc,
                      l.created_at desc
             limit 1
            """,
            [p.email],
            conn=conn,
        )
        if row:
            return BookingMatch(row["lead_id"], _latest_thread(conn, row["lead_id"]), "attendee_contact", p)
    for p in people:
        domain = p.email.rsplit("@", 1)[-1]
        if is_freemail(p.email) or domain in {m.rsplit("@", 1)[-1] for m in mine}:
            continue
        row = db.fetch_one(
            "select id::text as thread_id, lead_id::text as lead_id from public.email_threads "
            "where to_domain = %s and created_at > now() - make_interval(days => %s) "
            "order by created_at desc limit 1",
            [domain, DOMAIN_MATCH_DAYS],
            conn=conn,
        )
        if row:
            return BookingMatch(row["lead_id"], row["thread_id"], "attendee_domain", p)
    if thread is not None:
        return BookingMatch(str(thread["lead_id"]), str(thread["id"]), "mail_thread", people[0] if people else None)
    return None


def _latest_thread(conn: Connection[Any], lead_id: str) -> str | None:
    row = db.fetch_one(
        "select id::text as id from public.email_threads where lead_id = %s order by created_at desc limit 1",
        [lead_id],
        conn=conn,
    )
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Applying a booking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Current:
    """The lead's booking as the latest `booking` activity left it."""

    uid: str | None
    sequence: int
    start: datetime | None
    cancelled: bool


def current_booking(conn: Connection[Any], lead_id: str) -> Current | None:
    row = db.fetch_one(
        "select payload from public.activities where lead_id = %s and type = 'booking' order by at desc, id desc "
        "limit 1",
        [lead_id],
        conn=conn,
    )
    if not row:
        return None
    p = row["payload"] or {}
    try:
        start = datetime.fromisoformat(p["start"]) if p.get("start") else None
    except ValueError:
        start = None
    return Current(p.get("uid"), int(p.get("sequence") or 0), start, p.get("kind") == "cancelled")


def decide(event: CalendarEvent, current: Current | None) -> str:
    """What this invite means for the lead: booked, rescheduled, cancelled, duplicate or stale."""
    if event.cancelled:
        if current is None or current.uid != event.uid:
            return "stale"  # nothing booked, or a booking an earlier reschedule replaced
        if current.cancelled:
            return "duplicate"
        return "stale" if event.sequence < current.sequence else "cancelled"
    if event.start is None:
        return "stale"
    if current is None or (current.cancelled and current.uid != event.uid):
        return "booked"
    if current.uid == event.uid:
        if event.sequence < current.sequence:
            return "stale"
        if current.cancelled:
            return "booked" if event.sequence > current.sequence else "duplicate"
        return "duplicate" if event.start == current.start else "rescheduled"
    if current.cancelled:
        return "booked"
    return "duplicate" if event.start == current.start else "rescheduled"


def apply(
    conn: Connection[Any],
    match: BookingMatch,
    event: CalendarEvent,
    *,
    gmail_message_id: str | None = None,
    stop: Any = None,
) -> str:
    """Apply one invite to its lead inside the caller's transaction. Returns what `decide` said.

    `stop(conn, thread_id, reason)` stops the thread (the inbox passes its own, which also cancels the unsent
    sequence steps); without it only the thread row changes.
    """
    lead = db.fetch_one(
        "select id::text as id, stage, meeting_at from public.leads where id = %s for update",
        [match.lead_id],
        conn=conn,
    )
    if lead is None:
        return "stale"
    current = current_booking(conn, match.lead_id)
    kind = decide(event, current)
    if kind in ("duplicate", "stale"):
        return kind
    payload: dict[str, Any] = {
        "kind": kind,
        "uid": event.uid,
        "sequence": event.sequence,
        "start": event.start.isoformat() if event.start and kind != "cancelled" else None,
        "end": event.end.isoformat() if event.end and kind != "cancelled" else None,
        "tz": event.tzid,
        "method": event.method or None,
        "thread_id": match.thread_id,
        "matched_by": match.matched_by,
        "gmail_message_id": gmail_message_id,
        "notes": booking_notes(event.description) if kind != "cancelled" else None,
        "location": event.location if event.location.startswith("https://") and kind != "cancelled" else None,
    }
    if kind == "cancelled":
        payload["cancelled_start"] = current.start.isoformat() if current and current.start else None
        conn.execute("update public.leads set meeting_at = null where id = %s", [match.lead_id])
        conn.execute(
            "update public.leads set stage = 'talking' where id = %s and stage = 'discovery_booked'",
            [match.lead_id],
        )
    else:
        if kind == "rescheduled" and current is not None and current.start is not None:
            payload["previous_start"] = current.start.isoformat()
        conn.execute("update public.leads set meeting_at = %s where id = %s", [event.start, match.lead_id])
        conn.execute(
            "update public.leads set stage = 'discovery_booked' where id = %s and stage = any(%s)",
            [match.lead_id, list(BOOKABLE_STAGES)],
        )
        if match.thread_id:
            if stop is not None:
                stop(conn, match.thread_id, "booking")
            else:
                conn.execute(
                    "update public.email_threads set status = 'stopped', stop_reason = 'booking', updated_at = now() "
                    "where id = %s and status <> 'done'",
                    [match.thread_id],
                )
    conn.execute(
        "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'booking', %s)",
        [match.lead_id, db.Jsonb(payload)],
    )
    log.info("bookings.applied", kind=kind, lead_id=match.lead_id, matched_by=match.matched_by)
    return kind


NOTES_MAX_CHARS: Final = 600
_NOTES: Final = re.compile(
    r"(?:additional notes|notes)\s*:?\s*\n(?P<notes>.+?)(?:\n\s*\n[A-Z][^\n]{0,40}:\s*\n|\Z)", re.I | re.S
)


def booking_notes(description: str) -> str | None:
    """What the person wrote in the booking form (Cal.com's "Additional notes"), for the pre-call brief."""
    m = _NOTES.search(description or "")
    text = " ".join(m.group("notes").split()) if m else ""
    return text[:NOTES_MAX_CHARS] or None


def bookable(events: Sequence[CalendarEvent]) -> list[CalendarEvent]:
    """Events worth applying: cancellations, and requests with a call time."""
    return [e for e in events if e.cancelled or e.start is not None]
