"""WhatsApp links (Step 12.10). Built when shown, never stored, so a phone fix updates them at once.

The web app builds the same links in TypeScript with `encodeURIComponent`; the sheet push uses these.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import quote

_E164: Final = re.compile(r"^\+[1-9]\d{6,14}$")


def wa_digits(e164: str) -> str:
    """The number without the plus sign, as wa.me wants it: '+919876543210' -> '919876543210'."""
    if not _E164.match(e164 or ""):
        raise ValueError(f"not an E.164 number: {e164!r}")
    return e164[1:]


def wa_links(e164: str, message: str) -> dict[str, str]:
    """`web` opens WhatsApp Web on a desktop, `app` opens the phone app. Line breaks become %0A."""
    digits = wa_digits(e164)
    text = quote(message or "", safe="")
    return {
        "web": f"https://web.whatsapp.com/send?phone={digits}&text={text}",
        "app": f"https://wa.me/{digits}?text={text}",
    }


def can_whatsapp(contact: Mapping[str, Any] | None, suppressed_phones: frozenset[str] = frozenset()) -> bool:
    """Only a mobile that is not do-not-contact and not suppressed gets a WhatsApp link."""
    if not contact or not contact.get("phone_e164"):
        return False
    return (
        contact.get("phone_type") == "mobile"
        and not contact.get("do_not_contact")
        and contact["phone_e164"] not in suppressed_phones
    )
