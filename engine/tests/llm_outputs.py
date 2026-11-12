"""Valid example outputs for every AI task, used by the router, batch and health tests."""

from __future__ import annotations

from pydantic import BaseModel

from nument_engine.models import (
    AuditResult,
    Claim,
    FactsExtraction,
    FlaggedVerification,
    LeadJudgement,
    MessageCheck,
    MessageDraft,
    NewsClassification,
    PageChangeClassification,
    PersonFact,
    PhoneFact,
    PublicAskItem,
    PublicAskResults,
    ReviewLookup,
    SignalClassification,
    TextFact,
)

MESSAGE = (
    "Hi Dr. Mehta, saw on your careers page that you're hiring a patient coordinator for Baner. We're Nument, "
    "a small dev team. An AI front desk could answer WhatsApp enquiries in seconds and book the slot. Worth a look?"
)

OUTPUTS: dict[str, BaseModel] = {
    "classify_signal": SignalClassification(
        is_relevant=True,
        role_category="frontdesk",
        employer_name="Sunrise Dental Clinic",
        employer_website=None,
        employer_domain="clinics",
        city="Pune",
        evidence_quote="is hiring a front desk receptionist",
        confidence=0.92,
    ),
    "classify_news": NewsClassification(
        relevant=True,
        business_name="Sunrise Dental Clinic",
        city="Pune",
        signal_type="new_branch",
        quote="Sunrise Dental Clinic has opened its second branch in Kothrud, Pune",
        confidence=0.9,
    ),
    "classify_page_change": PageChangeClassification(
        change_type="new_job",
        roles=["Patient Coordinator"],
        quote="We are hiring: Patient Coordinator (Baner).",
        signal_type="hiring_frontdesk",
    ),
    "extract_facts": FactsExtraction(
        business_name=TextFact(
            value="Sunrise Dental Clinic", quote="Sunrise Dental Clinic.", url="https://example.com/"
        ),
        decision_makers=[
            PersonFact(
                name="Dr. Asha Mehta",
                role="Chief Dentist",
                is_decision_maker=True,
                quote="Founded by Dr. Asha Mehta, Chief Dentist",
                url="https://example.com/",
            )
        ],
        phones=[
            PhoneFact(
                number="+91 98200 00000",
                label="reception",
                belongs_to="business",
                quote="Call reception on +91 98200 00000",
                url="https://example.com/",
            )
        ],
    ),
    "verify_flagged": FlaggedVerification(trusted_fact_id="F1", is_competitor=None, reason="The home page lists two."),
    "judge_lead": LeadJudgement(
        judge_grade="A",
        cited_ids=["F1", "S1"],
        judge_note="Hiring a patient coordinator 5 days ago across 2 branches.",
        best_angle="hire_complement",
        risks=[],
        confidence=0.8,
    ),
    "write_message": MessageDraft(
        message=MESSAGE,
        message_alt=MESSAGE.replace("Worth a look?", "Is the role still open?"),
        followup_d3="One idea: the bot could also confirm tomorrow's appointments each evening. Want a short demo?",
        followup_d7="Shall I close this for now?",
        email_subject=None,
        email_body=None,
        claims=[Claim(text="hiring a patient coordinator for Baner", ids=["S1"])],
    ),
    "check_message": MessageCheck(score=9, issues=[], suggested_fix=None),
    "lookup_reviews": ReviewLookup(
        google_rating=4.6,
        google_review_count=874,
        google_quote="Google: 4.6 stars from 874 reviews",
        practo_rating=None,
        practo_story_count=None,
        practo_quote=None,
        complaint=None,
    ),
    "grounded_search": PublicAskResults(
        items=[
            PublicAskItem(
                poster_business="Smile Care Clinic",
                poster_city="Pune",
                need="A WhatsApp bot to book appointments.",
                quote="looking for someone to build a WhatsApp booking bot",
                url="https://forum.example.com/t/123",
                posted_date="2026-11-02",
            )
        ]
    ),
    "weekly_audit": AuditResult(
        audit_grade="B",
        agrees=True,
        stale_facts=[],
        phone_still_present=True,
        message_claims_ok=True,
        notes="Still a good lead.",
    ),
}
