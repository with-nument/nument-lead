"""Rule pre-filter and today's research queue (Step 8). Free rules only: no AI, no paid API.

Every candidate business goes through the rules R1 to R11 in order; the first that fails decides. Rejections
are permanent until a new signal arrives, so a rule that is not sure says "skip for now" instead. Businesses that
pass get a priority (Step 8.7), and today's queue is filled from them:
- at most `settings.research_per_day` (300) a day, minus what was already queued today;
- at most what the money left today pays for (80% of it, the rest is kept for the morning run);
- each segment up to its `segments.daily_quota` (the database value, A.13.5 rule 11), scaled down
  proportionally when fewer slots are left, and at least 10% of the slots for every segment that has work;
- fit-only businesses (no active signal) at most 10% of the slots (A.12.4);
- slots a segment cannot fill go to the best businesses of the other segments.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db
from ..budget import Budget
from ..logging import get_logger
from ..models import CLOSED_STAGES
from ..normalize import plain_text
from ..segments import Rule, Segment, load_yaml_config
from ..sources import health
from .runs import RunContext
from .selection import active_segments, daily_quotas

log = get_logger()

FIT_ONLY_SHARE = 0.10  # default; settings.prefilter.fit_only_share overrides it (0 to 1)
MIN_SEGMENT_SHARE = 0.10
MONEY_SHARE = 0.80  # keep 20% of today's money for the morning run (Step 8.8)
DEFAULT_COST_PER_ITEM_INR = 2.1  # Balanced tier estimate; tune after week 1 (setting research.est_cost_inr)
COOLDOWN_DAYS = 90
RECENT_DAYS = 90
STALE_PLACES_DAYS = 30
REGISTRY_SOURCES = frozenset({"art_registry"})

Verdict = tuple[str, str | None]  # ("pass" | "reject" | "skip" | "suppress", rule code)


# ---------------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------------


@dataclass
class Exclusions:
    chain_names: list[re.Pattern[str]]
    chain_domains: set[str]
    hospital: list[re.Pattern[str]]
    agency: list[re.Pattern[str]]
    max_branches: int
    non_target: list[re.Pattern[str]] = field(default_factory=list)

    @classmethod
    def load(cls) -> Exclusions:
        cfg = load_yaml_config("exclusions")
        return cls(
            chain_names=[_phrase(c["name"]) for c in cfg.get("chains", []) if c.get("name")],
            chain_domains={d.lower() for c in cfg.get("chains", []) for d in c.get("domains", []) or []},
            hospital=[_phrase(k) for k in cfg.get("hospital_keywords", [])],
            agency=[_phrase(k) for k in cfg.get("agency_keywords", [])],
            max_branches=int(cfg.get("max_branches", 10)),
            non_target=[_phrase(k) for k in cfg.get("non_target_keywords", [])],
        )


def _phrase(text: str) -> re.Pattern[str]:
    """Whole-word match (Step 3.6). Names keep their legal suffixes on both sides, so the chain "DLF Limited"
    matches "DLF Limited, Gurugram" but never "DLF Phase 4 Skin Clinic"."""
    words = [re.escape(w) for w in plain_text(text).split() if w]
    return re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)")


@dataclass
class World:
    """Everything the rules need, loaded in a few bulk queries."""

    signals: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    phones: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    emails: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    open_lead: set[str] = field(default_factory=set)
    last_closed: dict[str, datetime] = field(default_factory=dict)
    record_sources: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    facts: dict[str, dict[str, dict[str, Any]]] = field(default_factory=lambda: defaultdict(dict))
    suppressed_phones: set[str] = field(default_factory=set)
    suppressed_emails: set[str] = field(default_factory=set)
    suppressed_domains: set[str] = field(default_factory=set)


CANDIDATES_SQL = """
select b.id::text as id, b.segment_id, b.name, b.norm_name, b.website, b.web_domain, b.city, b.category,
       b.subcategory, b.branches_count, b.review_count, b.places_fetched_at, b.status, b.researched_at,
       b.queued_at, b.extra
from public.businesses b
where b.segment_id = any(%(segments)s)
  and (b.status in ('candidate', 'researched', 'qualified')
       or (b.status = 'queued' and b.queued_at < %(today)s))
