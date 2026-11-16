"""US SEC Form D and Form C filings from EDGAR's daily form index: small private raises, with their officers.

A Form D (Regulation D) or Form C (Regulation Crowdfunding) is filed by the company itself within days of
raising money, so it is fresh, dated and public. Each run:

1. reads the quarter's daily-index listing (`index.json`) to learn which business days have an index: a missing
   day (a weekend or a holiday) answers 403 at SEC, which must never be mistaken for a block;
2. reads `form.YYYYMMDD.idx` for the days of the last week that are not done yet and keeps the D, D/A, C and C/A
   lines; filings already read (`source_records` key `filing:<accession>`) and issuers whose name says they are a
   fund or a property vehicle are skipped before any document is fetched; several filings of one issuer in the
   same run count once;
3. fetches each filing's `primary_doc.xml` (Form C first, then new Form D, then amendments; newest first), at
   most `sec_edgar.filings_per_day` a day, and reads it with code, never AI.

Form D gives the issuer, its state, year of incorporation, industry group, the offering size, the amount sold,
the date of first sale and the related persons (executive officers, directors, promoters), who become
`details.founders` with their relationship. Form C gives the issuer's website, its current employees (team size
evidence), the target and maximum amounts and the people who signed it. Dropped by rule: pooled investment funds,
banking, insurance and investing, real estate, partnerships, business combinations, companies incorporated more
than five years ago, offerings whose first sale is older than 180 days, and anything over `startup.max_raise_usd`
or `startup.max_team` (`sources/startup.py`). US issuers go to `firms-us`; a Form D issuer abroad goes to its own
country's startup segment when outreach allows that country.

The signal is `funding`, dated the day of filing, with the filing's index page as its URL and no quote (a filing
is a form, not prose: its fields are in `details`). An amendment updates the signal of the offering it amends
(`previousAccessionNumber`), so one offering is one signal.

SEC fair access: every request carries `settings.sec_user_agent` (a name and contact email); without it the
source reports `sec_edgar.no_user_agent` and stops. Requests are spaced 0.2 seconds (at most 5 a second, SEC
allows 10), robots.txt is read and obeyed, and a block (403 or 429 on a file that exists) pauses the source.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .. import db
from ..http import PoliteClient, SourceBlocked, host_blocked
from ..logging import get_logger
from ..normalize import city_for_text, clean_text, web_domain
from ..segments import Segment
from ..settings import get_settings
from . import health, startup
from .base import Signal, SourceAdapter, SourceContext

log = get_logger()

NAME = "sec_edgar"
BASE = "https://www.sec.gov"
DAILY_LISTING = BASE + "/Archives/edgar/daily-index/{year}/QTR{quarter}/index.json"
DAILY_INDEX = BASE + "/Archives/edgar/daily-index/{year}/QTR{quarter}/{name}"
FILING_DOC = BASE + "/Archives/edgar/data/{cik}/{folder}/primary_doc.xml"
FILING_PAGE = BASE + "/Archives/edgar/data/{cik}/{folder}/{accession}-index.htm"
FORMS: tuple[str, ...] = ("D", "D/A", "C", "C/A")
FORM_ORDER = {"C": 0, "D": 1, "C/A": 2, "D/A": 3}  # crowdfunding first: it names the website and the team size
SETTING = "sec_edgar.filings_per_day"
DEFAULT_PER_DAY = 60
LOOKBACK_DAYS = 6  # calendar days of daily indexes read each run (weekends and holidays have none)
GAP_S = 0.2  # SEC fair access allows 10 requests a second; we make at most 5
INDEX_BYTES = 12_000_000
DOC_BYTES = 2_000_000
MAX_SALE_AGE_DAYS = 180
EASTERN = ZoneInfo("America/New_York")

# Industry groups that are never a startup lead (Form D `industryGroupType`, the most specific value is written).
BANKING = frozenset(
    {"Commercial Banking", "Insurance", "Investing", "Investment Banking", "Pooled Investment Fund",
     "Other Banking and Financial Services"}
)  # fmt: skip
REAL_ESTATE = frozenset({"Commercial", "Construction", "REITS and Finance", "Residential", "Other Real Estate"})
PARTNERSHIPS = frozenset({"Limited Partnership", "General Partnership", "Business Trust"})
# Issuer names that are funds, investment vehicles or property companies: skipped before any fetch. Kept narrow on
# purpose (the industry group decides for everything else).
_VEHICLE_NAME = re.compile(
    r"(?<![a-z0-9])(?:funds?|l\.?\s?p\.?|limited partnership|dst|spv|spe|trust|reit|co-?invest\w*|feeder|"
    r"a series of|series [a-z]?\d[\w-]*|acquisition corp\w*|bancorp|bancshares|bank|real estate|realty|"
    r"properties|apartments|mortgage|opportunity zone|qof)(?![a-z0-9])",
    re.I,
)
_CORPORATION = re.compile(r"(?<![a-z0-9])(?:inc|corp|corporation|pbc|co)\.?$", re.I)
_ENTRY = re.compile(
    r"^(?P<form>[A-Z0-9/-]+(?: [A-Z0-9/-]+)?)\s+(?P<company>.*?)\s+(?P<cik>\d{1,10})\s+(?P<date>\d{8})\s+"
    r"(?P<path>edgar/data/\d+/(?P<accession>\d{10}-\d{2}-\d{6})\.txt)\s*$"
)
_ENTITY_WORDS = re.compile(
    r"(?<![a-z0-9])(?:llc|inc|ltd|lp|corp|fund|partners|management|capital|holdings|trust)(?![a-z0-9])", re.I
)
_NOT_A_NAME = frozenset({"n/a", "na", "-", "none", "not applicable", "."})
US_STATES = frozenset(
    ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
     "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
     "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "GU", "VI"]
)  # fmt: skip
# EDGAR's country descriptions for the countries outreach may write to (config/outreach.yaml).
COUNTRY_NAMES: dict[str, str] = {
    "UNITED KINGDOM": "gb", "INDIA": "in", "SINGAPORE": "sg", "AUSTRALIA": "au", "CANADA": "ca",
    "UNITED ARAB EMIRATES": "ae", "IRELAND": "ie", "NETHERLANDS": "nl", "FRANCE": "fr", "SWEDEN": "se",
    "FINLAND": "fi", "BELGIUM": "be", "PORTUGAL": "pt", "NEW ZEALAND": "nz", "BRAZIL": "br", "MEXICO": "mx",
    "PHILIPPINES": "ph", "MALAYSIA": "my", "INDONESIA": "id",
}  # fmt: skip
# Crowdfunding portals and other hosts a Form C may give instead of the company's own site.
NOT_COMPANY_SITES: tuple[str, ...] = (
    "wefunder.com", "startengine.com", "republic.com", "republic.co", "netcapital.com", "mainvest.com",
    "honeycombcredit.com", "seedinvest.com", "picmii.com", "trucrowd.com", "dealmaker.tech", "crowdfundr.com",
    "linktr.ee", "notion.site", "google.com", "sites.google.com", "wixsite.com", "carrd.co",
)  # fmt: skip


# ---------------------------------------------------------------------------------------------------
# The daily index
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexEntry:
    form: str
    company: str
    cik: str
    filed: date
    accession: str

    @property
    def key(self) -> str:
        return f"filing:{self.accession}"

    @property
    def folder(self) -> str:
        return self.accession.replace("-", "")


def quarter(day: date) -> int:
    return (day.month - 1) // 3 + 1


def index_name(day: date) -> str:
    return f"form.{day:%Y%m%d}.idx"


def window(now: datetime, days: int = LOOKBACK_DAYS) -> list[date]:
    """Weekdays of the last `days` calendar days, newest first, in New York time (EDGAR's own clock)."""
    today = now.astimezone(EASTERN).date()
    out = [today - timedelta(days=i) for i in range(days + 1)]
    return [d for d in out if d.weekday() < 5]


def listed_indexes(data: Any) -> set[str]:
    """File names in a daily-index directory listing (`index.json`)."""
    items = ((data or {}).get("directory") or {}).get("item") or [] if isinstance(data, dict) else []
    return {str(item.get("name")) for item in items if isinstance(item, dict) and item.get("name")}


def parse_index(text: str) -> list[IndexEntry]:
    """The D, D/A, C and C/A lines of a daily form index (fixed-width columns, CIK and date last)."""
    out: list[IndexEntry] = []
    for line in text.splitlines():
        if not line.startswith(("D ", "D/A ", "C ", "C/A ")):
            continue
        m = _ENTRY.match(line.rstrip())
        if not m or m["form"] not in FORMS:
            continue
        try:
            filed = datetime.strptime(m["date"], "%Y%m%d").date()
        except ValueError:
            continue
        out.append(IndexEntry(m["form"], m["company"].strip(), m["cik"], filed, m["accession"]))
    return out


def looks_like_vehicle(company: str) -> bool:
    """A fund, an investment vehicle or a property company, judged by its name alone."""
    return _VEHICLE_NAME.search(company) is not None


def priority(entry: IndexEntry) -> tuple[int, int, int, str]:
    """Sort key: Form C first, then new Form D, then amendments; corporations first; newest first."""
    corporation = 0 if _CORPORATION.search(entry.company.strip().rstrip(",")) else 1
    return (FORM_ORDER[entry.form], corporation, -entry.filed.toordinal(), entry.accession)


# ---------------------------------------------------------------------------------------------------
# The filing
# ---------------------------------------------------------------------------------------------------


@dataclass
class Person:
    name: str
    role: str
    rank: int = 9  # executive officers first, then directors, then promoters


@dataclass
class Filing:
    form: str
    accession: str
    cik: str
    filed: date
    name: str
    live: bool = True
    city: str | None = None
    state: str | None = None
    country: str | None = None
    entity_type: str | None = None
    year_of_inc: int | None = None
    over_five_years: bool = False
    industry: str | None = None
    fund: bool = False
    tenant_in_common: bool = False
    mineral_property: bool = False
    business_combination: bool = False
    offering_usd: float | None = None
    offering_indefinite: bool = False
    sold_usd: float | None = None
    max_offering_usd: float | None = None
    first_sale: date | None = None
    investor_count: int | None = None
    previous_accession: str | None = None
    employees: int | None = None
    website: str | None = None
    portal: str | None = None
    security: str | None = None
    deadline: date | None = None
    people: list[Person] = field(default_factory=list)

    @property
    def crowdfunding(self) -> bool:
        return self.form in ("C", "C/A")

    @property
    def amount_usd(self) -> float | None:
        """The size of the raise: the offering amount (Form C: the target), else what was sold."""
        return self.offering_usd if self.offering_usd is not None else self.sold_usd


def _xml(text: str) -> ET.Element:
    """Parse a filing with every namespace removed. A document type declaration is never read (no entities)."""
    if re.search(r"<!(?:DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("a filing with a document type declaration is not read")
    root = ET.fromstring(text.encode("utf-8"))
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    value = el.findtext(path)
    value = clean_text(value) if value else ""
    return value or None


def _flag(el: ET.Element | None, path: str) -> bool:
    return (_text(el, path) or "").lower() in ("true", "y", "yes")


def _money(value: str | None) -> float | None:
    if not value:
        return None
    try:
        amount = float(value.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    return amount if amount >= 0 else None


def _count(value: str | None) -> int | None:
    amount = _money(value)
    return int(amount) if amount is not None else None


def _date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def country_of(code: str | None, description: str | None = None) -> str | None:
    """ISO country of an EDGAR state-or-country code: US states and territories are "us"; elsewhere the
    description names the country ("ONTARIO, CANADA", "UNITED KINGDOM"). None when unknown."""
    if code and code.upper() in US_STATES:
        return "us"
    desc = (description or "").upper()
    if "CANADA" in desc:
        return "ca"
    return COUNTRY_NAMES.get(desc.strip())


def person_name(first: str | None, last: str | None) -> str | None:
    """ "First Last" of an officer, or None for an entity or a placeholder. A name filed in capitals is
    written in title case ("DEVON KENNARD" is "Devon Kennard"); others are kept as filed."""
    first, last = clean_text(first or "", 60), clean_text(last or "", 60)
    if not first or not last or first.lower() in _NOT_A_NAME or last.lower() in _NOT_A_NAME:
        return None
    name = f"{first} {last}"
    if _ENTITY_WORDS.search(name) or re.search(r"[\d@]", name):
        return None
    return name.title() if name.isupper() else name


def _signature_name(value: str | None) -> str | None:
    name = re.sub(r"^/s/\s*", "", value or "", flags=re.I).strip()
    if not name or len(name.split()) < 2:
        return None
    return name.title() if name.isupper() else name


def parse_form_d(root: ET.Element, entry: IndexEntry) -> Filing:
    issuer = root.find("primaryIssuer")
    offering = root.find("offeringData")
    address = issuer.find("issuerAddress") if issuer is not None else None
    sale_amounts = offering.find("offeringSalesAmounts") if offering is not None else None
    total = _text(sale_amounts, "totalOfferingAmount")
    year = _text(issuer, "yearOfInc/value")
    securities = offering.find("typesOfSecuritiesOffered") if offering is not None else None
    filing = Filing(
        form=_text(root, "submissionType") or entry.form,
        accession=entry.accession,
        cik=entry.cik,
        filed=entry.filed,
        name=_text(issuer, "entityName") or entry.company,
        live=(_text(root, "testOrLive") or "LIVE").upper() == "LIVE",
        city=_text(address, "city"),
        state=_text(address, "stateOrCountry"),
        country=country_of(_text(address, "stateOrCountry"), _text(address, "stateOrCountryDescription")),
        entity_type=_text(issuer, "entityType"),
        year_of_inc=int(year) if year and year.isdigit() else None,
        over_five_years=_flag(issuer, "yearOfInc/overFiveYears"),
        industry=_text(offering, "industryGroup/industryGroupType"),
        fund=_text(offering, "industryGroup/investmentFundInfo/investmentFundType") is not None
        or _flag(securities, "isPooledInvestmentFundType"),
        tenant_in_common=_flag(securities, "isTenantInCommonType"),
        mineral_property=_flag(securities, "isMineralPropertyType"),
        business_combination=_flag(offering, "businessCombinationTransaction/isBusinessCombinationTransaction"),
        offering_usd=_money(total),
        offering_indefinite=(total or "").lower() == "indefinite",
        sold_usd=_money(_text(sale_amounts, "totalAmountSold")),
        first_sale=_date(_text(offering, "typeOfFiling/dateOfFirstSale/value")),
        investor_count=_count(_text(offering, "investors/totalNumberAlreadyInvested")),
        previous_accession=_text(offering, "typeOfFiling/newOrAmendment/previousAccessionNumber"),
    )
    signer = _text(offering, "signatureBlock/signature/nameOfSigner") or _text(
        offering, "signatureBlock/signature/signatureName"
    )
    signer_title = _text(offering, "signatureBlock/signature/signatureTitle")
    for info in root.findall("relatedPersonsList/relatedPersonInfo"):
        name = person_name(_text(info, "relatedPersonName/firstName"), _text(info, "relatedPersonName/lastName"))
        if not name:
            continue
        relations = [clean_text(r.text or "") for r in info.findall("relatedPersonRelationshipList/relationship")]
        relations = [r for r in relations if r]
        rank = min([{"Executive Officer": 0, "Director": 1, "Promoter": 2}.get(r, 3) for r in relations] or [3])
        is_signer = bool(signer) and (signer or "").lower() == name.lower() and bool(signer_title)
        role = signer_title if is_signer else _text(info, "relationshipClarification") or ", ".join(relations)
        filing.people.append(Person(name=name, role=role or "Officer", rank=rank))
    filing.people.sort(key=lambda p: p.rank)
    return filing


def parse_form_c(root: ET.Element, entry: IndexEntry, now: datetime) -> Filing:
    info = root.find("formData/issuerInformation/issuerInfo")
    offer = root.find("formData/offeringInformation")
    report = root.find("formData/annualReportDisclosureRequirements")
    incorporated = _date(_text(info, "legalStatus/dateIncorporation"))
    filing = Filing(
        form=_text(root, "headerData/submissionType") or entry.form,
        accession=entry.accession,
        cik=entry.cik,
        filed=entry.filed,
        name=_text(info, "nameOfIssuer") or entry.company,
        live=(_text(root, "headerData/filerInfo/liveTestFlag") or "LIVE").upper() == "LIVE",
        city=_text(info, "issuerAddress/city"),
        state=_text(info, "issuerAddress/stateOrCountry"),
        country=country_of(_text(info, "issuerAddress/stateOrCountry")),
        entity_type=_text(info, "legalStatus/legalStatusForm"),
        year_of_inc=incorporated.year if incorporated else None,
        over_five_years=bool(incorporated and (now.date() - incorporated).days > 5 * 365),
        offering_usd=_money(_text(offer, "offeringAmount")),
        max_offering_usd=_money(_text(offer, "maximumOfferingAmount")),
        deadline=_date(_text(offer, "deadlineDate")),
        security=_text(offer, "securityOfferedOtherDesc") or _text(offer, "securityOfferedType"),
        employees=_count(_text(report, "currentEmployees")),
        website=company_site(_text(info, "issuerWebsite")),
        portal=_text(root, "formData/issuerInformation/companyName"),
    )
    titles: dict[str, list[str]] = {}
    issuer_signer = _signature_name(_text(root, "formData/signatureInfo/issuerSignature/issuerSignature"))
    if issuer_signer:
        titles[issuer_signer] = [_text(root, "formData/signatureInfo/issuerSignature/issuerTitle") or "Officer"]
    for person in root.findall("formData/signatureInfo/signaturePersons/signaturePerson"):
        name = _signature_name(_text(person, "personSignature"))
        title = _text(person, "personTitle")
        if name and title and title not in titles.setdefault(name, []):
            titles[name].append(title)
    for name, roles in titles.items():
        filing.people.append(Person(name=name, role=", ".join(roles[:2]), rank=0))
    return filing


def parse_filing(text: str, entry: IndexEntry, now: datetime) -> Filing:
    """A Form D or Form C primary document. Raises ValueError on a document that is not one."""
    try:
        root = _xml(text)
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}") from exc
    if root.tag != "edgarSubmission":
        raise ValueError(f"not an EDGAR submission: {root.tag}")
    if root.find("formData") is not None:
        return parse_form_c(root, entry, now)
    if root.find("primaryIssuer") is not None:
        return parse_form_d(root, entry)
    raise ValueError("neither a Form D nor a Form C document")


def company_site(raw: str | None) -> str | None:
    """The company's own website from a Form C, or None for a portal page, a social profile or a non-site."""
    value = (raw or "").strip()
    if not value or " " in value:
        return None
    url = value if value.lower().startswith(("http://", "https://")) else f"https://{value}"
    dom = web_domain(url)
    if not dom or host_blocked(url) or dom.endswith(NOT_COMPANY_SITES):
        return None
    return f"https://{dom}"


def drop_reason(f: Filing, now: datetime, limits: tuple[int, float]) -> str | None:
    """Why a filing is not a startup lead, or None. Unknown values pass; qualification decides later."""
    if not f.live:
        return "test_filing"
    if f.fund:
        return "fund"
    if f.industry in BANKING:
        return "banking"
    if f.industry in REAL_ESTATE or f.tenant_in_common:
        return "real_estate"
    if f.mineral_property:
        return "mineral_property"
    if f.entity_type in PARTNERSHIPS:
        return "partnership"
    if f.business_combination:
        return "business_combination"
    if f.over_five_years:
        return "older_company"
    if f.first_sale and (now.date() - f.first_sale).days > MAX_SALE_AGE_DAYS:
        return "stale_offering"
    max_team, max_raise = limits
    gate = startup.startup_gate(
        team_size=f.employees,
        funding_round="crowdfunding" if f.crowdfunding else None,
        amount_usd=f.amount_usd,
        max_team=max_team,
        max_raise_usd=max_raise,
    )
    if not gate.ok:
        return gate.reason
    if f.sold_usd is not None and f.sold_usd > max_raise:
        return "raise_too_big"
    return None


def signal_details(f: Filing, url: str) -> dict[str, Any]:
    details: dict[str, Any] = {
        "form": f.form,
        "accession": f.accession,
        "cik": str(int(f.cik)),
        "filed": f.filed.isoformat(),
        "round": "crowdfunding" if f.crowdfunding else "unknown",
        "amount_usd": f.amount_usd,
        "amount_sold_usd": f.sold_usd,
        "offering": "indefinite" if f.offering_indefinite else None,
        "max_offering_usd": f.max_offering_usd,
        "first_sale": f.first_sale.isoformat() if f.first_sale else None,
        "deadline": f.deadline.isoformat() if f.deadline else None,
        "investor_count": f.investor_count,
        "industry": f.industry,
        "entity_type": f.entity_type,
        "year_of_inc": f.year_of_inc,
        "state": f.state,
        "security": f.security,
        "portal": f.portal,
    }
    if f.employees is not None:
        details["team_size"] = f.employees
        details["team_size_source"] = "filing"
    founders = startup.founders_detail(({"name": p.name, "role": p.role} for p in f.people), source_url=url)
    if founders:
        details["founders"] = founders
    return {k: v for k, v in details.items() if v is not None}


# ---------------------------------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------------------------------


class SecEdgarAdapter(SourceAdapter):
    name = NAME
    policy = "official_api"
    min_gap_s = GAP_S

    def __init__(self, ctx: SourceContext, *, user_agent: str, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(ctx, transport=transport)
        self.user_agent = user_agent
        self.blocked = False
        self.limits: tuple[int, float] = (startup.DEFAULT_MAX_TEAM, float(startup.DEFAULT_MAX_RAISE_USD))
        self.clock: Callable[[], datetime] = health.now_utc

    @property
    def http(self) -> PoliteClient:
        """SEC asks every client to name itself with a contact address (`settings.sec_user_agent`)."""
        if self._http is None:
            self._http = PoliteClient(
                self.name,
                policy=self.policy,
                min_gap_s=self.min_gap_s,
                max_bytes=INDEX_BYTES,
                transport=self._transport,
                user_agent=self.user_agent,
            )
        return self._http

    # ---- bookkeeping ---------------------------------------------------------------------------------------
    def filings_left(self) -> int:
        """Filing documents still allowed today (settings sec_edgar.filings_per_day, IST day)."""
        cap = health.setting_int(SETTING, DEFAULT_PER_DAY)
        used = db.scalar(
            "select count(*) from public.source_records where source = %s and source_key like 'filing:%%' "
            "and fetched_at >= %s and (payload->>'fetched')::boolean",
            [NAME, health.ist_day_start()],
        )
        return max(0, cap - int(used or 0))

    def record(self, rows: Sequence[tuple[str, dict[str, Any]]]) -> None:
        """Remember filings read and days done (`source_records`), so nothing is fetched twice."""
        if self.ctx.dry_run or not rows:
            return
        now = health.now_utc()
        db.upsert(
            "source_records",
            [{"source": NAME, "source_key": key, "payload": payload, "fetched_at": now} for key, payload in rows],
            conflict=["source", "source_key"],
            update=["payload", "fetched_at"],
        )

    @staticmethod
    def known(keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        """{source_key: payload} of the keys already in `source_records`."""
        wanted = list(dict.fromkeys(keys))
        if not wanted:
            return {}
        rows = db.fetch_all(
            "select source_key, payload from public.source_records where source = %s and source_key = any(%s)",
            [NAME, wanted],
        )
        return {r["source_key"]: r["payload"] or {} for r in rows}

    def offering_key(self, f: Filing) -> str:
        """One offering, one signal: an amendment belongs to the offering of the filing it amends. A Form C
        names no earlier filing, so a company's crowdfunding filings share one key."""
        if f.crowdfunding:
            return f"C-{int(f.cik)}"
        prev = (f.previous_accession or "").strip()
        if f.form == "D/A" and re.fullmatch(r"\d{10}-\d{2}-\d{6}", prev):
            earlier = self.known([f"filing:{prev}"]).get(f"filing:{prev}", {})
            return str(earlier.get("offering") or prev)
        return f.accession

    # ---- reading ------------------------------------------------------------------------------------------
    async def _get(self, url: str, max_bytes: int) -> Any:
        """The fetch result, or None after counting why (a transient failure is retried on a later run)."""
        res = await self.http.get(url, max_bytes=max_bytes, retries=1)
        if not res.ok:
            self.ctx.add(f"sec_edgar.http_{res.status or res.state}")
            return None
        return res

    async def open_days(self, now: datetime) -> list[date]:
        """Days of the window that have a daily index and are not done yet, newest first."""
        days = window(now)
        done = self.known(f"index:{d.isoformat()}" for d in days)
        todo = [d for d in days if not done.get(f"index:{d.isoformat()}", {}).get("done")]
        listed: dict[tuple[int, int], set[str]] = {}
        out: list[date] = []
        for day in todo:
            key = (day.year, quarter(day))
            if key not in listed:
                res = await self._get(DAILY_LISTING.format(year=key[0], quarter=key[1]), 2_000_000)
                try:
                    listed[key] = listed_indexes(res.json()) if res is not None else set()
                except ValueError:
                    self.ctx.add("sec_edgar.bad_listing")
                    listed[key] = set()
            if index_name(day) in listed[key]:
                out.append(day)
        return out

    async def read_index(self, day: date) -> tuple[list[IndexEntry], bool] | None:
        """(entries of the day, complete) or None when the index could not be read."""
        url = DAILY_INDEX.format(year=day.year, quarter=quarter(day), name=index_name(day))
        res = await self._get(url, INDEX_BYTES)
        if res is None:
            return None
        if res.truncated:
            self.ctx.add("sec_edgar.index_truncated")
        return parse_index(res.text), not res.truncated

    def plan(self, days: Mapping[date, list[IndexEntry]]) -> list[IndexEntry]:
        """Filings to fetch, best first. Filings read before and vehicles by name are skipped; one issuer's
        other filings in this run are remembered as `same_issuer` without a fetch."""
        entries = [e for day_entries in days.values() for e in day_entries]
        seen = self.known(e.key for e in entries)
        fresh: dict[str, IndexEntry] = {}
        for e in entries:
            if e.key in seen or e.key in fresh:
                continue
            if looks_like_vehicle(e.company):
                self.ctx.add("sec_edgar.vehicle_name")
                continue
            fresh[e.key] = e
        best: dict[tuple[str, bool], IndexEntry] = {}
        later: list[tuple[str, dict[str, Any]]] = []
        for e in sorted(fresh.values(), key=lambda x: (x.filed, x.accession), reverse=True):
            issuer = (e.cik, e.form.startswith("C"))
            if issuer in best:
                later.append((e.key, {"cik": e.cik, "form": e.form, "verdict": "same_issuer", "fetched": False}))
                self.ctx.add("sec_edgar.same_issuer")
                continue
            best[issuer] = e
        self.record(later)
        return sorted(best.values(), key=priority)

    async def process(
        self, e: IndexEntry, segments: Mapping[str, Segment], now: datetime
    ) -> tuple[Signal | None, bool]:
        """(the signal or None, whether the filing is settled). A filing is remembered whatever the verdict; a
        transient failure (a timeout, a server error) leaves it for a later run."""
        url = FILING_DOC.format(cik=int(e.cik), folder=e.folder)
        res = await self.http.get(url, max_bytes=DOC_BYTES, retries=1)
        payload: dict[str, Any] = {"cik": e.cik, "form": e.form, "name": e.company[:120], "fetched": True}
        if res.status == 404:
            self.record([(e.key, {**payload, "offering": e.accession, "verdict": "no_document"})])
            self.ctx.add("sec_edgar.no_document")
            return None, True
        if not res.ok:
            self.ctx.add(f"sec_edgar.http_{res.status or res.state}")
            return None, False
        try:
            filing = parse_filing(res.text, e, now)
        except ValueError as exc:
            log.info("sec_edgar.bad_document", accession=e.accession, error=str(exc)[:200])
            self.record([(e.key, {**payload, "offering": e.accession, "verdict": "bad_document"})])
            self.ctx.add("sec_edgar.bad_document")
            return None, True
        offering = self.offering_key(filing)
        sig, verdict = self.judge(filing, offering, segments, now)
        self.record([(e.key, {**payload, "name": filing.name[:120], "offering": offering, "verdict": verdict})])
        self.ctx.add(f"sec_edgar.{verdict}")
        return sig, True

    def judge(
        self, f: Filing, offering: str, segments: Mapping[str, Segment], now: datetime
    ) -> tuple[Signal | None, str]:
        """(the funding signal or None, the verdict) for one parsed filing."""
        reason = drop_reason(f, now, self.limits)
        if reason:
            return None, reason
        seg = startup.startup_segment(f.country, segments)
        if seg is None:
            return None, "country_unknown" if f.country is None else "country_not_enabled"
        url = FILING_PAGE.format(cik=int(f.cik), folder=f.accession.replace("-", ""), accession=f.accession)
        observed = datetime.combine(f.filed, time(12, 0), tzinfo=EASTERN).astimezone(UTC)
        sig = Signal(
            type="funding",
            source=NAME,
            observed_at=observed,
            url=url,
            quote=None,  # a form has no sentence to quote: its fields are in details
            evidence_key=f"sec:{offering}",
            business_hint={
                "name": f.name,
                "city": city_for_text(f.city or "", seg.cities),
                "website": f.website,
            },
            details=signal_details(f, url),
            segment_id=seg.id,
        )
        return sig, "signal"

    async def signals_for(self, segments: Mapping[str, Segment], *, limit: int | None = None) -> list[Signal]:
        """Funding signals from the open days of the window, at most the day's filing cap. A block stops the
        source but keeps what was found before it."""
        out: list[Signal] = []
        if not any(s.domain == "firms" for s in segments.values()):
            self.ctx.add("sec_edgar.no_startup_segment")
            return out
        left = self.filings_left()
        if limit:
            left = min(left, limit)
        if left <= 0:
            self.ctx.add("sec_edgar.daily_cap_reached")
            return out
        self.limits = startup.limits()
        now = self.clock()
        try:
            days: dict[date, list[IndexEntry]] = {}
            complete: set[date] = set()
            for day in await self.open_days(now):
                read = await self.read_index(day)
                if read is None:
                    continue
                days[day], whole = read
                if whole:
                    complete.add(day)
            todo = self.plan(days)
            self.ctx.add("sec_edgar.candidates", len(todo))
            settled: set[str] = set()
            for entry in todo[:left]:
                sig, ok = await self.process(entry, segments, now)
                if ok:
                    settled.add(entry.key)
                if sig is not None:
                    out.append(sig)
            self.mark_days(days, complete, {e.key for e in todo} - settled)
        except SourceBlocked as err:
            self.blocked = True
            self.health_blocked(err)
        return out

    def mark_days(self, days: Mapping[date, list[IndexEntry]], complete: set[date], waiting: set[str]) -> None:
        """A day read in full whose candidates are all settled (read, or skipped by rule) is not read again."""
        rows = [
            (f"index:{day.isoformat()}", {"done": True, "filings": len(entries)})
            for day, entries in days.items()
            if day in complete and not any(e.key in waiting for e in entries)
        ]
        self.record(rows)


async def watch(ctx: SourceContext, segments: dict[str, Segment], sink: Any) -> None:
    """Add this source's signals for the enabled segments to the sink."""
    user_agent = (get_settings().sec_user_agent or "").strip()
    if not user_agent:
        ctx.add("sec_edgar.no_user_agent")
        ctx.stats.setdefault("skip_reasons", {})[NAME] = "SEC_USER_AGENT is not set (a name and contact email)"
        return
    async with SecEdgarAdapter(ctx, user_agent=user_agent) as adapter:
        sigs = await adapter.signals_for(segments, limit=ctx.limit)
        if not adapter.blocked:
            adapter.health_ok()
    for sig in sigs:
        seg = segments.get(sig.segment_id or "")
        if seg is not None:
            sink.add(sig, seg)
