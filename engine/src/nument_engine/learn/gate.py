"""Eval gate for weight changes (Step 16.4.3).

A proposed weights document is applied only if the golden set, re-scored with it, still meets the grade
thresholds of Step 17.4.2: precision at 50 of 80% or more, and 70% or more of the businesses labelled bad
graded C or D. Weights change scoring only, so the gate re-scores stored facts and signals with code and
costs nothing: no AI calls.

No verdict (`passed is None`) means the gate could not run (too few golden labels, or scoring not built);
the caller then keeps the current weights.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from .. import db
from ..ops import bindings
from ..segments import Segment, load_segments
from .weights import Doc, use_weights

TOP_K: Final[int] = 50
GRADE_PRECISION_MIN: Final[float] = 0.80
BAD_REJECTION_MIN: Final[float] = 0.70
MIN_LABELS: Final[int] = 20

ScoreFn = Callable[[str], tuple[float, str]]  # business id -> (total, grade) with the active weights


@dataclass(frozen=True)
class GateVerdict:
    passed: bool | None  # None: the gate could not run, so nothing is applied
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


def golden_labels(conn: Any = None) -> dict[str, str]:
    """Latest label per business from `golden_labels` (good or bad)."""
    rows = db.fetch_all(
        "select distinct on (business_id) business_id::text as business_id, label "
        "from public.golden_labels order by business_id, at desc",
        conn=conn,
    )
    return {r["business_id"]: r["label"] for r in rows}


def grade_metrics(scored: list[tuple[str, float, str]], labels: Mapping[str, str], k: int = TOP_K) -> dict[str, Any]:
    """Precision at k (share labelled good among the k highest totals) and bad rejection (share of bad graded C/D)."""
    ranked = sorted(scored, key=lambda s: (-s[1], s[0]))
    top = ranked[: min(k, len(ranked))]
    good_top = sum(labels.get(bid) == "good" for bid, _, _ in top)
    bad = [(bid, grade) for bid, _, grade in scored if labels.get(bid) == "bad"]
    rejected = sum(grade in ("C", "D") for _, grade in bad)
    return {
        "k": len(top),
        "precision_at_k": good_top / len(top) if top else None,
        "bad": len(bad),
        "bad_rejection": rejected / len(bad) if bad else None,
    }


def production_score_fn(conn: Any = None) -> ScoreFn:
    """Score one stored business with Step 11's `score_business` and whatever weights are active."""
    score_business = bindings.business_scorer()
    segments: dict[str, Segment] = load_segments()

    def score(business_id: str) -> tuple[float, str]:
        b = db.fetch_one("select * from public.businesses where id = %s", [business_id], conn=conn)
        if b is None:
            raise LookupError(f"golden business {business_id} no longer exists")
        facts = db.fetch_all("select * from public.v_verified_facts where business_id = %s", [business_id], conn=conn)
        signals = db.fetch_all(
            "select * from public.signals where business_id = %s and expires_at > now()", [business_id], conn=conn
        )
        contacts = db.fetch_all(
            "select * from public.contacts where business_id = %s and not do_not_contact", [business_id], conn=conn
        )
        result = score_business(b, facts, signals, contacts, segments[b["segment_id"]])
        return float(result.total), str(result.grade)

    return score


def _score_all(score: ScoreFn, business_ids: list[str], doc: Doc) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    with use_weights(doc):
        for bid in business_ids:
            try:
                total, grade = score(bid)
            except LookupError:
                continue
            out.append((bid, total, grade))
    return out


def weights_gate(
    proposed: Doc,
    current: Doc,
    *,
    labels: Mapping[str, str] | None = None,
    score_fn: ScoreFn | None = None,
) -> GateVerdict:
    """Re-score the golden set with the current and the proposed weights; pass when the proposal meets both thresholds."""
    labelled = dict(labels) if labels is not None else golden_labels()
    if len(labelled) < MIN_LABELS:
        return GateVerdict(None, f"golden set has {len(labelled)} labels; the gate needs at least {MIN_LABELS}")
    try:
        score = score_fn or production_score_fn()
    except NotImplementedError as exc:
        return GateVerdict(None, f"scoring is not available: {exc}")
    ids = sorted(labelled)
    before = grade_metrics(_score_all(score, ids, current), labelled)
    after = grade_metrics(_score_all(score, ids, proposed), labelled)
    precision, rejection = after["precision_at_k"], after["bad_rejection"]
    ok_precision = precision is not None and precision >= GRADE_PRECISION_MIN
    ok_rejection = rejection is None or rejection >= BAD_REJECTION_MIN
    metrics = {"labels": len(labelled), "current": before, "proposed": after}

    def fmt(v: float | None) -> str:
        return "n/a" if v is None else f"{v:.0%}"

    detail = (
        f"precision at {after['k']}: {fmt(precision)} (current {fmt(before['precision_at_k'])}, need "
        f"{GRADE_PRECISION_MIN:.0%}); bad graded C or D: {fmt(rejection)} (current {fmt(before['bad_rejection'])}, "
        f"need {BAD_REJECTION_MIN:.0%})"
    )
    return GateVerdict(ok_precision and ok_rejection, detail, metrics)
