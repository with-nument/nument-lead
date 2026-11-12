"""One-time import from the old lead-engine folder (Step 20).

Reads `data/leads.jsonl`, `data/reviews.jsonl` (people's sheet edits), `data/suppression.csv` and
`data/skip_list.txt`. The old folder is only read, never written.

Safe to re-run: every row has a stable identity (the `legacy` source record for a business, `legacy:<id>` for its
signal, the business for its score and lead, a key per history entry), and a row is only written when it differs
from what is stored. A second run reports zero inserts and zero updates. `--dry-run` does the whole import in one
transaction and rolls it back, so the counts are real.

Mapping (20.3):
- businesses: one per old lead, in the segment from `legacy_segment_map.json`; leads outside wave 1 go to
  their domain's segment (d2c-in, firms-in, ...), created disabled so the engine never searches for more.
  Marketplace posts (D-xxxx) have no business identity: only their source record is kept (D-025).
- contacts: the named person (and the decision maker when it is someone else) plus the business's own line.
  Only phones and emails the old engine verified on the business's own pages (D-033).
- signals: the old "why now" as one dated signal; most arrive already expired, as intended.
- facts: evidence quotes and site checks with `model = 'legacy'`, unverified until a fresh crawl (Step 10).
- scores: `version = 'legacy-v1'`, total = win chance, the old parts in `reasons`.
- leads: listed A or B, or anything the team already worked on. The DB trigger logs `lead_created`; old sheet
  history becomes `edit` activities with their original times (A.13.5 rule 1: code never writes stage_change).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import phonenumbers
import tldextract
from psycopg import Connection, sql

from .. import db
from ..logging import get_logger
from ..models import SIGNAL_CATEGORY
from ..pipeline.runs import RunContext
from ..sheet import design as d

log = get_logger()

LEGACY_ROOT: Final = Path.home() / "Desktop" / "lead-engine"
SEGMENT_MAP_FILE: Final = Path(__file__).with_name("legacy_segment_map.json")
SCORE_VERSION: Final = "legacy-v1"
MODEL: Final = "legacy"
IST: Final = d.IST

# Segments for old leads outside wave 1 (20.3.1). Created disabled with no quota; a later wave adds the YAML.
LEGACY_SEGMENTS: Final[dict[str, tuple[str, str]]] = {
    "d2c-in": ("d2c", "D2C brands, India (old leads only)"),
    "firms-in": ("firms", "Firms and startups, India (old leads only)"),
    "wellness-in": ("wellness", "Fitness and wellness, India (old leads only)"),
    "hospitality-in": ("hospitality", "Hospitality and travel, India (old leads only)"),
    "auto-in": ("auto", "Auto services, India (old leads only)"),
    "finance-in": ("finance", "Insurance and loans, India (old leads only)"),
}
# Fresh-for windows and default points (A.12.3)
SIGNAL_DAYS: Final[dict[str, int]] = {
    "public_ask": 14,
    "tender": 30,
    "hiring_builder": 30,
    "hiring_frontdesk": 30,
    "funding": 120,
    "news": 30,
}
SIGNAL_POINTS: Final[dict[str, int]] = {
    "public_ask": 10,
    "tender": 10,
    "hiring_builder": 8,
    "hiring_frontdesk": 8,
    "funding": 0,
    "news": 3,
}
# Old watch-out flags in plain words (old build_workbook.FLAG_TEXT); info-only flags are dropped.
FLAG_TEXT: Final[dict[str, str]] = {
    "equity_risk": "equity-only ask", "in_house_tech": "has tech team", "larger_team": "bigger than ICP",
    "claims_unverified": "claims unverified", "low_engagement": "low engagement", "regulatory_risk": "regulatory risk",
    "activity_unconfirmed": "activity unconfirmed", "aging_intent": "need 31 to 90 days old", "stale_signal": "old signal",
    "need_not_current": "need over 30 days old", "undated_intent": "undated signal", "name_collision_risk": "name collision",
    "single_source": "single source", "competitor_check": "check: competitor?", "india_inferred": "India inferred",
    "sensitive_domain": "health or sensitive", "heavily_contested": "50+ bids", "new_unproven_client": "new client account",
    "old_funding": "old funding", "city_conflict": "city conflict", "founder_unknown": "founder unknown",
    "outside_sub_band": "outside size band",
}  # fmt: skip
INFO_FLAGS: Final = frozenset({"track_C_overlap", "lqs_missing", "marketplace_skipped"})
HISTORY_FIELDS: Final[dict[str, str]] = {"deal_value": "deal_value_inr"}  # old review field -> new column

# Step 6.5 normalisation, kept local so this one-time import does not depend on a stage built in parallel.
# Same rules as normalize.py; after the merge both give identical values.
_LEGAL_SUFFIXES: Final = ("private limited", "pvt ltd", "pvt", "ltd", "limited", "llp", "inc", "llc", "l l c", "fze", "fzco", "fz llc", "and co", "co", "opc")  # fmt: skip
_IGNORED_HOSTS: Final = frozenset({"practo.com", "linkedin.com", "instagram.com", "facebook.com", "x.com", "twitter.com", "youtube.com", "wa.me", "google.com", "linktr.ee", "justdial.com", "indiamart.com", "internshala.com"})  # fmt: skip
_SHARED_HOSTS: Final = frozenset({"wixsite.com", "blogspot.com", "wordpress.com", "webflow.io", "myshopify.com", "business.site", "carrd.co", "notion.site", "godaddysites.com", "zohosites.in", "zohosites.com"})  # fmt: skip
_tld = tldextract.TLDExtract(suffix_list_urls=())  # offline: the bundled public suffix list


def norm_name(raw: str | None) -> str:
    s = unicodedata.normalize("NFKC", raw or "").lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed:
        changed = False
        for suf in _LEGAL_SUFFIXES:
            if s.endswith(" " + suf):
                s, changed = s[: -len(suf) - 1].strip(), True
    return s


def web_domain(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    ext = _tld(str(url).strip())
    if not ext.domain or not ext.suffix:
        return None
    registrable = f"{ext.domain}.{ext.suffix}".lower()
    host = ".".join(p for p in (ext.subdomain, ext.domain, ext.suffix) if p).lower()
    host = host[4:] if host.startswith("www.") else host
    if registrable in _IGNORED_HOSTS:
        return None
    return host if registrable in _SHARED_HOSTS else registrable


def homepage(url: str | None) -> str | None:
    if not web_domain(url):
        return None
    ext = _tld(str(url).strip())
    host = ".".join(p for p in (ext.subdomain, ext.domain, ext.suffix) if p).lower()
    return f"https://{host}/"


def phone_e164(raw: str | None, kind_hint: str | None = None) -> tuple[str, str] | None:
    """(E.164, phone_type) for an Indian number, or None when it is not a valid number."""
    if not raw:
        return None
    try:
        num = phonenumbers.parse(str(raw), "IN")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    if kind_hint in ("mobile", "whatsapp"):
        return e164, "mobile"
    if kind_hint == "landline":
        return e164, "landline"
    t = phonenumbers.number_type(num)
    pnt = phonenumbers.PhoneNumberType
    if t == pnt.MOBILE or (t == pnt.FIXED_LINE_OR_MOBILE and str(num.national_number)[:1] in "6789"):
        return e164, "mobile"
    if t == pnt.FIXED_LINE:
        return e164, "landline"
    if t in (pnt.TOLL_FREE, pnt.SHARED_COST):
        return e164, "tollfree"
    return e164, "unknown"


# ---------------------------------------------------------------------------
# Reading the old folder (read only)
# ---------------------------------------------------------------------------
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def segment_map() -> dict[str, str]:
    data = json.loads(SEGMENT_MAP_FILE.read_text(encoding="utf-8"))
    return dict(data["segments"])


_DM_ROLE = re.compile(r"founder|owner|director|ceo|partner|principal|proprietor|managing|head", re.I)
_CLINIC = re.compile(
    r"clinic|hospital|diagnostic|dental|derma|skin|ivf|fertility|physio|therap|psycholog|dietitian|ayurved|health", re.I
)
_REALTY = re.compile(r"realty|real estate|properties|property|estates", re.I)
_EDU = re.compile(r"academy|classes|institute|school|coaching|edtech|course|tutor|learning", re.I)


def guess_segment(old: dict[str, Any]) -> str:
    """Keyword rules for an id the reviewed map does not have (20.3.1)."""
    text = f"{old.get('org') or ''} {old.get('why') or ''}"
    if _CLINIC.search(text):
        return "clinics-in"
    if _REALTY.search(text):
        return "realestate-in"
    if _EDU.search(text):
        return "education-in"
    return "firms-in"


def parse_day(value: Any) -> dt.date | None:
    """Old dates: ISO strings, 'YYYY-MM-DDTHH:MM:SS', or apply-by text like "30 Oct' 26"."""
    if not value:
        return None
    s = str(value).strip()
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d %b' %y", "%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def midnight(day: dt.date) -> dt.datetime:
    """00:00 IST on that day."""
    return dt.datetime.combine(day, dt.time(0, 0), tzinfo=IST)


def at_ist(day: dt.date | None) -> dt.datetime | None:
    return midnight(day) if day else None


def parse_local_time(value: Any) -> dt.datetime | None:
    """History times were written by the old Mac job in local time (IST) without a zone."""
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value))
    except ValueError:
        day = parse_day(value)
        return at_ist(day)
    return t if t.tzinfo else t.replace(tzinfo=IST)


def first_part(text: str | None) -> str:
    """'Founder (per LinkedIn snippet); co-director ...' -> 'Founder'."""
    return re.split(r"\s+\(|;", text or "")[0].strip()


def clean_city(text: str | None) -> str | None:
    city = re.split(r"\s*[(;,]", text or "")[0].strip()
    return city or None


def strip_quotes(text: str | None) -> str:
    return (text or "").strip().strip('"').strip("“”").strip()


# ---------------------------------------------------------------------------
# What each old record becomes (pure: no database)
# ---------------------------------------------------------------------------
def is_business(old: dict[str, Any]) -> bool:
    """Marketplace posts (track D) and records without a company name are not businesses (D-025)."""
    return old.get("track") != "D" and bool((old.get("org") or "").strip())


def stage_of(rev: dict[str, Any]) -> str:
    raw = str(rev.get("stage") or "").strip()
    if not raw:
        return "new"
    return d.LEGACY_LABELS.get(raw.lower()) or d.canon_stage(raw)[0] or "new"


def wants_lead(old: dict[str, Any], rev: dict[str, Any]) -> bool:
    """Listed A or B leads, and every lead someone already worked on (20.3.2)."""
    return stage_of(rev) != "new" or bool(old.get("listed") and old.get("grade") in ("A", "B"))


def grade_of(old: dict[str, Any]) -> str:
    return old["grade"] if old.get("grade") in ("A", "B", "C", "D") else "D"


def signal_type(old: dict[str, Any]) -> str | None:
    """The old "why now" as an A.12.3 signal type, from the source, the angle and the wording."""
    src = (old.get("source") or "").lower()
    why = f"{old.get('why') or ''} {old.get('why_now_short') or ''}".lower()
    angle = old.get("wa_angle") or ""
    if re.search(r"\brfp\b|tender", why):
        return "tender"
    if (
        angle == "public_ask"
        or "startuptalky" in src
        or re.search(r"asked publicly|publicly asking|public(ly)? ask", why)
    ):
        return "public_ask"
    if (
        "internshala" in src
        or "jobs" in src
        or angle == "hire_complement"
        or re.search(r"\bhiring\b|openings?\b|job post", why)
    ):
        frontdesk = re.search(r"receptionist|telecaller|front ?desk|sales executive|counsell?or|coordinator", why)
        return "hiring_frontdesk" if frontdesk else "hiring_builder"
    if re.search(r"\braised\b|\bfunded\b|funding|seed\b|pre-seed|\bcr\b round", why) or angle == "milestone_next":
        return "funding"
    return None


def pitch_mode_of(old: dict[str, Any]) -> str:
    kind = signal_type(old)
    category = SIGNAL_CATEGORY.get(kind or "", "")
    return category if category in ("stated_need", "visible_pain") else "fit_only"


def signal_values(old: dict[str, Any]) -> dict[str, Any] | None:
    """The old why-now as one dated signal; None when it is not a signal we track or has no date."""
    kind = signal_type(old)
    day = (
        parse_day(old.get("why_now_date"))
        or parse_day(old.get("source_published_at"))
        or parse_day(old.get("evidence_date_1"))
        or parse_day(old.get("collected_at"))
    )
    if not kind or not day:
        return None
    observed = midnight(day)
    expires = observed + dt.timedelta(days=SIGNAL_DAYS[kind])
    deadline = parse_day(old.get("apply_by"))
    if kind == "tender" and deadline and deadline >= day:  # a tender is fresh until its deadline (A.12.3)
        expires = midnight(deadline + dt.timedelta(days=1))
    summary = (old.get("why_now_short") or "").strip() or d.cut(old.get("why"), 60)
    return {
        "type": kind,
        "category": SIGNAL_CATEGORY[kind],
        "points": SIGNAL_POINTS[kind],
        "observed_at": observed,
        "expires_at": expires,
        "source": "legacy",
        "url": old.get("why_now_url") or old.get("evidence_url_1") or old.get("source_url") or None,
        "quote": strip_quotes(old.get("evidence_1")) or summary,
        "details": {
            "summary": summary,
            "note": old.get("why_now_note"),
            "legacy_id": old["lead_id"],
            "source_name": old.get("source"),
        },
    }


def legacy_facts(old: dict[str, Any]) -> list[dict[str, Any]]:
    """Old evidence and site checks as facts with Step 9 field names (A.13.2)."""
    site = old.get("website") or None
    out: list[dict[str, Any]] = []
    for i in (1, 2, 3):
        quote = strip_quotes(old.get(f"evidence_{i}"))
        if quote:
            out.append({"field": "sales_note", "value": {"text": quote, "date": old.get(f"evidence_date_{i}") or None},
                        "quote": quote[:1000], "url": old.get(f"evidence_url_{i}") or None})  # fmt: skip
    for item in old.get("wa_facts") or []:
        if isinstance(item, dict) and item.get("fact"):
            out.append({"field": "sales_note", "value": {"text": item["fact"]}, "quote": None, "url": item.get("url")})
    if old.get("dm_name"):
        out.append({"field": "decision_maker", "value": {"name": old["dm_name"], "role": first_part(old.get("dm_role"))},
                    "quote": old.get("dm_snippet") or None, "url": old.get("dm_source_url") or None})  # fmt: skip
    if old.get("team_size_band"):
        out.append({"field": "staff_or_doctors", "value": {"band": old["team_size_band"]}, "quote": None, "url": None})
    if old.get("has_tech_team"):
        out.append({"field": "in_house_tech", "value": {"answer": old["has_tech_team"]}, "quote": None, "url": None})
    if old.get("site_builder") or old.get("vendor_footer"):
        out.append({"field": "tech_stack", "value": {"builder": old.get("site_builder") or None,
                    "vendor_footer": old.get("vendor_footer") or None}, "quote": None, "url": site})  # fmt: skip
    has = old.get("site_has") or {}
    for key, fld in (("booking", "booking_method"), ("whatsapp", "whatsapp_present"), ("chat", "chat_widget")):
        if key in has:
            out.append({"field": fld, "value": {"present": bool(has[key])}, "quote": None, "url": site})
    if old.get("website_status"):
        out.append({"field": "website_status", "value": {"status": old["website_status"]}, "quote": None, "url": site})
    if old.get("contact_form_url"):
        out.append(
            {
                "field": "contact_form_url",
                "value": {"url": old["contact_form_url"]},
                "quote": None,
                "url": old["contact_form_url"],
            }
        )
    if old.get("site_score") is not None:
        out.append({"field": "site_speed_mobile", "value": {"score": old["site_score"]}, "quote": None, "url": site})
    return out


def contact_rows(old: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """[(identity, values)] for the named person, the decision maker when different, and the business's line.

    Only phones and emails the old engine verified on the business's own pages are kept (D-033).
    """
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    person = (old.get("name") or "").strip()
    dm = (old.get("dm_name") or "").strip()
    phone = phone_e164(old.get("phone"), old.get("phone_type")) if old.get("phone_status") == "verified" else None
    email = (old.get("email") or "").strip().lower() if old.get("email_status") == "verified" else ""
    owner = str(old.get("phone_belongs_to") or "")
    phone_is_person = bool(phone and person and owner.startswith("person") and person.lower() in owner.lower())
    domain = web_domain(old.get("website"))

    def src(url: str | None) -> str:
        return "website" if url and domain and web_domain(url) == domain else "other"

    if person:
        role = first_part(old.get("role"))
        is_dm = dm.lower() == person.lower() if dm else bool(_DM_ROLE.search(role))
        values: dict[str, Any] = {
            "role": role or None,
            "is_decision_maker": is_dm,
            "source": src(old.get("dm_source_url")) if is_dm and dm else "other",
            "source_url": old.get("dm_source_url") if is_dm and dm else None,
            "verified": False,
        }
        if phone and phone_is_person:
            values.update(phone_e164=phone[0], phone_type=phone[1], quote=old.get("phone_quote"),
                          source=src(old.get("phone_source_url")), source_url=old.get("phone_source_url"), verified=True)  # fmt: skip
        out.append(({"name": person}, values))
    if dm and dm.lower() != person.lower():
        out.append(({"name": dm}, {"role": first_part(old.get("dm_role")) or None, "is_decision_maker": True,
                    "source": src(old.get("dm_source_url")), "source_url": old.get("dm_source_url"), "verified": False}))  # fmt: skip
    if phone and not phone_is_person:  # the business's own line
        out.append((
            {"name": None, "phone_e164": phone[0]},
            {"role": (old.get("phone_label") or "").strip() or None, "phone_type": phone[1], "email": None,
             "source": src(old.get("phone_source_url")), "source_url": old.get("phone_source_url"),
             "quote": old.get("phone_quote"), "verified": True, "is_decision_maker": False},
        ))  # fmt: skip
    if email:  # its own row, so a wrong number never hides a good email (13.7.5)
        out.append((
            {"name": None, "phone_e164": None, "email": email},
            {"source": src(old.get("email_source_url")), "source_url": old.get("email_source_url"), "verified": True,
             "is_decision_maker": False},
        ))  # fmt: skip
    return out


def their_budget(old: dict[str, Any]) -> str:
    low, high, basis = old.get("budget_inr_min"), old.get("budget_inr_max"), old.get("money_basis")
    if high is None:
        return ""
    if basis == "funding":
        return f"Funded {d.inr(high)}"
    text = d.estimate_text(low, high).removeprefix("≈ ")
    return f"Their budget {text}" + (" a year" if basis == "salary_annual" else "")


def score_values(old: dict[str, Any]) -> dict[str, Any]:
    flags = [FLAG_TEXT.get(f, f.replace("_", " ")) for f in (old.get("flags") or []) if f not in INFO_FLAGS]
    reasons: dict[str, Any] = {
        "legacy": True,
        "win_parts": old.get("win_parts") or {},
        "watch_outs": flags,
        "can_pay": [x for x in (their_budget(old), old.get("buyer_fit_note") or "") if x],
    }
    if old.get("ticket_est_max") is not None:
        reasons["ticket_estimate"] = {"min": old.get("ticket_est_min"), "max": old.get("ticket_est_max")}
        reasons["ticket_basis"] = old.get("ticket_basis")
    fit = old.get("ai_fit") if old.get("ai_fit") is not None else old.get("eff_ai_fit")
    scored = parse_day(old.get("scored_at")) or parse_day(old.get("collected_at"))
    return {
        "version": SCORE_VERSION,
        "fit": max(0, min(3, int(fit or 0))),
        "total": max(0, min(100, int(old.get("win_chance") or 0))),
        "grade": grade_of(old),
        "pitch_mode": pitch_mode_of(old),
        "reasons": reasons,
        "judge_note": (old.get("why") or "")[:280] or None,
        "judge_model": MODEL,
        "computed_at": at_ist(scored) or dt.datetime.now(IST),
    }


def lead_values(old: dict[str, Any], rev: dict[str, Any], segment: str) -> dict[str, Any]:
    angle = old.get("wa_angle") or "legacy"
    pitch = pitch_mode_of(old)
    message = (old.get("wa_msg") or "").strip() or None
    deal = d.parse_money_cell(rev.get("deal_value"))
    return {
        "segment_id": segment,
        "grade": grade_of(old),
        "pitch_mode": pitch,
        "test_group": f"{segment}:{pitch}:{angle}",
        "angle": angle,
        "message": message,
        "message_alt": (old.get("wa_alt") or "").strip() or None,
        "message_model": MODEL if message else None,
        "stage": stage_of(rev),
        "wa_at": parse_day(rev.get("wa_at")),
        "call_at": parse_day(rev.get("call_at")),
        "d3_at": parse_day(rev.get("d3_at")),
        "d7_at": parse_day(rev.get("d7_at")),
        "meeting_at": at_ist(parse_day(rev.get("meeting_at"))),
        "deal_value_inr": Decimal(deal) if deal else None,
        "notes": (rev.get("notes") or "").strip() or None,
        "created_at": at_ist(parse_day(old.get("collected_at"))) or dt.datetime.now(IST),
    }


def history_rows(lead_key: str, rev: dict[str, Any]) -> list[dict[str, Any]]:
    """Old sheet history as `edit` activities at their original times (the trigger owns stage_change rows)."""
    out = []
    for i, h in enumerate(rev.get("history") or []):
        fld = HISTORY_FIELDS.get(h.get("field"), h.get("field"))
        old_v, new_v = h.get("from", ""), h.get("to", "")
        if fld == "stage":
            old_v, new_v = stage_of({"stage": old_v}), stage_of({"stage": new_v})
        key = f"{lead_key}:{i}:{h.get('at')}:{h.get('field')}"
        out.append({
            "at": parse_local_time(h.get("at")) or dt.datetime.now(IST),
            "payload": {"field": fld, "from": old_v, "to": new_v, "sheet": h.get("sheet"), "legacy": True, "legacy_key": key},
        })  # fmt: skip
    return out


def business_values(old: dict[str, Any], segment: str, status: str, reject: str | None) -> dict[str, Any]:
    name = d.clean_org(old.get("org"))
    collected = parse_day(old.get("collected_at"))
    verified = parse_day(old.get("last_verified_at")) or parse_day(old.get("scored_at")) or collected
    return {
        "segment_id": segment,
        "name": name,
        "norm_name": norm_name(name),
        "website": homepage(old.get("website")),
        "web_domain": web_domain(old.get("website")),
        "country": "in",
        "city": clean_city(old.get("city")),
        "status": status,
        "reject_reason": reject,
        "extra": {
            "legacy_id": old["lead_id"],
            "legal_name": old.get("org"),
            "state": old.get("state"),
            "track": old.get("track"),
        },
        "first_seen_at": at_ist(collected) or dt.datetime.now(IST),
        "last_seen_at": at_ist(verified) or dt.datetime.now(IST),
        "researched_at": at_ist(verified),
    }


def read_skip_list(path: Path) -> list[dict[str, Any]]:
    """data/skip_list.txt: 'org | name | website domain | source url' per line, '#' for comments."""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        org, person, dom, url = ([p.strip() for p in line.split("|")] + ["", "", "", ""])[:4]
        out.append(
            {"key": text, "org": org, "name": person, "domain": web_domain(dom) if dom else None, "url": url or None}
        )
    return out


def read_suppression(path: Path) -> list[tuple[str, str, str]]:
    """data/suppression.csv (value,type,reason,added_at,requested_by) as (column, value, reason)."""
    if not path.is_file():
        return []
    out = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            value, kind = (row.get("value") or "").strip(), (row.get("type") or "").strip().lower()
            reason = (row.get("reason") or "").strip() or "legacy"
            if not value:
                continue
            if kind == "phone":
                parsed = phone_e164(value)
                if parsed:
                    out.append(("phone_e164", parsed[0], reason))
            elif kind == "email":
                out.append(("email", value.lower(), reason))
            else:
                out.append(("web_domain", web_domain(value) or value.lower(), reason))
    return out


# ---------------------------------------------------------------------------
# Change counting and planning
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    inserted: Counter[str] = field(default_factory=Counter)
    updated: Counter[str] = field(default_factory=Counter)
    unchanged: Counter[str] = field(default_factory=Counter)
    deleted: Counter[str] = field(default_factory=Counter)
    notes: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "inserted": dict(self.inserted),
            "updated": dict(self.updated),
            "unchanged": dict(self.unchanged),
            "deleted": dict(self.deleted),
            "notes": dict(self.notes),
            "total_inserted": sum(self.inserted.values()),
            "total_updated": sum(self.updated.values()) + sum(self.deleted.values()),
        }


def _same(a: Any, b: Any) -> bool:
    """Compare a stored value with a new one, tolerant of numeric, date and JSON types."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except ArithmeticError:
            return False
    if isinstance(a, dict | list) or isinstance(b, dict | list):
        return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    if isinstance(a, dt.date) and isinstance(b, dt.date):
        return a == b
    return str(a) == str(b)


