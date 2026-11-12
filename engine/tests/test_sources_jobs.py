"""Job posts as signals (Steps 5.8, 5.13, 7.5.1): Apna discovery and parsing, classification rules, privacy."""

from __future__ import annotations

from typing import Any

import pytest

from nument_engine.models import SignalClassification
from nument_engine.sources.adzuna import AdzunaAdapter, to_post
from nument_engine.sources.apna import ApnaAdapter, match_job_url, parse_locs
from nument_engine.sources.jobs import (
    JobPost,
    classify_job,
    has_domain_hint,
    job_from_html,
    mask_contacts,
    pick_quote,
    role_from_keywords,
)

from .sources_helpers import FakeRouter, clean_db, ctx, fixture_text, mock_transport, no_network, segment

__all__ = ["clean_db", "no_network"]

SEGMENTS = {s: segment(s) for s in ("clinics-in", "realestate-in", "education-in")}


def verdict(**over: Any) -> SignalClassification:
    base: dict[str, Any] = {
        "is_relevant": True,
        "role_category": "frontdesk",
        "employer_name": "Lotus Skin and Hair Clinic",
        "employer_website": None,
        "employer_domain": "clinics",
        "city": "Pune",
        "evidence_quote": "Greet patients, manage appointments on the phone and WhatsApp",
        "confidence": 0.9,
    }
    return SignalClassification(**{**base, **over})


def post() -> JobPost:
    found = job_from_html(
        fixture_text("apna", "job.html"),
        source="apna",
        job_id="512345678",
        url="https://apna.co/job/pune/clinic-receptionist-baner-512345678",
    )
    assert found is not None
    return found


def test_job_urls_are_filtered_by_city_and_title_before_fetching() -> None:
    segs = list(SEGMENTS.values())
    urls = parse_locs(fixture_text("apna", "active-job-listings-1.xml"))
    matched = {u: match_job_url(u, segs) for u in urls}
    receptionist = matched["https://apna.co/job/pune/clinic-receptionist-baner-512345678"]
    assert receptionist is not None and receptionist.role == "frontdesk" and receptionist.job_id == "512345678"
    assert matched["https://apna.co/job/pune-region/telecaller-967671018"] is not None
    assert matched["https://apna.co/job/navi-mumbai/front-desk-executive-110000001"] is not None
    assert matched["https://apna.co/job/lucknow/receptionist-576335185"] is None  # not a segment city
    assert matched["https://apna.co/job/pune/staff-nurse-220000002"] is None  # excluded role
    builder = matched["https://apna.co/job/bengaluru-bangalore/full-stack-developer-330000003"]
    assert builder is not None and builder.role == "builder"
    assert matched["https://apna.co/job/new-delhi/admission-counsellor-264608617"] is not None
    assert matched["https://apna.co/jobs/pune"] is None  # not a job page


def test_jobposting_is_parsed_from_json_ld() -> None:
    p = post()
    assert p.title == "Clinic Receptionist - Baner"
    assert p.employer == "Lotus Skin and Hair Clinic"
    assert p.posted_at is not None and p.posted_at.isoformat().startswith("2026-11-07T07:47:58")
    assert p.valid_through is not None and p.valid_through.date().isoformat() == "2026-12-07"
    assert "Baner Road" in p.location_text and p.salary["currency"] == "INR"


def test_contact_details_are_masked_before_the_ai_sees_them() -> None:
    text = post().text()
    assert "90000 00000" not in text and "[phone]" in text
    assert mask_contacts("mail hr@clinic.in or call +91 98765 43210") == "mail [email] or call [phone]"


def test_role_keywords_and_domain_hints() -> None:
    seg = SEGMENTS["clinics-in"]
    assert role_from_keywords("Clinic Receptionist - Baner", seg) == "frontdesk"
    assert role_from_keywords("WordPress Developer", seg) == "builder"
    assert role_from_keywords("Staff Nurse", seg) is None
    assert has_domain_hint("Front desk for Lotus Skin Clinic", ["clinics"])
    assert not has_domain_hint("Delivery partner for a food app", ["clinics", "realestate"])


def test_a_relevant_post_becomes_a_hiring_signal() -> None:
    router = FakeRouter({"classify_signal": [verdict()]})
    sig = classify_job(ctx(router), post(), SEGMENTS, country="in", default_segment=SEGMENTS["clinics-in"])
    assert sig is not None
    assert sig.type == "hiring_frontdesk" and sig.segment_id == "clinics-in"
    assert sig.evidence_key == "apna:512345678"
    assert sig.quote == "Greet patients, manage appointments on the phone and WhatsApp"
    assert sig.business_hint["name"] == "Lotus Skin and Hair Clinic"
    assert sig.business_hint["city"] == "Pune" and sig.business_hint["locality"] == "Baner"
    assert sig.details["apply_by"].startswith("2026-12-07") and sig.details["role_category"] == "frontdesk"
    sent = router.calls[0][1]
    assert sent["mode"] == "job_post" and "90000 00000" not in sent["text"]


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"employer_domain": "agency_or_staffing"}, "jobs.agency_dropped"),
        ({"role_category": "other"}, "jobs.other_role"),
        ({"confidence": 0.4}, "jobs.low_confidence"),
        ({"is_relevant": False}, "jobs.not_relevant"),
        ({"employer_domain": "d2c"}, "jobs.domain_not_enabled"),
    ],
)
def test_classifier_rules_drop_posts(over: dict[str, Any], reason: str) -> None:
    context = ctx(FakeRouter({"classify_signal": [verdict(**over)]}))
    assert classify_job(context, post(), SEGMENTS, country="in", default_segment=SEGMENTS["clinics-in"]) is None
    assert context.stats[reason] == 1


