"""Official websites for businesses born from a job post or an ask (the need-first track, 13 Nov 2026)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from nument_engine import db
from nument_engine.pipeline import lookup

from .sources_helpers import clean_db, insert_business, no_network

__all__ = ["clean_db", "no_network"]

GROUNDING = {
    "sources": [
        {"uri": "https://vertexaisearch.example/redirect/1", "title": "brightcart.in"},
        {"uri": "https://www.naukri.com/job-1", "title": "naukri.com"},
    ],
    "supports": [{"text": "Brightcart Foods runs brightcart.in from Pune.", "chunks": [0]}],
}


def out(url: str | None) -> SimpleNamespace:
    return SimpleNamespace(website=url, website_line=f"Website: {url}")


def test_only_a_cited_own_website_is_a_candidate() -> None:
    assert lookup.candidate_url(out("brightcart.in"), GROUNDING) == "https://brightcart.in"
    assert lookup.candidate_url(out("https://www.naukri.com/job-1"), GROUNDING) is None  # a job board, never
    assert lookup.candidate_url(out("https://guessed-domain.in"), GROUNDING) is None  # the search never cited it
    assert lookup.candidate_url(out("unknown"), GROUNDING) is None
    assert lookup.candidate_url(out(None), GROUNDING) is None


def test_the_home_page_must_name_the_business() -> None:
    page = "<html><head><title>Brightcart | Fresh groceries in Pune</title></head><body>Order now</body></html>"
    assert lookup.page_matches("Brightcart Foods Pvt Ltd", page, "https://brightcart.in")
    other = "<html><head><title>Green Basket | Groceries</title></head><body>Order now</body></html>"
    assert not lookup.page_matches("Brightcart Foods Pvt Ltd", other, "https://greenbasket.in")
    by_domain = "<html><head><title>Home</title></head><body>Welcome</body></html>"
    assert lookup.page_matches("Brightcart Foods", by_domain, "https://brightcart.in")


def test_a_duplicate_website_merges_the_business_and_never_stops_the_other_lookups(clean_db: str) -> None:
    """Live, 14 Nov 2026: the found website of "Oaks Overseas" already belonged to another education-in business.
    The unique (segment, domain) index raised, the stage failed and every other lookup of the night was lost."""
    keep = insert_business(
        name="Oaks Overseas Education", segment_id="education-in", city="Delhi",
        website="https://oaksoverseas.com/", web_domain="oaksoverseas.com",
    )  # fmt: skip
    dup = insert_business(name="Oaks Overseas", segment_id="education-in", city="Delhi", extra={"born_from": "apna"})
    other = insert_business(
        name="Brightpath Study Abroad", segment_id="education-in", city="Delhi", extra={"born_from": "apna"}
    )
    db.execute(
        "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, url, "
        "quote, details, dedupe_key) values (%s, 'hiring_frontdesk', 'visible_pain', 8, now(), "
        "now() + interval '10 days', 'apna', 'https://apna.co/job/1', 'Front desk executive needed', "
        "'{}'::jsonb, 'dup-1')",
        [dup],
    )
    stats = lookup.write_results(
        str(uuid.uuid4()),
        {dup: "Oaks Overseas", other: "Brightpath Study Abroad"},
        {dup: "https://oaksoverseas.com/", other: "https://brightpath.in/"},
        datetime.now(UTC),
    )
    assert stats["merged_duplicate"] == 1 and not stats["write_failed"]
    assert db.scalar("select count(*) from public.businesses where id = %s", [dup]) == 0
    assert db.scalar("select count(*) from public.signals where business_id = %s", [keep]) == 1  # moved over
    row = db.fetch_one("select website, web_domain, extra from public.businesses where id = %s", [other])
    assert row is not None and row["web_domain"] == "brightpath.in" and "website_lookup_at" in row["extra"]
