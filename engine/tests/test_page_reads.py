"""The web app's one-call-per-page functions (0024) and the access token hook (0023).

Every check runs as an API role with a user's JWT claims, the way PostgREST calls the functions, against the
throwaway test database. Other tests may have committed rows into the same database, so the numbers are compared
with the queries the pages used to make (run in the same transaction, as the same user), and the rows a test
seeds are looked up by id. Each test's work is rolled back.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from .helpers import Conn, RlsWorld, act_as

IST = ZoneInfo("Asia/Kolkata")
CLOSED = ("won", "retainer", "lost", "not_now", "not_a_fit", "wrong_contact")
OPEN = ("contacted", "talking", "discovery_booked", "discovery_done", "proposal_sent")

PAGE_FUNCTIONS = {
    "home_summary(integer)",
    "nav_counts()",
    "lead_detail(uuid,boolean)",
    "deals_board(jsonb,integer,integer)",
    "leads_page(jsonb,integer,integer)",
    "search_leads(text,integer)",
    "insights_summary(timestamp with time zone,timestamp with time zone,jsonb)",
    "engine_counts()",
}


def _today() -> date:
    return datetime.now(IST).date()


def _one(conn: Conn, query: str, params: list[Any] | None = None) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return next(iter(row.values()))


def _call(conn: Conn, query: str, params: list[Any] | None = None) -> Any:
    """A function's jsonb result, decoded."""
    return _one(conn, query, params)


def _business(conn: Conn, *, name: str | None = None, city: str = "Pune", country: str = "in", **cols: Any) -> str:
    tag = uuid.uuid4().hex[:10]
    values = {
        "segment_id": f"clinics-{country}",
        "name": name or f"Page Read Clinic {tag}",
        "norm_name": (name or f"page read clinic {tag}").lower(),
        "country": country,
        "city": city,
        "web_domain": f"pr-{tag}.example.com",
        **cols,
    }
    row = conn.execute(
        f"insert into public.businesses ({', '.join(values)}) values ({', '.join(['%s'] * len(values))}) returning id",
        list(values.values()),
    ).fetchone()
    assert row is not None
    return str(row["id"])


def _lead(
    conn: Conn,
    *,
    stage: str = "new",
    grade: str = "A",
    total: float = 100,
    phone: str | None = "+919822200001",
    phone_type: str = "mobile",
    signal: bool = True,
    business: dict[str, Any] | None = None,
    **cols: Any,
) -> tuple[str, str]:
    """A scored lead (stage set after insert, as the app does), with a contact and an active signal."""
    biz = _business(conn, **(business or {}))
    if phone:
        conn.execute(
            "insert into public.contacts (business_id, name, phone_e164, phone_type, source, verified) "
            "values (%s, 'Reception', %s, %s, 'website', true)",
            [biz, phone, phone_type],
        )
    if signal:
        conn.execute(
            "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, quote, "
            "dedupe_key) values (%s, 'hiring_frontdesk', 'visible_pain', 8, now() - interval '2 days', "
            "now() + interval '28 days', 'apna', 'Hiring a front desk executive', %s)",
            [biz, f"apna:page-reads:{biz}"],
        )
    score = conn.execute(
        "insert into public.scores (business_id, version, fit, total, grade, pitch_mode) "
        "values (%s, 's1.0', 3, %s, %s, 'visible_pain') returning id",
        [biz, total, grade],
    ).fetchone()
    assert score is not None
    lead = conn.execute(
        "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, message, followup_d3, followup_d7) "
        "values (%s, %s, %s, %s, 'visible_pain', 'Hi there', 'Day 3 text', 'Day 7 text') returning id",
        [biz, f"clinics-{(business or {}).get('country', 'in')}", score["id"], grade],
    ).fetchone()
    assert lead is not None
    lead_id = str(lead["id"])
    updates = {"stage": stage, **cols} if stage != "new" or cols else {}
    if updates:
        sets = ", ".join(f"{k} = %s" for k in updates)
        conn.execute(f"update public.leads set {sets} where id = %s", [*updates.values(), lead_id])
    return lead_id, biz


def _seed_today(conn: Conn) -> dict[str, str]:
    """One of each thing the Today page shows."""
    today = _today()
    ids: dict[str, str] = {}
    ids["ready"], _ = _lead(conn)
    ids["ready_c"], _ = _lead(conn, grade="C", total=40)  # C leads are not on Today
    ids["d3"], _ = _lead(conn, stage="contacted", wa_at=today - timedelta(days=3), business={"city": "Kochi"})
    ids["talking"], _ = _lead(conn, stage="talking", wa_at=today - timedelta(days=2))
    ids["overdue"], _ = _lead(conn, stage="proposal_sent", due_at=today - timedelta(days=1))
    ids["won"], _ = _lead(conn, stage="won")
    conn.execute("update public.leads set deal_value_inr = 125000 where id = %s", [ids["won"]])
    return ids


