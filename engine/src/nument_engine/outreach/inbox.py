"""Read the outreach mailbox: replies, bounces and Cal.com booking invites (contract 4.6, phase `inbox`).

Every 15 minutes while outreach is on, new mail comes from `MailboxClient.fetch_new` with the Gmail history
cursor in `settings outreach.gmail_history:<mailbox>`. Each message is handled in its own transaction:

- a reply is matched to its thread by Gmail thread id, then In-Reply-To or References against the RFC
  Message-IDs we stored, then the sender's address (someone who writes a new email instead of answering), then
  the sender's company domain (a co-founder; one thread per domain, never a free-mail domain). It is stored as
  `direction='in'`, `status='received'`, and it stops the sequence at once: thread `stopped` with
  `stop_reason='reply'` and every unsent step `cancelled` (the steps and their old statuses are kept in the
  `sequence_stopped` activity, so an out-of-office reply can put them back). An email with the subject
  "unsubscribe" (our List-Unsubscribe mailto) is honoured right here, without AI;
- a bounce marks the bounced message `error='bounced'` (it stays `sent`), the address `email_status='invalid'`,
  stops the thread with `stop_reason='bounce'` and logs `email_bounced`;
- a calendar invite goes to `bookings` (booked, rescheduled, cancelled).

Nothing is ever lost: the cursor moves only after every message was handled, and a re-run skips what is already
stored. A message that fails three runs in a row is left unread in Gmail for the founder, so one broken message
cannot hold the cursor forever. Mail that matches nothing stays unread in Gmail too. Only machine mail the engine
fully handled (bounces and booking notices) is marked read; replies are never marked read, the founder reads them.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from psycopg import Connection

from .. import db
from ..logging import get_logger
from ..pipeline.phones import is_freemail
from ..pipeline.runs import RunContext, outreach_mode
from . import bookings
from .gmail import Incoming, MailboxClient, MailboxError

log = get_logger()

CURSOR_KEY: Final = "outreach.gmail_history:{address}"
UNSENT: Final = ("draft", "review", "approved", "queued")
BODY_MAX_CHARS: Final = 50_000
DOMAIN_MATCH_DAYS: Final = 180
OPT_OUT_SUBJECTS: Final = frozenset({"unsubscribe", "unsubscribe me", "please unsubscribe"})
RULE_CONFIDENCE: Final = 1.0
MARK_READ: Final = frozenset({"bounced", "bounce_duplicate"})
FAILURES_KEY: Final = "outreach.inbox_failures:{address}"
MAX_ATTEMPTS: Final = 3  # a message that fails this often is left unread for the founder, so the cursor moves on
FAILURES_KEPT: Final = 200

_REPLY_HEADER: Final = re.compile(
    r"^(?:on\b.{0,200}\b(?:wrote|escribi[oó]|a écrit|schrieb|scritto|schreef)\s*:\s*$"
    r"|-{2,}\s*original message\s*-{2,}"
    r"|_{5,}"
    r"|from:\s.+"
    r"|sent from my \w+)",
    re.I,
)


# ---------------------------------------------------------------------------
# Small shared helpers (replies and bookings use them too)
# ---------------------------------------------------------------------------


def addr(email: str | None) -> str:
    """A normalised address: trimmed, lower case, without angle brackets."""
    return (email or "").strip().strip("<>").strip().lower()


def domain_of(email: str | None) -> str:
    a = addr(email)
    return a.rsplit("@", 1)[1] if "@" in a else ""


def new_text(body: str | None) -> str:
    """What they wrote, without the quoted history under it (">" lines, "On ... wrote:" and below)."""
    lines = (body or "").replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    for i, line in enumerate(lines):
        s = line.strip()
        joined = f"{s} {lines[i + 1].strip()}" if i + 1 < len(lines) else s
        if s.startswith(">") or _REPLY_HEADER.match(s) or (s.lower().startswith("on ") and _REPLY_HEADER.match(joined)):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def activity(conn: Connection[Any], lead_id: str, kind: str, payload: Mapping[str, Any]) -> None:
    """One engine activity on the lead's timeline."""
    conn.execute(
        "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', %s, %s)",
        [lead_id, kind, db.Jsonb(dict(payload))],
    )


