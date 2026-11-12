"""Weekly re-weighting (Step 16.4): Beta-binomial maths, both clamps, the 30-lead minimum, the early rule,
version history and rollback, the eval gate, and the logistic path."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from nument_engine import db
from nument_engine.learn import gate, logistic, reweight, weights
from nument_engine.learn.metrics import FunnelRow
from nument_engine.pipeline.runs import Options, RunContext, run_context

from .helpers import Conn

AS_OF = datetime(2026, 12, 14, tzinfo=UTC)


def lead(
    i: int,
    *,
    days_ago: int = 80,
    meeting: bool = False,
    replied: bool = False,
    signals: tuple[str, ...] = (),
    proxies: tuple[str, ...] = (),
    segment: str = "clinics-in",
    grade: str = "A",
    total: float = 70,
) -> FunnelRow:
    contacted = AS_OF - timedelta(days=days_ago)
    reached = {}
    if replied or meeting:
        reached[2] = contacted + timedelta(days=2)
    if meeting:
        reached[3] = contacted + timedelta(days=9)
    return FunnelRow(
        lead_id=f"l{i}",
        segment_id=segment,
        country=segment[-2:],
        pitch_mode="visible_pain",
        angle="a",
        test_group=f"{segment}:visible_pain:a",
        grade=grade,
        stage="talking" if reached else "contacted",
        max_rank=max([1, *reached]),
        is_wrong_contact=False,
        contacted_at=contacted,
        attempted_at=contacted,
        reached_at=reached,
        signal_types=signals,
        can_pay_proxies=proxies,
        score_total=total,
    )


def doc(points: dict[str, float], proxies: dict[str, float] | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "signal_points": {"clinics-in": dict(points)},
        "can_pay_points": {"clinics-in": dict(proxies or {})},
        "fit_only_share": 0.1,
    }


# ---------------------------------------------------------------------------
# Maths
# ---------------------------------------------------------------------------


def test_beta_mean_uses_the_one_in_twenty_prior() -> None:
    assert reweight.beta_mean(0, 0) == pytest.approx(0.05)
    assert reweight.beta_mean(9, 80) == pytest.approx(10 / 100)


def test_thirty_lead_minimum() -> None:
    assert reweight.update_points(6.0, 6.0, 20, 29, 30, 300) == (6.0, "not enough data")


def test_weekly_clamp_limits_any_move_to_twenty_percent() -> None:
    up, note = reweight.update_points(6.0, 6.0, 30, 40, 10, 400)  # far better than the segment
    assert up == 7.2 and note == "x1.20"
    down, note = reweight.update_points(6.0, 6.0, 0, 200, 40, 400)
    assert down == 4.8 and note == "x0.80"


def test_absolute_clamp_keeps_points_between_half_and_double_the_default() -> None:
    assert reweight.update_points(11.5, 6.0, 30, 40, 10, 400)[0] == 12.0  # 2.0 x default
    assert reweight.update_points(3.2, 6.0, 0, 200, 40, 400)[0] == 3.0  # 0.5 x default


def test_small_changes_round_to_one_decimal() -> None:
    new, note = reweight.update_points(6.0, 6.0, 9, 80, 40, 400)  # p_sig 0.1, p_seg 41/420
    assert new == round(6.0 * (10 / 100) / (41 / 420), 1) and note.startswith("x1.0")


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------


def test_propose_uses_meetings_once_the_segment_has_fifteen() -> None:
    rows = [lead(i, meeting=i < 16, signals=("review_pain",) if i < 40 else ()) for i in range(200)]
    current = doc({"review_pain": 6.0, "news": 3.0})
    proposal = reweight.propose(rows, current, current, AS_OF)
    assert proposal.events == {"clinics-in": "meeting"}
    (change,) = proposal.changes  # news has no data: unchanged
    assert change.key == "review_pain" and change.new > 6.0 and change.trials == 40 and change.method == "beta_binomial"
    assert proposal.weights["signal_points"]["clinics-in"]["review_pain"] == change.new
    assert current["signal_points"]["clinics-in"]["review_pain"] == 6.0  # the input is not modified


def test_propose_falls_back_to_replies_early_and_says_so() -> None:
    rows = [lead(i, replied=i < 20, meeting=i < 3, signals=("hiring_frontdesk",) if i < 50 else ()) for i in range(150)]
    proposal = reweight.propose(rows, doc({"hiring_frontdesk": 8.0}), doc({"hiring_frontdesk": 8.0}), AS_OF)
    assert proposal.events == {"clinics-in": "replied"}
    assert proposal.changes and "early, based on replies" in proposal.changes[0].note


def test_propose_only_counts_mature_leads_and_can_pay_proxies() -> None:
    fresh = [lead(i, days_ago=10, replied=True, proxies=("branches_2plus",)) for i in range(100)]
    assert not reweight.propose(
        fresh, doc({}, {"branches_2plus": 6.0}), doc({}, {"branches_2plus": 6.0}), AS_OF
    ).changes
    rows = [lead(i, meeting=i % 4 == 0, proxies=("branches_2plus",) if i % 2 == 0 else ()) for i in range(120)]
    rows += [lead(500 + i, meeting=True) for i in range(15)]
    current = doc({}, {"branches_2plus": 6.0})
    proposal = reweight.propose(rows, current, current, AS_OF)
    assert [c.group for c in proposal.changes] == ["can_pay_points"]


def test_propose_respects_the_segment_filter() -> None:
    rows = [lead(i, meeting=i < 16, signals=("review_pain",)) for i in range(100)]
    assert not reweight.propose(
        rows, doc({"review_pain": 6.0}), doc({"review_pain": 6.0}), AS_OF, segments=["clinics-ae"]
    ).changes


# ---------------------------------------------------------------------------
# Versions, rollback, the run and its gate
# ---------------------------------------------------------------------------


def _rc(**opts: Any) -> RunContext:
    return RunContext(
        run_id="00000000-0000-0000-0000-000000000000", kind="weekly", opts=Options(**opts), started_at=datetime.now(UTC)
    )


def test_save_version_keeps_a_baseline_and_rollback_restores_it(engine_db: str) -> None:
    db.execute("delete from public.weight_versions")
    current = weights.load_current()
    proposed = {
        **current,
        "signal_points": {
            **current["signal_points"],
            "clinics-in": {**current["signal_points"]["clinics-in"], "news": 3.6},
        },
    }
    version = reweight.save_version(proposed, current, method="beta_binomial", reason="test")
    assert version == 2
    rows = db.fetch_all("select version, method, diff from public.weight_versions order by version")
    assert [(r["version"], r["method"]) for r in rows] == [(1, "defaults"), (2, "beta_binomial")]
    assert rows[1]["diff"] == [
        {"group": "signal_points", "segment_id": "clinics-in", "key": "news", "old": 3.0, "new": 3.6}
    ]
    stored = db.get_setting(weights.SETTINGS_KEY)
    assert stored["version"] == 2 and stored["signal_points"]["clinics-in"]["news"] == 3.6
    restored = reweight.rollback(1)
    assert restored == 3
    assert weights.load_current()["signal_points"]["clinics-in"]["news"] == 3.0
    assert db.fetch_one("select method, reason from public.weight_versions where version = 3") == {
        "method": "manual",
        "reason": "rollback to version 1",
    }
    with pytest.raises(ValueError, match="does not exist"):
        reweight.rollback(99)
    db.execute("delete from public.weight_versions")
    db.set_setting(weights.SETTINGS_KEY, {})


@pytest.fixture
def proposal_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """A funnel where review_pain clearly books more meetings (fewer than 200 outcomes: Beta-binomial only)."""
    rows = [lead(i, meeting=(i < 30) or (i % 10 == 0), signals=("review_pain",) if i < 60 else ()) for i in range(150)]
    monkeypatch.setattr(reweight, "load_funnel", lambda **_: rows)
    monkeypatch.setattr(logistic, "load_exposure", lambda rows, conn=None: {})


@pytest.mark.parametrize(
    ("verdict", "status"),
    [
        (gate.GateVerdict(True, "ok"), "applied"),
        (gate.GateVerdict(False, "precision 62%"), "rejected_by_eval"),
        (gate.GateVerdict(None, "golden set has 0 labels"), "not_checked"),
    ],
)
def test_run_applies_only_when_the_gate_passes(
    engine_db: str, proposal_ready: None, verdict: gate.GateVerdict, status: str
) -> None:
    db.execute("delete from public.weight_versions")
    with run_context("weekly", Options()) as rc:
        result = reweight.run(rc, gate=lambda proposed, current: verdict, as_of=AS_OF)
    assert result["status"] == status and result["changes"]
    assert result["gate"]["detail"] == verdict.detail
    versions = db.scalar("select count(*) from public.weight_versions")
    assert versions == (2 if status == "applied" else 0)
    stats = db.scalar("select stats -> 'reweight' ->> 'status' from public.runs where id = %s", [rc.run_id])
    assert stats == status
    db.execute("delete from public.weight_versions")
    db.set_setting(weights.SETTINGS_KEY, {})


def test_run_dry_run_and_frozen(engine_db: str, proposal_ready: None) -> None:
    def never(proposed: Any, current: Any) -> gate.GateVerdict:
        raise AssertionError("the gate must not run")

    assert reweight.run(_rc(dry_run=True), gate=never, as_of=AS_OF)["status"] == "dry_run"
    db.set_setting(weights.FROZEN_KEY, True)
    try:
        assert reweight.run(_rc(), gate=never, as_of=AS_OF)["status"] == "frozen"
    finally:
        db.set_setting(weights.FROZEN_KEY, False)


def test_gate_metrics_and_verdicts() -> None:
    labels = {f"b{i}": ("good" if i < 30 else "bad") for i in range(60)}
    good_first = {f"b{i}": (90 - i, "A" if i < 30 else "D") for i in range(60)}
    m = gate.grade_metrics([(b, t, g) for b, (t, g) in good_first.items()], labels)
    assert m == {"k": 50, "precision_at_k": 30 / 50, "bad": 30, "bad_rejection": 1.0}
    verdict = gate.weights_gate({"v": "new"}, {"v": "old"}, labels=labels, score_fn=lambda b: good_first[b])
    assert verdict.passed is False and "precision at 50: 60%" in verdict.detail
    few = gate.weights_gate({}, {}, labels={"b1": "good"}, score_fn=lambda b: (1.0, "A"))
    assert few.passed is None and "at least 20" in few.detail


def test_gate_scores_with_the_proposed_weights() -> None:
    labels = {f"b{i}": ("good" if i < 25 else "bad") for i in range(50)}

    def score(bid: str) -> tuple[float, str]:
        boost = weights.active_document().get("boost", 0)
        i = int(bid[1:])
        return (100 - i + (boost if i < 25 else 0), "A" if i < 25 or not boost else "C")

    verdict = gate.weights_gate({"boost": 50}, {"boost": 0}, labels=labels, score_fn=score)
    assert verdict.metrics["proposed"]["bad_rejection"] == 1.0 and verdict.metrics["current"]["bad_rejection"] == 0.0


# ---------------------------------------------------------------------------
# Logistic regression (16.4.4)
# ---------------------------------------------------------------------------


def test_decay_buckets_match_step_11() -> None:
    start, end = AS_OF - timedelta(days=100), AS_OF
    at = [start + timedelta(days=d) for d in (29, 31, 59, 61, 99)]
    assert [logistic.decay(start, end, a) for a in at] == [1.0, 0.7, 0.7, 0.4, 0.4]
    assert logistic.decay(start, end, end + timedelta(days=1)) == 0.0


def synthetic(n: int, effect: float, seed: int = 7) -> tuple[list[FunnelRow], dict[str, dict[str, float]]]:
    """review_pain drives replies by `effect`; hiring_frontdesk barely matters; totals are noise."""
    rng = random.Random(seed)
    rows, exposure = [], {}
    for i in range(n):
        has = {t for t in ("review_pain", "hiring_frontdesk") if rng.random() < 0.5}
        p = 0.12 + (effect if "review_pain" in has else 0.0) + (0.01 if "hiring_frontdesk" in has else 0.0)
        r = lead(
            i, days_ago=60, replied=rng.random() < p, signals=tuple(sorted(has)), grade="A", total=rng.uniform(50, 90)
        )
        rows.append(r)
        exposure[r.lead_id] = {t: 1.0 for t in has}
    return rows, exposure


def test_logistic_accepts_a_real_effect_and_moves_points_towards_it() -> None:
    rows, exposure = synthetic(400, effect=0.45)
    current = doc({"review_pain": 6.0, "hiring_frontdesk": 8.0, "news": 3.0})
    result = logistic.fit_segment("clinics-in", rows, exposure, current, AS_OF)
    assert result is not None and result.accepted, result.reason if result else None
    assert result.auc_model is not None and result.auc_points is not None
    assert result.auc_model >= logistic.AUC_MIN and result.auc_model - result.auc_points >= logistic.AUC_MARGIN
    assert result.signal_points["review_pain"] > result.signal_points["hiring_frontdesk"]
    assert result.signal_points["news"] == 3.0  # never seen: unchanged
    proposal = reweight.propose(rows, current, current, AS_OF, logistic_results={"clinics-in": result})
    moved = {c.key: c for c in proposal.changes}
    assert moved["review_pain"].method == "logistic" and moved["review_pain"].new == 7.2  # weekly clamp: x1.2
    assert moved["hiring_frontdesk"].new == 6.4  # x0.8
    assert proposal.model_cards[0]["accepted"] is True and proposal.method == "logistic"


def test_logistic_rejects_noise_and_needs_two_hundred_outcomes() -> None:
    rows, exposure = synthetic(600, effect=0.0)
    result = logistic.fit_segment(
        "clinics-in", rows, exposure, doc({"review_pain": 6.0, "hiring_frontdesk": 8.0}), AS_OF
    )
    assert result is not None and not result.accepted and "AUC" in result.reason
    sparse = [r for r in rows if not r.had("replied")][:250] + [r for r in rows if r.had("replied")][:10]
    thin = logistic.fit_segment("clinics-in", sparse, exposure, doc({"review_pain": 6.0}), AS_OF)
    assert thin is not None and not thin.accepted and "too few" in thin.reason
    few, few_exposure = synthetic(150, effect=0.4)
    assert logistic.fit_segment("clinics-in", few, few_exposure, doc({"review_pain": 6.0}), AS_OF) is None


def test_feature_matrix_drops_constant_columns() -> None:
    rows, exposure = synthetic(40, effect=0.3)
    x, names = logistic.build_matrix(rows, exposure, ["review_pain", "hiring_frontdesk", "news"], ["branches_2plus"])
    assert "sig:review_pain" in names and "sig:news" not in names and "pay:branches_2plus" not in names
    assert x.shape == (40, len(names)) and np.all(x[:, names.index("sig:review_pain")] >= 0)


def test_load_exposure_reads_signal_freshness(db_conn: Conn) -> None:
    from . import seed

    lead_id = seed.contacted(db_conn, 20)
    row = db.fetch_one("select business_id, created_at from public.leads where id = %s", [lead_id], conn=db_conn)
    assert row is not None
    db_conn.execute(
        "insert into public.signals (business_id, type, category, points, observed_at, expires_at, source, dedupe_key) "
        "values (%s, 'review_pain', 'visible_pain', 6, %s, %s, 'test', %s)",
        [
            row["business_id"],
            row["created_at"] - timedelta(days=10),
            row["created_at"] + timedelta(days=80),
            f"t:{lead_id}",
        ],
    )
    funnel = FunnelRow(
        lead_id=lead_id,
        segment_id="clinics-in",
        country="in",
        pitch_mode="visible_pain",
        angle=None,
        test_group=None,
        grade="A",
        stage="contacted",
        max_rank=1,
        is_wrong_contact=False,
        contacted_at=row["created_at"] + timedelta(days=1),
        attempted_at=row["created_at"],
    )
    assert logistic.load_exposure([funnel], conn=db_conn) == {lead_id: {"review_pain": 1.0}}
