"""Scoring weights document (Step 16.3): defaults, completion, overlays for scoring, and the diff."""

from __future__ import annotations

import importlib

import pytest

from nument_engine import db
from nument_engine.learn import weights as w
from nument_engine.models import SIGNAL_TYPES
from nument_engine.segments import Segment, load_segments, scoring_config

from .helpers import Conn


@pytest.fixture(scope="module")
def segments() -> dict[str, Segment]:
    return load_segments()


def test_default_points_match_the_contract_and_the_signals_stage() -> None:
    assert set(w.DEFAULT_SIGNAL_POINTS) == set(SIGNAL_TYPES)
    assert w.DEFAULT_SIGNAL_POINTS["public_ask"] == 10 and w.DEFAULT_SIGNAL_POINTS["funding"] == 0
    stage_points = getattr(importlib.import_module("nument_engine.pipeline.signals"), "DEFAULT_POINTS", None)
    if stage_points is not None:  # Step 7 keeps the same A.12.3 table
        assert {k: float(v) for k, v in stage_points.items()} == w.DEFAULT_SIGNAL_POINTS


def test_proxy_keys_follow_the_scoring_tiers(segments: dict[str, Segment]) -> None:
    cfg = scoring_config(segments["clinics-in"])
    points = w.can_pay_points_of(cfg)
    assert points["branches_2plus"] == 6 and points["branches_4plus"] == 8 and points["reviews_300plus"] == 6
    assert points["pays_for_software"] == 3 and points["funding"] == 6
    tiers = w.proxy_tiers(cfg)
    assert w.proxies_for_counts(tiers, branches=5, staff=3, reviews=99) == ["branches_4plus", "staff_3plus"]
    assert w.proxies_for_counts(tiers, branches=1) == []


def test_default_document_covers_every_segment(segments: dict[str, Segment]) -> None:
    doc = w.default_document(segments)
    assert doc["version"] == 0 and doc["fit_only_share"] == pytest.approx(0.10)
    assert set(doc["signal_points"]) == set(segments) == set(doc["can_pay_points"])
    for sid, seg in segments.items():
        for t, p in seg.signal_points.items():  # the segment file's overrides are the defaults there
            assert doc["signal_points"][sid][t] == p


def test_complete_keeps_learned_numbers_and_fills_the_rest(segments: dict[str, Segment]) -> None:
    defaults = w.default_document(segments)
    stored = {"version": 3, "signal_points": {"clinics-in": {"review_pain": 7.2}}, "fit_only_share": 0.08}
    doc = w.complete(stored, defaults)
    assert doc["version"] == 3 and doc["fit_only_share"] == 0.08
    assert doc["signal_points"]["clinics-in"]["review_pain"] == 7.2
    assert doc["signal_points"]["clinics-in"]["public_ask"] == defaults["signal_points"]["clinics-in"]["public_ask"]
    assert doc["can_pay_points"] == defaults["can_pay_points"]


def test_effective_numbers_for_scoring(segments: dict[str, Segment]) -> None:
    seg = segments["clinics-in"]
    doc = {
        "signal_points": {"clinics-in": {"review_pain": 7.5, "unknown_type": 99}},
        "can_pay_points": {"clinics-in": {"branches_2plus": 7.0, "funding": 4.0}},
        "fit_only_share": 0.05,
    }
    points = w.effective_signal_points(seg, doc)
    assert points["review_pain"] == 7.5 and "unknown_type" not in points
    cfg = w.effective_scoring_config(seg, doc)
    tiers = {t["min"]: t["points"] for t in cfg["can_pay"]["branches"]}
    assert tiers[2] == 7.0 and tiers[4] == 8  # only the learned tier changes
    assert cfg["can_pay"]["funding"] == 4.0 and cfg["fit_only_max_pct"] == 5.0
    assert w.effective_scoring_config(seg, None) == scoring_config(seg)


def test_use_weights_overrides_the_stored_document(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"version": 4}
    monkeypatch.setattr(w, "load_current", lambda conn=None: stored)
    proposed = {"version": 99}
    with w.use_weights(proposed):
        assert w.active_document() is proposed
    assert w.active_document() is stored  # outside the block scoring reads the stored weights again


def test_diff_lists_every_changed_number() -> None:
    old = {"signal_points": {"clinics-in": {"a": 1.0, "b": 2.0}}, "can_pay_points": {}, "fit_only_share": 0.1}
    new = {
        "signal_points": {"clinics-in": {"a": 1.2, "b": 2.0}},
        "can_pay_points": {"x": {"p": 3.0}},
        "fit_only_share": 0.1,
    }
    assert w.diff(old, new) == [
        {"group": "signal_points", "segment_id": "clinics-in", "key": "a", "old": 1.0, "new": 1.2},
        {"group": "can_pay_points", "segment_id": "x", "key": "p", "old": None, "new": 3.0},
    ]


def test_load_current_and_frozen_flag(db_conn: Conn, segments: dict[str, Segment]) -> None:
    defaults = w.default_document(segments)
    assert w.load_current(db_conn, defaults) == defaults  # the seed stores {} (nothing learned yet)
    db.set_setting(w.SETTINGS_KEY, {"version": 2, "signal_points": {"clinics-in": {"news": 2.5}}}, conn=db_conn)
    assert w.load_current(db_conn, defaults)["signal_points"]["clinics-in"]["news"] == 2.5
    assert not w.is_frozen(db_conn)
    db.set_setting(w.FROZEN_KEY, True, conn=db_conn)
    assert w.is_frozen(db_conn)