def cancel_unsent(conn: Connection[Any], thread_id: str, *, replies_too: bool = False) -> list[dict[str, Any]]:
    """Cancel the thread's unsent outgoing messages; returns each one's id, step and previous status."""
    steps_only = "" if replies_too else "and step is not null"
    rows = db.fetch_all(
        f"""
        with prev as (
            select id, step, status from public.email_messages
             where thread_id = %s and direction = 'out' and status = any(%s) {steps_only}
             for update
        )
        update public.email_messages m set status = 'cancelled', updated_at = now()
          from prev where m.id = prev.id
        returning m.id::text as id, prev.step, prev.status
        """,
        [thread_id, list(UNSENT)],
        conn=conn,
    )
    return sorted(rows, key=lambda r: (r["step"] is None, r["step"] or 0, r["id"]))


def stop_thread(conn: Connection[Any], thread_id: str, reason: str, *, message_id: str | None = None) -> bool:
    """Stop the sequence: thread `stopped` with `reason`, unsent steps cancelled, a `sequence_stopped` activity.

    A `done` thread is left alone. A thread already stopped stays stopped and keeps its first reason, except
    that a booking always records itself. Returns True when anything changed.
    """
    t = db.fetch_one(
        "select id::text as id, lead_id::text as lead_id, status, stop_reason from public.email_threads "
        "where id = %s for update",
        [thread_id],
        conn=conn,
    )
    if t is None or t["status"] == "done":
        return False
    cancelled = cancel_unsent(conn, thread_id)
    keep_old = t["status"] == "stopped" and t["stop_reason"] and reason != "booking"
    new_reason = t["stop_reason"] if keep_old else reason
    if t["status"] == "stopped" and new_reason == t["stop_reason"] and not cancelled:
        return False
    conn.execute(
        "update public.email_threads set status = 'stopped', stop_reason = %s, updated_at = now() where id = %s",
        [new_reason, thread_id],
    )
    activity(
        conn,
        t["lead_id"],
        "sequence_stopped",
        {"thread_id": thread_id, "reason": reason, "message_id": message_id, "cancelled": cancelled},
    )
    return True


def honour_unsubscribe(
    conn: Connection[Any],
    thread: Mapping[str, Any],
    addresses: Iterable[str | None],
    *,
    how: str,
    message_id: str | None,
) -> None:
    """An opt-out, always honoured: every address and the company domain (never a free-mail domain) go on the
    suppression list, the contacts with those addresses get `do_not_contact`, and the thread is `done` with
    everything unsent cancelled, replies included. Nothing is ever sent to them again."""
    emails = sorted({a for a in (addr(x) for x in [thread["to_email"], *addresses]) if "@" in a})
    for email in emails:
        conn.execute(
            "insert into public.suppression (email, reason) values (%s, 'opt_out') "
            "on conflict ((lower(email))) where email is not null do nothing",
            [email],
        )
    domains = sorted({domain_of(e) for e in emails if not is_freemail(e)})
    for domain in domains:
        conn.execute(
            "insert into public.suppression (web_domain, reason) values (%s, 'opt_out') "
            "on conflict (web_domain) where web_domain is not null do nothing",
            [domain],
        )
    conn.execute(
        "update public.contacts set do_not_contact = true where lower(email) = any(%s) or id = %s::uuid",
        [emails, thread.get("contact_id")],
    )
    cancelled = cancel_unsent(conn, str(thread["id"]), replies_too=True)
    conn.execute(
        "update public.email_threads set status = 'done', stop_reason = 'unsubscribe', paused_until = null, "
        "updated_at = now() where id = %s",
        [thread["id"]],
    )
    activity(
        conn,
        str(thread["lead_id"]),
        "sequence_stopped",
        {
            "thread_id": str(thread["id"]),
            "reason": "unsubscribe",
            "how": how,
            "message_id": message_id,
            "cancelled": cancelled,
            "suppressed_domains": domains,
        },
    )


def our_addresses(mailbox_address: str, *, conn: Connection[Any] | None = None) -> set[str]:
    """The outreach mailbox and every mailbox we have connected: mail from these is our own."""
    rows = db.fetch_all("select lower(email) as email from public.mailboxes", conn=conn)
    return {addr(mailbox_address), *(r["email"] for r in rows)} - {""}


