"""Database to sheet: the Today, Pipeline and Lead details tabs (Step 13.6).

The order of work is the lesson of 12 Nov 2026 (13.2.1):

1. READ      leads from `v_sheet_leads`, the sheet's metadata, and the current row order.
2. BUILD     every request for every tab, in memory.
3. VALIDATE  no money on the caller view, one id per row, payload under the API limit.
4. MARK      sheet_state = writing.
5. WRITE     one atomic batchUpdate per view: Google applies all of it or none of it.
6. SNAPSHOT  the editable values exactly as pull will read them, and sheet_state = ok, in one transaction.

A failure before step 6 leaves the old snapshot and the `writing` marker, so the next pull skips that sheet
and the next push rebuilds it. Nothing half-written is ever read back as an edit.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from psycopg import Connection

from .. import db
from ..logging import get_logger
from ..pipeline.runs import RunContext
from ..settings import get_settings
from . import client as gs
from . import design as d
from . import state as st
from .client import Target

log = get_logger()

MAX_PAYLOAD_BYTES: Final = 9_000_000  # the Sheets API refuses a batchUpdate over 10 MB
NEW_TAB_IDS: Final[dict[str, int]] = {"Today": 101, "Pipeline": 102, "Lead details": 103}  # + 100 per view
MONEY_PATTERN: Final = re.compile(r"ticket|budget|deal|₹|price|value", re.I)
_MONEY_AMOUNT: Final = re.compile(r"(₹|\bRs\.?|\bINR)\s?\d+(?:[.,]\d+)*\s?(?:crore|cr|lakhs?|lacs?|l|k)?\b", re.I)

# Editable Pipeline columns: database field -> header (13.3.5). Pull finds columns by these headers.
EDITABLE: Final[dict[str, str]] = {
    "stage": "Stage",
    "wa_at": "WA",
    "call_at": "Call",
    "d3_at": "Day 3",
    "d7_at": "Day 7",
    "meeting_at": "Meeting",
    "deal_value_inr": "Deal value",  # master only
    "notes": "Notes",
}


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    width: int
    group: str | None = None
    hidden: bool = False


def pipeline_columns(money: bool) -> list[Column]:
    """Pipeline columns (13.3.4). Group labels sit on the first column of each group."""
    cols = [
        Column("grade", "Grade", 52, "Who"),
        Column("company", "Company", 176),
        Column("person", "Person", 156),
        Column("phone", "Phone · WhatsApp", 222),
        Column("why", "Why now", 262, "Why now"),
        Column("stage", "Stage", 140, "Progress"),
        Column("wa", "WA", 78),
        Column("call", "Call", 78),
        Column("d3", "Day 3", 78),
        Column("d7", "Day 7", 78),
        Column("meeting", "Meeting", 84),
        Column("next", "Next step", 158),
        Column("due", "Due", 100),
        Column("bar", "Win chance", 128, "Outcome"),
    ]
    if money:
        cols.append(Column("deal", "Deal value", 112))
    cols.append(Column("notes", "Notes", 240))
    cols += [
        Column(key, header, width, hidden=True)
        for key, header, width in (
            ("chance", "Chance", 50),
            ("dd", "Due date", 80),
            ("queue", "Queue", 50),
            ("who", "Who", 80),
            ("wa_url", "WA link", 80),
            ("label", "Phone label", 80),
            ("group", "Test group", 80),
            ("id", "ID", 60),
        )
    ]
    return cols


def details_columns(money: bool) -> list[tuple[str, int]]:
    """Lead details columns (13.6.5): (header, width). The last column is the hidden lead id."""
    cols = [
        ("Grade", 52),
        ("Company", 176),
        ("Person & role", 196),
        ("Why now", 300),
        ("WhatsApp message", 420),
        ("Alternate message", 360),
        ("Day 3 follow-up", 280),
        ("Day 7 follow-up", 280),
        ("Score note", 300),
        ("Proof links", 230),
        ("Email", 210),
        ("Watch-outs", 190),
        ("Checked on", 100),
    ]
    if money:
        cols.append(("Can-pay notes", 280))
    cols.append(("ID", 60))
    return cols


@dataclass(frozen=True)
class Context:
    """Numbers and names every builder needs (settings, read once per push)."""

    today: dt.date
    send_per_day: int = 50
    today_rows_max: int = 60
    weekly_contact_target: int = 150
    associate_name: str = "Aditya"


@dataclass
class Built:
    """Everything one view needs, built in memory before anything is written."""

    target: Target
    requests: list[dict[str, Any]]
    snapshot: dict[str, dict[str, Any]]
    headers: list[str]
    cells: list[list[d.Cell]]
    full: bool
    tab_ids: dict[str, int]
    stats: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reading the database
# ---------------------------------------------------------------------------
LOAD_SQL: Final = """
select v.*,
       b.researched_at,
       pc.source_url                     as phone_source_url,
       dm.name                           as dm_name,
       dm.role                           as dm_role,
       sig.type                          as sig_type,
       sig.quote                         as sig_quote,
       sig.url                           as sig_url,
       sig.observed_at                   as sig_at,
       sig.details ->> 'summary'         as sig_summary,
       cv.verified_at                    as contact_verified_at
