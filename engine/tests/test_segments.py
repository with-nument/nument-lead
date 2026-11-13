"""Segment files (Step 3): the six wave-1 markets load, stay inside budgets, and sync to the database."""

from __future__ import annotations

from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

from nument_engine.segments import (
    PACKAGED_OUTCOME,
    REQUIRED_ANGLES,
    SEGMENTS_DIR,
    SegmentConfigError,
    file_hash,
    load_segments,
    load_yaml_config,
    scoring_config,
    sync_segments_to_db,
)

from .helpers import Conn

WAVE1 = {"clinics-in", "realestate-in", "education-in", "clinics-ae", "realestate-ae", "education-ae"}
NEED_FIRST = {"firms-in"}  # the need-first track (13 Nov 2026): businesses come from signals only
# A.13.5 rule 7: the only subcategory and ticket class names.
TICKET_CLASSES = {
    "ivf_fertility", "hair_transplant", "aesthetic", "dermatology", "dental", "physio", "therapy_group",
    "developer", "broker", "property_services", "study_abroad", "coaching_institute", "academy", "tutoring",
    "funded_startup", "smb",
}  # fmt: skip


def _copy_with(tmp_path: Path, seg_id: str, old: str, new: str, file_name: str | None = None) -> Path:
    text = (SEGMENTS_DIR / f"{seg_id}.yaml").read_text()
    assert old in text, old
    (tmp_path / (file_name or f"{seg_id}.yaml")).write_text(text.replace(old, new, 1))
    return tmp_path


# ---- Plan tests (3.8) ------------------------------------------------------


def test_all_segments_load() -> None:
    assert set(load_segments()) == WAVE1 | NEED_FIRST
    firms = load_segments()["firms-in"]
    assert firms.universe == "signals_only" and not firms.overture.categories and firms.packaged_outcome


def test_quotas_fit_research_per_day() -> None:
    assert sum(s.quota.daily_research for s in load_segments().values() if s.enabled) <= 300


def test_places_caps_inside_free_allowance() -> None:
    segs = list(load_segments().values())
    for field in ("details_per_day", "reviews_per_day"):
        india = sum(getattr(s.places, field) for s in segs if s.country == "in")
        abroad = sum(getattr(s.places, field) for s in segs if s.country != "in")
        assert india <= 230 and abroad <= 30, field


def test_every_segment_has_the_angles_step11_picks() -> None:
    for s in load_segments().values():
        assert {a.key for a in s.angles} >= REQUIRED_ANGLES, s.id
        assert s.fit_only_angle() and s.growth_angle()


def test_subcategory_ticket_and_premium_helpers() -> None:
    seg = load_segments()["clinics-in"]
    assert seg.subcategory_for("fertility_clinic") == "ivf_fertility"
    assert seg.subcategory_for(None, "Sunrise IVF and Fertility Centre") == "ivf_fertility"
    assert seg.subcategory_for(None, "City Physiotherapy Centre") == "physio"
    assert seg.ticket_points("ivf_fertility") == 6 and seg.ticket_points(None) == 0
    assert seg.premium_threshold("Consultation fee") == 800
    assert seg.premium_threshold("IVF package") == 20000
    assert seg.is_type_match("dentist", None) and not seg.is_type_match("restaurant", None)


def test_scoring_overrides_merge() -> None:
    base = load_yaml_config("scoring")
    merged = scoring_config(load_segments()["realestate-in"])
    assert merged["can_pay"]["reviews"][-1]["min"] == 30  # segment override
    assert merged["reach"] == base["reach"]  # untouched default


def test_exclusions_file_shape() -> None:
    ex = load_yaml_config("exclusions")
    assert set(ex) == {
        "chains",
        "non_target_keywords",
        "hospital_keywords",
        "agency_keywords",
        "competitors",
        "max_branches",
    }
    assert all(set(c) == {"name", "domains"} for c in ex["chains"])
    assert all(isinstance(k, str) and k == k.lower() for k in ex["non_target_keywords"])


def test_bad_id_is_rejected(tmp_path: Path) -> None:
    bad = (SEGMENTS_DIR / "clinics-in.yaml").read_text().replace("id: clinics-in", "id: clinic-in", 1)
    (tmp_path / "clinic-in.yaml").write_text(bad)
    with pytest.raises(SystemExit):
        load_segments(tmp_path)


# ---- Contract with A.12, A.13.5 and Step 11 --------------------------------


def test_ticket_classes_use_the_a13_5_names() -> None:
    names = {sub for s in load_segments().values() for sub in s.ticket_class}
    assert names == TICKET_CLASSES


def test_registry_subcategories_are_ticket_classes() -> None:
    """A registry stamps its subcategory on every business it finds (A.13.5 rule 7)."""
    for s in load_segments().values():
        for registry in s.registries:
            assert registry.subcategory is None or registry.subcategory in s.ticket_class, (s.id, registry.key)


def test_scoring_defaults_shape() -> None:
    scoring = load_yaml_config("scoring")
    assert scoring["fit"]["gate"] == 2 and set(scoring["fit"]["bonus"]) == {0, 1, 2, 3}
    assert scoring["can_pay"]["cap"] == 30 and scoring["intent"]["cap"] == 35  # s2.0
    assert scoring["can_pay"]["points"] + scoring["intent"]["cap"] + 10 + scoring["total"]["reach_points"] == 100
    assert set(scoring["reach"]) == {"decision_maker_mobile", "business_mobile", "landline", "email", "form", "none"}
    assert scoring["reach"]["none"] == 0 and scoring["fit_only_max_pct"] == 50


