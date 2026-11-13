"""Verification (Step 10): prove every fact again with code, not AI, then decide who can be scored.

Order for one business (10.1): quotes, website status, suppression, competitor check, contacts, conflicts,
signal freshness, final status. Each business is planned in memory first (bulk reads; AI only for a
conflict the rules cannot settle or a single competitor hint) and the plan is then written in one
transaction per chunk. Planning only touches facts that were never verified, so running `nlead verify`
twice gives the same rows (10.9).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from psycopg import Connection
from rapidfuzz import fuzz

from .. import db
from ..logging import get_logger
from ..models import FlaggedVerification
from ..segments import Segment, load_segments, load_yaml_config
from ..settings import get_settings
from . import ai, evidence
from .evidence import CODE_MODELS, Row, fact_count, fact_flag, fact_text, on_domain, vget
from .phones import (
    deobfuscate_email,
    emails_in_text,
    is_freemail,
    mx_exists,
    parse_phone,
    phones_in_text,
    region_for,
    snippet,
    valid_email,
)
from .runs import RunContext

log = get_logger()
IST: Final = ZoneInfo("Asia/Kolkata")

QUOTE_MIN_LEN: Final = 8
QUOTE_THRESHOLD: Final = 92
SUSPICIOUS_SHARE: Final = 0.40  # more failed quotes than this: the page text was probably incomplete (10.2.4)
SUSPICIOUS_MIN_FACTS: Final = 3
DM_PROXIMITY_CHARS: Final = 120
CONTEXT_CHARS: Final = 1500  # page text sent to verify_flagged around each quote (10.7.2)
CHUNK: Final = 50
AI_FAILURES_BEFORE_OFF: Final = 3

# =========================================================================
# 10.2 Quote verification
# =========================================================================

_WS: Final = re.compile(r"\s+")
_KEEP: Final = re.compile(r"[^\w\s@.+/:%₹$&]", re.UNICODE)
_QUOTES: Final = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00b4": "'"})


def norm(text: str | None) -> str:
    """The same normalisation for quote and page text: NFKC, plain quotes, lowercase, one space."""
    t = unicodedata.normalize("NFKC", text or "").translate(_QUOTES).lower()
    t = _KEEP.sub(" ", t)
    return _WS.sub(" ", t).strip()


@dataclass(frozen=True)
class QuoteCheck:
    ok: bool
    score: int
    why: str  # exact, fuzzy, quote_too_short, quote_not_found, page_missing


def check_quote(quote: str | None, page_text: str | None) -> QuoteCheck:
    """Exact match on normalised text, else rapidfuzz partial_ratio >= 92 (10.2.3)."""
    q, p = norm(quote), norm(page_text)
    if len(q) < QUOTE_MIN_LEN:
        return QuoteCheck(False, 0, "quote_too_short")
    if q in p:
        return QuoteCheck(True, 100, "exact")
    score = int(fuzz.partial_ratio(q, p))
    if score >= QUOTE_THRESHOLD:
        return QuoteCheck(True, score, "fuzzy")
    return QuoteCheck(False, score, "quote_not_found")


# =========================================================================
# 10.4 Website status (ported from check_links_emails.py)
# =========================================================================

PARKED: Final = re.compile(
    r"domain (?:is|may be) for sale|buy this domain|this domain is parked|parked free|"
    r"sedoparking|hugedomains|dan\.com/buy|domain has expired|godaddy\.com/domainsearch|"
    r"account suspended|site not found|404 not found",
    re.I,
)
COMING_SOON: Final = re.compile(r"coming soon|under construction|launching soon", re.I)
_TRANSIENT: Final = re.compile(r"timed out|timeout|temporarily unavailable|connection reset|remote end closed", re.I)
_BOT_CHECK: Final = re.compile(r"cloudflare|captcha|access denied", re.I)


def website_status(http_status: int | None, text: str | None, error: str | None) -> str:
    """live, parked, coming_soon, dead, blocked or unknown (10.4.1). Never 'dead' on a timeout or a block."""
    if error and (_TRANSIENT.search(error) or "CERTIFICATE_VERIFY_FAILED" in error):
        return "unknown"  # TLS failures are often local interception, never proof of death
    if error:
        return "dead"
    if http_status in (401, 403, 429, 503) or _BOT_CHECK.search((text or "")[:5000]):
        return "blocked"
    if http_status is None or http_status >= 400:
        return "dead" if http_status in (404, 410) else "unknown"
    if PARKED.search(text or ""):
        return "parked"
    if COMING_SOON.search((text or "")[:20000]):
        return "coming_soon"
    return "live"


# =========================================================================
# 10.5 Competitors, chains and hospitals
# =========================================================================

COMPETITOR_PHRASES: Final = re.compile(
    r"\b(?:web development company|software development company|app development company|"
    r"digital marketing agency|it services|it solutions|we build websites|website design company|"
    r"staffing solutions|recruitment agency|outsourcing partner|white label)\b",
    re.I,
)
# Footer credits ("Designed and developed by XYZ IT Solutions") name the clinic's web vendor, not the clinic.
_CREDIT_LINE: Final = re.compile(
    r"designed\s*(?:&|and)?\s*(?:developed\s*)?by|developed by|powered by|website by|site by|made by|"
    r"maintained by|all rights reserved|©|copyright",
    re.I,
)
_SERVICE_COMPETITOR: Final = re.compile(
    r"\b(?:software|web\s?(?:site)?\s?(?:design|development)|app development|mobile apps?|seo|"
    r"digital marketing|social media marketing|it (?:services|solutions|consulting)|staffing|recruitment|"
    r"placement|outsourcing|crm|erp)\b",
    re.I,
)
AGENCY_FIELDS: Final = ("business_name", "is_agency_or_vendor", "service", "sales_note", "in_house_tech")
AGENCY_QUESTION: Final = (
    "Is this business an agency or software vendor that sells the same services as Nument "
    "(websites, apps, software, automation, marketing or hiring services)?"
)


@dataclass(frozen=True)
class Exclusions:
    """engine/config/exclusions.yaml in the one shape of Step 3.6 (A.13.5 rule 6)."""

    chains: tuple[tuple[str, tuple[str, ...]], ...]
    hospital_keywords: tuple[str, ...]
    agency_keywords: tuple[str, ...]
    competitors: tuple[str, ...]
    max_branches: int

    @classmethod
    def load(cls, data: Mapping[str, Any] | None = None) -> Exclusions:
        raw = dict(data if data is not None else load_yaml_config("exclusions"))
        chains = tuple(
            (str(c["name"]).lower(), tuple(str(d).lower() for d in c.get("domains") or ()))
            for c in raw.get("chains") or ()
        )
        return cls(
            chains=chains,
            hospital_keywords=tuple(str(k).lower() for k in raw.get("hospital_keywords") or ()),
            agency_keywords=tuple(str(k).lower() for k in raw.get("agency_keywords") or ()),
            competitors=tuple(str(k).lower() for k in raw.get("competitors") or ()),
            max_branches=int(raw.get("max_branches") or 10),
        )

    @staticmethod
    def _word_in(phrase: str, text: str) -> bool:
        return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None

    def chain_match(self, names: Iterable[str], web_domain: str | None) -> str | None:
        texts = [n.lower() for n in names if n]
        dom = (web_domain or "").lower()
        for name, domains in self.chains:
            if dom and dom in domains:
                return f"chain domain {dom}"
            if any(self._word_in(name, t) for t in texts):
                return f"chain name '{name}'"
        return None

    def hospital_match(self, names: Iterable[str]) -> str | None:
        texts = [n.lower() for n in names if n]
        for kw in self.hospital_keywords:
            if any(self._word_in(kw, t) for t in texts):
                return f"hospital keyword '{kw}'"
        return None

    def competitor_match(self, names: Iterable[str], web_domain: str | None) -> str | None:
        texts = [n.lower() for n in names if n]
        dom = (web_domain or "").lower()
        label = dom.split(".", 1)[0] if dom else ""
        for comp in self.competitors:
            if dom and (dom == comp if "." in comp else label == comp):
                return f"competitor domain {dom}"
            if any(self._word_in(comp, t) for t in texts):
                return f"competitor name '{comp}'"
        for kw in self.agency_keywords:
            if any(self._word_in(kw, t) for t in texts):
                return f"agency keyword '{kw}'"
        return None


# =========================================================================
# 10.3.7 Decision makers
# =========================================================================

DM_ROLE: Final = re.compile(
    r"\b(?:co-?founder|founder|owner|proprietor|director|managing director|md|ceo|principal|"
    r"medical director|chief|partner|head)\b",
    re.I,
)
_SOLE_OWNER: Final = re.compile(r"\b(?:founder|owner|proprietor)\b", re.I)
_CO_FOUNDER: Final = re.compile(r"\bco-?founder\b", re.I)
_HONORIFIC: Final = re.compile(r"^(?:dr|mr|mrs|ms|miss|prof|sri|shri|smt)\.?\s+", re.I)


def is_decision_maker_fact(fact: Mapping[str, Any]) -> bool:
    role = str(vget(fact.get("value"), "role") or "")
    if role:
        return DM_ROLE.search(role) is not None
    return vget(fact.get("value"), "is_decision_maker") is True


def is_sole_owner_claim(fact: Mapping[str, Any]) -> bool:
    """Founder, owner or proprietor (a co-founder shares the role, so two of them do not conflict)."""
    role = str(vget(fact.get("value"), "role") or "")
    return bool(role) and _SOLE_OWNER.search(role) is not None and _CO_FOUNDER.search(role) is None


def person_name(fact: Mapping[str, Any]) -> str:
    return str(vget(fact.get("value"), "name") or "").strip()


def bare_name(name: str) -> str:
    """'Dr. Anil Rao' -> 'Anil Rao'."""
    return _HONORIFIC.sub("", name.strip()).strip()


def same_person(a: str, b: str) -> bool:
    x, y = bare_name(a).lower(), bare_name(b).lower()
    return bool(x) and bool(y) and fuzz.token_set_ratio(x, y) >= 90


def name_positions(text: str, name: str) -> list[tuple[int, int]]:
    """Where a person's name appears in page text: the full name, or 'Dr. Surname'."""
    bare = bare_name(name)
    parts = [p for p in re.split(r"[\s.]+", bare) if p]
    if not parts:
        return []
    patterns = [r"[\s.]+".join(re.escape(p) for p in parts)]
    if len(parts) > 1:
        patterns.append(rf"\bdr\.?\s*{re.escape(parts[-1])}\b")
    spans: list[tuple[int, int]] = []
    for pat in patterns:
        spans += [(m.start(), m.end()) for m in re.finditer(pat, text, re.I)]
    return spans


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    if a[1] < b[0]:
        return b[0] - a[1]
    if b[1] < a[0]:
        return a[0] - b[1]
    return 0


