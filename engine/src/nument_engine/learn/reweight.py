"""Weekly re-weighting of signal and can-pay points from outcomes (Step 16.4).

For each segment and each signal type (and each can-pay proxy) with enough data:

1. Success is a meeting inside its window. Until the segment has 15 meetings, a reply is used instead and
   the change is marked "early, based on replies".
2. Prior Beta(1, 19), a 5% base rate, keeps small samples close to the default:
   p_sig = (successes + 1) / (contacted + 20), p_seg the same for the whole segment.
3. Multiplier m = p_sig / p_seg, clamped to 0.8 to 1.2 per week.
4. New points = old * m, clamped to 0.5 to 2.0 times the default, rounded to one decimal.
5. Only signal types (or proxies) seen on 30 or more mature contacted leads change.

Segments with 200 or more mature outcomes try the logistic model first (`logistic.py`) and fall back to
this method when it is not accepted. Safety (16.4.3): weekly only, never when the founder froze the
weights, and never without the eval gate passing on the golden set. Every applied change writes a
`weight_versions` row before `settings.score_weights` is updated, so any version can be restored.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Final, Literal

from .. import db
from ..logging import get_logger
from ..pipeline.runs import RunContext
from ..segments import load_segments
from . import logistic
from .gate import GateVerdict, weights_gate
from .metrics import FunnelRow, load_funnel, tiers_by_segment
from .weights import FROZEN_KEY, SETTINGS_KEY, Doc, default_document, diff, is_frozen, load_current

log = get_logger()

PRIOR_A, PRIOR_B = 1, 19
MIN_CONTACTED: Final[int] = 30
WEEKLY_CLAMP: Final[tuple[float, float]] = (0.8, 1.2)
ABS_CLAMP: Final[tuple[float, float]] = (0.5, 2.0)
EARLY_MEETINGS: Final[int] = 15
LOOKBACK_DAYS: Final[int] = 365
IST = timezone(timedelta(hours=5, minutes=30))
LOCK_KEY: Final[int] = 7_331_016  # one weights writer at a time

Method = Literal["beta_binomial", "logistic"]
Gate = Callable[[Doc, Doc], GateVerdict]


def beta_mean(successes: int, trials: int) -> float:
    """Posterior mean with the Beta(1, 19) prior."""
    return (successes + PRIOR_A) / (trials + PRIOR_A + PRIOR_B)


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def update_points(old: float, default: float, s_sig: int, n_sig: int, s_seg: int, n_seg: int) -> tuple[float, str]:
    """New points for one signal type or proxy, and a short note ('x1.12' or 'not enough data')."""
    if n_sig < MIN_CONTACTED:
        return old, "not enough data"
    m = clamp(beta_mean(s_sig, n_sig) / beta_mean(s_seg, n_seg), *WEEKLY_CLAMP)
    new = clamp(old * m, ABS_CLAMP[0] * default, ABS_CLAMP[1] * default)
    return round(new, 1), f"x{m:.2f}"


def clamp_to(old: float, default: float, target: float) -> tuple[float, float]:
    """Apply the weekly and absolute clamps to a target value from the logistic model; returns (new, m)."""
    if old <= 0:
        return old, 1.0
    m = clamp(target / old, *WEEKLY_CLAMP)
    return round(clamp(old * m, ABS_CLAMP[0] * default, ABS_CLAMP[1] * default), 1), m


@dataclass
class Change:
    """One proposed number."""

    segment_id: str
    group: Literal["signal_points", "can_pay_points"]
    key: str
    old: float
    new: float
    successes: int
    trials: int
    event: str
    method: Method
    note: str


@dataclass
class Proposal:
    weights: Doc
    changes: list[Change] = field(default_factory=list)
    events: dict[str, str] = field(default_factory=dict)  # segment -> meeting | replied
    model_cards: list[dict[str, Any]] = field(default_factory=list)

    @property
    def method(self) -> Method:
        return "logistic" if any(c.method == "logistic" for c in self.changes) else "beta_binomial"


def _success_event(rows: Sequence[FunnelRow]) -> str:
    meetings = sum(r.had("meeting") for r in rows if r.contacted)
    return "meeting" if meetings >= EARLY_MEETINGS else "replied"


def propose(
    rows: Sequence[FunnelRow],
    current: Doc,
    defaults: Doc,
    as_of: datetime,
    *,
    segments: Sequence[str] | None = None,
    logistic_results: Mapping[str, logistic.LogisticResult] | None = None,
) -> Proposal:
    """The new weights document (version not yet assigned) and every number that changed."""
    new_doc = copy.deepcopy(current)
    proposal = Proposal(weights=new_doc)
    wanted = set(segments) if segments else None
    by_segment: dict[str, list[FunnelRow]] = {}
    for r in rows:
        if r.contacted:
            by_segment.setdefault(r.segment_id, []).append(r)

    for sid, seg_rows in sorted(by_segment.items()):
        if wanted is not None and sid not in wanted:
            continue
        model = (logistic_results or {}).get(sid)
        if model is not None and model.accepted:
            _apply_logistic(proposal, sid, model, current, defaults)
            continue
        event = _success_event(seg_rows)
        proposal.events[sid] = event
        mature = [r for r in seg_rows if r.mature(event, as_of)]
        if not mature:
            continue
        n_seg, s_seg = len(mature), sum(r.had(event) for r in mature)
        note_suffix = ", early, based on replies" if event == "replied" else ""
        groups: tuple[tuple[Literal["signal_points", "can_pay_points"], Callable[[FunnelRow], Sequence[str]]], ...] = (
            ("signal_points", lambda r: r.signal_types),
            ("can_pay_points", lambda r: r.can_pay_proxies),
        )
        for group, keys_of in groups:
            now = (current.get(group) or {}).get(sid) or {}
            base = (defaults.get(group) or {}).get(sid) or {}
            for key, old in sorted(now.items()):
                with_key = [r for r in mature if key in keys_of(r)]
                n_sig, s_sig = len(with_key), sum(r.had(event) for r in with_key)
                default = float(base.get(key, old))
                new, note = update_points(float(old), default, s_sig, n_sig, s_seg, n_seg)
                if new != float(old):
                    new_doc[group].setdefault(sid, {})[key] = new
                    proposal.changes.append(
                        Change(
                            sid, group, key, float(old), new, s_sig, n_sig, event, "beta_binomial", note + note_suffix
                        )
                    )
    return proposal


def _apply_logistic(proposal: Proposal, sid: str, model: logistic.LogisticResult, current: Doc, defaults: Doc) -> None:
    proposal.events[sid] = model.target
    proposal.model_cards.append(model.card())
    pairs: tuple[tuple[Literal["signal_points", "can_pay_points"], dict[str, float]], ...] = (
        ("signal_points", model.signal_points),
        ("can_pay_points", model.can_pay_points),
    )
    for group, targets in pairs:
        now = (current.get(group) or {}).get(sid) or {}
        base = (defaults.get(group) or {}).get(sid) or {}
        for key, target in sorted(targets.items()):
            old = float(now.get(key, target))
            new, m = clamp_to(old, float(base.get(key, old)), target)
            if new != old:
                proposal.weights[group].setdefault(sid, {})[key] = new
                proposal.changes.append(
                    Change(sid, group, key, old, new, 0, model.n, model.target, "logistic", f"x{m:.2f}")
                )


def _versioned(doc: Doc, version: int, method: str, now: datetime) -> Doc:
    out = copy.deepcopy(doc)
    out.update({"version": version, "updated_at": now.astimezone(IST).isoformat(timespec="seconds"), "method": method})
    return out


def save_version(
    new_doc: Doc, current: Doc, *, method: str, reason: str, created_by: str = "engine", now: datetime | None = None
) -> int:
    """Write a weight_versions row, then point settings.score_weights at it. Returns the new version."""
    now = now or datetime.now(UTC)
    with db.tx() as conn:
        conn.execute("select pg_advisory_xact_lock(%s)", [LOCK_KEY])
        latest = db.scalar("select max(version) from public.weight_versions", conn=conn)
        if latest is None:  # keep what was in force before the first learned change, so it can be restored
            baseline = max(int(current.get("version") or 0), 1)
            db.execute(
                "insert into public.weight_versions (version, weights, method, reason, diff, created_by) "
                "values (%s, %s, %s, %s, %s, %s)",
                [
                    baseline,
                    db.Jsonb(_versioned(current, baseline, "defaults", now)),
                    "defaults" if not current.get("version") else "manual",
                    "weights in force before the first learned change",
                    db.Jsonb([]),
                    created_by,
                ],
                conn=conn,
            )
            latest = baseline
        version = int(latest) + 1
        doc = _versioned(new_doc, version, method, now)
        db.execute(
            "insert into public.weight_versions (version, weights, method, reason, diff, created_by) "
            "values (%s, %s, %s, %s, %s, %s)",
            [version, db.Jsonb(doc), method, reason, db.Jsonb(diff(current, doc)), created_by],
            conn=conn,
        )
        db.set_setting(SETTINGS_KEY, doc, conn=conn)
    return version


def rollback(version: int, *, created_by: str = "manual") -> int:
    """Restore an older version's weights. Recorded as a new version (method 'manual'), so it can be undone too."""
    row = db.fetch_one("select weights from public.weight_versions where version = %s", [version])
    if row is None:
        raise ValueError(f"weight version {version} does not exist")
    return save_version(
        row["weights"], load_current(), method="manual", reason=f"rollback to version {version}", created_by=created_by
    )