@dataclass
class Plan:
    """Every write the import needs, worked out in memory against what the database already holds."""

    stats: Stats = field(default_factory=Stats)
    inserts: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    updates: dict[str, list[tuple[str, dict[str, Any]]]] = field(default_factory=lambda: defaultdict(list))
    deletes: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    new_leads: list[tuple[dict[str, Any], str]] = field(default_factory=list)  # (row, legacy id)

    def row(
        self, table: str, existing: dict[str, Any] | None, values: dict[str, Any], *, insert_only: Iterable[str] = ()
    ) -> dict[str, Any]:
        """Plan an insert (existing is None) or an update of the columns that differ. Returns the current row."""
        if existing is None:
            new = {"id": str(uuid.uuid4()), **values}
            if table == "leads":
                self.new_leads.append((new, values.get("_legacy_id", "")))
            else:
                self.inserts[table].append(new)
            self.stats.inserted[table] += 1
            return new
        skip = set(insert_only)
        diff = {
            k: v for k, v in values.items() if not k.startswith("_") and k not in skip and not _same(existing.get(k), v)
        }
        if diff:
            self.updates[table].append((existing["id"], diff))
            self.stats.updated[table] += 1
            existing.update(diff)
        else:
            self.stats.unchanged[table] += 1
        return existing


