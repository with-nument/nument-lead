"""Who answers a published number or address (founder, 15 Nov 2026).

"Most of them are not personal numbers, they are automation numbers." The first 33 India and UAE leads proved
it: nearly every number was the clinic's front desk (the green WhatsApp chat button, a booking or emergency
line, the number in the site header and in its schema data), answered by an auto-reply and then a receptionist.
The three marked "decision maker" were wrong too: an emergency line and a header number sat within 120
characters of the doctor's name. Each contact now gets a line:

- ``owner``: tied to the owner, founder or doctor in charge on the page (their name next to it, or the page's
  own label names them) and nothing says it is a shared line: not a booking or reception label, not the chat
  button, not the site-wide number, a mobile.
- ``front_desk``: a reception, booking, enquiry, emergency or "call us" label, the WhatsApp chat button, the
  number in the site's schema data, a number printed on three or more of its pages, a landline, or an address
  such as info@ or appointments@.
- ``bot``: the WhatsApp button of a site that runs a WhatsApp API vendor (AiSensy, Wati, Interakt...), a
  toll-free, 600 or helpline number, a number other businesses publish too (a call centre or an agency), or a
  number registered in another country than the business.
- ``other``: a business mobile or address with nothing that says who answers (in a small business it is often
  the owner).

Nothing here guesses a number or an address: it only describes the ones the business published (A.4.3).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, Literal

import phonenumbers
from psycopg import Connection

from .. import db
from ..logging import get_logger
from .phones import phones_in_text

log = get_logger()

Line = Literal["owner", "front_desk", "bot", "other"]
LINES: Final[tuple[str, ...]] = ("owner", "front_desk", "bot", "other")

DESK_WORDS: Final = re.compile(
    r"\b(?:reception|front\s*(?:desk|office)|appointments?|booking|book\s+(?:an?\s+)?(?:appointment|consultation|"
    r"visit|slot)|enquir(?:y|ies)|inquir(?:y|ies)|emergenc(?:y|ies)|customer\s+(?:care|service|support)|"
    r"help\s*desk|contact\s+us|call\s+us|whatsapp\s+us|chat\s+with\s+us|admissions?|main\s+line|hotline|"
    r"general\s+(?:line|enquir)|office|clinic\s+(?:number|phone|line))\b",
    re.I,
)
BOT_WORDS: Final = re.compile(r"\b(?:helpline|toll[\s-]?free|call\s*cent(?:re|er)|ivr)\b", re.I)
CHAT_BUTTON: Final = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send|web\.whatsapp\.com/send|whatsapp\.com/send)", re.I)
SCHEMA_PHONE: Final = re.compile(r'"telephone"', re.I)
GENERIC_LOCAL: Final = re.compile(
    r"^(?:info|contact|contactus|hello|hi|admin|enquir(?:y|ies)|inquir(?:y|ies)|support|help|reception|"
    r"appointments?|booking|bookings|care|office|mail|team|sales|frontdesk|front\.?desk|clinic|enquiry|"
    r"admissions?|customercare|service|services|connect|query|queries|noreply|no-reply)[0-9._-]*@",
    re.I,
)
SITE_WIDE_PAGES: Final = 3  # printed on this many of its own pages: the site's general number


def region_of(e164: str) -> str | None:
    """The country a number is registered in, lower case ("in", "ae", "gb"), or None."""
    try:
        code = phonenumbers.region_code_for_number(phonenumbers.parse(e164, None))
    except phonenumbers.NumberParseException:
        return None
    return code.lower() if code else None


def same_country(e164: str, seg_country: str) -> bool:
    region = region_of(e164)
    want = "gb" if seg_country.lower() == "uk" else seg_country.lower()
    return region is None or region == want


def classify_phone(
    e164: str,
    phone_type: str,
    quote: str | None,
    label: str | None,
    *,
    seg_country: str,
    pages_with_number: int = 0,
    has_whatsapp_vendor: bool = False,
    shared_with: int = 0,
    tied_to_person: bool = False,
) -> tuple[Line, str]:
    """(line, why) for one published number. `tied_to_person`: the page prints it next to the owner's name."""
    text = f"{quote or ''} {label or ''}"
    if not same_country(e164, seg_country):
        return "bot", f"registered in another country ({(region_of(e164) or '?').upper()})"
    if phone_type == "tollfree" or (e164.startswith("+9716") and len(e164) <= 13) or BOT_WORDS.search(text):
        return "bot", "a toll-free, 600 or helpline number"
    if shared_with >= 2:
        return "bot", f"{shared_with + 1} businesses publish this number: a call centre or an agency"
    button = bool(CHAT_BUTTON.search(quote or ""))
    if button and has_whatsapp_vendor:
        return "bot", "the WhatsApp button of a site that runs a WhatsApp bot vendor"
    desk_label = bool(DESK_WORDS.search(text))
    site_wide = pages_with_number >= SITE_WIDE_PAGES
    schema = bool(SCHEMA_PHONE.search(quote or ""))
    if tied_to_person and phone_type == "mobile" and not (desk_label or button or site_wide or schema):
        return "owner", "printed next to the owner's name, not as the clinic or office line"
    if desk_label:
        return "front_desk", "labelled as a reception, booking, enquiry or emergency line"
    if button:
        return "front_desk", "the WhatsApp chat button on their site"
    if schema:
        return "front_desk", "the business number in their site's listing data"
    if site_wide:
        return "front_desk", f"the site-wide number (on {pages_with_number} of their pages)"
    if shared_with == 1:
        return "front_desk", "another listing or branch publishes the same number"
    if phone_type == "landline":
        return "front_desk", "a landline"
    if tied_to_person:
        return "front_desk", "near the owner's name but used as the business line"
    return "other", "a business mobile; nothing says who answers"


