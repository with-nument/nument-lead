"""Logistic regression re-weighting, used once a segment has 200 or more mature outcomes (Step 16.4.4).

Per lead, the features are: the freshness of each signal type at first contact (the Step 11.4.1 decay of
the strongest signal of that type, 0 to 1), each can-pay proxy (0 or 1), reach type, pitch mode and country
(one-hot), grade (A=3 to D=0) and the signal's age at first contact in months. Features that never vary are
dropped. The target is a reply within 21 days, or a meeting within 45 days once the segment has 200 meetings.

An L2-regularised model (C=0.5, balanced classes) is cross-validated on 5 stratified folds. It is accepted
only if its mean AUC is 0.62 or more and beats the current score total's AUC on the same folds by 0.02 or
more. One safety addition: both outcomes need 30 or more leads, because a fold with three replies gives an
AUC that is mostly chance.

Accepted coefficients become points, scaled so the typical A lead keeps roughly its current total (the
median over A leads of current points divided by summed coefficients). The weekly and absolute clamps of
the Beta-binomial method still apply, and features seen on fewer than 30 leads keep their old points.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import numpy as np

from .. import db
from .metrics import FunnelRow
from .weights import Doc

MIN_OUTCOMES: Final[int] = 200
MIN_MEETINGS_FOR_MEETING_TARGET: Final[int] = 200
AUC_MIN: Final[float] = 0.62
AUC_MARGIN: Final[float] = 0.02
C_VALUE: Final[float] = 0.5
FOLDS: Final[int] = 5
MIN_SUPPORT: Final[int] = 30
MIN_CLASS: Final[int] = 30  # replies and non-replies each: fewer makes fold AUCs noise (a safety addition)
SEED: Final[int] = 42
GRADE_ORDINAL: Final[dict[str, float]] = {"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.0}


@dataclass
class LogisticResult:
    """The model card for one segment (shown in the weekly report) and, if accepted, the proposed points."""

    segment_id: str
    accepted: bool
    reason: str
    target: str
    n: int
    positives: int
    auc_model: float | None = None
    auc_points: float | None = None
    features: list[str] = field(default_factory=list)
    coefficients: dict[str, float] = field(default_factory=dict)
    signal_points: dict[str, float] = field(default_factory=dict)  # target points before clamps
    can_pay_points: dict[str, float] = field(default_factory=dict)
    fitted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def card(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "target": self.target,
            "sample_size": self.n,
            "positives": self.positives,
            "auc_model": self.auc_model,
            "auc_points": self.auc_points,
            "features": self.features,
            "coefficients": {k: round(v, 4) for k, v in self.coefficients.items()},
            "fitted_at": self.fitted_at,
        }


def decay(observed_at: datetime, expires_at: datetime, at: datetime) -> float:
    """Step 11.4.1 freshness: 1.0 up to 30% of the window, 0.7 up to 60%, 0.4 up to 100%, then 0."""
    window = (expires_at - observed_at).total_seconds()
    if window <= 0 or at >= expires_at or at < observed_at:
        return 0.0
    ratio = (at - observed_at).total_seconds() / window
    return 1.0 if ratio <= 0.30 else 0.7 if ratio <= 0.60 else 0.4


def load_exposure(lead_rows: Sequence[FunnelRow], conn: Any = None) -> dict[str, dict[str, float]]:
    """Per lead, the freshness of each signal type at first contact (strongest signal of each type)."""
    contacted = {r.lead_id: r.contacted_at for r in lead_rows if r.contacted_at is not None}
    if not contacted:
        return {}
    rows = db.fetch_all(
        """
        select l.id::text as lead_id, s.type, s.observed_at, s.expires_at
        from public.leads l
        join public.signals s on s.business_id = l.business_id
        where l.id = any(%s::uuid[]) and s.observed_at <= l.created_at and s.expires_at > l.created_at
        """,
        [list(contacted)],
        conn=conn,
    )
    exposure: dict[str, dict[str, float]] = {}
    for r in rows:
        at = contacted[r["lead_id"]]
        assert at is not None
        value = decay(r["observed_at"], r["expires_at"], at)
        per_lead = exposure.setdefault(r["lead_id"], {})
        per_lead[r["type"]] = max(per_lead.get(r["type"], 0.0), value)
    return exposure


def choose_target(rows: Sequence[FunnelRow], as_of: datetime) -> str | None:
    """'meeting' once 200 meetings exist, else 'replied' once 200 replied outcomes are mature, else None."""
    contacted = [r for r in rows if r.contacted]
    meetings = sum(r.had("meeting") for r in contacted if r.mature("meeting", as_of))
    if meetings >= MIN_MEETINGS_FOR_MEETING_TARGET:
        return "meeting"
    mature = sum(r.mature("replied", as_of) for r in contacted)
    return "replied" if mature >= MIN_OUTCOMES else None


def build_matrix(
    rows: Sequence[FunnelRow],
    exposure: Mapping[str, Mapping[str, float]],
    signal_keys: Sequence[str],
    proxy_keys: Sequence[str],
) -> tuple[np.ndarray, list[str]]:
    """Feature matrix and names. Columns that never vary are dropped."""
    names: list[str] = [f"sig:{k}" for k in signal_keys] + [f"pay:{k}" for k in proxy_keys]
    cats: dict[str, list[str]] = {
        "reach": sorted({r.reach_type for r in rows}),
        "pitch": sorted({r.pitch_mode for r in rows}),
        "country": sorted({r.country for r in rows}),
    }
    for prefix, options in cats.items():
        names += [f"{prefix}:{v}" for v in options]
    names += ["grade", "signal_age_months"]
    matrix = np.zeros((len(rows), len(names)))
    for i, r in enumerate(rows):
        exp = exposure.get(r.lead_id, {})
        values: dict[str, float] = {f"sig:{k}": float(exp.get(k, 0.0)) for k in signal_keys}
        values |= {f"pay:{k}": float(k in r.can_pay_proxies) for k in proxy_keys}
        values |= {f"reach:{r.reach_type}": 1.0, f"pitch:{r.pitch_mode}": 1.0, f"country:{r.country}": 1.0}
        values["grade"] = GRADE_ORDINAL.get(r.grade, 0.0)
        values["signal_age_months"] = (r.signal_age_days or 0.0) / 30.0
        for j, name in enumerate(names):
            matrix[i, j] = values.get(name, 0.0)
    keep = [j for j in range(len(names)) if np.ptp(matrix[:, j]) > 0] if len(rows) else []
    return matrix[:, keep], [names[j] for j in keep]


def fit_segment(
    segment_id: str,
    rows: Sequence[FunnelRow],
    exposure: Mapping[str, Mapping[str, float]],
    current: Doc,
    as_of: datetime,
    *,
    seed: int = SEED,
) -> LogisticResult | None:
    """Fit, cross-validate and convert to points. None when the segment does not have enough outcomes yet."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold

    seg_rows = [r for r in rows if r.segment_id == segment_id and r.contacted]
    target = choose_target(seg_rows, as_of)
    if target is None:
        return None
    data = [r for r in seg_rows if r.mature(target, as_of)]
    y = np.array([int(r.had(target)) for r in data])
    signal_keys = sorted((current.get("signal_points") or {}).get(segment_id, {}))
    proxy_keys = sorted((current.get("can_pay_points") or {}).get(segment_id, {}))
    x, names = build_matrix(data, exposure, signal_keys, proxy_keys)
    result = LogisticResult(segment_id, False, "", target, len(data), int(y.sum()), features=names)
    if min(int(y.sum()), len(y) - int(y.sum())) < MIN_CLASS or not names:
        result.reason = f"fewer than {MIN_CLASS} {target} and not-{target} outcomes: too few to fit reliably"
        return result
    totals = np.array([r.score_total if r.score_total is not None else np.nan for r in data])
    totals = np.where(np.isnan(totals), np.nanmedian(totals) if np.isfinite(totals).any() else 0.0, totals)

    auc_model, auc_points = [], []
    folds = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=seed)
    for train, test in folds.split(x, y):
        model = LogisticRegression(C=C_VALUE, class_weight="balanced", max_iter=2000)
        model.fit(x[train], y[train])
        auc_model.append(float(roc_auc_score(y[test], model.predict_proba(x[test])[:, 1])))
        auc_points.append(float(roc_auc_score(y[test], totals[test])))
    result.auc_model, result.auc_points = float(np.mean(auc_model)), float(np.mean(auc_points))
    if result.auc_model < AUC_MIN:
        result.reason = f"cross-validated AUC {result.auc_model:.3f} is under {AUC_MIN}"
        return result
    if result.auc_model - result.auc_points < AUC_MARGIN:
        result.reason = (
            f"AUC {result.auc_model:.3f} does not beat the current score's {result.auc_points:.3f} by {AUC_MARGIN}"
        )
        return result

    model = LogisticRegression(C=C_VALUE, class_weight="balanced", max_iter=2000).fit(x, y)
    result.coefficients = {name: float(c) for name, c in zip(names, model.coef_[0], strict=True)}
    converted = _to_points(data, exposure, result.coefficients, current, segment_id, x, names)
    if converted is None:
        result.reason = "coefficients give no positive scale for the median A lead"
        return result
    result.signal_points, result.can_pay_points = converted
    result.accepted = True
    result.reason = f"AUC {result.auc_model:.3f} vs {result.auc_points:.3f} for the current score"
    return result