def email_belongs_to(email: str, name: str) -> bool:
    """The contact is the person's own email when a name part (3+ letters) is in the local part."""
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].lower())
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in bare_name(name).split()]
    return any(len(p) >= 3 and p in local for p in parts)


# =========================================================================
# Inputs and outputs of planning
# =========================================================================

CODE_PHONE_FIELDS: Final = frozenset({"jsonld_phone", "phone", "tel_link", "whatsapp_link"})
CODE_EMAIL_FIELDS: Final = frozenset({"jsonld_email", "email", "mailto_link"})
PLACES_PHONE_KEYS: Final = (
    "internationalPhoneNumber",
    "nationalPhoneNumber",
    "international_phone_number",
    "formatted_phone_number",
    "phone",
)
REGISTRY_PHONE_KEYS: Final = ("phone", "phones", "telephone", "mobile", "contact_phone")
REGISTRY_EMAIL_KEYS: Final = ("email", "emails", "contact_email", "mail")
_JOB_CLOSED: Final = re.compile(
    r"no longer accepting applications|position (?:has been |is )?filled|job (?:is |has )?(?:closed|expired)|"
    r"applications? (?:are |is )?closed|vacancy (?:is )?closed",
    re.I,
)


@dataclass
class Bundle:
    """Everything stored about one business that verification reads."""

    business: Row
    pages: list[Row]
    facts: list[Row]
    signals: list[Row]
    contacts: list[Row]
    records: list[Row]  # source_records from Places and registries


@dataclass
class FactState:
    verified: bool
    score: float
    why: str
    url: str | None = None  # corrected citation (9.18), else unchanged
    page_id: str | None = None
    changed: bool = True


@dataclass
class ContactRow:
    business_id: str
    source: str
    verified: bool
    verified_at: datetime | None
    phone_e164: str | None = None
    phone_type: str = "unknown"
    email: str | None = None
    name: str | None = None
    role: str | None = None
    source_url: str | None = None
    quote: str | None = None
    is_decision_maker: bool = False
    do_not_contact: bool = False

    @property
    def usable(self) -> bool:
        return self.verified and not self.do_not_contact and bool(self.phone_e164 or self.email)


@dataclass
class Plan:
    business_id: str
    status: str | None = None
    reject_reason: str | None = None
    researched: bool = False
    fact_states: dict[str, FactState] = field(default_factory=dict)
    website_fact: Row | None = None
    contacts: list[ContactRow] = field(default_factory=list)
    expire_signals: list[str] = field(default_factory=list)
    branches_count: int | None = None
    staff_count: int | None = None
    rename: str | None = None  # the site's own name, when the listing name belongs to someone else
    extra_patch: dict[str, Any] = field(default_factory=dict)
    stats: Counter[str] = field(default_factory=Counter)


@dataclass
class VerifyDeps:
    """Things tests replace: the MX lookup (never DNS in unit tests) and the clock."""

    mx: Callable[[str], bool | None] = mx_exists
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


class FlagAsker:
    """`verify_flagged` calls for one run. Off in dry runs, when the router cannot start, after a budget
    stop, or after a few failures in a row, so one bad provider cannot slow a whole morning down."""

    def __init__(self, router: ai.AIRouter | None, run_id: str | None, enabled: bool = True) -> None:
        self.router, self.run_id = router, run_id
        self.enabled = enabled and router is not None
        self.failures = 0
        self.stats: Counter[str] = Counter()

    def ask(self, inputs: dict[str, Any]) -> FlaggedVerification | None:
        if not self.enabled or self.router is None:
            self.stats["verify_flagged.skipped"] += 1
            return None
        try:
            res = ai.call(self.router, "verify_flagged", inputs, FlaggedVerification, run_id=self.run_id)
        except ai.AIBudgetStop:
            self.enabled = False
            self.stats["verify_flagged.budget_stop"] += 1
            return None
        except ai.AIUnavailable:
            self.failures += 1
            self.stats["verify_flagged.unavailable"] += 1
            if self.failures >= AI_FAILURES_BEFORE_OFF:
                self.enabled = False
            return None
        self.failures = 0
        self.stats["verify_flagged.calls"] += 1
        return res.output


# =========================================================================
# Planning: pure functions over a Bundle (no writes)
# =========================================================================


def _page_index(pages: Sequence[Row]) -> tuple[dict[str, Row], dict[str, Row]]:
    by_id = {str(p["id"]): p for p in pages}
    by_url = {evidence.canonical_url(p["url"]): p for p in pages}
    return by_id, by_url