# ---------------------------------------------------------------------------
# Matching a message to its thread
# ---------------------------------------------------------------------------

THREAD_COLS: Final = (
    "t.id::text as id, t.lead_id::text as lead_id, t.contact_id::text as contact_id, t.to_email, t.to_domain, "
    "t.status, t.stop_reason, t.gmail_thread_id"
)


def message_ids(msg: Incoming) -> list[str]:
    """In-Reply-To first, then References (newest first), in the stored form "<id@host>"."""
    refs: Any = getattr(msg, "references", ()) or ()
    if isinstance(refs, str):
        refs = refs.split()
    out: list[str] = []
    for raw in [msg.in_reply_to or "", *reversed([str(r) for r in refs])]:
        for one in re.findall(r"<[^<>\s]+>", raw) or ([raw.strip()] if raw.strip() else []):
            mid = one if one.startswith("<") else f"<{one}>"
            if mid not in out:
                out.append(mid)
    return out


def match_thread(conn: Connection[Any], msg: Incoming) -> tuple[dict[str, Any] | None, str | None]:
    """(thread, how it matched) or (None, None). See the module docstring for the order."""
    if msg.gmail_thread_id:
        row = db.fetch_one(
            f"select {THREAD_COLS} from public.email_threads t where t.gmail_thread_id = %s "
            "order by t.created_at desc limit 1",
            [msg.gmail_thread_id],
            conn=conn,
        )
        if row:
            return row, "gmail_thread"
    ids = message_ids(msg)
    if ids:
        row = db.fetch_one(
            f"select {THREAD_COLS} from public.email_messages m join public.email_threads t on t.id = m.thread_id "
            "where m.rfc_message_id = any(%s) order by array_position(%s::text[], m.rfc_message_id) limit 1",
            [ids, ids],
            conn=conn,
        )
        if row:
            return row, "in_reply_to"
    sender = addr(msg.from_email)
    if sender:
        row = db.fetch_one(
            f"select {THREAD_COLS} from public.email_threads t where lower(t.to_email) = %s "
            "order by t.created_at desc limit 1",
            [sender],
            conn=conn,
        )
        if row:
            return row, "sender"
    domain = domain_of(sender)
    if domain and not is_freemail(sender):
        row = db.fetch_one(
            f"select {THREAD_COLS} from public.email_threads t where t.to_domain = %s "
            "and t.created_at > now() - make_interval(days => %s) order by t.created_at desc limit 1",
            [domain, DOMAIN_MATCH_DAYS],
            conn=conn,
        )
        if row:
            return row, "sender_domain"
    return None, None


# ---------------------------------------------------------------------------
# Handling one message
# ---------------------------------------------------------------------------


def already_stored(conn: Connection[Any], msg: Incoming) -> bool:
    row = db.fetch_one(
        "select 1 as x from public.email_messages where gmail_message_id = %s "
        "or (%s::text is not null and rfc_message_id = %s) limit 1",
        [msg.gmail_message_id, msg.rfc_message_id, msg.rfc_message_id],
        conn=conn,
    )
    return row is not None


def is_opt_out_email(msg: Incoming) -> bool:
    """Our List-Unsubscribe mailto: an email whose subject is just "unsubscribe"."""
    subject = re.sub(r"^\s*(?:re|fwd?)\s*:\s*", "", msg.subject or "", flags=re.I).strip().rstrip(".!").lower()
    return subject in OPT_OUT_SUBJECTS