# ---------------------------------------------------------------------------
# Who may call what
# ---------------------------------------------------------------------------


def _executable(conn: Conn, role: str, fn: str) -> bool:
    return bool(_one(conn, "select has_function_privilege(%s, %s, 'EXECUTE')", [role, f"public.{fn}"]))


def test_page_functions_exist_and_only_signed_in_users_may_call_them(db_conn: Conn) -> None:
    rows = db_conn.execute(
        "select p.oid::regprocedure::text as fn, p.prosecdef as definer, p.provolatile as volatility "
        "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public'"
    ).fetchall()
    found = {r["fn"].removeprefix("public."): r for r in rows}
    for fn in PAGE_FUNCTIONS:
        assert fn in found, fn
        assert found[fn]["volatility"] == "s", fn  # stable: reads only
        assert _executable(db_conn, "authenticated", fn), fn
        assert not _executable(db_conn, "anon", fn), fn
    # Only search_leads runs as its owner (indexes for ILIKE under RLS); everything else runs as the user.
    assert {fn for fn in PAGE_FUNCTIONS if found[fn]["definer"]} == {"search_leads(text,integer)"}


def test_hook_and_session_revocation_are_locked_down(db_conn: Conn) -> None:
    hook = "custom_access_token_hook(jsonb)"
    assert _executable(db_conn, "supabase_auth_admin", hook)
    for role in ("anon", "authenticated"):
        assert not _executable(db_conn, role, hook), role
        assert not _executable(db_conn, role, "revoke_user_sessions(uuid)"), role
    assert _executable(db_conn, "service_role", "revoke_user_sessions(uuid)")


def test_visitors_cannot_call_the_page_functions(db_conn: Conn) -> None:
    act_as(db_conn, "anon")
    for call in ("select public.home_summary()", "select public.nav_counts()", "select public.leads_page()",
                 "select public.deals_board()", "select public.engine_counts()", "select public.search_leads('ab')"):  # fmt: skip
        with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
            db_conn.execute(call)


# ---------------------------------------------------------------------------
# The access token hook (0023)
# ---------------------------------------------------------------------------


def _hook(conn: Conn, event: dict[str, Any] | str) -> Any:
    conn.execute("set local role supabase_auth_admin")
    payload = event if isinstance(event, str) else json.dumps(event)
    result = _one(conn, "select public.custom_access_token_hook(%s::jsonb)", [payload])
    conn.execute("reset role")
    return result


def test_hook_adds_the_role_and_name_from_the_profile(db_conn: Conn, rls_world: RlsWorld) -> None:
    claims = {"sub": rls_world.caller, "role": "authenticated", "email": "c@example.com", "app_metadata": {}}
    out = _hook(db_conn, {"user_id": rls_world.caller, "claims": claims, "authentication_method": "password"})
    assert out["claims"] == {**claims, "user_role": "caller", "full_name": "RLS caller"}
    assert out["user_id"] == rls_world.caller and out["authentication_method"] == "password"
    # A blank name is no name: the app falls back to the email.
    db_conn.execute("update public.profiles set full_name = '  ' where user_id = %s", [rls_world.admin])
    out = _hook(db_conn, {"user_id": rls_world.admin, "claims": {"sub": rls_world.admin}})
    assert out["claims"] == {"sub": rls_world.admin, "user_role": "admin", "full_name": None}


def test_hook_leaves_the_token_alone_without_a_profile_and_never_fails(db_conn: Conn) -> None:
    stranger = str(uuid.uuid4())
    # A stale claim from the request is removed, so the app reads the profile instead of trusting it.
    claims = {"sub": stranger, "role": "authenticated", "user_role": "admin"}
    out = _hook(db_conn, {"user_id": stranger, "claims": claims})
    assert out["claims"] == {"sub": stranger, "role": "authenticated"}
    broken = {"user_id": "not-a-uuid", "claims": {"sub": "x"}}
    assert _hook(db_conn, broken) == broken


def test_the_auth_server_role_reads_only_what_the_hook_needs(db_conn: Conn, rls_world: RlsWorld) -> None:
    db_conn.execute("set local role supabase_auth_admin")
    assert _one(db_conn, "select count(*) from public.profiles where user_id = %s", [rls_world.viewer]) == 1
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("select created_at from public.profiles")
    with pytest.raises(errors.InsufficientPrivilege), db_conn.transaction():
        db_conn.execute("update public.profiles set role = 'admin'")


# ---------------------------------------------------------------------------
# Ending a disabled user's sessions (0023)
# ---------------------------------------------------------------------------