def _cited_page(fact: Mapping[str, Any], by_id: Mapping[str, Row], by_url: Mapping[str, Row]) -> Row | None:
    if fact.get("page_id") and str(fact["page_id"]) in by_id:
        return by_id[str(fact["page_id"])]
    return by_url.get(evidence.canonical_url(fact.get("url")))


def _value_on_pages(fact: Mapping[str, Any], pages: Sequence[Row], region: str) -> Row | None:
    """For phone and email facts whose quote is just the number or address (10.2.3 exception)."""
    if fact["field"] == "phone":
        parsed = parse_phone(str(vget(fact.get("value"), "number", "phone", "value") or ""), region)
        if parsed is None:
            return None
        for p in pages:
            if any(h.e164 == parsed[0] for h in phones_in_text(p.get("text") or "", region)):
                return p
        return None
    email = deobfuscate_email(str(vget(fact.get("value"), "email", "value") or ""))
    if not valid_email(email):
        return None
    for p in pages:
        if email in emails_in_text(p.get("text") or ""):
            return p
    return None


def verify_quotes(bundle: Bundle, region: str) -> dict[str, FactState]:
    """10.2 for every fact never verified before. Code-made facts are trusted; AI facts must quote a page."""
    by_id, by_url = _page_index(bundle.pages)
    text_pages = [p for p in bundle.pages if p.get("text")]
    states: dict[str, FactState] = {}
    for f in bundle.facts:
        if f.get("verified_at") is not None or f["field"] == "website_status":
            continue
        fid = str(f["id"])
        if (f.get("model") or "") in CODE_MODELS:
            states[fid] = FactState(True, 100, "code")
            continue
        cited = _cited_page(f, by_id, by_url)
        if f["field"] in ("phone", "email") and len(norm(f.get("quote"))) < QUOTE_MIN_LEN:
            page = _value_on_pages(f, ([cited] if cited else []) + text_pages, region)
            if page is not None:
                states[fid] = FactState(True, 100, "value_on_page", page["url"], str(page["id"]))
            else:
                states[fid] = FactState(False, 0, "quote_too_short")
            continue
        result = check_quote(f.get("quote"), cited.get("text")) if cited and cited.get("text") else None
        if result is not None and result.ok:
            states[fid] = FactState(True, result.score, result.why)
            continue
        # 9.18: the model sometimes cites the home page for a line on the contact page.
        moved = None
        for p in text_pages:
            if cited is not None and p["id"] == cited["id"]:
                continue
            other = check_quote(f.get("quote"), p["text"])
            if other.ok:
                moved = FactState(True, other.score, f"{other.why}_other_page", p["url"], str(p["id"]))
                break
        if moved is not None:
            states[fid] = moved
        elif result is not None:
            states[fid] = FactState(False, result.score, result.why)
        else:
            states[fid] = FactState(False, 0, "page_missing")
    return states


def current_verified(bundle: Bundle, states: Mapping[str, FactState]) -> list[Row]:
    """Facts that count as verified right now: earlier verdicts plus this pass's states."""
    out: list[Row] = []
    for f in bundle.facts:
        st = states.get(str(f["id"]))
        if st is not None:
            if st.verified and st.score >= 0:
                out.append({**f, "url": st.url or f.get("url"), "page_id": st.page_id or f.get("page_id")})
        elif f.get("verified") and float(f.get("verify_score") or 0) >= 0 and f["field"] != "website_status":
            out.append(f)
    return out


def home_page(bundle: Bundle) -> Row | None:
    b = bundle.business
    own = [p for p in bundle.pages if on_domain(p["url"], b.get("web_domain"))]
    if not own:
        return None
    site = evidence.canonical_url(b.get("website"))
    for p in own:
        if site and evidence.canonical_url(p["url"]) == site:
            return p
    return min(own, key=lambda p: (len(evidence.canonical_url(p["url"])), str(p["url"])))


def plan_website(bundle: Bundle, now: datetime) -> tuple[str | None, Row | None]:
    """(status, the website_status fact to store) or (None, None) when the business has no website."""
    b = bundle.business
    if not b.get("website") and not b.get("web_domain"):
        return None, None
    page = home_page(bundle)
    previous = next((f for f in bundle.facts if f["field"] == "website_status"), None)
    if page is None:
        status, quote, url, page_id = "unknown", "home page not fetched", b.get("website"), None
    elif page.get("robots_allowed") is False:
        status, quote, url, page_id = "unknown", "robots.txt disallows our crawler", page["url"], page["id"]
    else:
        http_status = page.get("http_status")
        text = page.get("text") or ""
        status = website_status(http_status, text, None)
        matched = PARKED.search(text) if status == "parked" else None
        quote = matched.group(0) if matched else f"HTTP {http_status}" if http_status else "no response"
        url, page_id = page["url"], page["id"]
    today = now.astimezone(IST).date().isoformat()
    prev_value = (previous or {}).get("value") or {}
    dead_days: list[str] = []
    if status == "dead":
        if prev_value.get("status") == "dead":
            dead_days = [d for d in prev_value.get("dead_days") or [] if isinstance(d, str)]
        dead_days = sorted({*dead_days, today})
    fact = {
        "business_id": str(b["id"]),
        "value": {"status": status, "dead_days": dead_days},
        "quote": quote[:200],
        "url": url,
        "page_id": str(page_id) if page_id else None,
    }
    return status, fact


def _competitor_phrase(text: str) -> str | None:
    """The first competitor phrase on a page, ignoring footer credits for the site's own web vendor."""
    for line in text.splitlines():
        if _CREDIT_LINE.search(line):
            continue
        m = COMPETITOR_PHRASES.search(line)
        if m:
            return m.group(0).lower()
    return None


def competitor_hints(bundle: Bundle, verified: Sequence[Row], excl: Exclusions) -> list[str]:
    """The four signs of a competitor (10.5.2). One is a question for the AI, two reject."""
    b = bundle.business
    hints: list[str] = []
    agency_facts = [f for f in evidence.by_field(verified, "is_agency_or_vendor") if fact_flag(f) is True]
    if agency_facts:
        hints.append(f"is_agency_or_vendor fact {evidence.short_id(agency_facts[0]['id'])}")
    for p in bundle.pages:
        hit = _competitor_phrase(p.get("text") or "") if on_domain(p["url"], b.get("web_domain")) else None
        if hit:
            hints.append(f"own site says '{hit}'")
            break
    names = [
        str(b.get("name") or ""),
        *(
            str(vget(f.get("value"), "name", "value") or "")
            for f in evidence.by_field(verified, "business_name", "jsonld_name")
        ),
    ]
    listed = excl.competitor_match(names, b.get("web_domain"))
    if listed:
        hints.append(listed)
    services = [fact_text(f) for f in evidence.by_field(verified, "service")]
    selling = [s for s in services if _SERVICE_COMPETITOR.search(s)]
    if len(selling) >= 2 and len(selling) * 2 >= len(services):
        hints.append(f"{len(selling)} of {len(services)} services are software, marketing or hiring")
    return hints


def chain_or_hospital(bundle: Bundle, verified: Sequence[Row], excl: Exclusions) -> str | None:
    b = bundle.business
    names = [
        str(b.get("name") or ""),
        *(
            str(vget(f.get("value"), "name", "value") or "")
            for f in evidence.by_field(verified, "business_name", "jsonld_name")
        ),
    ]
    if excl.chain_match(names, b.get("web_domain")):
        return "big_chain"
    branches = [c for c in (fact_count(f) for f in evidence.by_field(verified, "branches")) if c is not None]
    if branches and max(branches) >= excl.max_branches:
        return "big_chain"
    if excl.hospital_match(names):
        return "hospital"
    return None


