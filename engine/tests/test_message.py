"""Step 12 message rules: lint, claim check, variety, greetings and links (no database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nument_engine.pipeline import leads
from nument_engine.pipeline.lint import (
    ClaimContext,
    capitalised_names,
    claim_problems,
    closing_question,
    lint,
    opener,
    similarity,
)
from nument_engine.pipeline.message import (
    DayLog,
    greeting_for,
    seen_where,
    short_name,
    variety_problems,
    wants_message,
)
from nument_engine.pipeline.whatsapp import can_whatsapp, wa_links

# The plan's worked examples (12.12), joined into one paragraph as WhatsApp shows them.
GOOD = [
    "Hi Dr. Mehta, came across your post on Apna for a developer to build an appointment app for your skin clinics. "
    "We're Nument, a small dev team, and we build this kind of thing. Honestly I'd start with WhatsApp booking first, "
    "since that's where most patients already message you. Is the app still on your list?",
    "Hi Dr. Rao, saw you're hiring two front desk executives for the Baner branch. We're Nument, a small dev team. "
    "We set up an AI front desk on WhatsApp that answers enquiries in seconds and books the slot, so your new staff "
    "only handle the tricky calls. Worth a look?",
    "Hi, noticed a few Google reviews for Glow Skin Studio mention calls not getting picked up in the evenings. "
    "We're Nument, a small dev team. We build an AI front desk that replies on WhatsApp within seconds, even at "
    "11 pm, and books the appointment. Would that help the front desk?",
    "Hi Karan, came across your post looking for someone to set up a CRM and follow ups for your property leads. "
    "We're Nument, a small dev team, and we build exactly this. I'd start by having every portal lead answered on "
    "WhatsApp in seconds and pushed into the CRM. Still looking for someone on this?",
    "Hi Ritu, saw your post for admissions counsellors at the Indiranagar centre. We're Nument, a small dev team. "
    "We build an AI admissions counsellor on WhatsApp that answers fee and batch questions instantly and books the "
    "demo class. Is admission season keeping the team busy?",
    "Hi Dr. Khan, saw you're hiring a receptionist for the Jumeirah clinic. We're Nument, a small dev team. We set "
    "up an AI front desk on WhatsApp that answers patients in seconds, day or night, and books the slot so your "
    "receptionist handles the rest. Would that take some load off?",
]
BAD = {
    "Dear Sir, Greetings of the day! We are a leading AI-powered software company offering cutting-edge solutions "
    "for businesses like yours.": ["banned phrase 'dear sir'", "banned phrase 'ai-powered'", "0 question marks"],
    "Hi Karan, we can build your CRM for ₹1.5 lakh with 30 days free support. Interested? Shall we talk tomorrow?": [
        "mentions a price",
        "2 question marks",
    ],
    "Hi Dr. Mehta, check out our work at nument.in": ["contains a link", "does not name Nument"],
    "Hi Ritu \U0001f642 quick question about the clinic, we're Nument and we build things for clinics like yours, okay?": [
        "contains an emoji"
    ],
    "Hi Neha, saw Skyline Realty is hiring telecallers \u2013 we're Nument, a small dev team that builds AI lead "
    "qualifiers which answer every enquiry in seconds and book the site visit. Has the hiring worked out?": [
        "contains a dash"
    ],
}


@pytest.mark.parametrize("text", GOOD)
def test_the_plans_worked_examples_pass_lint(text: str) -> None:
    assert lint(text, "message") == []


@pytest.mark.parametrize(("text", "expected"), BAD.items())
def test_the_plans_bad_examples_fail_lint(text: str, expected: list[str]) -> None:
    problems = " | ".join(lint(text, "message"))
    for want in expected:
        assert want.split(" (")[0] in problems, (want, problems)


def test_follow_up_limits() -> None:
    assert (
        lint(
            "Hi Dr. Rao, one quick idea: the same setup can also remind patients a day before, which usually "
            "cuts no-shows. Want me to send a 60-sec video of it?",
            "followup_d3",
        )
        == []
    )
    assert lint("Hi Dr. Rao, I don't want to crowd your inbox. Shall I close this for now?", "followup_d7") == []
    assert "words" in lint("Shall I close this?", "followup_d7")[0]
    assert lint("Front desk enquiries at Calmveda", "email_subject") == []


def test_spaced_hyphen_is_a_dash_but_hyphenated_words_are_fine() -> None:
    assert "contains a dash" in lint("Hi, a front-desk idea - we're Nument. " + "word " * 30 + "ok?")
    assert "contains a dash" not in lint("Hi, a front-desk follow-up idea from Nument. " + "word " * 30 + "ok?")


# ---------------------------------------------------------------------------
# 12.6 claims
# ---------------------------------------------------------------------------

CTX = ClaimContext(
    known_ids={"f1": "f1", "s1": "s1"},
    evidence_text={
        "f1": "branches 12 projects in Gurugram",
        "s1": "hiring frontdesk hiring 2 telecallers Dwarka Expressway",
    },
    trusted_words={"neha", "skyline", "realty"},
)


def test_claims_pass_when_numbers_and_names_are_cited() -> None:
    text = (
        "Hi Neha, saw Skyline Realty is hiring two telecallers for the Dwarka Expressway projects. We're Nument, "
        "a small dev team. Has the hiring worked out?"
    )
    assert claim_problems([text], [["S1"]], CTX) == []


def test_claim_check_rejects_an_invented_number_and_name() -> None:
    text = "Hi Neha, saw your 40 projects in Gurugram and the new Sohna Heights launch. We're Nument. Busy month?"
    problems = claim_problems([text], [["f1"]], CTX)
    assert "number '40' is not in the cited facts" in problems
    assert "name 'Sohna Heights' is not in the cited facts" in problems


def test_claim_check_rejects_unknown_ids_and_missing_claims() -> None:
    assert claim_problems(["Hi Neha"], [["F999"]], CTX) == ["cites unknown id 'F999'"]
    assert claim_problems(["Hi Neha"], [], CTX) == ["no claim cites a verified fact or signal"]


def test_product_speed_numbers_are_not_claims_about_them() -> None:
    text = "Hi Neha, every enquiry answered in 5 seconds, even at 11 pm. We're Nument. Worth a look?"
    assert claim_problems([text], [["s1"]], CTX) == []


def test_capitalised_names_skip_sentence_starts() -> None:
    assert capitalised_names("Worth a look? We're Nument, a small team. Glow Skin Studio rocks.") == [
        "Nument",
        "Skin Studio",
    ]


# ---------------------------------------------------------------------------
# 12.7 variety
# ---------------------------------------------------------------------------


def test_opener_and_question() -> None:
    text = "Hi Dr. Rao, saw you're hiring two front desk executives. We're Nument. Worth a look?"
    assert opener(text) == "saw you re hiring"
    assert closing_question(text) == "worth a look?"
    assert similarity(text, text.replace("Rao", "Shah")) > 85


def test_variety_rules() -> None:
    day = DayLog()
    base = "Hi Dr. {n}, saw you're hiring front desk staff at the {n} clinic. We're Nument, a small dev team. {q}"
    for i, q in enumerate(["Worth a look?", "Is the role open?", "Busy season?"]):
        day.add("clinics-in", None, base.format(n=f"Name{i}", q=q))
    problems = variety_problems(base.format(n="Fresh", q="Worth a look?"), "clinics-in", None, day)
    assert any("too similar" in p for p in problems)
    assert any("opener" in p for p in problems)
    assert any("question" in p for p in problems)
    other = "Hi, noticed a few Google reviews mention calls going unanswered after 7. We're Nument. Would that help?"
    assert variety_problems(other, "clinics-in", None, day) == []


# ---------------------------------------------------------------------------
# 12.1 and 12.2 inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("contact", "greeting"),
    [
        ({"name": "Dr. Anil Rao", "role": "Founder"}, "Hi Dr. Rao,"),
        ({"name": "Meera Shah", "role": "Consultant Dermatologist"}, "Hi Dr. Shah,"),
        ({"name": "dhruv agarwal", "role": "Founder"}, "Hi Dhruv,"),
        ({"name": "Ahmed Al Mansoori", "role": "Managing Director"}, "Hi Ahmed,"),
        ({"name": "R. Kumar", "role": "Owner"}, "Hi,"),
        ({"name": None, "role": None}, "Hi,"),
        (None, "Hi,"),
    ],
)
def test_greeting_rules(contact: dict[str, str | None] | None, greeting: str) -> None:
    assert greeting_for(contact)[0] == greeting


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("Calmveda Wellness Pvt Ltd", "Calmveda Wellness"),
        ("Skyline Realty Private Limited", "Skyline Realty"),
        ("Smile Studio Dental FZ-LLC", "Smile Studio Dental"),
        ("GlobalEdge LLP", "GlobalEdge"),
        ("Ltd", "Ltd"),
    ],
)
def test_short_business_names(name: str, short: str) -> None:
    assert short_name(name) == short


def test_seen_where_labels() -> None:
    assert seen_where({"source": "apna"}, {}) == "your post on Apna"
    assert seen_where({"source": "places"}, {}) == "a few of your Google reviews"
    assert seen_where(None, {"website": "https://x.in"}) == "your website"
    assert seen_where(None, {}) == "your Google listing"


def test_wants_message_respects_edits_and_regenerate() -> None:
    now = datetime.now(UTC)
    edited = leads.MessageHistory(edited=True, edited_at=now)
    assert wants_message({"message": None, "regen_requested_at": None}, leads.MessageHistory())
    assert not wants_message({"message": "x", "regen_requested_at": None}, leads.MessageHistory())
    assert not wants_message({"message": None, "regen_requested_at": None}, edited)
    assert not wants_message({"message": "x", "regen_requested_at": now - timedelta(minutes=5)}, edited)
    assert wants_message({"message": "x", "regen_requested_at": now + timedelta(minutes=5)}, edited)


# ---------------------------------------------------------------------------
# 12.10 WhatsApp links
# ---------------------------------------------------------------------------


def test_whatsapp_links_for_india_and_uae() -> None:
    msg = "Hi Dr. Rao, saw your post.\nWorth a look?"
    india = wa_links("+919876543210", msg)
    assert india["web"] == (
        "https://web.whatsapp.com/send?phone=919876543210&text=Hi%20Dr.%20Rao%2C%20saw%20your"
        "%20post.%0AWorth%20a%20look%3F"
    )
    assert india["app"].startswith("https://wa.me/919876543210?text=Hi%20Dr.")
    assert wa_links("+971501234567", msg)["app"].startswith("https://wa.me/971501234567?")
    with pytest.raises(ValueError):
        wa_links("98765 43210", msg)


def test_only_usable_mobiles_get_a_whatsapp_link() -> None:
    mobile = {"phone_e164": "+919876543210", "phone_type": "mobile", "do_not_contact": False}
    assert can_whatsapp(mobile)
    assert not can_whatsapp({**mobile, "phone_type": "landline"})
    assert not can_whatsapp({**mobile, "do_not_contact": True})
    assert not can_whatsapp(mobile, frozenset({"+919876543210"}))
