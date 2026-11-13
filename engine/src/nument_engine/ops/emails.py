"""The engine's emails: the morning list, alerts and the weekly report.

Each email is HTML from `templates/email` (base.html and morning.html are the founder-approved design) plus a
plain-text part. This module loads the data and renders; `notify` picks the recipients and sends. Money
(today's spend, the cap, money won) is shown only to admins: everyone else gets the same email without it.

- Morning list: the last phase of the morning run (non-essential). New A and B leads created today, best
  first, the top five as cards; follow-ups due; KPIs. With no new leads it is a short email that says so.
  Sent once per IST day, so a re-run never mails the team twice.
- Alerts: a failed run, spend near or at the daily cap, and the other alert-level health checks
  (`health.notify_alerts`, once a day for each problem).
- Weekly report: the stored report's numbers (`learn.report`), the caller view for non-admins.

Rendering is strict (an undefined value raises), so a broken email fails the phase instead of being sent.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, TypedDict

import jinja2
from markupsafe import Markup, escape

from .. import db
from ..learn import fmt
from ..learn.metrics import ist_day_start
from ..logging import get_logger
from ..pipeline.runs import RunContext
from ..settings import get_settings
from . import notify
from .notify import Email, Kind

log = get_logger()

TEMPLATES: Final = Path(__file__).resolve().parent / "templates" / "email"
TOP_LEADS: Final = 5
FOLLOWUPS_MAX: Final = 8
MORNING_SENT_KEY: Final = "morning_email_sent"
GRADE_STYLE: Final[dict[str, tuple[str, str]]] = {  # the app's grade badges (web/src/lib/grades.ts)
    "A": ("#E3F1D8", "#496D21"),
    "B": ("#E8EFFC", "#3333CC"),
    "C": ("#F5F5F5", "#666666"),
    "D": ("#FAFAFA", "#666666"),
}
GREEN: Final = "#496D21"
RED: Final = "#b4321f"
AMBER: Final = "#b7791f"
SIGNAL_WHY: Final[dict[str, str]] = {
    "public_ask": "Asked publicly for help",
    "tender": "Published a tender",
    "hiring_builder": "Hiring someone to build software",
    "hiring_frontdesk": "Hiring front desk staff",
    "review_pain": "Reviews say they are hard to reach",
    "ads_running": "Running ads",
    "no_booking": "No online booking on their site",
    "slow_site": "Their website is slow",
    "new_place": "Newly opened",
    "new_branch": "Opening a new branch",
    "news": "In the news",
    "funding": "Recently raised funding",
}
SUBCATEGORY_LABEL: Final[dict[str, str]] = {
    "ivf_fertility": "IVF",
    "hair_transplant": "Hair transplant",
    "therapy_group": "Therapy",
    "study_abroad": "Study abroad",
    "coaching_institute": "Coaching",
    "property_services": "Property services",
}
DOCTOR_SEGMENTS: Final = ("clinics",)  # staff are doctors in these segments


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_CODE_STYLE = (
    "font-family:Menlo,Consolas,monospace;font-size:13px;color:#1f1f1f;background:#f5f5f5;"
    "border-radius:4px;padding:1px 4px;"
)


def inline(text: object) -> Markup:
    """Escape, then show `code` as a quiet monospace span and **bold** as bold (weekly report lines)."""
    out = str(escape(str(text)))
    out = re.sub(r"`([^`]+)`", rf'<span style="{_CODE_STYLE}">\1</span>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return Markup(out)  # escaped above; only our own markup is added


@lru_cache
def _env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["inline"] = inline
    return env


def app_url() -> str:
    return get_settings().app_url.rstrip("/")


def render(template: str, **context: Any) -> str:
    """One template with the shared values (app URL, preheader, date label) filled in."""
    base = {"app_url": app_url(), "preheader": "", "date_label": ""}
    return _env().get_template(template).render(**{**base, **context})


def day_label(day: date) -> str:
    """'Thursday, 13 Nov'."""
    return f"{day:%A}, {day.day} {day:%b}"


def cut(text: str | None, limit: int) -> str:
    """At most `limit` characters, cut at a word, with an ellipsis."""
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    note: str = ""
    color: str = ""


# ---------------------------------------------------------------------------
# Morning list
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeadCard:
    id: str
    grade: str
    name: str
    place: str
    score: int
    why: str
    facts: str
    url: str
    phone: str = ""
    wa: str = ""
    tel: str = ""

    @property
    def grade_bg(self) -> str:
        return GRADE_STYLE.get(self.grade, GRADE_STYLE["D"])[0]

    @property
    def grade_fg(self) -> str:
        return GRADE_STYLE.get(self.grade, GRADE_STYLE["D"])[1]


@dataclass(frozen=True)
class FollowUp:
    name: str
    step: str
    url: str


@dataclass
class Morning:
    day: date
    leads: list[LeadCard]  # every new A and B lead created today, best first
    followups: list[FollowUp] = field(default_factory=list)
    contacted_week: int = 0
    spend_inr: float = 0.0
    cap_inr: float = 750.0

    @property
    def grade_a(self) -> int:
        return sum(lead.grade == "A" for lead in self.leads)


MORNING_LEADS_SQL: Final = """
select l.id::text as lead_id, l.grade, l.message, l.created_at,
       b.name, b.city, b.locality, b.segment_id, b.subcategory, b.rating::float as rating, b.review_count,
       b.staff_count, b.branches_count,
       s.total::float as total, s.judge_note, s.reasons,
       pc.phone_e164, pc.phone_type,
       sig.type as sig_type, sig.quote as sig_quote, sig.details ->> 'summary' as sig_summary,
       sig.observed_at as sig_at,
       bk.value as booking
