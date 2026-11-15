"""AI fact extraction as a batch (Steps 9.11 to 9.14): the input budget and trimming, the flattening table,
submit and collect through the router contract, the sync retry and the no_booking signal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nument_engine import db
from nument_engine.budget import BudgetExceeded
from nument_engine.llm.batch import BatchItem, CollectResult, ItemResult, SubmitResult, SubmittedJob
from nument_engine.models import FactsExtraction
from nument_engine.pipeline import extract
from nument_engine.pipeline.extract import PageIn, flatten, page_for, pages_block, trim_pages

from .sources_helpers import FakeRouter, clean_db, insert_business, no_network, run_context
from .startup_fakes import firms_us

__all__ = ["clean_db", "firms_us", "no_network"]

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


class FakeBatch:
    """Stands in for `nument_engine.llm.batch`: records submissions and returns real result types."""

    def __init__(self, results: list[ItemResult] | None = None, raises: BaseException | None = None) -> None:
        self.submitted: list[tuple[str, list[BatchItem]]] = []
        self.results = results or []
        self.raises = raises
        self.rebuilt: dict[str, Any] = {}

    def submit(self, router: Any, task: str, items: list[BatchItem], **kw: Any) -> SubmitResult:
        if self.raises:
            raise self.raises
        self.submitted.append((task, items))
        job = SubmittedJob("llm-1", "gemini", "batches/fake-1", "gemini-3-flash", [i.key for i in items], 1.5)
        return SubmitResult(jobs=[job])

    def collect(self, router: Any, task: str | None = None, *, rebuild_inputs: Any = None, **kw: Any) -> CollectResult:
        for r in self.results:
            if r.output is None and rebuild_inputs is not None:
                self.rebuilt[r.key] = rebuild_inputs(r.key)
        return CollectResult(results=self.results)


def batch(monkeypatch: pytest.MonkeyPatch, fake: FakeBatch) -> FakeBatch:
    monkeypatch.setattr(extract.llm_batch, "submit", fake.submit)
    monkeypatch.setattr(extract.llm_batch, "collect", fake.collect)
    return fake


def test_submit_builds_items_and_marks_them(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    bid = seed_business()
    fake = batch(monkeypatch, FakeBatch())
    out = extract.submit(run_context(segments=["clinics-in"]), router=FakeRouter())
    assert out["submitted"] >= 1 and out["providers"] == ["gemini"] and out["batches"] == ["batches/fake-1"]
    task, items = fake.submitted[0]
    mine = next(i for i in items if i.key == f"extract_facts:{bid}")
    assert task == "extract_facts"
    inputs = mine.inputs
    assert inputs["business_name"] == "Extract Clinic" and inputs["segment_id"] == "clinics-in"
    assert inputs["allowed_urls"][0] == f"{SITE}/" and "### PAGE 1" in inputs["pages_block"]
    assert inputs["tech_flags"] == {"has_booking": False, "has_whatsapp": False, "has_chat": False}
    assert db.scalar("select extra #>> '{extract,submitted_at}' from public.businesses where id = %s", [bid])
    again = extract.submit(run_context(segments=["clinics-in"]), router=FakeRouter())
    assert again["items"] == 0  # never the same business twice in a day


def test_submit_dry_run_and_settled_businesses(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_business()
    fake = batch(monkeypatch, FakeBatch())
    queued = datetime.now(UTC) - timedelta(minutes=5)
    crawled = {"crawl": {"at": datetime.now(UTC).isoformat(), "state": "robots_disallowed"}}
    no_pages = insert_business(
        name="No Pages Clinic", status="queued", queued_at=queued, place_id="ChIJnp-1", extra=crawled
    )
    nothing = insert_business(name="Nothing Clinic", status="queued", queued_at=queued, extra=crawled)
    unread = insert_business(name="Unread Clinic", status="queued", queued_at=queued)  # research not there yet
    out = extract.submit(run_context(segments=["clinics-in"], dry_run=True), router=FakeRouter())
    assert out["would_submit"] >= 1 and fake.submitted == []  # a dry run never submits
    assert db.scalar("select status from public.businesses where id = %s", [no_pages]) == "queued"
    extract.submit(run_context(segments=["clinics-in"]), router=FakeRouter())
    assert db.scalar("select status from public.businesses where id = %s", [no_pages]) == "researched"
    assert db.scalar("select reject_reason from public.businesses where id = %s", [nothing]) == "no_research_material"
    assert (
        db.scalar("select status from public.businesses where id = %s", [unread]) == "queued"
    )  # never rejected unread


def test_a_refused_batch_leaves_the_queue_alone(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    bid = seed_business()
    batch(monkeypatch, FakeBatch(raises=BudgetExceeded("extract_facts", "would cross the daily cap")))
    out = extract.submit(run_context(segments=["clinics-in"]), router=FakeRouter())
    assert out["stopped"].startswith("BudgetExceeded")
    assert db.scalar("select status from public.businesses where id = %s", [bid]) == "queued"


def item(bid: str, output: Any = None, **kw: Any) -> ItemResult:
    return ItemResult(
        key=f"extract_facts:{bid}",
        output=output,
        provider="gemini",
        model="gemini-3-flash",
        tag="gemini:gemini-3-flash#extract_facts.v1",
        **kw,
    )


def test_collect_writes_facts_marks_researched_and_adds_no_booking(
    clean_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    bid = seed_business()
    batch(monkeypatch, FakeBatch([item(bid, FactsExtraction.model_validate(facts_json(url=f"{SITE}/")))]))
    out = extract.collect(run_context(segments=["clinics-in"]), router=FakeRouter())
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


def test_a_nul_character_in_a_page_never_fails_the_batch(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live, 13 Nov 2026: a stray NUL (0x00) in one page's quote failed the whole morning batch of 60."""
    bid = seed_business()
    raw = facts_json(url=f"{SITE}/")
    raw["business_name"]["value"] = "Extract\x00 Clinic"
    batch(monkeypatch, FakeBatch([item(bid, FactsExtraction.model_validate(raw))]))
    out = extract.collect(run_context(segments=["clinics-in"]), router=FakeRouter())
    assert out["businesses"] == 1 and not out.get("write_failed")
    assert extract.no_nul({"a\x00": ["b\x00", 1]}) == {"a": ["b", 1]}


