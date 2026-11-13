"""Creating and updating leads from final grades (Step 11.11), shared by `score` and `judge`.

Rules:
- Only one open lead per business. The engine creates leads, and edits only leads still at stage `new`;
  every write is guarded with `stage = 'new'` so a founder's stage change in the same minute wins.
- Never touched by the engine: `notes`, `deal_value_inr`, the touch dates, and any stage beyond `new`
  (except the D-twice rule, which closes a `new` lead as `not_a_fit`).
- The database triggers log `lead_created`, `grade_change` and `stage_change` (A.13.5 rule 1); this module
  only opens the transaction with `db.tx("engine", ...)` so they are recorded as engine changes.
- Fit-only leads are at most 10% of a segment's new leads per day (rounded up, at least 1) (11.8.3).
- A phone proof older than 14 days is re-checked before a new lead is created (10.6.5).
"""

from __future__ import annotations

import asyncio
import importlib
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from psycopg import Connection

from .. import db
from ..logging import get_logger
from .evidence import Row
from .phones import phones_in_text, region_for

log = get_logger()
IST: Final = ZoneInfo("Asia/Kolkata")

COOL_DOWN: Final[dict[str, timedelta]] = {
    "not_now": timedelta(days=30),
    "lost": timedelta(days=90),
    "not_a_fit": timedelta(days=180),
}
CLIENT_STAGES: Final = frozenset({"won", "retainer"})  # a client is never pitched as a new lead
PHONE_PROOF_MAX_AGE: Final = timedelta(days=14)
_CLOSED_SQL: Final = "('won','retainer','lost','not_now','not_a_fit','wrong_contact')"
GENERATED_TEXT: Final = (
    "message",
    "message_alt",
    "followup_d3",
    "followup_d7",
    "email_subject",
    "email_body",
    "message_model",
    "message_check_score",
)

Fetcher = Callable[[str], str | None]  # url -> page HTML or text, None when it could not be fetched
Action = Literal["create", "update", "lower", "not_a_fit", "keep"]


@dataclass(frozen=True)
class Candidate:
    """A business with its final grade, as the lead rules need it."""

    business_id: str
    segment_id: str
    score_id: str
    grade: str
    total: float
    pitch_mode: str
    angle: str
    test_group: str
    reach_kind: str
    best_contact: Row | None
    region: str
    evidence_ids: frozenset[str] = frozenset()
    has_email: bool = False

    @property
    def channel(self) -> str:
        """whatsapp for a mobile; email when only a landline or an email; form for a contact form only."""
        if self.reach_kind in ("decision_maker_mobile", "business_mobile"):
            return "whatsapp"
        if self.reach_kind in ("email", "decision_maker_email") or (self.reach_kind == "landline" and self.has_email):
            return "email"
        if self.reach_kind == "form":
            return "form"
        return "whatsapp"


@dataclass
class LeadState:
    open_lead: Row | None = None
    last_closed: Row | None = None
    is_client: bool = False
    message_edited: bool = False
    cited_ids: frozenset[str] | None = None
    newest_contact_at: datetime | None = None


@dataclass
class LeadPlan:
    business_id: str
    action: Action
    candidate: Candidate
    lead_id: str | None = None
    clear_message: bool = False
    reason: str = ""


@dataclass
class Plans:
    items: list[LeadPlan] = field(default_factory=list)
    capped_ids: set[str] = field(default_factory=set)
    proof_refreshed: list[str] = field(default_factory=list)  # contact ids seen again on their page
    proof_gone: list[str] = field(default_factory=list)  # contact ids no longer on their page

    def capped(self, business_id: str) -> bool:
        return business_id in self.capped_ids


# =========================================================================
# Loading
# =========================================================================


