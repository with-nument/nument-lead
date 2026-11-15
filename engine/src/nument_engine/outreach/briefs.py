"""Pre-call briefs (write_precall_brief), emailed 60 to 75 minutes before each booked call (contract 4.8).

The outreach run comes every 15 minutes, so a call normally gets its brief in the run that falls 60 to 75 minutes
before `leads.meeting_at`. A run that was late still sends it, up to 10 minutes before the call; never after.
One brief per booking: a reschedule (a new `meeting_at`) gets a fresh brief, a copy of the same booking does not.

The brief is built from what we know (offer and why now, verified facts, the startup profile, signals, the whole
email thread and what they wrote when booking), goes to the alert recipients through the existing Resend path
(`ops.emails.deliver`) and is logged as a `brief` activity with its content. When email is not set up nothing
is written and nothing is spent; when sending fails the written brief is kept and sent again next run.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from psycopg import Connection

from .. import db
from ..logging import get_logger
from ..models import PrecallBrief
from ..ops import emails, notify
from ..pipeline import ai
from ..pipeline.runs import RunContext, outreach_mode
from . import replies
from .inbox import activity, new_text

log = get_logger()

IST: Final = ZoneInfo("Asia/Kolkata")
EARLIEST: Final = timedelta(minutes=75)
LATEST: Final = timedelta(minutes=10)
THREAD_MAX_CHARS: Final = 6000
FACTS_MAX: Final = 25
SIGNALS_MAX: Final = 6
AI_FAILURES_BEFORE_STOP: Final = 3

_DUE: Final = """
select l.id::text as lead_id, l.meeting_at, l.stage, l.business_id::text as business_id,
       b.name as company, b.country, b.city, b.website,
       pc.name as contact_name,
       lo.offer_key, o.name as offer_name, o.promise as offer_promise, o.timeline as offer_timeline, lo.why_now,
       bk.payload as booking
  from public.leads l
  join public.businesses b on b.id = l.business_id
  left join public.v_primary_contact pc on pc.business_id = l.business_id
  left join public.lead_offers lo on lo.lead_id = l.id and lo.rank = 1
  left join public.offers o on o.key = lo.offer_key
  left join lateral (
      select a.payload from public.activities a where a.lead_id = l.id and a.type = 'booking'
       order by a.at desc, a.id desc limit 1
  ) bk on true
 where l.meeting_at is not null and l.meeting_at > %(latest)s and l.meeting_at <= %(earliest)s
   and l.stage not in ('lost', 'not_a_fit', 'wrong_contact')
 order by l.meeting_at
