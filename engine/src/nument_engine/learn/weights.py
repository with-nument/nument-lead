"""Scoring weights the learning loop may change (Step 16.3), and how scoring reads them.

One JSON document in `settings.score_weights` holds three groups of numbers:

    {"version": 7, "updated_at": "2026-12-14T02:10:00+05:30", "method": "beta_binomial",
     "signal_points":  {"clinics-in": {"hiring_frontdesk": 8.0, "review_pain": 6.6, ...}, ...},
     "can_pay_points": {"clinics-in": {"branches_2plus": 6.0, "reviews_100plus": 4.0, ...}, ...},
     "fit_only_share": 0.10}

Missing entries fall back to the defaults: the A.12.3 signal points with the segment file's
`signal_points` overrides, and the can-pay points of `scoring_config(segment)`. Can-pay proxy keys are
derived from that config (`{group}_{min}plus` for tiers, the key itself for single proxies), so a segment
that changes a tier minimum gets its own key, for example `branches_3plus`.

Scoring (Step 11) reads the merged numbers through `effective_signal_points()` and
`effective_scoring_config()` (A.13.5 rule 8). `use_weights()` lets the eval gate score with a proposed
document without saving it.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final

from psycopg import Connection

from .. import db
from ..models import SIGNAL_TYPES
from ..segments import Segment, load_segments, load_yaml_config, scoring_config

# A.12.3 default points. pipeline/signals.py keeps the same table (DEFAULT_POINTS); a test keeps them equal.
DEFAULT_SIGNAL_POINTS: Final[dict[str, float]] = {
    "public_ask": 10.0,
    "tender": 10.0,
    "hiring_builder": 8.0,
    "hiring_frontdesk": 8.0,
    "review_pain": 6.0,
    "ads_running": 4.0,
    "no_booking": 3.0,
    "slow_site": 2.0,
    "new_place": 5.0,
    "new_branch": 5.0,
    "news": 3.0,
    "funding": 0.0,  # adds can-pay instead (the `funding` proxy)
}
TIERED_GROUPS: Final[tuple[str, ...]] = ("branches", "staff", "reviews")
SINGLE_PROXIES: Final[tuple[str, ...]] = ("premium_price", "pays_for_software", "custom_website", "funding")
DEFAULT_FIT_ONLY_SHARE: Final[float] = 0.10
SETTINGS_KEY: Final[str] = "score_weights"
FROZEN_KEY: Final[str] = "score_weights_frozen"

Doc = dict[str, Any]

_override: ContextVar[Doc | None] = ContextVar("nlead_score_weights_override", default=None)


def proxy_key(group: str, minimum: int | float) -> str:
    """`branches_2plus` for the branches tier that starts at 2."""
    return f"{group}_{int(minimum)}plus"


def proxy_tiers(cfg: Mapping[str, Any]) -> dict[str, list[tuple[float, str]]]:
    """Tiered proxies of a scoring config: group -> [(minimum, proxy key)], highest minimum first."""
    can_pay = cfg.get("can_pay") or {}
    tiers: dict[str, list[tuple[float, str]]] = {}
    for group in TIERED_GROUPS:
        entries = [(float(t["min"]), proxy_key(group, t["min"])) for t in can_pay.get(group) or []]
        tiers[group] = sorted(entries, reverse=True)
    return tiers


def can_pay_points_of(cfg: Mapping[str, Any]) -> dict[str, float]:
    """Every can-pay proxy of a scoring config with its points (the defaults the learning loop starts from)."""
    can_pay = cfg.get("can_pay") or {}
    points: dict[str, float] = {}
    for group in TIERED_GROUPS:
        for tier in can_pay.get(group) or []:
            points[proxy_key(group, tier["min"])] = float(tier["points"])
    for key in SINGLE_PROXIES:
        if key in can_pay:
            points[key] = float(can_pay[key])
    return points


def proxies_for_counts(
    tiers: Mapping[str, list[tuple[float, str]]],
    *,
    branches: float | None = None,
    staff: float | None = None,
    reviews: float | None = None,
) -> list[str]:
    """The tier proxy each count earns. Tiers are exclusive: the first that matches counts (Step 11.3)."""
    found: list[str] = []
    for group, value in (("branches", branches), ("staff", staff), ("reviews", reviews)):
        if value is None:
            continue
        for minimum, key in tiers.get(group, []):
            if value >= minimum:
                found.append(key)
                break
    return found


def segment_signal_defaults(seg: Segment) -> dict[str, float]:
    """A.12.3 points with the segment file's overrides applied."""
    points = dict(DEFAULT_SIGNAL_POINTS)
    points.update({k: float(v) for k, v in seg.signal_points.items()})
    return {t: points[t] for t in SIGNAL_TYPES}