def classify_email(email: str, *, tied_to_person: bool, free_mail: bool = False) -> tuple[Line, str]:
    if tied_to_person:
        return "owner", "the owner's own address"
    if GENERIC_LOCAL.match(email or ""):
        return "front_desk", "a shared inbox (info@, contact@, appointments@ ...)"
    if free_mail:
        return "other", "a free-mail address on their site; in a small business often the owner's"
    return "other", "a business address; nothing says who reads it"


# ---------------------------------------------------------------------------------------------------
# Refresh stored contacts (end of verify, and once for every business: `nlead lines`)
# ---------------------------------------------------------------------------------------------------

CONTACTS_SQL: Final = """
select c.id::text as id, c.business_id::text as business_id, c.phone_e164, c.phone_type, c.email, c.name, c.role,
       c.quote, c.source, c.is_decision_maker, c.line, c.line_why, b.country, s.country as seg_country
  from public.contacts c
  join public.businesses b on b.id = c.business_id
  left join public.segments s on s.id = b.segment_id
 where c.business_id = any(%(ids)s::uuid[])
"""
PAGES_SQL: Final = """
select business_id::text as business_id, text from public.pages
 where business_id = any(%(ids)s::uuid[]) and text is not null
"""
TOOLS_SQL: Final = """
select distinct on (business_id) business_id::text as business_id, value from public.facts
 where business_id = any(%(ids)s::uuid[]) and field = 'tech_stack' and model in ('rule', 'code')
 order by business_id, created_at desc
"""
SHARED_SQL: Final = """
select phone_e164, count(distinct business_id) - 1 as others from public.contacts
 where phone_e164 = any(%(phones)s) group by phone_e164 having count(distinct business_id) > 1
"""


def _has_vendor(tech: Any) -> bool:
    tools = tech.get("tools") if isinstance(tech, dict) else tech
    return any(isinstance(t, dict) and t.get("kind") == "whatsapp_vendor" for t in tools or [])


