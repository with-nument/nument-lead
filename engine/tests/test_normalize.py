"""Normalisation (Step 6.5): the table of 6.5.5 plus the cases the real data showed."""

from __future__ import annotations

import pytest

from nument_engine.normalize import (
    canonical_url,
    city_for,
    city_for_text,
    decode_email,
    emails_in_text,
    homepage,
    is_free_builder,
    locality_for,
    match_key,
    meters,
    norm_name,
    phone,
    phones_in_text,
    web_domain,
)

CITIES = [
    {"name": "Delhi", "aliases": ["New Delhi", "NCT of Delhi"], "bbox": [76.84, 28.40, 77.35, 28.88]},
    {"name": "Gurugram", "aliases": ["Gurgaon"], "bbox": [76.95, 28.38, 77.12, 28.53]},
    {"name": "Mumbai", "aliases": ["Bombay", "Mumbai Suburban"], "bbox": [72.77, 18.89, 72.99, 19.30]},
    {
        "name": "Thane and Navi Mumbai",
        "aliases": ["Thane", "Navi Mumbai", "New Bombay"],
        "bbox": [72.95, 18.98, 73.10, 19.30],
    },
    {"name": "Pune", "aliases": ["Pimpri Chinchwad", "PCMC"], "bbox": [73.70, 18.40, 74.05, 18.70]},
]


def test_norm_name_and_match_key() -> None:
    assert norm_name("Dr. Sharma's Skin & Hair Clinic Pvt. Ltd.") == "dr sharma s skin and hair clinic"
    assert norm_name("Smile Dental LLP") == "smile dental"
    assert norm_name("Gulf Smile FZ LLC") == "gulf smile"
    assert norm_name("डॉ. शर्मा क्लिनिक") == "डॉ शर्मा क्लिनिक"
    assert match_key("The Smile Dental Clinic") == "dental smile"
    assert match_key("Clinic") == ""


@pytest.mark.parametrize(
    ("url", "domain", "home"),
    [
        ("https://www.practo.com/delhi/clinic/x", None, None),
        ("https://drx.wixsite.com/home", "drx.wixsite.com", "https://drx.wixsite.com/"),
        ("https://www.example.co.in/about?utm_source=x", "example.co.in", "https://example.co.in/"),
        ("example.com", "example.com", "https://example.com/"),
        ("https://abc.business.site/", "abc.business.site", "https://abc.business.site/"),
        (
            "https://sites.google.com/view/DrSharma/home",
            "sites.google.com/view/drsharma",
            "https://sites.google.com/view/drsharma/",
        ),
        ("https://m.facebook.com/clinic", None, None),
        ("https://www.google.com/maps/place/x", None, None),
        ("https://linktr.ee/clinic", None, None),
        ("https://wixsite.com", None, None),
        ("", None, None),
    ],
)
def test_web_domain_and_homepage(url: str, domain: str | None, home: str | None) -> None:
    assert web_domain(url) == domain
    assert homepage(url) == home


def test_free_builders() -> None:
    assert is_free_builder("drx.wixsite.com") and is_free_builder("abc.business.site")
    assert is_free_builder("sites.google.com/view/x")
    assert not is_free_builder("drsharma.in") and not is_free_builder(None)


@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        ("098100 12345", "IN", ("+919810012345", "mobile")),
        ("011 4567 8901", "IN", ("+911145678901", "landline")),
        ("1800 123 4567", "IN", ("+9118001234567", "tollfree")),
        ("(080) 4123 4567", "IN", ("+918041234567", "landline")),
        ("020 2551 1111", "IN", ("+912025511111", "landline")),
        ("+91 98765 43210", "IN", ("+919876543210", "mobile")),
        ("04 331 4567", "AE", ("+97143314567", "landline")),  # Dubai landline (verified at build)
        ("+971 50 123 4567", "AE", ("+971501234567", "mobile")),
        ("800 123456", "AE", ("+971800123456", "tollfree")),
        ("12345", "IN", None),
        ("", "IN", None),
    ],
)
def test_phone(raw: str, region: str, expected: tuple[str, str] | None) -> None:
    assert phone(raw, region) == expected


def test_phones_and_emails_in_text() -> None:
    text = "Call +91 98765 43210 or (020) 2551 1111, fax 020-25511112. Mail hello@clinic.in, Hello@Clinic.in."
    assert phones_in_text(text, "IN") == [
        ("+919876543210", "mobile"),
        ("+912025511111", "landline"),
        ("+912025511112", "landline"),
    ]
    assert emails_in_text(text) == ["hello@clinic.in"]


def test_decode_obfuscated_emails() -> None:
    assert decode_email("mfc[dot]fertility[at]gmail[dot]com") == "mfc.fertility@gmail.com"
    assert decode_email("dr.x (at) clinic (dot) in") == "dr.x@clinic.in"
    assert decode_email("Info@Clinic.IN") == "info@clinic.in"
    assert decode_email("not an email") is None


def test_canonical_url() -> None:
    assert (
        canonical_url("https://WWW.Example.com/Contact-Us/?utm_source=a&b=1#top")
        == "https://example.com/Contact-Us?b=1"
    )
    assert canonical_url("http://example.com:80/") == "http://example.com/"
    assert canonical_url("https://example.com/a?fbclid=1&gclid=2") == "https://example.com/a"


def test_city_for_points_prefers_the_most_specific_box() -> None:
    assert city_for(28.46, 77.03, "", CITIES) == "Gurugram"  # inside both Delhi and Gurugram boxes
    assert city_for(28.46, 77.03, "Vasant Kunj, New Delhi", CITIES) == "Delhi"  # the address decides
    assert city_for(28.70, 77.20, "", CITIES) == "Delhi"
    assert city_for(10.0, 10.0, "", CITIES) is None


@pytest.mark.parametrize(
    ("text", "city"),
    [
        ("Plot 4, Vashi, Navi Mumbai 400703", "Thane and Navi Mumbai"),  # not Mumbai: longest alias wins
        ("Andheri West, Mumbai", "Mumbai"),
        ("navi-mumbai", "Thane and Navi Mumbai"),  # Apna city slugs
        ("delhi-ncr", "Delhi"),
        ("gurgaon-gurugram", "Gurugram"),
        ("pune-region", "Pune"),
        ("Punerwadi village", None),  # whole words only
        ("", None),
    ],
)
def test_city_for_text(text: str, city: str | None) -> None:
    assert city_for_text(text, CITIES) == city


def test_locality_and_distance() -> None:
    assert locality_for("Shop 2, Baner Road, Baner, Pune", ["Baner", "Aundh", "Baner Road"]) == "Baner Road"
    assert locality_for("Kothrud", ["Baner"]) is None
    assert 1100 < meters(18.5, 73.8, 18.51, 73.8) < 1120


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://eka.care/doctor/dr-vamsi-krishna-dentist", None),  # a health directory, not their site
        ("https://www.whitecoats.com/swastik-dental-care", None),
        ("https://wix.com", None),  # the builder itself
        ("https://smileavenue.icareheal.com/", "smileavenue.icareheal.com"),  # a site on a builder: the host
        ("https://impressionsdental.ueniweb.com/", "impressionsdental.ueniweb.com"),
        ("https://www.signaturesmiles.in/", "signaturesmiles.in"),
    ],
)
def test_platform_pages_are_not_a_clinic_website(url: str, expected: str | None) -> None:
    assert web_domain(url) == expected
