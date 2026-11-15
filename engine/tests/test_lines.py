"""Who answers a published number (15 Nov 2026). The cases are the first India and UAE leads the founder sent:
"most of them are not personal numbers, they are automation numbers"."""

from __future__ import annotations

from typing import Any

import pytest

from nument_engine.pipeline import lines
from nument_engine.pipeline.lines import classify_email, classify_phone, plan_lines


@pytest.mark.parametrize(
    ("e164", "kind", "quote", "label", "kw", "line"),
    [
        # the green WhatsApp chat button: a receptionist or an auto-reply
        ("+971504162866", "mobile", "wa.me/971504162866", None, {}, "front_desk"),
        # the number in the site's schema data is the business line
        ("+971544522332", "mobile", '{"telephone":"+971544522332"}', None, {}, "front_desk"),
        # an emergency line next to the doctor's name is still not the doctor's own phone
        ("+971566244491", "mobile", "Emergency: +971 56 624 4491 Jumeirah Branch", "Dr. Aburas",
         {"tied_to_person": True}, "front_desk"),
        # a UAE clinic with a Russian number
        ("+79854502323", "mobile", "tel:+7 (985) 450-23-23", None, {}, "bot"),
        # a UAE 600 helpline
        ("+971600578336", "unknown", "helpline at 6005 78336", None, {}, "bot"),
        # the chat button of a site that runs a WhatsApp bot vendor
        ("+919876543210", "mobile", "wa.me/919876543210", None, {"has_whatsapp_vendor": True}, "bot"),
        # three or more businesses publish it: a call centre or an agency
        ("+919876543210", "mobile", "Call 98765 43210", None, {"shared_with": 2}, "bot"),
        # printed on every page of the site
        ("+919876543210", "mobile", "Call 98765 43210", None, {"pages_with_number": 5}, "front_desk"),
        # the founder's own mobile, on the team page only, next to her name
        ("+919876543210", "mobile", "Dr. Asha Rao, Founder: +91 98765 43210", "Dr. Asha Rao",
         {"tied_to_person": True, "pages_with_number": 1}, "owner"),
        # a plain mobile on the contact page: nothing says who answers
        ("+919876543210", "mobile", "98765 43210", None, {"pages_with_number": 1}, "other"),
        ("+914022334455", "landline", "040 2233 4455", None, {}, "front_desk"),
    ],
)  # fmt: skip
def test_who_answers_a_number(
    e164: str, kind: str, quote: str, label: str | None, kw: dict[str, Any], line: str
) -> None:
    country = "ae" if e164.startswith(("+971", "+7")) else "in"
    got, why = classify_phone(e164, kind, quote, label, seg_country=country, **kw)
    assert got == line and why


def test_who_reads_an_address() -> None:
    assert classify_email("asha@sunrisedental.in", tied_to_person=True)[0] == "owner"
    assert classify_email("appointments@sunrisedental.in", tied_to_person=False)[0] == "front_desk"
    assert classify_email("info@sunrisedental.in", tied_to_person=False)[0] == "front_desk"
    assert classify_email("drasharao@gmail.com", tied_to_person=False, free_mail=True)[0] == "other"


def row(**kw: Any) -> dict[str, Any]:
    base = {"id": "c1", "business_id": "b1", "phone_type": "mobile", "email": None, "name": None, "role": None,
            "quote": None, "source": "website", "is_decision_maker": False, "line": "other", "line_why": None,
            "country": "in", "seg_country": "in"}  # fmt: skip
    return {**base, **kw}


def test_a_desk_number_next_to_the_owner_stops_counting_as_the_owner() -> None:
    """The live bug: within 120 characters of the doctor's name meant "decision maker", even for the header
    number. Now that row keeps the name but is the front desk, and is no longer the owner's line."""
    contacts = [
        row(id="c1", phone_e164="+919584584111", quote="tel:9584584111", is_decision_maker=True, name="Dr. Rao"),
        row(id="c2", phone_e164="+919876543210", quote="Dr. Rao, Founder: +91 98765 43210", is_decision_maker=True,
            name="Dr. Rao"),
        row(id="c3", phone_e164=None, email="info@clearskin.in", quote="info@clearskin.in"),
    ]  # fmt: skip
    pages = {"b1": ["Call 9584584111 to book", "Book: 9584584111", "Clinic 9584584111", "Dr. Rao 98765 43210"]}
    got = {u["id"]: u for u in plan_lines(contacts, pages, {}, {})}
    assert got["c1"]["line"] == "front_desk" and got["c1"]["dm"] is False
    assert got["c2"]["line"] == "owner" and got["c2"]["dm"] is True
    assert got["c3"]["line"] == "front_desk"
    assert lines.region_of("+971504162866") == "ae" and lines.same_country("+447700900123", "uk")
