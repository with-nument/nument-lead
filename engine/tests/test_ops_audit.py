"""The weekly audit (Step 17.6): sampling, re-checks against fresh pages, the stricter judge, storage."""

from __future__ import annotations

import random
import uuid
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import AuditResult
from nument_engine.ops import audit
from nument_engine.pipeline.runs import Options, run_context

SEGMENTS = ["clinics-ae", "clinics-in", "education-ae", "education-in", "realestate-ae", "realestate-in"]


def candidates(per_segment: int = 6, a_every: int = 5) -> list[dict[str, Any]]:
    out = []
    for seg in SEGMENTS:
        for i in range(per_segment):
            out.append({"lead_id": f"{seg}-{i}", "segment_id": seg, "grade": "A" if i % a_every == 0 else "B"})
    return out


def test_grade_agreement() -> None:
    assert [audit.grade_agreement("B", g) for g in "ABCD"] == ["one_step", "same", "one_step", "two_plus"]


def test_sample_is_stratified_and_repeatable() -> None:
    pool = candidates()
    sample = audit.pick_sample(pool, SEGMENTS, random.Random(202650))
    assert len(sample) == 20 and len({c["lead_id"] for c in sample}) == 20
    per_seg = Counter(c["segment_id"] for c in sample)
    assert all(per_seg[s] >= 2 for s in SEGMENTS)
    assert sum(c["grade"] == "A" for c in sample) >= 4
    assert sample == audit.pick_sample(pool, SEGMENTS, random.Random(202650))


def test_sample_with_few_leads_takes_what_exists() -> None:
    pool = candidates(per_segment=1, a_every=1)[:3]
    assert len(audit.pick_sample(pool, SEGMENTS, random.Random(1))) == 3
    assert audit.pick_sample([], SEGMENTS, random.Random(1)) == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Call +91 98200 12345 today", True),
        ("Ph: 098200-12345", True),
        ("(982) 001-2345", True),
        ("Call 98200 12346", False),
        ("no phone here", False),
    ],
)
def test_phone_on_page_ignores_formatting(text: str, found: bool) -> None:
    assert audit.phone_on_page("+919820012345", [text]) is found


FACTS = [
    {
        "id": "f1",
        "field": "branches",
        "value": {"count": 3},
        "quote": "Three branches in Pune",
        "url": "https://c.example.com/about",
    },
    {
        "id": "f2",
        "field": "service",
        "value": {"name": "IVF"},
        "quote": "IVF and IUI treatments",
        "url": "https://c.example.com/",
    },
    {"id": "f3", "field": "booking_method", "value": {"value": "phone"}, "quote": None, "url": None},
]
LEAD = {
    "lead_id": "L1",
    "business_id": "B1",
    "segment_id": "clinics-in",
    "name": "Clinic",
    "grade": "B",
    "pitch_mode": "visible_pain",
    "message": "Hi Dr. Rao",
    "website": "https://c.example.com/",
}


def contains(quote: str, text: str) -> bool:
    return quote.lower() in text.lower()


def test_check_pages_and_judge() -> None:
    pages = {
        "https://c.example.com/": "We offer IVF and IUI treatments. Call +91 98200 12345.",
        "https://c.example.com/about": "Founded in 2001. Now two branches in Pune.",
    }
    requested: list[list[str]] = []

    def fetch(urls: list[str]) -> dict[str, str]:
        requested.append(urls)
        return pages

    contact = {"phone_e164": "+919820012345", "source": "website"}
    out, texts = audit.check_pages(LEAD, facts=FACTS, contact=contact, fetch=fetch, still_there=contains)
    assert requested == [["https://c.example.com/", "https://c.example.com/about"]]
    assert (out.facts_checked, out.facts_still_verify, out.stale_fact_ids) == (2, 1, ["f1"])
    assert out.phone_checked and out.phone_still_present

    seen: dict[str, Any] = {}

    def judge(inputs: Mapping[str, Any], lead_id: str) -> AuditResult:
        seen.update(inputs)
        return AuditResult(
            audit_grade="D",
            agrees=False,
            stale_facts=["Ff2"],
            phone_still_present=True,
            message_claims_ok=False,
            notes="Branch count changed.",
        )

    audit.judge_lead(out, LEAD, FACTS, texts, judge)
    assert seen["grade"] == "B" and seen["facts"][0] == {"id": "f1", "field": "branches", "value": {"count": 3}}
    assert out.agreement == "two_plus" and out.message_claims_ok is False and out.stale_fact_ids == ["f1", "f2"]


def test_google_listing_phones_are_not_checked_on_the_site() -> None:
    out, _ = audit.check_pages(
        LEAD,
        facts=[],
        contact={"phone_e164": "+919820012345", "source": "google_listing"},
        fetch=lambda urls: {"https://c.example.com/": "text"},
        still_there=contains,
    )
    assert not out.phone_checked and out.phone_still_present is None