from public.v_sheet_leads v
join public.businesses b on b.id = v.business_id
left join public.v_primary_contact pc on pc.business_id = v.business_id
left join lateral (
  select c.name, c.role from public.contacts c
  where c.business_id = v.business_id and c.name is not null and not c.do_not_contact
  order by c.is_decision_maker desc, c.verified desc, c.created_at
  limit 1
) dm on true
left join lateral (
  -- the freshest active signal; for older leads the latest signal even if expired, so "Why now" stays filled
  select g.type, g.quote, g.url, g.observed_at, g.details from public.signals g
  where g.business_id = v.business_id
  order by (g.expires_at > now()) desc, g.points desc, g.observed_at desc
  limit 1
) sig on true
left join lateral (
  select max(c.verified_at) as verified_at from public.contacts c where c.business_id = v.business_id
) cv on true
"""


def load_rows(conn: Connection[Any] | None = None) -> list[dict[str, Any]]:
    rows = db.fetch_all(LOAD_SQL, conn=conn)
    for r in rows:
        r["lead_id"] = str(r["lead_id"])
        r["business_id"] = str(r["business_id"])
    return rows


def load_context(conn: Connection[Any] | None = None) -> Context:
    def setting(key: str, default: int) -> int:
        try:
            return max(1, int(db.get_setting(key, default, conn=conn)))
        except (TypeError, ValueError):
            return default

    return Context(
        today=d.today_ist(),
        send_per_day=setting("send_per_day", 50),
        today_rows_max=setting("today_rows_max", 60),
        weekly_contact_target=setting("weekly_contact_target", 150),
        associate_name=get_settings().associate_name or "Associate",
    )


def rank_key(r: dict[str, Any]) -> tuple[Any, ...]:
    """Best first: score, then grade, then the freshest signal (13.3.3)."""
    sig_at = r.get("sig_at") or r.get("top_signal_at")
    fresh = -sig_at.timestamp() if isinstance(sig_at, dt.datetime) else 0.0
    return (-float(r.get("score_total") or 0), r.get("grade") or "Z", fresh, r["lead_id"])


def order_rows(rows: list[dict[str, Any]], current: Sequence[str] | None, resort: bool = False) -> list[dict[str, Any]]:
    """Keep the order people left the rows in; new leads go to the end, best first (13.3.3)."""
    ranked = sorted(rows, key=rank_key)
    if resort or not current:
        return ranked
    by_id = {r["lead_id"]: r for r in rows}
    seen: set[str] = set()
    kept = []
    for lead_id in current:
        if lead_id in by_id and lead_id not in seen:
            kept.append(by_id[lead_id])
            seen.add(lead_id)
    return kept + [r for r in ranked if r["lead_id"] not in seen]


# ---------------------------------------------------------------------------
# Per-row values
# ---------------------------------------------------------------------------
def dates_of(r: dict[str, Any]) -> dict[str, dt.date | None]:
    return {k: d.as_date(r.get(k)) for k in d.DATE_FIELDS}


def has_phone(r: dict[str, Any]) -> bool:
    return bool(r.get("phone_e164"))


def is_mobile(r: dict[str, Any]) -> bool:
    return has_phone(r) and r.get("phone_type") == "mobile"


def first_touch(r: dict[str, Any]) -> str:
    if is_mobile(r):
        return "Send WhatsApp"
    if has_phone(r):
        return "Call"
    return "Send email" if r.get("email") else "Send intro"


def step2(r: dict[str, Any]) -> str:
    return "Call" if has_phone(r) else "Follow up"


def wa_url(r: dict[str, Any]) -> str:
    return d.wa_web_link(r.get("phone_e164"), r.get("phone_type"), r.get("message"))


def reach(r: dict[str, Any]) -> tuple[str, str, list[d.RichPart]]:
    """(label, link, rich parts) for the Phone column: the number opens WhatsApp Web when it is a mobile."""
    phone = d.phone_display(r.get("phone_e164"))
    if is_mobile(r):
        url = wa_url(r)
        return phone, url, [(phone, d.INK, False, url, None), ("   WhatsApp ↗", d.WA_GREEN, True, url, 9)]
    if phone:
        return phone, "", [(phone, d.INK, False, None, None)]
    if r.get("email"):
        url = f"mailto:{r['email']}"
        return "Email ↗", url, [("Email ↗", d.LINK, False, url, None)]
    return "No contact", "", [("No contact", d.FAINT, False, None, None)]


def person(r: dict[str, Any]) -> tuple[str, str]:
    """(name, role): the contact we reach, or the decision maker when the reachable line has no name."""
    if r.get("contact_name"):
        return r["contact_name"], r.get("contact_role") or ""
    return r.get("dm_name") or "", r.get("dm_role") or ""


def why_short(r: dict[str, Any]) -> str:
    return r.get("sig_summary") or d.cut(r.get("sig_quote"), 60) or d.cut(r.get("judge_note"), 60)


def strip_money(text: str | None) -> str:
    """Remove money amounts from free text shown on the caller view (D-040: the associate never sees money)."""
    out = _MONEY_AMOUNT.sub("", text or "")
    return re.sub(r"[ \t]{2,}", " ", out).replace(" ,", ",").replace(" .", ".").strip()


def snapshot_values(r: dict[str, Any], target: Target) -> dict[str, Any]:
    """The editable values exactly as `pull.read_editable` reads an untouched row (13.6.2)."""
    vals: dict[str, Any] = {
        "stage": r["stage"],
        "notes": (r.get("notes") or "").strip(),
        **{k: (dd.isoformat() if (dd := d.as_date(r.get(k))) else "") for k in d.DATE_FIELDS},
    }
    if target.money:
        vals["deal_value_inr"] = d.money_str(r.get("deal_value_inr"))
    return vals


def reasons_of(r: dict[str, Any]) -> dict[str, Any]:
    reasons = r.get("reasons")
    return reasons if isinstance(reasons, dict) else {}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
            elif isinstance(v, dict) and v.get("type"):
                out.append(f"{str(v['type']).replace('_', ' ')} signal ({v.get('value', '')})".replace(" ()", ""))
        return out
    return []


def ticket_estimate(r: dict[str, Any]) -> str:
    """The grey estimate for an empty Deal value (13.8.3), from scores.reasons.ticket_estimate."""
    est = reasons_of(r).get("ticket_estimate")
    if isinstance(est, str):
        return est if (" to " in est or est.startswith("≈")) else ("≈ " + est if est else "")
    if isinstance(est, dict):
        return d.estimate_text(est.get("min"), est.get("max"))
    return ""


def score_note(r: dict[str, Any], money: bool) -> str:
    """Judge note plus the main scoring reasons (fit and intent; can-pay goes in its own master-only column)."""
    reasons = reasons_of(r)
    lines = [r["judge_note"].strip()] if r.get("judge_note") else []
    parts = _strings(reasons.get("fit"))[:2] + _strings(reasons.get("intent"))[:2] + _strings(reasons.get("reach"))[:1]
    legacy = reasons.get("win_parts") if isinstance(reasons.get("win_parts"), dict) else None
    if legacy:
        parts.append("Old engine score: " + ", ".join(f"{k} {v}" for k, v in legacy.items() if not isinstance(v, list)))
    if parts:
        lines.append("Score " + str(int(float(r.get("score_total") or 0))) + ": " + "; ".join(parts) + ".")
    text = "\n".join(lines)
    return text if money else strip_money(text)


def can_pay_note(r: dict[str, Any]) -> str:
    reasons = reasons_of(r)
    parts = _strings(reasons.get("can_pay"))
    est = ticket_estimate(r)
    basis = reasons.get("ticket_basis")
    if est:
        parts.insert(0, f"Ticket estimate {est}" + (f": {basis}" if isinstance(basis, str) and basis else ""))
    return "\n".join(parts)


def watch_outs(r: dict[str, Any]) -> str:
    reasons = reasons_of(r)
    return ", ".join(_strings(reasons.get("risks")) or _strings(reasons.get("watch_outs")))


# ---------------------------------------------------------------------------
# Today sizing: the Python twin decides how many rows the Today list needs (13.6.4)
# ---------------------------------------------------------------------------
def tasks_due_today(rows: Sequence[dict[str, Any]], ctx: Context) -> int:
    n, queue = 0, 0
    for r in rows:
        qpos = None
        if r["stage"] == "new" and not d.as_date(r.get("wa_at")):
            queue += 1
            qpos = queue
        _, due = d.next_step_and_due(
            r["stage"], dates_of(r), ctx.today, qpos, ctx.send_per_day, first_touch(r), step2(r)
        )
        n += bool(due and due <= ctx.today)
    return n


def next_steps(rows: Sequence[dict[str, Any]], ctx: Context) -> dict[str, tuple[str, dt.date | None]]:
    """{lead_id: (next_step, due_at)} for the rows in sheet order: what the formulas show, for the app."""
    out, queue = {}, 0
    for r in rows:
        qpos = None
        if r["stage"] == "new" and not d.as_date(r.get("wa_at")):
            queue += 1
            qpos = queue
        out[r["lead_id"]] = d.next_step_and_due(
            r["stage"], dates_of(r), ctx.today, qpos, ctx.send_per_day, first_touch(r), step2(r)
        )
    return out


# ---------------------------------------------------------------------------
# Pipeline tab
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PipelineLayout:
    headers: list[str]
    index: dict[str, int]
    letters: dict[str, str]
    first: int  # first data row, 0-based
    last: int  # one past the last data row, 0-based
    tab: str


def build_pipeline(
    rows: Sequence[dict[str, Any]], target: Target, sid: int, ctx: Context
) -> tuple[list[dict[str, Any]], PipelineLayout, list[list[d.Cell]]]:
    cols = pipeline_columns(target.money)
    idx = {c.key: i for i, c in enumerate(cols)}
    letters = {k: d.col(i) for k, i in idx.items()}
    n = len(rows)
    first, last = 2, 2 + n
    ncols = len(cols)
    founder, associate = ("You", ctx.associate_name) if target.money else ("Founder", "You")

    group_row: list[d.Cell] = []
    for i, c in enumerate(cols):
        b: dict[str, Any] = {} if c.hidden else {"bottom": d.side(d.IND300, "SOLID_MEDIUM")}
        if c.group and i:
            b["left"] = d.side("E6E6E6")
        group_row.append(
            d.txt(c.group.upper() if c.group else "", d.f(color=d.SUB, size=8, font=d.MONO, bg=d.HEAD_BG, borders=b))
        )
    head_row = [
        d.txt(
            c.header,
            d.f(
                True,
                color=d.INK,
                size=10,
                bg=d.HEAD_BG,
                h="CENTER" if c.key == "grade" else "LEFT",
                borders={"bottom": d.side(d.IND200)},
            ),
            note=d.NOTES.get(c.header),
        )
        for c in cols
    ]

    date_fmt = d.f(color=d.TX2, size=9, nf='"✓ "d mmm', nf_type="DATE", borders=d.HAIRLINE)
    data: list[list[d.Cell]] = []
    for i, r in enumerate(rows):
        row_no = first + i + 1  # 1-based sheet row
        label, url, parts = reach(r)
        stage = r["stage"]
        bg, fg = d.stage_style(stage)
        fx = d.pipeline_formulas(
            letters, row_no, first + 1, ctx.send_per_day, first_touch(r), step2(r), founder, associate
        )
        chance = round(float(r.get("score_total") or 0))
        grade = r.get("grade") or "D"
        gi, gb = d.GRADE_STYLE.get(grade, d.GRADE_STYLE["D"])
        name, _role = person(r)
        why = why_short(r) if target.money else strip_money(why_short(r))
        cells: dict[str, d.Cell] = {
            "grade": d.txt(grade, d.f(True, color=gi, h="CENTER", bg=gb, borders=d.INSET)),
            "company": d.txt(d.short_name(r.get("name")), d.f(True, color=d.INK, borders=d.HAIRLINE)),
            "person": d.txt(d.person_short(name), d.f(color=d.SUB, borders=d.HAIRLINE)),
            "phone": d.rich(parts, d.f(color=d.INK, borders=d.HAIRLINE)),
            "why": d.txt(why, d.f(color=d.TX2, borders=d.HAIRLINE)),
            "stage": d.txt(d.stage_label(stage), d.f(True, color=fg, size=9, bg=bg, borders=d.INSET)),
            "meeting": d.num(
                d.serial(r.get("meeting_at")), d.f(color=d.TX2, size=9, nf="d mmm", nf_type="DATE", borders=d.HAIRLINE)
            ),
            "next": d.formula(fx["next"], d.f(True, color=d.INK, borders=d.HAIRLINE)),
            "due": d.formula(fx["due"], d.f(color=d.SUB, borders=d.INSET)),
            # lower half blocks read as a 5px bar on a light track (tested against the PDF export, 16 Oct 2026)
            "bar": d.rich(
                [
                    ("▄" * round(chance / 10), d.BAR_ON, False, None, None),
                    ("▄" * (10 - round(chance / 10)), d.BAR_OFF, False, None, None),
                    (f"   {chance}", d.SUB, False, None, 9),
                ],
                d.f(size=8, borders=d.HAIRLINE),
            ),
            "notes": d.txt(r.get("notes") or "", d.f(color=d.SUB, borders=d.HAIRLINE)),
            "chance": d.num(chance, d.f(color=d.SUB, size=9, h="RIGHT", borders=d.HAIRLINE)),
            "dd": d.formula(fx["dd"], d.f(color=d.FAINT, size=8, nf="yyyy-mm-dd", nf_type="DATE")),
            "queue": d.formula(fx["queue"], d.f(color=d.FAINT, size=8)),
            "who": d.formula(fx["who"], d.f(color=d.FAINT, size=8)),
            "wa_url": d.txt(url, d.f(color=d.FAINT, size=8)),
            "label": d.txt(label, d.f(color=d.FAINT, size=8)),
            "group": d.txt(r.get("test_group") or "", d.f(color=d.FAINT, size=8)),
            "id": d.txt(r["lead_id"], d.f(color=d.FAINT, size=8)),
        }
        for key, fld in (("wa", "wa_at"), ("call", "call_at"), ("d3", "d3_at"), ("d7", "d7_at")):
            cells[key] = d.num(d.serial(r.get(fld)), date_fmt)
        if target.money:
            dv = r.get("deal_value_inr")
            if dv is not None:
                cells["deal"] = d.num(float(dv), d.f(color=d.TX2, nf='"₹"#,##0', borders=d.HAIRLINE))
            else:
                cells["deal"] = d.txt(ticket_estimate(r), d.f(color=d.FAINT, borders=d.HAIRLINE))
        data.append([cells[c.key] for c in cols])

    hidden = [idx[c.key] for c in cols if c.hidden]
    reqs = d.grid(
        sid,
        ncols,
        max(last + 40, 80),
        [c.width for c in cols],
        frozen_rows=2,
        frozen_cols=3,
        hidden=hidden,
        tab=d.INDIGO,
    )
    reqs += d.row_heights(sid, [(0, 1, 26), (1, 2, 36), (first, last, 40)])
    reqs.append(d.put(sid, 0, 0, [group_row, head_row, *data]))
    if n:
        reqs += _pipeline_rules(sid, idx, letters, first, last, ncols, target.money)
    layout = PipelineLayout([c.header for c in cols], idx, letters, first, last, target.tab("Pipeline"))
    return reqs, layout, [group_row, head_row, *data]


def _pipeline_rules(
    sid: int, idx: dict[str, int], letters: dict[str, str], first: int, last: int, ncols: int, money: bool
) -> list[dict[str, Any]]:
    def span(c0: int, c1: int) -> tuple[int, int, int, int]:
        return first, last, c0, c1

    reqs: list[dict[str, Any]] = []
    sc, top = idx["stage"], first + 1
    stage_ref = f"${letters['stage']}{top}"
    for value, (label, bg, fg) in d.STAGES.items():
        del value
        reqs.append(d.rule(sid, *span(sc, sc + 1), f'={stage_ref}="{label}"', color=fg, bg=bg, bold=True))
    due_ref = f"${letters['due']}{top}"
    reqs.append(
        d.rule(
            sid,
            *span(idx["due"], idx["due"] + 1),
            f'=LEFT({due_ref},7)="Overdue"',
            color=d.RED_TX,
            bg=d.RED_BG,
            bold=True,
        )
    )
    reqs.append(
        d.rule(
            sid, *span(idx["due"], idx["due"] + 1), f'={due_ref}="Today"', color=d.AMBER_TX, bg=d.AMBER_BG, bold=True
        )
    )
    booked = d.stage_label("discovery_booked")
    reqs.append(
        d.rule(
            sid,
            *span(idx["meeting"], idx["meeting"] + 1),
            f'=AND({stage_ref}="{booked}",ISNUMBER(${letters["meeting"]}{top}))',
            color="9D2055",
            bold=True,
        )
    )
    won = "=OR(" + ",".join(f'{stage_ref}="{d.stage_label(s)}"' for s in d.WON) + ")"
    reqs.append(d.rule(sid, *span(idx["company"], idx["company"] + 1), won, color=d.WON_TX, bold=True))
    if money:
        reqs.append(d.rule(sid, *span(idx["deal"], idx["deal"] + 1), won, color=d.WON_TX, bold=True))
    faded = "=OR(" + ",".join(f'{stage_ref}="{d.stage_label(s)}"' for s in ("lost", "not_a_fit", "wrong_contact")) + ")"
    vis_end = idx["notes"] + 1
    for c0, c1 in ((0, sc), (sc + 1, vis_end)):
        reqs.append(d.rule(sid, *span(c0, c1), faded, color=d.MUTED, bold=False))
    reqs.append(
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": first,
                    "endRowIndex": last,
                    "startColumnIndex": sc,
                    "endColumnIndex": sc + 1,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": lab} for lab, _, _ in d.STAGES.values()],
                    },
                    "showCustomUi": True,
                    "strict": False,  # a typed unknown stage is kept and logged, never refused (13.2.1)
                },
            }
        }
    )
    reqs.append(
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": first,
                    "endRowIndex": last,
                    "startColumnIndex": idx["wa"],
                    "endColumnIndex": idx["meeting"] + 1,
                },
                "rule": {"condition": {"type": "DATE_IS_VALID"}, "showCustomUi": True, "strict": False},
            }
        }
    )
    reqs.append(
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": 1,
                        "endRowIndex": last,
                        "startColumnIndex": 0,
                        "endColumnIndex": ncols,
                    }
                }
            }
        }
    )
    editable = [idx[k] for k in ("stage", "wa", "call", "d3", "d7", "meeting", "notes")] + (
        [idx["deal"]] if money else []
    )
    start = 0
    for c in [*sorted(editable), ncols]:
        if c > start:
            reqs.append(d.protect(sid, 0, last, start, c))
        start = c + 1
    return reqs


# ---------------------------------------------------------------------------
# Today tab
# ---------------------------------------------------------------------------
def build_today(
    layout: PipelineLayout, target: Target, sid: int, pipe_sid: int, ctx: Context, cap: int, n_leads: int
) -> tuple[list[dict[str, Any]], list[list[d.Cell]]]:
    """KPI tiles, the To do list (one spill formula, sized to today's tasks) and the pipeline by stage."""
    L, first = layout.letters, layout.first
    ref = d.tab_ref(layout.tab)

    def pr(key: str) -> str:
        return f"{ref}!${L[key]}${first + 1}:${L[key]}"

    # A box · B Company · C Person · D Phone · E WhatsApp · F Next step · G Who · H Due · I Why now · J Stage
    widths = [24, 196, 166, 124, 100, 176, 112, 112, 262, 140]
    W = len(widths)
    r_title, r_tile, r_sec, r_head = 1, 3, 9, 10
    r_list = r_head + 1
    r_more = r_list + cap
    r_fsec = r_more + 2
    r_funnel = r_fsec + 1
    nf = len(d.FUNNEL)
    nrows = r_funnel + nf + 3
    all_cells: list[list[d.Cell]] = []

    reqs = d.grid(sid, W, nrows, widths, tab=d.WA_GREEN)
    reqs += d.row_heights(
        sid,
        [
            (0, 1, 18), (1, 2, 54), (2, 3, 10), (3, 4, 28), (4, 5, 36), (5, 6, 20), (6, 7, 6), (7, 8, 14), (8, 9, 22),
            (r_sec, r_sec + 1, 30), (r_head, r_head + 1, 34), (r_list, r_more, 40), (r_more, r_more + 1, 26),
            (r_more + 1, r_fsec, 18), (r_fsec, r_fsec + 1, 30), (r_funnel, r_funnel + nf, 30), (r_funnel + nf, nrows, 18),
        ],
    )  # fmt: skip

    def blank() -> d.Cell:
        return d.fmt_only(d.f(bg="FFFFFF"))

    def add(r: int, c: int, rows: list[list[d.Cell]]) -> None:
        reqs.append(d.put(sid, r, c, rows))
        all_cells.extend(rows)

    # Title row: a live date has to be a formula, and a formula cell takes one colour.
    week = '="WEEK OF "&UPPER(TEXT(TODAY()-WEEKDAY(TODAY(),3),"d mmm"))'
    title = [
        blank(),
        d.formula(
            '="Today  ·  "&TEXT(TODAY(),"ddd d mmm")', d.f(color=d.INK, size=22, font=d.DISPLAY, wrap="OVERFLOW_CELL")
        ),
        *[d.fmt_only(d.f()) for _ in range(W - 3)],
        d.formula(week, d.f(color=d.SUB, size=8, font=d.MONO, h="RIGHT")),
    ]
    add(r_title, 0, [title])

    # KPI tiles, 5 rows each: label, number, sub line, bar, padding.
    S = pr("stage")

    def cnt(*stages: str) -> str:
        return "+".join(f'COUNTIF({S},"{d.stage_label(s)}")' for s in stages)

    won = d.WON
    deal_sum = ("+".join(f'SUMIFS({pr("deal")},{S},"{d.stage_label(s)}")' for s in won)) if target.money else ""

    def nref(c0: int) -> str:
        return f"{d.col(c0)}{r_tile + 2}"

    od = nref(9)
    target_n = ctx.weekly_contact_target
    new_l, fit_l = d.stage_label("new"), d.stage_label("not_a_fit")
    # contacted = a WA date this week, plus leads moved past New with no WA date typed yet (counted as this week)
    undated = f'SUMPRODUCT(({S}<>"")*({S}<>"{new_l}")*({S}<>"{fit_l}")*({pr("wa")}=""))'
    tiles: list[tuple[tuple[int, int], str, str, str, str, str]] = [
        ((1, 3), "Contacted this week", f'=COUNTIFS({pr("wa")},">="&(TODAY()-WEEKDAY(TODAY(),3)))+{undated}', f"of {target_n}", "F4F7FF", "212191"),
        ((3, 5), "Conversations", "=" + cnt("talking", "discovery_booked", "discovery_done", "proposal_sent", *won), "", "F4F7FF", "212191"),
        ((5, 6), "Discovery calls", "=" + cnt("discovery_booked", "discovery_done", "proposal_sent", *won), "", "F4F7FF", "212191"),
        ((6, 8), "Proposals sent", "=" + cnt("proposal_sent", *won), "", "F4F7FF", "212191"),
        ((8, 9), "Won", "=" + cnt(*won), f'=IF({deal_sum}=0,"","₹"&TEXT(({deal_sum})/100000,"0.0")&"L")' if target.money else "", "E3F1D8", "385418"),
        ((9, 10), "Overdue", f'=COUNTIF({pr("dd")},"<"&TODAY())', f'=IF({od}>0,"do these first","all clear")', "F4F7FF", "212191"),
    ]  # fmt: skip
    thick = d.side("FFFFFF", "SOLID_THICK")
    for (c0, c1), label, numf, sub, bg, fg in tiles:
        span = c1 - c0

        def pad(bg: str = bg, span: int = span) -> list[d.Cell]:
            return [d.fmt_only(d.f(bg=bg)) for _ in range(span - 1)]

        sub_cell = (
            d.formula(sub, d.f(color=d.SUB, size=9, bg=bg))
            if sub.startswith("=")
            else d.txt(sub, d.f(color=d.SUB, size=9, bg=bg))
        )
        if c0 == 1:  # contacted: progress bar towards the weekly target, half the tile wide
            n_cell = nref(1)
            bar = [
                d.formula(
                    f'=SPARKLINE({{{n_cell},MAX(0,{target_n}-{n_cell})}},{{"charttype","bar";"color1","#556adc";"color2","#d2dff9"}})',
                    d.f(bg=bg),
                ),
                *pad(),
            ]
        else:
            bar = [d.fmt_only(d.f(bg=bg)), *pad()]
        tile_rows = [
            [d.txt(label, d.f(color=d.SUB, size=9, bg=bg)), *pad()],
            [d.formula(numf, d.f(color=fg, size=24, font=d.DISPLAY, bg=bg)), *pad()],
            [sub_cell, *pad()],
            bar,
            [d.fmt_only(d.f(bg=bg)), *pad()],
        ]
        add(r_tile, c0, tile_rows)
        if span > 1:
            for rr in range(r_tile, r_tile + 5):
                if not (c0 == 1 and rr == r_tile + 3):
                    reqs.append(d.merge(sid, rr, rr + 1, c0, c1))
        reqs.append(d.borders(sid, r_tile, r_tile + 5, c0, c1, top=thick, bottom=thick, left=thick, right=thick))
    # the Overdue tile turns red only when something is overdue
    reqs.append(d.rule(sid, r_tile, r_tile + 5, 9, 10, f"=${d.col(9)}${r_tile + 2}>0", bg=d.RED_BG))
    reqs.append(d.rule(sid, r_tile + 1, r_tile + 2, 9, 10, f"=${d.col(9)}${r_tile + 2}>0", color=d.RED_TX, bg=d.RED_BG))

    # To do today: one spill formula, overdue first, capped at `cap` rows
    dd = pr("dd")
    ntask = f'IFERROR(COUNT(FILTER({dd},{dd}<>"",{dd}<=TODAY())),0)'
    rule_b = {"bottom": d.side(d.IND300, "SOLID_MEDIUM")}
    sec = [
        blank(),
        d.rich(
            [
                ("TO DO TODAY", d.SUB, False, None, 8, d.MONO),
                ("     overdue first  ·  tap a phone to open WhatsApp", d.FAINT, False, None, 9, d.FONT),
            ],
            d.f(size=8, wrap="OVERFLOW_CELL", borders=rule_b),
        ),
        *[d.fmt_only(d.f(borders=rule_b)) for _ in range(W - 3)],
        d.formula(f'=LET(n,{ntask},n&IF(n=1," task"," tasks"))', d.f(color=d.FAINT, size=9, h="RIGHT", borders=rule_b)),
    ]
    add(r_sec, 0, [sec])
    heads = ["", "Company", "Person", "Phone · WhatsApp", "", "Next step", "Who", "Due", "Why now", "Stage"]
    head_b = {"bottom": d.side(d.IND200)}
    hrow = [blank()]
    for i, h in enumerate(heads[1:], start=1):
        fm = d.f(True, color=d.INK, bg=d.HEAD_BG, borders=head_b, wrap="OVERFLOW_CELL" if i == 3 else "CLIP")
        hrow.append(d.txt(h, fm) if h else d.fmt_only(fm))
    add(r_head, 0, [hrow])
    arr = (
        f"{{{pr('company')},{pr('person')},{pr('label')},{pr('next')},{pr('who')},{pr('due')},{pr('why')},{pr('stage')},"
        f"{pr('wa_url')},{dd},{pr('chance')}}}"
    )
    todo = (
        f'=IFERROR(ARRAY_CONSTRAIN(LET(d,SORT(FILTER({arr},{dd}<>"",{dd}<=TODAY()),10,TRUE,11,FALSE),u,CHOOSECOLS(d,9),'
        f'HSTACK(CHOOSECOLS(d,1,2),ARRAYFORMULA(IF(u="",CHOOSECOLS(d,3),HYPERLINK(u,CHOOSECOLS(d,3)))),'
        f'ARRAYFORMULA(IF(ISNUMBER(SEARCH("phone=",u)),HYPERLINK(u,"WhatsApp ↗"),"")),'
        f'CHOOSECOLS(d,4,5,6,7,8))),{cap},9),"{d.EMPTY_TODO}")'
    )
    b0, b1 = f"B{r_list + 1}", f"B{r_more}"
    box = f'=ARRAYFORMULA(IF(({b0}:{b1}="")+({b0}:{b1}="{d.EMPTY_TODO}"),"","☐"))'
    wa_fmt = d.f(True, color=d.WA_GREEN, size=9, borders=d.HAIRLINE)
    wa_fmt["padding"]["left"] = 0  # sits right after the number, as one "phone · WhatsApp" cell
    fmts = [
        d.f(color="CCCCCC", h="CENTER", borders=d.HAIRLINE), d.f(True, color=d.INK, borders=d.HAIRLINE),
        d.f(color=d.SUB, borders=d.HAIRLINE), d.f(color=d.INK, borders=d.HAIRLINE), wa_fmt,
        d.f(True, color=d.INK, borders=d.HAIRLINE), d.f(color=d.SUB, borders=d.HAIRLINE),
        d.f(color=d.SUB, borders=d.INSET), d.f(color=d.SUB, borders=d.HAIRLINE), d.f(True, size=9, borders=d.INSET),
    ]  # fmt: skip
    list_rows = []
    for i in range(cap):
        row = [d.fmt_only(fm) for fm in fmts]
        if i == 0:
            row[0], row[1] = d.formula(box, fmts[0]), d.formula(todo, fmts[1])
        list_rows.append(row)
    add(r_list, 0, list_rows)
    more = f'=LET(n,{ntask},IF(n>{cap},HYPERLINK("#gid={pipe_sid}","+ "&(n-{cap})&" more due today  ·  open Pipeline ↗"),""))'
    add(r_more, 1, [[d.formula(more, d.f(color=d.LINK, size=9, wrap="OVERFLOW_CELL"))]])
    lr = (r_list, r_more)
    reqs.append(d.rule(sid, *lr, 3, 4, f'=RIGHT($D{r_list + 1},1)="↗"', color=d.LINK))
    reqs.append(d.rule(sid, *lr, 7, 8, f'=LEFT($H{r_list + 1},7)="Overdue"', color=d.RED_TX, bg=d.RED_BG, bold=True))
    reqs.append(d.rule(sid, *lr, 7, 8, f'=$H{r_list + 1}="Today"', color=d.AMBER_TX, bg=d.AMBER_BG, bold=True))
    for label, bg, fg in d.STAGES.values():
        reqs.append(d.rule(sid, *lr, 9, 10, f'=$J{r_list + 1}="{label}"', color=fg, bg=bg, bold=True))

    # Pipeline by stage: text bars (a sparkline fills the whole row and reads as a block)
    fsec = [
        blank(),
        d.rich(
            [
                ("PIPELINE BY STAGE", d.SUB, False, None, 8, d.MONO),
                (f"     all {n_leads} leads", d.FAINT, False, None, 9, d.FONT),
            ],
            d.f(size=8, wrap="OVERFLOW_CELL", borders=rule_b),
        ),
        *[d.fmt_only(d.f(borders=rule_b)) for _ in range(W - 2)],
    ]
    add(r_fsec, 0, [fsec])
    top = f"MAX(1,MAX(C{r_funnel + 1}:C{r_funnel + nf}))"
    frows = []
    for i, stage in enumerate(d.FUNNEL):
        label, bg, fg = d.STAGES[stage]
        rr = r_funnel + i + 1
        frows.append(
            [
                blank(),
                d.txt(label, d.f(True, color=fg, size=9, bg=bg, borders=d.INSET)),
                d.formula(f'=COUNTIF({S},"{label}")', d.f(True, color=d.INK, h="RIGHT", borders=d.HAIRLINE)),
                d.formula(
                    f'=IF(C{rr}=0,"",REPT("▆",MAX(1,ROUND(C{rr}/{top}*40))))',
                    d.f(color=d.blend(fg), size=10, borders=d.HAIRLINE),
                ),
                *[d.fmt_only(d.f(borders=d.HAIRLINE)) for _ in range(W - 4)],
            ]
        )
    add(r_funnel, 0, frows)
    for i in range(nf):
        reqs.append(d.merge(sid, r_funnel + i, r_funnel + i + 1, 3, 6))
    reqs.append(d.protect(sid, 0, nrows, 0, W, "Live summary, built from the Pipeline tab"))
    return reqs, all_cells


# ---------------------------------------------------------------------------
# Lead details tab
# ---------------------------------------------------------------------------
def build_details(
    rows: Sequence[dict[str, Any]], target: Target, sid: int
) -> tuple[list[dict[str, Any]], list[str], list[list[d.Cell]]]:
    cols = details_columns(target.money)
    money = target.money

    def wrap(color: str = d.TX2, size: int = 9) -> dict[str, Any]:
        return d.f(color=color, size=size, wrap="WRAP", borders=d.HAIRLINE)

    def clean(text: str | None) -> str:
        return (text or "") if money else strip_money(text)

    head = [
        d.txt(
            h,
            d.f(
                True,
                color=d.INK,
                bg=d.HEAD_BG,
                h="CENTER" if h == "Grade" else "LEFT",
                borders={"bottom": d.side(d.IND200)},
            ),
        )
        for h, _ in cols
    ]
    out_rows: list[list[d.Cell]] = []
    heights: list[float] = []
    for r in rows:
        grade = r.get("grade") or "D"
        gi, gb = d.GRADE_STYLE.get(grade, d.GRADE_STYLE["D"])
        name, role = person(r)
        sig_text = r.get("sig_summary") or d.cut(r.get("sig_quote"), 220) or ""
        why_lines = [clean(sig_text or r.get("judge_note") or "")]
        sig_day = d.as_date(r.get("sig_at"))
        if sig_text and sig_day:
            why_lines.append(f"Signal date: {sig_day.day} {sig_day:%b %Y}")
        why_text = "\n".join(x for x in why_lines if x)
        why_parts: list[d.RichPart] = [(why_text, d.TX2, False, None, None)]
        if r.get("sig_url") and sig_text:
            why_parts.append(("\nProof ↗", d.LINK, False, r["sig_url"], None))
        message = clean((r.get("message") or "").strip())
        link = wa_url(r)
        msg_parts: list[d.RichPart] = [(message or "No message yet", d.TX2 if message else d.FAINT, False, None, None)]
        if link and message:
            msg_parts.append(("\nOpen in WhatsApp ↗", d.WA_GREEN, True, link, None))
        email = r.get("email") or ""
        checked = max(
            (x for x in (d.as_date(r.get("contact_verified_at")), d.as_date(r.get("researched_at"))) if x), default=None
        )
        note = score_note(r, money)
        row = [
            d.txt(grade, d.f(True, color=gi, h="CENTER", bg=gb, borders=d.INSET)),
            d.txt(d.short_name(r.get("name"), 40), d.f(True, color=d.INK, wrap="WRAP", borders=d.HAIRLINE)),
            d.txt(d.person_role(name, role), wrap(d.SUB)),
            d.rich(why_parts, wrap()),
            d.rich(msg_parts, wrap()),
            d.txt(clean(r.get("message_alt")), wrap()),
            d.txt(clean(r.get("followup_d3")), wrap()),
            d.txt(clean(r.get("followup_d7")), wrap()),
            d.txt(note, wrap(d.SUB)),
            d.links_cell(
                [
                    ("Proof", r.get("sig_url")),
                    ("Website", r.get("website")),
                    ("Phone source", r.get("phone_source_url")),
                ],
                wrap(d.LINK),
            ),
            d.links_cell([(email, f"mailto:{email}")] if email else [], wrap(d.LINK)),
            d.txt(watch_outs(r), wrap(d.SUB)),
            d.txt(checked.strftime("%d %b %Y") if checked else "", d.f(color=d.SUB, size=9, borders=d.HAIRLINE)),
        ]
        texts = [
            "",
            d.short_name(r.get("name"), 40),
            d.person_role(name, role),
            why_text + ("\nProof ↗" if r.get("sig_url") else ""),
            (message or "No message yet") + ("\nOpen in WhatsApp ↗" if link and message else ""),
            clean(r.get("message_alt")),
            clean(r.get("followup_d3")),
            clean(r.get("followup_d7")),
            note,
            "",
            "",
            watch_outs(r),
            "",
        ]
        if money:
            pay = can_pay_note(r)
            row.append(d.txt(pay, wrap(d.SUB)))
            texts.append(pay)
        row.append(d.txt(r["lead_id"], d.f(color=d.FAINT, size=8)))
        out_rows.append(row)
        # tall enough for the longest cell, so the message and its WhatsApp link are never cut off
        heights.append(max(64.0, *(d.text_height(t, w) for t, (_, w) in zip(texts, cols, strict=False) if t)))
    n = len(out_rows)
    reqs = d.grid(
        sid, len(cols), n + 30, [w for _, w in cols], frozen_rows=1, frozen_cols=2, hidden=(len(cols) - 1,), tab=d.PLUM
    )
    reqs += d.row_heights(sid, [(0, 1, 36)] + [(i + 1, i + 2, round(h)) for i, h in enumerate(heights)])
    reqs.append(d.put(sid, 0, 0, [head, *out_rows]))
    if n:
        reqs.append(
            {
                "setBasicFilter": {
                    "filter": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 0,
                            "endRowIndex": n + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(cols),
                        }
                    }
                }
            }
        )
        reqs.append(d.protect(sid, 0, n + 1, 0, len(cols)))
    return reqs, [h for h, _ in cols], [head, *out_rows]


