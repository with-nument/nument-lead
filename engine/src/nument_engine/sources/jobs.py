"""Job posts as signals: shared by Apna, Adzuna and JobPosting data found on business websites (Step 7.5.1).

A job post becomes `hiring_frontdesk` or `hiring_builder` only when the classifier (`classify_signal`) says a real
business in one of our domains is hiring for that role, with a quote that code finds again in the post.
Recruiter names and personal phone numbers are never kept: contact details are masked before the text is sent to
the AI or used as a quote.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import extruct
from dateutil import parser as dateparser

from ..normalize import EMAIL_RE, PHONE_RUN, city_for_text, clean_text, locality_for, web_domain
from ..segments import Segment
from .base import QUOTE_MAX, Signal, SourceContext, field_of

# SignalClassification.employer_domain to our segment domains (models.Domain).
DOMAIN_MAP: dict[str, str] = {
    "clinics": "clinics",
    "realestate": "realestate",
    "education": "education",
    "d2c": "d2c",
    "hospitality": "hospitality",
    "auto": "auto",
    "insurance_loans": "finance",
    "fitness_salon": "wellness",
    "firms_startups": "firms",
    "marketing_or_design_agency": "partners",  # white-label partners (13 Nov 2026), builder roles only
    "law_or_accounting": "professional",
}
MIN_CONFIDENCE = 0.6
DESCRIPTION_CHARS = 1500  # Step 7.5.1: the first 1,500 characters of the description

# Cheap words that show a post may belong to a domain. A post with none of them is not sent to the AI.
DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "clinics": (
        "clinic",
        "hospital",
        "dental",
        "dentist",
        "dermat",
        "skin",
        "hair",
        "ivf",
        "fertility",
        "physio",
        "patient",
        "doctor",
        "healthcare",
        "health care",
        "aesthetic",
        "cosmetic",
        "laser",
        "therapy",
        "medical",
    ),
    "realestate": (
        "real estate",
        "realty",
        "property",
        "properties",
        "builder",
        "developer",
        "construction",
        "site visit",
        "channel partner",
        "housing",
        "plots",
        "villa",
        "apartment",
        "projects",
    ),
    "education": (
        "school",
        "academy",
        "institute",
        "coaching",
        "classes",
        "education",
        "admission",
        "study abroad",
        "overseas",
        "ielts",
        "tuition",
        "college",
        "university",
        "students",
        "counsell",
    ),
    # 13 Nov 2026: the need-first, partner and professional tracks.
    "firms": (
        "developer",
        "engineer",
        "full stack",
        "app developer",
        "mobile app",
        "software",
        "automation",
        "ai ",
        "machine learning",
        "chatbot",
        "cto",
        "tech lead",
        "programmer",
        "shopify",
        "wordpress",
    ),
    "partners": (
        "marketing agency",
        "digital marketing",
        "advertising",
        "branding",
        "creative agency",
        "design studio",
        "design agency",
        "seo",
        "social media agency",
        "performance marketing",
    ),
    "professional": (
        "law firm",
        "lawyer",
        "attorney",
        "solicitor",
        "advocate",
        "legal",
        "accountant",
        "accounting",
        "chartered accountant",
        "cpa",
        "tax",
        "bookkeeping",
        "paralegal",
    ),
}


@dataclass
class JobPost:
    source: str
    job_id: str
    url: str
    title: str
    employer: str | None = None
    description: str = ""
    posted_at: datetime | None = None
    valid_through: datetime | None = None
    location_text: str = ""  # address, locality and region joined
    occupational_category: str | None = None
    industry: str | None = None
    salary: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        """What the classifier reads: title, employer, location and the start of the description."""
        parts = [self.title, self.employer or "", self.location_text, self.description[:DESCRIPTION_CHARS]]
        return mask_contacts("\n".join(p for p in parts if p))


def mask_contacts(text: str) -> str:
    """Hide phone numbers and email addresses (recruiters' details are never kept, A.4.3)."""
    return PHONE_RUN.sub("[phone]", EMAIL_RE.sub("[email]", text or ""))


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = dateparser.parse(str(value))
    except (ValueError, OverflowError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _types(item: Mapping[str, Any]) -> list[str]:
    t = item.get("@type")
    return [str(x) for x in t] if isinstance(t, list) else [str(t)] if t else []


def jsonld_items(html: str, url: str) -> list[dict[str, Any]]:
    """JSON-LD items of a page, with `@graph` containers flattened."""
    try:
        data = extruct.extract(html, base_url=url, syntaxes=["json-ld"], uniform=True)
    except Exception:  # extruct raises many parser errors on broken markup; a page without data is fine
        return []
    out: list[dict[str, Any]] = []
    for item in data.get("json-ld", []):
        if isinstance(item, dict) and isinstance(item.get("@graph"), list):
            out.extend(x for x in item["@graph"] if isinstance(x, dict))
        elif isinstance(item, dict):
            out.append(item)
    return out


def job_from_jsonld(item: Mapping[str, Any], *, source: str, job_id: str, url: str) -> JobPost:
    org = item.get("hiringOrganization") or {}
    employer = org.get("name") if isinstance(org, dict) else (org if isinstance(org, str) else None)
    location = item.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = (location.get("address") if isinstance(location, dict) else None) or {}
    if isinstance(address, str):
        location_text = address
    else:
        location_text = ", ".join(
            str(address.get(k))
            for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")
            if isinstance(address, dict) and address.get(k)
        )
    salary = item.get("baseSalary") if isinstance(item.get("baseSalary"), dict) else {}
    description = re.sub(r"<[^>]+>", " ", str(item.get("description") or ""))
    return JobPost(
        source=source,
        job_id=job_id,
        url=url,
        title=clean_text(str(item.get("title") or "")),
        employer=clean_text(str(employer)) if employer else None,
        description=clean_text(description),
        posted_at=parse_date(item.get("datePosted")),
        valid_through=parse_date(item.get("validThrough")),
        location_text=clean_text(location_text),
        occupational_category=item.get("occupationalCategory"),
        industry=item.get("industry"),
        salary=salary or {},
    )


def job_from_html(html: str, *, source: str, job_id: str, url: str) -> JobPost | None:
    """The first JobPosting on a page, or None."""
    for item in jsonld_items(html, url):
        if "JobPosting" in _types(item):
            return job_from_jsonld(item, source=source, job_id=job_id, url=url)
    return None


# ---------------------------------------------------------------------------------------------------
# Keyword rules (before any AI)
# ---------------------------------------------------------------------------------------------------


def _phrase_in(phrase: str, text: str) -> bool:
    words = [re.escape(w) for w in re.split(r"[\s_-]+", phrase.lower()) if w]
    return bool(words) and re.search(r"(?<![a-z0-9])" + r"[\s_-]+".join(words) + r"(?![a-z0-9])", text) is not None


def role_from_keywords(title: str, seg: Segment) -> str | None:
    """`frontdesk`, `builder` or None for a job title (or URL slug), using the segment's job keywords."""
    low = title.lower()
    if any(_phrase_in(k, low) for k in seg.job_keywords.exclude):
        return None
    if any(_phrase_in(k, low) for k in seg.job_keywords.builder):
        return "builder"
    if any(_phrase_in(k, low) for k in seg.job_keywords.frontdesk):
        return "frontdesk"
    return None


def has_domain_hint(text: str, domains: Iterable[str]) -> bool:
    low = text.lower()
    return any(h in low for d in domains for h in DOMAIN_HINTS.get(d, ()))


# ---------------------------------------------------------------------------------------------------
# Classification and the signal
# ---------------------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s@.+/:%₹$&]", " ", (text or "").lower())).strip()


def quote_in(quote: str | None, text: str) -> bool:
    """Code check that a quote really is in the text (whitespace and punctuation tolerant)."""
    q = _norm(quote or "")
    return len(q) >= 5 and q in _norm(text)


def pick_quote(candidate: str | None, post: JobPost) -> str:
    """The classifier's quote when code finds it in the post and it holds no contact details, else the title."""
    text = post.text()
    clean = bool(candidate) and not PHONE_RUN.search(candidate or "") and not EMAIL_RE.search(candidate or "")
    if candidate and clean and quote_in(candidate, text) and "[phone]" not in candidate and "[email]" not in candidate:
        return clean_text(candidate, QUOTE_MAX)
    return clean_text(post.title, QUOTE_MAX)


def classify_job(
    ctx: SourceContext,
    post: JobPost,
    segments: Mapping[str, Segment],
    *,
    country: str,
    default_segment: Segment,
) -> Signal | None:
    """Run `classify_signal` on a post and apply the rules of Step 7.5.1. Returns the signal, routed to the
    segment of the employer's domain, or None (with the reason counted in `ctx.stats`)."""
    inputs = {
        "segment_id": default_segment.id,
        "domain": default_segment.domain,
        "country": country,
        "source": post.source,
        "url": post.url,
        "posted_date": post.posted_at.date().isoformat() if post.posted_at else None,
        "title": post.title,
        "employer_name": post.employer,
        "employer": post.employer,
        "address": post.location_text,
        "mode": "job_post",
        "text": post.text(),
    }
    result = ctx.ai("classify_signal", inputs)
    if result is None:
        return None
    if not field_of(result, "is_relevant"):
        ctx.add("jobs.not_relevant")
        return None
    domain = str(field_of(result, "employer_domain") or "other")
    if domain == "agency_or_staffing":
        ctx.add("jobs.agency_dropped")
        return None
    role = field_of(result, "role_category")
    if role not in ("frontdesk", "builder"):
        ctx.add("jobs.other_role")
        return None
    if float(field_of(result, "confidence") or 0) < MIN_CONFIDENCE:
        ctx.add("jobs.low_confidence")
        return None
    if DOMAIN_MAP.get(domain) == "partners" and role != "builder":
        ctx.add("jobs.partner_not_builder")  # an agency hiring a receptionist is not a partner lead
        return None
    seg = segments.get(f"{DOMAIN_MAP.get(domain, domain)}-{country}")
    if seg is None and role == "builder" and DOMAIN_MAP.get(domain) != "partners":
        # A business hiring a developer is a need-first lead whatever its industry (13 Nov 2026).
        seg = segments.get(f"firms-{country}")
    if seg is None:
        ctx.add("jobs.domain_not_enabled")
        return None
    city = city_for_text(f"{post.url.replace('-', ' ')} {post.location_text}", seg.cities) or city_for_text(
        str(field_of(result, "city") or ""), seg.cities
    )
    website = field_of(result, "employer_website")
    if website and (web_domain(website) or "") not in post.text().lower():
        website = None  # a website the post does not show is a guess: never keep it
    localities = next((c.localities for c in seg.cities if c.name == city), [])
    observed = post.posted_at or datetime.now(UTC)
    details: dict[str, Any] = {"role": post.title, "role_category": role, "classifier_domain": domain}
    if post.valid_through:
        details["apply_by"] = post.valid_through.isoformat()
    if not post.posted_at:
        details["date_estimated"] = True
    if post.salary:
        details["salary"] = post.salary
    return Signal(
        type="hiring_frontdesk" if role == "frontdesk" else "hiring_builder",
        source=post.source,
        observed_at=observed,
        url=post.url,
        quote=pick_quote(field_of(result, "evidence_quote"), post),
        evidence_key=f"{post.source}:{post.job_id}",
        business_hint={
            "name": post.employer or field_of(result, "employer_name"),
            "city": city,
            "website": website,
            "address": post.location_text or None,
            "locality": locality_for(post.location_text, localities),
        },
        details=details,
        segment_id=seg.id,
    )