"""


def load_world(ids: list[str], fact_keys: set[str]) -> World:
    world = World()
    if not ids:
        return world
    for row in db.fetch_all(
        "select business_id::text as bid, type, category, points, observed_at, expires_at, created_at "
        "from public.signals where business_id = any(%s) and expires_at > now()",
        [ids],
    ):
        world.signals[row["bid"]].append(row)
    for row in db.fetch_all(
        "select business_id::text as bid, phone_e164, lower(email) as email from public.contacts "
        "where business_id = any(%s) and not do_not_contact",
        [ids],
    ):
        if row["phone_e164"]:
            world.phones[row["bid"]].add(row["phone_e164"])
        if row["email"]:
            world.emails[row["bid"]].add(row["email"])
    for row in db.fetch_all(
        "select business_id::text as bid, stage, updated_at from public.leads where business_id = any(%s)", [ids]
    ):
        if row["stage"] in CLOSED_STAGES:
            prev = world.last_closed.get(row["bid"])
            if prev is None or row["updated_at"] > prev:
                world.last_closed[row["bid"]] = row["updated_at"]
        else:
            world.open_lead.add(row["bid"])
    for row in db.fetch_all(
        "select distinct business_id::text as bid, source from public.source_records where business_id = any(%s)",
        [ids],
    ):
        world.record_sources[row["bid"]].add(row["source"])
    if fact_keys:
        for row in db.fetch_all(
            "select distinct on (business_id, field) business_id::text as bid, field, value from public.facts "
            "where business_id = any(%s) and field = any(%s) and verified and coalesce(verify_score, 0) >= 0 "
            "order by business_id, field, created_at desc",
            [ids, sorted(fact_keys)],
        ):
            world.facts[row["bid"]][row["field"]] = row["value"]
    for row in db.fetch_all("select phone_e164, lower(email) as email, web_domain from public.suppression"):
        if row["phone_e164"]:
            world.suppressed_phones.add(row["phone_e164"])
        if row["email"]:
            world.suppressed_emails.add(row["email"])
        if row["web_domain"]:
            world.suppressed_domains.add(row["web_domain"].lower())
    return world


# ---------------------------------------------------------------------------------------------------
# Rules (Step 8.5)
# ---------------------------------------------------------------------------------------------------


def _compare(value: Any, op: str, target: Any) -> bool | None:
    if op == "exists":
        return value is not None
    if value is None:
        return None
    try:
        if op == ">=":
            return float(value) >= float(target)
        if op == "<=":
            return float(value) <= float(target)
        if op == "==":
            return bool(value == target)
        if op == "!=":
            return bool(value != target)
        if op == "in":
            return value in (target or [])
        if op == "not_in":
            return value not in (target or [])
    except (TypeError, ValueError):
        return None
    return None


def eval_size_rule(rule: Rule, b: dict[str, Any], world: World, now: datetime) -> bool | None:
    """True / False when known, None when the data is not there yet (wait, do not reject)."""
    bid = b["id"]
    if rule.source == "business":
        value = b.get(rule.key)
        if rule.key in ("review_count", "rating"):
            fetched = b.get("places_fetched_at")
            if fetched is None or fetched < now - timedelta(days=STALE_PLACES_DAYS):
                value = None  # Places numbers older than 30 days count as unknown (Step 8.11)
        return _compare(value, rule.op, rule.value)
    if rule.source == "fact":
        fact = world.facts[bid].get(rule.key)
        value = fact.get(rule.field) if isinstance(fact, dict) and rule.field else fact
        return _compare(value, rule.op, rule.value)
    if rule.source == "signal":
        return any(s["type"] == rule.key for s in world.signals.get(bid, []))
    if rule.source == "registry":
        sources = world.record_sources.get(bid, set())
        registries = (b.get("extra") or {}).get("registries", {})
        if rule.key == "*":
            return bool(sources & REGISTRY_SOURCES) or bool(registries)
        return rule.key in sources or rule.key in registries
    return None


def size_verdict(b: dict[str, Any], seg: Segment, world: World, now: datetime) -> bool | None:
    results = [eval_size_rule(r, b, world, now) for r in seg.size_rules.any_of]
    if any(r is True for r in results):
        return True
    return None if any(r is None for r in results) else False


def apply_rules(b: dict[str, Any], seg: Segment | None, excl: Exclusions, world: World, now: datetime) -> Verdict:
    bid = b["id"]
    sigs = world.signals.get(bid, [])
    has_stated_need = any(s["category"] == "stated_need" for s in sigs)
    name = plain_text(b.get("name"))
    # R1: segment enabled and the city is one of its cities
    if seg is None or b.get("city") not in {c.name for c in seg.cities}:
        return "skip", "R1_segment"
    # R2: category or subcategory allowed. Unknown category waits, unless a classified signal vouches for it.
    if b.get("category") or b.get("subcategory"):
        if not seg.is_type_match(b.get("category"), b.get("subcategory")):
            return "reject", "R2_category"
    elif not sigs:
        return "skip", "R2_category_unknown"
    if any(p.search(name) for p in excl.non_target):  # the map category is wrong: "Home Centre - Furniture Store"
        return "reject", "R2_not_target"
    # R3: big chains, hospitals, too many branches
    domain = (b.get("web_domain") or "").lower()
    if domain in excl.chain_domains or any(p.search(name) for p in excl.chain_names):
        return "reject", "R3_excluded"
    if any(p.search(name) for p in excl.hospital):
        return "reject", "R3_excluded"
    if (b.get("branches_count") or 0) >= excl.max_branches:
        return "reject", "R3_excluded"
    # R4: agencies and vendors sell what we sell
    if any(p.search(name) or p.search(plain_text(b.get("category"))) for p in excl.agency):
        return "reject", "R4_agency"
    # R5: suppression list (phones, emails, domain)
    if (
        (domain and domain in world.suppressed_domains)
        or world.phones.get(bid, set()) & world.suppressed_phones
        or world.emails.get(bid, set()) & world.suppressed_emails
    ):
        return "suppress", "R5_suppressed"
    # R6: an open lead already exists
    if bid in world.open_lead:
        return "skip", "R6_open_lead"
    # R7: closed in the last 90 days, unless a new stated need arrived after that
    closed = world.last_closed.get(bid)
    new_need = closed is not None and any(s["category"] == "stated_need" and s["created_at"] > closed for s in sigs)
    if closed and closed > now - timedelta(days=COOLDOWN_DAYS) and not new_need:
        return "skip", "R7_cooldown"
    # R8: researched in the last 90 days, unless a new active signal arrived after that
    researched = b.get("researched_at")
    new_signal = researched is not None and any(s["created_at"] > researched for s in sigs)
    if researched and researched > now - timedelta(days=RECENT_DAYS) and not new_signal:
        return "skip", "R8_recent"
    # R9: big enough for the segment, or they asked for help (size is checked again in Step 11).
    # A business with no review data at all (no Places key, or no listing found) but its own website may be
    # researched with its size unknown: research reads its doctors and branches, and Step 11's fit gate drops
    # the small ones. It competes for the fit-only slots at the lowest size priority.
    if not has_stated_need:
        size = size_verdict(b, seg, world, now)
        unknown_with_site = size is None and b.get("review_count") is None and bool(b.get("web_domain"))
        if size is not True and not unknown_with_site:
            return "skip", "R9_size"
    # R10: some way to reach them
    if not (b.get("website") or world.phones.get(bid) or world.emails.get(bid)):
        extra = b.get("extra") or {}
        if sigs and extra.get("born_from") and not extra.get("places_lookup_at"):
            return "skip", "R10_waiting_lookup"  # the night's Places lookup may still find their listing
        return "reject", "no_contact_route"
    # R11: dormant businesses are not researched
    if b.get("status") == "dormant":
        return "skip", "R11_dormant"
    return "pass", None


# ---------------------------------------------------------------------------------------------------
# Priority (Step 8.7) and the queue (Step 8.8)
# ---------------------------------------------------------------------------------------------------


@dataclass
class Item:
    business_id: str
    segment_id: str
    priority: float
    fit_only: bool
    category: str | None  # the best signal's category
    observed_at: datetime | None
    review_count: int


def freshness(observed: datetime, expires: datetime, now: datetime) -> float:
    window = (expires - observed).total_seconds()
    ratio = (now - observed).total_seconds() / window if window > 0 else 1.0
    return 1.0 if ratio <= 0.3 else 0.7 if ratio <= 0.6 else 0.4 if ratio <= 1.0 else 0.0


def priority(b: dict[str, Any], signals: Sequence[dict[str, Any]], segment_weight: float, now: datetime) -> Item:
    reviews = int(b.get("review_count") or 0)
    branches = int(b.get("branches_count") or 1)
    size_bonus = min(20.0, 6 * math.log10(reviews + 1) + 4 * max(0, branches - 1))
    best: tuple[float, dict[str, Any]] | None = None
    for s in signals:
        value = float(s["points"]) * freshness(s["observed_at"], s["expires_at"], now)
        if best is None or value > best[0]:
            best = (value, s)
    if best is None or best[0] <= 0:
        return Item(b["id"], b["segment_id"], size_bonus + segment_weight, True, None, None, reviews)
    sig = best[1]
    strength = float(sig["points"]) / 10
    type_bonus = 15.0 if sig["category"] == "stated_need" else 8.0 if sig["category"] == "visible_pain" else 0.0
    value = 100 * strength * freshness(sig["observed_at"], sig["expires_at"], now) + type_bonus + size_bonus
    return Item(b["id"], b["segment_id"], value + segment_weight, False, sig["category"], sig["observed_at"], reviews)


def _order(items: list[Item]) -> list[Item]:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return sorted(items, key=lambda i: (-i.priority, -(i.observed_at or epoch).timestamp(), -i.review_count))


def segment_slots(slots: int, quotas: dict[str, int], with_work: set[str]) -> dict[str, int]:
    """Each segment's share of today's slots: its quota, scaled down when slots are short, and at least
    10% of the slots for every segment that has work (as far as its quota allows)."""
    active = {k: v for k, v in quotas.items() if v > 0 and k in with_work}
    total = sum(active.values())
    if not active or slots <= 0:
        return {}
    if total <= slots:
        return dict(active)
    floor_share = math.floor(slots * MIN_SEGMENT_SHARE)
    share = {k: max(min(floor_share, q), math.floor(slots * q / total)) for k, q in active.items()}
    while sum(share.values()) > slots:  # rounding up by the floor can overshoot: trim the biggest
        biggest = max(share, key=lambda k: share[k])
        share[biggest] -= 1
    return share


def build_queue(
    passed: list[Item],
    slots: int,
    quotas: dict[str, int],
    *,
    fit_only_allowed: bool = True,
    fit_only_share: float = FIT_ONLY_SHARE,
) -> list[Item]:
    """Today's queue: segment shares first, then any slots left by global priority (fit-only capped, and none at
    all once today's spend passes the fit-only threshold of the budget ladder, Step 19.6)."""
    if slots <= 0:
        return []
    fit_cap = math.floor(slots * min(max(fit_only_share, 0.0), 1.0)) if fit_only_allowed else 0
    by_seg: dict[str, list[Item]] = defaultdict(list)
    for item in _order(passed):
        by_seg[item.segment_id].append(item)
    shares = segment_slots(slots, quotas, set(by_seg))
    chosen: list[Item] = []
    taken: set[str] = set()
    fit_used = 0
    for seg_id, share in shares.items():
        n = 0
        for item in by_seg[seg_id]:
            if n >= share:
                break
            if item.fit_only and fit_used >= fit_cap:
                continue
            chosen.append(item)
            taken.add(item.business_id)
            fit_used += item.fit_only
            n += 1
    for item in _order([i for i in passed if i.business_id not in taken and quotas.get(i.segment_id, 0) > 0]):
        if len(chosen) >= slots:
            break
        if item.fit_only and fit_used >= fit_cap:
            continue
        chosen.append(item)
        fit_used += item.fit_only
    return _order(chosen)[:slots]


