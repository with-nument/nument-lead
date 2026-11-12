"""JSON-LD and microdata to code facts, without AI (Step 9.7, fact names from A.13.2).

Fields: `jsonld_phone`, `jsonld_email`, `jsonld_name`, `jsonld_price_range`, `jsonld_employees`, `jsonld_job`.
The quote is the compact JSON fragment the value came from. These are code facts (`model = 'rule'`), stored as
verified because code read them straight from the page (Step 10 does not re-check rule facts).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import extruct

from ..normalize import decode_email, phone

BUSINESS_TYPES = frozenset(
    {
        "LocalBusiness",
        "MedicalClinic",
        "MedicalBusiness",
        "MedicalOrganization",
        "Dentist",
        "Physician",
        "Hospital",
        "RealEstateAgent",
        "EducationalOrganization",
        "School",
        "CollegeOrUniversity",
        "Organization",
        "Corporation",
        "Hotel",
        "TravelAgency",
        "AutoDealer",
        "HealthAndBeautyBusiness",
        "BeautySalon",
        "DaySpa",
        "HealthClub",
        "ProfessionalService",
    }
)
BUSINESS_SUFFIXES = ("Business", "Clinic", "Organization", "Agent", "Store", "Dentist", "Physician", "School")


@dataclass
class CodeFact:
    """A fact produced by code (no AI). `value` is JSON-serialisable."""

    field: str
    value: Any
    quote: str
    url: str


def _types(item: dict[str, Any]) -> list[str]:
    t = item.get("@type")
    raw = t if isinstance(t, list) else [t] if t else []
    return [str(x).rsplit("/", 1)[-1] for x in raw]


def _is_business(types: list[str]) -> bool:
    return any(t in BUSINESS_TYPES or t.endswith(BUSINESS_SUFFIXES) for t in types)


def _fragment(key: str, value: Any) -> str:
    return json.dumps({key: value}, ensure_ascii=False, separators=(",", ":"))[:300]


def items(html: str, url: str) -> list[dict[str, Any]]:
    """Structured items (JSON-LD and microdata) with `@graph` containers flattened."""
    try:
        data = extruct.extract(html, base_url=url, syntaxes=["json-ld", "microdata"], uniform=True)
    except Exception:  # extruct raises many parser errors on broken markup; such a page has no usable data
        return []
    out: list[dict[str, Any]] = []
    for syntax in ("json-ld", "microdata"):
        for item in data.get(syntax, []):
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                out.extend(x for x in item["@graph"] if isinstance(x, dict))
            else:
                out.append(item)
    return out


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if value not in (None, "") else []


def facts_from_html(html: str, url: str, region: str) -> list[CodeFact]:
    """Code facts from one page's structured data. `region` (IN, AE, ...) parses phone numbers."""
    out: list[CodeFact] = []
    seen: set[tuple[str, str]] = set()

    def add(field: str, value: Any, quote: str) -> None:
        key = (field, json.dumps(value, sort_keys=True, default=str))
        if key not in seen:
            seen.add(key)
            out.append(CodeFact(field, value, quote, url))

    for item in items(html, url):
        types = _types(item)
        if "JobPosting" in types:
            org = item.get("hiringOrganization")
            org_name = org.get("name") if isinstance(org, dict) else org if isinstance(org, str) else None
            title = str(item.get("title") or "").strip()
            if title:
                value = {
                    "title": title[:200],
                    "date_posted": item.get("datePosted"),
                    "valid_through": item.get("validThrough"),
                    "hiring_organization": org_name,
                }
                add("jsonld_job", value, _fragment("title", title))
            continue
        if not _is_business(types):
            continue
        for raw in _as_list(item.get("telephone")):
            parsed = phone(str(raw), region)
            if parsed:
                add(
                    "jsonld_phone",
                    {"phone": str(raw), "e164": parsed[0], "kind": parsed[1]},
                    _fragment("telephone", raw),
                )
        for raw in _as_list(item.get("email")):
            email = decode_email(str(raw).removeprefix("mailto:"))
            if email:
                add("jsonld_email", {"email": email}, _fragment("email", raw))
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            add("jsonld_name", {"name": name.strip()[:200]}, _fragment("name", name.strip()))
        price = item.get("priceRange")
        if isinstance(price, str) and price.strip():
            add("jsonld_price_range", {"price_range": price.strip()[:100]}, _fragment("priceRange", price.strip()))
        employees = item.get("numberOfEmployees")
        count = employees.get("value") if isinstance(employees, dict) else employees
        try:
            n = int(float(str(count))) if count not in (None, "") else None
        except ValueError:
            n = None
        if n is not None and n >= 0:
            add("jsonld_employees", {"employees": n}, _fragment("numberOfEmployees", count))
    return out
