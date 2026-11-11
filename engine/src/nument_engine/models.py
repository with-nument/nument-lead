"""Shared names and models used across steps.

Part 1 holds the contract names from A.12 (stages, signal types, grades, ...). Each Literal mirrors a CHECK
constraint in `supabase/migrations`; `tests/test_models.py` compares them with a migrated database, so code
and schema cannot drift apart silently.

Part 2 holds the AI output models with the canonical names from A.13.1. Where two steps disagreed on the
fields, the step named in A.13.1 wins: SignalClassification (Step 7), FactsExtraction (Step 9),
FlaggedVerification (Step 10), LeadJudgement (Step 11), MessageDraft and MessageCheck (Step 12),
AuditResult (Step 17 with prompt A.10). The rest come from Step 4.8.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from pydantic import BaseModel, Field

# =========================================================================
# Part 1: contract names (A.12)
# =========================================================================

Domain = Literal["clinics", "realestate", "education", "d2c", "hospitality", "auto", "finance", "wellness", "firms"]
DOMAINS: Final[tuple[str, ...]] = get_args(Domain)

UserRole = Literal["admin", "caller", "viewer"]
USER_ROLES: Final[tuple[str, ...]] = get_args(UserRole)

# ---- Lead stages (A.12.2) -------------------------------------------------
Stage = Literal[
    "new",
    "contacted",
    "talking",
    "discovery_booked",
    "discovery_done",
    "proposal_sent",
    "won",
    "retainer",
    "lost",
    "not_now",
    "not_a_fit",
    "wrong_contact",
]
STAGES: Final[tuple[str, ...]] = get_args(Stage)
CLOSED_STAGES: Final[frozenset[str]] = frozenset({"won", "retainer", "lost", "not_now", "not_a_fit", "wrong_contact"})
OPEN_STAGES: Final[tuple[str, ...]] = tuple(s for s in STAGES if s not in CLOSED_STAGES)
STAGE_LABELS: Final[dict[str, str]] = {
    "new": "New",
    "contacted": "Contacted",
    "talking": "Talking",
    "discovery_booked": "Discovery booked",
    "discovery_done": "Discovery done",
    "proposal_sent": "Proposal sent",
    "won": "Won",
    "retainer": "Retainer",
    "lost": "Lost",
    "not_now": "Not now",
    "not_a_fit": "Not a fit",
    "wrong_contact": "Wrong contact",
}

# ---- Signals (A.12.3) -----------------------------------------------------
SignalType = Literal[
    "public_ask",
    "tender",
    "hiring_builder",
    "hiring_frontdesk",
    "review_pain",
    "ads_running",
    "no_booking",
    "slow_site",
    "new_place",
    "new_branch",
    "news",
    "funding",
]
SIGNAL_TYPES: Final[tuple[str, ...]] = get_args(SignalType)
SignalCategory = Literal["stated_need", "visible_pain", "growth", "money"]
SIGNAL_CATEGORIES: Final[tuple[str, ...]] = get_args(SignalCategory)
SIGNAL_CATEGORY: Final[dict[str, str]] = {
    "public_ask": "stated_need",
    "tender": "stated_need",
    "hiring_builder": "stated_need",
    "hiring_frontdesk": "visible_pain",
    "review_pain": "visible_pain",
    "ads_running": "visible_pain",
    "no_booking": "visible_pain",
    "slow_site": "visible_pain",
    "new_place": "growth",
    "new_branch": "growth",
    "news": "growth",
    "funding": "money",
}

# ---- Grades, pitch modes, test groups (A.12.4, A.12.9) ----------------------
Grade = Literal["A", "B", "C", "D"]
GRADES: Final[tuple[str, ...]] = get_args(Grade)
GRADE_MIN_TOTAL: Final[dict[str, int]] = {"A": 70, "B": 55, "C": 40}  # below the C threshold is D

PitchMode = Literal["stated_need", "visible_pain", "fit_only"]
PITCH_MODES: Final[tuple[str, ...]] = get_args(PitchMode)


def grade_for(total: float) -> Grade:
    """Grade from a 0 to 100 score total: A at 70 or more, B 55 to 69, C 40 to 54, D under 40."""
    if total >= GRADE_MIN_TOTAL["A"]:
        return "A"
    if total >= GRADE_MIN_TOTAL["B"]:
        return "B"
    if total >= GRADE_MIN_TOTAL["C"]:
        return "C"
    return "D"


def make_test_group(segment_id: str, pitch_mode: PitchMode, angle: str) -> str:
    """Test group key `{segment_id}:{pitch_mode}:{angle}`, for example `clinics-in:visible_pain:missed_calls`."""
    if pitch_mode not in PITCH_MODES:
        raise ValueError(f"unknown pitch mode {pitch_mode!r}")
    if not segment_id or not angle or ":" in segment_id or ":" in angle:
        raise ValueError("segment_id and angle must be non-empty and must not contain ':'")
    return f"{segment_id}:{pitch_mode}:{angle}"


# ---- Businesses and contacts (A.12.1) -------------------------------------
BusinessStatus = Literal["candidate", "queued", "researched", "qualified", "rejected", "suppressed", "dormant"]
BUSINESS_STATUSES: Final[tuple[str, ...]] = get_args(BusinessStatus)
PhoneType = Literal["mobile", "landline", "tollfree", "unknown"]
PHONE_TYPES: Final[tuple[str, ...]] = get_args(PhoneType)
ContactSource = Literal["website", "google_listing", "registry", "other"]
CONTACT_SOURCES: Final[tuple[str, ...]] = get_args(ContactSource)
Channel = Literal["whatsapp", "email", "form"]
CHANNELS: Final[tuple[str, ...]] = get_args(Channel)
RenderMode = Literal["http", "browser"]

# ---- Activities (0001_core.sql; A.13.5 rule 1) -----------------------------
ActivitySource = Literal["app", "sheet", "engine"]
ACTIVITY_SOURCES: Final[tuple[str, ...]] = get_args(ActivitySource)
ActivityType = Literal[
    # written by the lead triggers only
    "lead_created",
    "stage_change",
    "grade_change",
    "message_edited",
    # written by code
    "message_flagged",
    "regen_request",
    "sent",
    "followup_sent",
    "reply",
    "call",
    "meeting",
    "proposal",
    "proposal_upload",
    "note",
    "edit",
    "feedback",
    "skip",
    "wrong_contact",
    "undo",
    "merge",
    "ai_output",
    "conflict_overridden",
    "unknown_stage",
]
ACTIVITY_TYPES: Final[tuple[str, ...]] = get_args(ActivityType)
# The database triggers write these; code must never insert them (it labels db.tx(source, context) instead).
TRIGGER_ACTIVITY_TYPES: Final[frozenset[str]] = frozenset(
    {"lead_created", "stage_change", "grade_change", "message_edited"}
)

# ---- Operations -----------------------------------------------------------
RunKind = Literal["night", "morning", "sheet_sync", "weekly", "monthly", "manual"]
RUN_KINDS: Final[tuple[str, ...]] = get_args(RunKind)
RunStatus = Literal["running", "ok", "partial", "failed"]
RUN_STATUSES: Final[tuple[str, ...]] = get_args(RunStatus)
# costs.provider (A.13.5 rule 4): Places is google_places, grounded search google_search, cache hits cache.
CostProvider = Literal["gemini", "openai", "cache", "google_places", "google_search", "pagespeed", "other"]
COST_PROVIDERS: Final[tuple[str, ...]] = get_args(CostProvider)
LlmProvider = Literal["gemini", "openai"]
LLM_PROVIDERS: Final[tuple[str, ...]] = get_args(LlmProvider)
BatchStatus = Literal["submitted", "running", "completed", "failed", "expired", "cancelled"]
BATCH_STATUSES: Final[tuple[str, ...]] = get_args(BatchStatus)
SheetName = Literal["master", "caller"]
# source_records.source: a new registry adapter adds its key here and in a new migration (Step 2.6.1).
SourceName = Literal[
    "overture",
    "places",
    "art_registry",
    "osm",
    "apna",
    "grounded_search",
    "gdelt",
    "careers_watch",
    "adzuna",
    "practo",
    "legacy",
    "legacy_skip",
]
SOURCE_NAMES: Final[tuple[str, ...]] = get_args(SourceName)
# Inbox posts and custom queries (A.13.5 rule 9). The database also accepts the older Step 2 and
# Step 7 values (processed, running, done, failed) so no step's code is refused.
InboxStatus = Literal["new", "processing", "researched", "lead_created", "rejected"]
INBOX_STATUSES: Final[tuple[str, ...]] = get_args(InboxStatus)

# ---- AI tasks (A.12.5) ----------------------------------------------------
AITask = Literal[
    "classify_signal",
    "classify_news",
    "classify_page_change",
    "extract_facts",
    "verify_flagged",
    "judge_lead",
    "write_message",
    "check_message",
    "grounded_search",
    "weekly_audit",
]
AI_TASKS: Final[tuple[str, ...]] = get_args(AITask)


# =========================================================================
# Part 2: AI output models (A.13.1). Keep them flat: every field present, optional ones nullable.
# =========================================================================


class SignalClassification(BaseModel):
    """`classify_signal`: is this job post or post a signal we care about (Step 7.5.1)."""

    is_relevant: bool  # a real business hiring for a role we care about
    role_category: Literal["frontdesk", "builder", "other"]
    employer_name: str | None
    employer_website: str | None
    employer_domain: Literal[
        "clinics",
        "realestate",
        "education",
        "d2c",
        "hospitality",
        "auto",
        "insurance_loans",
        "fitness_salon",
        "firms_startups",
        "agency_or_staffing",
        "other",
    ]
    city: str | None
    evidence_quote: str  # exact sentence from the input proving the role
    confidence: float = Field(ge=0, le=1)


class NewsClassification(BaseModel):
    """`classify_news`: is a news article about a target business, and which signal (Step 4.8, Step 5.10)."""

    relevant: bool
    business_name: str | None
    city: str | None
    signal_type: Literal["new_branch", "news", "funding", "none"]
    quote: str | None
    confidence: float = Field(ge=0, le=1)


class PageChangeClassification(BaseModel):
    """`classify_page_change`: what changed on a careers or locations page (Step 4.8, Step 5.9)."""

    change_type: Literal["new_job", "new_branch", "removed", "cosmetic", "other"]
    roles: list[str]
    quote: str | None
    signal_type: Literal["hiring_builder", "hiring_frontdesk", "new_branch", "none"]


class PublicAskItem(BaseModel):
    """One public ask for a vendor found by grounded search (Step 5.11)."""

    poster_business: str | None
    poster_city: str | None
    need: str
    quote: str
    url: str
    posted_date: str | None


class PublicAskResults(BaseModel):
    """`grounded_search` structuring output (Step 5.11)."""

    items: list[PublicAskItem]


# ---- extract_facts (Step 9.12) ---------------------------------------------
Currency = Literal["INR", "AED", "SAR", "QAR", "GBP", "SGD", "USD", "AUD"]


class Quoted(BaseModel):
    """Every extracted fact carries the exact page text that proves it."""

    quote: str = Field(min_length=5, max_length=300, description="Exact text copied from the page TEXT")
    url: str = Field(description="Must be one of the PAGE URL lines in the input")


class PersonFact(Quoted):
    name: str
    role: str | None = None
    is_decision_maker: bool = Field(description="Owner, founder, director, CEO, managing partner, medical director")


class PhoneFact(Quoted):
    number: str
    label: str | None = Field(default=None, description="e.g. reception, WhatsApp, appointments, Dr. X")
    belongs_to: Literal["business", "person"]


class EmailFact(Quoted):
    email: str


class CountFact(Quoted):
    count: int = Field(ge=0)


class NameFact(Quoted):
    name: str


class PriceFact(Quoted):
    item: str
    amount: float = Field(ge=0)
    currency: Currency


class RoleFact(Quoted):
    title: str
    category: Literal["frontdesk", "builder", "other"]


class FlagFact(Quoted):
    value: bool


class TextFact(Quoted):
    value: str


class FactsExtraction(BaseModel):
    """`extract_facts`: facts from a business's own pages, each with a quote and a URL (Step 9.12)."""

    business_name: TextFact | None = None
    decision_makers: list[PersonFact] = Field(default_factory=list, max_length=5)
    phones: list[PhoneFact] = Field(default_factory=list, max_length=6)
    emails: list[EmailFact] = Field(default_factory=list, max_length=4)
    branches: CountFact | None = None
    staff_or_doctors: CountFact | None = None
    services: list[NameFact] = Field(default_factory=list, max_length=12)
    price_points: list[PriceFact] = Field(default_factory=list, max_length=10)
    booking_method: TextFact | None = Field(default=None, description="e.g. online form, call only, WhatsApp, Practo")
    whatsapp_present: FlagFact | None = None
    chat_widget: TextFact | None = None
    careers_roles: list[RoleFact] = Field(default_factory=list, max_length=10)
    in_house_tech: FlagFact | None = Field(
        default=None, description="True only if the page shows an in-house tech or IT team"
    )
    is_agency_or_vendor: FlagFact | None = Field(
        default=None, description="True if they SELL software, marketing or IT services"
    )
    languages: list[TextFact] = Field(default_factory=list, max_length=4)
    sales_notes: list[TextFact] = Field(
        default_factory=list, max_length=3, description="Quoted observations useful for a first message"
    )