# ---------------------------------------------------------------------------
# What is already in the database: a few queries up front instead of thousands of round trips
# ---------------------------------------------------------------------------
BUSINESS_COLS: Final = ("segment_id", "name", "norm_name", "website", "web_domain", "country", "city", "status",
                        "reject_reason", "extra", "first_seen_at", "last_seen_at", "researched_at")  # fmt: skip
CONTACT_COLS: Final = ("business_id", "name", "role", "phone_e164", "phone_type", "email", "source", "source_url", "quote",
                       "is_decision_maker", "verified", "do_not_contact")  # fmt: skip
SIGNAL_COLS: Final = ("dedupe_key", "business_id", "type", "category", "points", "observed_at", "expires_at", "source",
                      "url", "quote", "details")  # fmt: skip
SCORE_COLS: Final = ("business_id", "version", "fit", "total", "grade", "pitch_mode", "reasons", "judge_note", "judge_model", "computed_at")  # fmt: skip
LEAD_COLS: Final = ("business_id", "segment_id", "score_id", "grade", "pitch_mode", "test_group", "angle", "message",
                    "message_alt", "message_model", "stage", "wa_at", "call_at", "d3_at", "d7_at", "meeting_at",
                    "deal_value_inr", "notes", "created_at")  # fmt: skip


