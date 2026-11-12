"""Builders for test data in the learning, report, health and audit tests.

Stage history is written as `stage_change` activities with chosen times, the way the lead trigger would
have written them on those days. Only tests do this; engine code never inserts trigger-owned types.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .helpers import Conn

NOW = datetime(2026, 12, 14, 6, 0, tzinfo=UTC)  # a Monday morning, IST


def business(conn: Conn, segment: str = "clinics-in", **cols: Any) -> str:
    tag = uuid.uuid4().hex[:10]
    values = {
        "segment_id": segment,
        "name": f"Seed Clinic {tag}",
        "norm_name": f"seed clinic {tag}",
        "country": segment[-2:],
        "city": "Pune",
        "web_domain": f"seed-{tag}.example.com",
        **cols,
    }
    cols_sql = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    row = conn.execute(
        f"insert into public.businesses ({cols_sql}) values ({marks}) returning id", list(values.values())
    ).fetchone()
    assert row is not None
    return str(row["id"])


def score(
    conn: Conn, business_id: str, *, total: float = 72, grade: str = "A", reasons: dict[str, Any] | None = None
) -> str:
    row = conn.execute(
        "insert into public.scores (business_id, version, fit, total, grade, pitch_mode, reasons) "
        "values (%s, 's1.0', 3, %s, %s, 'visible_pain', %s) returning id",
        [business_id, total, grade, Jsonb(reasons or {})],
    ).fetchone()
    assert row is not None
    return str(row["id"])


def lead(
    conn: Conn,
    *,
    segment: str = "clinics-in",
    grade: str = "A",
    pitch_mode: str = "visible_pain",
    angle: str = "frontdesk_load",
    created: datetime = NOW - timedelta(days=60),
    history: Sequence[tuple[str, datetime]] = (),
    stage: str | None = None,
    wa_on: date | None = None,
    signals: Sequence[str] = (),
    proxies: Sequence[str] = (),
    total: float = 72,
    deal_value_inr: float | None = None,
    business_cols: dict[str, Any] | None = None,
    phone: tuple[str, str, str] | None = ("+919800000001", "mobile", "website"),
    message: str | None = "Hi Dr. Rao, saw you are hiring.",
    message_model: str | None = "gemini-3-flash / write_message@v1",
) -> tuple[str, str]:
    """A scored lead with a stage history. Returns (lead id, business id)."""
    biz = business(conn, segment, **(business_cols or {}))
    reasons = {"signals": [{"type": t, "points": 8} for t in signals], "can_pay_proxies": list(proxies)}
    score_id = score(conn, biz, total=total, grade=grade, reasons=reasons)
    if phone:
        conn.execute(
            "insert into public.contacts (business_id, name, phone_e164, phone_type, source, verified) "
            "values (%s, 'Reception', %s, %s, %s, true)",
            [biz, *phone],
        )
    test_group = f"{segment}:{pitch_mode}:{angle}"
    row = conn.execute(
        "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, angle, test_group, message, "
        "message_model, deal_value_inr, created_at, last_activity_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        [
            biz,
            segment,
            score_id,
            grade,
            pitch_mode,
            angle,
            test_group,
            message,
            message_model,
            deal_value_inr,
            created,
            created,
        ],
    ).fetchone()
    assert row is not None
    lead_id = str(row["id"])
    previous = "new"
    for to, at in history:
        conn.execute(
            "insert into public.activities (lead_id, source, type, at, payload) values (%s, 'app', 'stage_change', %s, %s)",
            [lead_id, at, json.dumps({"from": previous, "to": to})],
        )
        previous = to
    final = stage or (history[-1][0] if history else "new")
    if final != "new" or wa_on is not None:
        conn.execute("update public.leads set stage = %s, wa_at = %s where id = %s", [final, wa_on, lead_id])
        # The trigger logged this update at the real clock time; the history above is the truth for the test.
        conn.execute(
            "delete from public.activities where lead_id = %s and type = 'stage_change' and source = 'engine'",
            [lead_id],
        )
        last = history[-1][1] if history else created
        conn.execute("update public.leads set last_activity_at = %s where id = %s", [last, lead_id])
    return lead_id, biz


def contacted(
    conn: Conn,
    days_ago: int,
    *,
    reached: Sequence[tuple[str, int]] = (),
    as_of: datetime = NOW,
    **kw: Any,
) -> str:
    """A lead first contacted `days_ago` days before `as_of`, then reaching each (stage, days after contact)."""
    first = as_of - timedelta(days=days_ago)
    history = [("contacted", first)] + [(s, first + timedelta(days=d)) for s, d in reached]
    lead_id, _ = lead(conn, created=first - timedelta(days=1), history=history, wa_on=first.date(), **kw)
    return lead_id
