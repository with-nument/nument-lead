"""Funnel metrics per cut (Steps 16.1 and 16.2).

Every stage has a rank. A lead's highest rank ever reached decides which funnel events it counts for, even
if it later closed: Contacted, then Talking, then Lost still counts as contacted and replied (16.1.1).

- `wrong_contact` never counts as contacted (we never reached the business); it is counted on its own.
- A lead with `wa_at` set but still at `new` counts as contacted (the view handles it).
- Events count only inside their window after first contact (21, 45, 60 and 120 days, 16.1.3).
- Rates use mature leads only: a lead counts towards a rate once that event's window has closed. Leads
  still inside the meeting window are reported separately as "still open".

`load_funnel()` reads one row per contacted lead; `rates_by_cut()` groups them; `decision_label()` turns a
row into scale, keep, cut, watch or early_signal (16.2.4). The engine only recommends: it never turns a
segment or test group off by itself.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

from psycopg import Connection
from scipy.stats import beta

from .. import db
from ..models import SIGNAL_TYPES
from ..pipeline.runs import RunContext
from .weights import proxies_for_counts, proxy_tiers

STAGE_RANK: Final[dict[str, int | None]] = {
    "new": 0,
    "contacted": 1,
    "talking": 2,
    "discovery_booked": 3,
    "discovery_done": 3,
    "proposal_sent": 4,
    "won": 5,
    "retainer": 5,
    "lost": None,
    "not_now": None,
    "not_a_fit": None,
    "wrong_contact": None,
}
EVENT_RANK: Final[dict[str, int]] = {"contacted": 1, "replied": 2, "meeting": 3, "proposal": 4, "won": 5}
WINDOWS_DAYS: Final[dict[str, int]] = {"replied": 21, "meeting": 45, "proposal": 60, "won": 120}
EVENTS: Final[tuple[str, ...]] = ("replied", "meeting", "proposal", "won")
CUTS: Final[tuple[str, ...]] = (
    "segment_id",
    "country",
    "signal_type",
    "pitch_mode",
    "angle",
    "test_group",
    "grade",
    "reach_type",
    "writer",  # leads.message_model, so writers can be compared (Step 12.4)
)
NONE_KEY: Final[str] = "none"
CI_MASS: Final[float] = 0.90
# Decision label thresholds (16.2.4)
SCALE_MEETING_RATE, KEEP_MEETING_RATE = 0.08, 0.03
MIN_JUDGED, MIN_CUT = 50, 100
EARLY_MIN, EARLY_GREEN, EARLY_RED = 30, 0.10, 0.03
LOOKBACK_DAYS: Final[int] = 180  # long enough for the 120-day won window to mature

_COUNT_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "branches": re.compile(r"branch(?:es)?(?:_count)?\s*[=:]\s*(\d+)", re.I),
    "staff": re.compile(r"(?:staff|doctors?)(?:_count)?\s*[=:]\s*(\d+)", re.I),
    "reviews": re.compile(r"reviews?(?:_count)?\s*[=:]\s*(\d+)", re.I),
}
_FLAG_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "premium_price": re.compile(r"premium|price_point", re.I),
    "pays_for_software": re.compile(r"software|crm|booking system|live chat|practo", re.I),
    "custom_website": re.compile(r"custom.?(?:web)?site|own domain", re.I),
    "funding": re.compile(r"funding", re.I),
}


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunnelRow:
    """One lead that was contacted (or turned out to be a wrong contact), with what it reached and when."""

    lead_id: str
    segment_id: str
    country: str
    pitch_mode: str
    angle: str | None
    test_group: str | None
    grade: str
    stage: str
    max_rank: int
    is_wrong_contact: bool
    contacted_at: datetime | None  # first contact; None for a wrong contact that never got through
    attempted_at: datetime  # first contact, or when it was marked a wrong contact
    reached_at: Mapping[int, datetime] = field(default_factory=dict)  # first time rank 2..5 was reached
    created_at: datetime | None = None
    writer: str | None = None
    reach_type: str = "none"
    phone_source: str | None = None
    signal_types: tuple[str, ...] = ()
    can_pay_proxies: tuple[str, ...] = ()
    signal_age_days: float | None = None
    score_total: float | None = None
    deal_value_inr: float | None = None

    @property
    def contacted(self) -> bool:
        return self.contacted_at is not None and not self.is_wrong_contact

    def had(self, event: str) -> bool:
        """The event happened inside its window after first contact."""
        if not self.contacted or self.max_rank < EVENT_RANK[event]:
            return False
        if event == "contacted":
            return True
        assert self.contacted_at is not None
        at = self.reached_at.get(EVENT_RANK[event], self.contacted_at)
        return (max(at, self.contacted_at) - self.contacted_at) <= timedelta(days=WINDOWS_DAYS[event])

    def mature(self, event: str, as_of: datetime) -> bool:
        """The event's window has closed, so the lead can count towards that rate."""
        return self.contacted_at is not None and self.contacted_at + timedelta(days=WINDOWS_DAYS[event]) <= as_of

    def key(self, cut: str) -> list[str]:
        """The group keys this lead belongs to for a cut (a lead with two signal types is in both rows)."""
        if cut == "signal_type":
            return list(self.signal_types) or [NONE_KEY]
        value = getattr(self, cut)
        return [str(value) if value not in (None, "") else NONE_KEY]