def _context(text: str, quote: str, width: int = CONTEXT_CHARS) -> str:
    """Up to `width` characters of page text around a quote (10.7.2)."""
    if not text:
        return ""
    low, q = text.lower(), (quote or "").strip().lower()
    at = low.find(q[:60]) if q else -1
    if at < 0:
        return text[:width]
    start = max(0, at - (width - len(q)) // 2)
    return text[start : start + width]


def _fact_payload(f: Mapping[str, Any], by_id: Mapping[str, Row], by_url: Mapping[str, Row]) -> dict[str, Any]:
    page = _cited_page(f, by_id, by_url)
    return {
        "id": str(f["id"]),
        "field": f["field"],
        "value": f.get("value"),
        "quote": f.get("quote") or "",
        "url": f.get("url") or "",
        "context": _context((page or {}).get("text") or "", f.get("quote") or ""),
    }


# ---- 10.3 contacts ---------------------------------------------------------


@dataclass
class _OwnNumber:
    e164: str
    phone_type: str
    page: Row | None
    quote: str
    seen_at: datetime | None


def _seen_at(page: Mapping[str, Any] | None, fallback: datetime | None) -> datetime | None:
    return (page or {}).get("fetched_at") or fallback


def _record_values(payload: Mapping[str, Any], keys: Sequence[str]) -> list[str]:
    out: list[str] = []
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, list):
            out += [str(x).strip() for x in v if isinstance(x, str | int) and str(x).strip()]
    return out


def plan_contacts(
    bundle: Bundle,
    verified: Sequence[Row],
    seg: Segment,
    suppressed: Suppression,
    deps: VerifyDeps,
    now: datetime,
    stats: Counter[str],
) -> list[ContactRow]:
    """10.3: phones and emails the business published itself, typed, suppressed and linked to the owner."""
    b = bundle.business
    bid = str(b["id"])
    region = region_for(str(b.get("country") or seg.country))
    by_id, by_url = _page_index(bundle.pages)
    own_pages = [p for p in bundle.pages if on_domain(p["url"], b.get("web_domain")) and p.get("text")]
    dms = [f for f in evidence.by_field(verified, "decision_maker") if is_decision_maker_fact(f) and person_name(f)]

    # Every number printed on their own pages, first sighting kept (10.3.3).
    on_pages: dict[str, _OwnNumber] = {}
    for p in own_pages:
        for hit in phones_in_text(p["text"], region):
            on_pages.setdefault(
                hit.e164,
                _OwnNumber(hit.e164, hit.phone_type, p, snippet(p["text"], hit.start, hit.end), _seen_at(p, None)),
            )
    # Numbers code read from their HTML: tel: and WhatsApp links, JSON-LD telephone.
    from_code: dict[str, _OwnNumber] = {}
    for f in verified:
        if (
            f["field"] in CODE_PHONE_FIELDS
            and (f.get("model") or "") in CODE_MODELS
            and on_domain(f.get("url"), b.get("web_domain"))
        ):
            raw = str(vget(f.get("value"), "number", "telephone", "phone", "value") or "")
            parsed = parse_phone(raw, region)
            if parsed:
                page = _cited_page(f, by_id, by_url)
                from_code.setdefault(
                    parsed[0],
                    _OwnNumber(
                        parsed[0],
                        parsed[1],
                        page,
                        str(f.get("quote") or raw)[:200],
                        _seen_at(page, f.get("created_at")),
                    ),
                )

    rows: dict[str, ContactRow] = {}

    def add_phone(num: _OwnNumber, source: str, url: str | None, label: str | None = None) -> None:
        if num.e164 in rows:
            return
        rows[num.e164] = ContactRow(
            business_id=bid,
            source=source,
            verified=True,
            verified_at=num.seen_at,
            phone_e164=num.e164,
            phone_type=num.phone_type,
            role=(label or None) and str(label)[:60],
            source_url=url,
            quote=num.quote,
        )

    for f in evidence.by_field(verified, "phone"):
        if (f.get("model") or "") in CODE_MODELS:
            continue
        parsed = parse_phone(str(vget(f.get("value"), "number", "phone", "value") or ""), region)
        if parsed is None:
            stats["phones.invalid"] += 1
            continue
        found = on_pages.get(parsed[0]) or from_code.get(parsed[0])
        if found is None:
            stats["phones.not_on_own_page"] += 1  # a widget's number or another business's
            continue
        label = vget(f.get("value"), "label")
        add_phone(found, "website", (found.page or {}).get("url") or f.get("url"), label)
    for num in from_code.values():
        add_phone(num, "website", (num.page or {}).get("url"), None)

    # Registry entries (for example the ART registry) are published by the business through the regulator.
    registry_keys = {r.key for r in seg.registries} | {"art_registry"}
    for rec in bundle.records:
        if rec["source"] not in registry_keys:
            continue
        payload = rec.get("payload") or {}
        for raw in _record_values(payload, REGISTRY_PHONE_KEYS):
            parsed = parse_phone(raw, region)
            if parsed and parsed[0] not in rows:
                rows[parsed[0]] = ContactRow(
                    business_id=bid,
                    source="registry",
                    verified=True,
                    verified_at=rec.get("fetched_at"),
                    phone_e164=parsed[0],
                    phone_type=parsed[1],
                    source_url=payload.get("url") or None,
                    quote=raw[:200],
                )

    # Google listing, only when their own site gave no number, and only fresh Places data (10.3.4).
    if not any(r.source == "website" for r in rows.values()):
        for rec in bundle.records:
            if rec["source"] != "places":
                continue
            fetched = b.get("places_fetched_at") or rec.get("fetched_at")
            if fetched is None or now - fetched > evidence.GOOGLE_LISTING_MAX_AGE:
                stats["phones.listing_too_old"] += 1
                continue
            for raw in _record_values(rec.get("payload") or {}, PLACES_PHONE_KEYS):
                parsed = parse_phone(raw, region)
                if parsed and parsed[0] not in rows:
                    place = b.get("place_id")
                    rows[parsed[0]] = ContactRow(
                        business_id=bid,
                        source="google_listing",
                        verified=True,
                        verified_at=fetched,
                        phone_e164=parsed[0],
                        phone_type=parsed[1],
                        quote=None,
                        source_url=f"https://www.google.com/maps/place/?q=place_id:{place}" if place else None,
                    )
                    break

    # Emails (10.3.5): verified facts and code facts on their own pages, plus registry emails.
    emails: dict[str, ContactRow] = {}

    def add_email(raw: str, source: str, url: str | None, quote: str | None, seen: datetime | None) -> None:
        email = deobfuscate_email(raw)
        if not valid_email(email) or email in emails:
            return
        has_mx = deps.mx(email.rsplit("@", 1)[1])
        if has_mx is False:
            stats["emails.no_mx"] += 1
            return
        emails[email] = ContactRow(
            business_id=bid,
            source=source,
            verified=True,
            verified_at=seen,
            email=email,
            role="free mail" if is_freemail(email) else None,
            source_url=url,
            quote=(quote or email)[:200],
        )

    own_text = {str(p["id"]): (p.get("text") or "").lower() for p in own_pages}
    for f in evidence.by_field(verified, *CODE_EMAIL_FIELDS):
        if not on_domain(f.get("url"), b.get("web_domain")):
            continue
        raw = str(vget(f.get("value"), "email", "value") or "")
        page = _cited_page(f, by_id, by_url)
        code_made = (f.get("model") or "") in CODE_MODELS
        printed = page is not None and deobfuscate_email(raw) in emails_in_text(own_text.get(str(page["id"]), ""))
        if code_made or printed or deobfuscate_email(raw) in (f.get("quote") or "").lower():
            add_email(raw, "website", f.get("url"), f.get("quote"), _seen_at(page, f.get("created_at")))
    for rec in bundle.records:
        if rec["source"] in registry_keys:
            payload = rec.get("payload") or {}
            for raw in _record_values(payload, REGISTRY_EMAIL_KEYS):
                add_email(raw, "registry", payload.get("url") or None, raw, rec.get("fetched_at"))

    # Decision makers (10.3.7): a number printed next to the person's name, or their own email.
    out = list(rows.values()) + list(emails.values())
    dm_with_contact: set[str] = set()
    for c in out:
        for dm in dms:
            name = person_name(dm)
            role = str(vget(dm.get("value"), "role") or "") or None
            mine = False
            if c.phone_e164 and c.source == "website":
                for p in own_pages:
                    spans = name_positions(p["text"], name)
                    if not spans:
                        continue
                    for hit in phones_in_text(p["text"], region):
                        if hit.e164 == c.phone_e164 and any(
                            _gap(s, (hit.start, hit.end)) <= DM_PROXIMITY_CHARS for s in spans
                        ):
                            mine = True
                            break
                    if mine:
                        break
            elif c.email and email_belongs_to(c.email, name):
                mine = True
            if mine:
                note = " (free mail)" if c.email and is_freemail(c.email) else ""
                c.is_decision_maker, c.name, c.role = True, name, (role or "Owner") + note
                dm_with_contact.add(str(dm["id"]))
                break
    for dm in dms:
        if str(dm["id"]) in dm_with_contact:
            continue
        name = person_name(dm)
        if any(c.name and same_person(c.name, name) for c in out):
            continue
        page = _cited_page(dm, by_id, by_url)
        out.append(
            ContactRow(
                business_id=bid,
                source="website",
                verified=True,
                verified_at=_seen_at(page, dm.get("created_at")),
                name=name,
                role=str(vget(dm.get("value"), "role") or "") or None,
                is_decision_maker=True,
                source_url=dm.get("url"),
                quote=(dm.get("quote") or "")[:200],
            )
        )

    # Suppression (10.3.6): keep the row so the app can explain, never use it for reach.
    for c in out:
        if (c.phone_e164 and c.phone_e164 in suppressed.phones) or (c.email and c.email in suppressed.emails):
            c.do_not_contact = True
            stats["contacts.suppressed"] += 1
    # A person who marked a contact "do not contact" in the app keeps it that way.
    for existing in bundle.contacts:
        if existing.get("do_not_contact"):
            for c in out:
                if (c.phone_e164 and c.phone_e164 == existing.get("phone_e164")) or (
                    c.email and existing.get("email") and c.email == str(existing["email"]).lower()
                ):
                    c.do_not_contact = True
    return out