from public.leads l
join public.businesses b on b.id = l.business_id
left join public.scores s on s.id = l.score_id
left join public.v_primary_contact pc on pc.business_id = l.business_id
left join lateral (
  select g.type, g.quote, g.details, g.observed_at from public.signals g
  where g.business_id = l.business_id
  order by (g.expires_at > now()) desc, g.points desc, g.observed_at desc
  limit 1
) sig on true
left join public.v_verified_facts bk on bk.business_id = l.business_id and bk.field = 'booking_method'
where l.created_at >= %(day)s
  and l.grade in ('A', 'B')
  and l.stage not in ('lost', 'not_a_fit', 'wrong_contact')
  and not exists (select 1 from public.suppression su where su.web_domain = b.web_domain)
order by s.total desc nulls last, l.grade, l.created_at
"""

FOLLOWUPS_SQL: Final = """
select lead_id::text as lead_id, company, which, due_on from public.v_followups_due
"""


def _age(observed: datetime | None, now: datetime) -> str:
    if not isinstance(observed, datetime):
        return ""
    days = (now.astimezone(fmt.IST).date() - observed.astimezone(fmt.IST).date()).days
    if days <= 0:
        return "seen today"
    if days == 1:
        return "seen yesterday"
    return f"seen {days} days ago"


def _reason_strings(reasons: Any) -> list[str]:
    if not isinstance(reasons, Mapping):
        return []
    out: list[str] = []
    for key in ("intent", "fit"):
        value = reasons.get(key)
        items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        out += [str(v).strip() for v in items if isinstance(v, str) and v.strip() and "=" not in v]
    return out


def why_now(r: Mapping[str, Any], now: datetime) -> str:
    """The strongest signal in one line, else the judge's note, else the score reasons."""
    label = SIGNAL_WHY.get(str(r.get("sig_type") or ""), "")
    summary, quote = cut(r.get("sig_summary"), 180), cut(r.get("sig_quote"), 140)
    age = _age(r.get("sig_at"), now)
    if summary:
        return summary
    if label:
        head = f"{label}, {age}" if age else label
        return f'{head}: "{quote}"' if quote else head + "."
    if r.get("judge_note"):
        return cut(r["judge_note"], 200)
    reasons = _reason_strings(r.get("reasons"))
    return cut("; ".join(reasons[:2]), 200) + ("." if reasons else "")