def test_posts_are_routed_to_the_employers_segment() -> None:
    router = FakeRouter({"classify_signal": [verdict(employer_domain="education", role_category="frontdesk")]})
    sig = classify_job(ctx(router), post(), SEGMENTS, country="in", default_segment=SEGMENTS["clinics-in"])
    assert sig is not None and sig.segment_id == "education-in"


def test_a_quote_that_is_not_in_the_post_or_holds_a_phone_falls_back_to_the_title() -> None:
    p = post()
    assert pick_quote("We pay the best salary in Pune", p) == "Clinic Receptionist - Baner"
    assert pick_quote("Apply on WhatsApp: 90000 00000 with your name", p) == "Clinic Receptionist - Baner"
    assert pick_quote("collect fees and update patient records", p) == "collect fees and update patient records"


def test_a_guessed_website_is_not_kept() -> None:
    router = FakeRouter({"classify_signal": [verdict(employer_website="https://lotusclinic-nlead.in")]})
    sig = classify_job(ctx(router), post(), SEGMENTS, country="in", default_segment=SEGMENTS["clinics-in"])
    assert sig is not None and sig.business_hint["website"] is None


def test_without_a_router_nothing_is_classified() -> None:
    context = ctx(None)
    assert classify_job(context, post(), SEGMENTS, country="in", default_segment=SEGMENTS["clinics-in"]) is None
    assert context.stats["ai_skipped.classify_signal.no_router"] == 1


async def test_apna_end_to_end_with_a_budget(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {
        "https://apna.co/robots.txt": (200, "User-agent: *\nDisallow: /*.infra.apna.co/\n"),
        "https://apna.co/api/sitemap-index.xml": (200, fixture_text("apna", "sitemap-index.xml")),
        "https://apna.co/api/job-listing-sitemap.xml": (200, fixture_text("apna", "job-listing-sitemap.xml")),
        "https://apna.co/api/job-listing-sitemap/active-job-listings-1.xml": (
            200,
            fixture_text("apna", "active-job-listings-1.xml"),
        ),
        "https://apna.co/job/pune/clinic-receptionist-baner-512345678": (200, fixture_text("apna", "job.html")),
        "*": (200, "<html><head><title>Telecaller</title></head><body>No structured data</body></html>"),
    }
    transport, seen = mock_transport(routes)
    monkeypatch.setattr(ApnaAdapter, "min_gap_s", 0.0)
    router = FakeRouter({"classify_signal": [verdict()]})
    context = ctx(router)
    async with ApnaAdapter(context, transport=transport) as apna:
        sigs = await apna.signals_for(SEGMENTS, limit=2)
    assert [s.type for s in sigs] == ["hiring_frontdesk"]
    assert not any("external-job-listings" in str(r.url) for r in seen)  # only active listings are read
    assert context.stats["apna.pages_read"] <= 2
    # the job is remembered, so it is not fetched again tomorrow
    from nument_engine import db

    assert (
        db.scalar("select count(*) from public.source_records where source = 'apna' and source_key = 'apna:512345678'")
        == 1
    )


def test_adzuna_items_map_to_posts() -> None:
    item = {
        "id": "4012345678",
        "title": "Front Desk Executive",
        "company": {"display_name": "Bright Smile Dental"},
        "description": "Handle patient calls and appointments for our dental clinic.",
        "created": "2026-11-10T09:00:00Z",
        "redirect_url": "https://www.adzuna.in/land/ad/4012345678",
        "location": {"display_name": "Baner, Pune"},
    }
    p = to_post(item)
    assert p is not None and p.source == "adzuna" and p.employer == "Bright Smile Dental"
    assert p.posted_at is not None and p.location_text == "Baner, Pune"
    assert to_post({"id": "", "title": "x"}) is None


def test_adzuna_is_off_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    usable, why = AdzunaAdapter(ctx()).status()
    assert not usable and "ADZUNA_APP_ID" in why


def test_clinic_titles_are_read_before_generic_telecaller_posts() -> None:
    from nument_engine.segments import load_segments
    from nument_engine.sources.apna import ApnaAdapter, JobUrl

    seg = load_segments()["clinics-in"]

    def job(n: int, slug: str) -> JobUrl:
        return JobUrl(f"https://apna.co/job/pune/{slug}-{n}", str(n), "pune", slug, "clinics-in", "frontdesk")

    jobs = [job(1, "telecaller"), job(2, "dental-receptionist"), job(3, "telecaller"), job(4, "clinic-coordinator")]
    ordered = ApnaAdapter.order(jobs, [seg])
    assert [j.job_id for j in ordered] == ["2", "4", "1", "3"]  # clinic titles first, sitemap order kept inside