class FlaggedVerification(BaseModel):
    """`verify_flagged`: settle a conflict between facts (Step 10.7)."""

    trusted_fact_id: str | None = Field(description="id of the fact to keep, or null if none can be trusted")
    is_competitor: bool | None = Field(default=None, description="only for the agency question")
    reason: str = Field(max_length=240)


class LeadJudgement(BaseModel):
    """`judge_lead`: the top model's second opinion on a graded lead (Step 11.10.3)."""

    judge_grade: Grade
    cited_ids: list[str] = Field(min_length=1, description="fact or signal ids supporting the grade")
    judge_note: str = Field(
        max_length=280, description="at most 2 plain sentences, why this lead is worth contacting now"
    )
    best_angle: str
    risks: list[str] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0, le=1)


class Claim(BaseModel):
    """A specific claim in a message and the fact or signal ids that prove it (Step 12)."""

    text: str = Field(description="the specific claim as it appears in the message")
    ids: list[str] = Field(min_length=1, description="fact or signal ids that prove it")


class MessageDraft(BaseModel):
    """`write_message`: first message, an alternative and two follow-ups (Step 12)."""

    message: str
    message_alt: str = Field(description="same lead, a different opener or angle")
    followup_d3: str = Field(description="adds one new useful thing, never 'just bumping this'")
    followup_d7: str = Field(description="polite close, for example 'Shall I close this for now?'")
    email_subject: str | None = None
    email_body: str | None = None
    claims: list[Claim]


class MessageCheck(BaseModel):
    """`check_message`: the critic's score out of 10 (Step 12.9)."""

    score: int = Field(ge=0, le=10)
    issues: list[str] = Field(default_factory=list, max_length=5)
    suggested_fix: str | None = None


class AuditResult(BaseModel):
    """`weekly_audit`: a stricter re-check of one lead from last week (Step 17.6, prompt A.10)."""

    audit_grade: Grade
    agrees: bool
    stale_facts: list[str]
    phone_still_present: bool
    message_claims_ok: bool
    notes: str = Field(max_length=400, description="at most 2 sentences")


AI_OUTPUT_MODELS: Final[dict[str, type[BaseModel]]] = {
    "classify_signal": SignalClassification,
    "classify_news": NewsClassification,
    "classify_page_change": PageChangeClassification,
    "extract_facts": FactsExtraction,
    "verify_flagged": FlaggedVerification,
    "judge_lead": LeadJudgement,
    "write_message": MessageDraft,
    "check_message": MessageCheck,
    "grounded_search": PublicAskResults,
    "weekly_audit": AuditResult,
}