def default_document(segments: Mapping[str, Segment] | None = None) -> Doc:
    """Version 0: what scoring uses when nothing has been learned yet."""
    segs = load_segments() if segments is None else segments
    fit_only_pct = load_yaml_config("scoring").get("fit_only_max_pct")
    share = DEFAULT_FIT_ONLY_SHARE if fit_only_pct is None else float(fit_only_pct) / 100
    return {
        "version": 0,
        "updated_at": None,
        "method": "defaults",
        "signal_points": {sid: segment_signal_defaults(seg) for sid, seg in sorted(segs.items())},
        "can_pay_points": {sid: can_pay_points_of(scoring_config(seg)) for sid, seg in sorted(segs.items())},
        "fit_only_share": share,
    }


def complete(doc: Mapping[str, Any] | None, defaults: Doc) -> Doc:
    """`doc` with every segment and key that it lacks filled in from `defaults` (new segments, new proxies)."""
    out = copy.deepcopy(defaults)
    if not doc:
        return out
    for key in ("version", "updated_at", "method", "fit_only_share"):
        if doc.get(key) is not None:
            out[key] = doc[key]
    for group in ("signal_points", "can_pay_points"):
        for sid, values in (doc.get(group) or {}).items():
            out[group].setdefault(sid, {})
            out[group][sid].update({k: float(v) for k, v in values.items()})
    return out


def load_current(conn: Connection[Any] | None = None, defaults: Doc | None = None) -> Doc:
    """The weights in force: `settings.score_weights` completed with defaults (version 0 when empty)."""
    base = defaults if defaults is not None else default_document()
    stored = db.get_setting(SETTINGS_KEY, None, conn=conn)
    if not isinstance(stored, dict) or "version" not in stored:
        return base
    return complete(stored, base)


def is_frozen(conn: Connection[Any] | None = None) -> bool:
    """The founder froze the weights from the app (`settings.score_weights_frozen`, Step 16.4.3)."""
    return bool(db.get_setting(FROZEN_KEY, False, conn=conn))


@contextmanager
def use_weights(doc: Doc) -> Iterator[Doc]:
    """Score with `doc` inside this block (the eval gate's proposed weights), without saving it."""
    token = _override.set(doc)
    try:
        yield doc
    finally:
        _override.reset(token)


def active_document(conn: Connection[Any] | None = None) -> Doc:
    """The document scoring should use now: the `use_weights` override, else the stored weights."""
    override = _override.get()
    return override if override is not None else load_current(conn)


def effective_signal_points(seg: Segment, doc: Mapping[str, Any] | None = None) -> dict[str, float]:
    """Points per signal type for a segment: learned weights, else the segment file, else A.12.3."""
    points = segment_signal_defaults(seg)
    learned = ((doc or {}).get("signal_points") or {}).get(seg.id) or {}
    points.update({k: float(v) for k, v in learned.items() if k in points})
    return points


def effective_scoring_config(seg: Segment, doc: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """`scoring_config(seg)` with learned can-pay points and the learned fit-only share applied."""
    cfg = scoring_config(seg)
    learned = ((doc or {}).get("can_pay_points") or {}).get(seg.id) or {}
    can_pay = cfg.setdefault("can_pay", {})
    for group in TIERED_GROUPS:
        for tier in can_pay.get(group) or []:
            key = proxy_key(group, tier["min"])
            if key in learned:
                tier["points"] = float(learned[key])
    for key in SINGLE_PROXIES:
        if key in learned and key in can_pay:
            can_pay[key] = float(learned[key])
    share = (doc or {}).get("fit_only_share")
    if share is not None:
        cfg["fit_only_max_pct"] = round(float(share) * 100, 1)
    return cfg


def diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every number that differs between two documents, as rows for weight_versions.diff and the report."""
    rows: list[dict[str, Any]] = []
    for group in ("signal_points", "can_pay_points"):
        old_g, new_g = old.get(group) or {}, new.get(group) or {}
        for sid in sorted(set(old_g) | set(new_g)):
            o, n = old_g.get(sid) or {}, new_g.get(sid) or {}
            for key in sorted(set(o) | set(n)):
                if o.get(key) != n.get(key):
                    rows.append({"group": group, "segment_id": sid, "key": key, "old": o.get(key), "new": n.get(key)})
    if old.get("fit_only_share") != new.get("fit_only_share"):
        rows.append(
            {
                "group": "fit_only_share",
                "segment_id": None,
                "key": "fit_only_share",
                "old": old.get("fit_only_share"),
                "new": new.get("fit_only_share"),
            }
        )
    return rows