"""


@dataclass(frozen=True)
class Due:
    row: dict[str, Any]

    @property
    def lead_id(self) -> str:
        return str(self.row["lead_id"])

    @property
    def meeting_at(self) -> datetime:
        value: datetime = self.row["meeting_at"]
        return value

    @property
    def key(self) -> str:
        """The booking this brief belongs to: the call time (a reschedule is a new brief)."""
        return self.meeting_at.astimezone(UTC).isoformat()


def due(now: datetime, limit: int | None = None) -> list[Due]:
    rows = db.fetch_all(_DUE, {"latest": now + LATEST, "earliest": now + EARLIEST})
    return [Due(r) for r in (rows[:limit] if limit else rows)]


def previous(lead_id: str, key: str) -> dict[str, Any] | None:
    """The latest brief activity for this booking, if one was written."""
    row = db.fetch_one(
        "select payload from public.activities where lead_id = %s and type = 'brief' "
        "and payload ->> 'meeting_at' = %s order by at desc, id desc limit 1",
        [lead_id, key],
    )
    return dict(row["payload"]) if row else None


def thread_text(conn: Connection[Any] | None, lead_id: str) -> str:
    """The email conversation, oldest first: what we sent and what they wrote (quoted history removed)."""
    rows = db.fetch_all(
        """
        select m.direction, m.step, m.body, coalesce(m.sent_at, m.created_at) as at
          from public.email_messages m join public.email_threads t on t.id = m.thread_id
         where t.lead_id = %s and (m.direction = 'in' or m.status = 'sent')
         order by coalesce(m.sent_at, m.created_at)
        """,
        [lead_id],
        conn=conn,
    )
    parts = []
    for r in rows:
        who = "Them" if r["direction"] == "in" else (f"Us (day {r['step']})" if r["step"] is not None else "Us")
        body = new_text(r["body"]) if r["direction"] == "in" else str(r["body"] or "").strip()
        parts.append(f"{who}, {r['at']:%d %b}:\n{body}")
    text = "\n\n".join(parts)
    return text[-THREAD_MAX_CHARS:]


def profile_lines(conn: Connection[Any] | None, business_id: str) -> list[str]:
    """The startup profile in plain lines; only what is known."""
    p = db.fetch_one("select * from public.startup_profiles where business_id = %s", [business_id], conn=conn)
    if not p:
        return []
    lines: list[str] = []
    if p.get("team_size") is not None:
        lines.append(f"team size: {p['team_size']}")
    if p.get("tech_team") and p["tech_team"] != "unknown":
        lines.append(f"tech team: {str(p['tech_team']).replace('_', ' ')}")
    if p.get("product_status") and p["product_status"] != "unknown":
        lines.append(f"product: {str(p['product_status']).replace('_', ' ')}")
    if p.get("no_code_platform"):
        lines.append(f"built on: {p['no_code_platform']}")
    if p.get("funding_round") or p.get("funding_usd"):
        amount = f" ${float(p['funding_usd']):,.0f}" if p.get("funding_usd") else ""
        lines.append(f"funding: {p.get('funding_round') or 'raised'}{amount}")
    if p.get("uses_ai") is not None:
        lines.append(f"uses AI: {'yes' if p['uses_ai'] else 'no'}")
    return lines


def facts_for(conn: Connection[Any] | None, business_id: str) -> list[dict[str, Any]]:
    rows = db.fetch_all(
        "select id::text as id, field, value from public.facts where business_id = %s and verified "
        "and field not in ('phone', 'email', 'jsonld_phone', 'jsonld_email') "
        "order by verified_at desc nulls last, created_at desc limit %s",
        [business_id, FACTS_MAX],
        conn=conn,
    )
    return [dict(r) for r in rows]


def signals_for(conn: Connection[Any] | None, business_id: str) -> list[dict[str, Any]]:
    rows = db.fetch_all(
        "select id::text as id, type, quote, details from public.signals where business_id = %s "
        "order by observed_at desc limit %s",
        [business_id, SIGNALS_MAX],
        conn=conn,
    )
    out = []
    for r in rows:
        details = r.get("details") or {}
        summary = str(details.get("summary") or r.get("quote") or "").strip()
        out.append({"id": r["id"], "type": r["type"], "summary": summary[:200]})
    return out


def meeting_text(at: datetime, their_zone: ZoneInfo) -> str:
    """'Wed 18 Nov, 8:00 pm India time (9:30 am New York time)'."""
    ours = f"{replies.time_text(at, IST)} India time"
    if their_zone.key == IST.key:
        return ours
    return f"{ours} ({replies.time_text(at, their_zone)} {replies.zone_label(their_zone)})"


def inputs_for(d: Due) -> dict[str, Any]:
    r = d.row
    booking = r.get("booking") or {}
    zone = replies.recipient_zone(r.get("country"), r.get("city"))
    offer = (
        f"{r['offer_key']}: {r['offer_name']}. {r['offer_promise']} ({r['offer_timeline']})"
        if r.get("offer_key")
        else "not chosen yet"
    )
    signals = signals_for(None, r["business_id"])
    why_now = str(r.get("why_now") or "") or (signals[0]["summary"] if signals else "")
    return {
        "company": str(r.get("company") or ""),
        "founder_name": str(r.get("contact_name") or ""),
        "offer": offer,
        "why_now": why_now or "not known",
        "facts": facts_for(None, r["business_id"]),
        "thread": thread_text(None, d.lead_id) or "(no emails yet)",
        "meeting_time": meeting_text(d.meeting_at, zone),
        "booking_notes": str(booking.get("notes") or ""),
        "profile": profile_lines(None, r["business_id"]),
        "signals": signals,
    }


def tidy(brief: PrecallBrief, offer_key: str | None) -> PrecallBrief:
    """The offer key must be a real offer: the lead's own when the writer named another."""
    known = {r["key"] for r in db.fetch_all("select key from public.offers")}
    if brief.offer_key not in known and offer_key:
        return brief.model_copy(update={"offer_key": offer_key})
    return brief


BRIEF_HTML: Final = """{% extends "base.html" %}
{% set sans = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif" %}
{% block body %}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr><td class="pad" style="padding:32px 36px 8px 36px;">
    <div style="font:600 12px/16px {{ sans }};letter-spacing:.08em;text-transform:uppercase;color:#3333CC;">Call brief</div>
    <div class="h1" style="font:400 30px/38px Georgia,'Times New Roman',serif;color:#1f1f1f;margin:10px 0 8px 0;">{{ headline }}</div>
    <div style="font:400 15px/23px {{ sans }};color:#666666;">{{ when }}</div>
  </td></tr>
  {% for section in sections %}
  <tr><td class="pad" style="padding:18px 36px 0 36px;">
    <div style="font:600 13px/20px {{ sans }};color:#999999;">{{ section.title }}</div>
    {% if section.text %}<div style="font:400 15px/23px {{ sans }};color:#1f1f1f;margin-top:4px;">{{ section.text }}</div>{% endif %}
    {% if section.points %}<ul style="margin:6px 0 0 0;padding-left:20px;font:400 15px/23px {{ sans }};color:#1f1f1f;">
      {% for item in section.points %}<li style="margin:0 0 4px 0;">{{ item }}</li>{% endfor %}
    </ul>{% endif %}
  </td></tr>
  {% endfor %}
  <tr><td class="pad" style="padding:22px 36px 32px 36px;">
    <a class="btn" href="{{ lead_url }}" style="display:inline-block;background:#2a2c33;color:#ffffff;font:600 14px/20px {{ sans }};text-decoration:none;padding:10px 18px;border-radius:10px;margin-right:6px;">Open the lead</a>
    {% if call_url %}<a class="btn" href="{{ call_url }}" style="display:inline-block;background:#ffffff;color:#1f1f1f;border:1px solid #e6e6e6;font:600 14px/20px {{ sans }};text-decoration:none;padding:9px 17px;border-radius:10px;">Join the call</a>{% endif %}
  </td></tr>
</table>
{% endblock %}
{% block footer %}Sent about an hour before each booked call.{% endblock %}
"""