def store_reply(conn: Connection[Any], thread: Mapping[str, Any], msg: Incoming, matched_by: str) -> str | None:
    """Store the incoming message and its `email_received` activity; None when it was stored before."""
    row = db.fetch_one(
        """
        insert into public.email_messages
            (thread_id, direction, step, subject, body, status, sent_at, rfc_message_id, gmail_message_id)
        values (%s, 'in', null, %s, %s, 'received', %s, %s, %s)
        on conflict (rfc_message_id) where rfc_message_id is not null do nothing
        returning id::text as id
        """,
        [
            thread["id"],
            (msg.subject or "")[:500],
            (msg.body_text or "")[:BODY_MAX_CHARS],
            msg.received_at,
            msg.rfc_message_id,
            msg.gmail_message_id,
        ],
        conn=conn,
    )
    if row is None:
        return None
    if msg.gmail_thread_id and not thread.get("gmail_thread_id"):
        conn.execute(
            "update public.email_threads set gmail_thread_id = %s where id = %s and gmail_thread_id is null",
            [msg.gmail_thread_id, thread["id"]],
        )
    activity(
        conn,
        str(thread["lead_id"]),
        "email_received",
        {
            "thread_id": str(thread["id"]),
            "message_id": row["id"],
            "matched_by": matched_by,
            "from_email": addr(msg.from_email),
            "from_name": (msg.from_name or "").strip() or None,
            "subject": (msg.subject or "")[:200],
        },
    )
    return str(row["id"])


def handle_bounce(conn: Connection[Any], msg: Incoming) -> str:
    """bounced, bounce_duplicate or bounce_unmatched."""
    target = None
    cols = "m.id::text as id, m.step, m.error, m.thread_id::text as thread_id"
    if msg.bounced_rfc_id:
        ids = re.findall(r"<[^<>\s]+>", msg.bounced_rfc_id) or [f"<{msg.bounced_rfc_id.strip('<> ')}>"]
        target = db.fetch_one(
            f"select {cols} from public.email_messages m "
            "where m.direction = 'out' and m.rfc_message_id = any(%s) limit 1",
            [ids],
            conn=conn,
        )
    if target is None and msg.gmail_thread_id:
        target = db.fetch_one(
            f"select {cols} from public.email_messages m join public.email_threads t on t.id = m.thread_id "
            "where t.gmail_thread_id = %s and m.direction = 'out' and m.status = 'sent' "
            "order by m.sent_at desc nulls last limit 1",
            [msg.gmail_thread_id],
            conn=conn,
        )
    if target is None:
        return "bounce_unmatched"
    if target["error"] == "bounced":
        return "bounce_duplicate"
    thread = db.fetch_one(
        f"select {THREAD_COLS} from public.email_threads t where t.id = %s", [target["thread_id"]], conn=conn
    )
    if thread is None:
        return "bounce_unmatched"
    conn.execute("update public.email_messages set error = 'bounced', updated_at = now() where id = %s", [target["id"]])
    conn.execute(
        """
        update public.contacts c set email_status = 'invalid', email_checked_at = now()
          from public.leads l
         where l.id = %s and c.business_id = l.business_id
           and (c.id = %s::uuid or lower(c.email) = lower(%s))
        """,
        [thread["lead_id"], thread["contact_id"], thread["to_email"]],
    )
    stop_thread(conn, thread["id"], "bounce", message_id=target["id"])
    activity(
        conn,
        thread["lead_id"],
        "email_bounced",
        {"thread_id": thread["id"], "message_id": target["id"], "step": target["step"]},
    )
    return "bounced"


def handle_calendar(conn: Connection[Any], msg: Incoming, ours: set[str]) -> str | None:
    """booking.<what happened> for an invite we could place, or None to treat the message as ordinary mail."""
    events = bookings.bookable(bookings.parse_ics(msg.calendar_ics or ""))
    if not events:
        return None
    thread, _ = match_thread(conn, msg)
    outcomes: list[str] = []
    for event in events:
        match = bookings.find_lead(conn, event, ours, thread=thread)
        if match is None:
            continue
        outcomes.append(
            bookings.apply(
                conn,
                match,
                event,
                gmail_message_id=msg.gmail_message_id,
                stop=lambda c, tid, reason: stop_thread(c, tid, reason),
            )
        )
    if not outcomes:
        return None
    rank = ["booked", "rescheduled", "cancelled", "duplicate", "stale"]
    return f"booking.{min(outcomes, key=rank.index)}"