def test_revoke_user_sessions_ends_every_session_of_one_user(db_conn: Conn, rls_world: RlsWorld) -> None:
    # Local Postgres has no auth.sessions: nothing to end, and no error.
    db_conn.execute("set local role service_role")
    assert _one(db_conn, "select public.revoke_user_sessions(%s)", [rls_world.viewer]) == 0
    db_conn.execute("reset role")
    # The bits of Supabase's auth schema the function touches, for this transaction only.
    db_conn.execute("create table auth.sessions (id uuid primary key default gen_random_uuid(), user_id uuid not null)")
    db_conn.execute(
        "create table auth.refresh_tokens (id bigserial primary key, token text, user_id varchar(255), "
        "session_id uuid references auth.sessions(id) on delete cascade)"
    )
    for user in (rls_world.viewer, rls_world.viewer, rls_world.caller):
        session = _one(db_conn, "insert into auth.sessions (user_id) values (%s) returning id", [user])
        db_conn.execute(
            "insert into auth.refresh_tokens (token, user_id, session_id) values ('t', %s, %s)", [user, session]
        )
    db_conn.execute("insert into auth.refresh_tokens (token, user_id) values ('legacy', %s)", [rls_world.viewer])
    db_conn.execute("set local role service_role")
    assert _one(db_conn, "select public.revoke_user_sessions(%s)", [rls_world.viewer]) == 2
    db_conn.execute("reset role")
    left = db_conn.execute("select user_id::text as user_id from auth.sessions").fetchall()
    assert left == [{"user_id": rls_world.caller}]
    tokens = db_conn.execute("select user_id from auth.refresh_tokens").fetchall()
    assert tokens == [{"user_id": rls_world.caller}]


# ---------------------------------------------------------------------------
# Today
# ---------------------------------------------------------------------------


def _old_today_counts(conn: Conn) -> dict[str, int]:
    """The six counts lib/queries/today.ts used to make, one request each."""
    week_start = "date_trunc('week', now() at time zone 'Asia/Kolkata')::date"
    today = "(now() at time zone 'Asia/Kolkata')::date"
    return {
        "ready": _one(conn, "select count(*) from public.v_today"),
        "contacted_this_week": _one(conn, f"select count(*) from public.leads where wa_at >= {week_start}"),
        "talking": _one(conn, "select count(*) from public.leads where stage = 'talking'"),
        "discovery": _one(
            conn, "select count(*) from public.leads where stage in ('discovery_booked', 'discovery_done')"
        ),
        "proposals": _one(conn, "select count(*) from public.leads where stage = 'proposal_sent'"),
        "overdue": _one(conn, f"select count(*) from public.leads where due_at < {today} and stage not in {CLOSED}"),
    }


def test_home_summary_matches_the_queries_it_replaces(db_conn: Conn, rls_world: RlsWorld) -> None:
    ids = _seed_today(db_conn)
    for role in ("admin", "caller", "viewer"):
        act_as(db_conn, "authenticated", getattr(rls_world, role))
        summary = _call(db_conn, "select public.home_summary()")
        assert set(summary) == {"counts", "won_this_month_inr", "send", "followups"}
        assert summary["counts"] == _old_today_counts(db_conn), role
        expected_send = [r["lead_id"] for r in db_conn.execute(
            "select lead_id::text from public.v_today order by grade, total desc nulls last, created_at, lead_id limit 100"
        ).fetchall()]  # fmt: skip
        assert [r["lead_id"] for r in summary["send"]] == expected_send
        expected_due = db_conn.execute(
            "select lead_id::text, which from public.v_followups_due order by due_on, grade, lead_id, which limit 100"
        ).fetchall()
        assert [{"lead_id": r["lead_id"], "which": r["which"]} for r in summary["followups"]] == expected_due
        db_conn.execute("reset role")
    send = {r["lead_id"]: r for r in summary["send"]}
    assert ids["ready"] in send and ids["ready_c"] not in send
    row = send[ids["ready"]]
    assert row["grade"] == "A" and row["phone_e164"] == "+919822200001" and row["top_signal_type"] == "hiring_frontdesk"
    assert {"company", "city", "segment_id", "message", "email_subject", "phone_source", "top_signal_at"} <= set(row)
    due = {(r["lead_id"], r["which"]): r for r in summary["followups"]}
    d3 = due[(ids["d3"], "d3")]
    assert d3["city"] == "Kochi" and d3["phone_type"] == "mobile" and d3["followup_text"] == "Day 3 text"
    assert d3["due_on"] == (_today()).isoformat()