def load_states(business_ids: Sequence[str], conn: Connection[Any] | None = None) -> dict[str, LeadState]:
    """Open lead, last closed lead, client status, founder edits and message basis for each business."""
    ids = list(dict.fromkeys(business_ids))
    states: dict[str, LeadState] = {i: LeadState() for i in ids}
    if not ids:
        return states
    for r in db.fetch_all(
        "select id, business_id, stage, grade, angle, pitch_mode, test_group, score_id, channel, message, "
        "regen_requested_at, created_at from public.leads "
        f"where business_id = any(%s::uuid[]) and stage not in {_CLOSED_SQL}",
        [ids],
        conn=conn,
    ):
        states[str(r["business_id"])].open_lead = {**r, "id": str(r["id"])}
    for r in db.fetch_all(
        "select distinct on (business_id) business_id, stage, last_activity_at from public.leads "
        f"where business_id = any(%s::uuid[]) and stage in {_CLOSED_SQL} "
        "order by business_id, last_activity_at desc",
        [ids],
        conn=conn,
    ):
        states[str(r["business_id"])].last_closed = r
    for r in db.fetch_all(
        "select distinct business_id from public.leads where business_id = any(%s::uuid[]) "
        "and stage in ('won', 'retainer')",
        [ids],
        conn=conn,
    ):
        states[str(r["business_id"])].is_client = True
    for r in db.fetch_all(
        "select business_id, max(greatest(created_at, coalesce(verified_at, created_at))) as at "
        "from public.contacts where business_id = any(%s::uuid[]) and verified and not do_not_contact "
        "and (phone_e164 is not null or email is not null) group by business_id",
        [ids],
        conn=conn,
    ):
        states[str(r["business_id"])].newest_contact_at = r["at"]
    open_ids = {s.open_lead["id"]: bid for bid, s in states.items() if s.open_lead}
    if open_ids:
        for lead_id, hist in message_history(list(open_ids), conn=conn).items():
            st = states[open_ids[lead_id]]
            st.message_edited = hist.edited
            st.cited_ids = hist.cited_ids
    return states


@dataclass(frozen=True)
class MessageHistory:
    """What the timeline says about a lead's message."""

    edited: bool = False  # a person edited it after the last regenerate request
    edited_at: datetime | None = None
    cited_ids: frozenset[str] | None = None  # ids the stored message cited (None: never stored by Step 12)
    stored_at: datetime | None = None


def message_history(lead_ids: Sequence[str], conn: Connection[Any] | None = None) -> dict[str, MessageHistory]:
    """Founder edits, regenerate requests and the engine's 'message_stored' records, per lead."""
    rows = db.fetch_all(
        """
        select lead_id, type, payload, at from public.activities
         where lead_id = any(%s::uuid[])
           and (type in ('message_edited', 'regen_request')
                or (type = 'edit' and (payload ? 'message' or payload ->> 'field' in ('message', 'message_alt')))
                or (type = 'ai_output' and payload ->> 'kind' = 'message_stored'))
         order by at
        """,
        [list(lead_ids)],
        conn=conn,
    )
    out: dict[str, MessageHistory] = {str(i): MessageHistory() for i in lead_ids}
    for r in rows:
        lid, h = str(r["lead_id"]), out[str(r["lead_id"])]
        if r["type"] in ("message_edited", "edit"):
            out[lid] = MessageHistory(True, r["at"], h.cited_ids, h.stored_at)
        elif r["type"] == "regen_request":
            out[lid] = MessageHistory(False, h.edited_at, h.cited_ids, h.stored_at)  # a rewrite was asked for
        else:
            cited = frozenset(str(i) for i in (r["payload"] or {}).get("cited_ids") or [])
            out[lid] = MessageHistory(False, h.edited_at, cited, r["at"])
    return out


def created_today(
    segment_ids: Iterable[str], now: datetime, conn: Connection[Any] | None = None
) -> dict[str, Counter[str]]:
    """New leads per segment and pitch mode since 00:00 IST today (the fit-only cap counts these)."""
    start = datetime.combine(now.astimezone(IST).date(), time(0, 0), tzinfo=IST)
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for r in db.fetch_all(
        "select segment_id, pitch_mode, count(*) as n from public.leads "
        "where created_at >= %s and segment_id = any(%s) group by 1, 2",
        [start, list(segment_ids)],
        conn=conn,
    ):
        out[r["segment_id"]][r["pitch_mode"]] += int(r["n"])
    return out


# =========================================================================
# Deciding
# =========================================================================


def in_cool_down(state: LeadState, now: datetime) -> str | None:
    """Why a business with no open lead must not get a new one yet, or None."""
    if state.is_client:
        return "client"
    closed = state.last_closed
    if closed is None:
        return None
    stage, since = str(closed["stage"]), closed.get("last_activity_at")
    if stage == "wrong_contact":
        fresh = state.newest_contact_at is not None and since is not None and state.newest_contact_at > since
        return None if fresh else "wrong_contact_until_new_contact"
    wait = COOL_DOWN.get(stage)
    if wait is not None and since is not None and now - since < wait:
        return f"cool_down_{stage}"
    return None