def test_each_segment_pitches_its_packaged_outcome() -> None:
    for s in load_segments().values():
        assert s.packaged_outcome == PACKAGED_OUTCOME[s.domain]
        assert s.angle("build_what_they_asked").signals  # Step 11 looks angles up by key


def test_subcategory_order_puts_specific_classes_first() -> None:
    clinics = load_segments()["clinics-in"]
    assert clinics.subcategory_for(None, "Glow Laser and Skin Clinic") == "aesthetic"  # laser beats skin
    assert clinics.subcategory_for("dental_clinic", "Smile Dental") == "dental"
    assert clinics.subcategory_for(None, "Sunrise Bakery") is None
    realestate = load_segments()["realestate-in"]
    assert realestate.ticket_points(realestate.subcategory_for(None, "Skyline Developers")) >= 0


# ---- Invalid files stop the run with a clear message -----------------------


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("packaged_outcome: AI front desk", "packaged_outcome: Websites", "packaged_outcome must be"),
        ("bbox: [76.84, 28.40, 77.35, 28.88]", "bbox: [74.84, 28.40, 77.35, 28.88]", "wider than 2 degrees"),
        ("daily_research: 80", "daily_research: 900", "less than or equal to 300"),
        ('    - "dental clinic in {locality}, {city}"', '    - "dental clinic in {locality}"', "needs {city}"),
        ("signals: [fit_only]", "signals: [news]", "exactly one angle must list fit_only"),
        ("{key: slow_site,", "{key: site_speed,", "missing angles that Step 11 picks"),
        ("  pages_per_day: 120", "  pages_per_day: -1", "greater than or equal to 0"),
        ("  dental:          {match:", "  Dental:          {match:", "lowercase snake_case"),
    ],
)
def test_invalid_segment_files_are_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    _copy_with(tmp_path, "clinics-in", old, new)
    with pytest.raises(SegmentConfigError, match=message):
        load_segments(tmp_path)


def test_file_name_must_match_the_id(tmp_path: Path) -> None:
    _copy_with(tmp_path, "clinics-in", "enabled: true", "enabled: true", file_name="clinics.yaml")
    with pytest.raises(SegmentConfigError, match=r"must be named clinics-in\.yaml"):
        load_segments(tmp_path)


def test_quotas_over_the_daily_research_budget_are_rejected(tmp_path: Path) -> None:
    for seg_id in WAVE1 | NEED_FIRST:
        (tmp_path / f"{seg_id}.yaml").write_text((SEGMENTS_DIR / f"{seg_id}.yaml").read_text())
    with pytest.raises(SegmentConfigError, match="more than research_per_day=200"):
        load_segments(tmp_path, research_per_day=200)


def test_apna_is_india_only(tmp_path: Path) -> None:
    _copy_with(tmp_path, "clinics-ae", "apna: {pages_per_day: 0}", "apna: {pages_per_day: 10}")
    with pytest.raises(SegmentConfigError, match="apna is India only"):
        load_segments(tmp_path)


def test_broken_yaml_is_reported(tmp_path: Path) -> None:
    (tmp_path / "clinics-in.yaml").write_text("id: [unclosed\n")
    with pytest.raises(SegmentConfigError, match="not valid YAML"):
        load_segments(tmp_path)


def test_missing_config_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SegmentConfigError, match="not found"):
        load_yaml_config("scoring", directory=tmp_path)


# ---- Sync to the database (3.2) --------------------------------------------


def test_sync_fills_config_honours_the_switch_and_keeps_the_app_quota(db_conn: Conn) -> None:
    db_conn.execute(
        "update public.settings set value = value || %s where key = 'segments_enabled'",
        [Jsonb({"education-ae": False})],
    )
    segments = load_segments()
    assert sync_segments_to_db(db_conn, segments) == 7
    rows = {
        r["id"]: r
        for r in db_conn.execute(
            "select id, enabled, daily_quota, config, config_version from public.segments"
        ).fetchall()
    }
    assert rows["education-ae"]["enabled"] is False and rows["clinics-in"]["enabled"] is True
    assert rows["clinics-in"]["config"]["packaged_outcome"] == "AI front desk"
    assert rows["clinics-in"]["config_version"] == file_hash(SEGMENTS_DIR / "clinics-in.yaml")
    # The founder changes a quota in the app; the next sync must keep it (A.13.5 rule 11).
    db_conn.execute("update public.segments set daily_quota = 25 where id = 'clinics-in'")
    sync_segments_to_db(db_conn, segments)
    assert db_conn.execute("select daily_quota from public.segments where id = 'clinics-in'").fetchone() == {
        "daily_quota": 25
    }
    assert db_conn.execute("select count(*) as n from public.segments").fetchone() == {"n": 7}


def test_sync_inserts_a_new_segment_with_its_file_quota(db_conn: Conn) -> None:
    segments = load_segments()
    db_conn.execute("delete from public.segments where id = 'education-ae'")
    sync_segments_to_db(db_conn, {"education-ae": segments["education-ae"]})
    assert db_conn.execute("select daily_quota from public.segments where id = 'education-ae'").fetchone() == {
        "daily_quota": segments["education-ae"].quota.daily_research
    }