@dataclass(frozen=True)
class Rate:
    """successes / trials over mature leads, with a Beta(1 + s, 1 + f) credible interval."""

    successes: int
    trials: int

    @property
    def value(self) -> float | None:
        return self.successes / self.trials if self.trials else None

    @property
    def ci90(self) -> tuple[float, float] | None:
        return credible_interval(self.successes, self.trials) if self.trials else None

    def as_dict(self) -> dict[str, Any]:
        return {"successes": self.successes, "trials": self.trials, "value": self.value, "ci90": self.ci90}


@dataclass(frozen=True)
class CutRow:
    """Counts and rates for one group of one cut."""

    cut: str
    key: str
    contacted: int
    replied: int
    meetings: int
    proposals: int
    won: int
    wrong_contact: int
    open_leads: int  # contacted, still inside the meeting window ("still open")
    reply: Rate
    meeting: Rate
    proposal: Rate
    win: Rate
    label: str = "watch"
    tone: str | None = None

    @property
    def mature(self) -> bool:
        """Every contacted lead in the row is past the meeting window (45 days)."""
        return self.contacted > 0 and self.open_leads == 0

    @property
    def reply_rate(self) -> float | None:
        return self.reply.value

    @property
    def meeting_rate(self) -> float | None:
        return self.meeting.value

    @property
    def win_rate(self) -> float | None:
        return self.win.value

    @property
    def proposal_per_20(self) -> float | None:
        return None if self.proposal.value is None else self.proposal.value * 20

    @property
    def meeting_ci90(self) -> tuple[float, float] | None:
        return self.meeting.ci90

    def as_dict(self) -> dict[str, Any]:
        return {
            "cut": self.cut,
            "key": self.key,
            "contacted": self.contacted,
            "replied": self.replied,
            "meetings": self.meetings,
            "proposals": self.proposals,
            "won": self.won,
            "wrong_contact": self.wrong_contact,
            "open_leads": self.open_leads,
            "mature": self.mature,
            "reply": self.reply.as_dict(),
            "meeting": self.meeting.as_dict(),
            "proposal": self.proposal.as_dict(),
            "win": self.win.as_dict(),
            "reply_rate": self.reply_rate,
            "meeting_rate": self.meeting_rate,
            "proposal_per_20": self.proposal_per_20,
            "win_rate": self.win_rate,
            "label": self.label,
            "tone": self.tone,
        }


# ---------------------------------------------------------------------------
# Maths
# ---------------------------------------------------------------------------


def credible_interval(successes: int, trials: int, mass: float = CI_MASS) -> tuple[float, float]:
    """Equal-tailed interval of Beta(1 + successes, 1 + failures): small samples are not over-read."""
    a, b = 1 + successes, 1 + max(trials - successes, 0)
    tail = (1 - mass) / 2
    return float(beta.ppf(tail, a, b)), float(beta.ppf(1 - tail, a, b))