def handle(conn: Connection[Any], msg: Incoming, ours: set[str]) -> str:
    """Handle one message inside the caller's transaction; returns what happened (a stats key)."""
    if already_stored(conn, msg):
        return "duplicate"
    if addr(msg.from_email) in ours or "SENT" in msg.labels:
        return "own"
    if msg.is_bounce:
        return handle_bounce(conn, msg)
    if msg.calendar_ics:
        outcome = handle_calendar(conn, msg, ours)
        if outcome is not None:
            return outcome
    thread, matched_by = match_thread(conn, msg)
    if thread is None or matched_by is None:
        return "unmatched"
    message_id = store_reply(conn, thread, msg, matched_by)
    if message_id is None:
        return "duplicate"
    stop_thread(conn, str(thread["id"]), "reply", message_id=message_id)
    if is_opt_out_email(msg):
        conn.execute(
            "update public.email_messages set classification = 'unsubscribe', classification_confidence = %s, "
            "updated_at = now() where id = %s",
            [RULE_CONFIDENCE, message_id],
        )
        honour_unsubscribe(conn, thread, [msg.from_email], how="unsubscribe_email", message_id=message_id)
        return "unsubscribed"
    return "reply"


def open_mailbox() -> MailboxClient | None:
    """The connected Gmail mailbox from the Gmail client's `open_mailbox()`; None until it exists or is connected."""
    from . import gmail

    opener: Callable[[], MailboxClient | None] | None = getattr(gmail, "open_mailbox", None)
    return opener() if callable(opener) else None


def run(rc: RunContext, *, mailbox: MailboxClient | None = None, **_: Any) -> dict[str, Any]:
    """Read new mail: replies stop sequences, bounces mark addresses invalid, invites book calls."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    if mailbox is None:
        mailbox = open_mailbox()
        if mailbox is None:
            return {"skipped": "no mailbox connected"}
    key = CURSOR_KEY.format(address=addr(mailbox.address))
    cursor = db.get_setting(key)
    try:
        messages, new_cursor = mailbox.fetch_new(str(cursor) if cursor is not None else None)
    except MailboxError as exc:
        log.warning("inbox.fetch_failed", kind=exc.kind, error=str(exc)[:200])
        return {"skipped": f"mailbox error: {exc.kind}"}
    stats: Counter[str] = Counter(fetched=len(messages))
    if rc.opts.dry_run:
        return {**stats, "skipped": "dry run"}
    ours = our_addresses(mailbox.address)
    to_mark: list[str] = []
    epoch = datetime.min.replace(tzinfo=UTC)
    fail_key = FAILURES_KEY.format(address=addr(mailbox.address))
    failures: dict[str, int] = dict(db.get_setting(fail_key, {}) or {})
    for msg in sorted(messages, key=lambda m: (m.received_at or epoch, m.gmail_message_id)):
        if failures.get(msg.gmail_message_id, 0) >= MAX_ATTEMPTS:
            stats["skipped_after_errors"] += 1  # still unread in Gmail; the founder handles it by hand
            continue
        try:
            with db.tx("engine", {"run_id": rc.run_id, "stage": "inbox"}) as conn:
                outcome = handle(conn, msg, ours)
        except Exception as exc:  # one bad message must not stop the others; the cursor stays put
            stats["error"] += 1
            failures[msg.gmail_message_id] = failures.get(msg.gmail_message_id, 0) + 1
            log.error(
                "inbox.message_failed",
                gmail_message_id=msg.gmail_message_id,
                attempt=failures[msg.gmail_message_id],
                error=type(exc).__name__,
            )
            continue
        stats[outcome] += 1
        if outcome == "unmatched":
            log.info("inbox.unmatched", sender=addr(msg.from_email), subject=(msg.subject or "")[:80])
        if outcome in MARK_READ or outcome.startswith("booking."):
            to_mark.append(msg.gmail_message_id)
    result: dict[str, Any] = dict(sorted(stats.items()))
    if stats["error"]:
        result["cursor"] = "kept"  # the next run reads these messages again; stored ones are skipped
        db.set_setting(fail_key, dict(list(failures.items())[-FAILURES_KEPT:]))
    else:
        db.set_setting(key, new_cursor)
    for gmail_id in to_mark:
        try:
            mailbox.mark_read(gmail_id)
        except MailboxError as exc:
            log.warning("inbox.mark_read_failed", kind=exc.kind)
    rc.stats["inbox"] = result
    log.info("inbox.done", **{k.replace(".", "_"): v for k, v in result.items() if isinstance(v, int)})
    return result