def plan_lines(
    contacts: Sequence[Mapping[str, Any]],
    pages_by_business: Mapping[str, Sequence[str]],
    vendor: Mapping[str, bool],
    shared: Mapping[str, int],
) -> list[dict[str, Any]]:
    """The update for each contact: {id, line, line_why, is_decision_maker}. A number the page ties to the
    owner but that is really the business line stops counting as the owner's (its name stays on the row)."""
    region_by_business = {
        str(c["business_id"]): str(c.get("seg_country") or c.get("country") or "in").upper().replace("UK", "GB")
        for c in contacts
    }
    counts: dict[str, Counter[str]] = {}
    for bid, texts in pages_by_business.items():
        c: Counter[str] = Counter()
        for text in texts:
            c.update({hit.e164 for hit in phones_in_text(text, region_by_business.get(bid, "IN"))})
        counts[bid] = c
    out = []
    for row in contacts:
        bid = str(row["business_id"])
        country = str(row.get("seg_country") or row.get("country") or "in")
        tied = bool(row.get("is_decision_maker"))
        if row.get("phone_e164"):
            e164 = str(row["phone_e164"])
            line, why = classify_phone(
                e164,
                str(row.get("phone_type") or "unknown"),
                row.get("quote"),
                row.get("role"),
                seg_country=country,
                pages_with_number=counts.get(bid, Counter()).get(e164, 0),
                has_whatsapp_vendor=vendor.get(bid, False),
                shared_with=int(shared.get(e164, 0)),
                tied_to_person=tied and row.get("source") == "website",
            )
        elif row.get("email"):
            line, why = classify_email(
                str(row["email"]), tied_to_person=tied, free_mail="free mail" in str(row.get("role") or "")
            )
        else:  # a name-only decision maker: no line to answer
            line, why = ("owner", "a named decision maker without a published number") if tied else ("other", "")
        dm = tied and (line == "owner" or not (row.get("phone_e164") or row.get("email")))
        if line != row.get("line") or why != row.get("line_why") or dm != tied:
            out.append({"id": row["id"], "line": line, "line_why": why or None, "dm": dm})
    return out


def refresh(business_ids: Iterable[str], conn: Connection[Any] | None = None) -> Counter[str]:
    """Classify every contact of these businesses and store the result."""
    ids = sorted({str(b) for b in business_ids})
    stats: Counter[str] = Counter()
    if not ids:
        return stats
    contacts = db.fetch_all(CONTACTS_SQL, {"ids": ids}, conn=conn)
    pages: dict[str, list[str]] = defaultdict(list)
    for p in db.fetch_all(PAGES_SQL, {"ids": ids}, conn=conn):
        pages[p["business_id"]].append(p["text"] or "")
    vendor = {r["business_id"]: _has_vendor(r["value"]) for r in db.fetch_all(TOOLS_SQL, {"ids": ids}, conn=conn)}
    phones = sorted({str(c["phone_e164"]) for c in contacts if c.get("phone_e164")})
    shared = (
        {r["phone_e164"]: int(r["others"]) for r in db.fetch_all(SHARED_SQL, {"phones": phones}, conn=conn)}
        if phones
        else {}
    )
    updates = plan_lines(contacts, pages, vendor, shared)
    for u in updates:
        db.execute(
            "update public.contacts set line = %s, line_why = %s, is_decision_maker = %s where id = %s",
            [u["line"], u["line_why"], u["dm"], u["id"]],
            conn=conn,
        )
    stats["contacts"] = len(contacts)
    for u in updates:
        stats[f"line.{u['line']}"] += 1
    stats["changed"] = len(updates)
    return stats


def refresh_all(batch: int = 500) -> Counter[str]:
    """`nlead lines`: every business that has a contact (run once after migration 0018)."""
    stats: Counter[str] = Counter()
    ids = [r["id"] for r in db.fetch_all("select distinct business_id::text as id from public.contacts")]
    for start in range(0, len(ids), batch):
        with db.tx("engine", {"stage": "lines"}) as conn:
            stats.update(refresh(ids[start : start + batch], conn=conn))
    log.info("lines.refreshed", **{k.replace(".", "_"): v for k, v in stats.items()})
    return stats