def decide(c: Candidate, state: LeadState, now: datetime) -> LeadPlan:
    """The 11.11 table for one business."""
    lead = state.open_lead
    if lead is not None:
        if lead["stage"] != "new":
            return LeadPlan(c.business_id, "keep", c, lead["id"], reason="stage_beyond_new")
        if c.grade in ("A", "B"):
            changed_basis = state.cited_ids is not None and not state.cited_ids <= c.evidence_ids
            clear = (
                not state.message_edited
                and bool(lead.get("message"))
                and ((lead.get("angle") or "") != c.angle or changed_basis)
            )
            return LeadPlan(c.business_id, "update", c, lead["id"], clear_message=clear)
        if c.grade == "D" and lead.get("grade") == "D":
            return LeadPlan(c.business_id, "not_a_fit", c, lead["id"], reason="d_twice")
        return LeadPlan(c.business_id, "lower", c, lead["id"])
    if c.grade not in ("A", "B"):
        return LeadPlan(c.business_id, "keep", c, reason="grade")
    why = in_cool_down(state, now)
    if why:
        return LeadPlan(c.business_id, "keep", c, reason=why)
    return LeadPlan(c.business_id, "create", c)


def fit_only_allowed(pct: float, other_new: int, fit_only_today: int, min_per_day: int = 1) -> int:
    """How many more fit-only leads may be created today: `pct`% of the day's other new leads, rounded up, and
    never fewer than `min_per_day` (scoring.yaml fit_only_min_per_day)."""
    return max(0, max(min_per_day, math.ceil(pct / 100 * other_new)) - fit_only_today)


def plan_all(
    candidates: Sequence[Candidate],
    states: Mapping[str, LeadState],
    fit_only_pct: Mapping[str, float],
    now: datetime,
    *,
    fetch: Fetcher | None = None,
    stats: Counter[str] | None = None,
    today: Mapping[str, Counter[str]] | None = None,
    fit_only_min: Mapping[str, int] | None = None,
) -> Plans:
    """Decide every lead action, then apply the fit-only cap and the phone freshness rule to creations."""
    stats = stats if stats is not None else Counter()
    plans = Plans()
    decided = [decide(c, states.get(c.business_id, LeadState()), now) for c in candidates]
    today = today if today is not None else created_today({c.segment_id for c in candidates}, now)
    by_segment: dict[str, list[LeadPlan]] = defaultdict(list)
    for p in decided:
        if p.action == "create":
            by_segment[p.candidate.segment_id].append(p)
    for seg_id, creates in by_segment.items():
        others = [p for p in creates if p.candidate.pitch_mode != "fit_only"]
        fit_only = sorted(
            (p for p in creates if p.candidate.pitch_mode == "fit_only"), key=lambda p: -p.candidate.total
        )
        counts = today.get(seg_id, Counter())
        other_today = sum(n for mode, n in counts.items() if mode != "fit_only")
        allowed = fit_only_allowed(
            fit_only_pct.get(seg_id, 10.0),
            other_today + len(others),
            counts["fit_only"],
            (fit_only_min or {}).get(seg_id, 1),
        )
        for p in fit_only[allowed:]:
            p.action, p.reason = "keep", "fit_only_cap"
            plans.capped_ids.add(p.business_id)
            stats["leads.fit_only_capped"] += 1
    proofs = ProofChecker(fetch)
    for p in decided:
        if p.action == "create":
            verdict = proofs.check(p.candidate, now)
            if verdict == "refreshed" and p.candidate.best_contact:
                plans.proof_refreshed.append(str(p.candidate.best_contact["id"]))
            elif verdict in ("gone", "stale"):
                if verdict == "gone" and p.candidate.best_contact:
                    plans.proof_gone.append(str(p.candidate.best_contact["id"]))
                p.action, p.reason = "keep", f"phone_proof_{verdict}"
                plans.capped_ids.add(p.business_id)  # stays researched, tried again tomorrow
        stats[f"leads.{p.action}"] += 1
        if p.reason and p.action == "keep":
            stats[f"leads.keep.{p.reason}"] += 1
        if p.clear_message:
            stats["leads.message_cleared"] += 1
    plans.items = decided
    return plans


# =========================================================================
# 10.6.5 Phone freshness
# =========================================================================


