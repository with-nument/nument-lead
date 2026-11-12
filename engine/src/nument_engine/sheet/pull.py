"""Sheet to database: the stages, dates, deal values and notes people typed (Step 13.7).

An edit is a cell that differs from what this engine last wrote to *that* sheet (its own snapshot), so a stale
sheet can never undo an edit made on the other one (D-045). Each edit is then resolved against the database:

| Case | Condition                                             | Result                                        |
|------|-------------------------------------------------------|-----------------------------------------------|
| 1    | no sheet differs from its snapshot                    | nothing                                       |
| 2    | a sheet changed, the database did not                 | apply the sheet value (activity `edit`)       |
| 3    | only the database changed                             | nothing here; the next push writes it         |
| 4    | the sheet value already equals the database           | nothing                                       |
| 5    | the sheet and the app both changed it, differently    | the most recent wins; the loser is logged     |
| 6    | master and caller changed it, differently             | master wins; the caller value is logged       |
| 7    | a stage that is not in A.12.2                         | database unchanged, activity `unknown_stage`  |
| 8    | a lead id the database does not know                  | ignored and counted                           |

Stage changes are written by updating `leads.stage` inside `db.tx("sheet", ...)`: the database trigger logs the
`stage_change` activity with source `sheet` (A.13.5 rule 1). Code only logs `edit`, `conflict_overridden`,
`unknown_stage` and `wrong_contact`.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from psycopg import Connection, sql

from .. import db
from ..logging import get_logger
from ..pipeline.runs import RunContext
from . import client as gs
from . import design as d
from . import push
from . import state as st
from .client import Target

log = get_logger()

FIELDS: Final[tuple[str, ...]] = (
    "stage",
    "wa_at",
    "call_at",
    "d3_at",
    "d7_at",
    "meeting_at",
    "deal_value_inr",
    "notes",
)
DB_SQL: Final = """
select id::text as lead_id, stage, notes, wa_at, call_at, d3_at, d7_at, meeting_at, deal_value_inr
from public.leads where id = any(%s::uuid[])
"""
# Latest app edit per lead and field. The app logs `edit` with payload.field; the trigger logs stage changes;
# "Mark sent" logs `sent` (stage and WA date), calls and meetings log their own types (Step 15.5).
APP_TIMES_SQL: Final = """
select lead_id::text as lead_id, f.field, max(a.at) as at
from public.activities a
cross join lateral (
  select unnest(case
    when a.payload ? 'field'      then array[a.payload ->> 'field']
    when a.type = 'stage_change'  then array['stage']
    when a.type = 'sent'          then array['stage', 'wa_at']
    when a.type = 'call'          then array['call_at']
    when a.type = 'meeting'       then array['meeting_at']
    else array[]::text[] end) as field
) f
where a.source = 'app' and a.lead_id = any(%s::uuid[])
group by 1, 2
"""


@dataclass(frozen=True)
class Change:
    """One field of one lead that takes the sheet's value."""

    lead_id: str
    field: str
    old: str
    new: str
    sheet: str  # target key the value came from


@dataclass(frozen=True)
class Conflict:
    """A value that lost: logged as `conflict_overridden` so nothing disappears silently."""

    lead_id: str
    field: str
    kept: str
    kept_from: str  # "app", "master", "caller", ... (target key)
    lost: str
    lost_from: str
    reason: str  # "most_recent" or "master_wins"
    sheet_time: str | None = None
    app_time: str | None = None


@dataclass
class Resolution:
    changes: list[Change] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    unknown_stages: list[tuple[str, str, str]] = field(default_factory=list)  # (lead_id, sheet, text)
    missing: list[str] = field(default_factory=list)  # lead ids in a sheet but not in the database