@dataclass
class Existing:
    segments: set[str]
    records: dict[tuple[str, str], dict[str, Any]]  # (source, source_key) -> {id, business_id, payload}
    businesses: dict[str, dict[str, Any]]  # id -> row
    by_domain: dict[tuple[str, str], dict[str, Any]]  # (segment_id, web_domain) -> business row
    contacts: dict[str, list[dict[str, Any]]]  # business_id -> rows
    signals: dict[str, dict[str, Any]]  # dedupe_key -> row
    facts: dict[str, list[dict[str, Any]]]  # business_id -> legacy facts
    scores: dict[str, dict[str, Any]]  # business_id -> legacy score
    leads: dict[str, dict[str, Any]]  # legacy id -> lead row
    history: set[str]  # legacy_key of imported history entries
    suppressed: set[tuple[str, str]]  # (column, value)


def _cols(cols: Iterable[str]) -> sql.Composable:
    return sql.SQL(", ").join(map(sql.Identifier, cols))


def load_existing(conn: Connection[Any], domains: set[tuple[str, str]]) -> Existing:
    def rows(query: sql.Composed | sql.SQL | str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        return [dict(r) for r in conn.execute(query, params).fetchall()]

    records = {
        (r["source"], r["source_key"]): r
        for r in rows(
            "select id::text as id, source, source_key, business_id::text as business_id, payload "
            "from public.source_records where source in ('legacy', 'legacy_skip')"
        )
    }
    ids = sorted({r["business_id"] for r in records.values() if r["business_id"]})
    segs = [s for s, _ in domains]
    doms = [d_ for _, d_ in domains]
    businesses = {
        r["id"]: r
        for r in rows(
            sql.SQL(
                "select id::text as id, {} from public.businesses where id = any(%s::uuid[]) "
                "or (segment_id, web_domain) in (select * from unnest(%s::text[], %s::text[]))"
            ).format(_cols(BUSINESS_COLS)),
            [ids, segs, doms],
        )
    }
    all_ids = sorted(businesses)
    contacts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows(
        sql.SQL("select id::text as id, {} from public.contacts where business_id = any(%s::uuid[])").format(
            _cols(CONTACT_COLS)
        ),
        [all_ids],
    ):
        r["business_id"] = str(r["business_id"])
        contacts[r["business_id"]].append(r)
    facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows("select id::text as id, business_id::text as business_id, field, value, quote, url from public.facts "
                  "where model = %s and business_id = any(%s::uuid[])", [MODEL, all_ids]):  # fmt: skip
        facts[r["business_id"]].append(r)
    scores = {}
    for r in rows(sql.SQL("select id::text as id, {} from public.scores where version = %s and business_id = any(%s::uuid[]) "
                          "order by computed_at").format(_cols(SCORE_COLS)), [SCORE_VERSION, all_ids]):  # fmt: skip
        r["business_id"] = str(r["business_id"])
        scores[r["business_id"]] = r
    leads = {}
    for r in rows(sql.SQL("select a.payload ->> 'legacy_id' as legacy_id, l.id::text as id, {} from public.activities a "
                          "join public.leads l on l.id = a.lead_id where a.type = 'lead_created' and a.payload ? 'legacy_id'")
                  .format(sql.SQL(", ").join(sql.SQL("l.{}").format(sql.Identifier(c)) for c in LEAD_COLS))):  # fmt: skip
        for k in ("business_id", "score_id"):
            r[k] = str(r[k]) if r[k] else None
        leads[r.pop("legacy_id")] = r
    signals = {
        r["dedupe_key"]: r
        for r in rows(
            sql.SQL("select id::text as id, {} from public.signals where dedupe_key like 'legacy:%%'").format(
                _cols(SIGNAL_COLS)
            )
        )
    }
    for r in signals.values():
        r["business_id"] = str(r["business_id"])
    history = {
        r["k"] for r in rows("select payload ->> 'legacy_key' as k from public.activities where payload ? 'legacy_key'")
    }
    suppressed = set()
    for r in rows("select phone_e164, lower(email) as email, web_domain from public.suppression"):
        for col in ("phone_e164", "email", "web_domain"):
            if r[col]:
                suppressed.add((col, r[col]))
    segments = {r["id"] for r in rows("select id from public.segments")}
    by_domain = {(b["segment_id"], b["web_domain"]): b for b in businesses.values() if b["web_domain"]}
    return Existing(
        segments, records, businesses, by_domain, contacts, signals, facts, scores, leads, history, suppressed
    )


# ---------------------------------------------------------------------------
# The import
# ---------------------------------------------------------------------------
class DryRunRollback(Exception):
    """Raised at the end of a dry run so the transaction rolls back with real counts."""


def run(rc: RunContext, *, root: Path | None = None) -> dict[str, Any]:
    stats = migrate(root or LEGACY_ROOT, dry_run=rc.opts.dry_run)
    log.info("migrate_legacy.done", **{k: v for k, v in stats.items() if k != "checks"})
    return stats


def migrate(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Read the old folder, plan every write against the database, apply it in one transaction."""
    data = root / "data"
    if not (data / "leads.jsonl").is_file():
        raise FileNotFoundError(f"no old lead file at {data / 'leads.jsonl'}")
    olds = read_jsonl(data / "leads.jsonl")
    reviews = {r["lead_id"]: r for r in read_jsonl(data / "reviews.jsonl")}
    seg_map = segment_map()
    result: dict[str, Any] = {}
    try:
        with db.tx("engine", {"via": "migrate_legacy"}) as conn:
            businesses = [o for o in olds if is_business(o)]
            segment = {o["lead_id"]: seg_map.get(o["lead_id"]) or guess_segment(o) for o in businesses}
            domains = {(segment[o["lead_id"]], dom) for o in businesses if (dom := web_domain(o.get("website")))}
            have = load_existing(conn, domains)
            plan = build_plan(olds, reviews, segment, seg_map, have, read_skip_list(data / "skip_list.txt"),
                              read_suppression(data / "suppression.csv"))  # fmt: skip
            apply_plan(conn, plan)
            result = {**plan.stats.as_dict(), "checks": checks(conn), "dry_run": dry_run}
            if dry_run:
                raise DryRunRollback
    except DryRunRollback:
        pass
    return result


def build_plan(
    olds: list[dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
    segment: dict[str, str],
    seg_map: dict[str, str],
    have: Existing,
    skips: list[dict[str, Any]],
    suppression_rows: list[tuple[str, str, str]],
) -> Plan:
    plan = Plan()
    skip_domains = {s["domain"] for s in skips if s["domain"]}
    skip_names = {norm_name(s["org"]) for s in skips if s["org"]}

    for seg in sorted(set(segment.values())):
        if seg in have.segments:
            plan.stats.unchanged["segments"] += 1
            continue
        if seg not in LEGACY_SEGMENTS:
            raise ValueError(f"segment {seg} is neither seeded nor a known legacy segment")
        domain_name, display = LEGACY_SEGMENTS[seg]
        plan.inserts["segments"].append({"id": seg, "domain": domain_name, "country": "in", "display_name": display,
                                         "enabled": False, "daily_quota": 0, "config": {"legacy_only": True}})  # fmt: skip
        plan.stats.inserted["segments"] += 1
        have.segments.add(seg)

    # Group old records by the business they describe (two records of one site become one business, Step 6).
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for old in olds:
        key = old["lead_id"]
        if not is_business(old):
            rec = have.records.get(("legacy", key))
            payload = {
                "org": old.get("org"),
                "track": old.get("track"),
                "skipped": "marketplace post without a business",
            }
            plan.row(
                "source_records", rec, {"source": "legacy", "source_key": key, "business_id": None, "payload": payload}
            )
            plan.stats.notes["skipped_marketplace"] += 1
            continue
        if key not in seg_map:
            plan.stats.notes["segment_by_keywords"] += 1
        rec = have.records.get(("legacy", key))
        dom = web_domain(old.get("website"))
        if rec and rec.get("business_id") in have.businesses:
            group: tuple[str, ...] = ("id", rec["business_id"])
        elif dom:
            known = have.by_domain.get((segment[key], dom))
            group = ("id", known["id"]) if known else ("dom", segment[key], dom)
        else:
            group = ("key", key)
        groups[group].append(old)

    wanted_facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group, members in groups.items():
        lead_rec = max(
            members,
            key=lambda o: (wants_lead(o, reviews.get(o["lead_id"], {})), grade_of(o) in "AB", o.get("win_chance") or 0),
        )
        key = lead_rec["lead_id"]
        rev = reviews.get(key, {})
        is_lead = wants_lead(lead_rec, rev)
        names = {norm_name(o.get("org")) for o in members} | {norm_name(d.clean_org(o.get("org"))) for o in members}
        skipped = any(web_domain(o.get("website")) in skip_domains for o in members) or bool(names & skip_names)
        if is_lead:
            status, reject = "qualified", None
        elif skipped:  # the old engine already judged it: the pre-filter keeps it out for 180 days (Step 8)
            status, reject = "rejected", "legacy_skip"
        else:
            status, reject = ("researched" if grade_of(lead_rec) in ("A", "B", "C") else "dormant"), None
        values = business_values(lead_rec, segment[key], status, reject)
        existing = have.businesses.get(group[1]) if group[0] == "id" else None
        biz = plan.row("businesses", existing, values, insert_only=("first_seen_at",))
        have.businesses[biz["id"]] = biz
        if biz.get("web_domain"):
            have.by_domain[(biz["segment_id"], biz["web_domain"])] = biz

        for old in members:
            rec = have.records.get(("legacy", old["lead_id"]))
            payload = {
                "org": old.get("org"),
                "track": old.get("track"),
                "source": old.get("source"),
                "grade": old.get("grade"),
            }
            plan.row(
                "source_records",
                rec,
                {"source": "legacy", "source_key": old["lead_id"], "business_id": biz["id"], "payload": payload},
            )
            sig = signal_values(old)
            if sig is None:
                plan.stats.notes["no_signal"] += 1
            else:
                dedupe = f"legacy:{old['lead_id']}"
                plan.row("signals", have.signals.get(dedupe), {"dedupe_key": dedupe, "business_id": biz["id"], **sig})
            wanted_facts[biz["id"]] += legacy_facts(old)
            if old.get("phone") and old.get("phone_status") != "verified":
                plan.stats.notes["phones_not_verified_skipped"] += 1

        contacts = have.contacts[biz["id"]]
        wrong = is_lead and stage_of(rev) == "wrong_contact"
        for identity, values in (pair for old in members for pair in contact_rows(old)):
            match = next((c for c in contacts if all(c.get(k) == v for k, v in identity.items())), None)
            row_values = {"business_id": biz["id"], **identity, **values}
            if wrong and row_values.get("phone_e164"):
                row_values["do_not_contact"] = True  # 20.3.3: the wrong number is never used again
            contact = plan.row("contacts", match, row_values)
            if match is None:
                contacts.append(contact)
            if wrong and contact.get("phone_e164") and ("phone_e164", contact["phone_e164"]) not in have.suppressed:
                plan.inserts["suppression"].append({"phone_e164": contact["phone_e164"], "reason": "wrong_contact"})
                plan.stats.inserted["suppression"] += 1
                have.suppressed.add(("phone_e164", contact["phone_e164"]))

        score = plan.row("scores", have.scores.get(biz["id"]), {"business_id": biz["id"], **score_values(lead_rec)})
        if not is_lead:
            continue
        lead = plan.row(
            "leads",
            have.leads.get(key),
            {
                "business_id": biz["id"],
                "score_id": score["id"],
                **lead_values(lead_rec, rev, segment[key]),
                "_legacy_id": key,
            },
            insert_only=("created_at",),
        )
        for h in history_rows(key, rev):
            if h["payload"]["legacy_key"] in have.history:
                plan.stats.unchanged["activities"] += 1
                continue
            plan.inserts["activities"].append({"lead_id": lead["id"], "source": "sheet", "type": "edit", **h})
            plan.stats.inserted["activities"] += 1

    for business_id, wanted in wanted_facts.items():
        plan_facts(plan, business_id, wanted, have.facts.get(business_id, []))

    for col, value, reason in suppression_rows:
        if (col, value) in have.suppressed:
            plan.stats.unchanged["suppression"] += 1
            continue
        plan.inserts["suppression"].append({col: value, "reason": reason})
        plan.stats.inserted["suppression"] += 1
        have.suppressed.add((col, value))

    for s in skips:
        payload = {k: s[k] for k in ("org", "name", "domain", "url")}
        plan.row("source_records", have.records.get(("legacy_skip", s["key"])),
                 {"source": "legacy_skip", "source_key": s["key"], "business_id": None, "payload": payload})  # fmt: skip
    return plan


def plan_facts(plan: Plan, business_id: str, wanted: list[dict[str, Any]], have: list[dict[str, Any]]) -> None:
    """Keep exactly the facts the old records hold: add missing ones, remove legacy facts they no longer have."""

    def key(f: dict[str, Any]) -> str:
        return json.dumps([f["field"], f["value"], f.get("quote"), f.get("url")], sort_keys=True, default=str)

    have_keys = {key(f): f["id"] for f in have}
    seen: set[str] = set()
    for f in wanted:
        k = key(f)
        if k in seen:
            continue
        seen.add(k)
        if k in have_keys:
            plan.stats.unchanged["facts"] += 1
            continue
        plan.inserts["facts"].append({"business_id": business_id, "model": MODEL, "verified": False, **f})
        plan.stats.inserted["facts"] += 1
    stale = [fid for k, fid in have_keys.items() if k not in seen]
    plan.deletes["facts"] += stale
    plan.stats.deleted["facts"] += len(stale)


# Foreign keys decide the order: segments, businesses, their children, then leads and their activities.
APPLY_ORDER: Final = (
    "segments",
    "businesses",
    "source_records",
    "contacts",
    "signals",
    "facts",
    "scores",
    "leads",
    "activities",
    "suppression",
)


def _adapt(value: Any) -> Any:
    return db.Jsonb(value) if isinstance(value, dict | list) else value


def apply_plan(conn: Connection[Any], plan: Plan) -> None:
    """Write the plan with a handful of batched statements (executemany pipelines them over the network).

    Within a table: updates, then deletes, then inserts, so a unique value that moves between rows (an email
    leaving a phone row for its own row) is free before it is inserted again.
    """
    for table in APPLY_ORDER:
        _apply_updates(conn, table, plan.updates.get(table, []))
        if plan.deletes.get(table):
            conn.execute(
                sql.SQL("delete from public.{} where id = any(%s::uuid[])").format(sql.Identifier(table)),
                [plan.deletes[table]],
            )
        if table == "leads":
            for row, legacy_id in plan.new_leads:  # one by one: the trigger reads app.context for lead_created
                context = json.dumps({"via": "migrate_legacy", "legacy_id": legacy_id})
                conn.execute("select set_config('app.context', %s, true)", [context])
                values = {k: v for k, v in row.items() if not k.startswith("_")}
                conn.execute(
                    sql.SQL("insert into public.leads ({}) values ({})").format(
                        _cols(values), sql.SQL(", ").join(sql.Placeholder() * len(values))
                    ),
                    [_adapt(v) for v in values.values()],
                )
            conn.execute("select set_config('app.context', %s, true)", [json.dumps({"via": "migrate_legacy"})])
        _apply_inserts(conn, table, plan.inserts.get(table, []))


def _apply_updates(conn: Connection[Any], table: str, items: list[tuple[str, dict[str, Any]]]) -> None:
    by_set: dict[tuple[str, ...], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for row_id, diff in items:
        by_set[tuple(sorted(diff))].append((row_id, diff))
    for cols, group in by_set.items():
        query = sql.SQL("update public.{} set {} where id = %s").format(
            sql.Identifier(table), sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols)
        )
        with conn.cursor() as cur:
            cur.executemany(query, [[*(_adapt(diff[c]) for c in cols), row_id] for row_id, diff in group])


def _apply_inserts(conn: Connection[Any], table: str, rows: list[dict[str, Any]]) -> None:
    by_cols: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cols[tuple(row)].append(row)
    for cols, group in by_cols.items():
        on_conflict = sql.SQL(" on conflict do nothing") if table == "suppression" else sql.SQL("")
        query = sql.SQL("insert into public.{} ({}) values ({}){}").format(
            sql.Identifier(table), _cols(cols), sql.SQL(", ").join(sql.Placeholder() * len(cols)), on_conflict
        )
        with conn.cursor() as cur:
            cur.executemany(query, [[_adapt(r[c]) for c in cols] for r in group])


def checks(conn: Connection[Any]) -> dict[str, Any]:
    """The verification queries of Step 20.5, in one round trip."""
    row = conn.execute(
        """
        select
          (select count(*) from public.source_records where source = 'legacy')                              as legacy_source_records,
          (select count(*) from public.source_records where source = 'legacy' and business_id is not null)  as legacy_businesses,
          (select count(distinct l.id) from public.leads l join public.source_records r
             on r.business_id = l.business_id and r.source = 'legacy')                                      as legacy_leads,
          (select coalesce(jsonb_object_agg(stage, n), '{}'::jsonb) from
             (select stage, count(*) as n from public.leads where stage <> 'new' group by 1) s)              as stages_beyond_new,
          (select count(*) from public.leads where stage <> 'new' and wa_at = date '2026-11-12')            as worked_with_wa_12_nov,
          (select count(*) from public.leads where message is not null and message_model = 'legacy')         as legacy_messages,
          (select count(*) from public.suppression where reason = 'wrong_contact')                          as suppressed_wrong_contact,
          (select count(*) from public.source_records where source = 'legacy_skip')                        as legacy_skip_rows
        """
    ).fetchone()
    return dict(row) if row else {}
