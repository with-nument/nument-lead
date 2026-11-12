"""Step 10 verification: quotes, phones, websites, competitors, contacts, conflicts (no database)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

import pytest

from nument_engine.models import FlaggedVerification
from nument_engine.pipeline import verify
from nument_engine.pipeline.phones import parse_phone
from nument_engine.pipeline.verify import (
    Bundle,
    Conflict,
    Exclusions,
    FlagAsker,
    Suppression,
    VerifyDeps,
    check_quote,
    find_conflicts,
    norm,
    plan_business,
    plan_contacts,
    resolve_by_rule,
    signals_to_expire,
    verify_quotes,
    website_status,
)
from nument_engine.segments import load_segments

from .pipeline_fakes import NOW, FakeRouter

SEGMENTS = load_segments()
CLINICS = SEGMENTS["clinics-in"]
EXCL = Exclusions.load()
NO_SUPPRESSION = Suppression(frozenset(), frozenset(), frozenset())
DEPS = VerifyDeps(mx=lambda domain: True, now=lambda: NOW)

HOME = "https://www.glowskin.in/"
CONTACT = "https://www.glowskin.in/contact-us/"
TEAM = "https://www.glowskin.in/our-doctors/"
HOME_TEXT = (
    "Glow Skin Studio\nAdvanced dermatology and laser care in Baner, Pune.\n"
    "Book a consultation today. Call +91 98765 43210 for appointments.\n"
    "Designed and developed by Pixel IT Solutions"
)
CONTACT_TEXT = "Contact us\nReception: (020) 2612 3456\nWhatsApp Dr. Anil Rao on 98220 12345\nEmail: hello@glowskin.in"
TEAM_TEXT = "Our doctors\nDr. Anil Rao, Founder and Medical Director, MD Dermatology\nDr. Meera Shah, Consultant"


def _page(pid: str, url: str, text: str, **over: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "business_id": "b1",
        "url": url,
        "text": text,
        "http_status": 200,
        "fetched_at": NOW - timedelta(hours=5),
        "render_mode": "http",
        "robots_allowed": True,
        **over,
    }


def _fact(fid: str, field: str, value: Any, quote: str | None, url: str, **over: Any) -> dict[str, Any]:
    return {
        "id": fid,
        "business_id": "b1",
        "field": field,
        "value": value,
        "quote": quote,
        "url": url,
        "page_id": None,
        "model": "gemini:gemini-3-flash#extract_facts.v1",
        "verified": False,
        "verify_score": None,
        "verified_at": None,
        "created_at": NOW - timedelta(hours=2),
        **over,
    }


def _bundle(facts: list[dict[str, Any]] | None = None, **over: Any) -> Bundle:
    business = {
        "id": "b1",
        "segment_id": "clinics-in",
        "name": "Glow Skin Studio",
        "country": "in",
        "website": HOME,
        "web_domain": "glowskin.in",
        "place_id": "ChIJtest",
        "places_fetched_at": None,
        "extra": {},
        **over.pop("business", {}),
    }
    pages = over.pop("pages", None) or [
        _page("p1", HOME, HOME_TEXT),
        _page("p2", CONTACT, CONTACT_TEXT),
        _page("p3", TEAM, TEAM_TEXT),
    ]
    return Bundle(
        business=business,
        pages=pages,
        facts=facts or [],
        signals=over.pop("signals", []),
        contacts=over.pop("contacts", []),
        records=over.pop("records", []),
    )


def _asker(answers: list[Any] | None = None) -> tuple[FlagAsker, FakeRouter]:
    router = FakeRouter({"verify_flagged": answers or []})
    return FlagAsker(router, "run-1"), router


# ---------------------------------------------------------------------------
# 10.2 quotes
# ---------------------------------------------------------------------------


def test_norm_makes_quotes_and_prices_comparable() -> None:
    # Apostrophes are dropped on both sides, so "Rao's" and "Rao\u2019s" compare equal.
    assert norm("  Dr.\u00a0Rao\u2019s  \u201cclinic\u201d\n\u20b91,500 ") == "dr. rao s clinic \u20b91 500"
    assert norm("Dr. Rao's clinic") == norm("Dr. Rao\u2019s clinic")


@pytest.mark.parametrize(
    ("quote", "ok", "why"),
    [
        ("Advanced dermatology and laser care in Baner, Pune.", True, "exact"),
        ("advanced  dermatology and laser care in baner pune", True, "exact"),
        ("Advanced dermatology and laser care at Baner, Pune", True, "fuzzy"),
        ("We are the best hair transplant centre in Mumbai", False, "quote_not_found"),
        ("Pune", False, "quote_too_short"),
    ],
)
def test_check_quote(quote: str, ok: bool, why: str) -> None:
    result = check_quote(quote, HOME_TEXT)
    assert (result.ok, result.why) == (ok, why)
    assert result.score == 100 if why == "exact" else True


def test_fuzzy_threshold_is_92() -> None:
    assert check_quote("Advanced dermatology and laser care at Baner, Pune", HOME_TEXT).score >= 92
    assert check_quote("Advanced dermatology & laser care at Baner Pune", HOME_TEXT).score < 92  # a paraphrase
    assert not check_quote("Dermatology and cosmetic laser treatments across Pune city", HOME_TEXT).ok


def test_quote_found_on_another_page_corrects_the_citation() -> None:
    facts = [
        _fact(
            "f1",
            "decision_maker",
            {"name": "Dr. Anil Rao", "role": "Founder"},
            "Dr. Anil Rao, Founder and Medical Director",
            HOME,
        )
    ]
    states = verify_quotes(_bundle(facts), "IN")
    assert states["f1"].verified and states["f1"].url == TEAM and states["f1"].why.endswith("_other_page")


def test_code_facts_are_trusted_and_short_phone_quotes_are_found_on_the_page() -> None:
    facts = [
        _fact("f1", "jsonld_phone", {"value": "+919876543210"}, '{"telephone": "+919876543210"}', HOME, model="rule"),
        _fact("f2", "phone", {"number": "98220 12345"}, "98220", CONTACT),
        _fact("f3", "phone", {"number": "99999 00000"}, "99999", CONTACT),
        _fact("f4", "service", {"name": "laser"}, "laser", HOME, page_id=None),
    ]
    states = verify_quotes(_bundle(facts), "IN")
    assert (states["f1"].verified, states["f1"].why) == (True, "code")
    assert (states["f2"].verified, states["f2"].why) == (True, "value_on_page")
    assert (states["f3"].verified, states["f3"].why) == (False, "quote_too_short")
    assert states["f4"].why == "quote_too_short"


def test_missing_page_is_recorded() -> None:
    facts = [_fact("f1", "service", {"name": "botox"}, "Botox by senior dermatologists", "https://elsewhere.in/x")]
    states = verify_quotes(_bundle(facts, pages=[_page("p9", "https://www.glowskin.in/blog", "nothing")]), "IN")
    assert states["f1"].why == "quote_not_found" or states["f1"].why == "page_missing"
    assert not states["f1"].verified


# ---------------------------------------------------------------------------
# 10.3 phones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        ("(080) 4123 4567", "IN", ("+918041234567", "landline")),
        ("022-2345 6789", "IN", ("+912223456789", "landline")),
        ("080-6123 4567", "IN", ("+918061234567", "landline")),
        ("+91 98765 43210", "IN", ("+919876543210", "mobile")),
        ("09876 543210", "IN", ("+919876543210", "mobile")),
        ("1800 123 4567", "IN", ("+9118001234567", "tollfree")),
        ("+971 50 123 4567", "AE", ("+971501234567", "mobile")),
        ("055 123 4567", "AE", ("+971551234567", "mobile")),
        ("04 331 2222", "AE", ("+97143312222", "landline")),
        ("2019", "IN", None),
    ],
)
def test_parse_phone(raw: str, region: str, expected: tuple[str, str] | None) -> None:
    assert parse_phone(raw, region) == expected


# ---------------------------------------------------------------------------
# 10.4 website status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "text", "error", "expected"),
    [
        (200, "Welcome to our clinic", None, "live"),
        (200, "This domain is parked free, courtesy of GoDaddy", None, "parked"),
        (200, "Our new website is coming soon", None, "coming_soon"),
        (404, "", None, "dead"),
        (410, "", None, "dead"),
        (403, "", None, "blocked"),
        (200, "Checking your browser. Cloudflare Ray ID", None, "blocked"),
        (None, "", "ConnectTimeout: timed out", "unknown"),
        (None, "", "SSL: CERTIFICATE_VERIFY_FAILED", "unknown"),
        (None, "", "Name or service not known", "dead"),
        (500, "", None, "unknown"),
    ],
)
def test_website_status(status: int | None, text: str, error: str | None, expected: str) -> None:
    assert website_status(status, text, error) == expected


def test_dead_twice_on_two_days_with_no_contact_is_rejected() -> None:
    dead_home = _page("p1", HOME, "", http_status=404)
    previous = _fact(
        "w0",
        "website_status",
        {"status": "dead", "dead_days": ["2026-11-10"]},
        "HTTP 404",
        HOME,
        model="rule",
        verified=True,
        verify_score=100,
        verified_at=NOW - timedelta(days=2),
    )
    asker, _ = _asker()
    plan = plan_business(_bundle([previous], pages=[dead_home]), CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS)
    assert plan.website_fact is not None and plan.website_fact["value"]["status"] == "dead"
    assert plan.website_fact["value"]["dead_days"] == ["2026-11-10", "2026-11-12"]
    assert (plan.status, plan.reject_reason) == ("rejected", "website_dead_no_contact")


# ---------------------------------------------------------------------------
# 10.5 competitors, chains, hospitals
# ---------------------------------------------------------------------------


def test_footer_credit_is_not_a_competitor_sign() -> None:
    hints = verify.competitor_hints(_bundle(), [], EXCL)
    assert hints == []


def test_two_competitor_signs_reject_without_ai() -> None:
    agency_page = _page("p1", HOME, "Pixel Labs is a web development company. We build websites for clinics.")
    facts = [
        _fact(
            "f1",
            "is_agency_or_vendor",
            {"value": True},
            "Pixel Labs is a web development company",
            HOME,
            verified=True,
            verify_score=100,
            verified_at=NOW,
        )
    ]
    asker, router = _asker()
    plan = plan_business(_bundle(facts, pages=[agency_page]), CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS)
    assert (plan.status, plan.reject_reason) == ("rejected", "competitor")
    assert router.calls == []


@pytest.mark.parametrize(("is_competitor", "status"), [(True, "rejected"), (False, "researched")])
def test_one_competitor_sign_asks_verify_flagged(is_competitor: bool, status: str) -> None:
    page = _page(
        "p1",
        HOME,
        HOME_TEXT.replace("Designed and developed by Pixel IT Solutions", "")
        + "\nWe also offer IT services to other clinics.\n"
        + CONTACT_TEXT,
    )
    asker, router = _asker([FlaggedVerification(trusted_fact_id=None, is_competitor=is_competitor, reason="x")])
    phone = _fact("c", "phone", {"number": "+91 98765 43210"}, "Call +91 98765 43210 for appointments.", HOME)
    plan = plan_business(_bundle([phone], pages=[page]), CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS)
    assert router.tasks() == ["verify_flagged"]
    asked = router.calls[0].inputs
    assert "question" in asked and asked["field"] == "is_agency_or_vendor"
    assert all("context" not in f for f in asked["facts"]) and len(asked["pages"]) <= 4
    assert plan.status == status


def test_known_agencies_are_rejected_as_competitors() -> None:
    for name, domain in (("Interakt", "interakt.shop"), ("Gallabox", "gallabox.com"), ("AiSensy", "aisensy.com")):
        page = _page("p1", f"https://{domain}/", "WhatsApp API for businesses. We build websites and bots.")
        asker, _ = _asker([FlaggedVerification(trusted_fact_id=None, is_competitor=True, reason="vendor")])
        bundle = _bundle(pages=[page], business={"name": name, "website": f"https://{domain}/", "web_domain": domain})
        plan = plan_business(bundle, CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS)
        assert (plan.status, plan.reject_reason) == ("rejected", "competitor"), name


def test_chains_and_hospitals_are_rejected() -> None:
    asker, _ = _asker()
    chain = _bundle(
        business={"name": "Kaya Skin Clinic Baner", "web_domain": "kaya.in", "website": "https://kaya.in"},
        pages=[_page("p1", "https://kaya.in/", HOME_TEXT)],
    )
    assert plan_business(chain, CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS).reject_reason == "big_chain"
    hospital = _bundle(business={"name": "Sunrise Multispeciality Hospital"})
    assert plan_business(hospital, CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS).reject_reason == "hospital"


def test_suppressed_domain_stops_verification() -> None:
    asker, _ = _asker()
    plan = plan_business(
        _bundle(), CLINICS, EXCL, Suppression(frozenset(), frozenset(), frozenset({"glowskin.in"})), asker, DEPS
    )
    assert (plan.status, plan.reject_reason) == ("suppressed", "suppressed")
    assert plan.contacts == []


# ---------------------------------------------------------------------------
# 10.3 contacts
# ---------------------------------------------------------------------------


def _verified(*facts: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**f, "verified": True, "verify_score": 100, "verified_at": NOW} for f in facts]


def test_contacts_from_own_pages_with_types_and_decision_maker() -> None:
    facts = _verified(
        _fact(
            "f1",
            "phone",
            {"number": "+91 98765 43210", "label": "appointments", "belongs_to": "business"},
            "Call +91 98765 43210 for appointments.",
            HOME,
        ),
        _fact(
            "f2", "phone", {"number": "(020) 2612 3456", "label": "reception"}, "Reception: (020) 2612 3456", CONTACT
        ),
        _fact(
            "f3",
            "phone",
            {"number": "98220 12345", "belongs_to": "person"},
            "WhatsApp Dr. Anil Rao on 98220 12345",
            CONTACT,
        ),
        _fact("f4", "phone", {"number": "+91 90000 11111"}, "a number from a chat widget", HOME),
        _fact(
            "f5",
            "decision_maker",
            {"name": "Dr. Anil Rao", "role": "Founder and Medical Director"},
            "Dr. Anil Rao, Founder and Medical Director",
            TEAM,
        ),
        _fact("f6", "email", {"email": "hello@glowskin.in"}, "Email: hello@glowskin.in", CONTACT),
    )
    stats: Counter[str] = Counter()
    rows = plan_contacts(_bundle(facts), facts, CLINICS, NO_SUPPRESSION, DEPS, NOW, stats)
    by_phone = {r.phone_e164: r for r in rows if r.phone_e164}
    assert set(by_phone) == {"+919876543210", "+912026123456", "+919822012345"}
    assert stats["phones.not_on_own_page"] == 1
    assert by_phone["+912026123456"].phone_type == "landline"
    dm = by_phone["+919822012345"]
    assert dm.is_decision_maker and dm.name == "Dr. Anil Rao" and dm.source == "website" and dm.quote
    assert not by_phone["+919876543210"].is_decision_maker
    emails = [r for r in rows if r.email]
    assert [e.email for e in emails] == ["hello@glowskin.in"] and emails[0].role is None
    assert all(r.verified and r.source in ("website", "registry", "google_listing") for r in rows)


def test_decision_maker_without_own_number_gets_a_name_only_row() -> None:
    facts = _verified(
        _fact("f5", "decision_maker", {"name": "Dr. Meera Shah", "role": "Founder"}, "Dr. Meera Shah, Consultant", TEAM)
    )
    rows = plan_contacts(_bundle(facts), facts, CLINICS, NO_SUPPRESSION, DEPS, NOW, Counter())
    named = [r for r in rows if r.name]
    assert len(named) == 1 and named[0].phone_e164 is None and named[0].is_decision_maker


def test_google_listing_only_when_no_website_phone_and_fresh() -> None:
    record = {
        "source": "places",
        "payload": {"nationalPhoneNumber": "098765 00000"},
        "fetched_at": NOW - timedelta(days=3),
    }
    bundle = _bundle(
        pages=[_page("p1", HOME, "Welcome")], records=[record], business={"places_fetched_at": NOW - timedelta(days=3)}
    )
    rows = plan_contacts(bundle, [], CLINICS, NO_SUPPRESSION, DEPS, NOW, Counter())
    assert [(r.source, r.phone_e164) for r in rows] == [("google_listing", "+919876500000")]
    assert rows[0].source_url == "https://www.google.com/maps/place/?q=place_id:ChIJtest" and rows[0].quote is None
    old = _bundle(
        pages=[_page("p1", HOME, "Welcome")],
        records=[{**record, "fetched_at": NOW - timedelta(days=40)}],
        business={"places_fetched_at": NOW - timedelta(days=40)},
    )
    stats: Counter[str] = Counter()
    assert plan_contacts(old, [], CLINICS, NO_SUPPRESSION, DEPS, NOW, stats) == []
    assert stats["phones.listing_too_old"] == 1


def test_registry_email_is_decoded_and_mx_checked() -> None:
    record = {"source": "art_registry", "payload": {"email": "ivf [at] sunrisefertility [dot] com"}, "fetched_at": NOW}
    rows = plan_contacts(_bundle(pages=[], records=[record]), [], CLINICS, NO_SUPPRESSION, DEPS, NOW, Counter())
    assert [(r.source, r.email) for r in rows] == [("registry", "ivf@sunrisefertility.com")]
    no_mx = VerifyDeps(mx=lambda domain: False, now=lambda: NOW)
    stats: Counter[str] = Counter()
    assert plan_contacts(_bundle(pages=[], records=[record]), [], CLINICS, NO_SUPPRESSION, no_mx, NOW, stats) == []
    assert stats["emails.no_mx"] == 1


def test_free_mail_owner_email_is_marked() -> None:
    page = _page("p2", CONTACT, "Write to Dr. Anil Rao at anilrao.derm@gmail.com")
    facts = _verified(
        _fact(
            "f1",
            "email",
            {"email": "anilrao.derm@gmail.com"},
            "Write to Dr. Anil Rao at anilrao.derm@gmail.com",
            CONTACT,
        ),
        _fact("f2", "decision_maker", {"name": "Dr. Anil Rao", "role": "Founder"}, "Dr. Anil Rao", CONTACT),
    )
    rows = plan_contacts(_bundle(facts, pages=[page]), facts, CLINICS, NO_SUPPRESSION, DEPS, NOW, Counter())
    mail = next(r for r in rows if r.email)
    assert mail.is_decision_maker and mail.role == "Founder (free mail)"


def test_suppressed_phone_and_email_are_kept_but_never_used() -> None:
    facts = _verified(
        _fact("f1", "phone", {"number": "+91 98765 43210"}, "Call +91 98765 43210 for appointments.", HOME)
    )
    sup = Suppression(frozenset({"+919876543210"}), frozenset(), frozenset())
    rows = plan_contacts(_bundle(facts), facts, CLINICS, sup, DEPS, NOW, Counter())
    assert rows[0].do_not_contact and not rows[0].usable


def test_no_contact_at_all_is_rejected() -> None:
    asker, _ = _asker()
    plan = plan_business(
        _bundle(pages=[_page("p1", HOME, "Welcome to our clinic")]), CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS
    )
    assert (plan.status, plan.reject_reason) == ("rejected", "no_contact")


# ---------------------------------------------------------------------------
# 10.7 conflicts
# ---------------------------------------------------------------------------


def test_conflicts_are_detected() -> None:
    facts = _verified(
        _fact("a", "branches", {"count": 2}, "two branches", HOME),
        _fact("b", "branches", {"count": 5}, "five branches", "https://www.glowskin.in/locations/"),
        _fact("c", "staff_or_doctors", {"count": 10}, "10 doctors", TEAM),
        _fact("d", "staff_or_doctors", {"count": 8}, "8 doctors", HOME),
        _fact("e", "decision_maker", {"name": "Dr. Anil Rao", "role": "Founder"}, "x", TEAM),
        _fact("f", "decision_maker", {"name": "Ravi Kumar", "role": "Owner"}, "y", HOME),
        _fact("g", "decision_maker", {"name": "Sita Iyer", "role": "Co-founder"}, "z", TEAM),
        _fact("h", "in_house_tech", {"value": True}, "our IT team", HOME),
        _fact("i", "in_house_tech", {"value": False}, "no tech team", TEAM),
    )
    found = {c.field: sorted(f["id"] for f in c.facts) for c in find_conflicts(facts)}
    assert found == {"branches": ["a", "b"], "decision_maker": ["e", "f"], "in_house_tech": ["h", "i"]}


def test_rule_prefers_the_more_specific_page() -> None:
    pages = [_page("p1", HOME, "x"), _page("p4", "https://www.glowskin.in/locations/", "y")]
    by_id = {p["id"]: p for p in pages}
    by_url = {verify.evidence.canonical_url(p["url"]): p for p in pages}
    conflict = Conflict(
        "branches",
        [
            _fact("a", "branches", {"count": 2}, "q", HOME),
            _fact("b", "branches", {"count": 5}, "q", "https://www.glowskin.in/locations/"),
        ],
    )
    assert resolve_by_rule(conflict, by_id, by_url) == "b"
    same = Conflict(
        "branches", [_fact("a", "branches", {"count": 2}, "q", HOME), _fact("c", "branches", {"count": 6}, "q", HOME)]
    )
    assert resolve_by_rule(same, by_id, by_url) is None


def test_undecided_conflict_goes_to_verify_flagged_and_losers_get_minus_one() -> None:
    home = _page("p1", HOME, HOME_TEXT + "\nWe have 2 branches in Pune.\nNow 6 branches across Pune!")
    facts = [
        _fact("a", "branches", {"count": 2}, "We have 2 branches in Pune.", HOME),
        _fact("b", "branches", {"count": 6}, "Now 6 branches across Pune!", HOME),
        _fact("c", "phone", {"number": "+91 98765 43210"}, "Call +91 98765 43210 for appointments.", HOME),
    ]
    asker, router = _asker([FlaggedVerification(trusted_fact_id="Fb", is_competitor=None, reason="newer line")])
    plan = plan_business(_bundle(facts, pages=[home]), CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS)
    assert router.tasks() == ["verify_flagged"]
    assert [f["id"] for f in router.calls[0].inputs["facts"]] == ["a", "b"]
    assert plan.fact_states["a"].score == -1 and not plan.fact_states["a"].verified
    assert plan.fact_states["b"].verified and plan.branches_count == 6
    assert plan.status == "researched"


def test_without_ai_the_lower_count_wins() -> None:
    home = _page("p1", HOME, HOME_TEXT + "\nWe have 2 branches in Pune.\nNow 6 branches across Pune!")
    facts = [
        _fact("a", "branches", {"count": 2}, "We have 2 branches in Pune.", HOME),
        _fact("b", "branches", {"count": 6}, "Now 6 branches across Pune!", HOME),
        _fact("c", "phone", {"number": "+91 98765 43210"}, "Call +91 98765 43210 for appointments.", HOME),
    ]
    plan = plan_business(_bundle(facts, pages=[home]), CLINICS, EXCL, NO_SUPPRESSION, FlagAsker(None, None), DEPS)
    assert plan.fact_states["b"].score == -1 and plan.branches_count == 2


# ---------------------------------------------------------------------------
# 10.2.4 suspicious extraction and 10.6 freshness
# ---------------------------------------------------------------------------


def test_many_failed_quotes_requeue_once_with_a_browser() -> None:
    facts = [
        _fact(str(i), "service", {"name": "x"}, f"An invented sentence number {i} about lasers", HOME) for i in range(4)
    ]
    asker, _ = _asker()
    plan = plan_business(_bundle(facts), CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS)
    assert plan.status == "queued" and plan.extra_patch["force_browser"] is True
    again = _bundle(facts, business={"extra": {"browser_requeued_at": "2026-11-11"}})
    assert plan_business(again, CLINICS, EXCL, NO_SUPPRESSION, asker, DEPS).status != "queued"


def test_closed_jobs_expire() -> None:
    base = {
        "business_id": "b1",
        "category": "visible_pain",
        "points": 8,
        "observed_at": NOW - timedelta(days=5),
        "expires_at": NOW + timedelta(days=25),
        "source": "apna",
    }
    signals = [
        {**base, "id": "s1", "type": "hiring_frontdesk", "details": {"apply_by": "2026-11-10"}, "url": None},
        {**base, "id": "s2", "type": "hiring_frontdesk", "details": {"apply_by": "2026-11-30"}, "url": None},
        {**base, "id": "s3", "type": "hiring_builder", "details": {}, "url": CONTACT},
        {**base, "id": "s4", "type": "review_pain", "details": {"closed": True}, "url": None},
    ]
    pages = [_page("p2", CONTACT, "This job is closed. No longer accepting applications.")]
    assert signals_to_expire(_bundle(pages=pages, signals=signals), NOW) == ["s1", "s3"]
