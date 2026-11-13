"""Pain research already finds becomes signals: careers-page roles and education's low-ticket names (13 Nov 2026)."""

from __future__ import annotations

from typing import Any

import pytest

from nument_engine.models import FactsExtraction
from nument_engine.pipeline import extract
from nument_engine.segments import load_segments


def test_careers_page_roles_become_hiring_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract.db, "scalar", lambda *_a, **_k: "brightminds.ae")
    url = "https://brightminds.ae/careers"
    facts = FactsExtraction.model_validate(
        {
            "careers_roles": [
                {"title": "Front Desk Executive", "category": "frontdesk", "quote": "Front Desk Executive", "url": url},
                {"title": "front desk executive", "category": "frontdesk", "quote": "front desk executive", "url": url},
                {"title": "Full Stack Developer", "category": "builder", "quote": "Full Stack Developer", "url": url},
                {"title": "Physics Teacher", "category": "other", "quote": "Physics Teacher wanted", "url": url},
            ]
        }
    )
    sigs = extract.hiring_signals("b1", facts)
    assert [(s.type, s.details["role"]) for s in sigs] == [
        ("hiring_frontdesk", "Front Desk Executive"),
        ("hiring_builder", "Full Stack Developer"),
    ]
    first: Any = sigs[0]
    assert first.url == url and first.quote == "Front Desk Executive" and first.business_id == "b1"
    assert first.evidence_key.startswith("brightminds.ae|front desk executive|")


@pytest.mark.parametrize(
    ("name", "excluded"),
    [
        ("Ipromise English Speaking", "english speaking"),
        ("Sharma Tuition Classes", "tuition"),
        ("Little Stars Play School", "play school"),
        ("Aakash Institute JEE NEET", None),
        ("Leverage Edu Study Abroad", None),
    ],
)
def test_education_targets_high_ticket_only(name: str, excluded: str | None) -> None:
    seg = load_segments()["education-in"]
    assert seg.fit.excludes_name(name) == excluded
    assert "tutoring_service" not in seg.fit.categories and "language_school" not in seg.fit.categories


def test_old_website_signs_from_the_home_page() -> None:
    """13 Nov 2026: slow_site without a PageSpeed key, from the home page research already reads."""
    from nument_engine.research.techstack import site_issues

    modern = '<html><head><meta name="viewport" content="width=device-width"></head><body>&copy; 2026 Acme</body>'
    assert site_issues("https://acme.co.uk/", modern, 2026) == []
    old = (
        '<html><head><meta name="generator" content="WordPress 4.9.8">'
        '<script src="/js/jquery-1.11.3.min.js"></script></head><body>Copyright © 2017 - 2019 Acme</body>'
    )
    assert site_issues("http://acme.co.uk/", old, 2026) == [
        "no mobile layout (no viewport tag)",
        "no HTTPS",
        "copyright 2019",
        "jQuery 1.x",
        "WordPress 4.9",
    ]
    assert site_issues("https://acme.co.uk/", "", 2026) == []


@pytest.mark.parametrize(
    ("issues", "signal"),
    [
        (["no mobile layout (no viewport tag)"], True),
        (["copyright 2018"], True),
        (["jQuery 1.x"], False),  # common on fine sites: not enough alone
        (["jQuery 1.x", "WordPress 4.9"], True),
        ([], False),
    ],
)
def test_old_site_signal_needs_one_strong_or_two_reasons(
    monkeypatch: pytest.MonkeyPatch, issues: list[str], signal: bool
) -> None:
    row = {"web_domain": "acme.co.uk", "tech": {"site_issues": issues, "site_issues_url": "https://acme.co.uk/"}}
    monkeypatch.setattr(extract.db, "fetch_one", lambda *a, **k: row)
    sig = extract.old_site_signal("b1")
    assert (sig is not None) == signal
    if sig is not None:
        assert sig.type == "slow_site" and sig.quote is not None and sig.quote.startswith("Their website: ")
        assert sig.evidence_key.startswith("acme.co.uk|old_site|")