def usable_contact_exists(
    contacts: Iterable[ContactRow], existing: Iterable[Row], verified: Sequence[Row], now: datetime
) -> bool:
    """A phone, an email or a verified contact form we are allowed to use (10.8)."""
    if any(c.usable and (c.source != "google_listing" or _fresh_listing(c.verified_at, now)) for c in contacts):
        return True
    for c in existing:
        reachable = c.get("verified") and not c.get("do_not_contact") and (c.get("phone_e164") or c.get("email"))
        if reachable and (c.get("source") != "google_listing" or _fresh_listing(c.get("verified_at"), now)):
            return True
    return bool(evidence.by_field(verified, "contact_form_url"))


def _fresh_listing(seen: datetime | None, now: datetime) -> bool:
    return seen is not None and now - seen <= evidence.GOOGLE_LISTING_MAX_AGE


# ---- 10.7 conflicts ----------------------------------------------------------

_SPECIFIC_PATH: Final[dict[str, tuple[str, ...]]] = {
    "decision_maker": ("team", "doctor", "founder", "leadership", "management", "about", "people", "faculty"),
    "staff_or_doctors": ("team", "doctor", "specialist", "faculty", "people", "expert"),
    "branches": ("location", "branch", "centre", "center", "clinic", "office", "campus", "contact"),
    "in_house_tech": ("career", "job", "team", "about"),
}


@dataclass
class Conflict:
    field: str
    facts: list[Row]

    def disagrees(self, a: Row, b: Row) -> bool:
        if self.field == "decision_maker":
            return not same_person(person_name(a), person_name(b))
        if self.field == "in_house_tech":
            return fact_flag(a) is not fact_flag(b)
        x, y = fact_count(a), fact_count(b)
        if x is None or y is None:
            return False
        if self.field == "branches":
            return abs(x - y) > 1
        return abs(x - y) > 0.30 * max(x, y)


def find_conflicts(verified: Sequence[Row]) -> list[Conflict]:
    """10.7.1. is_agency_or_vendor disagreements are settled by the competitor question instead."""
    out: list[Conflict] = []
    owners = [f for f in evidence.by_field(verified, "decision_maker") if is_sole_owner_claim(f)]
    people: list[str] = []
    for f in owners:
        if not any(same_person(person_name(f), p) for p in people):
            people.append(person_name(f))
    if len(people) >= 2:
        out.append(Conflict("decision_maker", owners))
    for name in ("branches", "staff_or_doctors"):
        facts = [f for f in evidence.by_field(verified, name) if fact_count(f) is not None]
        c = Conflict(name, facts)
        if any(c.disagrees(a, b) for i, a in enumerate(facts) for b in facts[i + 1 :]):
            out.append(c)
    flags = [f for f in evidence.by_field(verified, "in_house_tech") if fact_flag(f) is not None]
    if {fact_flag(f) for f in flags} == {True, False}:
        out.append(Conflict("in_house_tech", flags))
    return out


def _specificity(field_name: str, page: Mapping[str, Any] | None) -> int:
    if page is None:
        return 0
    path = evidence.canonical_url(page.get("url")).split("/", 1)
    rest = path[1] if len(path) > 1 else ""
    if not rest:
        return 0  # home page: the least specific
    return 2 if any(k in rest for k in _SPECIFIC_PATH.get(field_name, ())) else 1


def resolve_by_rule(conflict: Conflict, by_id: Mapping[str, Row], by_url: Mapping[str, Row]) -> str | None:
    """The more specific page wins, then a page fetched more than a day later; otherwise undecided."""
    ranked = sorted(
        ((_specificity(conflict.field, _cited_page(f, by_id, by_url)), f) for f in conflict.facts),
        key=lambda t: -t[0],
    )
    top = [f for s, f in ranked if s == ranked[0][0]]
    if len(top) == 1 or not any(conflict.disagrees(top[0], f) for f in top[1:]):
        return str(top[0]["id"])
    dated: list[tuple[datetime, Row]] = []
    for f in top:
        fetched = (_cited_page(f, by_id, by_url) or {}).get("fetched_at")
        if not isinstance(fetched, datetime):
            return None
        dated.append((fetched, f))
    dated.sort(key=lambda t: t[0])
    if dated[-1][0] - dated[-2][0] > timedelta(days=1):
        return str(dated[-1][1]["id"])
    return None


def losers_for(conflict: Conflict, winner_id: str | None) -> list[str]:
    """Facts that disagree with the winner, or every fact of the conflict when none can be trusted."""
    if winner_id is None:
        return [str(f["id"]) for f in conflict.facts]
    winner = next((f for f in conflict.facts if str(f["id"]) == winner_id), None)
    if winner is None:
        return [str(f["id"]) for f in conflict.facts]
    return [str(f["id"]) for f in conflict.facts if str(f["id"]) != winner_id and conflict.disagrees(winner, f)]


def fallback_winner(conflict: Conflict) -> str | None:
    """No AI answer: the lower count wins (never overstate can-pay); people and flags stay unknown."""
    if conflict.field in ("branches", "staff_or_doctors"):
        return str(min(conflict.facts, key=lambda f: fact_count(f) or 0)["id"])
    return None


