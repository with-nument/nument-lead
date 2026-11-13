"""Steps 10 to 12 against a throwaway Postgres: verify, score, judge and message on one seeded business.

Everything runs in the `education-ae` segment, which no other test file writes to. The AI router is a fake.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.models import Claim, LeadJudgement, MessageCheck, MessageDraft
from nument_engine.pipeline import judge, message, score, verify
from nument_engine.pipeline.verify import VerifyDeps

from . import pipeline_fakes as pf
from .pipeline_fakes import FakeRouter, rc_for

DEPS = VerifyDeps(mx=lambda domain: True)  # never DNS in tests

HOME_TEXT = (
    "Bright Minds Academy\nIELTS and SAT preparation in Al Barsha, Dubai.\n"
    "Call us on +971 50 123 4567 for a free trial class.\nOur 3 branches serve 2,000 students every year."
)
TEAM_TEXT = (
    "Our team\nSara Khan, Founder and Director\n12 certified trainers\nReach Sara directly at +971 55 765 4321\n"
    "Omar Haddad, Co-founder and Head of Academics, leads curriculum design across all centres."
)
CONTACT_TEXT = "Contact us\nOffice: 04 331 2222\nEmail: admissions@brightminds.ae"


@pytest.fixture
def pipeline_db(engine_db: str) -> Iterator[str]:
    """The test segment starts empty and is left empty (test_segments deletes and re-inserts it)."""
    pf.wipe_segment(engine_db)
    yield engine_db
    pf.wipe_segment(engine_db)


def seed_academy(dsn: str, **business: Any) -> dict[str, str]:
    with pf.connect(dsn) as conn:
        bid = pf.business(conn, **business)
        domain = conn.execute("select web_domain from public.businesses where id = %s", [bid]).fetchone()["web_domain"]
        home, team, contact = f"https://{domain}/", f"https://{domain}/our-team/", f"https://{domain}/contact/"
        pf.page(conn, bid, home, HOME_TEXT)
        pf.page(conn, bid, team, TEAM_TEXT)
        pf.page(conn, bid, contact, CONTACT_TEXT.replace("brightminds.ae", domain))
        ids = {"business": bid, "domain": domain}
        ids["name"] = pf.fact(
            conn, bid, "business_name", {"name": "Bright Minds Academy"}, "Bright Minds Academy", home
        )
        ids["dm"] = pf.fact(
            conn,
            bid,
            "decision_maker",
            {"name": "Sara Khan", "role": "Founder and Director", "is_decision_maker": True},
            "Sara Khan, Founder and Director",
            team,
        )
        pf.fact(
            conn,
            bid,
            "decision_maker",
            {"name": "Omar Haddad", "role": "Co-founder and Head of Academics", "is_decision_maker": True},
            "Omar Haddad, Co-founder and Head of Academics",
            team,
        )
        pf.fact(
            conn,
            bid,
            "phone",
            {"number": "+971 50 123 4567", "label": "trial class", "belongs_to": "business"},
            "Call us on +971 50 123 4567 for a free trial class.",
            home,
        )
        pf.fact(
            conn,
            bid,
            "phone",
            {"number": "+971 55 765 4321", "belongs_to": "person"},
            "Reach Sara directly at +971 55 765 4321",
            team,
        )
        pf.fact(conn, bid, "phone", {"number": "04 331 2222", "label": "office"}, "Office: 04 331 2222", contact)
        pf.fact(conn, bid, "email", {"email": f"admissions@{domain}"}, f"Email: admissions@{domain}", contact)
        ids["branches"] = pf.fact(
            conn, bid, "branches", {"count": 3}, "Our 3 branches serve 2,000 students every year.", home
        )
        pf.fact(conn, bid, "staff_or_doctors", {"count": 12}, "12 certified trainers", team)
        pf.fact(
            conn, bid, "service", {"name": "IELTS preparation"}, "IELTS and SAT preparation in Al Barsha, Dubai.", home
        )
        ids["invented"] = pf.fact(
            conn,
            bid,
            "price_point",
            {"item": "IELTS course", "amount": 12000, "currency": "AED"},
            "IELTS course fee AED 12,000 with a money back guarantee",
            home,
        )
        ids["hiring"] = pf.signal(
            conn,
            bid,
            "hiring_frontdesk",
            "visible_pain",
            8,
            2,
            30,
            quote="We are hiring an admissions counsellor to handle WhatsApp enquiries",
            details={"role": "admissions counsellor"},
        )
        ids["reviews"] = pf.signal(
            conn,
            bid,
            "review_pain",
            "visible_pain",
            6,
            3,
            90,
            source="places",
            quote="reviews mention unanswered calls",
        )
    return ids


def snapshot(bid: str) -> dict[str, Any]:
    facts = db.fetch_all(
        "select id, verified, verify_score, verified_at, url from public.facts where business_id = %s order by id",
        [bid],
    )
    contacts = db.fetch_all(
        "select phone_e164, email, name, is_decision_maker, verified from public.contacts "
        "where business_id = %s order by phone_e164, email, name",
        [bid],
    )
    biz = db.fetch_one(
        "select status, reject_reason, branches_count, staff_count from public.businesses where id = %s", [bid]
    )
    return {"facts": facts, "contacts": contacts, "business": biz}


# ---------------------------------------------------------------------------
# Step 10
# ---------------------------------------------------------------------------


def test_verify_writes_facts_contacts_and_status_and_is_idempotent(pipeline_db: str) -> None:
    ids = seed_academy(pipeline_db)
    stats = verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
    assert stats["businesses"] == 1 and stats["status.researched"] == 1 and "errors" not in stats
    snap = snapshot(ids["business"])
    by_id = {str(f["id"]): f for f in snap["facts"]}
    assert by_id[ids["invented"]]["verified"] is False
    assert all(f["verified"] and f["verified_at"] is not None for i, f in by_id.items() if i != ids["invented"])
    phones = {c["phone_e164"]: c for c in snap["contacts"] if c["phone_e164"]}
    assert set(phones) == {"+971501234567", "+971557654321", "+97143312222"}
    assert phones["+971557654321"]["is_decision_maker"] and phones["+971557654321"]["name"] == "Sara Khan"
    named = [c for c in snap["contacts"] if not c["phone_e164"] and not c["email"]]
    assert [(c["name"], c["is_decision_maker"]) for c in named] == [("Omar Haddad", True)]
    assert snap["business"] == {"status": "researched", "reject_reason": None, "branches_count": 3, "staff_count": 12}
    site = db.fetch_one(
        "select value, model, verified from public.facts where business_id = %s and field = 'website_status'",
        [ids["business"]],
    )
    assert site is not None and site["value"]["status"] == "live" and site["model"] == "rule" and site["verified"]
    again = verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
    assert again.get("businesses", 0) == 0
    assert snapshot(ids["business"]) == snap


def test_verify_dry_run_writes_nothing(pipeline_db: str) -> None:
    ids = seed_academy(pipeline_db)
    before = snapshot(ids["business"])
    verify.run(rc_for(dry_run=True), deps=DEPS)
    assert snapshot(ids["business"]) == before


def test_suppressed_domain_and_phone(pipeline_db: str) -> None:
    ids = seed_academy(pipeline_db)
    other = seed_academy(pipeline_db)
    with pf.connect(pipeline_db) as conn:
        conn.execute("insert into public.suppression (web_domain, reason) values (%s, 'opt_out')", [ids["domain"]])
        conn.execute(
            "insert into public.suppression (phone_e164, reason) values ('+971557654321', 'opt_out') "
            "on conflict do nothing"
        )
    try:
        verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
        assert snapshot(ids["business"])["business"]["status"] == "suppressed"
        dm = db.fetch_one(
            "select do_not_contact from public.contacts where business_id = %s and phone_e164 = '+971557654321'",
            [other["business"]],
        )
        assert dm is not None and dm["do_not_contact"] is True
    finally:
        with pf.connect(pipeline_db) as conn:
            conn.execute(
                "delete from public.suppression where web_domain = %s or phone_e164 = '+971557654321'", [ids["domain"]]
            )


# ---------------------------------------------------------------------------
# Step 11
# ---------------------------------------------------------------------------


def _lead(bid: str) -> dict[str, Any] | None:
    return db.fetch_one("select * from public.leads where business_id = %s order by created_at desc limit 1", [bid])


def test_score_creates_the_lead_and_rescoring_changes_nothing(pipeline_db: str) -> None:
    ids = seed_academy(pipeline_db)
    verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
    stats = score.run(rc_for())
    assert stats["leads.create"] == 1
    row = db.fetch_one("select * from public.scores where business_id = %s", [ids["business"]])
    assert row is not None
    # s2.0: need 24 (visible pain cap) + can pay 22/30 x 35 + fit 10 + reach 20 = 80
    assert (row["fit"], float(row["can_pay"]), float(row["intent"]), float(row["reach"])) == (3, 22, 24, 1)
    assert (float(row["total"]), row["grade"], row["pitch_mode"], row["version"]) == (80, "A", "visible_pain", "s2.0")
    assert row["judge_note"] and row["reasons"]["basis"]
    lead = _lead(ids["business"])
    assert lead is not None
    assert (lead["stage"], lead["grade"], lead["angle"], lead["channel"]) == ("new", "A", "frontdesk_load", "whatsapp")
    assert lead["test_group"] == "education-ae:visible_pain:frontdesk_load" and lead["score_id"] == row["id"]
    created = db.fetch_all("select source, type from public.activities where lead_id = %s", [lead["id"]])
    assert created == [{"source": "engine", "type": "lead_created"}]
    assert snapshot(ids["business"])["business"]["status"] == "qualified"
    again = score.run(rc_for())
    assert again["scores.unchanged"] == 1 and again.get("scores.new_rows", 0) == 0
    assert db.scalar("select count(*) from public.scores where business_id = %s", [ids["business"]]) == 1
    assert db.scalar("select count(*) from public.leads where business_id = %s", [ids["business"]]) == 1


def test_a_contacted_lead_keeps_every_field_after_a_rescore(pipeline_db: str) -> None:
    ids = seed_academy(pipeline_db)
    verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
    score.run(rc_for())
    lead = _lead(ids["business"])
    assert lead is not None
    with pf.connect(pipeline_db) as conn:
        conn.execute(
            "update public.leads set stage = 'contacted', notes = 'called, call back Friday' where id = %s",
            [lead["id"]],
        )
        pf.signal(conn, ids["business"], "public_ask", "stated_need", 10, 1, 14, quote="Looking for a CRM partner")
    before = _lead(ids["business"])
    stats = score.run(rc_for())
    assert stats["scores.new_rows"] == 1
    after = _lead(ids["business"])
    assert after == before


def test_grade_d_twice_closes_a_new_lead_as_not_a_fit(pipeline_db: str) -> None:
    with pf.connect(pipeline_db) as conn:
        bid = pf.business(conn, review_count=None, category="shop", subcategory=None)
        sid = pf.insert(
            conn,
            "scores",
            {"business_id": bid, "version": "s0.9", "fit": 1, "total": 20, "grade": "D", "pitch_mode": "fit_only"},
        )
        pf.insert(
            conn,
            "leads",
            {
                "business_id": bid,
                "segment_id": pf.TEST_SEGMENT,
                "score_id": sid,
                "grade": "D",
                "pitch_mode": "fit_only",
                "stage": "new",
            },
        )
    score.run(rc_for())
    lead = _lead(bid)
    assert lead is not None and lead["stage"] == "not_a_fit"
    change = db.fetch_one(
        "select source, payload from public.activities where lead_id = %s and type = 'stage_change'", [lead["id"]]
    )
    assert change is not None and change["source"] == "engine" and change["payload"]["to"] == "not_a_fit"


# ---------------------------------------------------------------------------
# Step 11.10 judge
# ---------------------------------------------------------------------------


def _judgement(grade: str, note: str, cite: str = "hiring") -> Any:
    def answer(inputs: dict[str, Any]) -> LeadJudgement:
        signal_ids = [s["id"] for s in inputs["signals"] if s["type"] == "hiring_frontdesk"]
        cited = ["S" + signal_ids[0]] if cite == "hiring" else [cite]
        return LeadJudgement(
            judge_grade=grade, cited_ids=cited, judge_note=note, best_angle="frontdesk_load", risks=[], confidence=0.8
        )  # type: ignore[arg-type]

    return answer


def test_judge_moves_the_number_stores_the_note_and_updates_the_new_lead(pipeline_db: str) -> None:
    ids = seed_academy(pipeline_db)
    verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
    score.run(rc_for())
    router = FakeRouter(
        {
            "judge_lead": _judgement(
                "B", "Hiring an admissions counsellor 2 days ago, with 180 Google reviews behind it."
            )
        }
    )
    stats = judge.run(rc_for(), router=router)
    assert stats["judged"] == 1 and stats["grade.down"] == 1
    assert router.calls[0].lead_id == str(_lead(ids["business"])["id"])  # type: ignore[index]
    assert all("+971" not in str(v) for v in router.calls[0].inputs["contacts_summary"])
    row = db.fetch_one("select * from public.scores where business_id = %s", [ids["business"]])
    # one grade lower takes 8 points: 80 becomes 72, a B, and the number and the grade agree
    assert row is not None and (row["grade"], row["judge_grade"], float(row["total"])) == ("B", "B", 72)
    assert row["reasons"]["rule_total"] == 80 and row["reasons"]["judge"]["adjust"] == -8
    assert row["judge_note"].startswith("Hiring an admissions counsellor")
    assert row["judge_model"] == "gemini:gemini-3-flash#judge_lead.v1"
    assert _lead(ids["business"])["grade"] == "B"  # type: ignore[index]
    assert score.run(rc_for())["scores.unchanged"] == 1  # the moved total does not make a new score row
    assert judge.run(rc_for(), router=FakeRouter({"judge_lead": []}))["selected"] == 0  # already judged


def test_judge_with_a_fake_citation_is_discarded(pipeline_db: str) -> None:
    ids = seed_academy(pipeline_db)
    verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
    score.run(rc_for())
    rule_note = db.scalar("select judge_note from public.scores where business_id = %s", [ids["business"]])
    stats = judge.run(rc_for(), router=FakeRouter({"judge_lead": _judgement("A", "Great lead.", cite="F-made-up")}))
    assert stats["judge_bad_citation"] == 1
    row = db.fetch_one("select * from public.scores where business_id = %s", [ids["business"]])
    assert row is not None and row["grade"] == "A" and row["judge_grade"] is None and row["judge_note"] == rule_note


# ---------------------------------------------------------------------------
# Step 12 messages
# ---------------------------------------------------------------------------

GOOD = (
    "Hi Sara, saw on your careers page that Bright Minds is hiring an admissions counsellor for WhatsApp "
    "enquiries. We're Nument, a small dev team. We build an AI admissions counsellor that answers course and fee "
    "questions in seconds and books the trial class. Want to see how it would work for you?"
)
ALT = (
    "Hi Sara, noticed Bright Minds is looking for an admissions counsellor. We're Nument, a small dev team, and we "
    "build WhatsApp assistants that reply to every student enquiry instantly and book trial classes, so the new "
    "hire only calls students who are ready. Is the role still open?"
)


def _draft(inputs: dict[str, Any], message_text: str = GOOD) -> MessageDraft:
    hiring = next(s["id"] for s in inputs["signals"] if s["type"] == "hiring_frontdesk")
    return MessageDraft(
        message=message_text.replace("Bright Minds", inputs["business_name"].rsplit(" ", 1)[0]),
        message_alt=ALT.replace("Bright Minds", inputs["business_name"].rsplit(" ", 1)[0]),
        followup_d3="Hi Sara, one more idea: the same assistant can remind students a day before their trial class. "
        "Want a short demo?",
        followup_d7="Hi Sara, I don't want to crowd your inbox. Shall I close this for now?",
        claims=[Claim(text="hiring an admissions counsellor", ids=[f"S{hiring}"])],
    )


def _ready_lead(dsn: str) -> dict[str, str]:
    ids = seed_academy(dsn)
    verify.run(rc_for(), router=FakeRouter({}), deps=DEPS)
    score.run(rc_for())
    return ids


def test_message_is_written_checked_by_another_model_and_stored(pipeline_db: str) -> None:
    ids = _ready_lead(pipeline_db)
    router = FakeRouter({"write_message": _draft, "check_message": [MessageCheck(score=9, issues=[])]})
    stats = message.run(rc_for(), router=router)
    assert stats["stored"] == 1 and router.tasks() == ["write_message", "check_message"]
    assert router.calls[1].exclude_model == "gemini-3-flash"
    inputs = router.calls[0].inputs
    assert inputs["greeting"] == "Hi Sara," and inputs["pitch_mode"] == "visible_pain"
    assert inputs["seen_where"] == "your careers page"
    assert "+971" not in str(inputs) and "@" not in str(inputs["facts"])
    lead = _lead(ids["business"])
    assert lead is not None and lead["message"].startswith("Hi Sara, saw on your careers page")
    assert lead["message_model"] == "gemini:gemini-3-flash#write_message.v1"
    assert float(lead["message_check_score"]) == 9 and lead["followup_d7"].endswith("Shall I close this for now?")
    kinds = db.fetch_all(
        "select type, payload from public.activities where lead_id = %s and type in ('ai_output', 'message_flagged')",
        [lead["id"]],
    )
    assert [k["type"] for k in kinds] == ["ai_output"] and kinds[0]["payload"]["cited_ids"]
    assert message.run(rc_for(), router=FakeRouter({}))["selected"] == 0


def test_low_critic_score_gets_one_rewrite_then_a_flag(pipeline_db: str) -> None:
    ids = _ready_lead(pipeline_db)
    router = FakeRouter(
        {
            "write_message": _draft,
            "check_message": [
                MessageCheck(score=6, issues=["too generic"]),
                MessageCheck(score=8, issues=["still generic"]),
            ],
        }
    )
    stats = message.run(rc_for(), router=router)
    assert router.tasks() == ["write_message", "check_message", "write_message", "check_message"]
    assert router.calls[2].inputs["feedback"] == ["too generic"]
    assert stats["flagged.needs_edit"] == 1
    lead = _lead(ids["business"])
    assert lead is not None and float(lead["message_check_score"]) == 8
    flag = db.fetch_one(
        "select payload from public.activities where lead_id = %s and type = 'message_flagged'", [lead["id"]]
    )
    assert flag is not None and "reviewer score 8 of 10" in flag["payload"]["issues"]


def test_a_message_that_fails_lint_twice_is_not_stored(pipeline_db: str) -> None:
    ids = _ready_lead(pipeline_db)
    bad = "Dear Sir, we are a leading AI-powered company. Visit www.nument.in today!"
    router = FakeRouter({"write_message": lambda i: _draft(i, bad), "check_message": []})
    stats = message.run(rc_for(), router=router)
    assert stats["flagged.not_stored"] == 1 and router.tasks() == ["write_message", "write_message"]
    lead = _lead(ids["business"])
    assert lead is not None and lead["message"] is None


def test_an_edited_message_is_never_overwritten_unless_regenerate_is_pressed(pipeline_db: str) -> None:
    ids = _ready_lead(pipeline_db)
    lead = _lead(ids["business"])
    assert lead is not None
    with pf.connect(pipeline_db) as conn:
        conn.execute(
            "insert into public.activities (lead_id, source, type, payload) values (%s, 'app', 'message_edited', '{}')",
            [lead["id"]],
        )
    assert message.run(rc_for(), router=FakeRouter({}))["selected"] == 0
    with pf.connect(pipeline_db) as conn:
        conn.execute(
            "update public.leads set message = 'Hi Sara, my own words', regen_requested_at = %s where id = %s",
            [datetime.now(UTC) + timedelta(seconds=1), lead["id"]],
        )
    router = FakeRouter({"write_message": _draft, "check_message": [MessageCheck(score=10, issues=[])]})
    assert message.run(rc_for(), router=router)["stored"] == 1
    after = _lead(ids["business"])
    assert after is not None and after["message"].startswith("Hi Sara, saw") and after["regen_requested_at"] is None


def test_no_mobile_means_an_email_variant(pipeline_db: str) -> None:
    ids = _ready_lead(pipeline_db)
    lead = _lead(ids["business"])
    assert lead is not None
    with pf.connect(pipeline_db) as conn:
        conn.execute("update public.leads set channel = 'email' where id = %s", [lead["id"]])

    def draft(inputs: dict[str, Any]) -> MessageDraft:
        assert inputs["needs_email"] is True
        return _draft(inputs).model_copy(
            update={
                "email_subject": "Admissions enquiries at Bright Minds",
                "email_body": " ".join(
                    [ALT.replace("Bright Minds", inputs["business_name"].rsplit(" ", 1)[0])] * 2
                ).replace("Is the role still open? Hi Sara,", "Also,")
                + " Aditya from Nument",
            }
        )

    router = FakeRouter({"write_message": draft, "check_message": [MessageCheck(score=9, issues=[])]})
    message.run(rc_for(), router=router)
    after = _lead(ids["business"])
    assert after is not None and after["email_subject"] == "Admissions enquiries at Bright Minds"
    assert after["email_body"] and "Aditya from Nument" in after["email_body"]