# ---------------------------------------------------------------------------
# Reading a sheet
# ---------------------------------------------------------------------------
def read_editable(
    api: gs.SheetsApi, target: Target, legacy_ids: Mapping[str, str] | None = None
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """({lead_id: {field: value}}, lead ids in row order) from the Pipeline tab, by header text (13.7.2).

    Values use the snapshot format: DB stage, ISO dates, whole rupees, trimmed notes. A stage that is not a
    known label comes back as '?<text>'. A cell that cannot be read (a date typed as words) is left out, so it
    counts as untouched, never as cleared. Old sheets carry old ids ('A-0051'): `legacy_ids` maps them.
    """
    rows = api.values(target.spreadsheet_id, d.tab_ref(target.tab("Pipeline")))
    hrow = next((i for i, r in enumerate(rows[:6]) if "ID" in r and "Stage" in r), None)
    if hrow is None:
        return {}, []
    idx = {str(h): i for i, h in enumerate(rows[hrow])}
    out: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for r in rows[hrow + 1 :]:

        def cell(header: str, r: list[Any] = r) -> Any:
            i = idx.get(header)
            return r[i] if i is not None and i < len(r) else ""

        raw_id = str(cell("ID")).strip()
        lead_id = (legacy_ids or {}).get(raw_id, raw_id)
        if len(lead_id) != 36 or lead_id in out:  # a uuid; skips blank rows, footers and copied rows
            continue
        stage_db, raw = d.canon_stage(cell("Stage"))
        vals: dict[str, str] = {"stage": stage_db or f"?{raw}", "notes": _text(cell("Notes"))}
        for key, header in push.EDITABLE.items():
            if key in ("stage", "notes") or header not in idx:
                continue
            if key == "deal_value_inr":
                if not target.money:
                    continue
                parsed = d.parse_money_cell(cell(header))
            else:
                parsed = d.parse_date_cell(cell(header))
            if parsed is not None:
                vals[key] = parsed
        out[lead_id] = vals
        order.append(lead_id)
    return out, order


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# ---------------------------------------------------------------------------
# Database values in the snapshot format
# ---------------------------------------------------------------------------
def db_values(lead_ids: Iterable[str], conn: Connection[Any] | None = None) -> dict[str, dict[str, str]]:
    ids = list(lead_ids)
    if not ids:
        return {}
    out = {}
    for r in db.fetch_all(DB_SQL, [ids], conn=conn):
        vals = {
            "stage": r["stage"],
            "notes": (r["notes"] or "").strip(),
            "deal_value_inr": d.money_str(r["deal_value_inr"]),
        }
        for k in d.DATE_FIELDS:
            day = d.as_date(r[k])
            vals[k] = day.isoformat() if day else ""
        out[r["lead_id"]] = vals
    return out


def app_times(lead_ids: Iterable[str], conn: Connection[Any] | None = None) -> dict[tuple[str, str], dt.datetime]:
    ids = list(lead_ids)
    if not ids:
        return {}
    return {(r["lead_id"], r["field"]): r["at"] for r in db.fetch_all(APP_TIMES_SQL, [ids], conn=conn)}


# ---------------------------------------------------------------------------
# Resolution (pure, so every case is tested with fixed values and times)
# ---------------------------------------------------------------------------
def resolve(
    sheets: Mapping[str, Mapping[str, Mapping[str, str]]],
    snapshots: Mapping[str, Mapping[str, Mapping[str, Any]]],
    current: Mapping[str, Mapping[str, str]],
    sheet_times: Mapping[str, dt.datetime],
    app_edit_times: Mapping[tuple[str, str], dt.datetime],
) -> Resolution:
    """Decide what each edit does (13.7.3). `sheets` is ordered: the master view first, so it wins case 6."""
    res = Resolution()
    lead_ids: list[str] = []
    for vals in sheets.values():
        lead_ids += [x for x in vals if x not in lead_ids]
    for lead_id in lead_ids:
        if lead_id not in current:
            res.missing.append(lead_id)  # case 8
            continue
        for fld in FIELDS:
            candidates: list[tuple[str, str]] = []
            for key, vals in sheets.items():
                row, snap = vals.get(lead_id), snapshots.get(key, {}).get(lead_id)
                if row is None or snap is None or fld not in row:
                    continue
                value = row[fld]
                if fld == "stage" and value.startswith("?"):
                    res.unknown_stages.append((lead_id, key, value[1:]))  # case 7
                    continue
                if value != str(snap.get(fld, "")):
                    candidates.append((key, value))
            if not candidates:
                continue  # cases 1 and 3
            win_key, win_value = candidates[0]
            for key, value in candidates[1:]:
                if value != win_value:  # case 6: master wins
                    res.conflicts.append(Conflict(lead_id, fld, win_value, win_key, value, key, "master_wins"))
            now_value = current[lead_id].get(fld, "")
            if win_value == now_value:
                continue  # case 4
            base = str(snapshots[win_key][lead_id].get(fld, ""))
            if now_value == base:  # case 2
                res.changes.append(Change(lead_id, fld, now_value, win_value, win_key))
                continue
            # case 5: both sides changed it since the last push; the most recent edit wins
            sheet_time = sheet_times.get(win_key)
            app_time = app_edit_times.get((lead_id, fld))
            times = {
                "sheet_time": sheet_time.isoformat() if sheet_time else None,
                "app_time": app_time.isoformat() if app_time else None,
            }
            if app_time is None or (sheet_time is not None and sheet_time >= app_time):
                res.changes.append(Change(lead_id, fld, now_value, win_value, win_key))
                res.conflicts.append(
                    Conflict(lead_id, fld, win_value, win_key, now_value, "app", "most_recent", **times)
                )
            else:
                res.conflicts.append(
                    Conflict(lead_id, fld, now_value, "app", win_value, win_key, "most_recent", **times)
                )
    return res


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------
def _db_value(fld: str, value: str, existing: Any) -> Any:
    """A snapshot-format value as the column type."""
    if fld in ("stage",):
        return value
    if fld == "notes":
        return value or None
    if fld == "deal_value_inr":
        return Decimal(value) if value else None
    if not value:
        return None
    day = dt.date.fromisoformat(value)
    if fld == "meeting_at":  # keep the time of day the app set; a new date alone starts at 00:00 IST
        old = existing if isinstance(existing, dt.datetime) else None
        clock = old.astimezone(d.IST).timetz() if old else dt.time(0, 0, tzinfo=d.IST)
        return dt.datetime.combine(day, clock)
    return day


def apply(res: Resolution, *, conn: Connection[Any]) -> dict[str, int]:
    """Write the resolution inside the caller's transaction (opened with db.tx("sheet", ...))."""
    by_lead: dict[str, list[Change]] = {}
    for ch in res.changes:
        by_lead.setdefault(ch.lead_id, []).append(ch)
    meetings = {
        r["id"]: r["meeting_at"]
        for r in db.fetch_all(
            "select id::text as id, meeting_at from public.leads where id = any(%s::uuid[])", [list(by_lead)], conn=conn
        )
    }
    wrong = 0
    for lead_id, changes in by_lead.items():
        stage_sheet = next((c.sheet for c in changes if c.field == "stage"), changes[0].sheet)
        conn.execute("select set_config('app.context', %s, true)", [json.dumps({"sheet": stage_sheet})])
        sets = {c.field: _db_value(c.field, c.new, meetings.get(lead_id)) for c in changes}
        query = sql.SQL("update public.leads set {}, last_activity_at = now() where id = %s").format(
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(fld)) for fld in sets)
        )
        conn.execute(query, [*sets.values(), lead_id])
        for c in changes:
            if c.field != "stage":  # the trigger logs stage changes (A.13.5 rule 1)
                _activity(conn, lead_id, "edit", {"field": c.field, "from": c.old, "to": c.new, "sheet": c.sheet})
        if sets.get("stage") == "wrong_contact":
            wrong += _mark_wrong_contact(conn, lead_id, stage_sheet)
    for cf in res.conflicts:
        _activity(
            conn,
            cf.lead_id,
            "conflict_overridden",
            {
                "field": cf.field,
                "kept": cf.kept,
                "kept_from": cf.kept_from,
                "lost": cf.lost,
                "lost_from": cf.lost_from,
                "reason": cf.reason,
                "sheet_time": cf.sheet_time,
                "app_time": cf.app_time,
            },
        )
    seen_unknown = set()
    for lead_id, sheet, text in res.unknown_stages:
        if (lead_id, text) in seen_unknown:
            continue
        seen_unknown.add((lead_id, text))
        _activity(conn, lead_id, "unknown_stage", {"text": text, "sheet": sheet})
    return {
        "leads_changed": len(by_lead),
        "fields_changed": len(res.changes),
        "conflicts": len(res.conflicts),
        "unknown_stages": len(seen_unknown),
        "wrong_contacts": wrong,
        "missing": len(res.missing),
    }


