"""SEC EDGAR Form D and Form C (lane E1b, 15 Nov 2026): the daily form index, each filing's primary document, the
startup rules, routing, dedupe, the daily cap and SEC's fair-access rules. Fixtures are trimmed real EDGAR files
(tests/fixtures/e1b): the 12 Nov 2026 form index, the quarter's listing and Form D, D/A and C/A documents."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine import db
from nument_engine import settings as settings_module
from nument_engine.pipeline.signals import SignalSink
from nument_engine.segments import load_segments, sync_segments_to_db
from nument_engine.sources import sec_edgar as sec
from nument_engine.sources.sec_edgar import Filing, IndexEntry, SecEdgarAdapter

from .sources_helpers import clean_db, ctx, mock_transport, no_network

__all__ = ["clean_db", "no_network"]

FIX = Path(__file__).resolve().parent / "fixtures" / "e1b"
UA = "Nument Leads leads-test@example.com"
NOW = datetime(2026, 11, 13, 20, 30, tzinfo=UTC)  # 02:00 IST on 14 Nov; 15:30 in New York on Friday 13 Nov
DAILY = "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/"
DATA = "https://www.sec.gov/Archives/edgar/data/"
SEGMENTS = load_segments()


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def entry(form: str = "D", accession: str = "0002164767-26-000001", cik: str = "2164767") -> IndexEntry:
    return IndexEntry(form, "Care Nimble, Inc.", cik, date(2026, 11, 12), accession)


def doc(cik: str, accession: str) -> str:
    return f"{DATA}{cik}/{accession.replace('-', '')}/primary_doc.xml"


def form_c(name: str, cik: str, employees: int, website: str, form: str = "C") -> str:
    """A Form C built from the real C/A document with another issuer."""
    text = fixture("sec_form_c_amendment.xml")
    text = text.replace("<submissionType>C/A</submissionType>", f"<submissionType>{form}</submissionType>")
    text = text.replace("SwiftSift, Inc.", name).replace("0002144403", cik.zfill(10))
    text = text.replace("<currentEmployees>3</currentEmployees>", f"<currentEmployees>{employees}</currentEmployees>")
    return text.replace("https://swiftsift.net", website)


HEADER_ONLY = "\n".join(fixture("sec_form_20261112.idx").splitlines()[:11]) + "\n"


def routes(**docs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "https://www.sec.gov/robots.txt": (200, "User-agent: *\nAllow: /Archives/edgar/data\nDisallow: /cgi-bin\n"),
        DAILY + "index.json": (200, json.loads(fixture("sec_listing_2026_q4.json"))),
        DAILY + "form.20261110.idx": (200, HEADER_ONLY),
        DAILY + "form.20261112.idx": (200, fixture("sec_form_20261112.idx")),
        DAILY + "form.20261113.idx": (200, HEADER_ONLY),
        doc("2103234", "0002103234-26-000002"): (
            200,
            form_c("MAF Hospitality Holdings, LLC", "2103234", 25, "mafhg.com"),
        ),
        doc("2144403", "0002144403-26-000002"): (200, fixture("sec_form_c_amendment.xml")),
        doc("2164767", "0002164767-26-000001"): (200, fixture("sec_form_d_care_nimble.xml")),
        doc("2048143", "0002048143-26-000001"): (200, fixture("sec_form_d_amendment_reit.xml")),
        "*": (404, "not found"),
    }
    return base | docs


def adapter(context: Any, transport: httpx.MockTransport) -> SecEdgarAdapter:
    a = SecEdgarAdapter(context, user_agent=UA, transport=transport)
    a.clock = lambda: NOW
    return a


@pytest.fixture(autouse=True)
def _no_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SecEdgarAdapter, "min_gap_s", 0.0)


def verdicts() -> dict[str, str]:
    rows = db.fetch_all(
        "select source_key, payload->>'verdict' as verdict from public.source_records "
        "where source = 'sec_edgar' and source_key like 'filing:%'"
    )
    return {r["source_key"].removeprefix("filing:"): r["verdict"] for r in rows}


# ---- the index -------------------------------------------------------------------------------------------


def test_the_daily_index_keeps_only_form_d_and_c_lines() -> None:
    entries = sec.parse_index(fixture("sec_form_20261112.idx"))
    assert {e.form for e in entries} == {"C", "C/A", "D", "D/A"}  # C-AR, C-U, C-W and Form 4 are not raises
    care = next(e for e in entries if e.cik == "2164767")
    assert care == IndexEntry("D", "Care Nimble, Inc.", "2164767", date(2026, 11, 12), "0002164767-26-000001")
    assert care.key == "filing:0002164767-26-000001" and care.folder == "000216476726000001"
    assert len([e for e in entries if e.cik == "2113098"]) == 4  # one issuer filed four times that day
    assert sec.parse_index("garbage\nD  no columns here\n") == []


@pytest.mark.parametrize(
    ("name", "vehicle"),
    [
        ("8VC AI Fund XII, LLC", True),
        ("26North Diversified Credit Income Fund LP", True),
        ("AQR Flex 1 Series LLC - Series B16", True),
        ("Glide Lending SPV, LLC", True),
        ("8 Mercer Opportunities TML, L.P.", True),
        ("BHAV Acquisition Corp II", True),
        ("Care Nimble, Inc.", False),
        ("Blue Sky Robotics, Inc.", False),
        ("Trustworthy AI Inc.", False),  # "trust" only as a whole word
        ("Parallel Domain, Inc.", False),
    ],
)
def test_vehicles_are_recognised_by_name(name: str, vehicle: bool) -> None:
    assert sec.looks_like_vehicle(name) is vehicle


def test_listing_window_and_priority() -> None:
    names = sec.listed_indexes(json.loads(fixture("sec_listing_2026_q4.json")))
    assert "form.20261112.idx" in names and "form.20261111.idx" not in names  # 11 Nov: Veterans Day
    assert sec.listed_indexes({"unexpected": 1}) == set() and sec.listed_indexes(None) == set()
    assert sec.window(NOW) == [date(2026, 11, d) for d in (13, 12, 11, 10, 9)]  # no weekend days
    assert sec.window(datetime(2026, 11, 14, 3, 0, tzinfo=UTC))[0] == date(2026, 11, 13)  # still the 13th in NY
    entries = [
        IndexEntry("D/A", "A LLC", "1", date(2026, 11, 12), "0000000001-26-000001"),
        IndexEntry("D", "B LLC", "2", date(2026, 11, 12), "0000000002-26-000001"),
        IndexEntry("D", "C, Inc.", "3", date(2026, 11, 10), "0000000003-26-000001"),
        IndexEntry("D", "D Corp", "4", date(2026, 11, 12), "0000000004-26-000001"),
        IndexEntry("C", "E LLC", "5", date(2026, 11, 10), "0000000005-26-000001"),
    ]
    assert [e.cik for e in sorted(entries, key=sec.priority)] == ["5", "4", "3", "2", "1"]


# ---- the documents -----------------------------------------------------------------------------------------


def test_a_form_d_is_read_with_its_officers() -> None:
    f = sec.parse_filing(fixture("sec_form_d_care_nimble.xml"), entry(), NOW)
    assert (f.form, f.name, f.state, f.country, f.city) == ("D", "Care Nimble, Inc.", "DE", "us", "Dover")
    assert (f.entity_type, f.year_of_inc, f.industry) == ("Corporation", 2026, "Other Health Care")
    assert (f.offering_usd, f.sold_usd, f.first_sale, f.investor_count) == (1_500_000, 275_000, date(2026, 10, 30), 2)
    assert [(p.name, p.role) for p in f.people] == [
        ("Raymond Costantini", "CEO"),  # the signer's own title
        ("Andrew Migliore", "Executive Officer, Director, Promoter"),
        ("Erik Vanderlip", "Director, Promoter"),
    ]
    assert sec.drop_reason(f, NOW, (10, 2_000_000)) is None


def test_a_form_c_gives_the_website_and_the_team_size() -> None:
    f = sec.parse_filing(fixture("sec_form_c_amendment.xml"), entry("C/A", "0002144403-26-000002", "2144403"), NOW)
    assert (f.form, f.name, f.country, f.website, f.employees) == (
        "C/A",
        "SwiftSift, Inc.",
        "us",
        "https://swiftsift.net",
        3,
    )
    assert (f.offering_usd, f.max_offering_usd, f.deadline) == (10_000, 1_200_000, date(2027, 2, 12))
    assert (f.portal, f.security, f.year_of_inc) == ("NetCapital Funding Portal Inc.", "SAFE", 2025)
    assert [(p.name, p.role) for p in f.people] == [
        ("Michael Novielli", "Principal Executive Officer, Principal Financial Officer")
    ]
    assert sec.drop_reason(f, NOW, (10, 2_000_000)) is None


@pytest.mark.parametrize(
    ("fixture_name", "reason"),
    [("sec_form_d_fund.xml", "fund"), ("sec_form_d_amendment_reit.xml", "real_estate")],
)
def test_funds_and_property_companies_are_dropped(fixture_name: str, reason: str) -> None:
    f = sec.parse_filing(fixture(fixture_name), entry(), NOW)
    assert sec.drop_reason(f, NOW, (10, 2_000_000)) == reason


def base_filing(**changes: Any) -> Filing:
    values: dict[str, Any] = {
        "form": "D", "accession": "0000000001-26-000001", "cik": "1", "filed": date(2026, 11, 12), "name": "Acme, Inc.",
        "country": "us", "entity_type": "Corporation", "industry": "Other Technology", "offering_usd": 900_000.0,
    }  # fmt: skip
    return Filing(**{**values, **changes})


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({}, None),
        ({"live": False}, "test_filing"),
        ({"industry": "Commercial Banking"}, "banking"),
        ({"industry": "Residential"}, "real_estate"),
        ({"tenant_in_common": True}, "real_estate"),
        ({"mineral_property": True}, "mineral_property"),
        ({"entity_type": "Limited Partnership"}, "partnership"),
        ({"business_combination": True}, "business_combination"),
        ({"over_five_years": True}, "older_company"),
        ({"first_sale": date(2026, 4, 1)}, "stale_offering"),
        ({"first_sale": date(2026, 6, 1)}, None),  # 165 days: still fresh
        ({"offering_usd": 2_500_000.0}, "raise_too_big"),
        ({"offering_usd": None, "offering_indefinite": True, "sold_usd": 2_100_000.0}, "raise_too_big"),
        ({"offering_usd": 1_500_000.0, "sold_usd": 2_600_000.0}, "raise_too_big"),
        ({"form": "C", "employees": 11}, "too_big"),
        ({"form": "C", "employees": 10}, None),
    ],
)
def test_the_startup_rules(changes: dict[str, Any], reason: str | None) -> None:
    assert sec.drop_reason(base_filing(**changes), NOW, (10, 2_000_000)) == reason


@pytest.mark.parametrize(
    ("code", "description", "country"),
    [
        ("DE", "DELAWARE", "us"),
        ("NC", None, "us"),
        ("PR", "PUERTO RICO", "us"),
        ("X0", "UNITED KINGDOM", "gb"),
        ("A6", "ONTARIO, CANADA", "ca"),
        ("K7", "INDIA", "in"),
        ("2M", "GERMANY", None),  # not a country outreach writes to
        (None, None, None),
    ],
)
def test_edgar_codes_become_countries(code: str | None, description: str | None, country: str | None) -> None:
    assert sec.country_of(code, description) == country


def test_names_and_websites() -> None:
    assert sec.person_name("DEVON", "KENNARD") == "Devon Kennard"
    assert sec.person_name("Raymond", "Costantini") == "Raymond Costantini"
    assert sec.person_name("N/A", "Acme Capital Management LLC") is None
    assert sec.person_name("John", "Smith Holdings") is None
    assert sec.company_site("swiftsift.net") == "https://swiftsift.net"
    assert sec.company_site("https://wefunder.com/swiftsift") is None  # the portal's page, not the company's site
    assert sec.company_site("https://www.facebook.com/swiftsift") is None
    assert sec.company_site("N/A") is None and sec.company_site(None) is None


def test_a_document_type_declaration_or_garbage_is_never_read() -> None:
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><edgarSubmission>&a;</edgarSubmission>'
    for text in (evil, "<html>not a filing</html>", "plain text"):
        with pytest.raises(ValueError):
            sec.parse_filing(text, entry(), NOW)


# ---- the whole source --------------------------------------------------------------------------------------


async def test_a_run_reads_the_open_days_and_turns_startups_into_funding_signals(clean_db: str) -> None:
    transport, seen = mock_transport(routes())
    context = ctx()
    async with adapter(context, transport) as a:
        sigs = await a.signals_for(SEGMENTS)
    assert {r.headers["user-agent"] for r in seen} == {UA}  # SEC fair access: every request names us
    assert not any("20261111" in str(r.url) or "20261109" in str(r.url) for r in seen)  # no index that day: never asked
    by_name = {s.business_hint["name"]: s for s in sigs}
    assert set(by_name) == {"Care Nimble, Inc.", "SwiftSift, Inc."}

    care = by_name["Care Nimble, Inc."]
    assert (care.type, care.source, care.segment_id, care.quote) == ("funding", "sec_edgar", "firms-us", None)
    assert care.url == f"{DATA}2164767/000216476726000001/0002164767-26-000001-index.htm"
    assert care.evidence_key == "sec:0002164767-26-000001"
    assert care.observed_at == datetime(2026, 11, 12, 17, 0, tzinfo=UTC)  # noon in New York on the filing day
    d = care.details
    assert (d["form"], d["round"], d["amount_usd"], d["amount_sold_usd"]) == ("D", "unknown", 1_500_000, 275_000)
    assert (d["first_sale"], d["industry"], d["year_of_inc"], d["cik"]) == (
        "2026-10-30",
        "Other Health Care",
        2026,
        "2164767",
    )
    assert d["founders"][0] == {"name": "Raymond Costantini", "role": "CEO", "source_url": care.url}
    assert len(d["founders"]) == 3 and "team_size" not in d
    assert care.business_hint == {"name": "Care Nimble, Inc.", "city": None, "website": None}

    swift = by_name["SwiftSift, Inc."]
    assert swift.evidence_key == "sec:C-2144403" and swift.business_hint["website"] == "https://swiftsift.net"
    assert (swift.details["team_size"], swift.details["team_size_source"], swift.details["round"]) == (
        3,
        "filing",
        "crowdfunding",
    )

    got = verdicts()
    assert got["0002164767-26-000001"] == "signal" and got["0002144403-26-000002"] == "signal"
    assert got["0002103234-26-000002"] == "too_big"  # 25 employees
    assert got["0002048143-26-000001"] == "real_estate"
    assert got["0001930007-26-000009"] == "no_document"  # the "*" route answers 404
    assert list(got.values()).count("same_issuer") == 3  # NEXROC filed four times: one is read
    assert not any(k.startswith(("0002162326", "0002159077", "0002110380", "0002093045")) for k in got)  # vehicles
    done = {
        r["source_key"]
        for r in db.fetch_all("select source_key from public.source_records where source_key like 'index:%'")
    }
    assert done == {"index:2026-11-10", "index:2026-11-12", "index:2026-11-13"}

    transport2, seen2 = mock_transport(routes())
    async with adapter(ctx(), transport2) as again:
        assert await again.signals_for(SEGMENTS) == []
    assert all(str(r.url).endswith(("robots.txt", "index.json")) for r in seen2)  # nothing is read twice


async def test_signals_create_startup_businesses_that_wait_for_their_website(clean_db: str) -> None:
    with db.tx() as conn:
        sync_segments_to_db(conn, {"firms-us": SEGMENTS["firms-us"]})
    transport, _ = mock_transport(routes())
    context = ctx()
    async with adapter(context, transport) as a:
        sigs = await a.signals_for(SEGMENTS)
    sink = SignalSink({"firms-us": SEGMENTS["firms-us"]}, context)
    for sig in sigs:
        sink.add(sig, SEGMENTS["firms-us"])
    sink.flush()
    rows = db.fetch_all(
        "select b.name, b.website, b.extra->>'born_from' as born, s.points, s.details->'founders' as founders "
        "from public.signals s join public.businesses b on b.id = s.business_id where s.source = 'sec_edgar' "
        "order by b.name"
    )
    assert [(r["name"], r["website"], r["born"]) for r in rows] == [
        ("Care Nimble, Inc.", None, "sec_edgar"),  # the lookup stage finds its website
        ("SwiftSift, Inc.", "https://swiftsift.net/", "sec_edgar"),
    ]
    assert all(float(r["points"]) == 5.0 for r in rows) and rows[0]["founders"][0]["name"] == "Raymond Costantini"


async def test_the_daily_cap_and_a_server_error_leave_the_day_open(clean_db: str) -> None:
    db.set_setting("sec_edgar.filings_per_day", 2)
    transport, seen = mock_transport(routes(**{doc("2009632", "0002093398-26-000003"): (500, "busy")}))
    context = ctx()
    async with adapter(context, transport) as a:
        assert await a.signals_for(SEGMENTS) == []
    fetched = [str(r.url) for r in seen if str(r.url).endswith("primary_doc.xml")]
    assert fetched[0] == doc("2103234", "0002103234-26-000002")  # Form C first
    assert fetched[1:] == [doc("2009632", "0002093398-26-000003")] * 2  # then the best Form D, retried once
    assert context.stats["sec_edgar.http_500"] == 1
    got = verdicts()
    assert "0002093398-26-000003" not in got  # a server error is not an answer: read again later
    assert db.scalar("select count(*) from public.source_records where source_key = 'index:2026-11-12'") == 0
    async with adapter(ctx(), mock_transport(routes())[0]) as a:
        assert a.filings_left() == 1  # the 500 did not count; the Form C did


async def test_a_block_stops_the_source_but_keeps_what_it_found(clean_db: str) -> None:
    blocked = {doc("2113098", "0002113098-26-000036"): (403, "<html><title>Access Denied</title></html>")}
    good = {doc("2009632", "0002093398-26-000003"): (200, fixture("sec_form_d_care_nimble.xml"))}
    transport, seen = mock_transport(routes(**blocked, **good))
    context = ctx()
    async with adapter(context, transport) as a:
        sigs = await a.signals_for(SEGMENTS)
        assert a.blocked
    assert [s.business_hint["name"] for s in sigs] == ["Care Nimble, Inc."]  # found before the block
    assert not any(str(r.url) == doc("2164264", "0002164264-26-000001") for r in seen)  # nothing after it
    row = db.fetch_one("select blocked_until from public.source_health where source = 'sec_edgar'")
    assert row is not None and row["blocked_until"] > NOW
    assert context.alerts and "sec_edgar blocked" in context.alerts[0]


async def test_an_amendment_joins_the_offering_it_amends(clean_db: str) -> None:
    transport, _ = mock_transport(routes())
    async with adapter(ctx(), transport) as a:
        await a.signals_for(SEGMENTS)
        amended = (
            fixture("sec_form_d_care_nimble.xml")
            .replace("<submissionType>D</submissionType>", "<submissionType>D/A</submissionType>")
            .replace(
                "<isAmendment>false</isAmendment>",
                "<isAmendment>true</isAmendment><previousAccessionNumber>0002164767-26-000001</previousAccessionNumber>",
            )
        )
        f = sec.parse_filing(amended, entry("D/A", "0002164767-26-000004"), NOW)
        assert a.offering_key(f) == "0002164767-26-000001"
        f.previous_accession = "0009999999-25-000001"  # an offering filed before we started reading
        assert a.offering_key(f) == "0009999999-25-000001"
        f.form, f.previous_accession = "D", None
        assert a.offering_key(f) == "0002164767-26-000004"


async def test_without_a_user_agent_the_source_stops_quietly(clean_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    settings_module.get_settings.cache_clear()
    context = ctx()
    await sec.watch(context, dict(SEGMENTS), sink=None)
    assert context.stats["sec_edgar.no_user_agent"] == 1 and "sec_edgar" in context.stats["skip_reasons"]
    assert context.alerts == []


async def test_bad_listing_or_index_is_skipped_quietly(clean_db: str) -> None:
    transport, _ = mock_transport(routes(**{DAILY + "index.json": (200, "{not json")}))
    context = ctx()
    async with adapter(context, transport) as a:
        assert await a.signals_for(SEGMENTS) == []
    assert context.stats["sec_edgar.bad_listing"] == 1
    transport, _ = mock_transport(routes(**{DAILY + "form.20261112.idx": (500, "")}))
    context = ctx()
    async with adapter(context, transport) as a:
        assert await a.signals_for(SEGMENTS) == []
    assert context.stats["sec_edgar.http_500"] == 1
    assert db.scalar("select count(*) from public.source_records where source_key = 'index:2026-11-12'") == 0


async def test_no_startup_segment_means_no_request(clean_db: str) -> None:
    transport, seen = mock_transport(routes())
    context = ctx()
    async with adapter(context, transport) as a:
        assert await a.signals_for({"clinics-in": SEGMENTS["clinics-in"]}) == []
    assert seen == [] and context.stats["sec_edgar.no_startup_segment"] == 1