def _to_points(
    data: Sequence[FunnelRow],
    exposure: Mapping[str, Mapping[str, float]],
    coef: Mapping[str, float],
    current: Doc,
    segment_id: str,
    x: np.ndarray,
    names: list[str],
) -> tuple[dict[str, float], dict[str, float]] | None:
    """Coefficients to points. The scale k is the median, over A leads, of current points / summed coefficients
    of the signals and proxies each lead had, so the typical A lead keeps roughly its current total."""
    sig_now = (current.get("signal_points") or {}).get(segment_id, {})
    pay_now = (current.get("can_pay_points") or {}).get(segment_id, {})
    support = {name: int((x[:, j] > 0).sum()) for j, name in enumerate(names)}
    a_rows = [r for r in data if r.grade == "A"] or list(data)
    ratios: list[float] = []
    for r in a_rows:
        sigs = [k for k, v in exposure.get(r.lead_id, {}).items() if v > 0]
        now = sum(float(sig_now.get(k, 0.0)) for k in sigs) + sum(float(pay_now.get(p, 0.0)) for p in r.can_pay_proxies)
        logit = sum(coef.get(f"sig:{k}", 0.0) for k in sigs) + sum(coef.get(f"pay:{p}", 0.0) for p in r.can_pay_proxies)
        if now > 0 and logit > 0:
            ratios.append(now / logit)
    if not ratios:
        return None
    k = statistics.median(ratios)

    def target(prefix: str, now: Mapping[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, old in now.items():
            name = f"{prefix}:{key}"
            if name in coef and support.get(name, 0) >= MIN_SUPPORT:
                out[key] = max(k * coef[name], 0.0)
            else:
                out[key] = float(old)
        return out

    return target("sig", sig_now), target("pay", pay_now)


def mature_outcomes(rows: Sequence[FunnelRow], segment_id: str, as_of: datetime) -> int:
    """Contacted leads of the segment whose reply window has closed."""
    return sum(r.segment_id == segment_id and r.contacted and r.mature("replied", as_of) for r in rows)