def test_home_summary_money_is_for_admins_only(db_conn: Conn, rls_world: RlsWorld) -> None:
    ids = _seed_today(db_conn)
    # The trigger logged the move to Won just now, so it counts for this month.
    expected = _one(
        db_conn,
        "select coalesce(sum(l.deal_value_inr), 0) from public.leads l where l.stage in ('won', 'retainer') "
        "and l.id in (select a.lead_id from public.activities a where a.type = 'stage_change' "
        "and a.at >= date_trunc('month', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata' "
        "and a.payload ->> 'to' in ('won', 'retainer'))",
    )
    assert expected >= 125000
    act_as(db_conn, "authenticated", rls_world.admin)
    assert float(_call(db_conn, "select public.home_summary()")["won_this_month_inr"]) == float(expected)
    for role in ("caller", "viewer"):
        act_as(db_conn, "authenticated", getattr(rls_world, role))
        assert _call(db_conn, "select public.home_summary()")["won_this_month_inr"] is None, role
    assert ids["won"]


def test_nav_counts(db_conn: Conn, rls_world: RlsWorld) -> None:
    _seed_today(db_conn)
    db_conn.execute("insert into public.inbox_posts (text) values ('someone asked for an app')")
    for role in ("admin", "caller"):
        act_as(db_conn, "authenticated", getattr(rls_world, role))
        counts = _call(db_conn, "select public.nav_counts()")
        old = _old_today_counts(db_conn)
        assert counts["ready"] == old["ready"] and counts["overdue"] == old["overdue"]
        assert counts["followups_due"] == _one(db_conn, "select count(*) from public.v_followups_due")
        assert counts["deals"] == _one(
            db_conn, "select count(*) from public.leads where stage in ('talking', 'discovery_booked', "
            "'discovery_done', 'proposal_sent')"
        )  # fmt: skip
        inbox = _one(db_conn, "select count(*) from public.inbox_posts where status = 'new'")
        assert counts["inbox_new"] == inbox
        assert (inbox >= 1) == (role == "admin")  # the inbox is admin-only


# ---------------------------------------------------------------------------
# The lead page
# ---------------------------------------------------------------------------


def _seed_lead_page(conn: Conn) -> tuple[str, str]:
    lead, biz = _lead(conn, stage="lost", lost_reason="price", business={"address": "1 MG Road"})
    conn.execute("update public.leads set deal_value_inr = 90000, retainer_monthly_value = 1500, deal_currency = 'USD' "
                 "where id = %s", [lead])  # fmt: skip
    conn.execute(
        "insert into public.contacts (business_id, name, phone_e164, phone_type, source, is_decision_maker, line) "
        "values (%s, 'Dr. Owner', '+919822299999', 'mobile', 'website', true, 'owner')",
        [biz],
    )
    conn.execute("insert into public.suppression (phone_e164, reason) values ('+919822299999', 'opt_out')")
    conn.execute(
        "insert into public.facts (business_id, field, value, verified) values (%s, 'staff', '5', true), "
        "(%s, 'price_point', '\"high\"', false)",
        [biz, biz],
    )
    conn.execute(
        "insert into public.pages (business_id, url, title, text) values (%s, %s, 'Home', 'raw text')",
        [biz, f"https://{biz}.example.com/"],
    )
    conn.execute("insert into public.activities (lead_id, source, type, payload) values (%s, 'engine', 'note', %s)",
                 [lead, Jsonb({"text": "checked"})])  # fmt: skip
    return lead, biz


