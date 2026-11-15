"""Builders for the startup qualification and score s3.0 tests (15 Nov 2026).

Rows look like what `pipeline.evidence` loads: verified facts (AI facts with a quote and a page, probe facts as
`model='rule'`), signals with their windows and details, and contacts with the 0018 line and the 0020 email
status. Every id is readable ("f-team-1", "s-fund") so a failing golden case says which evidence it used.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import SIGNAL_CATEGORY
from nument_engine.segments import load_segments, sync_segments_to_db

from .pipeline_fakes import NOW

SITE = "https://brightcart.io"
TEAM_URL = f"{SITE}/team"
AI_MODEL = "gemini:gemini-3.8-flash#extract_facts.v2"


@pytest.fixture
def firms_us(clean_db: str) -> Iterator[str]:
    """The firms-us segment row, as `nlead db sync-segments` writes it (the migrations seed only wave 1)."""
    with db.tx() as conn:
        sync_segments_to_db(conn, {"firms-us": load_segments()["firms-us"]})
    yield "firms-us"


def business(**over: Any) -> dict[str, Any]:
    return {
        "id": "b-startup",
        "segment_id": "firms-us",
        "name": "BrightCart",
        "country": "us",
        "city": "San Francisco",
        "website": f"{SITE}/",
        "web_domain": "brightcart.io",
        "category": "startup",
        "subcategory": None,
        "staff_count": None,
        "review_count": None,
        "created_at": NOW - timedelta(days=3),
        "extra": {},
        **over,
    }


def fact(fid: str, field: str, value: Any, quote: str = "", url: str = TEAM_URL, **over: Any) -> dict[str, Any]:
    """A verified AI fact (verification already passed)."""
    return {
        "id": fid,
        "business_id": "b-startup",
        "field": field,
        "value": value,
        "quote": quote or str(value),
        "url": url,
        "page_id": None,
        "model": AI_MODEL,
        "verified": True,
        "verify_score": 100,
        "verified_at": NOW - timedelta(hours=1),
        "created_at": NOW - timedelta(hours=2),
        **over,
    }


def probe(
    fid: str, name: str, value: dict[str, Any], url: str = "https://rdap.org/domain/brightcart.io"
) -> dict[str, Any]:
    """A probe fact as lane E2a writes it (contract 4.2): model 'rule', verified."""
    return fact(fid, f"probe.{name}", value, quote=str(value)[:200], url=url, model="rule")


def member(fid: str, name: str, role: str, *, founder: bool = False, engineer: bool = False) -> dict[str, Any]:
    return fact(
        fid,
        "team_member",
        {"name": name, "role": role, "is_founder": founder, "is_engineer": engineer},
        quote=f"{name}, {role}",
    )


def signal(
    sid: str,
    kind: str,
    *,
    age_days: float = 5,
    window_days: float = 60,
    points: float = 0,
    source: str = "funding_rss",
    quote: str = "",
    **details: Any,
) -> dict[str, Any]:
    observed = NOW - timedelta(days=age_days)
    return {
        "id": sid,
        "business_id": "b-startup",
        "type": kind,
        "category": SIGNAL_CATEGORY[kind],
        "points": points,
        "observed_at": observed,
        "expires_at": observed + timedelta(days=window_days),
        "source": source,
        "url": f"https://news.example.com/{sid}",
        "quote": quote or f"{kind} {sid}",
        "details": details,
        "created_at": observed,
    }


def founder_email(cid: str = "c-maya", status: str = "verified", **over: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "business_id": "b-startup",
        "name": "Maya Chen",
        "role": "Co-founder and CEO",
        "email": "maya@brightcart.io",
        "phone_e164": None,
        "phone_type": "unknown",
        "source": "website",
        "verified": True,
        "verified_at": NOW - timedelta(days=1),
        "do_not_contact": False,
        "is_decision_maker": True,
        "line": "owner",
        "email_status": status,
        "email_origin": "published",
        **over,
    }


def company_email(cid: str = "c-hello", **over: Any) -> dict[str, Any]:
    return {
        **founder_email(cid),
        "name": None,
        "role": None,
        "email": "hello@brightcart.io",
        "is_decision_maker": False,
        "line": "front_desk",
        "email_status": "unknown",
        **over,
    }


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)
