"""The 12-day sequence (contract 4.6, lane E5a): drafts routed to auto or review, follow-ups scheduled in the
recipient's sending windows, and the send loop with every safety gate (phase `send` of the outreach run).

Order of one run:
1. Enqueue. Every open thread whose day-0 email is a draft: with settings `outreach.mode` 'auto' and the bar met
   (lead score >= `outreach.auto_min_score`, critic score >= `outreach.auto_min_critic`, a verified email, no
   `message_flagged` activity since the draft, clean content) the thread becomes 'auto' and day 0 'queued';
   otherwise day 0 waits in 'review' for a person. A thread that may never be mailed is stopped here already.
   In 'manual' mode anything 'queued' goes back to 'review': a person approves every send.
2. Crash recovery. A message left in 'sending' for over 10 minutes is looked up in Gmail by its Message-ID: if
   it went out it is recorded as sent, otherwise it goes back in the queue (with the same Message-ID).
3. Send. Due messages ('queued' or, in manual mode only, 'approved'), replies first, then follow-ups, then new
   conversations. Before each one, all of these hold or nothing is sent:
   - mode not off, `outreach.paused` false, the mailbox warming or active, the bounce rate under the limit;
   - production, or dev with `outreach.sandbox_to` (every recipient replaced by it);
   - the warm-up cap for the last 24 hours, `max_sends_per_run` and `min_seconds_between_sends`;
   - a weekday window in the recipient's local time;
   - not suppressed (address or domain), not do_not_contact, the address still the contact's and not invalid;
   - country allowed and not blocked; never a guessed address in a published-only country;
   - the lead still at the stage the sequence expects (a person moving it stops the sequence);
   - day 0: no other conversation with the domain in the last `domain_cooldown_days`;
   - no placeholder left, no link in day 0, the footer present.
   The message is claimed ('sending', with its RFC Message-ID stored) before Gmail is called, so it can never go
   out twice. Then it is recorded: 'sent', the Gmail ids, an `email_sent` activity, the lead from 'new' to
   'contacted' on day 0, and the follow-ups scheduled.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from psycopg import Connection

from .. import db
from ..logging import get_logger
from ..pipeline.runs import RunContext, outreach_mode
from ..settings import get_settings
from . import compose, windows
from . import mailbox as mb
from .gmail import MailboxClient, MailboxError, Outgoing, Sent
from .net import outreach_config

log = get_logger()

RECOVER_AFTER: Final = timedelta(minutes=10)
SEND_GRACE_S: Final = 120.0  # no new send starts this long after the run's deadline (the job ends soon after)
CANDIDATES: Final = 200  # due messages looked at per run (most are held by a window or a cap)
UNSENT: Final = ("draft", "review", "approved", "queued")
DONE_REASONS: Final = frozenset({"suppressed", "do_not_contact"})  # nothing is ever sent to them again
FILLED_LATER: Final = frozenset({"{plan_link}", "{case_study}"})  # the plans phase fills these before day 3, 7
MAX_REFERENCES: Final = 10

MESSAGE_SQL: Final = """
select m.id::text as id, m.thread_id::text as thread_id, m.step, m.subject, m.body, m.status, m.scheduled_for,
       m.rfc_message_id, m.created_at, m.updated_at,
       t.lead_id::text as lead_id, t.contact_id::text as contact_id, t.to_email, t.to_domain,
       t.mode as thread_mode, t.status as thread_status, t.paused_until, t.gmail_thread_id,
       l.stage, l.message_check_score, s.total as score_total,
       b.country, b.city, b.address,
       c.email as contact_email, c.email_status, c.email_origin, coalesce(c.do_not_contact, false) as do_not_contact