def test_lead_detail_for_each_role(db_conn: Conn, rls_world: RlsWorld) -> None:
    lead, biz = _seed_lead_page(db_conn)
    db_conn.execute("insert into public.feedback (lead_id, user_id, rating, reason) values (%s, %s, 1, 'fit')",
                    [lead, rls_world.caller])  # fmt: skip
    act_as(db_conn, "authenticated", rls_world.admin)
    full = _call(db_conn, "select public.lead_detail(%s, true)", [lead])
    assert set(full) == {"lead", "business", "contacts", "suppressed_phones", "signals", "facts", "score", "pages",
                         "activities", "feedback", "money"}  # fmt: skip
    view_row = db_conn.execute(
        "select to_jsonb(v) as row from public.v_leads_caller v where id = %s", [lead]
    ).fetchone()
    assert view_row is not None
    assert full["lead"] == {**view_row["row"], "lost_reason": "price"}
    assert full["business"]["address"] == "1 MG Road" and full["business"]["name"] == full["lead"]["name"]
    assert [c["name"] for c in full["contacts"]] == ["Dr. Owner", "Reception"]  # decision makers first
    assert full["contacts"][0]["line"] == "owner"
    assert full["suppressed_phones"] == ["+919822299999"]
    assert {f["field"] for f in full["facts"]} == {"staff", "price_point"}
    assert full["score"]["total"] == 100 and full["signals"][0]["type"] == "hiring_frontdesk"
    assert full["pages"][0]["title"] == "Home" and "text" not in full["pages"][0]
    assert {"lead_created", "stage_change", "note"} <= {a["type"] for a in full["activities"]}
    assert full["feedback"][0]["user_id"] == rls_world.caller
    assert full["money"] == {"deal": 90000, "retainer": 1500, "currency": "USD"}
    assert {f["field"] for f in _call(db_conn, "select public.lead_detail(%s)", [lead])["facts"]} == {"staff"}

    act_as(db_conn, "authenticated", rls_world.caller)
    caller = _call(db_conn, "select public.lead_detail(%s, true)", [lead])
    assert caller["money"] is None
    assert {f["field"] for f in caller["facts"]} == {"staff"}  # unverified facts are an admin view
    assert caller["suppressed_phones"] == ["+919822299999"]
    assert "deal_value_inr" not in caller["lead"]

    act_as(db_conn, "authenticated", rls_world.viewer)
    viewer = _call(db_conn, "select public.lead_detail(%s)", [lead])
    assert viewer["suppressed_phones"] == []  # viewers cannot read Do not contact
    assert viewer["money"] is None and viewer["lead"]["id"] == lead

    assert _call(db_conn, "select public.lead_detail(%s)", [str(uuid.uuid4())]) is None
    db_conn.execute("reset role")
    stranger = str(uuid.uuid4())
    act_as(db_conn, "authenticated", stranger)  # signed in, no profile: Row Level Security shows nothing
    assert _call(db_conn, "select public.lead_detail(%s)", [lead]) is None
    assert biz


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def test_deals_board_shows_open_stages_and_counts_the_closed_ones(db_conn: Conn, rls_world: RlsWorld) -> None:
    mine = {}
    for stage in (*OPEN, *CLOSED):
        mine[stage], _ = _lead(db_conn, stage=stage, owner_id=rls_world.caller)
    db_conn.execute("update public.leads set deal_value_inr = 50000 where id = %s", [mine["proposal_sent"]])
    db_conn.execute("update public.leads set deal_value_inr = 80000 where id = %s", [mine["won"]])
    new_lead, _ = _lead(db_conn)

    act_as(db_conn, "authenticated", rls_world.caller)
    board = _call(db_conn, "select public.deals_board()")
    assert set(board) == {"cards", "counts", "open_stages", "max_per_stage", "closed_per_stage"}
    stages = {c["stage"] for c in board["cards"]}
    assert stages <= set(OPEN)  # no New, no closed stage
    ids = {c["id"] for c in board["cards"]}
    assert {mine[s] for s in OPEN} <= ids and not {mine[s] for s in CLOSED} & ids and new_lead not in ids
    expected = {r["stage"]: r["n"] for r in db_conn.execute(
        "select stage, count(*) as n from public.leads where stage <> 'new' group by stage"
    ).fetchall()}  # fmt: skip
    assert board["counts"] == expected
    assert not any("deal_value_inr" in c for c in board["cards"])  # callers never see money

    with_closed = _call(db_conn, "select public.deals_board('{}'::jsonb, 500, 5)")
    assert {mine[s] for s in CLOSED} <= {c["id"] for c in with_closed["cards"]}

    act_as(db_conn, "authenticated", rls_world.admin)
    admin = {c["id"]: c for c in _call(db_conn, "select public.deals_board('{}'::jsonb, 500, 5)")["cards"]}
    assert float(admin[mine["proposal_sent"]]["deal_value_inr"]) == 50000
    assert float(admin[mine["won"]]["deal_value_inr"]) == 80000
    assert "deal_value_inr" not in admin[mine["talking"]]  # no deal value, no money keys


def test_deals_board_filters(db_conn: Conn, rls_world: RlsWorld) -> None:
    today = _today()
    mine, _ = _lead(db_conn, stage="talking", owner_id=rls_world.caller, due_at=today - timedelta(days=2))
    nobody, _ = _lead(db_conn, stage="talking", due_at=today + timedelta(days=2))
    uae, _ = _lead(db_conn, stage="talking", business={"country": "ae", "city": "Dubai"})
    act_as(db_conn, "authenticated", rls_world.caller)

    def ids(filters: dict[str, Any]) -> set[str]:
        return {c["id"] for c in _call(db_conn, "select public.deals_board(%s)", [Jsonb(filters)])["cards"]}

    assert mine in ids({"owner": "me"}) and nobody not in ids({"owner": "me"})
    assert nobody in ids({"owner": "none"}) and mine not in ids({"owner": "none"})
    assert mine in ids({"owner": rls_world.caller}) and mine in ids({"owner": rls_world.caller.upper()})
    assert mine in ids({"overdue": True}) and nobody not in ids({"overdue": True})
    assert uae in ids({"country": "ae"}) and mine not in ids({"country": "ae"})
    assert uae in ids({"seg": "clinics-ae"}) and mine not in ids({"seg": "clinics-ae"})