def decision_label(row: CutRow) -> tuple[str, str | None]:
    """scale, keep, cut or watch once meetings are judged on 50+ mature leads; early_signal before (16.2.4)."""
    judged, m = row.meeting.trials, row.meeting.value
    if judged >= MIN_JUDGED and m is not None:
        p20 = row.proposal_per_20
        if m >= SCALE_MEETING_RATE and p20 is not None and p20 >= 1:
            return "scale", None
        if m >= KEEP_MEETING_RATE:
            return "keep", None
        return ("cut", None) if judged >= MIN_CUT else ("watch", None)
    r = row.reply.value
    if row.reply.trials >= EARLY_MIN and r is not None:
        if r >= EARLY_GREEN:
            return "early_signal", "green"
        if r < EARLY_RED:
            return "early_signal", "red"
    return "watch", None


def summarise(rows: Iterable[FunnelRow], cut: str, key: str, as_of: datetime) -> CutRow:
    """One CutRow from the rows of one group."""
    rows = list(rows)
    contacted = [r for r in rows if r.contacted]

    def rate(event: str) -> Rate:
        mature = [r for r in contacted if r.mature(event, as_of)]
        return Rate(sum(r.had(event) for r in mature), len(mature))

    row = CutRow(
        cut=cut,
        key=key,
        contacted=len(contacted),
        replied=sum(r.had("replied") for r in contacted),
        meetings=sum(r.had("meeting") for r in contacted),
        proposals=sum(r.had("proposal") for r in contacted),
        won=sum(r.had("won") for r in contacted),
        wrong_contact=sum(r.is_wrong_contact for r in rows),
        open_leads=sum(not r.mature("meeting", as_of) for r in contacted),
        reply=rate("replied"),
        meeting=rate("meeting"),
        proposal=rate("proposal"),
        win=rate("won"),
    )
    label, tone = decision_label(row)
    return replace(row, label=label, tone=tone)


def rates_by_cut(rows: Sequence[FunnelRow], cut: str, as_of: datetime) -> list[CutRow]:
    """Group rows by a cut; most contacted first."""
    if cut not in CUTS:
        raise ValueError(f"unknown cut {cut!r}; expected one of {', '.join(CUTS)}")
    groups: dict[str, list[FunnelRow]] = defaultdict(list)
    for r in rows:
        for k in r.key(cut):
            groups[k].append(r)
    out = [summarise(members, cut, k, as_of) for k, members in groups.items()]
    return sorted(out, key=lambda c: (-c.contacted, -c.wrong_contact, c.key))


def total_row(rows: Sequence[FunnelRow], as_of: datetime) -> CutRow:
    """All rows together (the "all segments" line)."""
    return summarise(rows, "all", "all", as_of)


def median(values: Iterable[float | None]) -> float | None:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return statistics.median(clean) if clean else None


# ---------------------------------------------------------------------------
# Attribution helpers
# ---------------------------------------------------------------------------


def reach_type_of(phone_type: str | None, has_phone: bool, has_email: bool, has_form: bool) -> str:
    """mobile, landline (also toll free or unknown phone type), email, form or none (16.2.1)."""
    if has_phone:
        return "mobile" if phone_type == "mobile" else "landline"
    if has_email:
        return "email"
    return "form" if has_form else "none"


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def signal_types_from(reasons: Any, fallback: Sequence[str] | None) -> tuple[str, ...]:
    """Signal types the score used: scores.reasons 'signals' (16.2.2) or 'intent' (Step 11.6), else fallback."""
    found: set[str] = set()
    if isinstance(reasons, Mapping):
        for key in ("signals", "intent"):
            for item in _as_list(reasons.get(key)):
                t = item.get("type") if isinstance(item, Mapping) else None
                if t in SIGNAL_TYPES:
                    found.add(t)
    if not found and fallback:
        found = {t for t in fallback if t in SIGNAL_TYPES}
    return tuple(sorted(found))