from public.email_messages m
join public.email_threads t on t.id = m.thread_id
join public.leads l on l.id = t.lead_id
join public.businesses b on b.id = l.business_id
left join public.scores s on s.id = l.score_id
left join public.contacts c on c.id = t.contact_id
where m.direction = 'out'
"""
Row = dict[str, Any]


# ---------------------------------------------------------------------------
# The rules of this run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rules:
    mode: str
    production: bool
    sandbox_to: str | None
    postal_address: str | None
    app_url: str
    allowed: frozenset[str]
    blocked: frozenset[str]
    published_only: frozenset[str]
    windows: tuple[windows.Window, ...]
    max_per_run: int
    min_gap_s: float
    cooldown_days: int
    followup_days: tuple[int, ...]
    auto_min_score: float
    auto_min_critic: float
    auto_email_status: str

    @property
    def sendable(self) -> tuple[str, ...]:
        """Statuses that may go out: in manual mode only what a person approved."""
        return ("approved",) if self.mode == "manual" else ("queued", "approved")


def _text_setting(key: str) -> str | None:
    value = db.get_setting(key, None)
    text = str(value).strip() if value is not None else ""
    return text or None


def load_rules(rc: RunContext) -> Rules:
    """Settings and config/outreach.yaml, read once per run (the switches are read again before every send)."""
    cfg = outreach_config()
    auto = cfg.get("auto_send") or {}
    days = sorted({int(d) for d in cfg.get("sequence_days") or [0, 3, 7, 12]})
    settings = get_settings()
    return Rules(
        mode=outreach_mode(),
        production=rc.opts.env == "prod" and settings.app_env == "prod",
        sandbox_to=_text_setting("outreach.sandbox_to"),
        postal_address=_text_setting("outreach.postal_address"),
        app_url=settings.app_url,
        allowed=compose.country_codes(cfg.get("allowed_countries") or []),
        blocked=compose.country_codes(cfg.get("blocked_countries") or []),
        published_only=compose.country_codes(cfg.get("published_only_countries") or []),
        windows=windows.parse_windows(cfg.get("windows") or []),
        max_per_run=int(cfg.get("max_sends_per_run", 3)),
        min_gap_s=float(cfg.get("min_seconds_between_sends", 90)),
        cooldown_days=int(cfg.get("domain_cooldown_days", 90)),
        followup_days=tuple(d for d in days if d > 0),
        auto_min_score=float(db.get_setting("outreach.auto_min_score", auto.get("min_score", 75))),
        auto_min_critic=float(db.get_setting("outreach.auto_min_critic", auto.get("min_critic", 9))),
        auto_email_status=str(auto.get("email_status", "verified")),
    )


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def _same_address(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def suppressed(email: str | None, domain: str | None, *, conn: Connection[Any] | None = None) -> bool:
    """The address or its domain is on the never-contact list."""
    return bool(
        db.scalar(
            "select exists (select 1 from public.suppression su where "
            "(su.email is not null and lower(su.email) = lower(%(email)s)) or "
            "(su.web_domain is not null and lower(su.web_domain) = lower(%(domain)s)))",
            {"email": email or "", "domain": domain or ""},
            conn=conn,
        )
    )


def domain_in_cooldown(row: Row, days: int, now: datetime, *, conn: Connection[Any] | None = None) -> bool:
    """Another conversation with this domain sent something in the last `days` days, or is sending now."""
    return bool(
        db.scalar(
            "select exists (select 1 from public.email_threads t2 join public.email_messages m2 "
            "on m2.thread_id = t2.id where lower(t2.to_domain) = lower(%(domain)s) and t2.id <> %(thread)s::uuid "
            "and m2.direction = 'out' and (m2.status = 'sending' or (m2.status = 'sent' and m2.sent_at > %(since)s)))",
            {"domain": row["to_domain"] or "", "thread": row["thread_id"], "since": now - timedelta(days=days)},
            conn=conn,
        )
    )


def hard_block(row: Row, rules: Rules, now: datetime, *, conn: Connection[Any] | None = None) -> str | None:
    """Why this message may never be sent (the conversation is stopped), or None."""
    if suppressed(row["to_email"], row["to_domain"], conn=conn):
        return "suppressed"
    if row["do_not_contact"]:
        return "do_not_contact"
    # A re-check after the thread was made can find the address invalid: nothing more goes to it, replies too.
    known = row["contact_id"] is not None and _same_address(row["contact_email"], row["to_email"])
    if known and row["email_status"] == "invalid":
        return "email_invalid"
    if row["step"] is None:  # a reply to someone who wrote to us: the cold-email rules do not apply
        return None
    if row["contact_id"] is None:
        return "no_contact"
    if not _same_address(row["contact_email"], row["to_email"]):
        return "address_changed"
    country = (row["country"] or "").strip().lower()
    if country in rules.blocked:
        return "blocked_country"
    if country not in rules.allowed:
        return "country_not_allowed"
    if country in rules.published_only and row["email_origin"] in (None, "guess"):
        return "guess_in_published_only"
    if row["stage"] != ("new" if row["step"] == 0 else "contacted"):
        return "stage_changed"
    if row["step"] == 0 and domain_in_cooldown(row, rules.cooldown_days, now, conn=conn):
        return "domain_cooldown"
    return None


def zone_of(row: Row) -> ZoneInfo | None:
    return windows.zone_for(row["country"], row["city"], row["address"])


def earlier_steps(row: Row, *, conn: Connection[Any] | None = None) -> str | None:
    """A follow-up waits for day 0 to be sent and for every earlier step to be sent or dropped."""
    rows = db.fetch_all(
        "select step, status from public.email_messages where thread_id = %s and direction = 'out' "
        "and step is not null and step < %s",
        [row["thread_id"], row["step"]],
        conn=conn,
    )
    by_step = {r["step"]: r["status"] for r in rows}
    if by_step.get(0) != "sent":
        return "day0_not_sent"
    if any(status in (*UNSENT, "sending") for status in by_step.values()):
        return "earlier_step_pending"
    return None


def hold_reason(row: Row, rules: Rules, now: datetime, *, conn: Connection[Any] | None = None) -> str | None:
    """Why this message waits for a later run (nothing changes), or None."""
    zone = zone_of(row)
    if zone is None:
        return "no_time_zone"
    if not windows.in_window(now, zone, rules.windows):
        return "outside_window"
    if row["contact_id"] is not None and row["email_status"] not in ("verified", "likely"):
        return f"email_{row['email_status'] or 'unknown'}"  # wait for the verifier to settle it
    if row["step"] is None:
        return None
    if row["step"] > 0:
        return earlier_steps(row, conn=conn)
    return None


# ---------------------------------------------------------------------------
# The email as it leaves
# ---------------------------------------------------------------------------


def thread_headers(row: Row, *, conn: Connection[Any] | None = None) -> tuple[str, str | None, tuple[str, ...]]:
    """(subject, In-Reply-To, References) for a message. Follow-ups answer the latest message of the
    conversation with `Re: <day 0 subject>`; a reply answers the latest message the person sent us."""
    if row["step"] == 0:
        return str(row["subject"] or ""), None, ()
    history = db.fetch_all(
        "select direction, subject, rfc_message_id from public.email_messages where thread_id = %s "
        "and rfc_message_id is not null and ((direction = 'out' and status = 'sent') or direction = 'in') "
        "order by coalesce(sent_at, created_at), created_at",
        [row["thread_id"]],
        conn=conn,
    )
    first = db.scalar(
        "select subject from public.email_messages where thread_id = %s and direction = 'out' and step = 0",
        [row["thread_id"]],
        conn=conn,
    )
    if row["step"] is None:
        received = [h for h in history if h["direction"] == "in"]
        upto = history.index(received[-1]) + 1 if received else len(history)
        chain = [h["rfc_message_id"] for h in history[:upto]]
        base = row["subject"] or (received[-1]["subject"] if received else None) or first
    else:
        chain = [h["rfc_message_id"] for h in history]
        base = first
    if len(chain) > MAX_REFERENCES:  # keep the first and the latest ones (RFC 5322 3.6.4)
        chain = [chain[0], *chain[-(MAX_REFERENCES - 1) :]]
    return compose.reply_subject(str(base or "")), (chain[-1] if chain else None), tuple(chain)


@dataclass(frozen=True)
class Decision:
    action: str  # send | hold | block | review | stop
    reason: str = ""
    outgoing: Outgoing | None = None
    sandboxed: bool = False


def decide(
    row: Row, rules: Rules, sender: mb.Mailbox, now: datetime, *, conn: Connection[Any] | None = None
) -> Decision:
    """Every gate for one message, in order: stop the conversation, wait, back to review, or send this."""
    reason = hard_block(row, rules, now, conn=conn)
    if reason:
        return Decision("block", reason)
    reason = hold_reason(row, rules, now, conn=conn)
    if reason:
        return Decision("hold", reason)
    try:
        subject, in_reply_to, references = thread_headers(row, conn=conn)
    except compose.ComposeError as err:
        return Decision("review", err.reason)
    left = compose.placeholders(subject) + compose.placeholders(str(row["body"] or ""))
    if left:
        if row["step"] and set(left) <= FILLED_LATER:
            return Decision("hold", "waiting_for_link")
        return Decision("review", "placeholder")
    try:
        final = compose.compose(
            thread_id=row["thread_id"],
            to_email=row["to_email"],
            subject=subject,
            body=str(row["body"] or ""),
            step=row["step"],
            mailbox=sender.email,
            app_url=rules.app_url,
            postal_address=rules.postal_address,
            production=rules.production,
            sandbox_to=rules.sandbox_to,
        )
    except compose.ComposeError as err:
        if err.reason in ("no_footer", "no_sandbox"):
            return Decision("stop", err.reason)
        if err.reason == "bad_address":
            return Decision("block", err.reason)
        return Decision("review", err.reason)
    outgoing = Outgoing(
        to=final.to,
        subject=final.subject,
        body=final.body,
        rfc_message_id=row["rfc_message_id"] or compose.new_rfc_message_id(),
        from_name=sender.display_name or "Nument",
        in_reply_to=in_reply_to,
        references=references,
        gmail_thread_id=row["gmail_thread_id"] if row["step"] != 0 else None,
        unsubscribe_url=final.unsubscribe_url,
        unsubscribe_mailto=final.unsubscribe_mailto,
    )
    return Decision("send", outgoing=outgoing, sandboxed=final.sandboxed)


# ---------------------------------------------------------------------------
# State changes
# ---------------------------------------------------------------------------


def _activity(conn: Connection[Any], lead_id: str, kind: str, payload: dict[str, Any], at: datetime) -> None:
    conn.execute(
        "insert into public.activities (lead_id, source, type, at, payload) values (%s, 'engine', %s, %s, %s)",
        [lead_id, kind, at, db.Jsonb(payload)],
    )


def stop_thread(row: Row, reason: str, now: datetime) -> None:
    """End a conversation that may not be mailed: 'done' for suppression and do-not-contact, else 'stopped'
    (approved replies may still go). Every unsent step is cancelled. A blocked reply cancels only itself."""
    done = reason in DONE_REASONS
    with db.tx() as conn:
        if row["step"] is None and not done:
            conn.execute(
                "update public.email_messages set status = 'cancelled', error = %s, updated_at = %s "
                "where id = %s and status in ('draft','review','approved','queued')",
                [reason, now, row["id"]],
            )
            return
        conn.execute(
            "update public.email_threads set status = %s, stop_reason = %s, updated_at = %s "
            "where id = %s and status <> 'done'",
            ["done" if done else "stopped", reason, now, row["thread_id"]],
        )
        conn.execute(
            "update public.email_messages set status = 'cancelled', error = %s, updated_at = %s "
            "where thread_id = %s and direction = 'out' and status in ('draft','review','approved','queued')",
            [reason, now, row["thread_id"]],
        )
        _activity(conn, row["lead_id"], "sequence_stopped", {"thread_id": row["thread_id"], "reason": reason}, now)
    log.info("send.thread_stopped", reason=reason, step=row["step"])


def to_review(row: Row, reason: str, now: datetime) -> None:
    """Back to a person: the content breaks a rule only a person can fix."""
    db.execute(
        "update public.email_messages set status = 'review', error = %s, updated_at = %s "
        "where id = %s and status in ('queued','approved')",
        [reason, now, row["id"]],
    )


def claim(row: Row, rfc_message_id: str, now: datetime) -> str | None:
    """Mark the message 'sending' and store its Message-ID before Gmail is called. Only succeeds while nobody
    changed it since it was read (status, subject and body) and its conversation may still be mailed. Returns
    the stored Message-ID (an earlier attempt's, when there was one)."""
    claimed = db.fetch_one(
        "update public.email_messages m set status = 'sending', rfc_message_id = coalesce(m.rfc_message_id, %(rfc)s), "
        "updated_at = %(now)s from public.email_threads t "
        "where m.id = %(id)s and t.id = m.thread_id and m.status = %(status)s "
        "and m.subject is not distinct from %(subject)s and m.body is not distinct from %(body)s "
        "and ((m.step is not null and t.status = 'open') or (m.step is null and t.status <> 'done')) "
        "and (t.paused_until is null or t.paused_until <= %(now)s) "
        "returning m.rfc_message_id",
        {
            "rfc": rfc_message_id,
            "now": now,
            "id": row["id"],
            "status": row["status"],
            "subject": row["subject"],
            "body": row["body"],
        },
    )
    return str(claimed["rfc_message_id"]) if claimed else None


def unclaim(row: Row, now: datetime) -> None:
    """Gmail refused the send: the message goes back to the status it had (its Message-ID stays)."""
    db.execute(
        "update public.email_messages set status = %s, updated_at = %s where id = %s and status = 'sending'",
        [row["status"], now, row["id"]],
    )


def fail(row: Row, err: MailboxError, now: datetime) -> None:
    db.execute(
        "update public.email_messages set status = 'failed', error = %s, updated_at = %s "
        "where id = %s and status = 'sending'",
        [f"{err.kind}: {err}"[:500], now, row["id"]],
    )


def schedule_followups(
    conn: Connection[Any], row: Row, sent_at: datetime, rules: Rules, now: datetime
) -> dict[int, datetime]:
    """After day 0: each follow-up at sent day + N, at the same local time, moved into the next window. In auto
    mode they are queued (day 0 was approved by a person or by the bar); in manual mode a person approves each."""
    zone = zone_of(row)
    if zone is None:
        return {}
    draft_to = "queued" if rules.mode == "auto" else "review"
    planned: dict[int, datetime] = {}
    for day in rules.followup_days:
        when = windows.followup_at(sent_at, day, zone, rules.windows)
        changed = conn.execute(
            "update public.email_messages set scheduled_for = %s, "
            "status = case when status = 'draft' then %s else status end, updated_at = %s "
            "where thread_id = %s and direction = 'out' and step = %s "
            "and status in ('draft','review','approved','queued')",
            [when, draft_to, now, row["thread_id"], day],
        ).rowcount
        if changed:
            planned[day] = when
    return planned


def record_sent(row: Row, sent: Sent, sender: mb.Mailbox, rules: Rules, now: datetime, *, sandboxed: bool) -> None:
    """Everything that follows a send, in one transaction."""
    today = mb.ist_day(sent.sent_at)
    with db.tx() as conn:
        updated = conn.execute(
            "update public.email_messages set status = 'sent', sent_at = %s, gmail_message_id = %s, "
            "rfc_message_id = %s, error = null, updated_at = %s where id = %s and status = 'sending'",
            [sent.sent_at, sent.gmail_message_id, sent.rfc_message_id, now, row["id"]],
        ).rowcount
        if not updated:
            log.warning("send.record_skipped", step=row["step"])
            return
        conn.execute(
            "update public.email_threads set gmail_thread_id = coalesce(gmail_thread_id, %s), "
            "mailbox_id = coalesce(mailbox_id, %s), updated_at = %s where id = %s",
            [sent.gmail_thread_id or None, sender.id, now, row["thread_id"]],
        )
        _activity(
            conn,
            row["lead_id"],
            "email_sent",
            {"thread_id": row["thread_id"], "message_id": row["id"], "step": row["step"], "sandbox": sandboxed},
            sent.sent_at,
        )
        if row["step"] == 0:
            conn.execute(
                "update public.leads set stage = 'contacted' where id = %s and stage = 'new'", [row["lead_id"]]
            )
            schedule_followups(conn, row, sent.sent_at, rules, now)
        conn.execute(
            "update public.mailboxes set sent_today = case when sent_day = %(day)s then sent_today + 1 else 1 end, "
            "sent_day = %(day)s, warmup_started_on = coalesce(warmup_started_on, %(day)s), updated_at = now() "
            "where id = %(id)s",
            {"day": today, "id": sender.id},
        )
    log.info("send.sent", step=row["step"], sandbox=sandboxed)


# ---------------------------------------------------------------------------
# 1. Enqueue
# ---------------------------------------------------------------------------


def _flagged(row: Row) -> bool:
    return bool(
        db.scalar(
            "select exists (select 1 from public.activities where lead_id = %s and type = 'message_flagged' "
            "and at >= %s)",
            [row["lead_id"], row["created_at"]],
        )
    )


def meets_auto_bar(row: Row, rules: Rules) -> bool:
    """The founder's bar for sending without a person: score, critic, a verified email, no flag, clean text."""
    if rules.mode != "auto":
        return False
    if row["score_total"] is None or float(row["score_total"]) < rules.auto_min_score:
        return False
    if row["message_check_score"] is None or float(row["message_check_score"]) < rules.auto_min_critic:
        return False
    if row["email_status"] != rules.auto_email_status:
        return False
    try:
        compose.check_content(subject=str(row["subject"] or ""), body=str(row["body"] or ""), step=0)
    except compose.ComposeError:
        return False
    return not _flagged(row)


def enqueue(rc: RunContext, rules: Rules, now: datetime) -> dict[str, Any]:
    """Route each new day-0 draft to auto or review, and stop the conversations that may never be mailed."""
    out: dict[str, Any] = {"queued": 0, "review": 0, "stopped": Counter()}
    if rules.mode == "manual" and not rc.opts.dry_run:
        out["back_to_review"] = db.execute(
            "update public.email_messages m set status = 'review', updated_at = %s from public.email_threads t "
            "where t.id = m.thread_id and m.direction = 'out' and m.status = 'queued' and t.status <> 'done'",
            [now],
        )
    rows = db.fetch_all(
        MESSAGE_SQL + " and m.step = 0 and m.status = 'draft' and t.status = 'open' "
        "order by s.total desc nulls last, m.created_at limit %s",
        [rc.opts.limit or 500],
    )
    for row in rows:
        reason = hard_block(row, rules, now)
        if reason:
            out["stopped"][reason] += 1
            if not rc.opts.dry_run:
                stop_thread(row, reason, now)
            continue
        auto = meets_auto_bar(row, rules)
        out["queued" if auto else "review"] += 1
        if rc.opts.dry_run:
            continue
        with db.tx() as conn:
            if auto:
                conn.execute(
                    "update public.email_threads set mode = 'auto', updated_at = %s where id = %s",
                    [now, row["thread_id"]],
                )
            conn.execute(
                "update public.email_messages set status = %s, updated_at = %s where id = %s and status = 'draft'",
                ["queued" if auto else "review", now, row["id"]],
            )
    out["stopped"] = dict(out["stopped"])
    return out


# ---------------------------------------------------------------------------
# 2. Crash recovery
# ---------------------------------------------------------------------------


def _requeue_status(row: Row, rules: Rules) -> str:
    if rules.mode == "manual" or row["step"] is None or row["thread_mode"] == "review":
        return "approved"
    return "queued"


def recover(rules: Rules, sender: mb.Mailbox, client: MailboxClient, now: datetime) -> dict[str, int]:
    """Settle messages left in 'sending' by a crash: sent (found in Gmail) or back in the queue."""
    out: Counter[str] = Counter()
    rows = db.fetch_all(MESSAGE_SQL + " and m.status = 'sending' and m.updated_at < %s", [now - RECOVER_AFTER])
    for row in rows:
        to = (rules.sandbox_to if not rules.production else row["to_email"]) or row["to_email"]
        try:
            found = client.find_sent(row["rfc_message_id"], to=to) if row["rfc_message_id"] else None
        except MailboxError as err:
            out["errors"] += 1
            if err.kind == "auth":
                mb.record_error(sender, err)
                break
            continue
        if found is not None:
            record_sent(row, found, sender, rules, now, sandboxed=not rules.production)
            out["sent"] += 1
        else:
            db.execute(
                "update public.email_messages set status = %s, error = 'recovered: not sent', updated_at = %s "
                "where id = %s and status = 'sending'",
                [_requeue_status(row, rules), now, row["id"]],
            )
            out["requeued"] += 1
        log.warning("send.recovered", found=found is not None, step=row["step"])
    return dict(out)


# ---------------------------------------------------------------------------
# 3. Send
# ---------------------------------------------------------------------------


@dataclass
class Clock:
    """Time for the send loop (tests replace both)."""

    now: Callable[[], datetime]
    sleep: Callable[[float], None]


def _last_send(sender: mb.Mailbox) -> datetime | None:
    value = db.scalar(
        "select max(m.sent_at) from public.email_messages m join public.email_threads t on t.id = m.thread_id "
        "where m.direction = 'out' and m.sent_at is not null and (t.mailbox_id = %s or t.mailbox_id is null)",
        [sender.id],
    )
    return value if isinstance(value, datetime) else None


def _switches_off() -> str | None:
    if outreach_mode() == "off":
        return "outreach off"
    if mb.is_paused():
        return "paused"
    box = mb.current()
    if box is None or not box.usable:
        return f"mailbox {box.status if box else 'missing'}"
    return None


def send_due(
    rc: RunContext,
    rules: Rules,
    sender: mb.Mailbox,
    open_client: Callable[[], MailboxClient],
    clock: Clock,
    stats: dict[str, Any],
) -> None:
    """The send loop: every gate before each message, claim, send, record."""
    held: Counter[str] = stats.setdefault("held", Counter())
    stopped: Counter[str] = stats.setdefault("conversations_stopped", Counter())
    reviewed: Counter[str] = stats.setdefault("to_review", Counter())
    budget = min(rules.max_per_run, rc.opts.limit or rules.max_per_run)
    now = clock.now()
    cap = mb.daily_cap(sender.warmup_started_on, mb.ist_day(now), mb.warmup_schedule())
    used = mb.sent_last_24h(sender.id, now)
    stats.update(cap_24h=cap, sent_24h=used)
    rows = db.fetch_all(
        MESSAGE_SQL + " and m.status = any(%(statuses)s) and (m.scheduled_for is null or m.scheduled_for <= %(now)s) "
        "and ((m.step is not null and t.status = 'open') or (m.step is null and t.status <> 'done')) "
        "and (t.paused_until is null or t.paused_until <= %(now)s) "
        "order by (m.step is null) desc, (coalesce(m.step, 0) > 0) desc, "
        "coalesce(m.scheduled_for, m.created_at), m.created_at limit %(limit)s",
        {"statuses": list(rules.sendable), "now": now, "limit": CANDIDATES},
    )
    sent_now = 0
    for row in rows:
        now = clock.now()
        if sent_now >= budget:
            stats["stopped"] = "per_run_cap"
            break
        if used >= cap:
            stats["stopped"] = "warmup_cap"
            break
        if rc.time_left() < -SEND_GRACE_S:
            stats["stopped"] = "deadline"
            break
        off = _switches_off()
        if off:
            stats["stopped"] = off
            break
        decision = decide(row, rules, sender, now)
        if decision.action == "stop":
            stats["stopped"] = decision.reason
            break
        if decision.action == "hold":
            held[decision.reason] += 1
            continue
        if decision.action == "block":
            stopped[decision.reason] += 1
            if not rc.opts.dry_run:
                stop_thread(row, decision.reason, now)
            continue
        if decision.action == "review":
            reviewed[decision.reason] += 1
            if not rc.opts.dry_run:
                to_review(row, decision.reason, now)
            continue
        outgoing = decision.outgoing
        if outgoing is None:
            continue
        if rc.opts.dry_run:
            stats["would_send"] = stats.get("would_send", 0) + 1
            sent_now += 1
            continue
        last = _last_send(sender)
        if last is not None:
            wait = (last + timedelta(seconds=rules.min_gap_s) - now).total_seconds()
            if wait > 0:
                if rc.time_left() - wait < -SEND_GRACE_S:
                    stats["stopped"] = "deadline"
                    break
                clock.sleep(wait)
                now = clock.now()
                off = _switches_off()  # a person may have paused while we waited
                if off:
                    stats["stopped"] = off
                    break
        rfc = claim(row, outgoing.rfc_message_id, now)
        if rfc is None:
            held["changed_meanwhile"] += 1
            continue
        try:
            client = open_client()
            sent = client.send(replace(outgoing, rfc_message_id=rfc))
        except MailboxError as err:
            stats["gmail_error"] = err.kind
            mb.record_error(sender, err)
            if err.maybe_sent:  # Gmail may have it: it stays claimed and recovery settles it
                stats["stopped"] = "gmail_unclear"
                break
            if err.kind == "invalid":  # this message is wrong; the others may go
                fail(row, err, now)
                stats["failed"] = stats.get("failed", 0) + 1
                continue
            unclaim(row, now)  # refused, so not sent: it goes out in a later run
            stats["stopped"] = f"gmail_{err.kind}"
            break
        record_sent(row, sent, sender, rules, clock.now(), sandboxed=decision.sandboxed)
        stats["sent"] = stats.get("sent", 0) + 1
        sent_now += 1
        used += 1


def run(
    rc: RunContext,
    *,
    mailbox: MailboxClient | None = None,
    clock: Clock | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Queue and send what is due (phase send). `mailbox` replaces the Gmail client in tests."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    clock = clock or Clock(now=lambda: datetime.now(UTC), sleep=time.sleep)
    rules = load_rules(rc)
    now = clock.now()
    stats: dict[str, Any] = {"mode": rules.mode, "production": rules.production}
    if rc.opts.dry_run:
        stats["dry_run"] = True
    stats["enqueued"] = enqueue(rc, rules, now)
    sender = mb.current()
    if sender is None:
        stats["stopped"] = "no mailbox"
        return stats
    clients: list[MailboxClient] = []

    def open_client() -> MailboxClient:
        if not clients:
            if mailbox is not None:
                clients.append(mailbox)
            else:
                from .gmail import connect

                clients.append(connect(sender.email))
        return clients[0]

    try:
        if not rc.opts.dry_run and sender.status not in ("error", "disconnected") and _has_stuck(now):
            try:
                stats["recovered"] = recover(rules, sender, open_client(), now)
            except MailboxError as err:
                mb.record_error(sender, err)
                stats["stopped"] = f"gmail_{err.kind}"
                return _finish(stats)
        reason = _ready(rc, rules, sender, now)
        if reason:
            stats["stopped"] = reason
            return _finish(stats)
        send_due(rc, rules, mb.current() or sender, open_client, clock, stats)
    except MailboxError as err:  # opening the client failed
        mb.record_error(sender, err)
        stats["stopped"] = f"gmail_{err.kind}"
    finally:
        for client in clients:
            if client is not mailbox and hasattr(client, "close"):
                client.close()
    return _finish(stats)


def _has_stuck(now: datetime) -> bool:
    return bool(
        db.scalar(
            "select exists (select 1 from public.email_messages where status = 'sending' and updated_at < %s)",
            [now - RECOVER_AFTER],
        )
    )


def _ready(rc: RunContext, rules: Rules, sender: mb.Mailbox, now: datetime) -> str | None:
    """Why nothing may be sent this run at all, or None."""
    off = _switches_off()
    if off:
        return off
    if not rules.production and not rules.sandbox_to:
        return "dev without outreach.sandbox_to"
    if not rules.postal_address:
        return "no postal address (settings outreach.postal_address)"
    bounces = mb.check_bounces(sender, now, dry_run=rc.opts.dry_run)
    if bounces.get("over_limit"):
        return "bounce rate"
    return None


def _finish(stats: dict[str, Any]) -> dict[str, Any]:
    """Counters as plain dicts for the run row; empty ones left out."""
    return {
        k: dict(v) if isinstance(v, Counter) else v for k, v in stats.items() if not (isinstance(v, Counter) and not v)
    }