def _activity(conn: Connection[Any], lead_id: str, kind: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "insert into public.activities (lead_id, source, type, payload) values (%s, 'sheet', %s, %s)",
        [lead_id, kind, db.Jsonb(payload)],
    )


def _mark_wrong_contact(conn: Connection[Any], lead_id: str, sheet: str) -> int:
    """Wrong contact (13.7.5): the number shown for the lead is never used again."""
    row = db.fetch_one(
        "select pc.contact_id::text as contact_id, pc.phone_e164 from public.leads l "
        "join public.v_primary_contact pc on pc.business_id = l.business_id where l.id = %s",
        [lead_id],
        conn=conn,
    )
    if not row or not row["phone_e164"]:
        return 0
    conn.execute("update public.contacts set do_not_contact = true where id = %s", [row["contact_id"]])
    conn.execute(
        "insert into public.suppression (phone_e164, reason) values (%s, 'wrong_contact') "
        "on conflict (phone_e164) where phone_e164 is not null do nothing",
        [row["phone_e164"]],
    )
    _activity(conn, lead_id, "wrong_contact", {"contact_id": row["contact_id"], "sheet": sheet})
    return 1


# ---------------------------------------------------------------------------
# The pull
# ---------------------------------------------------------------------------
@dataclass
class PullResult:
    stats: dict[str, Any]
    order: list[str] | None  # the master view's row order, for the push that follows