# ---- 10.6 freshness ------------------------------------------------------------


def signals_to_expire(bundle: Bundle, now: datetime) -> list[str]:
    """Hiring signals whose job closed: a past apply-by date, a closed flag, or a stored page saying so."""
    today = now.astimezone(IST).date()
    page_text = {evidence.canonical_url(p["url"]): p.get("text") or "" for p in bundle.pages}
    out: list[str] = []
    for s in bundle.signals:
        if not s["type"].startswith("hiring_") or not evidence.is_active(s, now):
            continue
        details = s.get("details") or {}
        apply_by = _as_date(details.get("apply_by"))
        if (apply_by is not None and apply_by < today) or details.get("closed") is True:
            out.append(str(s["id"]))
            continue
        text = page_text.get(evidence.canonical_url(s.get("url")))
        if text and _JOB_CLOSED.search(text):
            out.append(str(s["id"]))
    return out


def _as_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


# ---- the whole business ----------------------------------------------------------


@dataclass(frozen=True)
class Suppression:
    phones: frozenset[str]
    emails: frozenset[str]
    domains: frozenset[str]

    @classmethod
    def load(cls, conn: Connection[Any] | None = None) -> Suppression:
        rows = db.fetch_all("select phone_e164, email, web_domain from public.suppression", conn=conn)
        return cls(
            phones=frozenset(r["phone_e164"] for r in rows if r["phone_e164"]),
            emails=frozenset(str(r["email"]).lower() for r in rows if r["email"]),
            domains=frozenset(str(r["web_domain"]).lower() for r in rows if r["web_domain"]),
        )


# Words every business in a field shares: they say nothing about which business a name means.
GENERIC_NAME_WORDS: Final = frozenset(
    [
        "the",
        "and",
        "of",
        "a",
        "an",
        "&",
        "dr",
        "doctor",
        "doctors",
        "pvt",
        "private",
        "ltd",
        "limited",
        "llp",
        "inc",
        "co",
        "company",
        "group",
        "india",
        "clinic",
        "clinics",
        "dental",
        "dentist",
        "dentists",
        "dentistry",
        "dent",
        "skin",
        "hair",
        "derma",
        "dermatology",
        "dermatologist",
        "cosmetic",
        "aesthetic",
        "aesthetics",
        "laser",
        "care",
        "cure",
        "centre",
        "center",
        "centres",
        "centers",
        "hospital",
        "hospitals",
        "health",
        "healthcare",
        "medical",
        "multispeciality",
        "multispecialty",
        "speciality",
        "specialty",
        "super",
        "ivf",
        "fertility",
        "test",
        "tube",
        "baby",
        "physio",
        "physiotherapy",
        "therapy",
        "wellness",
        "academy",
        "institute",
        "institution",
        "classes",
        "class",
        "coaching",
        "tuition",
        "tuitions",
        "tutorial",
        "tutorials",
        "english",
        "speaking",
        "spoken",
        "school",
        "schools",
        "education",
        "educational",
        "learning",
        "studies",
        "study",
        "abroad",
        "overseas",
        "consultant",
        "consultants",
        "consultancy",
        "training",
    ]
)


def distinctive_words(name: str | None) -> list[str]:
    words = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", str(name or "")).lower())
    return [w for w in words if w not in GENERIC_NAME_WORDS and len(w) > 1]


def names_match(
    listing: str | None, site: str | None, web_domain: str | None = None, places: Iterable[str] = ()
) -> bool:
    """Do the listing's name and the site's own name mean the same business?

    Only distinctive words count (not "clinic", "dental", "english speaking" or the city), so "Ipromise English
    Speaking" and "BM English Speaking" do not match, while "Cosmodentindia" and "Cosmodent India" do. A name
    with no distinctive word left cannot be judged and counts as a match.
    """
    skip = {w for p in places for w in distinctive_words(p)}
    a = [w for w in distinctive_words(listing) if w not in skip]
    b = [w for w in distinctive_words(site) if w not in skip]
    if not a or not b:
        return True
    ja, jb = "".join(a), "".join(b)
    if ja in jb or jb in ja or fuzz.token_set_ratio(" ".join(a), " ".join(b)) >= 80:
        return True
    domain = re.sub(r"[^a-z0-9]", "", str(web_domain or "").lower())
    return any(len(w) >= 4 and w in domain for w in a)


def name_check(bundle: Bundle, verified: Sequence[Row], seg: Segment) -> tuple[str, str | None]:
    """('ok', None), ('rename', site name) or ('wrong_website', site name), from the verified `business_name`.

    13 Nov 2026: an Overture listing carried another business's website, so the message greeted a different name.
    The site's own name wins when the site is in the listing's city; otherwise the website is not theirs.
    """
    b = bundle.business
    names = [str(vget(f.get("value"), "name") or "").strip() for f in evidence.by_field(verified, "business_name")]
    site = next((n for n in names if n), None)
    places = [str(b.get("city") or ""), str(b.get("locality") or "")]
    places += [a for c in seg.cities if c.name == b.get("city") for a in c.aliases]
    if site is None or names_match(b.get("name"), site, b.get("web_domain"), places):
        return "ok", None
    city_words = [p.lower() for p in places if p]
    text = " ".join(str(pg.get("text") or "")[:20000].lower() for pg in bundle.pages)
    if city_words and any(w in text for w in city_words):
        return "rename", site
    return "wrong_website", site


def _roll_up(verified: Sequence[Row], name: str) -> int | None:
    counts = [c for c in (fact_count(f) for f in evidence.by_field(verified, name)) if c is not None]
    return max(counts) if counts else None