def test_deals_board_never_loses_open_deals_behind_closed_leads(db_conn: Conn, rls_world: RlsWorld) -> None:
    """The old board read 1,000 rows across every stage, most recently active first, so a quiet deal could be cut."""
    deal, _ = _lead(db_conn, stage="proposal_sent")
    db_conn.execute("update public.leads set last_activity_at = now() - interval '300 days' where id = %s", [deal])
    for _ in range(12):
        _lead(db_conn, stage="lost", lost_reason="no_reply")
    act_as(db_conn, "authenticated", rls_world.viewer)
    board = _call(db_conn, "select public.deals_board('{}'::jsonb, 2000, 0)")
    assert deal in {c["id"] for c in board["cards"]}
    assert board["counts"]["lost"] >= 12
    capped = _call(db_conn, "select public.deals_board('{}'::jsonb, 1, 0)")
    per_stage: dict[str, int] = {}
    for c in capped["cards"]:
        per_stage[c["stage"]] = per_stage.get(c["stage"], 0) + 1
    assert per_stage and max(per_stage.values()) == 1


# ---------------------------------------------------------------------------
# The Leads page
# ---------------------------------------------------------------------------


def _old_page(conn: Conn, where: str, params: list[Any], order: str, limit: int = 50, offset: int = 0) -> list[str]:
    return [
        r["id"]
        for r in conn.execute(
            f"select id::text from public.v_leads_caller where {where} order by {order} limit {limit} offset {offset}",
            params,
        ).fetchall()
    ]


def test_leads_page_matches_the_old_query(db_conn: Conn, rls_world: RlsWorld) -> None:
    today = _today()
    a1, _ = _lead(db_conn, business={"name": "Zebra Dental Care", "city": "Kochi"})
    a2, _ = _lead(db_conn, grade="B", total=60, phone="+919822233333", phone_type="landline", signal=False,
                  business={"name": "Zebra Smiles", "city": "Kochi"})  # fmt: skip
    a3, _ = _lead(db_conn, stage="contacted", wa_at=today, owner_id=rls_world.caller, due_at=today - timedelta(days=1),
                  business={"country": "ae", "city": "Dubai"})  # fmt: skip
    db_conn.execute("update public.leads set deal_value_inr = 70000 where id = %s", [a3])
    act_as(db_conn, "authenticated", rls_world.caller)

    def page(filters: dict[str, Any], page: int = 1, size: int = 50) -> Any:
        return _call(db_conn, "select public.leads_page(%s, %s, %s)", [Jsonb(filters), page, size])

    first = page({})
    assert set(first) == {"rows", "total", "page", "page_size", "filtered", "cities", "views"}
    assert first["filtered"] is False and first["page"] == 1 and first["page_size"] == 50
    assert first["total"] == _one(db_conn, "select count(*) from public.v_leads_caller")
    assert [r["id"] for r in first["rows"]] == _old_page(db_conn, "true", [], "created_at desc nulls last, id")
    assert not any("deal_value_inr" in r for r in first["rows"])

    cases: list[tuple[dict[str, Any], str, list[Any], str]] = [
        ({"q": "zebra"}, "(name ilike %s or web_domain ilike %s)", ["%zebra%", "%zebra%"],
         "created_at desc nulls last, id"),
        ({"q": "Zebra (Dental)", "sort": "company", "dir": "asc"}, "(name ilike %s or web_domain ilike %s)",
         ["%Zebra Dental%", "%Zebra Dental%"], "name asc nulls last, id"),
        ({"q": "98222 33333"}, "(name ilike %s or web_domain ilike %s or phone_e164 ilike %s)",
         ["%98222 33333%", "%98222 33333%", "%9822233333%"], "created_at desc nulls last, id"),
        ({"grade": ["B"], "city": ["Kochi"]}, "grade = any(%s) and city = any(%s)", [["B"], ["Kochi"]],
         "created_at desc nulls last, id"),
        ({"signal": ["hiring_frontdesk"], "mobile": True, "sort": "score"},
         "top_signal_type = any(%s) and phone_type = 'mobile'", [["hiring_frontdesk"]], "total desc nulls last, id"),
        ({"owner": "me", "overdue": True}, f"owner_id = %s and due_at < %s and stage not in {CLOSED}",
         [rls_world.caller, today], "created_at desc nulls last, id"),
        ({"owner": "none", "stage": ["new"], "sort": "activity", "dir": "asc"},
         "owner_id is null and stage = any(%s)", [["new"]], "last_activity_at asc nulls last, id"),
        ({"country": ["ae"], "from": today.isoformat(), "to": today.isoformat(), "sort": "due"},
         "country = any(%s) and created_at >= %s and created_at < %s",
         [["ae"], datetime.combine(today, datetime.min.time(), IST),
          datetime.combine(today + timedelta(days=1), datetime.min.time(), IST)], "due_at desc nulls last, id"),
    ]  # fmt: skip
    for filters, where, params, order in cases:
        got = page(filters)
        expected = _old_page(db_conn, where, params, order)
        assert [r["id"] for r in got["rows"]] == expected, filters
        assert got["total"] == _one(db_conn, f"select count(*) from public.v_leads_caller where {where}", params), (
            filters
        )
        assert got["filtered"] is True
    assert {a1, a2} <= {r["id"] for r in page({"q": "zebra"})["rows"]}
    assert [r["id"] for r in page({"owner": "me", "overdue": True})["rows"]] == [a3]
    # Paging: the second page of two-row pages continues the first.
    two = _old_page(db_conn, "true", [], "created_at desc nulls last, id", limit=4)
    assert [r["id"] for r in page({}, 1, 2)["rows"]] + [r["id"] for r in page({}, 2, 2)["rows"]] == two
    # A bad date is ignored, not an error.
    assert page({"from": "2026-02-30"})["total"] == first["total"]

    act_as(db_conn, "authenticated", rls_world.admin)
    rows = {r["id"]: r for r in page({"owner": rls_world.caller})["rows"]}
    assert float(rows[a3]["deal_value_inr"]) == 70000
    assert all("deal_value_inr" in r for r in rows.values())


