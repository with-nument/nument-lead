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