def plan_business(
    bundle: Bundle,
    seg: Segment,
    excl: Exclusions,
    suppressed: Suppression,
    asker: FlagAsker,
    deps: VerifyDeps,
) -> Plan:
    """Decide everything verification writes for one business, without writing it."""
    now = deps.now()
    b = bundle.business
    bid = str(b["id"])
    plan = Plan(business_id=bid)
    st = plan.stats
    region = region_for(str(b.get("country") or seg.country))
    by_id, by_url = _page_index(bundle.pages)

    # 1. Quotes (10.2)
    states = verify_quotes(bundle, region)
    plan.fact_states = states
    checked_ai = [s for fid, s in states.items() if s.why not in ("code",)]
    st["facts.verified"] += sum(s.verified for s in states.values())
    st["facts.unverified"] += sum(not s.verified for s in states.values())
    st["facts.page_missing"] += sum(s.why == "page_missing" for s in states.values())
    failed = sum(not s.verified for s in checked_ai)
    if (
        len(checked_ai) >= SUSPICIOUS_MIN_FACTS
        and failed / len(checked_ai) > SUSPICIOUS_SHARE
        and not (b.get("extra") or {}).get("browser_requeued_at")
        and any(p.get("render_mode") != "browser" for p in bundle.pages)
    ):
        # The page text was probably incomplete: research once more with a browser (10.2.4).
        st["requeued_for_browser"] += 1
        plan.status = "queued"
        plan.extra_patch = {"force_browser": True, "browser_requeued_at": now.isoformat()}
        return plan
    verified = current_verified(bundle, states)

    # 2. Website status (10.4)
    site, plan.website_fact = plan_website(bundle, now)
    if site:
        st[f"website.{site}"] += 1

    # 3. Suppressed domain (10.3.6)
    if b.get("web_domain") and str(b["web_domain"]).lower() in suppressed.domains:
        plan.status, plan.reject_reason = "suppressed", "suppressed"
        st["status.suppressed"] += 1
        return plan

    # 4. Competitors, chains, hospitals (10.5)
    hints = competitor_hints(bundle, verified, excl)
    if len(hints) >= 2:
        plan.status, plan.reject_reason = "rejected", "competitor"
        st["status.rejected.competitor"] += 1
        return plan
    if len(hints) == 1:
        answer = asker.ask(
            {
                "business_name": b.get("name"),
                "field": "is_agency_or_vendor",
                "question": AGENCY_QUESTION,
                "hint": hints[0],
                "facts": [
                    {k: v for k, v in _fact_payload(f, by_id, by_url).items() if k != "context"}
                    for f in evidence.by_field(verified, *AGENCY_FIELDS)
                ][:12],
                "pages": [
                    {"url": p["url"], "text": (p.get("text") or "")[:CONTEXT_CHARS]}
                    for p in bundle.pages
                    if on_domain(p["url"], b.get("web_domain"))
                ][:4],
            }
        )
        st["competitor.asked"] += 1
        if answer is not None and answer.is_competitor is True:
            plan.status, plan.reject_reason = "rejected", "competitor"
            st["status.rejected.competitor"] += 1
            return plan
    big = chain_or_hospital(bundle, verified, excl)
    if big:
        plan.status, plan.reject_reason = "rejected", big
        st[f"status.rejected.{big}"] += 1
        return plan

    # 5. Contacts (10.3), first to see whether the business is reachable at all
    contacts = plan_contacts(bundle, verified, seg, suppressed, deps, now, st)
    reachable = usable_contact_exists(contacts, bundle.contacts, verified, now)

    # 6. Conflicts (10.7): only worth AI money when the business can be contacted
    if reachable:
        for conflict in find_conflicts(verified):
            winner = resolve_by_rule(conflict, by_id, by_url)
            how = "rule"
            if winner is None:
                answer = asker.ask(
                    {
                        "business_name": b.get("name"),
                        "field": conflict.field,
                        "question": f"These facts about {conflict.field} disagree. Which one does the page "
                        "text support? Answer with its id, or null if none can be trusted.",
                        "facts": [_fact_payload(f, by_id, by_url) for f in conflict.facts],
                        "pages": [
                            {"url": f.get("url"), "text": _fact_payload(f, by_id, by_url)["context"]}
                            for f in conflict.facts
                        ],
                    }
                )
                known = {str(f["id"]).lower(): str(f["id"]) for f in conflict.facts}
                if answer is not None:
                    how = "ai"
                    winner = evidence.resolve_cited_id(answer.trusted_fact_id or "", known)
                else:
                    how = "fallback"
                    winner = fallback_winner(conflict)
            for loser in losers_for(conflict, winner):
                states[loser] = FactState(False, -1, f"lost_conflict_{how}")
            st[f"conflicts.{how}"] += 1
        verified = current_verified(bundle, states)
        contacts = plan_contacts(bundle, verified, seg, suppressed, deps, now, Counter())
    plan.contacts = contacts
    st["contacts.planned"] += len(contacts)

    # 7. Signal freshness (10.6)
    plan.expire_signals = signals_to_expire(bundle, now)
    st["signals.expired"] += len(plan.expire_signals)

    # Verified counts roll up into the business columns that scoring reads (A.13.2).
    plan.branches_count = _roll_up(verified, "branches")
    plan.staff_count = _roll_up(verified, "staff_or_doctors")

    # 7b. The listing's name and the site's own name must mean the same business (13 Nov 2026)
    outcome, site_name = name_check(bundle, verified, seg)
    if outcome == "wrong_website":
        plan.status, plan.reject_reason = "rejected", "wrong_website"
        plan.extra_patch["site_name"] = site_name
        st["status.rejected.wrong_website"] += 1
        return plan
    if outcome == "rename" and site_name:
        plan.rename = site_name[:200]
        plan.extra_patch["listing_name"] = b.get("name")
        st["name.renamed"] += 1

    # 8. Final status (10.8)
    if not reachable:
        dead_twice = site == "dead" and len((plan.website_fact or {}).get("value", {}).get("dead_days") or []) >= 2
        plan.status = "rejected"
        plan.reject_reason = "website_dead_no_contact" if dead_twice else "no_contact"
        st[f"status.rejected.{plan.reject_reason}"] += 1
        return plan
    plan.status, plan.researched = "researched", True
    st["status.researched"] += 1
    return plan


# =========================================================================
# Writing
# =========================================================================

_PHONE_UPSERT: Final = """
insert into public.contacts (business_id, name, role, phone_e164, phone_type, email, source, source_url, quote,
                             is_decision_maker, verified, verified_at, do_not_contact)
values (%(business_id)s, %(name)s, %(role)s, %(phone_e164)s, %(phone_type)s, null, %(source)s, %(source_url)s,
        %(quote)s, %(is_decision_maker)s, %(verified)s, %(verified_at)s, %(do_not_contact)s)
on conflict (business_id, phone_e164) where phone_e164 is not null do update set
  name = coalesce(excluded.name, contacts.name),
  role = coalesce(excluded.role, contacts.role),
  phone_type = excluded.phone_type,
  source = case when contacts.source = 'website' then contacts.source else excluded.source end,
  source_url = case when contacts.source = 'website' and excluded.source <> 'website'
                    then contacts.source_url else excluded.source_url end,
  quote = case when contacts.source = 'website' and excluded.source <> 'website'
               then contacts.quote else excluded.quote end,
  is_decision_maker = contacts.is_decision_maker or excluded.is_decision_maker,
  verified = excluded.verified,
  verified_at = greatest(contacts.verified_at, excluded.verified_at),
  do_not_contact = contacts.do_not_contact or excluded.do_not_contact
"""
_EMAIL_UPSERT: Final = """
insert into public.contacts (business_id, name, role, phone_e164, phone_type, email, source, source_url, quote,
                             is_decision_maker, verified, verified_at, do_not_contact)
values (%(business_id)s, %(name)s, %(role)s, null, 'unknown', %(email)s, %(source)s, %(source_url)s, %(quote)s,
        %(is_decision_maker)s, %(verified)s, %(verified_at)s, %(do_not_contact)s)
on conflict (business_id, lower(email)) where email is not null do update set
  name = coalesce(excluded.name, contacts.name),
  role = coalesce(excluded.role, contacts.role),
  source = case when contacts.source = 'website' then contacts.source else excluded.source end,
  source_url = coalesce(contacts.source_url, excluded.source_url),
  quote = coalesce(contacts.quote, excluded.quote),
  is_decision_maker = contacts.is_decision_maker or excluded.is_decision_maker,
  verified = excluded.verified,
  verified_at = greatest(contacts.verified_at, excluded.verified_at),
  do_not_contact = contacts.do_not_contact or excluded.do_not_contact
"""
_NAME_ONLY_INSERT: Final = """
insert into public.contacts (business_id, name, role, source, source_url, quote, is_decision_maker, verified,
                             verified_at)
select %(business_id)s, %(name)s, %(role)s, %(source)s, %(source_url)s, %(quote)s, true, true, %(verified_at)s
where not exists (select 1 from public.contacts c
                  where c.business_id = %(business_id)s and c.phone_e164 is null and c.email is null
                    and lower(c.name) = lower(%(name)s))
"""
_WEBSITE_FACT: Final = """
with upd as (
  update public.facts set value = %(value)s, quote = %(quote)s, url = %(url)s, page_id = %(page_id)s,
         model = 'rule', verified = true, verify_score = 100, verified_at = %(now)s
   where business_id = %(business_id)s and field = 'website_status'
  returning id
)
insert into public.facts (business_id, field, value, quote, url, page_id, model, verified, verify_score, verified_at)
select %(business_id)s, 'website_status', %(value)s, %(quote)s, %(url)s, %(page_id)s, 'rule', true, 100, %(now)s
where not exists (select 1 from upd)
"""


