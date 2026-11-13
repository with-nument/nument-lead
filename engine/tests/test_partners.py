"""The partner track (13 Nov 2026): marketing and design agencies are white-label partners, not competitors.
Software, app and IT shops, staffing and recruitment firms stay excluded everywhere."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from nument_engine.models import LeadJudgement
from nument_engine.pipeline import judge, verify
from nument_engine.pipeline.prefilter import Exclusions as PrefilterExclusions
from nument_engine.pipeline.prefilter import World, apply_rules
from nument_engine.pipeline.verify import Bundle
from nument_engine.pipeline.verify import Exclusions as VerifyExclusions
from nument_engine.segments import load_segments

from .pipeline_fakes import NOW

SEGS = load_segments()
PARTNERS = SEGS["partners-gb"]
CLINICS = SEGS["clinics-in"]
VEXCL = VerifyExclusions.load()
PEXCL = PrefilterExclusions.load()


def business(**kw: Any) -> dict[str, Any]:
    return {
        "id": "b1",
        "segment_id": "partners-gb",
        "name": "Bloom Digital Marketing Agency",
        "norm_name": "bloom digital marketing agency",
        "website": "https://bloomcreative.co.uk/",
        "web_domain": "bloomcreative.co.uk",
        "city": "London",
        "category": "marketing_agency",
        "subcategory": None,
        "branches_count": None,
        "review_count": 40,
        "places_fetched_at": NOW - timedelta(days=3),
        "status": "candidate",
        "researched_at": None,
        "queued_at": None,
        "extra": {},
        **kw,
    }


def test_prefilter_keeps_marketing_agencies_only_in_partner_segments() -> None:
    w = World()
    assert apply_rules(business(), PARTNERS, PEXCL, w, NOW) == ("pass", None)
    software = business(name="Bloom Software Development Studio")
    assert apply_rules(software, PARTNERS, PEXCL, w, NOW) == ("reject", "R4_agency")
    clinic_side = business(segment_id="clinics-in", city="Pune", category="dermatology")
    assert apply_rules(clinic_side, CLINICS, PEXCL, w, NOW)[1] == "R4_agency"


def page(text: str) -> dict[str, Any]:
    return {"id": "p1", "url": "https://bloomcreative.co.uk/", "text": text}


def bundle(text: str, segment_id: str = "partners-gb") -> Bundle:
    b = business(segment_id=segment_id)
    return Bundle(business=b, pages=[page(text)], facts=[], signals=[], contacts=[], records=[])


def test_competitor_signs_differ_for_partners() -> None:
    marketing = "Bloom is a digital marketing agency. We build websites and brands for growing companies."
    assert verify.competitor_hints(bundle(marketing), [], VEXCL) == []
    assert verify.competitor_hints(bundle(marketing, "clinics-in"), [], VEXCL)  # elsewhere it is a competitor
    dev_shop = "Bloom is a software development company and IT services partner."
    assert verify.competitor_hints(bundle(dev_shop), [], VEXCL)
    assert VEXCL.competitor_match(["Bloom SEO Agency"], None, partner=True) is None
    assert VEXCL.competitor_match(["Bloom IT Services"], None, partner=True) is not None


def judgement(grade: str, risks: list[str]) -> LeadJudgement:
    return LeadJudgement(
        judge_grade=grade,  # type: ignore[arg-type]
        judge_note="note",
        best_angle="white_label_team",
        cited_ids=["F1"],
        risks=risks,
        confidence=0.9,
    )


def test_the_judge_never_drops_a_partner_for_being_an_agency() -> None:
    agency = judgement("D", ["it is a marketing agency"])
    assert judge.adjustment("B", agency, cited=0, total=60) == -21  # elsewhere: below 40, so D
    assert judge.adjustment("B", agency, cited=0, total=60, partner=True) == -15  # partners: a lower grade only
    dev_shop = judgement("D", ["a software agency, a competitor"])
    assert judge.adjustment("B", dev_shop, cited=0, total=60, partner=True) == -21  # below 40: D
    assert judge.adjustment("A", agency, cited=0, total=80) == -41  # elsewhere an agency is a disqualifier
    assert judge.adjustment("A", agency, cited=0, total=80, partner=True) == -15