def _summary(
    status: str, proposal: Proposal | None, verdict: GateVerdict | None, version: int | None
) -> dict[str, Any]:
    return {
        "status": status,
        "version": version,
        "method": proposal.method if proposal else None,
        "events": proposal.events if proposal else {},
        "changes": [asdict(c) for c in proposal.changes] if proposal else [],
        "model_cards": proposal.model_cards if proposal else [],
        "gate": None
        if verdict is None
        else {"passed": verdict.passed, "detail": verdict.detail, "metrics": verdict.metrics},
    }


def run(rc: RunContext, *, gate: Gate | None = None, as_of: datetime | None = None) -> dict[str, Any]:
    """Propose, check and (unless dry run, frozen or rejected) apply this week's weights. Stores a summary in run stats.

    Status: frozen, no_change, dry_run, applied, rejected_by_eval, or not_checked (the gate could not run,
    for example before the golden set exists; nothing is applied).
    """
    as_of = as_of or datetime.now(UTC)
    if is_frozen():
        result = _summary("frozen", None, None, None)
        result["note"] = f"settings.{FROZEN_KEY} is true: the founder froze the weights"
        rc.stats["reweight"] = result
        return result
    segs = load_segments()
    defaults = default_document(segs)
    current = load_current(defaults=defaults)
    tiers = tiers_by_segment()
    rows = load_funnel(as_of=as_of, since_days=LOOKBACK_DAYS, tiers=tiers)
    wanted = rc.opts.segments or sorted(segs)

    models: dict[str, logistic.LogisticResult] = {}
    big = [sid for sid in wanted if logistic.mature_outcomes(rows, sid, as_of) >= logistic.MIN_OUTCOMES]
    if big:
        exposure = logistic.load_exposure([r for r in rows if r.segment_id in big])
        for sid in big:
            fitted = logistic.fit_segment(sid, rows, exposure, current, as_of)
            if fitted is not None:
                models[sid] = fitted

    proposal = propose(rows, current, defaults, as_of, segments=wanted, logistic_results=models)
    for card in (m.card() for m in models.values() if not m.accepted):
        proposal.model_cards.append(card)

    verdict: GateVerdict | None = None
    version: int | None = None
    if not proposal.changes:
        status = "no_change"
    elif rc.opts.dry_run:
        status = "dry_run"
    else:
        verdict = (gate or weights_gate)(proposal.weights, current)
        if verdict.passed is True:
            n = len(proposal.changes)
            version = save_version(
                proposal.weights,
                current,
                method=proposal.method,
                reason=f"weekly {proposal.method.replace('_', '-')} update: {n} change(s)",
            )
            status = "applied"
        elif verdict.passed is False:
            status = "rejected_by_eval"
        else:
            status = "not_checked"
    result = _summary(status, proposal, verdict, version)
    log.info("learn.reweight", status=status, changes=len(proposal.changes), version=version)
    rc.stats["reweight"] = result
    return result