def sections(brief: PrecallBrief, notes: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {"title": "Who they are", "text": brief.summary, "points": []},
        {"title": "Why now", "text": brief.why_now, "points": []},
    ]
    if notes:
        out.append({"title": "What they wrote when booking", "text": notes, "points": []})
    out += [
        {"title": "What they need", "text": "", "points": list(brief.what_they_need)},
        {"title": "Ask them", "text": "", "points": list(brief.questions)},
        {"title": "Offer to lead with", "text": brief.offer_key.replace("_", " "), "points": []},
    ]
    if brief.risks:
        out.append({"title": "Watch out for", "text": "", "points": list(brief.risks)})
    return out


def brief_email(d: Due, brief: PrecallBrief) -> notify.Email:
    r = d.row
    booking = r.get("booking") or {}
    company = str(r.get("company") or "a startup")
    who = str(r.get("contact_name") or "").strip()
    zone = replies.recipient_zone(r.get("country"), r.get("city"))
    when = meeting_text(d.meeting_at, zone)
    headline = f"{company}{f', {who}' if who else ''}"
    subject = f"Call brief: {headline}, {replies.time_text(d.meeting_at, IST)} India time"
    lead_url = f"{emails.app_url()}/leads/{d.lead_id}"
    call_url = str(booking.get("location") or "")
    notes = str(booking.get("notes") or "")
    parts = sections(brief, notes)
    html = replies.render(
        BRIEF_HTML,
        subject=subject,
        preheader=brief.summary[:120],
        date_label=emails.day_label(d.meeting_at.astimezone(IST).date()),
        headline=headline,
        when=when,
        sections=parts,
        lead_url=lead_url,
        call_url=call_url,
    )
    lines = [headline, when, ""]
    for s in parts:
        lines.append(f"{s['title']}:")
        if s["text"]:
            lines.append(str(s["text"]))
        lines += [f"- {item}" for item in s["points"]]
        lines.append("")
    lines.append(f"Open the lead: {lead_url}")
    if call_url:
        lines.append(f"Join the call: {call_url}")
    return notify.Email(subject, html, "\n".join(lines) + "\n")


def deliver(email: notify.Email) -> int:
    """Send one email to the alert recipients (the same email for admins and everyone else: no money in it)."""
    return emails.deliver("alerts", lambda _admin: email)


def run(rc: RunContext, *, router: ai.AIRouter | None = None, now: datetime | None = None, **_: Any) -> dict[str, Any]:
    """Write and email the briefs that are due."""
    if outreach_mode() == "off":
        return {"skipped": "outreach off"}
    now = now or datetime.now(UTC)
    todo = due(now, rc.opts.limit)
    stats: Counter[str] = Counter(due=len(todo))
    if rc.opts.dry_run or not todo:
        return {**stats, **({"skipped": "dry run"} if rc.opts.dry_run else {})}
    if not notify.email_configured():
        return {**stats, "skipped": "email is not set up"}
    failures = 0
    for d in todo:
        before = previous(d.lead_id, d.key)
        if before and int(before.get("sent") or 0) > 0:
            stats["already_sent"] += 1
            continue
        brief: PrecallBrief | None = None
        tag = ""
        if before and isinstance(before.get("content"), Mapping):
            brief, tag = PrecallBrief.model_validate(before["content"]), str(before.get("model") or "")
            stats["reused"] += 1
        else:
            if router is None:
                try:
                    router = ai.router_for(rc)
                except ai.AIUnavailable as exc:
                    stats["ai.unavailable"] += 1
                    log.warning("briefs.no_ai", reason=exc.reason)
                    break
            try:
                res = ai.call(
                    router, "write_precall_brief", inputs_for(d), PrecallBrief, run_id=rc.run_id, lead_id=d.lead_id
                )
            except ai.AIBudgetStop:
                stats["stopped.budget"] += 1
                break
            except ai.AIUnavailable:
                stats["ai.failed"] += 1
                failures += 1
                if failures >= AI_FAILURES_BEFORE_STOP:
                    break
                continue
            failures = 0
            brief, tag = tidy(res.output, d.row.get("offer_key")), res.tag
        sent = deliver(brief_email(d, brief))
        with db.tx("engine", {"run_id": rc.run_id, "stage": "briefs"}) as conn:
            activity(
                conn,
                d.lead_id,
                "brief",
                {
                    "meeting_at": d.key,
                    "uid": (d.row.get("booking") or {}).get("uid"),
                    "sent": sent,
                    "model": tag,
                    "content": brief.model_dump(),
                },
            )
        stats["sent" if sent else "send_failed"] += 1
    result = dict(sorted(stats.items()))
    rc.stats["briefs"] = result
    log.info("briefs.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