def today_slots(segment_ids: list[str], budget: Budget | None = None) -> tuple[int, dict[str, int], dict[str, Any]]:
    """(slots, per-segment quotas left, explanation) after today's earlier queueing and the money check."""
    budget = budget or Budget()
    today = health.ist_day_start()
    research_per_day = health.setting_int("research_per_day", 300)
    used = {
        r["segment_id"]: int(r["n"])
        for r in db.fetch_all(
            "select segment_id, count(*) as n from public.businesses where queued_at >= %s group by segment_id",
            [today],
        )
    }
    slots = max(0, research_per_day - sum(used.values()))
    try:
        est = float(db.get_setting("research.est_cost_inr", DEFAULT_COST_PER_ITEM_INR) or DEFAULT_COST_PER_ITEM_INR)
    except (TypeError, ValueError):
        est = DEFAULT_COST_PER_ITEM_INR
    remaining = max(0.0, budget.cap_inr - budget.committed_inr())  # spend today plus batch reservations
    money_slots = math.floor(remaining * MONEY_SHARE / est) if est > 0 else slots
    quotas = {k: max(0, v - used.get(k, 0)) for k, v in daily_quotas(segment_ids).items()}
    why = {"research_per_day": research_per_day, "queued_today": sum(used.values()), "money_slots": money_slots}
    return min(slots, money_slots), quotas, why