def run(rc: RunContext, *, seed_snapshots: bool = False, legacy_root: Path | None = None) -> dict[str, Any]:
    """`nlead sheet pull`: take the lock, then pull (or adopt the sheets first with --seed-snapshots)."""
    with st.sheet_lock(rc.opts.env) as got:
        if not got:
            log.warning("sheet.pull.locked")
            return {"skipped": "another sheet sync is running"}
        stats: dict[str, Any] = {}
        if seed_snapshots:
            stats["seeded"] = seed(rc, legacy_root=legacy_root)
        stats.update(pull(rc).stats)
        return stats


def pull(rc: RunContext, *, api: gs.SheetsApi | None = None) -> PullResult:
    """Pull without taking the lock (the caller holds it)."""
    if db.get_setting("sheet_sync_enabled", True) is False:
        log.warning("sheet.pull.disabled")
        return PullResult({"skipped": "sheet_sync_enabled is false"}, None)
    api = api or gs.api()
    views = gs.targets()
    marks = st.states()
    legacy_ids = push.legacy_id_map()
    sheets: dict[str, dict[str, dict[str, str]]] = {}
    snapshots: dict[str, dict[str, dict[str, Any]]] = {}
    sheet_times: dict[str, dt.datetime] = {}
    skipped: dict[str, str] = {}
    order: list[str] | None = None
    for t in views:  # master view first: it wins conflicts between the sheets
        mark = marks.get(t.key, {})
        reason = _skip_reason(t, mark)
        if reason:
            skipped[t.key] = reason
            log.warning("sheet.pull.skipped", target=t.key, reason=reason)
            continue
        snap, _ = st.load_snapshot(t.key)
        if not snap:
            skipped[t.key] = "no snapshot yet: push first, or adopt it with --seed-snapshots"
            continue
        sheets[t.key], view_order = read_editable(api, t, legacy_ids)
        snapshots[t.key] = {k: st.editable(v) for k, v in snap.items()}
        sheet_times[t.key] = dt.datetime.fromisoformat(api.modified_time(t.spreadsheet_id).replace("Z", "+00:00"))
        if order is None:
            order = view_order
    seen = {lead_id for vals in sheets.values() for lead_id in vals}
    current = db_values(seen)
    res = resolve(sheets, snapshots, current, sheet_times, app_times(seen))
    stats: dict[str, Any] = {"read": {k: len(v) for k, v in sheets.items()}, "skipped_sheets": skipped}
    if rc.opts.dry_run:
        stats.update(
            would_change=len(res.changes),
            conflicts=len(res.conflicts),
            unknown_stages=len(res.unknown_stages),
            missing=len(res.missing),
            changes=[(c.lead_id, c.field, c.old, c.new, c.sheet) for c in res.changes[:20]],
        )
        log.info("sheet.pull.dry_run", **stats)
        return PullResult(stats, order)
    with db.tx("sheet", {"via": "pull"}) as conn:
        stats.update(apply(res, conn=conn))
    if res.changes and order:
        ctx = push.load_context()
        stats["next_steps_updated"] = push.refresh_next_steps(push.order_rows(push.load_rows(), order), ctx)
    log.info("sheet.pull.done", **stats)
    return PullResult(stats, order)


