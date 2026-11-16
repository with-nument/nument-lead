"""Score s3.0 (15 Nov 2026) for startup segments (domain firms); every other segment keeps s2.0 (score.py).

The target is a startup of 2 to 10 people, idea to small seed, without a tech team. Funding alone is not the
signal; funding plus no tech team is. Four parts add up to 100 (weights in config/scoring.yaml `startup`):

    need    = the missing tech team (two signs 15, a lone CTO 8, one sign 7) + their own ask or builder job post
              (signal points x 2.0, decayed, at most 20; +4 for a first-engineer or CTO role) + fresh funding, a
              launch or news (signal points x 1.6, decayed, at most 8)                                  -> 0 to 35
    fit     = a startup (6) + 2 to 5 people (6) + an early round (5) + a product still to build (5) + young (3)
                                                                                                        -> 0 to 25
    can_pay = qualify.py's points: money raised or earned, a builder job post, paid tools, own domain   -> 0 to 20
    reach   = the founder email ladder: verified owner email 1.0, likely owner email 0.85, company email
              0.7, phone 0.4, form 0.3, nothing 0; times 20                                              -> 0 to 20

Grade D for more than settings startup.max_team people, a team with engineers, a late round, more than
startup.max_raise_usd raised or a business that is not a startup (contract 4.3). Otherwise A at 75, B 55, C 40
(the s2.0 lines, so the judge reads both the same), with caps: at most B without anyone to email (the founder
email search still runs for B leads), at most B without a sign of a missing tech team, a lone CTO or their own
ask, and at most C when they offer equity only and no money was seen.

The profile comes from `qualify.assess()`, the same function the qualify phase stores, so a score never depends
on whether that phase ran first. Columns keep their s2.0 meaning where they can: `fit` counts the three gates
passed (startup, no tech team, can pay), `can_pay` is the can-pay part, `intent` the need part, `reach` the share.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

from ..models import PitchMode, make_test_group
from ..segments import Segment
from . import evidence, qualify
from .evidence import Row
from .qualify import FIRST_BUILDER, Profile, Rules
from .score import (
    Reach,
    ScoreResult,
    ScoringConfig,
    _signal_line,
    decay,
    grade_of,
    line_of,
    round_half_up,
    signal_points,
)
from .verify import Suppression

SCORE_VERSION: Final = "s3.0"
STATED: Final = frozenset({"public_ask", "tender", "hiring_builder"})
TRIGGERS: Final = frozenset({"funding", "launch", "news", "new_place", "new_branch"})
TO_BUILD: Final = frozenset({"idea", "landing", "waitlist", "no_code"})
LIVE: Final = frozenset({"web_app", "mobile_app"})
GRADE_ORDER: Final = "ABCD"
REACH_KINDS: Final[dict[str, str]] = {  # the rung -> the reach kind leads.py and the judge read
    "verified_owner_email": "decision_maker_email",
    "likely_owner_email": "decision_maker_email",
    "company_email": "email",
    "form": "form",
    "none": "none",
}


def is_startup_segment(seg: Segment) -> bool:
    return seg.domain == "firms"


@dataclass(frozen=True)
class Weights:
    """config/scoring.yaml `startup` (with the segment's overrides), as numbers."""

    need: Mapping[str, float]
    fit: Mapping[str, Any]
    reach: Mapping[str, float]
    reach_points: float
    caps: Mapping[str, str]

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> Weights:
        return cls(
            need={str(k): float(v) for k, v in (raw.get("need") or {}).items()},
            fit=dict(raw.get("fit") or {}),
            reach={str(k): float(v) for k, v in (raw.get("reach") or {}).items()},
            reach_points=float(raw.get("reach_points", 20)),
            caps={str(k): str(v) for k, v in (raw.get("caps") or {}).items()},
        )


def rules_of(cfg: ScoringConfig) -> Rules:
    """Qualification rules from the segment's config; score.segment_configs adds the settings' limits."""
    raw = cfg.startup
    return Rules.from_config(raw, max_team=raw.get("max_team"), max_raise_usd=raw.get("max_raise_usd"))


# =========================================================================
# The four parts
# =========================================================================


def _fresh(s: Mapping[str, Any], now: datetime) -> float:
    return decay(s["observed_at"], s["expires_at"], now)


def need_of(
    p: Profile, active: Sequence[Row], seg: Segment, cfg: ScoringConfig, w: Weights, now: datetime
) -> tuple[float, list[dict[str, Any]], list[str], Row | None, Row | None]:
    """(need, kept signals with their values, reasons, the stated-need signal, the trigger signal)."""
    n = w.need
    why: list[str] = []
    if p.tech_team == "none":
        gap = n.get("no_tech_team", 15)
        why.append(f"no tech team, two signs: {'; '.join(s.why for s in p.no_tech_signs)} (+{gap:g})")
    elif p.tech_team == "lone_cto":
        gap = n.get("lone_cto", 8)
        why.append(f"a lone CTO: {(p.evidence.get('tech_team') or {}).get('why', '')} (+{gap:g})")
    elif p.tech_team == "unknown" and p.no_tech_signs:
        gap = n.get("one_sign", 7)
        why.append(f"one sign of no tech team: {p.no_tech_signs[0].why} (+{gap:g})")
    else:
        gap = 0.0
    kept: list[dict[str, Any]] = []
    stated_best: tuple[float, Row | None] = (0.0, None)
    trigger_best: tuple[float, Row | None] = (0.0, None)
    for s in active:
        kind = str(s["type"])
        fresh = _fresh(s, now)
        if fresh <= 0:
            continue
        if kind in STATED:
            value = signal_points(s, seg, cfg) * n.get("stated_multiplier", 2.0) * fresh
            text = f"{(s.get('details') or {}).get('role') or ''} {s.get('quote') or ''}"
            if kind == "hiring_builder" and FIRST_BUILDER.search(text):
                value += n.get("first_builder", 4) * fresh
            if value > stated_best[0]:
                stated_best = (value, s)
        elif kind in TRIGGERS:
            value = signal_points(s, seg, cfg) * n.get("trigger_multiplier", 1.6) * fresh
            if value > trigger_best[0]:
                trigger_best = (value, s)
    stated = min(stated_best[0], n.get("stated_cap", 20))
    trigger = min(trigger_best[0], n.get("trigger_cap", 8))
    for value, used in ((stated, stated_best[1]), (trigger, trigger_best[1])):
        if used is not None and value > 0:
            kept.append({**used, "value": value})
            why.append(f"{_signal_line(used, now)} (signal {evidence.short_id(used['id'])}, +{value:.1f})")
    return min(n.get("cap", 35), gap + stated + trigger), kept, why, stated_best[1], trigger_best[1]


def _age_band(p: Profile, now: datetime, fit: Mapping[str, Any]) -> tuple[str, str]:
    starts = [d for d in (p.online_since, p.founded_year and datetime(p.founded_year, 1, 1).date()) if d]
    if not starts:
        return "unknown", "age unknown"
    years = (now.date() - min(starts)).days / 365.25
    since = min(starts).year
    if years <= float(fit.get("new_years", 3)):
        return "new", f"young: since {since}"
    if years <= float(fit.get("middle_years", 6)):
        return "middle", f"since {since}"
    return "old", f"since {since}, not young"


def fit_of(p: Profile, rules: Rules, w: Weights, now: datetime) -> tuple[float, list[str]]:
    fit = w.fit

    def pts(group: str, key: str) -> float:
        return float((fit.get(group) or {}).get(key, 0))

    why: list[str] = []
    total = 0.0
    if p.is_startup is True:
        total += pts("startup", "shown")
        why.append(
            f"a startup: {p.is_startup_why.removeprefix('Startup: ').rstrip('.')} (+{pts('startup', 'shown'):g})"
        )
    elif p.is_startup is None:
        total += pts("startup", "unknown")
        why.append(f"startup not yet shown (+{pts('startup', 'unknown'):g})")
    size = p.team_size
    if size is None:
        band = "unknown"
    elif size <= 1:
        band = "solo"
    elif size <= int(fit.get("small_max", 5)):
        band = "small"
    elif size <= rules.max_team:
        band = "mid"
    else:
        band = ""
    if band:
        total += pts("size", band)
        label = "team size unknown" if size is None else f"{size} {'person' if size == 1 else 'people'}"
        why.append(f"{label} (+{pts('size', band):g})")
    stage = "early" if p.early_round and p.late_round is None else "unknown"
    total += pts("stage", stage)
    rnd = qualify.ROUND_WORDS.get(p.early_round or "", "")
    why.append(f"{'an early round: ' + rnd if stage == 'early' else 'stage unknown'} (+{pts('stage', stage):g})")
    product = "to_build" if p.product_status in TO_BUILD else "live" if p.product_status in LIVE else "unknown"
    total += pts("product", product)
    why.append(f"product: {p.product_status.replace('_', ' ')} (+{pts('product', product):g})")
    age, age_why = _age_band(p, now, fit)
    total += pts("young", age)
    why.append(f"{age_why} (+{pts('young', age):g})")
    return min(total, float(fit.get("cap", 25))), why


def usable(contacts: Sequence[Row], now: datetime, suppressed: Suppression | None) -> list[Row]:
    """Contacts we may use: not do-not-contact, not suppressed, not a bot line, not an invalid email, and either
    seen on a public page (verified) or an email the checker passed (lane E3 labels verified or likely)."""
    out = []
    for c in contacts:
        status = str(c.get("email_status") or "unknown")
        checked = c.get("email") and status in ("verified", "likely")
        if c.get("do_not_contact") or not (c.get("verified") or checked) or line_of(c) == "bot":
            continue
        if not (c.get("phone_e164") or (c.get("email") and status != "invalid")):
            continue
        if suppressed and (
            c.get("phone_e164") in suppressed.phones or str(c.get("email") or "").lower() in suppressed.emails
        ):
            continue
        if c.get("source") == "google_listing" and (
            c.get("verified_at") is None or now - c["verified_at"] > evidence.GOOGLE_LISTING_MAX_AGE
        ):
            continue
        out.append(c)
    return out


def _owner_rung(c: Row) -> str | None:
    """verified or likely for an owner's email; an unchecked guess is no rung at all (never emailed)."""
    status = str(c.get("email_status") or "unknown")
    if status == "verified":
        return "verified_owner_email"
    if status == "likely":
        return "likely_owner_email"
    if status == "unknown" and c.get("email_origin") != "guess":
        return "likely_owner_email"  # published by the person or found in public: lane E3 checks it next
    return None


def reach_of(contacts: Sequence[Row], facts: Sequence[Row], w: Weights, now: datetime,
             suppressed: Suppression | None) -> tuple[Reach, str]:  # fmt: skip
    """(reach, rung) on the founder email ladder (contract 4.4)."""
    ok = usable(contacts, now, suppressed)
    mails = [c for c in ok if c.get("email") and str(c.get("email_status") or "unknown") != "invalid"]
    order = ("verified_owner_email", "likely_owner_email")
    owners = sorted(
        ((r, c) for c in mails if line_of(c) == "owner" and (r := _owner_rung(c)) is not None),
        key=lambda t: order.index(t[0]),
    )
    if owners:
        rung, c = owners[0]
        status = c.get("email_status") or "unchecked"
        why = f"{rung.replace('_', ' ')} (contact {evidence.short_id(c['id'])}, {status}, {c.get('source')})"
        return Reach(w.reach.get(rung, 0.0), REACH_KINDS[rung], c, why), rung
    company = next((c for c in mails if line_of(c) != "owner" or _owner_rung(c) is None), None)
    company = company if company is None or company.get("email_origin") != "guess" else None
    if company is not None:
        why = f"company email (contact {evidence.short_id(company['id'])})"
        return Reach(w.reach.get("company_email", 0.0), "email", company, why), "company_email"
    phone = next((c for c in ok if c.get("phone_e164")), None)
    if phone is not None:
        kind = "business_mobile" if phone.get("phone_type") == "mobile" else "landline"
        why = f"phone only, a call (contact {evidence.short_id(phone['id'])})"
        return Reach(w.reach.get("phone", 0.0), kind, phone, why), "phone"
    form = evidence.by_field(facts, "contact_form_url")
    if form:
        why = f"contact form only (fact {evidence.short_id(form[0]['id'])})"
        return Reach(w.reach.get("form", 0.0), "form", None, why), "form"
    return Reach(w.reach.get("none", 0.0), "none", None, "nobody to email yet"), "none"


# =========================================================================
# Grade, pitch, angle and note
# =========================================================================


def _cap(grade: str, most: str) -> str:
    return most if GRADE_ORDER.index(grade) < GRADE_ORDER.index(most) else grade


def grade_with_caps(total: float, p: Profile, stated: Row | None, rung: str, cfg: ScoringConfig,
                    w: Weights) -> tuple[str, list[str]]:  # fmt: skip
    """The rule grade and the caps that lowered it."""
    if p.disqualified:
        return "D", []
    grade = grade_of(total, cfg)
    caps: list[str] = []
    rules = (
        (rung == "none", "no_contact", "nobody to email yet"),
        (p.tech_team not in ("none", "lone_cto") and not p.no_tech_signs and stated is None, "no_tech_evidence",
         "nothing yet about the tech team and no ask of their own"),
        (p.tech_team != "none" and stated is None, "no_gap_or_ask",
         "no proof of a missing tech team (one sign, or a lone CTO who can build) and no ask of their own"),
        (p.can_pay == "no", "no_budget", "equity only or unpaid, and no money seen"),
    )  # fmt: skip
    for applies, key, why in rules:
        most = w.caps.get(key)
        if applies and most in ("A", "B", "C", "D") and GRADE_ORDER.index(grade) < GRADE_ORDER.index(most):
            grade = _cap(grade, most)
            caps.append(f"at most {most}: {why}")
    return grade, caps


def pitch_mode_of(p: Profile, stated: Row | None) -> str:
    """Their own ask is a stated need; a team without anyone technical is a visible gap; else fit only."""
    if stated is not None:
        return "stated_need"
    if p.tech_team in ("none", "lone_cto") or p.no_tech_signs:
        return "visible_pain"
    return "fit_only"


def angle_of(p: Profile, mode: str, trigger: Row | None, seg: Segment) -> str:
    """The segment's angle for this startup (the startup angles live in segments/firms-*.yaml)."""
    keys = {a.key for a in seg.angles}

    def pick(*wanted: str) -> str | None:
        return next((k for k in wanted if k in keys), None)

    if mode == "stated_need":
        return "build_what_they_asked"
    chosen: str | None = None
    if p.product_status == "no_code":
        chosen = pick("beyond_no_code")
    elif p.tech_team == "lone_cto":
        chosen = pick("extra_hands")
    elif mode == "visible_pain":
        chosen = pick("first_version")
    if chosen is None and trigger is not None:
        chosen = seg.growth_angle()
    return chosen or seg.fit_only_angle()


def startup_note(p: Profile, stated: Row | None, trigger: Row | None, now: datetime) -> str:
    """Two plain sentences at most, from the evidence only (no AI, no dashes)."""
    first = ""
    if p.disqualified:
        first = f"Not a fit: {p.disqualified[0]}"
    elif stated is not None:
        first = _signal_line(stated, now)
    elif trigger is not None and trigger["type"] == "funding" and p.funding_round:
        amount = f" of {qualify._usd_text(p.raised_usd)}" if p.raised_usd else ""
        days = max(0, (now - trigger["observed_at"]).days)
        when = "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"
        first = f"Raised {qualify._a(qualify.ROUND_WORDS.get(p.funding_round, 'funding'))} round{amount}, seen {when}"
    elif trigger is not None and trigger["type"] == "launch":
        details = trigger.get("details") or {}
        days = max(0, (now - trigger["observed_at"]).days)
        where = f"in the {details['batch']} batch" if details.get("batch") else "launched"
        first = f"{'Listed' if details.get('batch') else 'Launched'} {where if details.get('batch') else ''}".strip()
        first = f"{first}, seen {'today' if days == 0 else f'{days} days ago'}"
    elif trigger is not None:
        first = _signal_line(trigger, now)
    else:
        first = "No buying signal yet, but a startup that fits"
    team = f"a team of {p.team_size}" if p.team_size else "the team"
    if p.tech_team == "has_engineers":
        second = f"Engineers already on {team}"
    elif p.tech_team == "none":
        second = f"Nobody technical on {team}"
    elif p.tech_team == "lone_cto":
        second = f"One technical person and no engineers on {team}"
    elif p.no_tech_signs:
        second = f"No technical person found yet on {team}"
    else:
        second = f"Who builds the product is not known yet ({team})"
    if p.product_status == "no_code" and p.no_code_platform:
        second += f", and the product runs on {p.no_code_platform.title()}"
    elif p.product_status in ("idea", "landing", "waitlist"):
        second += f", and the product is at the {p.product_status} stage"
    note = f"{first}. {second}."
    return note.replace("\u2013", ",").replace("\u2014", ",")[:280]


# =========================================================================
# score()
# =========================================================================


def score(
    b: Mapping[str, Any],
    facts: Sequence[Row],
    signals: Sequence[Mapping[str, Any]],
    contacts: Sequence[Row],
    seg: Segment,
    cfg: ScoringConfig,
    now: datetime,
    suppressed: Suppression | None = None,
    *,
    profile: Profile | None = None,
) -> ScoreResult:
    """Score s3.0 for one startup (no AI, no database)."""
    w = Weights.parse(cfg.startup)
    rules = rules_of(cfg)
    rows = [dict(s) for s in signals]
    p = profile or qualify.assess(b, facts, rows, now, rules, currency=seg.currency)
    active = [s for s in rows if evidence.is_active(s, now)]
    need, kept, need_why, stated, trigger = need_of(p, active, seg, cfg, w, now)
    fit_points, fit_why = fit_of(p, rules, w, now)
    pay = 0.0 if p.can_pay == "no" else p.pay_points
    reach, rung = reach_of(contacts, facts, w, now, suppressed)
    total = min(100, round_half_up(round(need, 2) + fit_points + pay + reach.value * w.reach_points))
    grade, caps = grade_with_caps(total, p, stated, rung, cfg, w)
    mode = pitch_mode_of(p, stated)
    angle = angle_of(p, mode, trigger, seg)
    gates = {
        "startup": p.is_startup is True,
        "no_tech_team": p.tech_team in ("none", "lone_cto"),
        "can_pay": p.can_pay in ("yes", "likely"),
    }
    fact_ids = [str(f["id"]) for f in facts]
    signal_ids = [str(s["id"]) for s in active]
    basis = evidence.basis_hash(fact_ids, signal_ids, total, rung)
    reasons: dict[str, Any] = {
        "version": SCORE_VERSION,
        "need": need_why,
        "fit": fit_why,
        "fit_gate_failed": bool(p.disqualified),
        "disqualified": p.disqualified,
        "caps": caps,
        "can_pay": [f"{x.why} (+{x.points:g})" for x in p.pay] if p.can_pay != "no" else [p.evidence["can_pay"]["why"]],
        "can_pay_proxies": [x.key for x in p.pay],
        "intent": [{"signal_id": str(s["id"]), "type": s["type"], "value": round(s["value"], 1)} for s in kept],
        "reach": [reach.reason],
        "reach_kind": reach.kind,
        "reach_rung": rung,
        "rule_grade": grade,
        "angle": angle,
        "basis": basis,
        "gates": gates,
        "profile": p.snapshot(),
        "parts": {
            "need": round(need, 1),
            "can_pay": round(pay, 1),
            "fit": round(fit_points, 1),
            "reach": round(reach.value * w.reach_points, 1),
        },
    }
    result = ScoreResult(
        fit=sum(gates.values()),
        can_pay=round(min(pay, 30.0), 2),
        intent=round(need, 1),
        reach=reach.value,
        total=total,
        grade=grade,
        pitch_mode=mode,
        angle=angle,
        test_group=make_test_group(seg.id, cast(PitchMode, mode), angle),
        reasons=reasons,
        kept=kept,
        reach_kind=reach.kind,
        best_contact=reach.contact,
        basis=basis,
        note=startup_note(p, stated, trigger, now),
        evidence_ids=frozenset(fact_ids) | frozenset(signal_ids) | frozenset(p.all_ids),
        has_email=any(c.get("email") for c in usable(contacts, now, suppressed)),
        version=SCORE_VERSION,
    )
    return result