# ---------------------------------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------------------------------


def run(rc: RunContext) -> dict[str, Any]:
    """Apply the rules and queue today's businesses for research."""
    now = datetime.now(UTC)
    segments = active_segments(rc.opts.segments)
    excl = Exclusions.load()
    rows = db.fetch_all(CANDIDATES_SQL, {"segments": list(segments), "today": health.ist_day_start(now)})
    fact_keys = {r.key for s in segments.values() for r in s.size_rules.any_of if r.source == "fact"}
    world = load_world([r["id"] for r in rows], fact_keys)
    weights = db.get_setting("segment_weights", {}) or {}
    verdicts: Counter[str] = Counter()
    rejects: list[tuple[str, str]] = []
    suppressed: list[str] = []
    passed: list[Item] = []
    for b in rows:
        seg = segments.get(b["segment_id"])
        outcome, code = apply_rules(b, seg, excl, world, now)
        verdicts[code or "pass"] += 1
        if outcome == "pass":
            passed.append(priority(b, world.signals.get(b["id"], []), float(weights.get(b["segment_id"], 0)), now))
        elif outcome == "reject" and code:
            rejects.append((code, b["id"]))
        elif outcome == "suppress":
            suppressed.append(b["id"])
    budget = Budget(rc.run_id)
    slots, quotas, why = today_slots(list(segments), budget)
    fit_ok = budget.allow_phase("fit_only_research")
    share = db.get_setting("prefilter.fit_only_share", FIT_ONLY_SHARE)
    share = float(share) if isinstance(share, int | float) else FIT_ONLY_SHARE
    queue = build_queue(passed, slots, quotas, fit_only_allowed=fit_ok, fit_only_share=share)
    if rc.opts.limit:
        queue = queue[: rc.opts.limit]
    if not rc.opts.dry_run:
        with db.tx() as conn, conn.cursor() as cur:
            if rejects:
                cur.executemany(
                    "update public.businesses set status = 'rejected', reject_reason = %s where id = %s", rejects
                )
            if suppressed:
                cur.executemany(
                    "update public.businesses set status = 'suppressed', reject_reason = 'R5_suppressed' where id = %s",
                    [[b] for b in suppressed],
                )
            if queue:
                cur.executemany(
                    "update public.businesses set status = 'queued', queued_at = now(), queue_priority = %s, "
                    "reject_reason = null where id = %s",
                    [[round(i.priority, 2), i.business_id] for i in queue],
                )
    stats = {
        "candidates": len(rows),
        "passed": len(passed),
        "queued": len(queue),
        "slots": slots,
        **why,
        "by_segment": dict(Counter(i.segment_id for i in queue)),
        "by_signal_category": dict(Counter(i.category or "fit_only" for i in queue)),
        "fit_only_share": round(sum(i.fit_only for i in queue) / len(queue), 3) if queue else 0.0,
        "fit_only_allowed": fit_ok,
        "rules": dict(verdicts),
        "dry_run": rc.opts.dry_run,
    }
    rc.stats["prefilter"] = stats
    log.info("prefilter.done", queued=len(queue), passed=len(passed), candidates=len(rows))
    return stats