def test_collect_can_rebuild_inputs_for_a_retry(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    bid = seed_business()
    fake = batch(monkeypatch, FakeBatch([item(bid, None, error="invalid JSON")]))
    out = extract.collect(run_context(segments=["clinics-in"]), router=FakeRouter())
    rebuilt = fake.rebuilt[f"extract_facts:{bid}"]
    assert rebuilt is not None and rebuilt["business_name"] == "Extract Clinic" and rebuilt["pages"]
    assert out["failed"] == 1  # still invalid after the retry: stays queued, marked for a look
    row = db.fetch_one("select status, reject_reason from public.businesses where id = %s", [bid])
    assert row == {"status": "queued", "reject_reason": "extract_failed"}


def test_without_a_router_nothing_is_submitted(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_business()
    monkeypatch.setattr("nument_engine.sources.base.router_for_run", lambda rc: None)
    out = extract.submit(run_context(segments=["clinics-in"]))
    assert out["skipped"] == "no AI router"


# ---------------------------------------------------------------------------------------------------
# extract_facts v2: the startup fields (15 Nov 2026)
# ---------------------------------------------------------------------------------------------------

STARTUP = "https://brightcart-nlead.io"
STARTUP_TEAM = (
    "Our team\nMaya Chen, Co-founder and CEO, ex-McKinsey\nTom Price, Co-founder and COO\n"
    "We are a team of 4 building the checkout for small shops."
)
STARTUP_HOME = (
    "BrightCart\nAI checkout assistant for independent shops.\nJoin the waitlist for early access.\n"
    "Backed by Pioneer Fund: we raised a $400K pre-seed round in March 2026.\nFounded in 2025.\n"
    "We are looking for a technical co-founder to build the first version."
)


def startup_json() -> dict[str, Any]:
    team = f"{STARTUP}/team"
    return {
        "business_name": {"quote": "BrightCart", "url": f"{STARTUP}/", "value": "BrightCart"},
        "team_members": [
            {"quote": "Maya Chen, Co-founder and CEO", "url": team, "name": "Maya Chen", "role": "Co-founder and CEO",
             "is_founder": True, "is_engineer": False},
            {"quote": "Tom Price, Co-founder and COO", "url": team, "name": "Tom Price", "role": "Co-founder and COO",
             "is_founder": True, "is_engineer": False},
        ],
        "team_size": {"quote": "We are a team of 4 building the checkout", "url": team, "count": 4},
        "founded_year": {"quote": "Founded in 2025.", "url": f"{STARTUP}/", "year": 2025},
        "product_status": {"quote": "Join the waitlist for early access.", "url": f"{STARTUP}/", "value": "waitlist"},
        "uses_ai": {"quote": "AI checkout assistant for independent shops.", "url": f"{STARTUP}/", "value": True},
        "funding_mentions": [
            {"quote": "we raised a $400K pre-seed round in March 2026", "url": f"{STARTUP}/", "round": "pre-seed",
             "amount": 400000, "currency": "USD", "date": "March 2026"}
        ],
        "revenue_hints": [],
        "tech_statements": [
            {"quote": "We are looking for a technical co-founder to build the first version.", "url": f"{STARTUP}/",
             "kind": "no_technical_team"}
        ],
    }  # fmt: skip


def test_v2_startup_fields_flatten_into_facts() -> None:
    rows = flatten(FactsExtraction.model_validate(startup_json()))
    by_field: dict[str, list[dict[str, Any]]] = {}
    for f, v, _, _ in rows:
        by_field.setdefault(f, []).append(v)
    assert by_field["team_member"][0] == {
        "name": "Maya Chen", "role": "Co-founder and CEO", "is_founder": True, "is_engineer": False
    }  # fmt: skip
    assert len(by_field["team_member"]) == 2
    assert by_field["team_size"] == [{"count": 4}] and by_field["founded_year"] == [{"year": 2025}]
    assert by_field["product_status"] == [{"value": "waitlist", "platform": None}]
    assert by_field["uses_ai"] == [{"value": True}]
    assert by_field["funding_mention"] == [
        {"round": "pre-seed", "amount": 400000.0, "currency": "USD", "date": "March 2026"}
    ]
    assert by_field["tech_statement"] == [{"kind": "no_technical_team"}]
    assert {f for f in by_field} <= set(extract.AI_FIELDS)  # replaced on the next extraction


def test_v1_answers_still_parse_and_leave_the_startup_fields_empty() -> None:
    old = FactsExtraction.model_validate(facts_json())
    assert old.team_members == [] and old.funding_mentions == [] and old.product_status is None
    assert not {f for f, *_ in flatten(old)} & {"team_member", "funding_mention", "product_status"}


@pytest.mark.parametrize(
    "bad",
    [
        {"team_members": [{"quote": "Maya Chen, CEO", "url": "u", "name": "Maya Chen", "is_founder": True}]},
        {"product_status": {"quote": "Join the waitlist", "url": "u", "value": "beta"}},
        {"revenue_hints": [{"quote": "Paid plans from $9", "url": "u", "kind": "income", "value": "$9"}]},
        {"funding_mentions": [{"quote": "We raised 1M", "url": "u", "amount": -5}]},
        {"founded_year": {"quote": "Since 1066 and all that", "url": "u", "year": 1066}},
        {"tech_statements": [{"quote": "x" * 301, "url": "u", "kind": "no_code"}]},
    ],
)
def test_v2_output_validation_refuses_bad_values(bad: dict[str, Any]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FactsExtraction.model_validate(bad)


def test_v2_prompt_asks_for_startup_fields_only_in_startup_segments() -> None:
    from nument_engine.llm import prompts
    from nument_engine.llm.health import SMOKE_INPUTS

    prompt = prompts.load("extract_facts.md", directory=extract_prompt_dir())
    assert prompt.version == 2
    startup, _ = prompt.render(**{**SMOKE_INPUTS["extract_facts"], "domain": "firms"})
    clinic, _ = prompt.render(**SMOKE_INPUTS["extract_facts"])
    assert "team_members: the people the pages list as the team" in startup and "Leave the startup" not in startup
    assert "Leave the startup fields empty" in clinic and "team_members: the people" not in clinic


def extract_prompt_dir() -> Any:
    from pathlib import Path

    return Path(extract.__file__).resolve().parents[3] / "prompts"


def test_startup_pages_get_their_own_budgets_and_numbered_kinds_count_as_their_kind() -> None:
    assert extract.base_kind("blog_2") == "blog" and extract.base_kind("press") == "press"
    trimmed = trim_pages(
        [
            PageIn("blog_2", f"{STARTUP}/blog/launch", "We launched on Product Hunt today.", "b2"),
            PageIn("imprint", f"{STARTUP}/imprint", "Managing director: Maya Chen", "i1"),
            PageIn("press", f"{STARTUP}/press", "BrightCart raises $400K pre-seed", "p9"),
            PageIn("home", f"{STARTUP}/", STARTUP_HOME, "h1"),
        ]
    )
    assert [p.kind for p in trimmed] == ["home", "press", "blog_2", "imprint"]


def test_startup_key_lines_survive_trimming() -> None:
    filler = "\n".join(f"Paragraph {i} about how much shop owners love a calm checkout." for i in range(400))
    page = PageIn("home", f"{STARTUP}/", filler + "\nWe raised a $400K pre-seed round\n" + filler, "h1")
    assert "We raised a $400K pre-seed round" in trim_pages([page])[0].text


def seed_startup(**kw: Any) -> str:
    bid = insert_business(
        segment_id="firms-us",
        country="us",
        city="San Francisco",
        name="BrightCart",
        website=f"{STARTUP}/",
        web_domain="brightcart-nlead.io",
        status="queued",
        queued_at=datetime.now(UTC),
        queue_priority=10,
        **kw,
    )
    crawl = {}
    for kind, url, text in (("home", f"{STARTUP}/", STARTUP_HOME), ("team", f"{STARTUP}/team", STARTUP_TEAM)):
        db.execute("insert into public.pages (business_id, url, text) values (%s, %s, %s)", [bid, url, text])
        crawl[kind] = url
    db.execute(
        "update public.businesses set extra = jsonb_set(extra, '{crawl}', %s) where id = %s",
        [db.Jsonb({"state": "ok", "pages": crawl, "at": datetime.now(UTC).isoformat()}), bid],
    )
    return bid


def test_collect_stores_the_startup_fields_as_facts(firms_us: str, monkeypatch: pytest.MonkeyPatch) -> None:
    bid = seed_startup()
    out = FactsExtraction.model_validate(startup_json())
    batch(monkeypatch, FakeBatch([item(bid, out)]))
    stats = extract.collect(run_context(segments=["firms-us"]), router=FakeRouter())
    assert stats["businesses"] == 1
    facts = db.fetch_all(
        "select field, value, url, page_id from public.facts where business_id = %s and model <> 'rule'", [bid]
    )
    fields = sorted(f["field"] for f in facts)
    assert fields.count("team_member") == 2 and "funding_mention" in fields and "tech_statement" in fields
    team = [f for f in facts if f["field"] == "team_member"]
    assert all(f["url"] == f"{STARTUP}/team" and f["page_id"] for f in team)
    # a second answer replaces the first one's startup facts instead of piling up
    batch(monkeypatch, FakeBatch([item(bid, out)]))
    db.execute("update public.businesses set status = 'queued' where id = %s", [bid])
    extract.collect(run_context(segments=["firms-us"]), router=FakeRouter())
    assert db.scalar("select count(*) from public.facts where business_id = %s and field = 'team_member'", [bid]) == 2
