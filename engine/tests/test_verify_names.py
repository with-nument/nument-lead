"""The listing's name and the site's own name must mean the same business (13 Nov 2026)."""

from __future__ import annotations

import pytest

from nument_engine.pipeline.verify import names_match


@pytest.mark.parametrize(
    ("listing", "site", "domain", "expected"),
    [
        ("Ipromise English Speaking", "BM English Speaking", "bmconsultantsindia.com", False),
        ("Cosmodentindia", "Cosmodent India", "cosmodentindia.com", True),
        ("Clear Skin - Baner", "Clear Skin", "clearskin.in", True),
        ("Magnum VIP Dental Clinic - Arjan", "Magnum Dental Clinic", "magnumclinic.ae", True),
        ("Dr. Sharma's Dental Clinic", "Sharma Dental Care", "sharmadental.in", True),
        ("Smile Dental Clinic", "Dental Clinic", "smile.in", True),  # nothing distinctive left: cannot judge
        ("Apex Fertility Centre", "Nova IVF Fertility", "novaivf.com", False),
        ("Sunrise Skin Clinic", "The Sunrise Clinic", None, True),
    ],
)
def test_names_match(listing: str, site: str, domain: str | None, expected: bool) -> None:
    assert names_match(listing, site, domain, ["Pune", "Baner", "Dubai", "Arjan", "Gurugram"]) is expected