def test_leads_page_cities_and_saved_views(db_conn: Conn, rls_world: RlsWorld) -> None:
    _lead(db_conn, business={"city": " Kollam "})
    _lead(db_conn, business={"country": "ae", "city": "Al Ain"})
    db_conn.execute(
        "insert into public.saved_views (user_id, name, query, shared) values "
        "(%s, 'Mine', %s, false), (%s, 'Team', %s, true), (%s, 'Private', %s, false)",
        [rls_world.caller, Jsonb({"qs": "grade=A"}), rls_world.admin, Jsonb({"qs": "stage=talking"}),
         rls_world.admin, Jsonb({"qs": "x=1"})],
    )  # fmt: skip
    act_as(db_conn, "authenticated", rls_world.caller)
    result = _call(db_conn, "select public.leads_page('{}')")
    cities = result["cities"]
    assert "Kollam" in cities and "Al Ain" in cities and " Kollam " not in cities
    assert len(cities) == len(set(cities))
    expected = {r["c"] for r in db_conn.execute(
        "select distinct btrim(b.city) as c from public.leads l join public.businesses b on b.id = l.business_id "
        "where b.city is not null and btrim(b.city) <> ''"
    ).fetchall()}  # fmt: skip
    assert set(cities) == expected
    only_india = _call(db_conn, 'select public.leads_page(\'{"country": ["in"]}\')')["cities"]
    assert "Kollam" in only_india and "Al Ain" not in only_india
    views = {v["name"]: v for v in result["views"]}
    assert set(views) >= {"Mine", "Team"} and "Private" not in views
    assert views["Mine"]["mine"] is True and views["Mine"]["qs"] == "grade=A"
    assert views["Team"]["mine"] is False and views["Team"]["shared"] is True


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_leads(db_conn: Conn, rls_world: RlsWorld) -> None:
    lead, _ = _lead(
        db_conn,
        phone="+919811122334",
        business={"name": "Quixotic Orthodontics", "web_domain": "quixo-smile.example.com"},
    )
    act_as(db_conn, "authenticated", rls_world.viewer)

    def ids(q: str, n: int = 10) -> list[str]:
        return [r["id"] for r in _call(db_conn, "select public.search_leads(%s, %s)", [q, n])]

    assert ids("quixotic")[:1] == [lead]
    assert lead in ids("Quixotik Orthodontic")  # a typo
    assert lead in ids("quixo-smile")  # the website
    assert lead in ids("98111 22334")  # the phone's digits
    assert ids("q") == [] and ids("   ") == []
    assert lead not in ids("100%_")  # LIKE wildcards are literal
    hit = _call(db_conn, "select public.search_leads('quixotic', 1)")
    assert len(hit) == 1 and set(hit[0]) == {"id", "name", "city", "country", "web_domain", "segment_id", "grade",
                                             "stage", "created_at"}  # fmt: skip
    db_conn.execute("reset role")
    act_as(db_conn, "authenticated", str(uuid.uuid4()))  # no profile, no app role
    assert ids("quixotic") == []


# ---------------------------------------------------------------------------
# Insights and the Engine page
# ---------------------------------------------------------------------------


