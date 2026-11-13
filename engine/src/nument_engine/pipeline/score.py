"""Scoring and grading (Step 11): need, can-pay, fit and reach add up to one number from 0 to 100 (score s2.0).

    need    = signal points x category multiplier, visible pain at most 24, growth at most 12   -> 0 to 35
    can_pay = proxy points (capped at 30) scaled to 35                                         -> 0 to 35
    fit     = 10 for fit 3, 6 for fit 2                                                        -> 0 to 10
    reach   = share of 20 (decision maker mobile 1.0, business mobile 0.9, landline 0.6, ...) -> 0 to 20
    total   = round_half_up(need + can_pay + fit + reach)                                      -> 0 to 100
    grade   = A at 75+, B 55 to 74, C 40 to 54, D under 40; D whenever the fit gate fails or nobody is reachable

s2.0 replaced s1.0 (raw / 80 x 100 x reach) on 13 Nov 2026: a strong business without a signal could not get
above 50 there, so the judge lifted C to B and the lead showed "B, 40/100". The stored columns keep their
meaning: `intent` is the need points, `can_pay` the proxy points before scaling, `reach` the share (0 to 1).

Every weight comes from `scoring_config(segment)` (config/scoring.yaml plus segment overrides) with the
learned `settings.score_weights` on top (A.13.5 rule 8, Step 16.3). Scoring is pure code and cheap, so the
morning run re-scores every researched and qualified business; a new `scores` row is stored only when
something changed, which keeps the history meaningful and the free-tier database small.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, cast

from psycopg import Connection

from .. import db
from ..learn.weights import active_document
from ..logging import get_logger
from ..models import SIGNAL_CATEGORY, PitchMode, make_test_group
from ..segments import Segment, load_segments, scoring_config
from ..settings import get_settings
from . import evidence, leads
from .evidence import Row, fact_count, fact_flag, fact_text, vget
from .runs import RunContext
from .verify import Exclusions, Suppression

log = get_logger()

SCORE_VERSION: Final = "s2.0"
DEFAULT_GRADES: Final[dict[str, float]] = {"A": 75, "B": 55, "C": 40}  # s2.0
DECAY_STEPS: Final = ((0.30, 1.0), (0.60, 0.7), (1.00, 0.4))  # share of the window -> multiplier (11.4.1)
# A.12.3 default points, used only when a stored signal carries none.
DEFAULT_SIGNAL_POINTS: Final[dict[str, float]] = {
    "public_ask": 10,
    "tender": 10,
    "hiring_builder": 8,
    "hiring_frontdesk": 8,
    "review_pain": 6,
    "ads_running": 4,
    "no_booking": 3,
    "slow_site": 2,
    "new_place": 5,
    "new_branch": 5,
    "news": 3,
    "funding": 0,
}
# Can-pay proxies that `settings.score_weights.can_pay_points[segment]` may re-weight (Step 16.3):
# the tier keys are "<proxy>_<min>plus", for example branches_2plus or reviews_300plus.
CAN_PAY_FLAT_PROXIES: Final = ("premium_price", "pays_for_software", "custom_website", "funding")
PAID_TOOL_KINDS: Final = frozenset({"booking", "chat", "live_chat", "crm", "whatsapp_vendor"})
FREE_BUILDER_DOMAINS: Final = (
    "wixsite.com",
    "business.site",
    "sites.google.com",
    "godaddysites.com",
    "wordpress.com",
    "blogspot.com",
    "weebly.com",
    "webflow.io",
    "squarespace.com",
    "carrd.co",
    "mystrikingly.com",
    "jimdosite.com",
    "zohosites.com",
    "zohosites.in",
    "site123.me",
    "webnode.page",
    "netlify.app",
    "vercel.app",
    "github.io",
    "my.canva.site",
    "framer.website",
    "notion.site",
)
JUDGE_LOOKBACK: Final = timedelta(days=2)
CHUNK: Final = 500


def round_half_up(x: float) -> int:
    """round(42.5) is 43 here, as in the worked examples; Python's round() would give 42."""
    return int(Decimal(repr(round(x, 6))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# =========================================================================
# Config
# =========================================================================


@dataclass(frozen=True)
class Tier:
    min: float
    points: float


@dataclass(frozen=True)
class ScoringConfig:
    """Every number Step 11 uses, resolved for one segment."""

    fit_gate: int
    fit_bonus: Mapping[int, float]
    can_pay_cap: float
    can_pay_points: float  # the can-pay part of the total: proxy points / can_pay_cap * can_pay_points
    branches: tuple[Tier, ...]
    staff: tuple[Tier, ...]
    reviews: tuple[Tier, ...]
    premium_price: float
    pays_for_software: float
    custom_website: float
    funding: float
    intent_cap: float
    stack_bonus_per_type: float
    stack_bonus_max: float
    reach: Mapping[str, float]
    reach_points: float
    grades: Mapping[str, float]
    fit_only_max_pct: float
    judge_top_share: float
    multiplier: Mapping[str, float] = field(default_factory=dict)  # signal category -> need multiplier
    category_cap: Mapping[str, float] = field(default_factory=dict)  # signal category -> most need points
    fit_only_min_per_day: int = 1
    signal_points: Mapping[str, float] = field(default_factory=dict)
    reach_email_first: Mapping[str, float] = field(default_factory=dict)  # outreach_channel: email segments
    retainer_fit: float = 3.0  # ongoing work likely (13 Nov 2026)
    too_big: float = -4.0  # 200+ staff

    @classmethod
    def build(cls, raw: Mapping[str, Any], segment_id: str, weights: Mapping[str, Any] | None = None) -> ScoringConfig:
        """From the merged scoring dict (`scoring_config(seg)`) plus `settings.score_weights`."""
        weights = weights or {}
        learned_pay: Mapping[str, Any] = (weights.get("can_pay_points") or {}).get(segment_id) or {}

        def tiers(name: str) -> tuple[Tier, ...]:
            out = []
            for t in raw["can_pay"][name]:
                key = f"{name}_{int(t['min'])}plus"
                out.append(Tier(float(t["min"]), float(learned_pay.get(key, t["points"]))))
            return tuple(sorted(out, key=lambda t: -t.min))

        pay = raw["can_pay"]
        flat = {k: float(learned_pay.get(k, pay[k])) for k in CAN_PAY_FLAT_PROXIES}
        share = weights.get("fit_only_share")
        return cls(
            fit_gate=int(raw["fit"]["gate"]),
            fit_bonus={int(k): float(v) for k, v in raw["fit"]["bonus"].items()},
            can_pay_cap=float(pay["cap"]),
            can_pay_points=float(pay.get("points", pay["cap"])),
            branches=tiers("branches"),
            staff=tiers("staff"),
            reviews=tiers("reviews"),
            premium_price=flat["premium_price"],
            pays_for_software=flat["pays_for_software"],
            custom_website=flat["custom_website"],
            funding=flat["funding"],
            intent_cap=float(raw["intent"]["cap"]),
            stack_bonus_per_type=float(raw["intent"]["stack_bonus_per_type"]),
            stack_bonus_max=float(raw["intent"]["stack_bonus_max"]),
            reach={k: float(v) for k, v in raw["reach"].items()},
            reach_email_first={k: float(v) for k, v in (raw.get("reach_email_first") or {}).items()},
            retainer_fit=float(raw["can_pay"].get("retainer_fit", 3)),
            too_big=float(raw["can_pay"].get("too_big", -4)),
            reach_points=float(raw["total"]["reach_points"]),
            grades={k: float(v) for k, v in (raw.get("grades") or DEFAULT_GRADES).items()},
            fit_only_max_pct=float(share) * 100 if share is not None else float(raw.get("fit_only_max_pct", 10)),
            judge_top_share=float(raw.get("judge_top_share", 0.5)),
            multiplier={str(k): float(v) for k, v in (raw["intent"].get("multiplier") or {}).items()},
            category_cap={str(k): float(v) for k, v in (raw["intent"].get("category_cap") or {}).items()},
            fit_only_min_per_day=int(raw.get("fit_only_min_per_day", 1)),
            signal_points={
                str(k): float(v) for k, v in ((weights.get("signal_points") or {}).get(segment_id) or {}).items()
            },
        )

    @classmethod
    def for_segment(cls, seg: Segment, weights: Mapping[str, Any] | None = None) -> ScoringConfig:
        return cls.build(scoring_config(seg), seg.id, weights)


# =========================================================================
# 11.2 to 11.5: the four parts
# =========================================================================


def decay(observed_at: datetime, expires_at: datetime, now: datetime) -> float:
    """1.0 for the first 30% of a signal's window, 0.7 to 60%, 0.4 to the end, 0 once expired (11.4.1)."""
    window = (expires_at - observed_at).total_seconds()
    if window <= 0 or now >= expires_at:
        return 0.0
    ratio = (now - observed_at).total_seconds() / window
    for limit, factor in DECAY_STEPS:
        if ratio <= limit:
            return factor
    return 0.0


def signal_points(signal: Mapping[str, Any], seg: Segment, cfg: ScoringConfig) -> float:
    """Points for one signal: its own stored points (Step 7 may give a strong signal more than the type's
    default), scaled by what learning did to its type (Step 16.3).

    The type default is the segment override, else A.12.3. A learned type weight acts as a multiplier
    `learned / default`, so per-signal strength survives re-weighting and the version 0 document (learned
    equals default) changes nothing. A type whose default is 0 takes the learned value as is.
    """
    kind = str(signal["type"])
    default = float(seg.signal_points.get(kind, DEFAULT_SIGNAL_POINTS.get(kind, 0)))  # type: ignore[call-overload]
    stored = float(signal.get("points") or 0)
    own = stored if stored > 0 else default
    learned = cfg.signal_points.get(kind)
    if learned is None:
        return own
    if default <= 0:
        return float(learned)
    return own * float(learned) / default


def intent_score(
    signals: Iterable[Mapping[str, Any]], now: datetime, cfg: ScoringConfig, seg: Segment | None = None
) -> tuple[float, list[dict[str, Any]]]:
    """(need 0 to 35, the signals kept). Best value per type, one per event, a small stacking bonus.

    A signal's value is its points times its category's multiplier (a stated need counts most), decayed by
    age. Visible pain and growth each add at most their category cap, so without a stated need a lead cannot
    reach the top of the scale.
    """
    best_by_type: dict[str, dict[str, Any]] = {}
    for s in signals:
        points = signal_points(s, seg, cfg) if seg is not None else float(s.get("points") or 0)
        category = str(s.get("category") or SIGNAL_CATEGORY.get(str(s["type"])) or "")
        value = points * cfg.multiplier.get(category, 1.0) * decay(s["observed_at"], s["expires_at"], now)
        if value <= 0:
            continue
        cur = best_by_type.get(s["type"])
        if cur is None or value > cur["value"]:
            best_by_type[s["type"]] = {**s, "value": value}
    by_event: dict[str, dict[str, Any]] = {}
    for s in best_by_type.values():
        key = (s.get("details") or {}).get("event_key") or f"type:{s['type']}"
        if key not in by_event or s["value"] > by_event[key]["value"]:
            by_event[key] = s
    kept = sorted(by_event.values(), key=lambda s: -s["value"])
    by_category: dict[str, float] = defaultdict(float)
    for s in kept:
        by_category[str(s.get("category") or SIGNAL_CATEGORY.get(str(s["type"])) or "")] += s["value"]
    base = sum(min(v, cfg.category_cap.get(cat, v)) for cat, v in by_category.items())
    n = len(kept)
    bonus = min(cfg.stack_bonus_per_type * (n - 1), cfg.stack_bonus_max) if n >= 2 else 0.0
    # Without a stated need the ceiling is the highest cap among the categories present (visible pain 24).
    ceiling = cfg.intent_cap
    if by_category and "stated_need" not in by_category:
        ceiling = min(ceiling, max(cfg.category_cap.get(cat, cfg.intent_cap) for cat in by_category))
    return min(base + bonus, ceiling), kept


def _word_match(phrase: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", text.lower()) is not None


def business_count(b: Mapping[str, Any], facts: Sequence[Row], column: str, fact_field: str) -> int | None:
    """A business column (filled by Step 10 from verified facts and by Places), else the facts themselves."""
    if b.get(column) is not None:
        return int(b[column])
    counts = [c for c in (fact_count(f) for f in evidence.by_field(facts, fact_field)) if c is not None]
    return max(counts) if counts else None


def fit_gate(
    b: Mapping[str, Any],
    facts: Sequence[Row],
    seg: Segment,
    excl: Exclusions,
    stated_need: Mapping[str, Any] | None = None,
) -> tuple[int, list[str]]:
    """0 to 3: type match, size, owner-led without a tech team (11.2).

    In a need-first segment (`universe: signals_only`) there is no map category: the business's own stated need
    (a builder job post or a public ask) is the type match.
    """
    why: list[str] = []
    fit = 0
    services = [
        f
        for f in evidence.by_field(facts, "service")
        if any(_word_match(k, fact_text(f)) for k in seg.fit.service_keywords)
    ]
    excluded = seg.fit.excludes_name(b.get("name"))
    if excluded:  # a type the segment does not target: the fit gate fails, so the grade is D
        return 0, [f"not a target type: '{excluded}' in the name"]
    if seg.is_type_match(b.get("category"), b.get("subcategory")):
        fit += 1
        why.append(f"type match: {b.get('subcategory') or b.get('category')}")
    elif seg.universe == "signals_only" and stated_need is not None:
        fit += 1
        why.append(f"type match: their own stated need (signal {evidence.short_id(stated_need['id'])})")
    elif services:
        fit += 1
        why.append(f"type match: service '{fact_text(services[0])[:40]}' (fact {evidence.short_id(services[0]['id'])})")
    reviews = b.get("review_count")
    staff = business_count(b, facts, "staff_count", "staff_or_doctors")
    branches = business_count(b, facts, "branches_count", "branches")
    if reviews is not None and reviews >= seg.fit.min_reviews:
        fit += 1
        why.append(f"size: review_count={reviews} (places)")
    elif staff is not None and staff >= seg.fit.min_staff:
        fit += 1
        why.append(f"size: staff_count={staff}")
    elif branches is not None and branches >= 2:
        fit += 1
        why.append(f"size: branches_count={branches}")
    tech = [f for f in evidence.by_field(facts, "in_house_tech") if fact_flag(f) is True]
    names = [str(b.get("name") or "")]
    listed = (
        excl.chain_match(names, b.get("web_domain"))
        or excl.hospital_match(names)
        or excl.competitor_match(names, b.get("web_domain"), partner=seg.domain == "partners")
    )
    if tech:
        why.append(f"has an in-house tech team (fact {evidence.short_id(tech[0]['id'])})")
    elif listed:
        why.append(f"on the exclusions list ({listed})")
    else:
        fit += 1
        why.append("owner-led, no in-house tech team found")
    return fit, why


def _tier_points(value: float | None, tiers: Sequence[Tier]) -> Tier | None:
    if value is None:
        return None
    return next((t for t in tiers if value >= t.min), None)


def tech_tools(facts: Sequence[Row]) -> list[dict[str, Any]]:
    """Tools found by the Step 9 tech scan: a list of {tool, kind, page_url} (or that list under 'tools')."""
    out: list[dict[str, Any]] = []
    for f in evidence.by_field(facts, "tech_stack"):
        value = f.get("value")
        items = value.get("tools") if isinstance(value, Mapping) else value
        if isinstance(items, list):
            out += [{**i, "_fact": f["id"]} for i in items if isinstance(i, Mapping)]
    return out


def pays_for_software(facts: Sequence[Row]) -> str | None:
    """A paid booking system, CRM, live chat or WhatsApp API provider, or a claimed Practo profile (11.3)."""
    for f in evidence.by_field(facts, "tech_stack"):
        if isinstance(f.get("value"), Mapping) and f["value"].get("pays_for_software") is True:
            return f"paid software (fact {evidence.short_id(f['id'])})"
    for t in tech_tools(facts):
        kind = re.sub(r"[\s-]+", "_", str(t.get("kind") or "").strip().lower())
        if kind in PAID_TOOL_KINDS:
            return f"{t.get('tool') or kind} ({kind}, fact {evidence.short_id(t['_fact'])})"
    for f in facts:
        if "practo.com" in evidence.host_of(f.get("url")) and re.search(
            r"\bclaimed\b", f"{f.get('quote') or ''} {fact_text(f)}", re.I
        ):
            return f"claimed Practo profile (fact {evidence.short_id(f['id'])})"
    return None


def custom_website(b: Mapping[str, Any], facts: Sequence[Row]) -> str | None:
    """A live site on its own domain, not a free builder sub-domain."""
    status = next((vget(f.get("value"), "status") for f in evidence.by_field(facts, "website_status")), None)
    domain = str(b.get("web_domain") or "").lower()
    host = evidence.host_of(b.get("website"))
    if status != "live" or not domain:
        return None
    if any(domain == d or domain.endswith("." + d) or host.endswith("." + d) for d in FREE_BUILDER_DOMAINS):
        return None
    return f"live site on {domain}"


def premium_price(facts: Sequence[Row], seg: Segment) -> Row | None:
    for f in evidence.by_field(facts, "price_point"):
        value = f.get("value") or {}
        amount = vget(value, "amount", "price")
        currency = str(vget(value, "currency") or seg.currency).upper()
        try:
            amount_f = float(amount)
        except (TypeError, ValueError):
            continue
        if currency == seg.currency and amount_f >= seg.premium_threshold(str(vget(value, "item") or "")):
            return f
    return None


def can_pay_points(
    b: Mapping[str, Any],
    facts: Sequence[Row],
    active: Sequence[Mapping[str, Any]],
    seg: Segment,
    cfg: ScoringConfig,
) -> tuple[float, list[str]]:
    """0 to 30 from measurable signs the business can pay Rs 50K or more (11.3)."""
    total, why, _ = can_pay_breakdown(b, facts, active, seg, cfg)
    return total, why


def can_pay_breakdown(
    b: Mapping[str, Any],
    facts: Sequence[Row],
    active: Sequence[Mapping[str, Any]],
    seg: Segment,
    cfg: ScoringConfig,
) -> tuple[float, list[str], list[str]]:
    """`can_pay_points` plus the proxy keys the business earned (`branches_2plus`, `pays_for_software`, ...).

    The keys go into `scores.reasons.can_pay_proxies`, where the learning loop measures each proxy's
    outcomes (Step 16.2). A matched tier is listed even when its points are 0, so it can still be learned.
    """
    why: list[str] = []
    proxies: list[str] = []
    total = 0.0
    for label, group, column, fact_field, tiers in (
        ("branches_count", "branches", "branches_count", "branches", cfg.branches),
        ("staff_count", "staff", "staff_count", "staff_or_doctors", cfg.staff),
        ("review_count", "reviews", "review_count", "", cfg.reviews),
    ):
        value = business_count(b, facts, column, fact_field) if fact_field else b.get(column)
        tier = _tier_points(value, tiers)
        if tier is None:
            continue
        proxies.append(f"{group}_{int(tier.min)}plus")
        if tier.points:
            total += tier.points
            why.append(f"{label}={value} (+{tier.points:g})")
    price = premium_price(facts, seg)
    if price is not None:
        total += cfg.premium_price
        proxies.append("premium_price")
        why.append(
            f"premium price {fact_text(price)[:40]} (fact {evidence.short_id(price['id'])}, +{cfg.premium_price:g})"
        )
    paid = pays_for_software(facts)
    if paid:
        total += cfg.pays_for_software
        proxies.append("pays_for_software")
        why.append(f"already pays for software: {paid} (+{cfg.pays_for_software:g})")
    site = custom_website(b, facts)
    if site:
        total += cfg.custom_website
        proxies.append("custom_website")
        why.append(f"custom website: {site} (+{cfg.custom_website:g})")
    sub = b.get("subcategory") or seg.subcategory_for(b.get("category"), str(b.get("name") or ""))
    ticket = seg.ticket_points(sub)
    if ticket:
        total += ticket
        why.append(f"ticket class {sub} (+{ticket})")
    funding = [s for s in active if s["type"] == "funding"]
    if funding:
        total += cfg.funding
        proxies.append("funding")
        why.append(f"funding signal {evidence.short_id(funding[0]['id'])} (+{cfg.funding:g})")
    retainer = retainer_reason(b, facts, active, seg)
    if retainer and cfg.retainer_fit:
        total += cfg.retainer_fit
        proxies.append("retainer_fit")
        why.append(f"retainer fit: {retainer} (+{cfg.retainer_fit:g})")
    staff = business_count(b, facts, "staff_count", "staff_or_doctors")
    if staff is not None and staff >= TOO_BIG_STAFF and cfg.too_big:
        total += cfg.too_big
        proxies.append("too_big")
        why.append(f"staff_count={staff}: rarely buys from a young studio ({cfg.too_big:g})")
    return max(0.0, min(total, cfg.can_pay_cap)), why, proxies


TOO_BIG_STAFF: Final = 200
STORE_TOOLS: Final = frozenset({"Shopify", "WooCommerce", "Magento", "BigCommerce"})


def retainer_reason(
    b: Mapping[str, Any], facts: Sequence[Row], active: Sequence[Mapping[str, Any]], seg: Segment
) -> str | None:
    """Why this business would likely keep paying monthly (13 Nov 2026: the founder wants retainers)."""
    if seg.domain == "partners":
        return "a partner agency brings client work every month"
    for s in active:
        details = s.get("details") or {}
        if s["type"] == "hiring_builder" and not details.get("contract"):
            return "hiring a full-time builder: the salary budget can become a monthly retainer"
    for f in evidence.by_field(facts, "tech_stack"):
        value = f.get("value")
        listed = value.get("tools") if isinstance(value, dict) else value  # older facts hold the list itself
        tools = {str(t.get("tool")) for t in listed or [] if isinstance(t, dict)}
        store = sorted(tools & STORE_TOOLS)
        if store:
            return f"runs an online store on {store[0]}: ongoing changes and automation"
    return None


@dataclass(frozen=True)
class Reach:
    value: float
    kind: str  # decision_maker_mobile, business_mobile, landline, email, form, none
    contact: Row | None
    reason: str


def usable_contacts(contacts: Iterable[Row], now: datetime, suppressed: Suppression | None = None) -> list[Row]:
    """Verified, not do-not-contact, not suppressed, and Google listing data younger than 30 days."""
    out = []
    for c in contacts:
        if not c.get("verified") or c.get("do_not_contact") or not (c.get("phone_e164") or c.get("email")):
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


def reach_of(
    contacts: Iterable[Row],
    facts: Sequence[Row],
    cfg: ScoringConfig,
    now: datetime,
    suppressed: Suppression | None = None,
    *,
    email_first: bool = False,
) -> Reach:
    """How we can reach the decision maker, as a multiplier from 0 to 1 (11.5)."""
    usable = usable_contacts(contacts, now, suppressed)
    if email_first:
        return _reach_email_first(usable, facts, cfg)
    phones = [c for c in usable if c.get("phone_e164")]
    for kind, test in (
        (
            "decision_maker_mobile",
            lambda c: c.get("is_decision_maker") and c.get("phone_type") == "mobile" and c.get("source") == "website",
        ),
        ("business_mobile", lambda c: c.get("phone_type") == "mobile"),
        ("landline", lambda c: True),
    ):
        hit = next((c for c in phones if test(c)), None)
        if hit is not None:
            return Reach(
                cfg.reach[kind],
                kind,
                hit,
                f"{kind.replace('_', ' ')} (contact {evidence.short_id(hit['id'])}, {hit.get('source')})",
            )
    mail = next((c for c in usable if c.get("email")), None)
    if mail is not None:
        return Reach(cfg.reach["email"], "email", mail, f"email only (contact {evidence.short_id(mail['id'])})")
    form = evidence.by_field(facts, "contact_form_url")
    if form:
        return Reach(cfg.reach["form"], "form", None, f"contact form only (fact {evidence.short_id(form[0]['id'])})")
    return Reach(cfg.reach["none"], "none", None, "no usable contact")


def _reach_email_first(usable: Sequence[Row], facts: Sequence[Row], cfg: ScoringConfig) -> Reach:
    """Email-first countries: a published address of a decision maker, then the company's, then a form, then a
    phone (a call). Never a guessed address."""
    share = {**{"decision_maker_email": 1.0, "email": 0.7, "phone": 0.4, "form": 0.3, "none": 0.0},
             **cfg.reach_email_first}  # fmt: skip
    mails = [c for c in usable if c.get("email")]
    boss = next((c for c in mails if c.get("is_decision_maker")), None)
    if boss is not None:
        why = f"decision maker email (contact {evidence.short_id(boss['id'])}, {boss.get('source')})"
        return Reach(share["decision_maker_email"], "decision_maker_email", boss, why)
    if mails:
        return Reach(share["email"], "email", mails[0], f"company email (contact {evidence.short_id(mails[0]['id'])})")
    form = evidence.by_field(facts, "contact_form_url")
    if form:
        return Reach(share["form"], "form", None, f"contact form only (fact {evidence.short_id(form[0]['id'])})")
    phone = next((c for c in usable if c.get("phone_e164")), None)
    if phone is not None:
        kind = "business_mobile" if phone.get("phone_type") == "mobile" else "landline"
        return Reach(share["phone"], kind, phone, f"phone only, a call (contact {evidence.short_id(phone['id'])})")
    return Reach(share["none"], "none", None, "no usable contact")


def pitch_mode_of(kept: Sequence[Mapping[str, Any]]) -> str:
    """stated_need beats visible_pain beats fit_only (A.12.4)."""
    cats = {s.get("category") or SIGNAL_CATEGORY.get(str(s["type"])) for s in kept}
    if "stated_need" in cats:
        return "stated_need"
    if "visible_pain" in cats:
        return "visible_pain"
    return "fit_only"


def angle_for_type(seg: Segment, signal_type: str) -> str | None:
    return next((a.key for a in seg.angles if signal_type in a.signals), None)


def pick_angle(mode: str, kept: Sequence[Mapping[str, Any]], seg: Segment) -> str:
    """11.8.2: the need itself, else the strongest pain; growth only when it is the strongest signal."""
    if mode == "stated_need":
        return "build_what_they_asked"
    strongest = kept[0] if kept else None
    if strongest is not None and SIGNAL_CATEGORY.get(str(strongest["type"])) == "growth":
        return seg.growth_angle()
    if mode == "visible_pain":
        pains = [s for s in kept if SIGNAL_CATEGORY.get(str(s["type"])) == "visible_pain"]
        types = {str(s["type"]) for s in pains}
        top = str(pains[0]["type"])
        if top == "no_booking" and "ads_running" in types:
            top = "ads_running"  # ads with or without online booking: the ad leads angle
        return angle_for_type(seg, top) or seg.fit_only_angle()
    return seg.fit_only_angle()


def grade_of(total: float, cfg: ScoringConfig) -> str:
    g = cfg.grades
    return "A" if total >= g["A"] else "B" if total >= g["B"] else "C" if total >= g["C"] else "D"


# =========================================================================
# One business
# =========================================================================


@dataclass
class ScoreResult:
    fit: int
    can_pay: float
    intent: float
    reach: float
    total: int
    grade: str  # the rule grade
    pitch_mode: str
    angle: str
    test_group: str
    reasons: dict[str, Any]
    kept: list[dict[str, Any]]
    reach_kind: str
    best_contact: Row | None
    basis: str
    note: str  # rule-built "why this lead" (11.10.5)
    evidence_ids: frozenset[str] = frozenset()  # verified fact ids and active signal ids
    has_email: bool = False


def score_business(
    b: Mapping[str, Any],
    facts: Sequence[Row],
    signals: Sequence[Mapping[str, Any]],
    contacts: Sequence[Row],
    seg: Segment,
    cfg: ScoringConfig,
    excl: Exclusions,
    now: datetime,
    suppressed: Suppression | None = None,
) -> ScoreResult:
    """The whole Step 11 rule score for one business (no AI)."""
    active = [s for s in signals if evidence.is_active(s, now)]
    stated = next(
        (s for s in active if (s.get("category") or SIGNAL_CATEGORY.get(str(s["type"]))) == "stated_need"), None
    )
    fit, fit_why = fit_gate(b, facts, seg, excl, stated)
    can_pay, pay_why, pay_proxies = can_pay_breakdown(b, facts, active, seg, cfg)
    # Money signals feed can-pay; a segment that gives them points (firms: "just funded") also counts them as need.
    intent, kept = intent_score(
        [
            s
            for s in active
            if (s.get("category") or SIGNAL_CATEGORY.get(str(s["type"]))) != "money"
            or float(cast(dict[str, float], seg.signal_points).get(str(s["type"])) or 0) > 0
        ],
        now,
        cfg,
        seg,
    )
    reach = reach_of(contacts, facts, cfg, now, suppressed, email_first=seg.outreach_channel == "email")
    fit_bonus = cfg.fit_bonus.get(fit, 0.0)
    pay_part = can_pay / cfg.can_pay_cap * cfg.can_pay_points if cfg.can_pay_cap else 0.0
    total = min(100, round_half_up(round(intent, 2) + pay_part + fit_bonus + reach.value * cfg.reach_points))
    gate_failed = fit < cfg.fit_gate
    grade = "D" if gate_failed or reach.value <= 0 else grade_of(total, cfg)
    mode = pitch_mode_of(kept)
    angle = pick_angle(mode, kept, seg)
    fact_ids = [str(f["id"]) for f in facts]
    signal_ids = [str(s["id"]) for s in active]
    basis = evidence.basis_hash(fact_ids, signal_ids, total)
    reasons: dict[str, Any] = {
        "fit": fit_why,
        "fit_gate_failed": gate_failed,
        "can_pay": pay_why,
        "can_pay_proxies": pay_proxies,
        "intent": [{"signal_id": str(s["id"]), "type": s["type"], "value": round(s["value"], 1)} for s in kept],
        "reach": [reach.reason],
        "reach_kind": reach.kind,
        "rule_grade": grade,
        "angle": angle,
        "basis": basis,
        # the four parts of the total as shown in the app and the email (s2.0)
        "parts": {
            "need": round(intent, 1),
            "can_pay": round(pay_part, 1),
            "fit": fit_bonus,
            "reach": round(reach.value * cfg.reach_points, 1),
        },
    }
    result = ScoreResult(
        fit=fit,
        can_pay=round(can_pay, 2),
        intent=round(intent, 1),
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
        note="",
        evidence_ids=frozenset(fact_ids) | frozenset(signal_ids),
        has_email=any(c.get("email") for c in usable_contacts(contacts, now, suppressed)),
    )
    result.note = rule_note(result, b, facts, now)
    return result


# =========================================================================
# 11.10.5 Rule-built note ("Why this lead")
# =========================================================================

SOURCE_LABELS: Final[dict[str, str]] = {
    "apna": "on Apna",
    "internshala": "on Internshala",
    "naukri": "on Naukri",
    "adzuna": "on a job board",
    "careers_watch": "on their careers page",
    "places": "in Google reviews",
    "maps_reviews": "in Google reviews",
    "practo": "in Practo patient stories",
    "grounded_search": "in a public post",
    "inbox": "in a public post",
    "gdelt": "in the news",
    "research": "on their website",
    "manual": "in the ad libraries",
    "overture": "on the map",
    "legacy": "in our earlier research",
}


def _age(observed_at: datetime, now: datetime) -> str:
    days = max(0, (now - observed_at).days)
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


PAIN_WORDS: Final[dict[str, str]] = {
    "unanswered_calls": "unanswered calls",
    "slow_replies": "slow replies",
    "slow_whatsapp": "slow WhatsApp replies",
    "booking_trouble": "booking trouble",
    "long_wait": "long waits",
    "rude_front_desk": "a rude front desk",
}


def _pain_words(flags: Any) -> str:
    words = [PAIN_WORDS[f] for f in flags or [] if f in PAIN_WORDS][:2]
    return " and ".join(words) if words else "missed calls or slow replies"


def _signal_line(s: Mapping[str, Any], now: datetime) -> str:
    details = s.get("details") or {}
    where = SOURCE_LABELS.get(str(s.get("source") or ""), "")
    age = _age(s["observed_at"], now)
    what = str(details.get("role") or details.get("title") or details.get("need") or "").strip()
    kind = str(s["type"])
    if kind == "hiring_frontdesk":
        text = f"Hiring {what or 'front desk staff'} {where} {age}"
    elif kind == "hiring_builder":
        text = f"Hiring a {what or 'developer'} {where} {age}"
    elif kind == "public_ask":
        text = f"Asked publicly for {what or 'a tech partner'} {age}"
    elif kind == "tender":
        text = f"Tender out for {what or 'software work'}"
    elif kind == "review_pain":
        where = "Practo patient stories" if s.get("source") == "practo" else "Google reviews"
        text = f"Recent {where} mention {_pain_words(details.get('flags'))}"
    elif kind == "ads_running":
        text = "Running ads"
    elif kind == "no_booking":
        text = "No online booking, WhatsApp or chat on the website"
    elif kind == "slow_site":
        text = "Slow mobile website"
    elif kind == "new_branch":
        text = f"Opening a new branch, seen {where or 'online'} {age}"
    elif kind == "new_place":
        text = f"New on the map {age}"
    else:
        text = f"In the news {age}"
    return re.sub(r"\s+", " ", text).strip()


def rule_note(result: ScoreResult, b: Mapping[str, Any], facts: Sequence[Row], now: datetime) -> str:
    """Two plain sentences at most, built only from the reasons (no AI, no dashes)."""
    first = _signal_line(result.kept[0], now) if result.kept else "No buying signal yet, but a strong fit"
    proofs: list[str] = []
    reviews = b.get("review_count")
    branches = business_count(b, facts, "branches_count", "branches")
    staff = business_count(b, facts, "staff_count", "staff_or_doctors")
    if reviews:
        proofs.append(f"{reviews} Google reviews")
    if branches and branches >= 2:
        proofs.append(f"{branches} branches")
    if staff and staff >= 3:
        proofs.append(f"{staff} staff on the team page")
    tail = ""
    if proofs:
        tail = " and ".join([", ".join(proofs[:-1]), proofs[-1]] if len(proofs) > 1 else proofs)
        tail = f", and {tail}" if result.kept else f": {tail}"
    note = f"{first}{tail}."
    return note.replace("\u2013", ",").replace("\u2014", ",")[:280]


# =========================================================================
# Persisting (11.9) and the stage entry point
# =========================================================================


@dataclass
class Scored:
    business: Row
    segment: Segment
    result: ScoreResult
    score_id: str
    is_new_row: bool
    final_grade: str  # the stored grade (the judge's when the row is reused after a judgement)
    final_angle: str  # the judge's angle when it changed it, else the rule angle
    capped: bool = False


def latest_scores(business_ids: Sequence[str], conn: Connection[Any] | None = None) -> dict[str, Row]:
    if not business_ids:
        return {}
    rows = db.fetch_all(
        "select distinct on (business_id) * from public.scores where business_id = any(%s::uuid[]) "
        "order by business_id, computed_at desc",
        [list(business_ids)],
        conn=conn,
    )
    return {str(r["business_id"]): {**r, "id": str(r["id"])} for r in rows}


def same_result(row: Mapping[str, Any] | None, r: ScoreResult) -> bool:
    """True when the latest stored row already says exactly this (then no new row is written)."""
    if row is None or row.get("version") != SCORE_VERSION:
        return False
    reasons = row.get("reasons") or {}
    return (
        reasons.get("basis") == r.basis
        and reasons.get("rule_grade") == r.grade
        and reasons.get("angle") == r.angle
        and row.get("pitch_mode") == r.pitch_mode
        and int(row.get("fit") or 0) == r.fit
        and math.isclose(float(row.get("can_pay") or 0), r.can_pay, abs_tol=0.005)
        and math.isclose(float(row.get("intent") or 0), r.intent, abs_tol=0.005)
        and math.isclose(float(row.get("reach") or 0), r.reach, abs_tol=0.005)
        # the judge may have moved the stored total (s2.0); the rule total is kept in reasons
        and math.isclose(float(reasons.get("rule_total", row.get("total")) or 0), r.total, abs_tol=0.005)
    )


_PENDING: Final = """
select b.id
  from public.businesses b
 where b.segment_id = any(%(segments)s)
   and b.status not in ('rejected', 'suppressed', 'candidate', 'queued')
   and (b.status = any(%(statuses)s)
        or exists (select 1 from public.leads l where l.business_id = b.id and l.stage = 'new'))
   and not exists (select 1 from public.facts f where f.business_id = b.id and f.verified_at is null)
 order by b.researched_at desc nulls last, b.id
 limit %(limit)s
"""


def pending_ids(
    segment_ids: Sequence[str], limit: int | None, include_dormant: bool, conn: Connection[Any] | None = None
) -> list[str]:
    """Researched and qualified businesses (plus dormant ones with --all), and any with a new lead."""
    statuses = ["researched", "qualified", *(["dormant"] if include_dormant else [])]
    rows = db.fetch_all(_PENDING, {"segments": list(segment_ids), "statuses": statuses, "limit": limit}, conn=conn)
    return [str(r["id"]) for r in rows]


def segment_configs(segments: Mapping[str, Segment], conn: Connection[Any] | None = None) -> dict[str, ScoringConfig]:
    """Resolved configs with the weights in force: `learn.weights.use_weights` inside the eval gate, else
    `settings.score_weights` completed with the YAML defaults (Step 16.3)."""
    weights = active_document(conn)
    return {sid: ScoringConfig.for_segment(seg, weights) for sid, seg in segments.items()}


@dataclass
class Scorer:
    """Score one business at a time, exactly as `nlead score` would, without writing anything.

    Used by the eval gate and replays (Steps 16.4 and 17). Weights are read on every call, so a
    `use_weights(doc)` block scores with the proposed weights.
    """

    segments: Mapping[str, Segment]
    excl: Exclusions
    suppressed: Suppression

    @classmethod
    def load(cls, conn: Connection[Any] | None = None) -> Scorer:
        return cls(load_segments(get_settings().segments_dir), Exclusions.load(), Suppression.load(conn))

    def score_rows(
        self,
        b: Mapping[str, Any],
        facts: Sequence[Row],
        signals: Sequence[Mapping[str, Any]],
        contacts: Sequence[Row],
        seg: Segment,
        *,
        now: datetime | None = None,
    ) -> ScoreResult:
        cfg = ScoringConfig.for_segment(seg, active_document())
        return score_business(
            b, facts, signals, contacts, seg, cfg, self.excl, now or datetime.now(UTC), self.suppressed
        )

    def score(
        self, business_id: str, *, now: datetime | None = None, conn: Connection[Any] | None = None
    ) -> ScoreResult | None:
        """None when the business or its segment no longer exists."""
        ids = [business_id]
        b = evidence.businesses(ids, conn=conn).get(business_id)
        seg = self.segments.get(str((b or {}).get("segment_id")))
        if b is None or seg is None:
            return None
        return self.score_rows(
            b,
            evidence.verified_facts(ids, conn=conn).get(business_id, []),
            evidence.signals_for(ids, conn=conn).get(business_id, []),
            evidence.contacts_for(ids, conn=conn).get(business_id, []),
            seg,
            now=now,
        )


def enabled_segments(rc: RunContext, conn: Connection[Any] | None = None) -> dict[str, Segment]:
    """The YAML segments asked for, minus any switched off in the database (kill switch)."""
    segments = load_segments(get_settings().segments_dir)
    wanted = set(rc.opts.segments) if rc.opts.segments else set(segments)
    rows = db.fetch_all("select id, enabled from public.segments", conn=conn)
    off = {r["id"] for r in rows if not r["enabled"]}
    return {k: v for k, v in segments.items() if k in wanted and k not in off}


def score_ids(
    ids: Sequence[str],
    segments: Mapping[str, Segment],
    configs: Mapping[str, ScoringConfig],
    excl: Exclusions,
    suppressed: Suppression,
    now: datetime,
    errors: Counter[str] | None = None,
) -> list[Scored]:
    """Score a chunk of businesses in memory."""
    biz = evidence.businesses(ids)
    facts = evidence.verified_facts(ids)
    signals = evidence.signals_for(ids)
    contacts = evidence.contacts_for(ids)
    latest = latest_scores(ids)
    out: list[Scored] = []
    for bid in ids:
        b = biz.get(bid)
        seg = segments.get(str((b or {}).get("segment_id")))
        if b is None or seg is None:
            continue
        try:
            r = score_business(
                b,
                facts.get(bid, []),
                signals.get(bid, []),
                contacts.get(bid, []),
                seg,
                configs[seg.id],
                excl,
                now,
                suppressed,
            )
        except Exception as exc:  # one odd record must not stop the run; it is scored again next run
            if errors is not None:
                errors["errors"] += 1
            log.error("score.business_failed", business_id=bid, error=f"{type(exc).__name__}: {exc}")
            continue
        prev = latest.get(bid)
        if prev is not None and same_result(prev, r):
            judged = (prev.get("reasons") or {}).get("judge") or {}
            out.append(Scored(b, seg, r, prev["id"], False, str(prev["grade"]), str(judged.get("angle") or r.angle)))
        else:
            out.append(Scored(b, seg, r, str(uuid.uuid4()), True, r.grade, r.angle))
    return out


def insert_scores(conn: Connection[Any], items: Sequence[Scored], now: datetime) -> None:
    rows = [
        {
            "id": s.score_id,
            "business_id": str(s.business["id"]),
            "version": SCORE_VERSION,
            "fit": s.result.fit,
            "can_pay": s.result.can_pay,
            "intent": s.result.intent,
            "reach": s.result.reach,
            "total": s.result.total,
            "grade": s.result.grade,
            "pitch_mode": s.result.pitch_mode,
            "reasons": db.Jsonb({**s.result.reasons, **({"capped": "fit_only_cap"} if s.capped else {})}),
            "note": s.result.note,
            "at": now,
        }
        for s in items
        if s.is_new_row
    ]
    if rows:
        conn.cursor().executemany(
            "insert into public.scores (id, business_id, version, fit, can_pay, intent, reach, total, grade, "
            "pitch_mode, reasons, judge_note, computed_at) values (%(id)s, %(business_id)s, %(version)s, %(fit)s, "
            "%(can_pay)s, %(intent)s, %(reach)s, %(total)s, %(grade)s, %(pitch_mode)s, %(reasons)s, %(note)s, %(at)s)",
            rows,
        )


def business_status(grade: str, capped: bool) -> str:
    """A and B are qualified, C waits as researched, D sleeps 90 days as dormant (11.9)."""
    if grade in ("A", "B"):
        return "researched" if capped else "qualified"
    return "researched" if grade == "C" else "dormant"


def run(rc: RunContext, *, all_businesses: bool = False, fetch: leads.Fetcher | None = None) -> dict[str, Any]:
    """`nlead score`: score, grade, cap fit-only leads and create or update leads (Steps 11.9 and 11.11)."""
    now = datetime.now(UTC)
    segments = enabled_segments(rc)
    configs = segment_configs(segments)
    excl = Exclusions.load()
    suppressed = Suppression.load()
    stats: Counter[str] = Counter()
    ids = pending_ids(list(segments), rc.opts.limit, all_businesses)
    scored: list[Scored] = []
    for start in range(0, len(ids), CHUNK):
        scored += score_ids(ids[start : start + CHUNK], segments, configs, excl, suppressed, now, errors=stats)
    states = leads.load_states([str(s.business["id"]) for s in scored])
    pct = {sid: cfg.fit_only_max_pct for sid, cfg in configs.items()}
    floor = {sid: cfg.fit_only_min_per_day for sid, cfg in configs.items()}
    plans = leads.plan_all(candidates(scored), states, pct, now, fetch=fetch, stats=stats, fit_only_min=floor)
    for s in scored:
        s.capped = plans.capped(str(s.business["id"]))
        stats[f"grade.{s.final_grade}"] += 1
        stats["scores.new_rows" if s.is_new_row else "scores.unchanged"] += 1
    stats["businesses"] = len(scored)
    if not rc.opts.dry_run:
        context = {"run_id": rc.run_id, "stage": "score"}
        for start in range(0, len(scored), CHUNK):
            chunk = scored[start : start + CHUNK]
            with db.tx("engine", context) as conn:
                insert_scores(conn, chunk, now)
                conn.cursor().executemany(
                    "update public.businesses set status = %(status)s, reject_reason = null "
                    "where id = %(id)s and status <> %(status)s",
                    [{"id": str(s.business["id"]), "status": business_status(s.final_grade, s.capped)} for s in chunk],
                )
        with db.tx("engine", context) as conn:  # after every score row exists (leads.score_id references it)
            leads.apply(conn, plans, now)
    result = dict(sorted(stats.items()))
    rc.stats["score"] = result
    log.info("score.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result


def candidate(s: Scored) -> leads.Candidate:
    """What the lead rules need from one score."""
    return leads.Candidate(
        business_id=str(s.business["id"]),
        segment_id=s.segment.id,
        score_id=s.score_id,
        grade=s.final_grade,
        total=s.result.total,
        pitch_mode=s.result.pitch_mode,
        angle=s.final_angle,
        test_group=make_test_group(s.segment.id, cast(PitchMode, s.result.pitch_mode), s.final_angle),
        reach_kind=s.result.reach_kind,
        best_contact=s.result.best_contact,
        region=s.segment.country,
        evidence_ids=s.result.evidence_ids,
        has_email=s.result.has_email,
    )


def candidates(scored: Sequence[Scored]) -> list[leads.Candidate]:
    return [candidate(s) for s in scored]