def test_summary_against_targets() -> None:
    a = audit.LeadAudit(
        "1",
        "b",
        "clinics-in",
        "n",
        "A",
        facts_checked=10,
        facts_still_verify=10,
        phone_checked=True,
        phone_still_present=True,
        audit_grade="A",
        agreement="same",
        message_claims_ok=True,
    )
    b = audit.LeadAudit(
        "2",
        "b",
        "clinics-in",
        "n",
        "A",
        facts_checked=10,
        facts_still_verify=8,
        phone_checked=True,
        phone_still_present=False,
        audit_grade="C",
        agreement="two_plus",
        message_claims_ok=True,
    )
    s = audit.summarise([a, b])
    assert s["grade_agreement"] == 0.5 and s["facts_still_verify"] == 0.9 and s["phones_still_present"] == 0.5
    assert {m["measure"] for m in s["missed"]} == {"grade_agreement", "facts_still_verify", "phones_still_present"}


@pytest.fixture
def recent_leads(engine_db: str) -> list[str]:
    """Three committed leads created yesterday in education-ae, removed afterwards."""
    ids: list[str] = []
    businesses: list[str] = []
    for grade in ("A", "B", "A"):
        tag = uuid.uuid4().hex[:8]
        biz = db.fetch_one(
            "insert into public.businesses (segment_id, name, norm_name, country, city, website, web_domain) values "
            "('education-ae', %s, %s, 'ae', 'Dubai', %s, %s) returning id::text as id",
            [f"Audit Academy {tag}", f"audit academy {tag}", f"https://{tag}.example.com/", f"{tag}.example.com"],
        )
        assert biz is not None
        businesses.append(biz["id"])
        db.execute(
            "insert into public.facts (business_id, field, value, quote, url, verified) values "
            "(%s, 'branches', '{\"count\": 2}', 'Two campuses in Dubai', %s, true)",
            [biz["id"], f"https://{tag}.example.com/"],
        )
        db.execute(
            "insert into public.contacts (business_id, phone_e164, phone_type, source, verified) "
            "values (%s, '+971501234567', 'mobile', 'website', true)",
            [biz["id"]],
        )
        lead = db.fetch_one(
            "insert into public.leads (business_id, segment_id, grade, pitch_mode, message, created_at) "
            "values (%s, 'education-ae', %s, 'visible_pain', 'Hi there', now() - interval '1 day') returning id::text as id",
            [biz["id"], grade],
        )
        assert lead is not None
        ids.append(lead["id"])
    yield ids
    db.execute("delete from public.leads where id = any(%s::uuid[])", [ids])
    db.execute("delete from public.businesses where id = any(%s::uuid[])", [businesses])


def test_weekly_audit_stores_a_report_and_a_queue(recent_leads: list[str]) -> None:
    def fetch(urls: list[str]) -> dict[str, str]:
        return {urls[0]: "Two campuses in Dubai. WhatsApp +971 50 123 4567"}

    def judge(inputs: Mapping[str, Any], lead_id: str) -> AuditResult:
        return AuditResult(
            audit_grade="B",
            agrees=True,
            stale_facts=[],
            phone_still_present=True,
            message_claims_ok=True,
            notes="Fine.",
        )

    with run_context("weekly", Options(segments=["education-ae"])) as rc:
        result = audit.weekly(rc, fetch=fetch, still_there=contains, judge=judge)
    summary = result["summary"]
    assert summary["leads"] == 3 and summary["facts_still_verify"] == 1.0 and summary["phones_still_present"] == 1.0
    assert summary["grade_agreement"] == 1.0 and len(result["queue"]) == 3 and set(result["queue"]) <= set(recent_leads)
    row = db.fetch_one("select kind, content, markdown from public.reports where id = %s", [result["report_id"]])
    assert row is not None and row["kind"] == "audit" and row["content"]["queue"] == result["queue"]
    assert row["markdown"].startswith("# Weekly audit")
    db.execute("delete from public.reports where id = %s", [result["report_id"]])


def test_weekly_audit_dry_run_makes_no_ai_calls_and_stores_nothing(recent_leads: list[str]) -> None:
    def judge(inputs: Mapping[str, Any], lead_id: str) -> AuditResult:
        raise AssertionError("no AI in a dry run")

    before = db.scalar("select count(*) from public.reports where kind = 'audit'")
    with run_context("weekly", Options(segments=["education-ae"], dry_run=True)) as rc:
        result = audit.weekly(
            rc, fetch=lambda urls: {}, still_there=contains, judge=judge, as_of=datetime.now(UTC) + timedelta(minutes=1)
        )
    assert result["report_id"] is None and result["summary"]["judged"] == 0
    assert db.scalar("select count(*) from public.reports where kind = 'audit'") == before
