"""One-time import of the old lead engine (Step 20): mapping, idempotence, dry run, suppression, skip list."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nument_engine import db
from nument_engine.ops import migrate_legacy as ml
from nument_engine.pipeline.runs import Options, RunContext

ORGS = ("Lotus Diagnostic Clinic Pvt Ltd", "Skyline Realty Private Limited (Skyline)", "Bloom Candles", "Quark Labs")


def _lead(lead_id: str, org: str, **extra: Any) -> dict[str, Any]:
    base = {
        "lead_id": lead_id, "track": "A", "org": org, "name": "Asha Rao", "role": "Founder (per site); also CEO",
        "website": f"https://www.{lead_id.lower()}-test.in/about", "city": "Pune (head office)", "state": "Maharashtra",
        "country": "India", "source": "Internshala", "why": "Hiring two web developers this week.",
        "why_now_short": "Hiring 2 web developers", "why_now_date": "2026-10-01", "evidence_1": '"Web developer intern needed"',
        "evidence_url_1": f"https://internshala.com/{lead_id}", "evidence_date_1": "2026-10-01", "collected_at": "2026-10-01",
        "last_verified_at": "2026-10-16", "scored_at": "2026-11-10", "grade": "B", "listed": True, "win_chance": 60,
        "win_parts": {"need": 14, "fit": 37, "reach": 20, "caps": ["no direct ask"]}, "ai_fit": 2, "flags": ["aging_intent", "lqs_missing"],
        "phone": "+91 98000 00123", "phone_type": "mobile", "phone_status": "verified", "phone_belongs_to": "company",
        "phone_label": "Helpline", "phone_source_url": f"https://www.{lead_id.lower()}-test.in/contact",
        "phone_quote": "Helpline: +91 98000 00123", "email": "hello@example.in", "email_status": "verified",
        "ticket_est_min": 100000, "ticket_est_max": 300000, "ticket_basis": "Small web build",
        "wa_msg": "Hi Asha, saw you are hiring web developers. We're Nument. Still looking?", "wa_alt": "Hi Asha, alt text?",
        "wa_angle": "hire_complement", "site_has": {"booking": False, "whatsapp": True, "chat": False}, "team_size_band": "11-50",
    }  # fmt: skip
    return {**base, **extra}


def _clean() -> None:
    with db.tx() as conn:
        conn.execute("delete from public.source_records where source in ('legacy', 'legacy_skip')")
        conn.execute(
            "delete from public.leads where business_id in (select id from public.businesses where extra ? 'legacy_id')"
        )
        conn.execute("delete from public.businesses where extra ? 'legacy_id'")
        conn.execute("delete from public.suppression where reason in ('wrong_contact', 'opt_out')")
        conn.execute("delete from public.segments where id = any(%s)", [list(ml.LEGACY_SEGMENTS)])


@pytest.fixture
def legacy(tmp_path: Path, engine_db: str) -> Iterator[Path]:
    _clean()
    data = tmp_path / "data"
    data.mkdir()
    leads = [
        _lead("A-0901", ORGS[0]),
        _lead(
            "A-0902", ORGS[1], phone="+91-8010-222-888", wa_angle="hire_complement", email="sales@skyline.example.in"
        ),
        _lead(
            "A-0903",
            ORGS[2],
            grade="C",
            listed=True,
            source="Inc42",
            why="Raised seed funding last month.",
            why_now_short="Raised seed",
            phone="",
            phone_status="",
            wa_msg=None,
            wa_angle=None,
        ),
        _lead("A-0904", ORGS[3], grade="D", listed=False, phone="+91 98000 11111", phone_status="unverified"),
        {"lead_id": "D-0901", "track": "D", "org": "", "why": "Marketplace post", "grade": "D", "listed": False},
    ]
    (data / "leads.jsonl").write_text("".join(json.dumps(x) + "\n" for x in leads))
    reviews = [
        {"lead_id": "A-0901", "stage": "Contacted", "wa_at": "2026-11-12", "notes": "Sent 1 am", "updated_at": "2026-11-12T01:11:34",
         "history": [{"at": "2026-11-12T01:10:42", "field": "stage", "from": "New", "to": "Contacted", "sheet": "Google Sheet (master)"},
                     {"at": "2026-11-12T01:10:42", "field": "wa_at", "from": "", "to": "2026-11-12", "sheet": "Google Sheet (master)"}]},
        {"lead_id": "A-0902", "stage": "Wrong contact", "wa_at": "2026-11-12", "updated_at": "2026-11-12T01:11:34",
         "history": [{"at": "2026-11-12T01:10:42", "field": "stage", "from": "New", "to": "Wrong Contact", "sheet": "Google Sheet (master)"}]},
        {"lead_id": "A-0904", "history": [], "updated_at": "2026-10-16T16:27:57"},
    ]  # fmt: skip
    (data / "reviews.jsonl").write_text("".join(json.dumps(x) + "\n" for x in reviews))
    (data / "suppression.csv").write_text(
        "value,type,reason,added_at,requested_by\nstop@example.org,email,opt_out,2026-10-01,founder\n"
    )
    (data / "skip_list.txt").write_text(
        "# org | name | website domain | source url\n"
        "Bloom Candles |  | a-0903-test.in | \n"
        " | Some Person |  | \n"
        "Lotus Diagnostic Clinic Pvt Ltd |  | a-0901-test.in | \n"
    )
    yield tmp_path
    _clean()  # later test modules expect only the six seeded segments


def _count(query: str, *args: Any) -> Any:
    return db.scalar(query, list(args))


def test_dry_run_counts_everything_and_writes_nothing(legacy: Path) -> None:
    rc = RunContext(
        run_id=str(uuid.uuid4()), kind="manual", opts=Options(dry_run=True), started_at=dt.datetime.now(dt.UTC)
    )
    stats = ml.run(rc, root=legacy)
    assert stats["dry_run"] is True and stats["checks"]["legacy_source_records"] == 5
    assert _count("select count(*) from public.source_records where source = 'legacy'") == 0


def test_import_maps_the_old_engine(legacy: Path) -> None:
    stats = ml.migrate(legacy)
    checks = stats["checks"]
    assert checks["legacy_source_records"] == 5 and checks["legacy_businesses"] == 4
    assert checks["legacy_leads"] == 2 and checks["stages_beyond_new"] == {"contacted": 1, "wrong_contact": 1}
    assert checks["worked_with_wa_12_nov"] == 2 and checks["legacy_messages"] == 2
    assert checks["suppressed_wrong_contact"] == 1 and checks["legacy_skip_rows"] == 3
    assert stats["notes"]["skipped_marketplace"] == 1 and stats["notes"]["phones_not_verified_skipped"] == 1

    biz = {r["legacy"]: r for r in db.fetch_all(
        "select extra->>'legacy_id' as legacy, segment_id, name, web_domain, website, city, status, reject_reason, country "
        "from public.businesses where extra ? 'legacy_id'")}  # fmt: skip
    assert biz["A-0901"]["segment_id"] == "clinics-in" and biz["A-0901"]["name"] == "Lotus Diagnostic Clinic"
    assert biz["A-0901"]["web_domain"] == "a-0901-test.in" and biz["A-0901"]["website"] == "https://www.a-0901-test.in/"
    assert biz["A-0901"]["city"] == "Pune" and biz["A-0901"]["country"] == "in"
    assert biz["A-0901"]["status"] == "qualified"  # a lead: the skip list never rejects it
    assert biz["A-0902"]["segment_id"] == "realestate-in" and biz["A-0902"]["name"] == "Skyline Realty"
    assert (biz["A-0903"]["status"], biz["A-0903"]["reject_reason"]) == ("rejected", "legacy_skip")
    assert biz["A-0904"]["segment_id"] == "firms-in" and biz["A-0904"]["status"] == "dormant"
    seg = db.fetch_one("select enabled, daily_quota, domain from public.segments where id = 'firms-in'")
    assert seg == {"enabled": False, "daily_quota": 0, "domain": "firms"}


def test_leads_messages_history_and_wrong_contact(legacy: Path) -> None:
    ml.migrate(legacy)
    lead = db.fetch_one(
        "select l.*, b.name from public.leads l join public.businesses b on b.id = l.business_id where b.extra->>'legacy_id' = 'A-0901'"
    )
    assert lead is not None
    assert (lead["stage"], lead["wa_at"], lead["notes"], lead["message_model"]) == (
        "contacted",
        dt.date(2026, 11, 12),
        "Sent 1 am",
        "legacy",
    )
    assert lead["test_group"] == "clinics-in:stated_need:hire_complement" and lead["pitch_mode"] == "stated_need"
    acts = db.fetch_all(
        "select type, source, at, payload from public.activities where lead_id = %s order by at", [lead["id"]]
    )
    created = [a for a in acts if a["type"] == "lead_created"]
    assert len(created) == 1 and created[0]["payload"]["legacy_id"] == "A-0901"
    edits = [a for a in acts if a["type"] == "edit"]
    assert [(e["payload"]["field"], e["payload"]["to"]) for e in edits] == [
        ("stage", "contacted"),
        ("wa_at", "2026-11-12"),
    ]
    assert edits[0]["source"] == "sheet" and edits[0]["at"] == dt.datetime(2026, 11, 11, 19, 40, 42, tzinfo=dt.UTC)
    assert not [a for a in acts if a["type"] == "stage_change"]  # code never writes trigger-owned rows

    wrong = db.fetch_one(
        "select l.id, l.stage from public.leads l join public.businesses b on b.id = l.business_id where b.extra->>'legacy_id' = 'A-0902'"
    )
    assert wrong is not None and wrong["stage"] == "wrong_contact"
    assert _count("select reason from public.suppression where phone_e164 = '+918010222888'") == "wrong_contact"
    assert _count(
        "select bool_and(do_not_contact) from public.contacts c join public.leads l on l.business_id = c.business_id "
        "where l.id = %s and c.phone_e164 is not null",
        wrong["id"],
    )
    assert _count("select reason from public.suppression where email = 'stop@example.org'") == "opt_out"
    usable_email = _count(  # the wrong number is retired; the business email stays usable
        "select count(*) from public.v_primary_contact pc join public.leads l on l.business_id = pc.business_id "
        "where l.id = %s and pc.email = 'sales@skyline.example.in' and pc.phone_e164 is null",
        wrong["id"],
    )
    assert usable_email == 1


def test_contacts_signals_facts_and_scores(legacy: Path) -> None:
    ml.migrate(legacy)
    contacts = db.fetch_all(
        "select c.name, c.role, c.phone_e164, c.phone_type, c.email, c.source, c.is_decision_maker, c.verified "
        "from public.contacts c join public.businesses b on b.id = c.business_id where b.extra->>'legacy_id' = 'A-0901' order by c.name"
    )
    person = next(c for c in contacts if c["name"] == "Asha Rao")
    line = next(c for c in contacts if c["phone_e164"])
    mail = next(c for c in contacts if c["email"])
    assert person["role"] == "Founder" and person["is_decision_maker"] and person["phone_e164"] is None
    assert (line["phone_e164"], line["phone_type"], line["source"], line["email"]) == (
        "+919800000123",
        "mobile",
        "website",
        None,
    )
    assert (mail["email"], mail["phone_e164"], mail["name"]) == ("hello@example.in", None, None)  # its own row
    sig = db.fetch_one(
        "select type, category, points, quote, details, observed_at, expires_at from public.signals where dedupe_key = 'legacy:A-0901'"
    )
    assert sig is not None and (sig["type"], sig["category"], float(sig["points"])) == (
        "hiring_builder",
        "stated_need",
        8.0,
    )
    assert sig["quote"] == "Web developer intern needed" and sig["details"]["summary"] == "Hiring 2 web developers"
    assert sig["expires_at"] - sig["observed_at"] == dt.timedelta(days=30)
    funding = db.fetch_one("select type, points from public.signals where dedupe_key = 'legacy:A-0903'")
    assert funding is not None and funding["type"] == "funding" and float(funding["points"]) == 0
    fields = {r["field"] for r in db.fetch_all(
        "select f.field from public.facts f join public.businesses b on b.id = f.business_id where b.extra->>'legacy_id' = 'A-0901'")}  # fmt: skip
    assert {"sales_note", "staff_or_doctors", "booking_method", "whatsapp_present", "chat_widget"} <= fields
    score = db.fetch_one(
        "select s.version, s.total, s.grade, s.fit, s.reasons, s.judge_model from public.scores s "
        "join public.businesses b on b.id = s.business_id where b.extra->>'legacy_id' = 'A-0901'"
    )
    assert score is not None and (score["version"], float(score["total"]), score["grade"], score["fit"]) == (
        "legacy-v1",
        60.0,
        "B",
        2,
    )
    assert score["reasons"]["ticket_estimate"] == {"min": 100000, "max": 300000}
    assert score["reasons"]["watch_outs"] == ["need 31 to 90 days old"] and score["judge_model"] == "legacy"


def test_second_run_changes_nothing(legacy: Path) -> None:
    ml.migrate(legacy)
    again = ml.migrate(legacy)
    assert again["total_inserted"] == 0 and again["total_updated"] == 0, again
    assert again["checks"]["legacy_leads"] == 2


def test_segment_map_covers_every_old_business() -> None:
    mapping = ml.segment_map()
    assert len(mapping) == 84 and set(mapping.values()) <= {
        "clinics-in", "realestate-in", "education-in", "d2c-in", "firms-in", "wellness-in", "hospitality-in", "auto-in", "finance-in",
    }  # fmt: skip
    # the 13 leads contacted on 12 Nov 2026
    assert (
        mapping["A-0033"] == "clinics-in"
        and mapping["A-0045"] == "realestate-in"
        and mapping["C-0006"] == "education-in"
    )
    assert set(ml.LEGACY_SEGMENTS) >= {
        s for s in mapping.values() if s not in ("clinics-in", "realestate-in", "education-in")
    }


@pytest.mark.parametrize(
    ("old", "expected"),
    [
        ({"source": "Internshala", "why": "Hiring 2 web developers"}, "hiring_builder"),
        ({"source": "Internshala", "why": "Hiring a receptionist and telecaller"}, "hiring_frontdesk"),
        ({"source": "StartupTalky Community", "why": "asked for a partner"}, "public_ask"),
        ({"source": "Inc42", "why": "Raised Rs 10 Cr seed"}, "funding"),
        ({"source": "Org site", "why": "Issued a formal RFP for software"}, "tender"),
        ({"source": "Practitioner blog", "why": "Built DIY tools"}, None),
    ],
)
def test_signal_types(old: dict[str, Any], expected: str | None) -> None:
    assert ml.signal_type(old) == expected


def test_normalisation_matches_step_6() -> None:
    assert ml.norm_name("Dr. Sharma's Skin & Hair Clinic Pvt. Ltd.") == "dr sharma s skin and hair clinic"
    assert ml.web_domain("https://www.example.co.in/about?utm_source=x") == "example.co.in"
    assert ml.web_domain("https://drx.wixsite.com/home") == "drx.wixsite.com"
    assert ml.web_domain("https://www.linkedin.com/in/someone") is None
    assert ml.phone_e164("098100 12345") == ("+919810012345", "mobile")
    assert ml.phone_e164("011 4567 8901") == ("+911145678901", "landline")
    assert ml.parse_day("30 Oct' 26") == dt.date(2026, 10, 30)