def _contact_params(c: ContactRow) -> dict[str, Any]:
    return {
        "business_id": c.business_id,
        "name": c.name,
        "role": c.role,
        "phone_e164": c.phone_e164,
        "phone_type": c.phone_type,
        "email": c.email,
        "source": c.source,
        "source_url": c.source_url,
        "quote": c.quote,
        "is_decision_maker": c.is_decision_maker,
        "verified": c.verified,
        "verified_at": c.verified_at,
        "do_not_contact": c.do_not_contact,
    }


def apply_plans(conn: Connection[Any], plans: Sequence[Plan], now: datetime) -> None:
    """Write a chunk of plans in the caller's transaction (batched statements, one round trip each)."""
    facts = [
        {"id": fid, "verified": s.verified, "score": s.score, "at": now, "url": s.url, "page_id": s.page_id}
        for p in plans
        for fid, s in p.fact_states.items()
        if s.changed
    ]
    site_facts = [
        {**p.website_fact, "value": db.Jsonb(p.website_fact["value"]), "now": now}
        for p in plans
        if p.website_fact is not None
    ]
    contacts = [c for p in plans for c in p.contacts]
    with conn.cursor() as cur:
        if facts:
            cur.executemany(
                "update public.facts set verified = %(verified)s, verify_score = %(score)s, verified_at = %(at)s, "
                "url = coalesce(%(url)s, url), page_id = coalesce(%(page_id)s::uuid, page_id) where id = %(id)s",
                facts,
            )
        if site_facts:
            cur.executemany(_WEBSITE_FACT, site_facts)
        phones = [_contact_params(c) for c in contacts if c.phone_e164]
        mails = [_contact_params(c) for c in contacts if c.email and not c.phone_e164]
        names = [_contact_params(c) for c in contacts if not c.phone_e164 and not c.email and c.name]
        if phones:
            cur.executemany(_PHONE_UPSERT, phones)
        if mails:
            cur.executemany(_EMAIL_UPSERT, mails)
        if names:
            cur.executemany(_NAME_ONLY_INSERT, names)
        expire = [{"id": sid, "now": now} for p in plans for sid in p.expire_signals]
        if expire:
            cur.executemany(
                "update public.signals set expires_at = greatest(%(now)s, observed_at + interval '1 second') "
                "where id = %(id)s and expires_at > %(now)s",
                expire,
            )
        cur.executemany(
            """
            update public.businesses set
              status = coalesce(%(status)s, status),
              reject_reason = case when %(status)s::text is null then reject_reason else %(reason)s end,
              researched_at = case when %(researched)s then %(now)s else researched_at end,
              branches_count = coalesce(%(branches)s, branches_count),
              staff_count = coalesce(%(staff)s, staff_count),
              queued_at = case when %(status)s = 'queued' then %(now)s else queued_at end,
              name = coalesce(%(rename)s, name),
              extra = extra || %(extra)s
            where id = %(id)s
            """,
            [
                {
                    "id": p.business_id,
                    "status": p.status,
                    "reason": p.reject_reason,
                    "researched": p.researched,
                    "now": now,
                    "branches": p.branches_count,
                    "staff": p.staff_count,
                    "rename": p.rename,
                    "extra": db.Jsonb(p.extra_patch),
                }
                for p in plans
            ],
        )


# =========================================================================
# Loading and the stage entry point
# =========================================================================

_PENDING: Final = """
select b.id
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.status in ('queued', 'researched')
   and (exists (select 1 from public.facts f where f.business_id = b.id and f.verified_at is null)
        or (b.status = 'researched'
            and not exists (select 1 from public.contacts c where c.business_id = b.id)
            and not exists (select 1 from public.scores s where s.business_id = b.id)))
 order by b.researched_at nulls last, b.id
 limit %(limit)s
"""


def pending_ids(segment_ids: Sequence[str], limit: int | None, conn: Connection[Any] | None = None) -> list[str]:
    """Businesses with facts never verified, or researched without any contact yet (no website)."""
    rows = db.fetch_all(_PENDING, {"segments": list(segment_ids), "limit": limit}, conn=conn)
    return [str(r["id"]) for r in rows]


def load_bundles(business_ids: Sequence[str], conn: Connection[Any] | None = None) -> list[Bundle]:
    """Everything for a chunk of businesses in a handful of queries."""
    ids = list(business_ids)
    biz = evidence.businesses(ids, conn=conn)
    pages = db.fetch_all(
        "select id, business_id, url, fetched_at, http_status, render_mode, title, text, robots_allowed "
        "from public.pages where business_id = any(%s::uuid[])",
        [ids],
        conn=conn,
    )
    records = db.fetch_all(
        "select business_id, source, source_key, payload, fetched_at from public.source_records "
        "where business_id = any(%s::uuid[]) and source <> 'legacy_skip'",
        [ids],
        conn=conn,
    )
    facts = evidence.all_facts(ids, conn=conn)
    signals = evidence.signals_for(ids, conn=conn)
    contacts = evidence.contacts_for(ids, conn=conn)
    pages_by: dict[str, list[Row]] = {}
    for p in pages:
        p["id"] = str(p["id"])
        pages_by.setdefault(str(p["business_id"]), []).append(p)
    records_by: dict[str, list[Row]] = {}
    for r in records:
        records_by.setdefault(str(r["business_id"]), []).append(r)
    return [
        Bundle(
            business=biz[i],
            pages=pages_by.get(i, []),
            facts=facts.get(i, []),
            signals=signals.get(i, []),
            contacts=contacts.get(i, []),
            records=records_by.get(i, []),
        )
        for i in ids
        if i in biz
    ]


def selected_segments(rc: RunContext) -> dict[str, Segment]:
    segments = load_segments(get_settings().segments_dir)
    wanted = set(rc.opts.segments) if rc.opts.segments else set(segments)
    return {k: v for k, v in segments.items() if k in wanted}


def run(rc: RunContext, router: ai.AIRouter | None = None, deps: VerifyDeps | None = None) -> dict[str, Any]:
    """`nlead verify`: verify every business with new facts. Dry runs plan everything and write nothing."""
    deps = deps or VerifyDeps()
    segments = selected_segments(rc)
    excl = Exclusions.load()
    suppressed = Suppression.load()
    stats: Counter[str] = Counter()
    if router is None and not rc.opts.dry_run:
        try:
            router = ai.router_for(rc)
        except ai.AIUnavailable as exc:
            stats["ai.unavailable"] += 1
            log.warning("verify.no_ai", reason=exc.reason)
    asker = FlagAsker(router, rc.run_id, enabled=not rc.opts.dry_run)
    ids = pending_ids(list(segments), rc.opts.limit)
    for start in range(0, len(ids), CHUNK):
        bundles = load_bundles(ids[start : start + CHUNK])
        plans: list[Plan] = []
        for bundle in bundles:
            seg = segments.get(str(bundle.business["segment_id"]))
            if seg is None:
                stats["skipped.unknown_segment"] += 1
                continue
            try:
                plan = plan_business(bundle, seg, excl, suppressed, asker, deps)
            except Exception as exc:  # one odd record must not stop the morning run; it is retried tomorrow
                stats["errors"] += 1
                log.error(
                    "verify.business_failed",
                    business_id=str(bundle.business["id"]),
                    error=f"{type(exc).__name__}: {exc}",
                )
                continue
            plans.append(plan)
            stats.update(plan.stats)
        if plans and not rc.opts.dry_run:
            with db.tx("engine", {"run_id": rc.run_id, "stage": "verify"}) as conn:
                apply_plans(conn, plans, deps.now())
        stats["businesses"] += len(plans)
    stats.update(asker.stats)
    result = dict(sorted(stats.items()))
    rc.stats["verify"] = result
    log.info("verify.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
