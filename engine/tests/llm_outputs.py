"""Valid example outputs for every AI task, used by the router, batch and health tests."""

from __future__ import annotations

from pydantic import BaseModel

from nument_engine.models import (
    AuditResult,
    Claim,
    DecisionMakerLookup,
    EmailSequence,
    FactsExtraction,
    FeedJobClassification,
    FlaggedVerification,
    LeadJudgement,
    MessageCheck,
    MessageDraft,
    NewsClassification,
    OfferPick,
    PageChangeClassification,
    PersonFact,
    PhoneFact,
    PlanContent,
    PlanWeek,
    PrecallBrief,
    ProposalDraft,
    ProposalMilestone,
    PublicAskItem,
    PublicAskResults,
    ReplyClassification,
    ReplyDraft,
    ReviewLookup,
    ReviewPainClassification,
    ScreenSection,
    ScreenSpec,
    SignalClassification,
    StartupItemClassification,
    TextFact,
    WebsiteLookup,
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
    "classify_startup_item": StartupItemClassification(
        is_relevant=True,
        event="funding",
        company_name="Brightcart",
        company_website=None,
        hq_country="us",
        city="Austin",
        is_startup=True,
        team_size=3,
        round="pre_seed",
        amount_usd=600000.0,
        founders=["Maya Chen", "Leo Park"],
        evidence_quote="raised $600K in a pre-seed round",
        confidence=0.9,
    ),
    "pick_offer": OfferPick(
        offer_key="mvp_sprint",
        backup_offer_key="launch_kit",
        why_now="Brightcart just raised a pre-seed round and has no engineers yet.",
        cited_ids=["S1", "F1"],
        confidence=0.85,
    ),
    "write_email_sequence": EmailSequence(
        subject="your pre-seed round",
        day0="Hi Maya, congrats on Brightcart's pre-seed round. We're Nument, a small AI-first studio that ships "
        "MVPs in weeks with fixed scope. Want me to send a 1-page plan for Brightcart?",
        day0_alt=None,
        day3="Hi Maya, here's the 1-page plan for Brightcart: {plan_link}",
        day7="Hi Maya, here's something similar we built: {case_study}",
        day12="Hi Maya, should I close this out, or is later better?",
        claims=[Claim(text="pre-seed round", ids=["S1"])],
    ),
    "write_plan": PlanContent(
        headline="Brightcart ordering MVP in 5 weeks",
        their_goal="Let grocers take orders online.",
        scope_now=["Shop page", "Cart and checkout", "Grocer dashboard"],
        scope_later=["Delivery tracking"],
        timeline=[PlanWeek(week=1, deliverable="Design"), PlanWeek(week=5, deliverable="Launch")],
        typical_range="Projects like this usually run $4,000 to $8,000.",
        first_screen=ScreenSpec(
            app_name="Brightcart",
            title="Today's orders",
            sections=[ScreenSection(kind="list", label="Orders", items=["#1042 Ready"])],
        ),
        next_step="Book a 20-minute call to go through it.",
    ),
    "classify_reply": ReplyClassification(category="send_plan", confidence=0.92, summary="Wants the plan and a price."),
    "draft_reply": ReplyDraft(
        body="Hi Maya, here it is. Happy to walk you through it: "
        "https://cal.com/abhigyan-numentai/intro-call Team Nument"
    ),
    "write_precall_brief": PrecallBrief(
        summary="Brightcart, 3 people, pre-seed.",
        why_now="Just raised, no engineers.",
        what_they_need=["Web ordering MVP"],
        questions=["Deadline?", "Budget band?", "Who decides?"],
        offer_key="mvp_sprint",
    ),
    "write_proposal": ProposalDraft(
        title="Brightcart MVP",
        problem="Grocers cannot take orders online.",
        scope_must=["Ordering", "Dashboard"],
        milestones=[ProposalMilestone(name="Design and setup", weeks=1, deliverables=["Clickable design"])],
        total_range="$4,000 to $8,000",
        guarantee="If milestone 1 is not what we agreed, you do not pay for it.",
        retainer="Monthly product care after launch.",
        next_step="Approve milestone 1 to start.",
    ),
    "classify_feed_job": FeedJobClassification(
        is_relevant=True,
        company_name="Brightcart",
        company_website="https://brightcart.example",
        company_kind="product_company",
        hq_country="us",
        city="Austin",
        role="Full-stack engineer",
        contract=True,
        team_size=9,
        evidence_quote="Full-stack engineer (contract)",
        confidence=0.9,
    ),
    "find_decision_maker": DecisionMakerLookup(
        name="Asha Rao", role="Founder", line="Decision maker: Asha Rao, Founder at Brightcart Foods"
    ),
    "find_website": WebsiteLookup(website="https://brightcart.in", website_line="Website: https://brightcart.in"),
    "classify_reviews": ReviewPainClassification(
        has_pain=True,
        flags=["unanswered_calls"],
        complaining_reviews=[1],
        quote="Called five times to book, nobody picked up.",
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
