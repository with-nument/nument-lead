"""AI fact extraction as a batch (Steps 9.11 to 9.14): the input budget and trimming, the flattening table,
submit and collect through the router contract, the sync retry and the no_booking signal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nument_engine import db
from nument_engine.models import FactsExtraction
from nument_engine.pipeline import extract
from nument_engine.pipeline.extract import PageIn, flatten, page_for, pages_block, trim_pages

from .sources_helpers import FakeRouter, clean_db, insert_business, no_network, run_context

__all__ = ["clean_db", "no_network"]

SITE = "https://extractclinic-nlead.in"
NAV = "Home | About | Doctors | Contact\nCall +91 98765 43210\n© 2026 Extract Clinic. All rights reserved."


def pages() -> list[PageIn]:
    return [
        PageIn("about", f"{SITE}/about", "About us\nFounded in 2012 by Dr. Asha Rao.\n" + NAV, "p4"),
        PageIn("home", f"{SITE}/", "Welcome to Extract Clinic\nSkin and hair care in Baner\n" + NAV, "p1"),
        PageIn("contact", f"{SITE}/contact", "Contact us\nOffice 2, Baner Road\n" + NAV, "p3"),
        PageIn("team", f"{SITE}/team", "Our doctors\nDr. Asha Rao, Founder and Medical Director\n" + NAV, "p2"),
    ]


def test_trimming_orders_pages_and_keeps_repeated_lines_once() -> None:
    trimmed = trim_pages(pages())
    assert [p.kind for p in trimmed] == ["home", "team", "contact", "about"]
    joined = "\n".join(p.text for p in trimmed)
    assert joined.count("Call +91 98765 43210") == 1 and "Call +91 98765 43210" in trimmed[0].text
    assert "All rights reserved" not in joined  # boilerplate
    assert "Dr. Asha Rao, Founder and Medical Director" in trimmed[1].text


def test_budgets_cut_on_line_boundaries_and_keep_key_lines_first() -> None:
    filler = "\n".join(
        f"Paragraph {i} about our gentle approach to skin care for everyone in the city." for i in range(400)
    )
    big = PageIn("home", f"{SITE}/", filler + "\nConsultation fee ₹1,000 with Dr. Rao\n" + filler, "p1")
    trimmed = trim_pages([big])
    assert len(trimmed[0].text) <= 3000 * 4
    assert "Consultation fee ₹1,000 with Dr. Rao" in trimmed[0].text
    assert all(line.startswith(("Paragraph", "Consultation")) for line in trimmed[0].text.splitlines())


def test_total_budget_is_16k_tokens_minus_instructions() -> None:
    many = [PageIn(k, f"{SITE}/{k}", ("x" * 70 + "\n") * 2000, f"p{i}") for i, k in enumerate(extract.PAGE_ORDER)]
    total = sum(len(p.text) for p in trim_pages(many))
    assert total <= (16_000 - 2_000) * 4


def test_page_blocks_name_every_url() -> None:
    block = pages_block([PageIn("home", f"{SITE}/", "Hello", "p1"), PageIn("team", f"{SITE}/team", "Dr X", "p2")])
    assert block == (
        f"### PAGE 1\nURL: {SITE}/\nTEXT:\nHello\n### END PAGE 1\n"
        f"### PAGE 2\nURL: {SITE}/team\nTEXT:\nDr X\n### END PAGE 2"
    )


def facts_json(url: str = f"{SITE}/team") -> dict[str, Any]:
    return {
        "business_name": {"quote": "Welcome to Extract Clinic", "url": f"{SITE}/", "value": "Extract Clinic"},
        "decision_makers": [
            {
                "quote": "Dr. Asha Rao, Founder and Medical Director",
                "url": url,
                "name": "Dr. Asha Rao",
                "role": "Founder and Medical Director",
                "is_decision_maker": True,
            }
        ],
        "phones": [
            {
                "quote": "Call +91 98765 43210",
                "url": f"{SITE}/",
                "number": "+91 98765 43210",
                "label": "reception",
                "belongs_to": "business",
            }
        ],
        "emails": [],
        "branches": {"quote": "Office 2, Baner Road", "url": f"{SITE}/contact", "count": 1},
        "price_points": [
            {
                "quote": "Consultation fee ₹1,000",
                "url": f"{SITE}/",
                "item": "consultation",
                "amount": 1000,
                "currency": "INR",
            }
        ],
        "booking_method": {"quote": "Call +91 98765 43210", "url": f"{SITE}/", "value": "call only"},
    }


def test_flattening_table() -> None:
    rows = {f: (v, q, u) for f, v, q, u in flatten(FactsExtraction.model_validate(facts_json()))}
    assert rows["business_name"][0] == {"name": "Extract Clinic"}
    assert rows["decision_maker"][0] == {
        "name": "Dr. Asha Rao",
        "role": "Founder and Medical Director",
        "is_decision_maker": True,
    }
    assert rows["phone"][0] == {"number": "+91 98765 43210", "label": "reception", "belongs_to": "business"}
    assert rows["branches"][0] == {"count": 1}
    assert rows["price_point"][0] == {"item": "consultation", "amount": 1000.0, "currency": "INR"}
    assert rows["booking_method"][0] == {"value": "call only"}


def test_a_wrong_url_citation_is_moved_to_the_page_that_holds_the_quote() -> None:
    known = {f"{SITE}/": ("p1", "Welcome"), f"{SITE}/team": ("p2", "Dr. Asha Rao, Founder and Medical Director")}
    assert page_for(f"{SITE}/", "Dr. Asha Rao, Founder and Medical Director", known) == (f"{SITE}/team", "p2")
    assert page_for(f"{SITE}/team/", "anything", known) == (f"{SITE}/team", "p2")  # canonical match
    assert page_for("https://elsewhere-nlead.in/", "nowhere", known) == ("https://elsewhere-nlead.in/", None)


def seed_business(**kw: Any) -> str:
    bid = insert_business(
        name="Extract Clinic",
        website=f"{SITE}/",
        web_domain="extractclinic-nlead.in",
        status="queued",
        queued_at=datetime.now(UTC),
        queue_priority=10,
        **kw,
    )
    crawl_pages = {}
    for p in pages():
        db.execute("insert into public.pages (business_id, url, text) values (%s, %s, %s)", [bid, p.url, p.text])
        crawl_pages[p.kind] = p.url
    db.execute(
        "update public.businesses set extra = jsonb_set(extra, '{crawl}', %s) where id = %s",
        [db.Jsonb({"state": "ok", "pages": crawl_pages, "at": datetime.now(UTC).isoformat()}), bid],
    )
    db.execute(
        "insert into public.facts (business_id, field, value, quote, url, model, verified) "
        "values (%s, 'tech_stack', %s, 'none', %s, 'rule', true)",
        [bid, db.Jsonb({"tools": [], "has_booking": False, "has_whatsapp": False, "has_chat": False}), f"{SITE}/"],
    )
    return bid


def test_submit_builds_items_and_marks_them(clean_db: str) -> None:
    bid = seed_business()
    router = FakeRouter()
    out = extract.submit(run_context(segments=["clinics-in"]), router=router)
    assert out["submitted"] >= 1 and out["provider"] == "gemini" and out["batch_id"] == "batches/fake-1"
    task, items = router.submitted[0]
    mine = next(i for i in items if i["key"] == bid)
    assert task == "extract_facts"
    inputs = mine["inputs"]
    assert inputs["business_name"] == "Extract Clinic" and inputs["segment_id"] == "clinics-in"
    assert inputs["allowed_urls"][0] == f"{SITE}/" and "### PAGE 1" in inputs["pages_block"]
    assert inputs["tech_flags"] == {"has_booking": False, "has_whatsapp": False, "has_chat": False}
    assert (
        db.scalar("select extra #>> '{extract,batch}' from public.businesses where id = %s", [bid]) == "batches/fake-1"
    )
    again = extract.submit(run_context(segments=["clinics-in"]), router=FakeRouter())
    assert again["items"] == 0  # never the same business twice in a day


def test_submit_dry_run_and_settled_businesses(clean_db: str) -> None:
    seed_business()
    no_pages = insert_business(
        name="No Pages Clinic", status="queued", queued_at=datetime.now(UTC), place_id="ChIJnp-1"
    )
    nothing = insert_business(name="Nothing Clinic", status="queued", queued_at=datetime.now(UTC))
    out = extract.submit(run_context(segments=["clinics-in"], dry_run=True), router=FakeRouter())
    assert out["would_submit"] >= 1
    assert db.scalar("select status from public.businesses where id = %s", [no_pages]) == "queued"  # dry run
    extract.submit(run_context(segments=["clinics-in"]), router=FakeRouter())
    assert db.scalar("select status from public.businesses where id = %s", [no_pages]) == "researched"
    assert db.scalar("select reject_reason from public.businesses where id = %s", [nothing]) == "no_research_material"


def test_collect_writes_facts_marks_researched_and_adds_no_booking(clean_db: str) -> None:
    bid = seed_business()
    router = FakeRouter(
        batch_results=[
            {
                "key": bid,
                "parsed": facts_json(url=f"{SITE}/"),
                "provider": "gemini",
                "model": "gemini-3-flash",
                "tag": "gemini:gemini-3-flash#extract_facts.v1",
            }
        ]
    )
    out = extract.collect(run_context(segments=["clinics-in"]), router=router)
    assert out["businesses"] == 1 and out["no_booking"] == 1
    facts = db.fetch_all(
        "select field, url, page_id, model, verified from public.facts where business_id = %s and model <> 'rule'",
        [bid],
    )
    by_field = {f["field"]: f for f in facts}
    assert by_field["decision_maker"]["url"] == f"{SITE}/team"  # moved to the page that holds the quote
    assert all(f["page_id"] for f in facts) and not any(f["verified"] for f in facts)
    assert by_field["phone"]["model"] == "gemini:gemini-3-flash#extract_facts.v1"
    assert db.scalar("select status from public.businesses where id = %s", [bid]) == "researched"
    sig = db.fetch_one("select type, quote from public.signals where business_id = %s", [bid])
    assert sig is not None and sig["type"] == "no_booking" and "pages checked" in sig["quote"]


def test_an_invalid_result_is_retried_once_synchronously(clean_db: str) -> None:
    bid = seed_business()
    router = FakeRouter(
        replies={"extract_facts": [FactsExtraction.model_validate(facts_json())]},
        batch_results=[{"key": bid, "parsed": {"phones": [{"quote": "x"}]}, "provider": "gemini", "model": "m"}],
    )
    out = extract.collect(run_context(segments=["clinics-in"]), router=router)
    assert out["businesses"] == 1 and router.tasks() == ["extract_facts"]
    assert db.scalar("select count(*) from public.facts where business_id = %s and model like '%%+retry'", [bid]) > 0


def test_a_failed_retry_keeps_the_business_queued(clean_db: str) -> None:
    bid = seed_business()
    router = FakeRouter(
        replies={"extract_facts": [RuntimeError("bad output")]},
        batch_results=[{"key": bid, "parsed": None, "error": "boom"}],
    )
    out = extract.collect(run_context(segments=["clinics-in"]), router=router)
    assert out["failed"] == 1
    row = db.fetch_one("select status, reject_reason from public.businesses where id = %s", [bid])
    assert row == {"status": "queued", "reject_reason": "extract_failed"}


def test_without_a_router_nothing_is_submitted(clean_db: str) -> None:
    seed_business()
    out = extract.submit(run_context(segments=["clinics-in"]))
    assert out["skipped"].startswith("no AI router")
