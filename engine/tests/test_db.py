"""Database helpers (db.py) against the test database, through the real connection pool."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from nument_engine import db


def _key() -> str:
    return f"test.{uuid.uuid4().hex[:10]}"


def test_pool_uses_the_session_settings(engine_db: str) -> None:
    row = db.fetch_one(
        "select current_setting('statement_timeout') as timeout, current_setting('TimeZone') as tz, "
        "current_setting('application_name') as app"
    )
    assert row == {"timeout": "2min", "tz": "UTC", "app": "nlead-dev"}


def test_fetch_helpers(engine_db: str) -> None:
    assert db.scalar("select 41 + %s", [1]) == 42
    assert db.scalar("select 1 where false") is None
    assert db.fetch_one("select 1 as n where false") is None
    assert db.fetch_all("select n from generate_series(1, 3) as n") == [{"n": 1}, {"n": 2}, {"n": 3}]


def test_settings_round_trip(engine_db: str) -> None:
    key = _key()
    try:
        assert db.get_setting(key, default="fallback") == "fallback"
        db.set_setting(key, {"a": 1, "b": [1, 2]})
        assert db.get_setting(key) == {"a": 1, "b": [1, 2]}
        db.set_setting(key, 5)
        assert db.get_setting(key) == 5
        assert db.get_setting("daily_cap_inr") == 750
    finally:
        db.execute("delete from public.settings where key = %s", [key])


def test_upsert_inserts_updates_and_wraps_json(engine_db: str) -> None:
    sources = [f"test_{uuid.uuid4().hex[:8]}" for _ in range(2)]
    try:
        rows = [{"source": s, "enabled": True, "last_error": None} for s in sources]
        assert db.upsert("source_health", rows, conflict=["source"]) == []
        out = db.upsert(
            "public.source_health",
            [{"source": sources[0], "enabled": False, "last_error": "blocked"}],
            conflict=["source"],
            returning="source, enabled",
        )
        assert out == [{"source": sources[0], "enabled": False}]
        # update=[] means DO NOTHING
        db.upsert("source_health", [{"source": sources[1], "enabled": False}], conflict=["source"], update=[])
        got = {
            r["source"]: r["enabled"]
            for r in db.fetch_all("select source, enabled from public.source_health where source = any(%s)", [sources])
        }
        assert got == {sources[0]: False, sources[1]: True}
        key = _key()
        db.upsert("settings", [{"key": key, "value": {"nested": [1, {"x": True}]}}], conflict=["key"])
        assert db.get_setting(key) == {"nested": [1, {"x": True}]}
        db.execute("delete from public.settings where key = %s", [key])
    finally:
        db.execute("delete from public.source_health where source = any(%s)", [sources])


def test_upsert_validates_input(engine_db: str) -> None:
    assert db.upsert("settings", [], conflict=["key"]) == []
    with pytest.raises(ValueError, match="same keys"):
        db.upsert("settings", [{"key": "a", "value": 1}, {"key": "b"}], conflict=["key"])
    with pytest.raises(ValueError, match="bad table name"):
        db.upsert("a.b.c", [{"key": "a"}], conflict=["key"])
    with pytest.raises(ValueError, match="conflict column"):
        db.upsert("settings", [{"key": "a"}], conflict=[])


def test_tx_commits_rolls_back_and_tags_the_source(engine_db: str) -> None:
    key = _key()
    with pytest.raises(RuntimeError), db.tx() as conn:
        db.set_setting(key, 1, conn=conn)
        raise RuntimeError("boom")
    assert db.get_setting(key) is None  # rolled back
    with db.tx(source="sheet", context={"sheet": "master"}) as conn:
        assert db.scalar("select current_setting('app.source')", conn=conn) == "sheet"
        assert db.scalar("select current_setting('app.context')::jsonb", conn=conn) == {"sheet": "master"}
    with db.tx() as conn:  # defaults: engine, empty context
        assert db.scalar("select current_setting('app.source')", conn=conn) == "engine"
        assert db.scalar("select current_setting('app.context')::jsonb", conn=conn) == {}
    assert db.scalar("select current_setting('app.source', true)") in (None, "")  # transaction-local only


def test_sheet_writes_label_the_lead_timeline(engine_db: str) -> None:
    """Step 13 writes with db.tx(source="sheet", context=...); the trigger records both (A.13.5 rule 1)."""
    with db.tx() as conn:
        biz = db.scalar(
            "insert into public.businesses (segment_id, name, norm_name, country) "
            "values ('clinics-in', 'Tx Clinic', 'tx clinic', 'in') returning id",
            conn=conn,
        )
        lead = db.scalar(
            "insert into public.leads (business_id, segment_id, grade, pitch_mode) "
            "values (%s, 'clinics-in', 'B', 'fit_only') returning id",
            [biz],
            conn=conn,
        )
    try:
        db.execute(
            "update public.leads set stage = 'talking' where id = %s",
            [lead],
            source="sheet",
            context={"sheet": "caller"},
        )
        row = db.fetch_one(
            "select source, payload from public.activities where lead_id = %s and type = 'stage_change'", [lead]
        )
        assert row == {"source": "sheet", "payload": {"from": "new", "to": "talking", "sheet": "caller"}}
    finally:
        db.execute("delete from public.leads where id = %s", [lead])
        db.execute("delete from public.businesses where id = %s", [biz])


def test_execute_returns_rowcount(engine_db: str) -> None:
    key = _key()
    db.set_setting(key, 1)
    assert db.execute("update public.settings set value = '2' where key = %s", [key]) == 1
    assert db.execute("delete from public.settings where key = %s", [key]) == 1


def test_errors_surface(engine_db: str) -> None:
    with pytest.raises(psycopg.errors.UndefinedTable):
        db.fetch_all("select * from public.no_such_table")