def _skip_reason(target: Target, mark: Mapping[str, Any]) -> str | None:
    if mark.get("spreadsheet_id") != target.spreadsheet_id:
        return "not adopted: this engine has not written this spreadsheet yet"
    if mark.get("state") != "ok":
        return f"last push incomplete (state {mark.get('state')!r}); the next push rebuilds it"
    return None


# ---------------------------------------------------------------------------
# Adopting sheets the old engine wrote (Step 20.6)
# ---------------------------------------------------------------------------
LEGACY_ROOT: Final = Path.home() / "Desktop" / "lead-engine"


def seed(rc: RunContext, *, legacy_root: Path | None = None, api: gs.SheetsApi | None = None) -> dict[str, Any]:
    """Adopt each sheet: record a baseline snapshot so the next pull can tell real edits apart.

    The baseline is what the old engine last wrote to that sheet (its own per-sheet snapshot file, D-045), so
    edits typed after the old engine's last run are still found and imported by the pull that follows. Leads
    the old snapshot does not cover take the values the sheet shows now (nothing to import for them, and a
    stale sheet can never undo anything). Writes no lead data.
    """
    api = api or gs.api()
    root = legacy_root or LEGACY_ROOT
    legacy_ids = push.legacy_id_map()
    stats: dict[str, Any] = {}
    for t in gs.targets():
        values, order = read_editable(api, t, legacy_ids)
        old = _old_snapshot(root / "data" / "cache" / f"sheet_snapshot_{t.view}.json", legacy_ids, t.money)
        known = set(db_values(values))
        snapshot = {}
        for pos, lead_id in enumerate(order):
            if lead_id not in known:
                continue
            base = old.get(lead_id) or values[lead_id]
            snapshot[lead_id] = {**{k: v for k, v in base.items() if not v.startswith("?")}, st.ROW_KEY: pos}
        stats[t.key] = {
            "rows": len(order),
            "seeded": len(snapshot),
            "from_old_snapshot": sum(1 for x in snapshot if x in old),
        }
        if rc.opts.dry_run:
            continue
        mark = {
            "state": "ok",
            "run_id": rc.run_id,
            "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "spreadsheet_id": t.spreadsheet_id,
            "rows": len(snapshot),
            "adopted": True,
        }
        with db.tx("sheet", {"sheet": t.key, "via": "seed"}) as conn:
            st.save_snapshot(t.key, snapshot, conn=conn)
            st.set_state(t.key, mark, conn=conn)
    log.info("sheet.seed.done", **stats)
    return stats


def _old_snapshot(path: Path, legacy_ids: Mapping[str, str], money: bool) -> dict[str, dict[str, str]]:
    """The old engine's per-sheet snapshot, converted to new ids and the new value format."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for old_id, vals in raw.items():
        lead_id = legacy_ids.get(old_id)
        if not lead_id or not isinstance(vals, dict):
            continue
        stage_text = str(vals.get("stage") or "")
        stage = d.LEGACY_LABELS.get(stage_text.strip().lower()) or d.canon_stage(stage_text)[0] or "new"
        conv = {"stage": stage, "notes": str(vals.get("notes") or "").strip()}
        for k in d.DATE_FIELDS:
            conv[k] = d.parse_date_cell(vals.get(k)) or ""
        if money:
            conv["deal_value_inr"] = d.parse_money_cell(vals.get("deal_value")) or ""
        out[lead_id] = conv
    return out