class ProofChecker:
    """Re-checks a website phone whose proof page is older than 14 days, once per run and URL."""

    def __init__(self, fetch: Fetcher | None) -> None:
        self.fetch = fetch
        self._resolved = fetch is not None
        self._cache: dict[str, str | None] = {}

    def _fetcher(self) -> Fetcher | None:
        if not self._resolved:
            self.fetch, self._resolved = default_fetcher(), True
        return self.fetch

    def check(self, c: Candidate, now: datetime) -> str:
        """ok, refreshed, gone or stale (could not re-check)."""
        contact = c.best_contact
        if contact is None or not contact.get("phone_e164") or contact.get("source") != "website":
            return "ok"
        seen = contact.get("verified_at")
        if seen is not None and now - seen <= PHONE_PROOF_MAX_AGE:
            return "ok"
        url = contact.get("source_url")
        fetch = self._fetcher()
        if not url or fetch is None:
            return "stale"
        if url not in self._cache:
            try:
                self._cache[url] = fetch(url)
            except Exception as exc:  # a page that fails today is tried again tomorrow
                log.warning("leads.proof_fetch_failed", error=type(exc).__name__)
                self._cache[url] = None
        text = self._cache[url]
        if text is None:
            return "stale"
        region = region_for(c.region)
        found = any(h.e164 == contact["phone_e164"] for h in phones_in_text(text, region))
        return "refreshed" if found else "gone"


def default_fetcher() -> Fetcher | None:
    """The Step 5 polite client (`nument_engine.http.PoliteClient`), or None while it is not available."""
    try:
        http = importlib.import_module("nument_engine.http")
    except ImportError:
        return None
    client_cls = vars(http).get("PoliteClient")
    if client_cls is None:
        return None

    def fetch(url: str) -> str | None:
        async def go() -> str | None:
            client = client_cls("verify", 1.0)
            try:
                res = await client.get(url)
            finally:
                closer = getattr(client, "aclose", None) or getattr(getattr(client, "client", None), "aclose", None)
                if closer is not None:
                    await closer()
            return str(res.text) if getattr(res, "state", "") == "ok" else None

        return asyncio.run(go())

    return fetch


# =========================================================================
# Writing
# =========================================================================


def apply(conn: Connection[Any], plans: Plans | Sequence[LeadPlan], now: datetime) -> None:
    """Write lead plans in the caller's transaction. Stage guards make concurrent founder edits win."""
    items = plans.items if isinstance(plans, Plans) else list(plans)
    cur = conn.cursor()
    creates = [p for p in items if p.action == "create"]
    if creates:
        cur.executemany(
            "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode, test_group, angle, "
            "channel, stage) values (%(b)s, %(seg)s, %(score)s, %(grade)s, %(mode)s, %(tg)s, %(angle)s, %(ch)s, 'new') "
            f"on conflict (business_id) where stage not in {_CLOSED_SQL} do nothing",
            [
                {
                    "b": p.business_id,
                    "seg": p.candidate.segment_id,
                    "score": p.candidate.score_id,
                    "grade": p.candidate.grade,
                    "mode": p.candidate.pitch_mode,
                    "tg": p.candidate.test_group,
                    "angle": p.candidate.angle,
                    "ch": p.candidate.channel,
                }
                for p in creates
            ],
        )
    clear_sql = ", ".join(f"{col} = case when %(clear)s then null else {col} end" for col in GENERATED_TEXT)
    updates = [p for p in items if p.action == "update"]
    if updates:
        cur.executemany(
            "update public.leads set grade = %(grade)s, score_id = %(score)s, pitch_mode = %(mode)s, "
            f"test_group = %(tg)s, angle = %(angle)s, channel = %(ch)s, {clear_sql} "
            "where id = %(id)s and stage = 'new'",
            [
                {
                    "id": p.lead_id,
                    "grade": p.candidate.grade,
                    "score": p.candidate.score_id,
                    "mode": p.candidate.pitch_mode,
                    "tg": p.candidate.test_group,
                    "angle": p.candidate.angle,
                    "ch": p.candidate.channel,
                    "clear": p.clear_message,
                }
                for p in updates
            ],
        )
    lowers = [p for p in items if p.action == "lower"]
    if lowers:
        cur.executemany(
            "update public.leads set grade = %(grade)s, score_id = %(score)s where id = %(id)s and stage = 'new'",
            [{"id": p.lead_id, "grade": p.candidate.grade, "score": p.candidate.score_id} for p in lowers],
        )
    closes = [p for p in items if p.action == "not_a_fit"]
    if closes:
        cur.executemany(
            "update public.leads set stage = 'not_a_fit', grade = 'D', score_id = %(score)s "
            "where id = %(id)s and stage = 'new'",
            [{"id": p.lead_id, "score": p.candidate.score_id} for p in closes],
        )
    if isinstance(plans, Plans):
        if plans.proof_refreshed:
            cur.executemany(
                "update public.contacts set verified_at = %(now)s where id = %(id)s",
                [{"id": i, "now": now} for i in plans.proof_refreshed],
            )
        if plans.proof_gone:
            cur.executemany(
                "update public.contacts set verified = false where id = %(id)s",
                [{"id": i} for i in plans.proof_gone],
            )
