"""Phone numbers and email addresses: parse, type, find on a page, check (Step 10.3).

Ported from the old engine's `check_links_emails.py` (PHONE_RUN, PHONE_LINK, EMAIL_RE, phone_kind, the
free-mail list) and rebuilt on `phonenumbers`. Only numbers a business published itself are ever used
(A.4.3): this module checks shapes and presence on a page; Step 10 decides which sources are allowed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

import phonenumbers
from phonenumbers import PhoneNumberFormat
from phonenumbers import PhoneNumberType as T

# A run of digits that looks like a phone number in page text, and numbers inside tel: and WhatsApp links.
PHONE_RUN: Final = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().\u2011-]{7,18}\d")
PHONE_LINK: Final = re.compile(r"(?:tel:|wa\.me/|whatsapp\.com/send/?\?phone=)\+?([\d\s().%20-]{8,22})", re.I)

# India: an STD code in brackets, "(080) 4123 4567", or with the trunk 0 and a separator, "022-2345 6789",
# is a landline even when the subscriber digits start with 6 to 9 (phone_kind in the old engine).
# STD codes never start with 9, so "09876 543210" stays a mobile.
_STD_BRACKET: Final = re.compile(r"^\s*(?:\+91[\s-]*)?\(0?\d{2,4}\)[\s-]*\d")
_STD_TRUNK: Final = re.compile(r"^\s*0([1-8]\d{1,3})[\s-]+(\d[\d\s-]{4,10}\d)\s*$")

EMAIL_RE: Final = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
EMAIL_FIND: Final = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
FREEMAIL: Final = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.in",
        "yahoo.in",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "rediffmail.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "zohomail.in",
        "zoho.com",
        "aol.com",
        "gmx.com",
    }
)
# Obfuscations seen in registries and on pages: name[at]clinic[dot]com, name (at) clinic (dot) com.
_AT: Final = re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*|\s+at\s+", re.I)
_DOT: Final = re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*|\s+dot\s+", re.I)
_AT_BRACKETED: Final = re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", re.I)
_DOT_BRACKETED: Final = re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.I)


def region_for(country: str) -> str:
    """phonenumbers region from a segment country code: 'in' -> 'IN'."""
    return country.strip().upper()


def _is_std_landline(raw: str) -> bool:
    if _STD_BRACKET.search(raw):
        return True
    m = _STD_TRUNK.match(raw)
    if not m:
        return False
    subscriber = re.sub(r"\D", "", m.group(2))
    return len(m.group(1)) + len(subscriber) == 10


def parse_phone(raw: str, region: str) -> tuple[str, str] | None:
    """(E.164, phone_type) for a valid number, else None. Types: mobile, landline, tollfree, unknown."""
    text = (raw or "").replace("\u2011", "-").strip()
    if not text:
        return None
    try:
        n = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(n):
        return None
    e164 = phonenumbers.format_number(n, PhoneNumberFormat.E164)
    kind = phonenumbers.number_type(n)
    if kind in (T.TOLL_FREE, T.SHARED_COST):
        return e164, "tollfree"
    if n.country_code == 91 and _is_std_landline(text):
        return e164, "landline"
    if kind == T.MOBILE:
        return e164, "mobile"
    if kind == T.FIXED_LINE:
        return e164, "landline"
    if kind == T.FIXED_LINE_OR_MOBILE:
        national = str(n.national_number)
        if n.country_code == 91:
            return e164, "mobile" if national[:1] in "6789" else "landline"
        if n.country_code == 971:
            return e164, "mobile" if national.startswith("5") else "landline"
        return e164, "unknown"
    return e164, "unknown"


@dataclass(frozen=True)
class PhoneHit:
    """A number found in a text, with its position (for the decision maker proximity rule)."""

    e164: str
    phone_type: str
    start: int
    end: int
    raw: str


def phones_in_text(text: str, region: str) -> Iterator[PhoneHit]:
    """Every valid number in page text, from plain digit runs and from tel: and WhatsApp links."""
    for m in PHONE_RUN.finditer(text or ""):
        parsed = parse_phone(m.group(0), region)
        if parsed:
            yield PhoneHit(parsed[0], parsed[1], m.start(), m.end(), m.group(0))
    for m in PHONE_LINK.finditer(text or ""):
        digits = m.group(1).replace("%20", " ")
        candidate = digits if digits.strip().startswith("+") else f"+{digits.strip()}"
        parsed = parse_phone(candidate, region) or parse_phone(digits, region)
        if parsed:
            yield PhoneHit(parsed[0], parsed[1], m.start(), m.end(), m.group(0))


def snippet(text: str, start: int, end: int, width: int = 40) -> str:
    """About `width` characters around a match, on one line (contacts.quote)."""
    pad = max(0, (width - (end - start)) // 2)
    return re.sub(r"\s+", " ", text[max(0, start - pad) : end + pad]).strip()


def deobfuscate_email(raw: str) -> str:
    """'name [at] clinic [dot] com' -> 'name@clinic.com'. Use on short email strings, not on whole pages."""
    text = _AT.sub("@", (raw or "").strip())
    return _DOT.sub(".", text).replace(" ", "").strip(".,;:").lower()


def emails_in_text(text: str) -> set[str]:
    """Addresses printed in page text, including bracketed obfuscations ([at], (dot))."""
    plain = _DOT_BRACKETED.sub(".", _AT_BRACKETED.sub("@", text or ""))
    return {m.group(0).lower().rstrip(".") for m in EMAIL_FIND.finditer(plain)}


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def is_freemail(email: str) -> bool:
    return email_domain(email) in FREEMAIL


@lru_cache(maxsize=4096)
def mx_exists(domain: str) -> bool | None:
    """True or False when the domain's MX records could be looked up, None when no resolver is available.

    Uses dnspython when installed, else the system `dig`. Never probes SMTP (Step 10.3.5).
    """
    domain = domain.strip().lower().rstrip(".")
    if not domain:
        return False
    try:
        import dns.exception
        import dns.resolver
    except ImportError:
        dig = shutil.which("dig")
        if dig is None:
            return None
        try:
            out = subprocess.run(
                [dig, "+short", "+time=5", "+tries=1", "MX", domain],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        return bool(out.stdout.strip())
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        return len(answers) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except dns.exception.DNSException:
        return None
