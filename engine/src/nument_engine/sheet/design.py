"""The sheet design approved on 16 Oct 2026 (D-041), ported from the old `sync_sheet.py` (Step 13.5).

Everything here is pure: colours, the stage map, cell and request builders for the Sheets `batchUpdate` API,
the live formulas, and their Python twin `next_step_and_due`. No database and no network, so the design can be
tested cell by cell. `push.py` assembles these pieces into tabs; `pull.py` reads cells back with the parsers
at the bottom of this file.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any, Final

import phonenumbers
from dateutil import parser as date_parser

Cell = dict[str, Any]
Request = dict[str, Any]

# ---------------------------------------------------------------------------
# Kit: fonts and colours (Figtree body, Newsreader display, DM Mono labels)
# ---------------------------------------------------------------------------
FONT, DISPLAY, MONO = "Figtree", "Newsreader", "DM Mono"
INK, TX2, SUB, FAINT, MUTED = "1F1F1F", "3D3D3D", "666666", "999999", "BDBDBD"
INDIGO, IND300, IND200, HEAD_BG, HAIR = "3333CC", "A7C0F1", "D2DFF9", "FCFCFC", "F0F0F0"
WA_GREEN, LINK, PLUM = "1FA855", "3333CC", "9D2055"
RED_TX, RED_BG, AMBER_TX, AMBER_BG = "A21913", "FDE7E2", "8A5A00", "FFF0CF"
WON_TX, WON_BG, BAR_ON, BAR_OFF = "385418", "E3F1D8", "556ADC", "EEF0F6"

# ---------------------------------------------------------------------------
# Stages (A.12.2): DB value -> (display label, background, text). Order = dropdown order.
# ---------------------------------------------------------------------------
STAGES: Final[dict[str, tuple[str, str, str]]] = {
    "new": ("New", "F2F2F2", "525252"),
    "contacted": ("Contacted", "E8EFFC", "212191"),
    "talking": ("Talking", "D2DFF9", "11115B"),
    "discovery_booked": ("Discovery booked", "FCEAF0", "9D2055"),
    "discovery_done": ("Discovery done", "F9D5E1", "871F4B"),
    "proposal_sent": ("Proposal sent", "FFF0CF", "8A5A00"),
    "won": ("Won", "E3F1D8", "385418"),
    "retainer": ("Retainer", "D9F0EA", "0F5C52"),
    "lost": ("Lost", "FDE7E2", "A21913"),
    "not_now": ("Not now", "FEEDE6", "A5460F"),
    "not_a_fit": ("Not a fit", "F5F5F5", "999999"),
    "wrong_contact": ("Wrong contact", "F3EEE8", "7A5536"),
}
CLOSED: Final[frozenset[str]] = frozenset({"won", "retainer", "lost", "not_now", "not_a_fit", "wrong_contact"})
WON: Final[tuple[str, ...]] = ("won", "retainer")  # Retainer = won and paying monthly (founder, 17 Oct 2026)
LABEL_TO_STAGE: Final[dict[str, str]] = {label.lower(): key for key, (label, _, _) in STAGES.items()}
# Labels of the old sheets (Call result column, before 16 Oct 2026) -> stage. Used by the legacy import only.
LEGACY_LABELS: Final[dict[str, str]] = {
    "not reached": "contacted",
    "interested": "talking",
    "meeting booked": "discovery_booked",
}
UNKNOWN_STAGE_STYLE: Final[tuple[str, str]] = ("FFFFFF", "999999")
GRADE_STYLE: Final[dict[str, tuple[str, str]]] = {  # text, background
    "A": ("496D21", "E3F1D8"),
    "B": ("3333CC", "E8EFFC"),
    "C": ("666666", "F5F5F5"),
    "D": ("999999", "FAFAFA"),
}
# Pipeline by stage, on the Today tab: open stages first, then the closed ones.
FUNNEL: Final[tuple[str, ...]] = (
    "new",
    "contacted",
    "talking",
    "discovery_booked",
    "discovery_done",
    "proposal_sent",
    "won",
    "retainer",
    "not_now",
    "lost",
    "not_a_fit",
    "wrong_contact",
)
# Next steps that only the founder does; every other step belongs to whoever calls.
FOUNDER_STEPS: Final[tuple[str, ...]] = (
    "Discovery call",
    "Send proposal",
    "Follow up proposal",
    "Kick-off",
    "Monthly review",
)
EMPTY_TODO: Final = "Nothing due today"
EPOCH: Final = dt.date(1899, 12, 30)  # Sheets date serial 0
IST: Final = dt.timezone(dt.timedelta(hours=5, minutes=30))
DATE_FIELDS: Final[tuple[str, ...]] = ("wa_at", "call_at", "d3_at", "d7_at", "meeting_at")


def canon_stage(text: object) -> tuple[str | None, str]:
    """(DB stage, original text) for a Stage cell. Unknown text gives (None, text). Never raises.

    Matches the display label in any case ("wrong Contact"), or the DB value itself ("not_now"). A blank cell
    means New, like the old sheets.
    """
    raw = "" if text is None else str(text).strip()
    if not raw:
        return "new", raw
    key = raw.lower()
    if key in LABEL_TO_STAGE:
        return LABEL_TO_STAGE[key], raw
    return (key if key in STAGES else None), raw


def stage_label(value: str) -> str:
    """Display label of a DB stage; an unknown value is shown as it is."""
    return STAGES[value][0] if value in STAGES else value


def stage_style(value: str) -> tuple[str, str]:
    """(background, text) colours of a stage. Unknown stages are grey and never raise (lesson 3, 13.2.1)."""
    return (STAGES[value][1], STAGES[value][2]) if value in STAGES else UNKNOWN_STAGE_STYLE


# ---------------------------------------------------------------------------
# Header notes (13.5.5)
# ---------------------------------------------------------------------------
NOTES: Final[dict[str, str]] = {
    "Grade": "A = start here, B = next. C and D stay in the database and come back when they show a new signal.",
    "Phone · WhatsApp": "A number the business published itself. Click it to open WhatsApp Web with the first "
    "message typed.",
    "Why now": "Their freshest buying signal. The proof link is in Lead details and in the app.",
    "Stage": "Move it forward as the lead progresses. Contacted without a WA date means the first WhatsApp went "
    "out today; the call is next. Retainer = won and paying monthly. Lost, Not now, Not a fit and Wrong contact "
    "close the lead.",
    "WA": "Date the first WhatsApp went out. Double-click for a date picker.",
    "Call": "Date of the first call (day 1).",
    "Day 3": "Date of the day 3 follow-up.",
    "Day 7": "Date of the last touch. After this, move the lead to Not now if there is no reply.",
    "Meeting": "Date of the discovery call with the founder.",
    "Next step": "Filled automatically from the stage and the touch dates.",
    "Due": "When the next step is due. Red = overdue, amber = today.",
    "Win chance": "Lead score from 0 to 100: their buying signal, whether they can pay, and how reachable they are.",
    "Deal value": "Our estimate (grey) until you type the real value once quoted or won. Master sheet only.",
    "Notes": "Anything worth remembering. Synced with the app.",
}


# ---------------------------------------------------------------------------
# Cell builders (ported unchanged in behaviour; they only build JSON for batchUpdate)
# ---------------------------------------------------------------------------
def rgb(hex_colour: str) -> dict[str, float]:
    h = hex_colour
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def f(
    bold: bool = False,
    color: str = TX2,
    h: str = "LEFT",
    size: int = 10,
    wrap: str = "CLIP",
    nf: str | None = None,
    nf_type: str = "NUMBER",
    font: str = FONT,
    bg: str | None = None,
    borders: dict[str, Any] | None = None,
    italic: bool = False,
) -> dict[str, Any]:
    """A cell format: font, colour, alignment, wrap, number format, fill and borders."""
    out: dict[str, Any] = {
        "textFormat": {
            "fontFamily": font,
            "fontSize": size,
            "bold": bold,
            "italic": italic,
            "foregroundColorStyle": {"rgbColor": rgb(color)},
        },
        "verticalAlignment": "MIDDLE",
        "horizontalAlignment": h,
        "wrapStrategy": wrap,
        "padding": {"left": 9, "right": 9, "top": 2, "bottom": 2},
    }
    if nf:
        out["numberFormat"] = {"type": nf_type, "pattern": nf}
    if bg:
        out["backgroundColorStyle"] = {"rgbColor": rgb(bg)}
    if borders:
        out["borders"] = borders
    return out


def side(color: str, style: str = "SOLID") -> dict[str, Any]:
    return {"style": style, "colorStyle": {"rgbColor": rgb(color)}}


HAIRLINE: Final[dict[str, Any]] = {"bottom": side(HAIR)}
# White gaps around a filled cell make the fill read as a block (grade and stage chips).
INSET: Final[dict[str, Any]] = {k: side("FFFFFF", "SOLID_THICK") for k in ("top", "bottom", "left", "right")}


def txt(value: object, fmt: dict[str, Any] | None = None, note: str | None = None) -> Cell:
    out: Cell = {
        "userEnteredValue": {"stringValue": "" if value is None else str(value)},
        "userEnteredFormat": fmt or f(),
    }
    if note:
        out["note"] = note
    return out


def fmt_only(fmt: dict[str, Any]) -> Cell:
    return {"userEnteredFormat": fmt}


def num(value: float | int | None, fmt: dict[str, Any]) -> Cell:
    return {"userEnteredValue": {"numberValue": value} if value is not None else {}, "userEnteredFormat": fmt}


def formula(expr: str, fmt: dict[str, Any]) -> Cell:
    return {"userEnteredValue": {"formulaValue": expr}, "userEnteredFormat": fmt}


RichPart = tuple[Any, ...]  # (text, colour, bold, link or None, size or None[, font])


def rich(parts: Sequence[RichPart], fmt: dict[str, Any]) -> Cell:
    """One cell with several styles: parts are (text, colour, bold, link or None, size or None[, font])."""
    text, runs = "", []
    for t, color, bold, url, size, *font in parts:
        tf: dict[str, Any] = {"foregroundColorStyle": {"rgbColor": rgb(color)}, "bold": bold}
        if size:
            tf["fontSize"] = size
        if font:
            tf["fontFamily"] = font[0]
        if url:
            tf["link"] = {"uri": url}
            tf["underline"] = False
        runs.append({"startIndex": len(text), "format": tf})
        text += t
    return {"userEnteredValue": {"stringValue": text}, "userEnteredFormat": fmt, "textFormatRuns": runs}


def links_cell(pairs: Iterable[tuple[str, str | None]], fmt: dict[str, Any]) -> Cell:
    """One cell, several links: 'Proof · Website · Phone source' (rich-text runs)."""
    good = [(label, u) for label, u in pairs if str(u or "").startswith(("http", "mailto:"))]
    if not good:
        return txt("", fmt)
    parts: list[RichPart] = []
    for i, (label, u) in enumerate(good):
        if i:
            parts.append(("  ·  ", FAINT, False, None, None))
        parts.append((label, LINK, False, u, None))
    return rich(parts, fmt)


def rule(
    sid: int,
    r0: int,
    r1: int,
    c0: int,
    c1: int,
    expr: str,
    color: str | None = None,
    bg: str | None = None,
    bold: bool | None = None,
) -> Request:
    """A conditional format rule with a custom formula."""
    fmt: dict[str, Any] = {}
    tf: dict[str, Any] = {}
    if color:
        tf["foregroundColorStyle"] = {"rgbColor": rgb(color)}
    if bold is not None:
        tf["bold"] = bold
    if tf:
        fmt["textFormat"] = tf  # an empty textFormat is rejected by the API
    if bg:
        fmt["backgroundColorStyle"] = {"rgbColor": rgb(bg)}
    return {
        "addConditionalFormatRule": {
            "index": 0,
            "rule": {
                "ranges": [
                    {
                        "sheetId": sid,
                        "startRowIndex": r0,
                        "endRowIndex": r1,
                        "startColumnIndex": c0,
                        "endColumnIndex": c1,
                    }
                ],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": expr}]},
                    "format": fmt,
                },
            },
        }
    }


def col(i: int) -> str:
    """Column letter of a 0-based index (A..Z, AA..AZ)."""
    return chr(ord("A") + i) if i < 26 else "A" + chr(ord("A") + i - 26)


def tab_ref(tab: str) -> str:
    """A tab name for formulas, always quoted ('Pipeline (caller)' needs it, 'Pipeline' accepts it)."""
    return "'" + tab.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Request builders (pure; push.py sends them)
# ---------------------------------------------------------------------------
def grid(
    sid: int,
    ncols: int,
    nrows: int,
    widths: Sequence[int],
    frozen_rows: int = 0,
    frozen_cols: int = 0,
    hidden: Iterable[int] = (),
    tab: str | None = None,
) -> list[Request]:
    hidden_set = set(hidden)
    props: dict[str, Any] = {
        "sheetId": sid,
        "gridProperties": {
            "frozenRowCount": frozen_rows,
            "frozenColumnCount": frozen_cols,
            "hideGridlines": True,
            "rowCount": nrows,
            "columnCount": ncols,
        },
    }
    fields = "gridProperties(frozenRowCount,frozenColumnCount,hideGridlines,rowCount,columnCount)"
    if tab:
        props["tabColorStyle"] = {"rgbColor": rgb(tab)}
        fields += ",tabColorStyle"
    reqs: list[Request] = [{"updateSheetProperties": {"properties": props, "fields": fields}}]
    reqs += [
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": j, "endIndex": j + 1},
                "properties": {"pixelSize": w, "hiddenByUser": j in hidden_set},
                "fields": "pixelSize,hiddenByUser",
            }
        }
        for j, w in enumerate(widths)
    ]
    return reqs


def row_heights(sid: int, spans: Iterable[tuple[int, int, int]]) -> list[Request]:
    """spans = [(start_row, end_row, px)], 0-based, end exclusive."""
    return [
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": a, "endIndex": b},
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        }
        for a, b, px in spans
        if b > a
    ]


def put(sid: int, r: int, c: int, rows: Sequence[Sequence[Cell]]) -> Request:
    return {
        "updateCells": {
            "start": {"sheetId": sid, "rowIndex": r, "columnIndex": c},
            "rows": [{"values": list(v)} for v in rows],
            "fields": "*",
        }
    }


def merge(sid: int, r0: int, r1: int, c0: int, c1: int) -> Request:
    return {
        "mergeCells": {
            "range": {
                "sheetId": sid,
                "startRowIndex": r0,
                "endRowIndex": r1,
                "startColumnIndex": c0,
                "endColumnIndex": c1,
            },
            "mergeType": "MERGE_ALL",
        }
    }


def borders(sid: int, r0: int, r1: int, c0: int, c1: int, **sides: Any) -> Request:
    return {
        "updateBorders": {
            "range": {
                "sheetId": sid,
                "startRowIndex": r0,
                "endRowIndex": r1,
                "startColumnIndex": c0,
                "endColumnIndex": c1,
            },
            **sides,
        }
    }


def protect(
    sid: int,
    r0: int,
    r1: int,
    c0: int,
    c1: int,
    what: str = "Filled by Nument Leads; changes here are overwritten on the next sync",
) -> Request:
    """A warning-only protected range (people can override the warning; pull ignores these columns anyway)."""
    return {
        "addProtectedRange": {
            "protectedRange": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": r0,
                    "endRowIndex": r1,
                    "startColumnIndex": c0,
                    "endColumnIndex": c1,
                },
                "description": what,
                "warningOnly": True,
            }
        }
    }


# ---------------------------------------------------------------------------
# Display values
# ---------------------------------------------------------------------------
_LEGAL = re.compile(r"\b(private limited|pvt\.? ltd\.?|limited|llp)\b\.?", re.I)


def clean_org(name: str | None) -> str:
    """'Hometrust Realty Private Limited (HomeTrust)' -> 'Hometrust Realty'."""
    first = re.split(r"\s+\(|\s+/\s+", name or "")[0]
    return _LEGAL.sub("", first).strip(" ,·-") or (name or "")


def short_name(name: str | None, limit: int = 24) -> str:
    """Company name cut at a word boundary to fit the column (13.3.4: 24 characters)."""
    full = clean_org(name)
    if len(full) <= limit:
        return full
    out = ""
    for word in full.split():
        if len(out) + len(word) + (1 if out else 0) > limit:
            break
        out = f"{out} {word}".strip()
    return re.sub(r"\s+(of|and|&|the)$", "", out, flags=re.I) or full[:limit]


def cut(text: str | None, n: int) -> str:
    """Shorten at a word boundary and add an ellipsis."""
    s = (text or "").strip().strip('"').strip("“”")
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(",;:·/(") + "…"


_HONORIFICS: Final = ("dr", "ca", "adv", "mr", "ms", "mrs", "prof", "acharya")


def person_short(name: str | None, limit: int = 20) -> str:
    """'Dr. Asha Kiranmayee Rao' -> 'Dr. Asha Rao': drop middle names when the name is long."""
    p = (name or "").strip()
    words = p.split()
    if len(p) <= limit or len(words) < 3:
        return p
    hon = words[0] if words[0].rstrip(".").lower() in _HONORIFICS else ""
    core = words[1:] if hon else words
    return " ".join(x for x in (hon, core[0], core[-1]) if x)


def person_role(name: str | None, role: str | None) -> str:
    role_short = re.split(r"\s+\(|;", role or "")[0].strip()
    return ", ".join(p for p in ((name or "").strip(), role_short) if p)


def inr(value: float | int | Decimal | None) -> str:
    """₹ in the Indian way: ₹45K, ₹3L, ₹1.2 Cr."""
    if value is None:
        return ""
    v = float(value)
    if v >= 1e7:
        s = f"{v / 1e7:.1f}".rstrip("0").rstrip(".") + " Cr"
    elif v >= 1e5:
        s = f"{v / 1e5:.1f}".rstrip("0").rstrip(".") + "L"
    elif v >= 1e3:
        s = f"{v / 1e3:.0f}K"
    else:
        s = f"{v:.0f}"
    return "₹" + s


def estimate_text(low: float | int | Decimal | None, high: float | int | Decimal | None) -> str:
    """The grey deal estimate: '₹3L to 8L', or '≈ ₹5L' for a single value.

    Both forms are ignored by `parse_money_cell`, so an untouched estimate is never read back as an edit.
    """
    if high is None and low is None:
        return ""
    if high is None or low is None or float(low) == float(high):
        return "≈ " + inr(high if high is not None else low)
    return f"{inr(low)} to {inr(high)[1:]}"


def phone_display(phone_e164: str | None) -> str:
    """'+919800000123' -> '+91 98000 00123' (international format of the number's own country)."""
    if not phone_e164:
        return ""
    try:
        parsed = phonenumbers.parse(phone_e164, None)
    except phonenumbers.NumberParseException:
        return phone_e164
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def wa_web_link(phone_e164: str | None, phone_type: str | None, message: str | None) -> str:
    """Desktop link that opens WhatsApp Web on the chat with the message typed (founder's choice, 12 Nov 2026).

    Mobiles only: landlines and unknown types get no WhatsApp link.
    """
    if not phone_e164 or phone_type != "mobile":
        return ""
    digits = phone_e164.lstrip("+")
    return f"https://web.whatsapp.com/send?phone={digits}&text={urllib.parse.quote(message or '')}"


def text_height(text: object, width: int, size: int = 9) -> float:
    """Pixel height a wrapped cell needs (Figtree averages about 0.52 em a character; 9 pt lines are about 15 px)."""
    per = max(8, int((width - 24) / (size * 4 / 3 * 0.52)))
    lines = 0
    for para in str(text or "").split("\n"):
        n, used = 1, 0
        for word in para.split():
            if used and used + 1 + len(word) > per:
                n, used = n + 1, len(word)
            else:
                used += (1 if used else 0) + len(word)
        lines += n
    return lines * 15.5 + 14


def blend(hex_colour: str, alpha: float = 0.75) -> str:
    """The colour at opacity `alpha` over white."""
    return "".join(f"{round(alpha * int(hex_colour[i : i + 2], 16) + (1 - alpha) * 255):02X}" for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def as_date(value: object) -> dt.date | None:
    """A date from a date, an aware datetime (taken in IST) or an ISO string; None when empty or unreadable."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return (value.astimezone(IST) if value.tzinfo else value).date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def serial(value: object) -> int | None:
    """Sheets date serial of a date (days since 1899-12-30)."""
    d = as_date(value)
    return (d - EPOCH).days if d else None


def from_serial(value: float | int) -> dt.date:
    """Date of a Sheets serial number; the fraction (a time typed with the date) is dropped."""
    return EPOCH + dt.timedelta(days=int(value))


def parse_date_cell(value: object) -> str | None:
    """A WA, Call, Day 3, Day 7 or Meeting cell -> 'YYYY-MM-DD', '' when blank, None when unreadable.

    Cells are read with UNFORMATTED_VALUE and SERIAL_NUMBER, so real dates arrive as numbers. Text the sheet
    could not parse as a date (for example '12/11' in a sheet with a US locale) is read day first, like India.
    None means "not a date": the caller treats it as untouched, never as cleared.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return from_serial(value).isoformat() if value > 0 else None
    s = str(value).strip()
    if not s:
        return ""
    try:
        return dt.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        pass
    try:
        parsed = date_parser.parse(s, dayfirst=True, default=dt.datetime(today_ist().year, 1, 1))
    except (ValueError, OverflowError):
        return None
    return parsed.date().isoformat()


_MONEY = re.compile(r"₹?\s*([\d.]+)\s*(cr|crore|l|lakh|lac|k)?", re.I)
_MONEY_UNITS: Final[dict[str, float]] = {"cr": 1e7, "crore": 1e7, "l": 1e5, "lakh": 1e5, "lac": 1e5, "k": 1e3}


def parse_money_cell(value: object) -> str | None:
    """A Deal value cell -> whole rupees as a string, '' when blank or an estimate, None when unreadable.

    Grey estimates written by push ('₹3L to 8L', '≈ ₹5L') are never edits. '₹1.2L' is 120000.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return money_str(value)
    s = str(value).strip().replace(",", "")
    if not s or " to " in s or s.startswith("≈"):
        return ""
    m = _MONEY.fullmatch(s)
    if not m:
        return None
    try:
        amount = float(m.group(1)) * _MONEY_UNITS.get((m.group(2) or "").lower(), 1)
    except ValueError:
        return None
    return str(round(amount))


def money_str(value: float | int | Decimal | None) -> str:
    """Canonical text of a money value for snapshots: '' for none, '150000' for whole rupees, else '1500.5'."""
    if value is None:
        return ""
    v = Decimal(str(value))
    if v == v.to_integral_value():
        return str(int(v))
    return format(v.normalize(), "f")


# ---------------------------------------------------------------------------
# Next step and due date: the Python twin of the Pipeline formulas (13.5.4)
# ---------------------------------------------------------------------------
def next_step_and_due(
    stage: str,
    dates: dict[str, dt.date | None],
    today: dt.date,
    queue_pos: int | None,
    new_per_day: int,
    first_touch: str = "Send WhatsApp",
    step2: str = "Call",
) -> tuple[str, dt.date | None]:
    """(next step, due date) with exactly the rules of the sheet formulas (`pipeline_formulas`).

    first_touch  the first action for a new lead: "Send WhatsApp" for a mobile, "Call" for a landline, ...
    step2        the action after the first message: "Call" when there is a phone, else "Follow up".
    queue_pos    position among New leads without a WA date, in sheet order; only the first `new_per_day`
                 are due today.
    """
    wa, call, d3, d7, mt = (dates.get(k) for k in DATE_FIELDS)
    touches = [d for d in (wa, call, d3, d7) if d]
    last = max(touches) if touches else None
    day = dt.timedelta(days=1)
    if stage == "won":
        return "Kick-off", None
    if stage == "retainer":
        return "Monthly review", None
    if stage == "wrong_contact":
        return "Find the right number", None
    if stage in ("lost", "not_a_fit"):
        return "", None
    if stage == "not_now":
        return "Check back", (last or today) + 30 * day
    if stage == "proposal_sent":
        return "Follow up proposal", (mt + 4 * day) if mt else today
    if stage == "discovery_done":
        return "Send proposal", (mt + 2 * day) if mt else today
    if stage == "discovery_booked":
        return "Discovery call", mt or today
    if stage == "talking":
        return "Book discovery call", (last + day) if last else today
    if stage == "contacted" and not wa:
        return step2, today
    if not wa:
        return first_touch, (today if (queue_pos and queue_pos <= new_per_day) else None)
    if not call:
        return step2, wa + day
    if not d3:
        return "Day 3 follow-up", wa + 3 * day
    if not d7:
        return "Last touch", wa + 7 * day
    return "Move to Not now", d7 + day


def pipeline_formulas(
    refs: dict[str, str],
    row: int,
    first_row: int,
    new_per_day: int,
    first_touch: str,
    step2: str,
    founder: str,
    associate: str,
) -> dict[str, str]:
    """Live formulas for one Pipeline row (1-based `row`; `first_row` = first data row, 1-based).

    refs maps column keys to letters. Stage cells hold display labels, so the formulas compare labels.
    Keep these rules identical to `next_step_and_due`; `test_next_step_twin` checks both.
    """

    def lab(stage: str) -> str:
        return '"' + STAGES[stage][0] + '"'

    s, wa, ca, d3, d7, mt, dd, q, nx = (
        f"${refs[k]}{row}" for k in ("stage", "wa", "call", "d3", "d7", "meeting", "dd", "queue", "next")
    )
    nxt = (
        f'=IFS({s}={lab("won")},"Kick-off",{s}={lab("retainer")},"Monthly review",'
        f'{s}={lab("wrong_contact")},"Find the right number",OR({s}={lab("lost")},{s}={lab("not_a_fit")}),"",'
        f'{s}={lab("not_now")},"Check back",{s}={lab("proposal_sent")},"Follow up proposal",'
        f'{s}={lab("discovery_done")},"Send proposal",{s}={lab("discovery_booked")},"Discovery call",'
        f'{s}={lab("talking")},"Book discovery call",AND({s}={lab("contacted")},{wa}=""),"{step2}",'
        f'{wa}="","{first_touch}",{ca}="","{step2}",{d3}="","Day 3 follow-up",'
        f'{d7}="","Last touch",TRUE,"Move to Not now")'
    )
    last = f"MAX({wa},{ca},{d3},{d7})"
    closed = ",".join(f"{s}={lab(k)}" for k in ("won", "retainer", "lost", "not_a_fit", "wrong_contact"))
    due_date = (
        f'=IFS(OR({closed}),"",{s}={lab("not_now")},IF({last}=0,TODAY()+30,{last}+30),'
        f'{s}={lab("proposal_sent")},IF({mt}="",TODAY(),{mt}+4),'
        f'{s}={lab("discovery_done")},IF({mt}="",TODAY(),{mt}+2),'
        f'{s}={lab("discovery_booked")},IF({mt}="",TODAY(),{mt}),'
        f"{s}={lab('talking')},IF({last}=0,TODAY(),{last}+1),"
        f'AND({s}={lab("contacted")},{wa}=""),TODAY(),'
        f'{wa}="",IF(AND(ISNUMBER({q}),{q}<={new_per_day}),TODAY(),""),'
        f'{ca}="",{wa}+1,{d3}="",{wa}+3,{d7}="",{wa}+7,TRUE,{d7}+1)'
    )
    due = (
        f'=IF({dd}="","",IF({dd}<TODAY(),"Overdue "&(TODAY()-{dd})&"d",IF({dd}=TODAY(),"Today",'
        f'IF({dd}-TODAY()>6,TEXT({dd},"d mmm"),TEXT({dd},"ddd d")))))'
    )
    st, wac = refs["stage"], refs["wa"]
    queue = (
        f'=IF(AND({s}={lab("new")},{wa}=""),COUNTIFS(${st}${first_row}:${st}{row},{lab("new")},'
        f'${wac}${first_row}:${wac}{row},""),"")'
    )
    founder_steps = ",".join(f'{nx}="{step}"' for step in FOUNDER_STEPS)
    who = f'=IF({nx}="","",IF(OR({founder_steps}),"{founder}","{associate}"))'
    return {"next": nxt, "dd": due_date, "due": due, "queue": queue, "who": who}