def can_pay_proxies_from(
    reasons: Any,
    tiers: Mapping[str, list[tuple[float, str]]],
    *,
    branches: float | None,
    staff: float | None,
    reviews: float | None,
) -> tuple[str, ...]:
    """Can-pay proxies the lead earned when it was scored.

    Preferred: `scores.reasons.can_pay_proxies` (a list of proxy keys). Otherwise the numbers and flags in
    the `can_pay` reason strings (for example "branches_count=3 (fact 8f2c)"), then the business columns.
    """
    if isinstance(reasons, Mapping):
        listed = [str(p) for p in _as_list(reasons.get("can_pay_proxies"))]
        if listed:
            return tuple(sorted(set(listed)))
    counts: dict[str, float | None] = {"branches": branches, "staff": staff, "reviews": reviews}
    flags: set[str] = set()
    texts = [str(t) for t in _as_list(reasons.get("can_pay"))] if isinstance(reasons, Mapping) else []
    for text in texts:
        for group, pattern in _COUNT_PATTERNS.items():
            if match := pattern.search(text):
                counts[group] = float(match.group(1))
        flags |= {key for key, pattern in _FLAG_PATTERNS.items() if pattern.search(text)}
    found = set(proxies_for_counts(tiers, **counts)) | flags
    return tuple(sorted(found))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

FUNNEL_SQL = """
with ranks(stage, rnk) as (
  values ('contacted',1),('talking',2),('discovery_booked',3),('discovery_done',3),
         ('proposal_sent',4),('won',5),('retainer',5)
),
hist as (
  select a.lead_id,
         min(a.at) filter (where r.rnk >= 1) as at1,
         min(a.at) filter (where r.rnk >= 2) as at2,
         min(a.at) filter (where r.rnk >= 3) as at3,
         min(a.at) filter (where r.rnk >= 4) as at4,
         min(a.at) filter (where r.rnk >= 5) as at5
  from public.activities a
  join ranks r on r.stage = a.payload ->> 'to'
  where a.type = 'stage_change'
  group by a.lead_id
),
wrong as (
  select a.lead_id, min(a.at) as wrong_at
  from public.activities a
  where a.type = 'stage_change' and a.payload ->> 'to' = 'wrong_contact'
  group by a.lead_id
),
base as (
  select f.*, l.business_id, l.created_at, l.last_activity_at, l.message_model, l.deal_value_inr,
         l.score_id, h.at2, h.at3, h.at4, h.at5, w.wrong_at,
         coalesce(f.contacted_at, h.at1) as first_contact_at
  from public.v_lead_funnel f
  join public.leads l on l.id = f.lead_id
  left join hist h on h.lead_id = f.lead_id
  left join wrong w on w.lead_id = f.lead_id
  where f.max_rank >= 1 or f.is_wrong_contact
)
select b.lead_id::text as lead_id, b.segment_id, b.country, b.pitch_mode, b.angle, b.test_group, b.grade,
       b.stage, b.max_rank, b.is_wrong_contact, b.first_contact_at, b.at2, b.at3, b.at4, b.at5, b.wrong_at,
       b.created_at, b.last_activity_at, b.message_model, b.deal_value_inr,
       sc.total as score_total, sc.reasons,
       bz.branches_count, bz.staff_count, bz.review_count,
       pc.phone_type, coalesce(pc.has_phone, false) as has_phone, coalesce(pc.has_email, false) as has_email,
       pc.phone_source,
       exists (select 1 from public.facts fa
               where fa.business_id = b.business_id and fa.field = 'contact_form_url' and fa.verified) as has_form,
       sig.types as active_signal_types,
       top.observed_at as top_signal_observed_at
from base b
join public.businesses bz on bz.id = b.business_id
left join public.scores sc on sc.id = b.score_id
left join lateral (
  select c.phone_type, (c.phone_e164 is not null) as has_phone, (c.email is not null) as has_email,
         case when c.phone_e164 is not null then c.source end as phone_source
  from public.contacts c
  where c.business_id = b.business_id
  order by (c.phone_e164 is not null) desc, c.is_decision_maker desc, (c.phone_type = 'mobile') desc,
           c.verified desc, (c.source = 'website') desc, c.created_at
  limit 1
) pc on true
left join lateral (
  select array_agg(distinct s.type order by s.type) as types
  from public.signals s
  where s.business_id = b.business_id and s.observed_at <= b.created_at and s.expires_at > b.created_at
) sig on true
left join lateral (
  select s.observed_at
  from public.signals s
  where s.business_id = b.business_id and s.category <> 'money'
    and s.observed_at <= b.created_at and s.expires_at > b.created_at
  order by s.points desc, s.observed_at desc
  limit 1
) top on true
where coalesce(b.first_contact_at, b.wrong_at, b.last_activity_at) >= %(since)s
  and coalesce(b.first_contact_at, b.wrong_at, b.last_activity_at) < %(until)s
order by b.first_contact_at nulls last, b.lead_id
"""


