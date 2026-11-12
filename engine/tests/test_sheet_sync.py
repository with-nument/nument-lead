"""Two-way sheet sync against a throwaway database and an in-memory Google Sheets (Step 13.11).

The staging spreadsheet holds both views in dev (13.3.1), so every test here exercises the master view (money)
and the caller view (no money) side by side.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.pipeline.runs import Options, RunContext
from nument_engine.sheet import client, pull, push, sync
from nument_engine.sheet import design as d
from nument_engine.sheet import state as st
from nument_engine.sheet.client import SheetsApiError, Target

from .sheets_fake import FakeSheets

BOOK = "staging-test-book"
MASTER = Target("staging_master", "master", BOOK)
CALLER = Target("staging_caller", "caller", BOOK, " (caller)")
PREFIX = "Sync Test"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def sheets(engine_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSheets]:
    monkeypatch.setenv("SHEET_STAGING_ID", BOOK)
    settings_module.get_settings.cache_clear()
    fake = FakeSheets()
    fake.add_book(BOOK)
    client.use_api(lambda: fake)
    saved = db.get_setting("sheet_state")
    with db.tx() as conn:
        conn.execute(
            "delete from public.leads where business_id in (select id from public.businesses where name like %s)",
            [f"{PREFIX}%"],
        )
        conn.execute("delete from public.businesses where name like %s", [f"{PREFIX}%"])
        conn.execute("delete from public.sheet_snapshots")
        conn.execute("delete from public.suppression where reason = 'wrong_contact'")
        conn.execute(
            'update public.settings set value = value || \'{"staging_master": {"state": "ok"}, '
            '"staging_caller": {"state": "ok"}}\'::jsonb where key = \'sheet_state\''
        )
    yield fake
    client.use_api(None)
    db.set_setting("sheet_state", saved)
    with db.tx() as conn:  # leave nothing behind for later test modules
        conn.execute("delete from public.sheet_snapshots")
        conn.execute(
            "delete from public.leads where business_id in (select id from public.businesses where name like %s)",
            [f"{PREFIX}%"],
        )
        conn.execute("delete from public.businesses where name like %s", [f"{PREFIX}%"])


def rc(dry_run: bool = False) -> RunContext:
    return RunContext(
        run_id=str(uuid.uuid4()),
        kind="sheet_sync",
        opts=Options(env="dev", dry_run=dry_run),
        started_at=dt.datetime.now(dt.UTC),
    )


def make_lead(
    name: str,
    *,
    stage: str = "new",
    grade: str = "A",
    total: int = 80,
    phone: str | None = None,
    phone_type: str = "mobile",
    email: str | None = None,
    deal: int | None = None,
    notes: str | None = None,
    wa_at: dt.date | None = None,
    message: str | None = "Hi Dr. Test, saw you are hiring a front desk executive. Is the phone busy?",
) -> str:
    tag = uuid.uuid4().hex[:8]
    phone = phone or f"+9198{int(tag, 16) % 10**8:08d}"
    with db.tx() as conn:
        biz = conn.execute(
            "insert into public.businesses (segment_id, name, norm_name, country, city, web_domain, website, status) "
            "values ('clinics-in', %s, %s, 'in', 'Pune', %s, %s, 'qualified') returning id::text as id",
            [f"{PREFIX} {name}", f"sync test {name.lower()}", f"{tag}.example.com", f"https://{tag}.example.com/"],
        ).fetchone()["id"]  # type: ignore[index]
        conn.execute(
            "insert into public.contacts (business_id, name, role, phone_e164, phone_type, email, source, source_url, "
            "is_decision_maker, verified, verified_at) values (%s, %s, 'Founder', %s, %s, %s, 'website', %s, true, true, now())",
            [biz, f"Dr. {name} Test", phone, phone_type, email, f"https://{tag}.example.com/contact"],
        )
        score = conn.execute(
            "insert into public.scores (business_id, version, fit, total, grade, pitch_mode, reasons, judge_note) "
            "values (%s, 's1.0', 3, %s, %s, 'visible_pain', %s, 'Hiring a front desk executive this week.') returning id::text as id",
            [
                biz,
                total,
                grade,
                db.Jsonb(
                    {
                        "fit": ["branches_count=3"],
                        "can_pay": ["price_point ₹40,000"],
                        "ticket_estimate": {"min": 100000, "max": 300000},
                        "risks": ["big chain?"],
                    }
                ),
            ],
        ).fetchone()["id"]  # type: ignore[index]
        conn.execute(
            "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, url, quote, details, dedupe_key) "
            "values (%s, 'hiring_frontdesk', 'visible_pain', 8, now() - interval '2 days', now() + interval '28 days', 'apna', %s, "
            "'Front desk executive needed', %s, %s)",
            [biz, f"https://apna.co/job/{tag}", db.Jsonb({"summary": "Hiring a front desk executive"}), f"test:{tag}"],
        )
        lead = conn.execute(
            "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, test_group, angle, message, "
            "stage, wa_at, deal_value_inr, notes) values (%s, 'clinics-in', %s, %s, 'visible_pain', "
            "'clinics-in:visible_pain:missed_calls', 'missed_calls', %s, %s, %s, %s, %s) returning id::text as id",
            [biz, score, grade, message, stage, wa_at, deal, notes],
        ).fetchone()["id"]  # type: ignore[index]
    return str(lead)


def lead_row(lead_id: str) -> dict[str, Any]:
    row = db.fetch_one("select * from public.leads where id = %s", [lead_id])
    assert row is not None
    return row


def activities(lead_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    sql = "select type, source, payload from public.activities where lead_id = %s"
    args: list[Any] = [lead_id]
    if kind:
        sql += " and type = %s"
        args.append(kind)
    return db.fetch_all(sql + " order by at", args)


def sheet_values(fake: FakeSheets, target: Target) -> dict[str, dict[str, str]]:
    values, _ = pull.read_editable(fake, target)
    return values


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------
def test_push_writes_both_views_atomically_and_snapshots_them(sheets: FakeSheets) -> None:
    a = make_lead("Alpha", deal=150000)
    b = make_lead("Beta", grade="B", total=60)
    stats = push.run(rc())
    titles = [t.title for t in sorted(sheets.books[BOOK].tabs.values(), key=lambda t: t.index)]
    assert titles == [
        "Today",
        "Pipeline",
        "Lead details",
        "Today (caller)",
        "Pipeline (caller)",
        "Lead details (caller)",
    ]
    assert len(sheets.batches) == 2  # one atomic batchUpdate per view
    marks = st.states()
    assert marks["staging_master"]["state"] == marks["staging_caller"]["state"] == "ok"
    assert marks["staging_master"]["spreadsheet_id"] == BOOK
    assert stats["views"]["staging_master"]["full"] is True
    for target in (MASTER, CALLER):
        snap, _ = st.load_snapshot(target.key)
        read = sheet_values(sheets, target)
        for lead_id in (a, b):
            assert read[lead_id] == st.editable(snap[lead_id])  # snapshot = what pull reads (13.6.2)
    assert sheet_values(sheets, MASTER)[a]["deal_value_inr"] == "150000"
    assert "deal_value_inr" not in sheet_values(sheets, CALLER)[a]


def test_caller_view_never_shows_money(sheets: FakeSheets) -> None:
    make_lead("Gamma", deal=250000)
    push.run(rc())
    for title in ("Today (caller)", "Pipeline (caller)", "Lead details (caller)"):
        tab = sheets.tab(BOOK, title)
        for cell in tab.cells.values():
            value = cell.get("userEnteredValue") or {}
            assert "₹" not in str(value.get("stringValue", "")) + str(value.get("formulaValue", "")), title
    headers = sheets.values(BOOK, "Pipeline (caller)")[1]
    assert "Deal value" not in headers and "Deal value" in sheets.values(BOOK, "Pipeline")[1]


def test_money_assertion_blocks_a_leak() -> None:
    with pytest.raises(AssertionError, match="money columns"):
        push.assert_no_money(CALLER, ["Company", "Deal value"], [])
    with pytest.raises(AssertionError, match="₹"):
        push.assert_no_money(CALLER, ["Company"], [[d.txt("₹3L")]])
    push.assert_no_money(MASTER, ["Deal value"], [[d.txt("₹3L")]])  # the master may show money
    assert (
        push.strip_money("Raised ₹10 Cr last month, budget Rs 2.5L and INR 50,000.") == "Raised last month, budget and."
    )


def test_estimate_shows_grey_and_is_not_an_edit(sheets: FakeSheets) -> None:
    lead = make_lead("Delta")
    push.run(rc())
    pipeline = sheets.values(BOOK, "Pipeline")
    col = pipeline[1].index("Deal value")
    row = next(r for r in pipeline if lead in r)
    assert row[col] == "₹1L to 3L"
    assert sheet_values(sheets, MASTER)[lead]["deal_value_inr"] == ""
    assert pull.pull(rc()).stats["fields_changed"] == 0


def test_push_keeps_row_order_and_appends_new_leads_best_first(sheets: FakeSheets) -> None:
    low = make_lead("Low", grade="B", total=56)
    high = make_lead("High", total=90)
    push.run(rc())
    _, order = pull.read_editable(sheets, MASTER)
    assert order.index(high) < order.index(low)
    # a person sorts the sheet by hand: low first. The order survives the next push.
    pushed = st.load_snapshot(MASTER.key)[0]
    assert pushed[high][st.ROW_KEY] < pushed[low][st.ROW_KEY]
    newest = make_lead("Newest", total=99)
    push.push(rc(), order=[low, high])
    _, order = pull.read_editable(sheets, MASTER)
    mine = [x for x in order if x in (low, high, newest)]
    assert mine == [low, high, newest]
    push.push(rc(), order=[low, high], resort=True)
    _, order = pull.read_editable(sheets, MASTER)
    assert [x for x in order if x in (low, high, newest)] == [newest, high, low]


def test_push_copies_next_step_and_due_into_the_database(sheets: FakeSheets) -> None:
    lead = make_lead("Echo", stage="contacted", wa_at=d.today_ist() - dt.timedelta(days=2))
    push.run(rc())
    row = lead_row(lead)
    assert row["next_step"] == "Call" and row["due_at"] == d.today_ist() - dt.timedelta(days=1)


def test_dry_run_writes_nothing(sheets: FakeSheets) -> None:
    make_lead("Foxtrot")
    stats = push.run(rc(dry_run=True))
    assert stats["rows"] >= 1 and stats["views"]["staging_master"]["requests"] > 10
    assert sheets.batches == [] and st.load_snapshot(MASTER.key)[0] == {}


def test_light_push_skips_lead_details_until_the_leads_change(sheets: FakeSheets) -> None:
    make_lead("Golf")
    push.run(rc())
    stats = push.run(rc(), light=True)
    assert stats["views"]["staging_master"]["full"] is False
    make_lead("Hotel")
    stats = push.run(rc(), light=True)
    assert stats["views"]["staging_master"]["full"] is True


def test_a_rejected_write_keeps_the_sheet_readable(sheets: FakeSheets) -> None:
    make_lead("India")
    push.run(rc())
    sheets.reject_next = 400  # Google refused the batch: nothing was applied
    with pytest.raises(SheetsApiError):
        push.run(rc())
    assert st.states()["staging_master"]["state"] == "ok"
    sheets.reject_next = 0  # no answer (timeout): we cannot know, so the sheet is rebuilt before it is read again
    with pytest.raises(SheetsApiError):
        push.run(rc())
    assert st.states()["staging_master"]["state"] == "writing"


def test_a_live_sheet_must_be_adopted_before_the_first_push(
    sheets: FakeSheets, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheets.add_book("old-sheet", ("Today", "Pipeline", "Lead details"))
    monkeypatch.setenv("SHEET_STAGING_ID", "old-sheet")
    settings_module.get_settings.cache_clear()
    with db.tx() as conn:
        conn.execute(
            "update public.settings set value = value - 'staging_master' - 'staging_caller' where key = 'sheet_state'"
        )
    with pytest.raises(push.SheetNotAdopted, match="seed-snapshots"):
        push.run(rc())
    assert sheets.batches == []


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------
def test_pull_after_push_changes_nothing(sheets: FakeSheets) -> None:
    make_lead("Juliet", stage="contacted", wa_at=dt.date(2026, 11, 12), notes="Called once")
    push.run(rc())
    stats = pull.pull(rc()).stats
    assert stats["fields_changed"] == 0 and stats["conflicts"] == 0 and stats["skipped_sheets"] == {}


def test_sheet_edits_reach_the_database_with_activities(sheets: FakeSheets) -> None:
    lead = make_lead("Kilo")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Stage", "talking")
    sheets.type_cell(BOOK, "Pipeline", lead, "WA", d.serial(dt.date(2026, 11, 12)))
    sheets.type_cell(BOOK, "Pipeline", lead, "Notes", "  Asked for a demo on Friday ")
    sheets.type_cell(BOOK, "Pipeline", lead, "Deal value", "₹1.2L")
    stats = pull.pull(rc()).stats
    row = lead_row(lead)
    assert (row["stage"], row["wa_at"], row["notes"], row["deal_value_inr"]) == (
        "talking", dt.date(2026, 11, 12), "Asked for a demo on Friday", Decimal("120000"))  # fmt: skip
    assert stats["fields_changed"] == 4
    changes = {
        a["payload"].get("field") or "stage": a for a in activities(lead) if a["type"] in ("edit", "stage_change")
    }
    assert changes["stage"]["type"] == "stage_change" and changes["stage"]["source"] == "sheet"
    assert changes["stage"]["payload"]["sheet"] == "staging_master"  # labelled through db.tx, written by the trigger
    assert changes["wa_at"]["payload"] == {"field": "wa_at", "from": "", "to": "2026-11-12", "sheet": "staging_master"}
    assert {a["type"] for a in activities(lead)} >= {"edit", "stage_change"}
    assert not [a for a in activities(lead) if a["type"] == "stage_change" and a["source"] != "sheet"]


def test_app_edit_that_is_newer_wins_and_the_sheet_value_is_logged(sheets: FakeSheets) -> None:
    lead = make_lead("Lima", notes="first")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Notes", "sheet note", at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))
    with db.tx() as conn:
        conn.execute("update public.leads set notes = 'app note' where id = %s", [lead])
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'app', 'edit', %s)",
            [lead, db.Jsonb({"field": "notes", "from": "first", "to": "app note"})],
        )
    pull.pull(rc())
    assert lead_row(lead)["notes"] == "app note"
    (conflict,) = activities(lead, "conflict_overridden")
    assert conflict["payload"]["lost"] == "sheet note" and conflict["payload"]["kept_from"] == "app"


def test_sheet_edit_that_is_newer_wins(sheets: FakeSheets) -> None:
    lead = make_lead("Mike", notes="first")
    push.run(rc())
    with db.tx() as conn:
        conn.execute("update public.leads set notes = 'app note' where id = %s", [lead])
        conn.execute(
            "insert into public.activities (lead_id, source, type, at, payload) values (%s, 'app', 'edit', now() - interval '2 hours', %s)",
            [lead, db.Jsonb({"field": "notes", "from": "first", "to": "app note"})],
        )
    sheets.type_cell(BOOK, "Pipeline", lead, "Notes", "sheet note")
    pull.pull(rc())
    assert lead_row(lead)["notes"] == "sheet note"
    (conflict,) = activities(lead, "conflict_overridden")
    assert conflict["payload"]["lost"] == "app note" and conflict["payload"]["lost_from"] == "app"


def test_master_wins_when_both_sheets_change_a_cell(sheets: FakeSheets) -> None:
    lead = make_lead("November")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Stage", "Talking")
    sheets.type_cell(BOOK, "Pipeline (caller)", lead, "Stage", "Not now")
    pull.pull(rc())
    assert lead_row(lead)["stage"] == "talking"
    (conflict,) = activities(lead, "conflict_overridden")
    assert (conflict["payload"]["lost"], conflict["payload"]["lost_from"]) == ("not_now", "staging_caller")


def test_a_stale_caller_sheet_cannot_undo_a_master_edit(sheets: FakeSheets) -> None:
    """The 12 Nov 2026 bug (D-045): the caller sheet was left behind and its old cells undid 13 stage changes."""
    lead = make_lead("Oscar")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Stage", "Contacted")
    pull.pull(rc())  # applied; the caller sheet was never pushed again, so it still says New
    assert lead_row(lead)["stage"] == "contacted"
    assert sheet_values(sheets, CALLER)[lead]["stage"] == "new"
    stats = pull.pull(rc()).stats
    assert stats["fields_changed"] == 0 and lead_row(lead)["stage"] == "contacted"


def test_a_sheet_left_half_written_is_never_read(sheets: FakeSheets) -> None:
    lead = make_lead("Papa", stage="contacted", wa_at=dt.date(2026, 11, 12))
    push.run(rc())
    with db.tx() as conn:  # a push crashed after marking the sheet: its cells may be blank
        st.set_state(MASTER.key, {**st.states(conn=conn)[MASTER.key], "state": "writing"}, conn=conn)
    sheets.tab(BOOK, "Pipeline").cells = {k: v for k, v in sheets.tab(BOOK, "Pipeline").cells.items() if k[0] < 2}
    stats = pull.pull(rc()).stats
    assert "staging_master" in stats["skipped_sheets"]
    assert lead_row(lead)["stage"] == "contacted"
    push.run(rc())  # the next push rebuilds it and marks it ok again
    assert st.states()[MASTER.key]["state"] == "ok"
    assert sheet_values(sheets, MASTER)[lead]["stage"] == "contacted"


def test_unknown_stage_is_logged_and_the_cell_corrects_itself(sheets: FakeSheets) -> None:
    lead = make_lead("Quebec", stage="talking")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Stage", "Maybe later")
    sync.run(rc())
    assert lead_row(lead)["stage"] == "talking"
    (unknown,) = activities(lead, "unknown_stage")
    assert unknown["payload"] == {"text": "Maybe later", "sheet": "staging_master"}
    assert sheet_values(sheets, MASTER)[lead]["stage"] == "talking"


def test_wrong_contact_retires_the_number(sheets: FakeSheets) -> None:
    lead = make_lead("Romeo", phone="+919800000777")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Stage", "Wrong contact")
    stats = pull.pull(rc()).stats
    assert stats["wrong_contacts"] == 1
    assert db.scalar("select reason from public.suppression where phone_e164 = '+919800000777'") == "wrong_contact"
    assert db.scalar(
        "select bool_and(do_not_contact) from public.contacts c join public.leads l on l.business_id = c.business_id where l.id = %s",
        [lead],
    )
    assert activities(lead, "wrong_contact")
    push.run(rc())  # the lead stays on the sheet (it was worked on), now without the retired number
    pipeline = sheets.values(BOOK, "Pipeline")
    row = next(r for r in pipeline if lead in r)
    assert "+91 98000 00777" not in row


def test_contacted_without_a_wa_date_means_sent_today(sheets: FakeSheets) -> None:
    lead = make_lead("Sierra")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Stage", "Contacted")
    sync.run(rc())
    assert lead_row(lead)["wa_at"] == d.today_ist()  # the database trigger fills it (17 Oct 2026 fix)
    assert sheet_values(sheets, MASTER)[lead]["wa_at"] == d.today_ist().isoformat()


def test_dry_run_pull_reports_and_changes_nothing(sheets: FakeSheets) -> None:
    lead = make_lead("Tango")
    push.run(rc())
    sheets.type_cell(BOOK, "Pipeline", lead, "Stage", "Talking")
    stats = pull.pull(rc(dry_run=True)).stats
    assert stats["would_change"] == 1 and lead_row(lead)["stage"] == "new"


def test_sync_disabled_by_the_kill_switch(sheets: FakeSheets) -> None:
    db.set_setting("sheet_sync_enabled", False)
    try:
        assert sync.run(rc())["push"] == {"skipped": "sheet_sync_enabled is false"}
        assert sheets.batches == []
    finally:
        db.set_setting("sheet_sync_enabled", True)


def test_seed_adopts_an_old_sheet_and_keeps_edits_made_after_the_old_engine(sheets: FakeSheets, tmp_path: Path) -> None:
    """Cutover (20.6): the old sheet carries old ids; its newest edits must survive the first new push."""
    edited, untouched = make_lead("Uniform", stage="contacted", wa_at=dt.date(2026, 11, 12)), make_lead("Victor")
    push.run(rc())
    for lead, old_id in ((edited, "A-0101"), (untouched, "A-0102")):  # make it look like the old engine's sheet
        sheets.type_cell(BOOK, "Pipeline", lead, "ID", old_id)
        sheets.type_cell(BOOK, "Pipeline (caller)", lead, "ID", old_id)
        with db.tx() as conn:
            conn.execute(
                "insert into public.source_records (source, source_key, business_id) "
                "select 'legacy', %s, business_id from public.leads where id = %s",
                [old_id, lead],
            )
    with db.tx() as conn:
        conn.execute("delete from public.sheet_snapshots")
        conn.execute(
            "update public.settings set value = value - 'staging_master' - 'staging_caller' where key = 'sheet_state'"
        )
    cache = tmp_path / "data" / "cache"
    cache.mkdir(parents=True)
    old = {
        "stage": "Contacted",
        "notes": "",
        "wa_at": "2026-11-12",
        "call_at": "",
        "d3_at": "",
        "d7_at": "",
        "meeting_at": "",
        "deal_value": "",
    }
    new = {**old, "stage": "New", "wa_at": ""}
    for view in ("master", "caller"):
        (cache / f"sheet_snapshot_{view}.json").write_text(json.dumps({"A-0101": old, "A-0102": new}))
    sheets.type_cell(BOOK, "Pipeline", "A-0101", "Stage", "Talking")  # typed after the old engine's last run
    stats = pull.run(rc(), seed_snapshots=True, legacy_root=tmp_path)
    assert stats["seeded"]["staging_master"]["from_old_snapshot"] == 2
    assert lead_row(edited)["stage"] == "talking" and lead_row(untouched)["stage"] == "new"
    push.run(rc())  # the first new push: ids become uuids, nothing is lost
    assert sheet_values(sheets, MASTER)[edited]["stage"] == "talking"


# ---------------------------------------------------------------------------
# Conflict rules, case by case (13.7.3), with fixed values and times
# ---------------------------------------------------------------------------
T0 = dt.datetime(2026, 11, 12, 10, 0, tzinfo=dt.UTC)
L = "00000000-0000-0000-0000-000000000001"


def _resolve(master: str | None, caller: str | None, snap: str, db_value: str, *, sheet_at: dt.datetime = T0,
             app_at: dt.datetime | None = None) -> pull.Resolution:  # fmt: skip
    sheets_in = {}
    snaps = {}
    for key, value in (("master", master), ("caller", caller)):
        if value is not None:
            sheets_in[key] = {L: {"notes": value}}
            snaps[key] = {L: {"notes": snap}}
    app = {(L, "notes"): app_at} if app_at else {}
    return pull.resolve(sheets_in, snaps, {L: {"notes": db_value}}, {"master": sheet_at, "caller": sheet_at}, app)


def test_case_1_nothing_changed() -> None:
    r = _resolve("a", "a", "a", "a")
    assert not r.changes and not r.conflicts


def test_case_2_sheet_edit_only() -> None:
    r = _resolve("b", "a", "a", "a")
    assert [(c.new, c.sheet) for c in r.changes] == [("b", "master")] and not r.conflicts


def test_case_3_app_edit_only() -> None:
    r = _resolve("a", "a", "a", "z")
    assert not r.changes and not r.conflicts


def test_case_4_same_edit_both_sides() -> None:
    r = _resolve("z", "a", "a", "z")
    assert not r.changes and not r.conflicts


def test_case_5_most_recent_wins() -> None:
    newer_sheet = _resolve("b", None, "a", "z", sheet_at=T0, app_at=T0 - dt.timedelta(minutes=5))
    assert [c.new for c in newer_sheet.changes] == ["b"] and newer_sheet.conflicts[0].lost == "z"
    newer_app = _resolve("b", None, "a", "z", sheet_at=T0, app_at=T0 + dt.timedelta(minutes=5))
    assert not newer_app.changes and newer_app.conflicts[0].lost == "b" and newer_app.conflicts[0].kept == "z"


def test_case_6_master_beats_caller() -> None:
    r = _resolve("m", "c", "a", "a")
    assert [c.new for c in r.changes] == ["m"]
    assert [(x.lost, x.lost_from, x.reason) for x in r.conflicts] == [("c", "caller", "master_wins")]


def test_case_7_unknown_stage() -> None:
    r = pull.resolve(
        {"master": {L: {"stage": "?Maybe later"}}}, {"master": {L: {"stage": "new"}}}, {L: {"stage": "new"}}, {}, {}
    )
    assert not r.changes and r.unknown_stages == [(L, "master", "Maybe later")]


def test_case_8_lead_missing_in_database() -> None:
    r = pull.resolve({"master": {L: {"notes": "x"}}}, {"master": {L: {"notes": ""}}}, {}, {}, {})
    assert r.missing == [L] and not r.changes


def test_a_lead_without_a_snapshot_row_is_never_guessed() -> None:
    r = pull.resolve({"master": {L: {"notes": "x"}}}, {"master": {}}, {L: {"notes": ""}}, {}, {})
    assert not r.changes


def test_check_reports_reachability_and_adoption(sheets: FakeSheets, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = client.check_targets(sheets, st.states())
    assert [(r["target"], r["ok"], r["adopted"]) for r in rows] == [
        ("staging_master", True, False),
        ("staging_caller", True, False),
    ]
    assert "first `nlead sheet sync`" in rows[0]["next"]
    push.run(rc())
    assert all(r["adopted"] and r["state"] == "ok" for r in client.check_targets(sheets, st.states()))
    monkeypatch.setenv("SHEET_STAGING_ID", "not-shared")
    settings_module.get_settings.cache_clear()
    missing, _ = client.check_targets(sheets, st.states())
    assert missing["ok"] is False and "as Editor" in missing["fix"]


def test_a_prod_run_without_a_sheet_skips_the_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Founder, 12 Nov: the old sheets stay as they are; with no sheet ids the web app is the only view."""
    from datetime import UTC, datetime

    from nument_engine.pipeline.runs import Options, RunContext
    from nument_engine.sheet import client as gs
    from nument_engine.sheet import sync

    monkeypatch.setattr(gs, "targets", lambda settings=None: [])
    rc = RunContext(run_id="r1", kind="morning", opts=Options(env="prod"), started_at=datetime.now(UTC))
    assert sync.run(rc)["skipped"].startswith("no sheet configured")
