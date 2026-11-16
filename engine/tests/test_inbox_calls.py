"""The Inbox, Calls and conversation functions of the web app (0033).

Every check runs as an API role with a user's JWT claims, the way PostgREST calls the functions, against the
throwaway test database, and is rolled back. Other tests may have committed rows into the same database, so the
counts are compared before and after a test seeds its own rows, and items are looked up by id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from .helpers import Conn, RlsWorld, act_as

IST = ZoneInfo("Asia/Kolkata")
FUNCTIONS = {
    "inbox_page(text,timestamp with time zone,uuid,integer)": "s",
    "calls_page()": "s",
    "lead_conversation(uuid)": "s",
    "review_message(uuid,text,text,text)": "v",
    "save_call_notes(uuid,text)": "v",
}


def _one(conn: Conn, query: str, params: list[Any] | None = None) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return next(iter(row.values()))


def _lead(conn: Conn, *, stage: str = "contacted", meeting_at: datetime | None = None) -> tuple[str, str, str]:
    """A startup lead with a founder contact. Returns (lead id, business id, contact id)."""
    tag = uuid.uuid4().hex[:10]
    biz = _one(
        conn,
        "insert into public.businesses (segment_id, name, norm_name, country, city, web_domain) "
        "values ('clinics-in', %s, %s, 'in', 'Bengaluru', %s) returning id",
        [f"Leafline {tag}", f"leafline {tag}", f"leafline-{tag}.example.com"],
    )
    contact = _one(
        conn,
        "insert into public.contacts (business_id, name, role, email, source, is_decision_maker, line) "
        "values (%s, 'Maya Rao', 'Co-founder', %s, 'website', true, 'owner') returning id",
        [biz, f"maya@leafline-{tag}.example.com"],
    )
    lead = _one(
        conn,
        "insert into public.leads (business_id, segment_id, grade, pitch_mode, message) "
        "values (%s, 'clinics-in', 'A', 'visible_pain', 'Hi Maya') returning id",
        [biz],
    )
    conn.execute("update public.leads set stage = %s, meeting_at = %s where id = %s", [stage, meeting_at, lead])
    return str(lead), str(biz), str(contact)


def _thread(conn: Conn, lead: str, contact: str) -> str:
    return str(
        _one(
            conn,
            "insert into public.email_threads (lead_id, contact_id, to_email, to_domain) "
            "values (%s, %s, 'maya@leafline.example.com', 'leafline.example.com') returning id",
            [lead, contact],
        )
    )


def _msg(conn: Conn, thread: str, direction: str, status: str, *, step: int | None = None, at: datetime | None = None,
         body: str = "Hello", subject: str | None = None, **cols: Any) -> str:  # fmt: skip
    values = {"thread_id": thread, "direction": direction, "status": status, "step": step, "body": body,
              "subject": subject, **cols}  # fmt: skip
    if at is not None:
        values.update(sent_at=at, created_at=at, updated_at=at)
    return str(
        _one(
            conn,
            f"insert into public.email_messages ({', '.join(values)}) values ({', '.join(['%s'] * len(values))}) "
            "returning id",
            list(values.values()),
        )
    )


def _inbox(conn: Conn, tab: str, **kw: Any) -> Any:
    return _one(
        conn,
        "select public.inbox_page(%s, %s, %s, %s)",
        [tab, kw.get("cursor_at"), kw.get("cursor_id"), kw.get("page_size", 200)],
    )


def _keys(page: Any) -> set[str]:
    return {i["key"] for i in page["items"]}


# ---------------------------------------------------------------------------
# Who may call what
# ---------------------------------------------------------------------------


def test_functions_run_as_the_user_and_only_signed_in_users_may_call_them(db_conn: Conn) -> None:
    rows = db_conn.execute(
        "select p.oid::regprocedure::text as fn, p.prosecdef as definer, p.provolatile as volatility "
        "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public'"
    ).fetchall()
    found = {r["fn"].removeprefix("public."): r for r in rows}
    for fn, volatility in FUNCTIONS.items():
        assert fn in found, fn
        assert found[fn]["volatility"] == volatility, fn
        assert not found[fn]["definer"], fn  # security invoker: RLS applies
        assert _one(db_conn, "select has_function_privilege('authenticated', %s, 'EXECUTE')", [f"public.{fn}"]), fn
        assert not _one(db_conn, "select has_function_privilege('anon', %s, 'EXECUTE')", [f"public.{fn}"]), fn
    act_as(db_conn, "anon")
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("select public.inbox_page()")


def test_viewers_see_no_email(db_conn: Conn, rls_world: RlsWorld) -> None:
    lead, _, contact = _lead(db_conn)
    thread = _thread(db_conn, lead, contact)
    _msg(db_conn, thread, "out", "review", step=0)
    act_as(db_conn, "authenticated", rls_world.viewer)
    page = _inbox(db_conn, "review")
    assert page["counts"] == {"replies": 0, "review": 0, "done": 0} and page["items"] == []
    conv = _one(db_conn, "select public.lead_conversation(%s)", [lead])
    assert conv["messages"] == [] and conv["thread"] is None and conv["plan_pages"] == []


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


def test_inbox_tabs_sort_replies_drafts_and_done(db_conn: Conn, rls_world: RlsWorld) -> None:
    act_as(db_conn, "authenticated", rls_world.caller)
    before = _inbox(db_conn, "replies")["counts"]
    db_conn.execute("reset role")

    now = datetime.now(UTC)
    lead, _, contact = _lead(db_conn)
    thread = _thread(db_conn, lead, contact)
    day0 = _msg(db_conn, thread, "out", "sent", step=0, at=now - timedelta(days=6), subject="WhatsApp orders")
    _msg(db_conn, thread, "out", "cancelled", step=3, error="replied", at=now - timedelta(hours=2))  # the engine's
    answer = _msg(db_conn, thread, "in", "received", at=now - timedelta(hours=3), body="Open to a call",
                  classification="interested", classification_confidence=0.93, suggested_reply="Hi Maya, ...")  # fmt: skip
    draft = _msg(db_conn, thread, "out", "review", body="Hi Maya, Thursday?", at=now - timedelta(hours=2))

    lead2, _, contact2 = _lead(db_conn, stage="new")
    thread2 = _thread(db_conn, lead2, contact2)
    review = _msg(db_conn, thread2, "out", "review", step=0, subject="Quick question")
    _msg(db_conn, thread2, "out", "draft", step=3)  # drafts wait for the engine, not for a person

    lead3, _, contact3 = _lead(db_conn)
    thread3 = _thread(db_conn, lead3, contact3)
    _msg(db_conn, thread3, "out", "sent", step=0, at=now - timedelta(days=2))
    _msg(db_conn, thread3, "in", "received", at=now - timedelta(days=1), classification="out_of_office")
    ooo_thread_sent = _msg(db_conn, thread3, "out", "cancelled", step=7, at=now - timedelta(hours=1))  # by a person

    act_as(db_conn, "authenticated", rls_world.caller)
    replies = _inbox(db_conn, "replies")
    assert replies["counts"]["replies"] == before["replies"] + 1
    assert replies["counts"]["review"] == before["review"] + 1
    assert replies["counts"]["done"] == before["done"] + 3  # two sent, one cancelled by a person
    item = next(i for i in replies["items"] if i["key"] == answer)
    assert item["lead_id"] == lead and item["contact_name"] == "Maya Rao" and item["contact_role"] == "Co-founder"
    assert item["inbound"]["classification"] == "interested" and item["inbound"]["body"] == "Open to a call"
    assert item["draft"]["id"] == draft and item["draft"]["status"] == "review" and item["draft"]["step"] is None
    assert item["last_out"]["id"] == day0 and item["last_out"]["subject"] == "WhatsApp orders"
    assert item["grade"] == "A" and item["stage"] == "contacted" and item["city"] == "Bengaluru"

    review_page = _inbox(db_conn, "review")
    assert review in _keys(review_page) and draft not in _keys(review_page)
    r = next(i for i in review_page["items"] if i["key"] == review)
    assert r["draft"]["subject"] == "Quick question" and r["inbound"] is None

    done = _inbox(db_conn, "done")
    assert {day0, ooo_thread_sent} <= _keys(done)

    # Approving the reply moves the answer from Replies to Done.
    _one(db_conn, "select public.review_message(%s, 'approve')", [draft])
    after = _inbox(db_conn, "replies")
    assert answer not in _keys(after) and after["counts"]["replies"] == before["replies"]
    done_item = next(i for i in _inbox(db_conn, "done")["items"] if i["key"] == draft)
    assert done_item["draft"]["status"] == "approved" and done_item["inbound"]["id"] == answer


def test_inbox_pages_with_a_cursor(db_conn: Conn, rls_world: RlsWorld) -> None:
    lead, _, contact = _lead(db_conn, stage="new")
    future = datetime.now(UTC) + timedelta(days=3650)  # newer than anything another test committed
    ids = []
    for n in range(5):
        lead_n, _, contact_n = (lead, None, contact) if n == 0 else _lead(db_conn, stage="new")
        thread = _thread(db_conn, lead_n, contact_n)
        ids.append(_msg(db_conn, thread, "out", "review", step=0, created_at=future - timedelta(minutes=n)))
    act_as(db_conn, "authenticated", rls_world.admin)
    first = _inbox(db_conn, "review", page_size=2)
    assert [i["key"] for i in first["items"]] == ids[:2]
    cur = first["next_cursor"]
    second = _inbox(db_conn, "review", page_size=2, cursor_at=cur["at"], cursor_id=cur["id"])
    assert [i["key"] for i in second["items"]] == ids[2:4]
    with pytest.raises(errors.InvalidParameterValue), db_conn.transaction():
        _inbox(db_conn, "spam")


# ---------------------------------------------------------------------------
# review_message
# ---------------------------------------------------------------------------


def test_review_message_approves_edits_cancels_but_never_sends(db_conn: Conn, rls_world: RlsWorld) -> None:
    lead, _, contact = _lead(db_conn, stage="new")
    thread = _thread(db_conn, lead, contact)
    m = _msg(db_conn, thread, "out", "review", step=0, subject="Old", body="Old body")
    sent = _msg(db_conn, thread, "out", "sent", step=3, at=datetime.now(UTC))
    received = _msg(db_conn, thread, "in", "received", at=datetime.now(UTC))
    act_as(db_conn, "authenticated", rls_world.caller)

    out = _one(db_conn, "select public.review_message(%s, 'edit', %s, %s)", [m, "New", "New body"])
    assert (out["status"], out["subject"], out["body"]) == ("review", "New", "New body")
    out = _one(db_conn, "select public.review_message(%s, 'approve')", [m])
    assert out["status"] == "approved" and out["body"] == "New body"
    out = _one(db_conn, "select public.review_message(%s, 'reopen')", [m])
    assert out["status"] == "review"
    out = _one(db_conn, "select public.review_message(%s, 'approve', null, %s)", [m, "Final"])
    assert out["status"] == "approved" and out["body"] == "Final" and out["subject"] == "New"
    out = _one(db_conn, "select public.review_message(%s, 'cancel')", [m])
    assert out["status"] == "cancelled"

    for target, action in ((m, "approve"), (m, "edit"), (sent, "edit"), (sent, "cancel"), (received, "approve")):
        with pytest.raises(errors.NoDataFound), db_conn.transaction():
            db_conn.execute("select public.review_message(%s, %s)", [target, action])
    with pytest.raises(errors.InvalidParameterValue), db_conn.transaction():
        db_conn.execute("select public.review_message(%s, 'send')", [m])
    db_conn.execute("reset role")
    assert _one(db_conn, "select status from public.email_messages where id = %s", [sent]) == "sent"

    # A viewer cannot change anything (RLS hides the row).
    m2 = _msg(db_conn, thread, "out", "review", step=7)
    act_as(db_conn, "authenticated", rls_world.viewer)
    with pytest.raises(errors.NoDataFound), db_conn.transaction():
        db_conn.execute("select public.review_message(%s, 'approve')", [m2])


# ---------------------------------------------------------------------------
# Calls and call notes
# ---------------------------------------------------------------------------


def test_calls_page_groups_by_india_day_with_brief_offer_and_plan(db_conn: Conn, rls_world: RlsWorld) -> None:
    now_ist = datetime.now(IST)
    today_at = now_ist.replace(hour=23, minute=50, second=0, microsecond=0)
    lead_today, _, _ = _lead(db_conn, stage="discovery_booked", meeting_at=today_at)
    lead_next, _, _ = _lead(db_conn, stage="discovery_booked", meeting_at=today_at + timedelta(days=2))
    lead_past, _, _ = _lead(db_conn, stage="discovery_done", meeting_at=today_at - timedelta(days=3))
    lead_old, _, _ = _lead(db_conn, stage="discovery_done", meeting_at=today_at - timedelta(days=40))
    db_conn.execute(
        "insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'booking', %s), "
        "(%s, 'engine', 'brief', %s)",
        [lead_today, Jsonb({"kind": "booked", "location": "https://meet.google.com/abc", "notes": "Contracts"}),
         lead_today, Jsonb({"meeting_at": today_at.isoformat(), "content": {"summary": "Two lawyers", "questions": ["a"]}})],
    )  # fmt: skip
    db_conn.execute(
        "insert into public.lead_offers (lead_id, rank, offer_key, why_now) values (%s, 1, 'mvp_sprint', 'Raised')",
        [lead_today],
    )
    db_conn.execute(
        "insert into public.plan_pages (token, lead_id, content, views, last_viewed_at) values (%s, %s, '{}', 2, now())",
        [uuid.uuid4().hex, lead_today],
    )
    act_as(db_conn, "authenticated", rls_world.caller)
    page = _one(db_conn, "select public.calls_page()")
    ids = {k: [c["lead_id"] for c in page[k]] for k in ("today", "upcoming", "earlier")}
    assert lead_today in ids["today"] and lead_next in ids["upcoming"] and lead_past in ids["earlier"]
    assert lead_old not in ids["earlier"]
    call = next(c for c in page["today"] if c["lead_id"] == lead_today)
    assert call["contact_name"] == "Maya Rao" and call["booking"]["location"] == "https://meet.google.com/abc"
    assert call["brief"]["content"]["summary"] == "Two lawyers"
    assert call["offer"]["key"] == "mvp_sprint" and call["offer"]["why_now"] == "Raised"
    assert call["plan"]["views"] == 2 and call["proposal"] is None
    assert next(c for c in page["upcoming"] if c["lead_id"] == lead_next)["plan"] is None


def test_call_notes_start_one_draft_proposal(db_conn: Conn, rls_world: RlsWorld) -> None:
    lead, _, _ = _lead(db_conn, stage="discovery_booked", meeting_at=datetime.now(UTC))
    act_as(db_conn, "authenticated", rls_world.caller)
    first = _one(db_conn, "select public.save_call_notes(%s, %s)", [lead, "  NDAs first, 6 weeks  "])
    assert first["created"] is True and first["drafted"] is False
    again = _one(db_conn, "select public.save_call_notes(%s, %s)", [lead, "NDAs and service agreements"])
    assert again["id"] == first["id"] and again["created"] is False
    row = db_conn.execute("select status, content, call_notes from public.proposals where lead_id = %s", [lead]).fetchall()
    assert row == [{"status": "draft", "content": {}, "call_notes": "NDAs and service agreements"}]
    page = _one(db_conn, "select public.calls_page()")
    call = next(c for k in ("today", "upcoming", "earlier") for c in page[k] if c["lead_id"] == lead)
    assert call["proposal"]["call_notes"] == "NDAs and service agreements" and call["proposal"]["drafted"] is False
    with pytest.raises(errors.InvalidParameterValue), db_conn.transaction():
        db_conn.execute("select public.save_call_notes(%s, '  ')", [lead])
    # A person may start a draft but never write the content or skip the review.
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("insert into public.proposals (lead_id, content) values (%s, '{\"a\": 1}')", [lead])
    act_as(db_conn, "authenticated", rls_world.viewer)
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("select public.save_call_notes(%s, 'x')", [lead])


# ---------------------------------------------------------------------------
# A lead's conversation
# ---------------------------------------------------------------------------


def test_lead_conversation_has_everything_in_order(db_conn: Conn, rls_world: RlsWorld) -> None:
    now = datetime.now(UTC)
    lead, biz, contact = _lead(db_conn)
    thread = _thread(db_conn, lead, contact)
    a = _msg(db_conn, thread, "out", "sent", step=0, at=now - timedelta(days=3))
    b = _msg(db_conn, thread, "in", "received", at=now - timedelta(days=1), classification="question")
    c = _msg(db_conn, thread, "out", "review", at=now)
    db_conn.execute(
        "insert into public.startup_profiles (business_id, is_startup, team_size, tech_team, evidence) "
        "values (%s, true, 3, 'none', %s)",
        [biz, Jsonb({"tech_team": {"ids": ["f1"], "why": "no engineers on the team page"}})],
    )
    db_conn.execute(
        "insert into public.lead_offers (lead_id, rank, offer_key) values (%s, 1, 'mvp_sprint'), (%s, 2, 'ai_feature')",
        [lead, lead],
    )
    act_as(db_conn, "authenticated", rls_world.caller)
    conv = _one(db_conn, "select public.lead_conversation(%s)", [lead])
    assert [m["id"] for m in conv["messages"]] == [a, b, c]
    assert conv["thread"]["id"] == thread and conv["thread"]["status"] == "open" and conv["threads"] == 1
    assert [o["key"] for o in conv["offers"]] == ["mvp_sprint", "ai_feature"]
    assert conv["offers"][0]["name"] == "MVP sprint"
    assert conv["startup_profile"]["team_size"] == 3
    assert conv["startup_profile"]["evidence"]["tech_team"]["why"] == "no engineers on the team page"
    assert conv["briefs"] == [] and conv["proposals"] == [] and conv["plan_pages"] == []
    assert _one(db_conn, "select public.lead_conversation(%s)", [str(uuid.uuid4())]) is None