def ist_day_start(day: date) -> datetime:
    """Midnight IST of a date, as an aware UTC datetime."""
    return datetime.combine(day, time(0), tzinfo=UTC) - timedelta(hours=5, minutes=30)


def _row_from_db(rec: Mapping[str, Any], tiers_by_segment: Mapping[str, Any]) -> FunnelRow:
    max_rank = int(rec["max_rank"] or 0)
    wrong = bool(rec["is_wrong_contact"])
    fallback: datetime = rec["last_activity_at"] or rec["created_at"]
    contacted_at: datetime | None = None
    if max_rank >= 1 and not wrong:
        contacted_at = rec["first_contact_at"] or fallback
    reached: dict[int, datetime] = {}
    for rank in (2, 3, 4, 5):
        at = rec[f"at{rank}"]
        if at is None and max_rank >= rank:
            at = fallback
        if at is not None:
            reached[rank] = at
    signal_at = rec["top_signal_observed_at"]
    age = (contacted_at - signal_at).total_seconds() / 86400 if contacted_at and signal_at else None
    reasons = rec["reasons"]
    return FunnelRow(
        lead_id=rec["lead_id"],
        segment_id=rec["segment_id"],
        country=rec["country"],
        pitch_mode=rec["pitch_mode"],
        angle=rec["angle"],
        test_group=rec["test_group"],
        grade=rec["grade"],
        stage=rec["stage"],
        max_rank=max_rank,
        is_wrong_contact=wrong,
        contacted_at=contacted_at,
        attempted_at=contacted_at or rec["wrong_at"] or fallback,
        reached_at=reached,
        created_at=rec["created_at"],
        writer=rec["message_model"],
        reach_type=reach_type_of(rec["phone_type"], rec["has_phone"], rec["has_email"], rec["has_form"]),
        phone_source=rec["phone_source"],
        signal_types=signal_types_from(reasons, rec["active_signal_types"]),
        can_pay_proxies=can_pay_proxies_from(
            reasons,
            tiers_by_segment.get(rec["segment_id"], {}),
            branches=rec["branches_count"],
            staff=rec["staff_count"],
            reviews=rec["review_count"],
        ),
        signal_age_days=None if age is None else max(age, 0.0),
        score_total=None if rec["score_total"] is None else float(rec["score_total"]),
        deal_value_inr=None if rec["deal_value_inr"] is None else float(rec["deal_value_inr"]),
    )


def tiers_by_segment() -> dict[str, dict[str, list[tuple[float, str]]]]:
    """Can-pay tiers of every segment file (with its overrides), for proxy attribution."""
    from ..segments import load_segments, scoring_config

    return {sid: proxy_tiers(scoring_config(seg)) for sid, seg in load_segments().items()}


def load_funnel(
    conn: Connection[Any] | None = None,
    *,
    as_of: datetime | None = None,
    since_days: int = LOOKBACK_DAYS,
    tiers: Mapping[str, Any] | None = None,
) -> list[FunnelRow]:
    """Contacted leads (and wrong contacts) whose first attempt falls in the `since_days` before `as_of`."""
    until = as_of or datetime.now(UTC)
    since = until - timedelta(days=since_days)
    records = db.fetch_all(FUNNEL_SQL, {"since": since, "until": until}, conn=conn)
    tier_map = tiers if tiers is not None else tiers_by_segment()
    return [_row_from_db(rec, tier_map) for rec in records]


def all_cuts(rows: Sequence[FunnelRow], as_of: datetime) -> dict[str, list[CutRow]]:
    """rates_by_cut for every cut."""
    return {cut: rates_by_cut(rows, cut, as_of) for cut in CUTS}


def audit(rc: RunContext) -> dict[str, Any]:
    """The weekly audit lives in ops.audit (Step 17.6); kept here for callers of the Step 1 stub."""
    from ..ops.audit import weekly

    return weekly(rc)