# ---------------------------------------------------------------------------
# Tabs: structure and reset, from the metadata read before anything is written
# ---------------------------------------------------------------------------
def plan_tabs(
    meta: dict[str, Any], target: Target, position: int
) -> tuple[dict[str, int], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Tab ids for this view, the requests that create or rename tabs, and the existing tabs to reset.

    New tabs get fixed ids (101.. for the first view, 201.. for the second) so every request can be built
    before the batch runs. Tabs that belong to nobody are left alone, except an empty default 'Sheet1' in a
    spreadsheet this engine is setting up for the first time.
    """
    sheets = {s["properties"]["title"]: s for s in meta.get("sheets", [])}
    used_ids = {s["properties"]["sheetId"] for s in meta.get("sheets", [])}
    ids: dict[str, int] = {}
    structure: list[dict[str, Any]] = []
    existing: dict[str, dict[str, Any]] = {}
    for i, base in enumerate(gs.TABS):
        title = target.tab(base)
        index = position * len(gs.TABS) + i
        if title in sheets:
            sheet = sheets[title]
        else:
            old = next(
                (sheets[o] for o, new in gs.OLD_TAB_NAMES.items() if new == base and target.tab(o) in sheets), None
            )
            sheet = old
            if old is not None:
                structure.append(
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": old["properties"]["sheetId"], "title": title},
                            "fields": "title",
                        }
                    }
                )
        if sheet is not None:
            sid = int(sheet["properties"]["sheetId"])
            existing[base] = sheet
            structure.append(
                {"updateSheetProperties": {"properties": {"sheetId": sid, "index": index}, "fields": "index"}}
            )
        else:
            sid = NEW_TAB_IDS[base] + 100 * position
            while sid in used_ids:
                sid += 1000
            used_ids.add(sid)
            structure.append(
                {
                    "addSheet": {
                        "properties": {
                            "sheetId": sid,
                            "title": title,
                            "index": index,
                            "gridProperties": {"rowCount": 100, "columnCount": 26},
                        }
                    }
                }
            )
        ids[base] = sid
    return ids, structure, existing


def reset_requests(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Remove everything a previous version added: tables, slicers, banding, filters, rules, protections, merges, cells."""
    sid = sheet["properties"]["sheetId"]
    reqs: list[dict[str, Any]] = [{"deleteTable": {"tableId": t["tableId"]}} for t in sheet.get("tables", [])]
    reqs += [{"deleteEmbeddedObject": {"objectId": s["slicerId"]}} for s in sheet.get("slicers", [])]
    reqs += [{"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}} for b in sheet.get("bandedRanges", [])]
    reqs += [{"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}} for _ in sheet.get("conditionalFormats", [])]
    reqs += [
        {"deleteProtectedRange": {"protectedRangeId": p["protectedRangeId"]}} for p in sheet.get("protectedRanges", [])
    ]
    reqs += [{"deleteFilterView": {"filterId": fv["filterViewId"]}} for fv in sheet.get("filterViews", [])]
    if sheet.get("basicFilter"):
        reqs.append({"clearBasicFilter": {"sheetId": sid}})
    reqs += [
        {"unmergeCells": {"range": {"sheetId": sid}}},
        {"updateCells": {"range": {"sheetId": sid}, "fields": "*"}},
        {"setDataValidation": {"range": {"sheetId": sid}}},
    ]
    return reqs


# ---------------------------------------------------------------------------
# Validation (13.6.1 step 4, 13.6.6)
# ---------------------------------------------------------------------------
def _cell_strings(cell: d.Cell) -> list[str]:
    value = cell.get("userEnteredValue") or {}
    return [str(value.get("stringValue", "")), str(value.get("formulaValue", ""))]


def assert_no_money(target: Target, headers: Sequence[str], rows: Sequence[Sequence[d.Cell]]) -> None:
    """The caller view never shows money: no money header, no ₹ in any cell or formula. Raises before writing."""
    if target.money:
        return
    bad = [h for h in headers if MONEY_PATTERN.search(h) and h != "Win chance"]
    if bad:
        raise AssertionError(f"money columns on the caller sheet: {bad}")
    for row in rows:
        for cell in row:
            if any("₹" in s for s in _cell_strings(cell)):
                raise AssertionError("a ₹ amount reached the caller sheet")


def validate(built: Built, rows: Sequence[dict[str, Any]]) -> None:
    assert_no_money(built.target, built.headers, built.cells)
    if any(not r.get("lead_id") for r in rows):
        raise AssertionError("a sheet row has no lead id")
    if len(built.snapshot) != len(rows):
        raise AssertionError(f"snapshot has {len(built.snapshot)} rows for {len(rows)} leads (duplicate lead ids?)")
    size = len(json.dumps(built.requests, ensure_ascii=False).encode())
    if size > MAX_PAYLOAD_BYTES:
        raise AssertionError(f"batchUpdate payload {size:,} bytes is over the {MAX_PAYLOAD_BYTES:,} byte limit")
    built.stats["payload_bytes"] = size


# ---------------------------------------------------------------------------
# Building a view
# ---------------------------------------------------------------------------
def build_view(
    rows: Sequence[dict[str, Any]],
    target: Target,
    meta: dict[str, Any],
    position: int,
    ctx: Context,
    *,
    full: bool = True,
    adopting: bool = False,
) -> Built:
    """Every request for one view, in the order one atomic batchUpdate applies them."""
    tab_ids, structure, existing = plan_tabs(meta, target, position)
    reqs: list[dict[str, Any]] = list(structure)
    if adopting:  # a spreadsheet set up for the first time: drop the empty default tab
        ours = {t for p in range(2) for t in (target.tab(b) for b in gs.TABS)} | set(gs.TABS)
        for s in meta.get("sheets", []):
            title = s["properties"]["title"]
            if title in ("Sheet1", "Sheet 1") and title not in ours:
                reqs.append({"deleteSheet": {"sheetId": s["properties"]["sheetId"]}})
    for base in gs.TABS if full else ("Today", "Pipeline"):
        if base in existing:
            reqs += reset_requests(existing[base])
    pipe_reqs, layout, pipe_cells = build_pipeline(rows, target, tab_ids["Pipeline"], ctx)
    cap = min(ctx.today_rows_max, max(1, tasks_due_today(rows, ctx)))
    today_reqs, today_cells = build_today(layout, target, tab_ids["Today"], tab_ids["Pipeline"], ctx, cap, len(rows))
    reqs += pipe_reqs + today_reqs
    headers = list(layout.headers)
    cells = pipe_cells + today_cells
    if full:
        det_reqs, det_headers, det_cells = build_details(rows, target, tab_ids["Lead details"])
        reqs += det_reqs
        headers += det_headers
        cells += det_cells
    snapshot = {r["lead_id"]: {**snapshot_values(r, target), st.ROW_KEY: i} for i, r in enumerate(rows)}
    built = Built(target, reqs, snapshot, headers, cells, full, tab_ids, {"rows": len(rows), "today_rows": cap})
    validate(built, rows)
    return built


# ---------------------------------------------------------------------------
# Row order from the sheet itself (people may sort it by hand; pull matches rows by the hidden ID)
# ---------------------------------------------------------------------------
def sheet_order(api: gs.SheetsApi, target: Target, legacy_ids: dict[str, str] | None = None) -> list[str]:
    """Lead ids in the order the Pipeline tab shows them. Old sheets carry old ids ('A-0051'); map them."""
    rows = api.values(target.spreadsheet_id, d.tab_ref(target.tab("Pipeline")))
    hrow = next((i for i, r in enumerate(rows[:6]) if "ID" in r and "Stage" in r), None)
    if hrow is None:
        return []
    id_col = rows[hrow].index("ID")
    out = []
    for r in rows[hrow + 1 :]:
        raw = str(r[id_col]).strip() if id_col < len(r) else ""
        lead_id = (legacy_ids or {}).get(raw, raw)
        if len(lead_id) == 36:
            out.append(lead_id)
    return out


def legacy_id_map(conn: Connection[Any] | None = None) -> dict[str, str]:
    """Old lead id ('A-0051') -> new lead uuid, through source_records('legacy') (Step 20.6)."""
    rows = db.fetch_all(
        "select r.source_key, l.id::text as lead_id from public.source_records r "
        "join public.leads l on l.business_id = r.business_id where r.source = 'legacy' order by l.created_at",
        conn=conn,
    )
    return {r["source_key"]: r["lead_id"] for r in rows}


# ---------------------------------------------------------------------------
# The push
# ---------------------------------------------------------------------------
class SheetNotAdopted(RuntimeError):
    """A live sheet that this engine has never written: it must be adopted first (Step 20.6)."""


def run(rc: RunContext, *, light: bool = False, resort: bool = False) -> dict[str, Any]:
    """`nlead sheet push`: take the lock, then push every view of this environment."""
    with st.sheet_lock(rc.opts.env) as got:
        if not got:
            log.warning("sheet.push.locked")
            return {"skipped": "another sheet sync is running"}
        return push(rc, light=light, resort=resort)


def push(
    rc: RunContext,
    *,
    light: bool = False,
    resort: bool = False,
    order: Sequence[str] | None = None,
    api: gs.SheetsApi | None = None,
) -> dict[str, Any]:
    """Push without taking the lock (the caller holds it). `order` comes from a pull that just read the sheet."""
    if db.get_setting("sheet_sync_enabled", True) is False:
        log.warning("sheet.push.disabled")
        return {"skipped": "sheet_sync_enabled is false"}
    api = api or gs.api()
    views = gs.targets()
    rows = load_rows()
    ctx = load_context()
    marks = st.states()

    metas = {t.key: api.metadata(t.spreadsheet_id) for t in views}
    for t in views:
        _check_adopted(t, marks.get(t.key, {}), metas[t.key])

    if order is None and not resort:
        order = _current_order(api, views[0], marks.get(views[0].key, {}))
    rows = order_rows(rows, order, resort=resort)

    stats: dict[str, Any] = {"rows": len(rows), "views": {}}
    built: list[Built] = []
    first_views: set[str] = set()  # the first view of each spreadsheet tidies its default tab
    for position, t in enumerate(views):
        mark = marks.get(t.key, {})
        snap, _ = st.load_snapshot(t.key)
        same_leads = set(snap) == {r["lead_id"] for r in rows}
        full = not (light and _adopted(t, mark) and mark.get("full_at") and same_leads and mark.get("state") == "ok")
        tidy = not _adopted(t, mark) and t.spreadsheet_id not in first_views
        first_views.add(t.spreadsheet_id)
        built.append(build_view(rows, t, metas[t.key], position, ctx, full=full, adopting=tidy))
    stats["today_rows"] = built[0].stats["today_rows"] if built else 0
    stats["tasks_due_today"] = tasks_due_today(rows, ctx)
    if rc.opts.dry_run:
        for b in built:
            stats["views"][b.target.key] = {**b.stats, "full": b.full, "requests": len(b.requests)}
        log.info("sheet.push.dry_run", **stats, first_rows=[(r["name"], r["grade"], r["stage"]) for r in rows[:5]])
        return stats

    for b in built:
        stats["views"][b.target.key] = _write(rc, api, b)
    stats["next_steps_updated"] = refresh_next_steps(rows, ctx)
    log.info("sheet.push.done", **stats)
    return stats


def _adopted(target: Target, mark: dict[str, Any]) -> bool:
    return mark.get("spreadsheet_id") == target.spreadsheet_id


def _check_adopted(target: Target, mark: dict[str, Any], meta: dict[str, Any]) -> None:
    """Refuse to overwrite a sheet this engine has never written if it already holds a Pipeline (Step 20.6).

    A brand-new spreadsheet (staging) has no Pipeline tab and is adopted by its first push. A live sheet that
    the old engine wrote must be adopted with `nlead sheet pull --seed-snapshots`, which records what it shows
    so the founder's latest edits are kept.
    """
    if _adopted(target, mark):
        return
    titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if target.tab("Pipeline") in titles or target.tab("Leads") in titles:
        raise SheetNotAdopted(
            f"the {target.key} sheet already has a Pipeline tab that this engine never wrote. "
            "Run `nlead sheet pull --seed-snapshots` first (Step 20.6), so its latest edits are kept."
        )


def _current_order(api: gs.SheetsApi, target: Target, mark: dict[str, Any]) -> list[str] | None:
    """The master view's current row order: from the sheet when it is in a good state, else the snapshot."""
    if _adopted(target, mark) and mark.get("state") == "ok":
        try:
            return sheet_order(api, target, legacy_id_map())
        except gs.SheetsApiError as exc:
            log.warning("sheet.order_unreadable", target=target.key, error=str(exc))
    snap, _ = st.load_snapshot(target.key)
    if snap:
        return [k for k, _ in sorted(snap.items(), key=lambda kv: kv[1].get(st.ROW_KEY, 1_000_000))]
    return None


def _write(rc: RunContext, api: gs.SheetsApi, b: Built) -> dict[str, Any]:
    t = b.target
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    with db.tx("engine", {"sheet": t.key}) as conn:
        previous = st.states(conn=conn).get(t.key, {})
        writing = {**previous, "state": "writing", "run_id": rc.run_id, "at": now, "spreadsheet_id": t.spreadsheet_id}
        st.set_state(t.key, writing, conn=conn)
    try:
        api.batch_update(t.spreadsheet_id, b.requests)  # atomic: all or nothing
    except gs.SheetsApiError as exc:
        if exc.rejected:  # Google applied nothing: the sheet still matches its snapshot, keep reading it
            with db.tx("engine", {"sheet": t.key}) as conn:
                st.set_state(t.key, previous, conn=conn)
        raise
    mark = {
        "state": "ok",
        "run_id": rc.run_id,
        "at": now,
        "spreadsheet_id": t.spreadsheet_id,
        "rows": len(b.snapshot),
        "tab_ids": b.tab_ids,
        "full_at": now if b.full else previous.get("full_at"),
    }
    with db.tx("engine", {"sheet": t.key}) as conn:
        st.save_snapshot(t.key, b.snapshot, conn=conn)
        st.set_state(t.key, mark, conn=conn)
    return {**b.stats, "full": b.full, "requests": len(b.requests)}


def refresh_next_steps(rows: Sequence[dict[str, Any]], ctx: Context) -> int:
    """Copy the formulas' next step and due date into leads, so the app shows what the sheet shows."""
    steps = next_steps(rows, ctx)
    changed = [
        (step, due, lead_id)
        for r in rows
        for lead_id in [r["lead_id"]]
        for step, due in [steps[lead_id]]
        if (r.get("next_step") or "") != step or d.as_date(r.get("due_at")) != due
    ]
    if not changed:
        return 0
    with db.tx("engine", {"reason": "next_step"}) as conn, conn.cursor() as cur:
        cur.executemany("update public.leads set next_step = %s, due_at = %s where id = %s", changed)
    return len(changed)