def _booking_text(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("value")
    return cut(str(value), 40) if isinstance(value, str) and value.strip() else ""


def key_facts(r: Mapping[str, Any]) -> str:
    """Google reviews, doctors or staff, branches and how they take bookings."""
    parts: list[str] = []
    reviews, rating = r.get("review_count"), r.get("rating")
    if reviews:
        text = f"{fmt.group_indian(int(reviews))} Google review{'s' if int(reviews) != 1 else ''}"
        parts.append(text + (f", rated {float(rating):.1f}" if rating else ""))
    staff = r.get("staff_count")
    if staff:
        doctors = str(r.get("segment_id") or "").split("-")[0] in DOCTOR_SEGMENTS
        parts.append(plural(int(staff), "doctor") if doctors else f"{int(staff)} staff")
    branches = r.get("branches_count")
    if branches and int(branches) > 1:
        parts.append(f"{int(branches)} branches")
    booking = _booking_text(r.get("booking"))
    if booking:
        parts.append(f"booking: {booking.lower()}")
    elif r.get("sig_type") == "no_booking":
        parts.append("no online booking on their site")
    return " · ".join(parts)


def place_of(r: Mapping[str, Any]) -> str:
    where = ", ".join(str(x) for x in (r.get("locality"), r.get("city")) if x)
    sub = str(r.get("subcategory") or "")
    what = SUBCATEGORY_LABEL.get(sub, sub.replace("_", " ").capitalize())
    return " · ".join(x for x in (where, what) if x)


def contact_links(phone: str | None, phone_type: str | None, message: str | None) -> dict[str, str]:
    """WhatsApp (wa.me opens the app on a phone and WhatsApp Web on a computer) for mobiles, else a call link."""
    if not phone:
        return {}
    from ..sheet.design import phone_display

    if phone_type == "mobile":
        text = urllib.parse.quote(message or "")
        return {"phone": phone_display(phone), "wa": f"https://wa.me/{phone.lstrip('+')}?text={text}"}
    return {"phone": phone_display(phone), "tel": f"tel:{phone}"}


def lead_card(r: Mapping[str, Any], now: datetime) -> LeadCard:
    return LeadCard(
        id=str(r["lead_id"]),
        grade=str(r["grade"]),
        name=str(r["name"]),
        place=place_of(r),
        score=round(float(r.get("total") or 0)),
        why=why_now(r, now),
        facts=key_facts(r),
        url=f"{app_url()}/leads/{r['lead_id']}",
        **_links(contact_links(r.get("phone_e164"), r.get("phone_type"), r.get("message"))),
    )


class Links(TypedDict):
    phone: str
    wa: str
    tel: str


def _links(links: Mapping[str, str]) -> Links:
    return {"phone": links.get("phone", ""), "wa": links.get("wa", ""), "tel": links.get("tel", "")}


def followup(r: Mapping[str, Any], today: date) -> FollowUp:
    step = "Day 3 follow-up" if r["which"] == "d3" else "Day 7 follow-up"
    if isinstance(r.get("due_on"), date) and r["due_on"] < today:
        step += ", overdue"
    return FollowUp(name=str(r["company"]), step=step, url=f"{app_url()}/leads/{r['lead_id']}")


def load_morning(now: datetime | None = None) -> Morning:
    """Today's numbers for the morning list (IST day)."""
    now = now or datetime.now(UTC)
    today = now.astimezone(fmt.IST).date()
    rows = db.fetch_all(MORNING_LEADS_SQL, {"day": ist_day_start(today)})
    followups = [followup(r, today) for r in db.fetch_all(FOLLOWUPS_SQL)]
    spend = db.fetch_one("select inr::float as inr from public.v_spend_today") or {}
    return Morning(
        day=today,
        leads=[lead_card(r, now) for r in rows],
        followups=followups,
        contacted_week=int(db.scalar("select contacted_this_week from public.v_kpis_week") or 0),
        spend_inr=float(spend.get("inr") or 0.0),
        cap_inr=float(db.get_setting("daily_cap_inr", 750)),
    )


def render_morning(m: Morning, *, admin: bool) -> Email:
    n, label = len(m.leads), day_label(m.day)
    top = m.leads[:TOP_LEADS]
    shown_followups = m.followups[:FOLLOWUPS_MAX]
    more_followups = len(m.followups) - len(shown_followups)
    if n:
        headline = f"{plural(n, 'new lead')} {'is' if n == 1 else 'are'} ready"
        intro = (
            "It has a fresh reason to talk now and a message ready to send."
            if n == 1
            else "Best first. Each one has a fresh reason to talk now and a message ready to send."
        )
        subject = f"{plural(n, 'new lead')} for {label}"
        names = [lead.name for lead in top[:2]]
        preheader = ", ".join(names) + (f" and {n - len(names)} more" if n > len(names) else "")
    else:
        headline = "No new leads today"
        intro = "The engine ran, but nothing new reached grade A or B this morning. " + (
            "The follow-ups below still need you." if m.followups else "Older leads are still in the app."
        )
        subject = f"No new leads for {label}"
        preheader = f"{plural(len(m.followups), 'follow-up')} due today" if m.followups else "Nothing new this morning"
    last = (
        Kpi("Spend", fmt.inr(m.spend_inr), f"of {fmt.inr(m.cap_inr)}")
        if admin
        else Kpi("This week", str(m.contacted_week), "messages sent")
    )
    kpis = [
        Kpi("New today", str(n), "best first"),
        Kpi("Grade A", str(m.grade_a), "start here" if m.grade_a else "", GREEN if m.grade_a else ""),
        Kpi("Follow-ups", str(len(m.followups)), "due today"),
        last,
    ]
    spend, cap = (fmt.inr(m.spend_inr), fmt.inr(m.cap_inr)) if admin else ("", "")
    html = render(
        "morning.html",
        subject=subject,
        preheader=preheader,
        date_label=label,
        headline=headline,
        intro=intro,
        kpis=kpis,
        leads=top,
        new_count=n,
        more=n > len(top),
        followups=shown_followups,
        followups_more=more_followups,
        spend=spend,
        cap=cap,
    )
    return Email(subject, html, morning_text(m, headline, intro, admin=admin))


def morning_text(m: Morning, headline: str, intro: str, *, admin: bool) -> str:
    base = app_url()
    lines = [f"Your morning list, {day_label(m.day)}", "", f"{headline}.", intro, ""]
    for i, lead in enumerate(m.leads[:TOP_LEADS], 1):
        lines.append(f"{i}. {lead.name} ({lead.grade}, {lead.score}/100)" + (f", {lead.place}" if lead.place else ""))
        if lead.why:
            lines.append(f"   Why now: {lead.why}")
        if lead.facts:
            lines.append(f"   {lead.facts}")
        lines.append(f"   Open lead: {lead.url}")
        if lead.wa:
            lines.append(f"   WhatsApp: {lead.wa}")
        elif lead.tel:
            lines.append(f"   Call: {lead.phone}")
        lines.append("")
    if len(m.leads) > TOP_LEADS:
        lines += [f"See all {len(m.leads)} in the app: {base}/", ""]
    if not m.leads:
        lines += [f"Open the app: {base}/", ""]
    if m.followups:
        lines.append("Follow-ups due today:")
        lines += [f"- {f.name}, {f.step}: {f.url}" for f in m.followups[:FOLLOWUPS_MAX]]
        if len(m.followups) > FOLLOWUPS_MAX:
            lines.append(f"- and {len(m.followups) - FOLLOWUPS_MAX} more in the app")
        lines.append("")
    footer = "Sent every morning by 7:30 IST."
    if admin:
        footer += f" Spend today {fmt.inr(m.spend_inr)} of {fmt.inr(m.cap_inr)}."
    lines += [footer, f"Email settings: {base}/settings/email"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

LEVELS: Final[dict[str, tuple[str, str, int]]] = {
    "fail": ("Stopped", RED, 0),
    "alert": ("Alert", RED, 1),
    "warn": ("Warning", AMBER, 2),
}


@dataclass(frozen=True)
class AlertItem:
    title: str
    detail: str
    fix: str = ""
    status: str = "alert"
    money: bool = False  # the detail holds money: left out for non-admins

    @property
    def level(self) -> str:
        return LEVELS.get(self.status, LEVELS["alert"])[0]

    @property
    def color(self) -> str:
        return LEVELS.get(self.status, LEVELS["alert"])[1]


_RUN_DETAIL = re.compile(r"^\w+, started (?P<at>.+? IST): failed \((?P<error>.*)\)$")


def _run_detail(detail: str) -> str:
    """'failed, started 13 Nov 2026, 06:00 IST: failed (X)' as 'Started 13 Nov 2026, 06:00 IST. Last error: X'."""
    m = _RUN_DETAIL.match(detail.strip())
    if not m:
        return detail
    return f"Started {m['at']}. Last error: {m['error']}"


def alert_item(name: str, status: str, detail: str) -> AlertItem:
    """A health check in plain words: what happened and what to do."""
    kind = name.split(".", 1)[1] if "." in name else ""
    if name.startswith("run."):
        return AlertItem(
            f"The {kind.replace('_', ' ')} run failed",
            _run_detail(detail),
            "The Engine page shows which phase stopped and why. Run now starts it again.",
            status,
        )
    if name == "spend":
        reached = status in ("alert", "fail")
        return AlertItem(
            "Spend reached the daily cap" if reached else "Spend is near the daily cap",
            detail,
            "Paid work has stopped until midnight IST. Raise the cap on the Engine page if today needs more."
            if reached
            else "Paid phases stop one by one as spend gets closer to the cap.",
            status,
            money=True,
        )
    if name == "database":
        return AlertItem("The database is filling up", detail, "Prune old data or plan an upgrade.", status)
    if name == "migrations":
        return AlertItem("Database changes are waiting", detail, "Run nlead db migrate.", status)
    if name == "sheets":
        return AlertItem("The sheet sync is off", detail, "", status)
    if name.startswith("ai.") and name.endswith(".breaker"):
        provider = name.split(".")[1].capitalize()
        return AlertItem(
            f"{provider} is paused after errors", detail, "It retries by itself when the pause ends.", status
        )
    if name.startswith("ai."):
        return AlertItem(f"{kind.split('.')[0].capitalize()} cannot run", detail, "", status)
    if name.startswith("source."):
        return AlertItem(f"The {kind.replace('_', ' ')} source needs a look", detail, "", status)
    return AlertItem(name, detail, "", status)


def _run_url() -> str:
    """This GitHub Actions run, when the email is sent from one."""
    server, repo, run_id = (os.environ.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else ""


def render_alerts(items: Sequence[AlertItem], *, admin: bool, run_url: str = "", day: date | None = None) -> Email:
    if not items:
        raise ValueError("an alert email needs at least one alert")
    ordered = sorted(items, key=lambda a: LEVELS.get(a.status, LEVELS["alert"])[2])
    shown = [a if admin or not a.money else replace(a, detail="") for a in ordered]
    n = len(shown)
    headline = shown[0].title if n == 1 else f"{n} things need attention"
    intro = "Here is what happened and where to look." if n == 1 else "Most urgent first. Here is where to look."
    subject = f"Alert: {headline}"
    day = day or datetime.now(fmt.IST).date()
    html = render(
        "alert.html",
        subject=subject,
        preheader="; ".join(a.title for a in shown),
        date_label=day_label(day),
        headline=headline,
        intro=intro,
        items=shown,
        run_url=run_url,
    )
    lines = [f"{headline}.", intro, ""]
    for a in shown:
        lines.append(f"- {a.level}: {a.title}" + (f". {a.detail}" if a.detail else ""))
        if a.fix:
            lines.append(f"  {a.fix}")
    lines += ["", f"Engine page: {app_url()}/engine"]
    if run_url:
        lines.append(f"Run log: {run_url}")
    lines += ["", "Sent when something needs you, at most once a day for each problem."]
    return Email(subject, html, "\n".join(lines) + "\n")


def send_alerts(items: Sequence[AlertItem]) -> int:
    """Email the alerts to everyone opted into alerts; returns how many emails were accepted."""
    if not items:
        return 0
    run_url = _run_url()
    return deliver("alerts", lambda admin: render_alerts(items, admin=admin, run_url=run_url))


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------

WEEKLY_SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("test_groups", "Test groups"),
    ("outcomes", "Lost and not now"),
    ("quality", "Lead quality"),
    ("cost", "Cost"),
    ("health", "Engine health"),
    ("changes", "What the engine changed"),
    ("eval_audit", "Eval and audit"),
)


def render_weekly(content: Mapping[str, Any], markdown: str, *, admin: bool) -> Email:
    """The weekly report email. Non-admins get `content['caller']` (no money won, no cost section)."""
    c: Mapping[str, Any] = content if admin else content.get("caller", content)
    h = c["headline"]
    period = str(content["period"]["label"])
    contacted, replied = int(h.get("contacted") or 0), int(h.get("replied") or 0)
    won = int(h.get("won") or 0)
    kpis = [
        Kpi("Leads added", str(h.get("leads_added", 0)), f"A or B: {h.get('good_added', 0)}"),
        Kpi("Contacted", str(contacted), "first messages"),
        Kpi("Replies", str(replied), f"{fmt.pct(replied / contacted)} reply rate" if contacted else ""),
        Kpi("Meetings", str(h.get("meetings", 0)), "discovery calls"),
        Kpi("Proposals", str(h.get("proposals", 0)), "sent"),
        Kpi("Won", str(won), "new clients", GREEN if won else ""),
    ]
    if admin and "money_won_inr" in h:
        retainers = h.get("retainer_monthly") or {}
        note = f"plus {fmt.amounts(retainers)} a month in retainers" if retainers else "deal value"
        kpis.append(Kpi("Money won", fmt.inr(h["money_won_inr"]), note))
    sections = []
    for key, title in WEEKLY_SECTIONS:
        part = c.get(key)
        if key == "cost" and not admin:
            continue
        lines = [str(x) for x in (part or {}).get("lines", [])] if isinstance(part, Mapping) else []
        if key == "quality" and isinstance(part, Mapping):
            lines += [f"Exclusion idea: {x}" for x in part.get("exclusion_lines", [])]
        if lines:
            sections.append({"title": title, "lines": lines})
    actions = [str(a) for a in c.get("actions", [])]
    subject = f"Weekly report: {period}"
    html = render(
        "weekly.html",
        subject=subject,
        preheader=actions[0].replace("`", "").replace("**", "") if actions else f"The week of {period}",
        date_label=period,
        headline=f"The week of {period}",
        intro="What worked, what to cut and how the engine did.",
        kpi_rows=[kpis[i : i + 4] for i in range(0, len(kpis), 4)],
        actions=actions,
        sections=sections,
    )
    return Email(subject, html, markdown.rstrip() + f"\n\nOpen Insights: {app_url()}/insights\n")


def send_weekly(content: Mapping[str, Any], admin_markdown: str, caller_markdown: str) -> int:
    return deliver(
        "weekly",
        lambda admin: render_weekly(content, admin_markdown if admin else caller_markdown, admin=admin),
    )


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _tagged(email: Email) -> Email:
    """Mark emails from a dev run, so nobody acts on test data."""
    if get_settings().app_env == "dev":
        return replace(email, subject=f"[dev] {email.subject}")
    return email


def deliver(kind: Kind, build: Callable[[bool], Email]) -> int:
    """Render once per audience (admins, everyone else) and send each recipient their own email."""
    if not notify.email_configured():
        return 0
    to = notify.recipients(kind)
    sent = 0
    for admin in (True, False):
        group = [r for r in to if r.admin == admin]
        if group:
            sent += notify.send(_tagged(build(admin)), group)
    return sent


def morning(rc: RunContext) -> dict[str, Any]:
    """The email phase of the morning run: the morning list, once per IST day."""
    data = load_morning()
    stats: dict[str, Any] = {"leads": len(data.leads), "followups": len(data.followups)}
    render_morning(data, admin=True)  # always render, so a broken email shows up as a failed phase
    if rc.opts.dry_run:
        return {**stats, "skipped": "dry run"}
    if not notify.email_configured():
        return {**stats, "skipped": "RESEND_API_KEY is not set"}
    today = data.day.isoformat()
    if (db.get_setting(MORNING_SENT_KEY, {}) or {}).get("day") == today:
        return {**stats, "skipped": "already sent today"}
    sent = deliver("morning", lambda admin: render_morning(data, admin=admin))
    if sent:
        db.set_setting(MORNING_SENT_KEY, {"day": today, "sent": sent})
    log.info("emails.morning", sent=sent, **stats)
    return {**stats, "sent": sent}


# ---------------------------------------------------------------------------
# Samples: `nlead notify test` and `nlead notify preview`
# ---------------------------------------------------------------------------

SAMPLE_KINDS: Final[tuple[str, ...]] = ("morning", "morning-empty", "alert", "weekly")


def sample_morning(*, empty: bool = False, day: date | None = None) -> Morning:
    day = day or datetime.now(fmt.IST).date()
    base = app_url()
    rows = [
        ("A", "Sunrise Skin & Hair Clinic", "Baner, Pune · Dermatology", 78,
         'Hiring front desk staff, seen 3 days ago: "Front desk executive to handle patient calls and appointments"',
         "612 Google reviews, rated 4.7 · 6 doctors · no online booking on their site", "+919811012345"),
        ("A", "Kavya Fertility Centre", "Indiranagar, Bengaluru · IVF", 74,
         "Recent reviews mention calls going unanswered after 6 pm.",
         "Registered ART centre · 2 branches · 430 Google reviews, rated 4.5", "+919845012345"),
        ("B", "Smile Studio Dental", "Andheri West, Mumbai · Dental", 63,
         "Posted on a forum asking for a WhatsApp booking setup.",
         "318 Google reviews, rated 4.6 · 3 doctors · booking: phone only", "+912226301234"),
        ("B", "Clear Path Physio", "Sector 18, Noida · Physio", 58,
         "No online booking on their site.", "212 Google reviews, rated 4.8 · 4 doctors", "+919810098765"),
    ]  # fmt: skip
    leads = [
        LeadCard(
            id=f"sample-{i}",
            grade=g,
            name=name,
            place=place,
            score=score,
            why=why,
            facts=facts,
            url=f"{base}/leads",
            **_links(contact_links(phone, "landline" if phone.startswith("+9122") else "mobile", "Hi, quick question")),
        )
        for i, (g, name, place, score, why, facts, phone) in enumerate(rows)
    ]
    followups = [
        FollowUp("Aarna Dental Care", "Day 3 follow-up", f"{base}/"),
        FollowUp("Lotus Eye Hospital", "Day 7 follow-up", f"{base}/"),
    ]
    return Morning(
        day=day,
        leads=[] if empty else leads,
        followups=followups[:1] if empty else followups,
        contacted_week=37,
        spend_inr=412.0,
        cap_inr=750.0,
    )


def sample_alerts() -> list[AlertItem]:
    return [
        alert_item(
            "run.morning",
            "alert",
            "failed, started 13 Nov 2026, 06:00 IST: failed (EssentialPhaseFailed: essential phase 'score' failed: "
            "database timeout)",
        ),
        alert_item("spend", "warn", "₹642 of ₹750 today (86%): past the 80% alert line"),
    ]


def sample_weekly() -> tuple[dict[str, Any], str]:
    headline = {"leads_added": 84, "good_added": 31, "contacted": 52, "replied": 9, "meetings": 3,
                "proposals": 1, "won": 1, "money_won_inr": 85000.0,
                "retainer_monthly": {"INR": 40000.0}}  # fmt: skip
    content: dict[str, Any] = {
        "period": {"start": "2026-11-02", "end": "2026-11-08", "label": "2 to 8 Nov 2026"},
        "headline": headline,
        "actions": [
            "Raise the daily quota for clinics-in: `clinics-in:review_pain:v1` books meetings at 12% from 25 contacted.",
            "Consider pausing `education-in:fit_only:v1`: 0% meetings from 22 contacted.",
            "Add 2 name(s) or domain(s) to exclusions.yaml (see Lead quality).",
        ],
        "test_groups": {"lines": ["Scale `clinics-in:review_pain:v1`: 12% meetings from 25 contacted."]},
        "outcomes": {
            "lines": [
                "This week: lost 2 (price 1, no reply 1); not now 1 (no need right now 1).",
                "Last 180 days: lost 9 (no reply 4, price 3, chose another vendor 2); not now 5 (no need right now 5).",
            ]
        },
        "quality": {
            "lines": [
                "Wrong contacts: 3.8% of numbers tried in the last 30 days (2 of 52). Target under 5%.",
                "New A and B leads with a phone the business published: 94% (from its own website: 71%). "
                "Target 90% or more.",
                "Median signal age at first contact: 6.0 days. Target under 30 days.",
                "Thumbs this week: 14 up, 3 down.",
            ],
            "exclusion_lines": ["domain `practo.com`: 3 thumbs down"],
        },
        "cost": {
            "lines": [
                "Spend this week: ₹2,940 ($35.12), ₹420 a day on average against the ₹750 daily cap.",
                "Per researched business: ₹1.12; per good lead: ₹94.84; per meeting: ₹980; per won client: ₹2,940.",
            ]
        },
        "health": {"lines": ["Runs: morning 7 ok; night 6 ok, 1 partial; weekly 1 ok."]},
        "changes": {"lines": ["No weight changes: not enough new outcomes yet."]},
        "eval_audit": {"lines": ["Last eval 8 Nov 2026: passed on 20 businesses."]},
    }
    caller = {k: v for k, v in content.items() if k != "cost"}
    caller["headline"] = {k: v for k, v in headline.items() if k not in ("money_won_inr", "retainer_monthly")}
    content["caller"] = caller
    markdown = "## Weekly report, 2 to 8 Nov 2026\n\n" + "\n".join(f"- {a}" for a in content["actions"]) + "\n"
    return content, markdown


def sample(kind: str, *, admin: bool = True) -> Email:
    """A realistic sample of one email kind, with made-up businesses."""
    if kind == "morning":
        return render_morning(sample_morning(), admin=admin)
    if kind == "morning-empty":
        return render_morning(sample_morning(empty=True), admin=admin)
    if kind == "alert":
        return render_alerts(sample_alerts(), admin=admin, run_url="https://github.com/with-nument/nument-lead/actions")
    if kind == "weekly":
        content, markdown = sample_weekly()
        return render_weekly(content, markdown, admin=admin)
    raise ValueError(f"unknown sample {kind!r}; expected one of {', '.join(SAMPLE_KINDS)}")


def write_previews(out: Path) -> list[Path]:
    """Every sample as HTML and text, for the founder and admin view and the team view."""
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for kind in SAMPLE_KINDS:
        for admin in (True, False):
            email = sample(kind, admin=admin)
            stem = kind if admin else f"{kind}-team"
            for suffix, body in ((".html", email.html), (".txt", email.text)):
                path = out / f"{stem}{suffix}"
                path.write_text(body, encoding="utf-8")
                written.append(path)
    return written