def test_insights_summary_counts_like_v_funnel(db_conn: Conn, rls_world: RlsWorld) -> None:
    today = _today()
    won, _ = _lead(db_conn, stage="contacted", wa_at=today)
    for stage in ("talking", "discovery_booked", "proposal_sent", "won"):
        db_conn.execute("update public.leads set stage = %s where id = %s", [stage, won])
    lost, _ = _lead(db_conn, stage="talking", wa_at=today)
    db_conn.execute("update public.leads set stage = 'lost', lost_reason = 'price' where id = %s", [lost])
    wrong, _ = _lead(db_conn, stage="wrong_contact", business={"country": "ae", "city": "Dubai"})
    db_conn.execute("insert into public.feedback (lead_id, user_id, rating, reason) values (%s, %s, 1, 'fit'), "
                    "(%s, %s, -1, 'wrong')", [won, rls_world.caller, lost, rls_world.caller])  # fmt: skip
    db_conn.execute("insert into public.costs (provider, task, inr) values ('gemini', 'page_reads', 12.5)")
    start = datetime.combine(today - timedelta(days=6), datetime.min.time(), IST)
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), IST)

    act_as(db_conn, "authenticated", rls_world.admin)
    for filters in ({}, {"country": "in", "group": "signal"}, {"seg": "clinics-ae", "group": "pitch"}):
        got = _call(db_conn, "select public.insights_summary(%s, %s, %s)", [start, end, Jsonb(filters)])
        where = "created_on between %s and %s"
        params: list[Any] = [(today - timedelta(days=6)), today]
        if "country" in filters:
            where += " and country = %s"
            params.append(filters["country"])
        if "seg" in filters:
            where += " and segment_id = %s"
            params.append(filters["seg"])
        old = db_conn.execute(
            "select count(*) as leads, count(*) filter (where reached_contacted) as contacted, "
            "count(*) filter (where reached_talking) as replied, count(*) filter (where reached_discovery) as meetings, "
            "count(*) filter (where reached_proposal) as proposals, count(*) filter (where reached_won) as won "
            f"from public.v_funnel where {where}",
            params,
        ).fetchone()
        assert got["total"] == old, filters
        by_segment = {r["id"]: r for r in got["by_segment"]}
        assert sum(r["leads"] for r in by_segment.values()) == old["leads"]
        assert sum(r["leads"] for r in got["by_group"]) == old["leads"]
        contacted = [r["contacted"] for r in got["by_group"]]
        assert contacted == sorted(contacted, reverse=True)

    everything = _call(db_conn, "select public.insights_summary(%s, %s)", [start, end])
    quality = everything["quality"]
    assert set(quality) == {"leads", "with_phone", "own_phone", "contacted", "wrong", "median_signal_age_days",
                            "votes", "up_votes"}  # fmt: skip
    assert quality["leads"] == everything["total"]["leads"] and quality["wrong"] >= 1
    assert quality["votes"] >= 2 and quality["up_votes"] >= 1
    costs = everything["costs"]
    assert len(costs["days"]) == 7 and costs["days"][-1]["day"] == today.isoformat()
    assert costs["spend"] >= 12.5
    assert costs["cap"] == _one(db_conn, "select value from public.settings where key = 'daily_cap_inr'")
    assert costs["won"] >= 1 and costs["good_leads"] >= 3
    assert wrong

    act_as(db_conn, "authenticated", rls_world.caller)
    caller = _call(db_conn, "select public.insights_summary(%s, %s)", [start, end])
    assert caller["costs"] is None and caller["total"] == everything["total"]


def test_engine_counts_are_admin_only(db_conn: Conn, rls_world: RlsWorld) -> None:
    db_conn.execute("insert into public.runs (kind, status) values ('manual', 'ok')")
    db_conn.execute("insert into public.costs (provider, task, inr) values ('gemini', 'page_reads', 3.25)")
    db_conn.execute("insert into public.custom_queries (segment_id, query) values ('clinics-in', 'dentists in Kochi')")
    act_as(db_conn, "authenticated", rls_world.admin)
    admin = _call(db_conn, "select public.engine_counts()")
    assert set(admin) == {"spend_today", "researched_yesterday", "leads_yesterday", "sources", "runs", "queries"}
    assert admin["spend_today"] >= 3.25
    assert len(admin["sources"]) == _one(db_conn, "select count(*) from public.v_source_health")
    assert admin["runs"] and admin["queries"][0]["query"] == "dentists in Kochi"
    assert [s["source"] for s in admin["sources"]] == sorted(s["source"] for s in admin["sources"])
    act_as(db_conn, "authenticated", rls_world.caller)
    caller = _call(db_conn, "select public.engine_counts()")
    assert caller["sources"] == [] and caller["runs"] == [] and caller["queries"] == [] and caller["spend_today"] == 0
