"""Startup qualification (15 Nov 2026): is this a real startup of 2 to 10 people, idea to small seed, without a
tech team, that can pay? Every answer rests on verified facts (extract_facts v2 and the probe facts of contract
4.2) and signals, or stays unknown.

`assess()` is a pure function of one business's verified facts and its signals. `run()` stores its answers in
`startup_profiles` (contract 4.3: this module is the only writer), and score s3.0 (`score_startup.py`) calls the
same function, so a score never depends on whether this phase ran first.

- is_startup: a startup sign (early funding, a launch, an accelerator batch, a young company with founders and a
  product) makes it true; a services agency, or a company older than `max_age_years` with no startup sign, false.
- team_size: the best stated count (their own page, a filing, an accelerator list, a job post, the news), raised
  to the number of people the team page names when that is more. Investors and advisors are not the team.
- tech_team: `has_engineers` with two technical people, or one sign of an engineering team (their own words, an
  in-house tech fact, a careers board with many engineering roles, an active GitHub org with members);
  `lone_cto` with exactly one technical person; `none` only with two independent signs that nobody technical is
  there (a team page without a technical person, their own words, a job post for their first engineer or CTO, a
  public ask for a builder, a product on a no-code app builder, a build outsourced to others); else unknown.
- can_pay: points for money raised or earned, a builder job post, paid tools and their own domain; `no` for an
  equity-only or unpaid offer when no money was seen.
- product_status, no_code_platform, uses_ai, funding_*, domain_created_at: what the evidence says.

`evidence` (migration 0028) keeps, for every answer, the fact and signal ids it rests on and one plain line why.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from psycopg import Connection

from .. import db
from ..logging import get_logger
from ..segments import Segment, load_yaml_config, scoring_config
from ..sources.startup import DEFAULT_MAX_RAISE_USD, DEFAULT_MAX_TEAM, LATE_ROUNDS, limits, normalize_round
from . import evidence
from .evidence import Row, fact_count, fact_flag, vget
from .runs import RunContext
from .score import FREE_BUILDER_DOMAINS, enabled_segments

log = get_logger()

CHUNK: Final = 200
RECHECK_AFTER: Final = timedelta(days=30)  # a profile is worked out again at least this often
EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

FOUNDER_ROLE: Final = re.compile(r"\b(?:co-?\s?founder|founder|founding (?:ceo|team|partner))\b", re.I)
TECH_ROLE: Final = re.compile(
    r"\b(?:cto|chief (?:technology|technical) officer|technical co-?\s?founder|tech(?:nical)? lead|"
    r"head of (?:engineering|technology|tech)|vp,? (?:of )?engineering|engineer(?:ing)?|developer|programmer|"
    r"software|full[\s-]?stack|back[\s-]?end|front[\s-]?end|devops|machine learning|data scientist|"
    r"(?:software|solutions|cloud) architect|coder)\b",
    re.I,
)
NOT_TEAM_ROLE: Final = re.compile(
    r"\b(?:advis[eo]r\w*|investor|mentor|board|angel|backer|ambassador|venture partner)\b", re.I
)
FIRST_BUILDER: Final = re.compile(
    r"\b(?:founding (?:engineer|developer|cto|full[\s-]?stack\w*|software engineer)|"
    r"first (?:engineer|developer|technical hire|tech hire|engineering hire)|cto|chief technology officer|"
    r"tech(?:nical)? co-?\s?founder)\b",
    re.I,
)
APP_BUILDERS: Final = frozenset(
    {"bubble", "softr", "glide", "adalo", "flutterflow", "thunkable", "lovable", "bolt", "replit", "appsheet",
     "draftbit", "noloco", "retool"}
)  # fmt: skip
PAID_TOOLS: Final = frozenset(
    {"stripe", "hubspot", "salesforce", "intercom", "zendesk", "atlassian", "segment", "docusign", "klaviyo",
     "pipedrive", "freshdesk", "paddle", "chargebee"}
)  # fmt: skip
PAID_MAIL: Final = frozenset({"google", "microsoft", "zoho"})
# Approximate dollars per unit (Nov 2026). Amounts are only weighed against the ~$2M line and the can-pay tiers.
USD_PER: Final[dict[str, float]] = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "INR": 0.012, "AED": 0.27, "SAR": 0.27, "QAR": 0.27, "AUD": 0.65,
    "NZD": 0.6, "CAD": 0.73, "SGD": 0.75, "SEK": 0.095, "NOK": 0.093, "DKK": 0.145, "CHF": 1.13, "BRL": 0.18,
    "MXN": 0.055, "PHP": 0.017, "MYR": 0.22, "IDR": 0.000063, "JPY": 0.0066, "HKD": 0.128, "PLN": 0.25,
}  # fmt: skip
SYMBOL_CURRENCY: Final = (("€", "EUR"), ("£", "GBP"), ("₹", "INR"), ("$", "USD"))
EARLY_NAMED: Final = frozenset({"pre_seed", "seed", "angel", "friends_family", "idea"})
EARLY_ANY: Final = EARLY_NAMED | {"accelerator", "grant", "crowdfunding"}
# Where a signal's team size came from, by source (details.team_size_source wins when a source sets it).
SIZE_SOURCE: Final[dict[str, str]] = {
    "startup_lists": "list", "hn_launches": "list", "betalist": "list", "sec_edgar": "filing",
    "funding_rss": "news", "gdelt": "news", "startup_news": "news", "ats_jobs": "job_post", "job_feeds": "job_post",
    "adzuna": "job_post", "careers_watch": "job_post", "apna": "job_post", "grounded_search": "snippet",
}  # fmt: skip
SIZE_PRIORITY: Final[dict[str, int]] = {"team_page": 1, "filing": 2, "list": 3, "job_post": 4, "news": 5, "snippet": 6}
SOURCE_WORDS: Final[dict[str, str]] = {
    "hn_launches": "Hacker News", "betalist": "BetaList", "startup_lists": "an accelerator list",
    "funding_rss": "the news", "gdelt": "the news", "sec_edgar": "an SEC filing",
}  # fmt: skip
ROUND_WORDS: Final[dict[str, str]] = {
    "pre_seed": "pre-seed", "seed": "seed", "angel": "angel", "grant": "grant", "crowdfunding": "crowdfunding",
    "accelerator": "accelerator", "friends_family": "friends and family", "idea": "idea stage",
    "series_a": "Series A", "series_b": "Series B", "series_c": "Series C", "series_d": "Series D",
    "series_e": "later series", "growth": "growth", "late": "late stage", "private_equity": "private equity",
    "ipo": "IPO", "acquired": "acquisition", "debt": "debt", "unknown": "funding",
}  # fmt: skip


# =========================================================================
# Rules (config/scoring.yaml `startup` plus settings startup.max_team and startup.max_raise_usd)
# =========================================================================


@dataclass(frozen=True)
class Rules:
    """The qualification numbers for one segment."""

    max_team: int = DEFAULT_MAX_TEAM
    max_raise_usd: float = DEFAULT_MAX_RAISE_USD
    max_age_years: float = 10
    signal_days: int = 180
    engineering_roles_team: int = 3
    github_members_team: int = 2
    github_active_days: int = 180
    funding_valid_days: int = 540
    pay_points: Mapping[str, float] = field(default_factory=dict)
    pay_cap: float = 20
    yes_at: float = 14
    likely_at: float = 6

    @classmethod
    def from_config(
        cls, raw: Mapping[str, Any] | None, *, max_team: int | None = None, max_raise_usd: float | None = None
    ) -> Rules:
        """From a scoring config's `startup` block; settings, when given, win over the block's own limits."""
        raw = raw or {}
        tech = raw.get("tech") or {}
        pay = dict(raw.get("can_pay") or {})
        return cls(
            max_team=int(max_team if max_team is not None else raw.get("max_team", DEFAULT_MAX_TEAM)),
            max_raise_usd=float(
                max_raise_usd if max_raise_usd is not None else raw.get("max_raise_usd", DEFAULT_MAX_RAISE_USD)
            ),
            max_age_years=float(raw.get("max_age_years", 10)),
            signal_days=int(tech.get("signal_days", 180)),
            engineering_roles_team=int(tech.get("engineering_roles_team", 3)),
            github_members_team=int(tech.get("github_members_team", 2)),
            github_active_days=int(tech.get("github_active_days", 180)),
            funding_valid_days=int(pay.pop("funding_valid_days", 540)),
            pay_cap=float(pay.pop("cap", 20)),
            yes_at=float(pay.pop("yes_at", 14)),
            likely_at=float(pay.pop("likely_at", 6)),
            pay_points={str(k): float(v) for k, v in pay.items()},
        )

    @classmethod
    def for_segment(cls, seg: Segment, *, max_team: int | None = None, max_raise_usd: float | None = None) -> Rules:
        return cls.from_config(scoring_config(seg).get("startup"), max_team=max_team, max_raise_usd=max_raise_usd)

    @classmethod
    def defaults(cls) -> Rules:
        """config/scoring.yaml with no segment override and the code's default limits."""
        return cls.from_config(load_yaml_config("scoring").get("startup"))


# =========================================================================
# The profile
# =========================================================================


@dataclass(frozen=True)
class Piece:
    """One piece of evidence: its kind, the fact or signal ids behind it and a plain reason."""

    kind: str
    ids: tuple[str, ...]
    why: str


@dataclass(frozen=True)
class Proxy:
    """One can-pay sign and its points."""

    key: str
    points: float
    ids: tuple[str, ...]
    why: str


@dataclass(frozen=True)
class Funding:
    round: str  # normalised (sources.startup.normalize_round)
    usd: float | None
    on: date | None
    ids: tuple[str, ...]


@dataclass
class Profile:
    """What qualification found for one business: the `startup_profiles` row plus what scoring needs."""

    business_id: str
    is_startup: bool | None = None
    is_startup_why: str = ""
    team_size: int | None = None
    team_size_source: str | None = None
    tech_team: str = "unknown"
    can_pay: str = "unknown"
    product_status: str = "unknown"
    no_code_platform: str | None = None
    uses_ai: bool | None = None
    funding_usd: float | None = None
    funding_round: str | None = None
    funding_at: date | None = None
    domain_created_at: date | None = None
    first_seen_at: date | None = None
    founded_year: int | None = None
    online_since: date | None = None
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    no_tech_signs: list[Piece] = field(default_factory=list)  # one per kind: two make tech_team 'none'
    engineer_signs: list[Piece] = field(default_factory=list)
    pay: list[Proxy] = field(default_factory=list)
    pay_points: float = 0.0
    late_round: str | None = None
    raised_usd: float | None = None  # every round with a known amount
    early_round: str | None = None  # the newest early round known
    disqualified: list[str] = field(default_factory=list)  # grade D in score s3.0
    signal_ids: frozenset[str] = frozenset()

    def ids(self, answer: str) -> list[str]:
        return list((self.evidence.get(answer) or {}).get("ids") or [])

    def note(self, answer: str, ids: Iterable[Any], why: str) -> None:
        self.evidence[answer] = {"ids": list(dict.fromkeys(str(i) for i in ids)), "why": why[:300]}

    def ref(self, raw: Any) -> str:
        """'signal 1a2b' or 'fact 3c4d' for a reason line."""
        return f"{'signal' if str(raw) in self.signal_ids else 'fact'} {evidence.short_id(raw)}"

    @property
    def all_ids(self) -> set[str]:
        return {i for v in self.evidence.values() for i in v.get("ids") or []}

    def snapshot(self) -> dict[str, Any]:
        """The answers in plain JSON (stored with each s3.0 score row)."""
        return {
            "is_startup": self.is_startup,
            "team_size": self.team_size,
            "tech_team": self.tech_team,
            "can_pay": self.can_pay,
            "product_status": self.product_status,
            "no_code_platform": self.no_code_platform,
            "uses_ai": self.uses_ai,
            "funding_usd": self.funding_usd,
            "funding_round": self.funding_round,
            "no_tech_signs": [p.kind for p in self.no_tech_signs],
            "disqualified": self.disqualified,
        }


# =========================================================================
# Small readers
# =========================================================================

_MONTHS: Final = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _as_date(raw: Any) -> date | None:
    """A date from a date, a datetime, an ISO string or a written one ("March 2025", "2024")."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
        year = re.search(r"\b(?:19|20)\d{2}\b", text)
        if year:
            low = text.lower()
            month = next((i for i, m in enumerate(_MONTHS, start=1) if re.search(rf"\b{m}", low)), 1)
            return date(int(year.group(0)), month, 1)
    return None


def _value(f: Mapping[str, Any] | None) -> Mapping[str, Any]:
    raw = (f or {}).get("value")
    return raw if isinstance(raw, Mapping) else {}


def _by(facts: Sequence[Row], *fields: str) -> list[Row]:
    return evidence.by_field(facts, *fields)


def _newest(rows: Iterable[Row]) -> Row | None:
    return max(rows, key=lambda r: r.get("created_at") or EPOCH, default=None)


def _probe(facts: Sequence[Row], name: str) -> Row | None:
    """The newest probe fact of one kind (contract 4.2: field `probe.<name>`, model 'rule')."""
    return _newest(f for f in facts if f.get("field") == f"probe.{name}")


def _round_of(text: str | None) -> str:
    low = (text or "").strip().lower()
    if low in ("series_b_plus", "series b+", "series b plus"):  # classify_startup_item's last bucket
        return "series_b"
    return normalize_round(low)


def to_usd(amount: Any, currency: str | None, quote: str, default_currency: str) -> float | None:
    """An amount in dollars: its own currency, else the symbol in the quote, else the segment's currency."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    code = (currency or "").strip().upper()
    if code not in USD_PER:
        code = next((c for sym, c in SYMBOL_CURRENCY if sym in quote), default_currency.upper())
    return value * USD_PER.get(code, 1.0)


def _recent(on: Any, now: datetime, days: int) -> bool:
    day = _as_date(on)
    return day is None or (now.date() - day).days <= days


def _detail(s: Mapping[str, Any], *keys: str) -> Any:
    details = s.get("details") or {}
    return next((details[k] for k in keys if details.get(k) not in (None, "")), None)


def _int(raw: Any) -> int | None:
    try:
        return int(float(raw)) if raw is not None and str(raw).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _usd_text(usd: float) -> str:
    return f"${usd / 1e6:.1f}M" if usd >= 1e6 else f"${usd:,.0f}"


def _a(word: str) -> str:
    return f"{'an' if word[:1].lower() in 'aeiou' else 'a'} {word}"


def _free_builder(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in FREE_BUILDER_DOMAINS)


# =========================================================================
# The team and the money
# =========================================================================


@dataclass(frozen=True)
class Member:
    fact: Row
    name: str
    role: str
    founder: bool
    technical: bool


def team_members(facts: Sequence[Row]) -> list[Member]:
    """The verified team, one entry per person. Investors, advisors and board members are not the team.

    Technical means the role or the quoted line says so (CTO, engineer, developer, technical co-founder, an
    ex-Google engineer); the model's own flag counts only when no role was given."""
    out: dict[str, Member] = {}
    for f in _by(facts, "team_member"):
        v = _value(f)
        name = str(v.get("name") or "").strip()
        role = str(v.get("role") or "").strip()
        text = f"{role} {f.get('quote') or ''}"
        if not name or NOT_TEAM_ROLE.search(role):
            continue
        technical = bool(TECH_ROLE.search(text)) or (v.get("is_engineer") is True and not role)
        founder = v.get("is_founder") is True or bool(FOUNDER_ROLE.search(text))
        key = re.sub(r"[^a-z]", "", name.lower())
        if key and key not in out:
            out[key] = Member(f, name, role, founder, technical)
    return list(out.values())


def funding_events(facts: Sequence[Row], signals: Sequence[Row], currency: str) -> tuple[list[Funding], list[Piece]]:
    """Rounds from funding signals, the site's own funding lines and accelerator batches, one per round."""
    raw: list[Funding] = []
    batches: list[Piece] = []
    for s in signals:
        batch = _detail(s, "batch", "accelerator")
        if s["type"] in ("launch", "news") and batch:
            raw.append(Funding("accelerator", None, _as_date(s.get("observed_at")), (str(s["id"]),)))
            batches.append(Piece("accelerator", (str(s["id"]),), f"in {batch}"))
        if s["type"] != "funding":
            continue
        rnd = _round_of(_detail(s, "round", "funding_round") or s.get("quote"))
        usd = _detail(s, "amount_usd")
        when = _as_date(_detail(s, "announced_at", "date")) or _as_date(s.get("observed_at"))
        raw.append(Funding(rnd, float(usd) if usd is not None else None, when, (str(s["id"]),)))
    for f in _by(facts, "funding_mention"):
        v = _value(f)
        quote = str(f.get("quote") or "")
        rnd = _round_of(str(v.get("round") or "") or quote)
        usd = to_usd(v.get("amount"), v.get("currency"), quote, currency) if v.get("amount") is not None else None
        raw.append(Funding(rnd, usd, _as_date(v.get("date")), (str(f["id"]),)))
    merged: list[Funding] = []
    for e in sorted(raw, key=lambda e: (e.on or date.min, e.ids)):
        same = next(
            (
                i
                for i, m in enumerate(merged)
                if (e.round != "unknown" and m.round == e.round)
                or (e.usd is not None and m.usd is not None and abs(m.usd - e.usd) <= 0.1 * max(m.usd, e.usd))
            ),
            None,
        )
        if same is None:
            merged.append(e)
            continue
        m = merged[same]
        merged[same] = Funding(
            m.round if m.round != "unknown" else e.round,
            max((x for x in (m.usd, e.usd) if x is not None), default=None),
            max((x for x in (m.on, e.on) if x is not None), default=None),
            m.ids + tuple(i for i in e.ids if i not in m.ids),
        )
    return merged, batches


# =========================================================================
# assess()
# =========================================================================


def assess(
    business: Mapping[str, Any],
    facts: Sequence[Row],
    signals: Sequence[Row],
    now: datetime,
    rules: Rules | None = None,
    *,
    currency: str = "USD",
) -> Profile:
    """The startup profile of one business from its verified facts (AI and probe) and all its signals."""
    rules = rules or Rules.defaults()
    p = Profile(business_id=str(business.get("id") or ""), signal_ids=frozenset(str(s["id"]) for s in signals))
    _dates(p, business, facts, signals)
    members = team_members(facts)
    _tech_team(p, members, facts, signals, now, rules)
    _team_size(p, members, facts, signals)
    events, batches = funding_events(facts, signals, currency)
    _funding(p, events)
    _product(p, facts)
    _uses_ai(p, facts)
    _can_pay(p, business, events, facts, signals, now, rules)
    _is_startup(p, members, events, batches, facts, signals, now, rules)
    _disqualify(p, rules)
    return p


def _dates(p: Profile, b: Mapping[str, Any], facts: Sequence[Row], signals: Sequence[Row]) -> None:
    rdap = _probe(facts, "domain_created")
    if rdap is not None and _as_date(_value(rdap).get("date")):
        p.domain_created_at = _as_date(_value(rdap).get("date"))
        p.note("domain_created_at", [rdap["id"]], f"domain registered on {p.domain_created_at} (RDAP)")
    seen: list[tuple[date, str, str]] = []
    for name, label in (("domain_created", "domain registered"), ("first_cert", "first certificate"),
                        ("first_capture", "first web archive copy")):  # fmt: skip
        f = _probe(facts, name)
        day = _as_date(_value(f).get("date"))
        if f is not None and day is not None:
            seen.append((day, str(f["id"]), label))
    if seen:
        day, fid, label = min(seen)
        p.online_since = day
        p.note("online_since", [fid], f"online since {day} ({label})")
    years = [(int(y), f) for f in _by(facts, "founded_year") if (y := _value(f).get("year")) is not None]
    if years:
        year, f = min(years, key=lambda t: t[0])
        p.founded_year = year
        p.note("founded_year", [f["id"]], f"founded in {year} ({p.ref(f['id'])})")
    firsts = [d for d in [_as_date(b.get("created_at")), *(_as_date(s.get("observed_at")) for s in signals)] if d]
    p.first_seen_at = min(firsts) if firsts else None


def _age_years(p: Profile, now: datetime) -> float | None:
    starts = [d for d in (p.online_since, date(p.founded_year, 1, 1) if p.founded_year else None) if d]
    return (now.date() - min(starts)).days / 365.25 if starts else None


def _engineer_signs(facts: Sequence[Row], recent: Sequence[Row], now: datetime, rules: Rules) -> list[Piece]:
    eng: list[Piece] = []
    flag = next((f for f in _by(facts, "in_house_tech") if fact_flag(f) is True), None)
    if flag is not None:
        eng.append(Piece("in_house_tech", (str(flag["id"]),), "their pages show an in-house tech team"))
    said = next((f for f in _by(facts, "tech_statement") if _value(f).get("kind") == "engineering_team"), None)
    if said is not None:
        eng.append(Piece("own_words", (str(said["id"]),), f'their own words: "{str(said.get("quote"))[:80]}"'))
    for s in recent:
        roles = _int(_detail(s, "engineering_roles"))
        if roles is not None and roles >= rules.engineering_roles_team:
            eng.append(Piece("careers_board", (str(s["id"]),), f"{roles} engineering roles open"))
            break
    github = _probe(facts, "github")
    if github is not None:
        v = _value(github)
        pushed = _as_date(v.get("last_push"))
        active = pushed is not None and (now.date() - pushed).days <= rules.github_active_days
        people = _int(v.get("members_public")) or 0
        if active and people >= rules.github_members_team:
            eng.append(Piece("github", (str(github["id"]),), f"{people} people push code to their GitHub org"))
    return eng


def _code_activity(facts: Sequence[Row], now: datetime, rules: Rules) -> Piece | None:
    """Recent public code by fewer people than an engineering team: someone technical is there."""
    github = _probe(facts, "github")
    v = _value(github)
    pushed = _as_date(v.get("last_push"))
    if github is None or pushed is None or (now.date() - pushed).days > rules.github_active_days:
        return None
    if (_int(v.get("public_repos")) or 0) <= 0:
        return None
    return Piece("github", (str(github["id"]),), f"code pushed to their GitHub org on {pushed}")


def _no_tech_signs(
    members: Sequence[Member], facts: Sequence[Row], recent: Sequence[Row], p: Profile
) -> dict[str, Piece]:
    """At most one sign per kind; two kinds make tech_team 'none' (contract 4.3)."""
    signs: dict[str, Piece] = {}
    if members and any(m.founder for m in members) and not any(m.technical for m in members):
        names = ", ".join(f"{m.name} ({m.role or 'founder'})" for m in members[:3])
        people = "person" if len(members) == 1 else "people"
        signs["team_page"] = Piece(
            "team_page",
            tuple(str(m.fact["id"]) for m in members),
            f"the team page lists {len(members)} {people}, none technical: {names}",
        )
    for f in _by(facts, "tech_statement"):
        kind = str(_value(f).get("kind") or "")
        quote = str(f.get("quote") or "")[:90]
        label = {
            "no_technical_team": "their own words",
            "outsourced": "built by others",
            "no_code": "built with a no-code tool",
        }
        key = {"no_technical_team": "own_words", "outsourced": "outsourced", "no_code": "no_code"}.get(kind)
        if key and key not in signs:
            signs[key] = Piece(key, (str(f["id"]),), f'{label[kind]}: "{quote}"')
    for s in recent:
        text = f"{_detail(s, 'role', 'title') or ''} {s.get('quote') or ''}"
        if s["type"] == "hiring_builder" and FIRST_BUILDER.search(text) and "first_builder" not in signs:
            role = str(_detail(s, "role", "title") or "their first engineer")
            signs["first_builder"] = Piece("first_builder", (str(s["id"]),), f"hiring {role} ({p.ref(s['id'])})")
        elif s["type"] == "public_ask" and "asked" not in signs:
            signs["asked"] = Piece("asked", (str(s["id"]),), f"asked in public for a builder ({p.ref(s['id'])})")
    if "first_builder" not in signs:
        for f in _by(facts, "careers_role"):
            v = _value(f)
            if v.get("category") == "builder" and FIRST_BUILDER.search(str(v.get("title") or "")):
                why = f"their careers page hires {v.get('title')} ({p.ref(f['id'])})"
                signs["first_builder"] = Piece("first_builder", (str(f["id"]),), why)
                break
    if "no_code" not in signs:
        tech = _probe(facts, "tech")
        platform = str(_value(tech).get("no_code_platform") or "").lower()
        built = next((f for f in _by(facts, "product_status") if _value(f).get("value") == "no_code"), None)
        if tech is not None and platform in APP_BUILDERS:
            signs["no_code"] = Piece("no_code", (str(tech["id"]),), f"the product runs on {platform.title()}")
        elif built is not None:
            signs["no_code"] = Piece(
                "no_code", (str(built["id"]),), f"the product runs on a no-code tool ({p.ref(built['id'])})"
            )
    return signs


def _tech_team(
    p: Profile, members: Sequence[Member], facts: Sequence[Row], signals: Sequence[Row], now: datetime, rules: Rules
) -> None:
    """has_engineers, lone_cto, none (two independent signs) or unknown; see the module docstring."""
    recent = [s for s in signals if _recent(s.get("observed_at"), now, rules.signal_days)]
    tech_people = [m for m in members if m.technical]
    eng = _engineer_signs(facts, recent, now, rules)
    signs = _no_tech_signs(members, facts, recent, p)
    p.engineer_signs, p.no_tech_signs = eng, list(signs.values())
    activity = _code_activity(facts, now, rules)
    if eng or len(tech_people) >= 2:
        p.tech_team = "has_engineers"
        ids = [m.fact["id"] for m in tech_people] + [i for piece in eng for i in piece.ids]
        whys = [f"{m.name} ({m.role})" for m in tech_people[:3]] + [piece.why for piece in eng[:2]]
        p.note("tech_team", ids, "a team with engineers: " + "; ".join(whys))
    elif len(tech_people) == 1:
        m = tech_people[0]
        p.tech_team = "lone_cto"
        p.note("tech_team", [m.fact["id"]], f"one technical person and no engineers: {m.name} ({m.role})")
    elif activity is not None:
        p.no_tech_signs = []  # recent code says someone technical is there, whatever the team page shows
        p.note("tech_team", activity.ids, f"unknown: {activity.why}, so someone technical is there")
    elif len(signs) >= 2:
        p.tech_team = "none"
        p.note(
            "tech_team",
            [i for x in signs.values() for i in x.ids],
            "no tech team: " + "; ".join(x.why for x in signs.values()),
        )
    elif signs:
        piece = next(iter(signs.values()))
        p.note("tech_team", piece.ids, f"unknown, one sign so far: {piece.why}")


def _team_size(p: Profile, members: Sequence[Member], facts: Sequence[Row], signals: Sequence[Row]) -> None:
    found: list[tuple[int, int, str, tuple[str, ...], str]] = []  # (priority, count, source, ids, why)
    stated = [(c, f) for f in _by(facts, "team_size") if (c := fact_count(f)) is not None]
    if stated:
        count, f = max(stated, key=lambda t: t[0])  # two stated sizes: the larger, a team is never understated
        found.append((1, count, "team_page", (str(f["id"]),), f"their site says {count} ({p.ref(f['id'])})"))
    for s in sorted(signals, key=lambda s: s.get("observed_at") or EPOCH, reverse=True):
        said = _int(_detail(s, "team_size", "employees", "current_employees"))
        if said is None or said <= 0:
            continue
        source = str(_detail(s, "team_size_source") or SIZE_SOURCE.get(str(s.get("source")), "snippet"))
        found.append(
            (SIZE_PRIORITY.get(source, 6), said, source, (str(s["id"]),), f"{said} per {source} ({p.ref(s['id'])})")
        )
    for f in _by(facts, "jsonld_employees"):
        coded = _int(vget(f.get("value"), "count", "value", "maxValue", "max"))
        if coded:
            found.append((7, coded, "team_page", (str(f["id"]),), f"{coded} in their structured data"))
    for f in _by(facts, "staff_or_doctors"):
        staff = fact_count(f)
        if staff:
            found.append((8, staff, "team_page", (str(f["id"]),), f"{staff} staff on their site ({p.ref(f['id'])})"))
    best = min(found, key=lambda t: (t[0], -t[1])) if found else None
    listed = len(members)
    if listed and (best is None or listed > best[1]):
        p.team_size, p.team_size_source = listed, "team_page"
        people = "person" if listed == 1 else "people"
        p.note("team_size", [m.fact["id"] for m in members], f"the team page names {listed} {people}")
    elif best is not None:
        p.team_size, p.team_size_source = best[1], best[2]
        p.note("team_size", best[3], best[4])


def _funding(p: Profile, events: Sequence[Funding]) -> None:
    if not events:
        return
    late = next((e for e in events if e.round in LATE_ROUNDS), None)
    if late is not None:
        p.late_round = late.round
    amounts = [e.usd for e in events if e.usd is not None]
    p.raised_usd = sum(amounts) if amounts else None
    newest = max(events, key=lambda e: (e.on or date.min, len(e.ids)))
    p.funding_round, p.funding_at, p.funding_usd = newest.round, newest.on, p.raised_usd
    early = [e for e in events if e.round in EARLY_ANY]
    if early:
        p.early_round = max(early, key=lambda e: e.on or date.min).round
    parts = [
        f"{ROUND_WORDS.get(e.round, e.round)}{' of ' + _usd_text(e.usd) if e.usd else ''}"
        f"{' on ' + str(e.on) if e.on else ''}"
        for e in events
    ]
    p.note("funding", [i for e in events for i in e.ids], "raised: " + "; ".join(parts))


def _product(p: Profile, facts: Sequence[Row]) -> None:
    store, links, tech = _probe(facts, "app_store"), _probe(facts, "app_links"), _probe(facts, "tech")
    stated = _newest(_by(facts, "product_status"))
    platform = str(_value(tech).get("no_code_platform") or "").strip().lower()
    if tech is not None and platform:
        p.no_code_platform = platform
        p.note("no_code_platform", [tech["id"]], f"their site runs on {platform.title()} (tech probe)")
    elif stated is not None and _value(stated).get("platform"):
        p.no_code_platform = str(_value(stated)["platform"]).strip().lower()
        p.note("no_code_platform", [stated["id"]], f"built on {_value(stated)['platform']} ({p.ref(stated['id'])})")
    app_ids = bool(_value(links).get("ios_app_ids") or _value(links).get("android_packages"))
    no_code_said = next((f for f in _by(facts, "tech_statement") if _value(f).get("kind") == "no_code"), None)
    said = str(_value(stated).get("value") or "")
    quote = str((stated or {}).get("quote") or "")[:90]
    if store is not None and (_value(store).get("url") or _value(store).get("name")):
        p.product_status = "mobile_app"
        p.note("product_status", [store["id"]], f"an app in the store: {_value(store).get('name') or 'their app'}")
    elif links is not None and app_ids:
        p.product_status = "mobile_app"
        p.note("product_status", [links["id"]], "their domain links a mobile app")
    elif stated is not None and said in ("idea", "landing", "waitlist"):
        p.product_status = said
        p.note("product_status", [stated["id"]], f'{said}: "{quote}"')
    elif platform in APP_BUILDERS or said == "no_code" or no_code_said is not None:
        p.product_status = "no_code"
        backing = [tech if platform in APP_BUILDERS else None, stated if said == "no_code" else None, no_code_said]
        on = f" on {platform.title()}" if platform in APP_BUILDERS else ""
        p.note("product_status", [x["id"] for x in backing if x is not None], f"a no-code product{on}")
    elif stated is not None and said:
        p.product_status = said
        p.note("product_status", [stated["id"]], f'{said.replace("_", " ")}: "{quote}"')
    else:
        site = next((f for f in _by(facts, "website_status") if _value(f).get("status") == "coming_soon"), None)
        if site is not None:
            p.product_status = "landing"
            p.note("product_status", [site["id"]], "their site says coming soon")


def _uses_ai(p: Profile, facts: Sequence[Row]) -> None:
    said = _newest(f for f in _by(facts, "uses_ai") if fact_flag(f) is not None)
    tech = _probe(facts, "tech")
    vendors = [str(v) for v in _value(tech).get("ai_vendors") or []]
    if said is not None:
        p.uses_ai = fact_flag(said)
        p.note("uses_ai", [said["id"]], f'"{str(said.get("quote"))[:90]}"')
    elif tech is not None and vendors:
        p.uses_ai = True
        p.note("uses_ai", [tech["id"]], f"AI vendors on their site: {', '.join(vendors[:3])}")


def _can_pay(
    p: Profile,
    b: Mapping[str, Any],
    events: Sequence[Funding],
    facts: Sequence[Row],
    signals: Sequence[Row],
    now: datetime,
    rules: Rules,
) -> None:
    """The best money sign, the best revenue sign and the small ones, at most `pay_cap` points."""
    pts = rules.pay_points
    money: list[Proxy] = []
    recent = [e for e in events if _recent(e.on, now, rules.funding_valid_days) and e.round not in LATE_ROUNDS]
    usd = sum(e.usd for e in recent if e.usd is not None)
    ids = tuple(i for e in recent if e.usd is not None for i in e.ids)
    for key, floor in (("raised_250k", 250_000), ("raised_50k", 50_000), ("raised_small", 0.01)):
        if usd >= floor:
            money.append(Proxy(key, pts.get(key, 0), ids, f"raised {_usd_text(usd)}"))
            break
    for rnd in ("pre_seed", "seed", "angel", "friends_family", "accelerator", "crowdfunding", "grant"):
        hit = next((e for e in recent if e.round == rnd), None)
        if hit is not None:
            key = "round_known" if rnd in EARLY_NAMED else rnd
            money.append(Proxy(key, pts.get(key, 0), hit.ids, f"{_a(ROUND_WORDS[rnd])} round"))
    revenue = [
        Proxy(kind, pts.get(kind, 0), (str(f["id"]),), f'{kind.replace("_", " ")}: "{str(f.get("quote"))[:70]}"')
        for f in _by(facts, "revenue_hint")
        if (kind := str(_value(f).get("kind") or "")) in ("revenue", "paying_customers", "pricing")
    ]
    small: list[Proxy] = []
    hire = next(
        (s for s in signals if s["type"] == "hiring_builder" and _recent(s.get("observed_at"), now, rules.signal_days)),
        None,
    )
    if hire is not None:
        small.append(Proxy("hiring_builder", pts.get("hiring_builder", 0), (str(hire["id"]),), "hiring a builder"))
    dns = _probe(facts, "dns")
    hints = {str(h).lower() for h in _value(dns).get("txt_hints") or []}
    mail = str(_value(dns).get("mx_provider") or "").lower()
    paid = sorted(hints & PAID_TOOLS) + ([f"{mail.title()} mail"] if mail in PAID_MAIL else [])
    if dns is not None and paid:
        small.append(
            Proxy("pays_for_tools", pts.get("pays_for_tools", 0), (str(dns["id"]),), "pays for " + ", ".join(paid[:3]))
        )
    site = next((f for f in _by(facts, "website_status") if _value(f).get("status") == "live"), None)
    domain = str(b.get("web_domain") or "").lower()
    if site is not None and domain and not _free_builder(domain):
        small.append(
            Proxy("custom_domain", pts.get("custom_domain", 0), (str(site["id"]),), f"a live site on {domain}")
        )
    best_money = max(money, key=lambda x: x.points, default=None)
    best_revenue = max(revenue, key=lambda x: x.points, default=None)
    chosen = [x for x in (best_money, best_revenue) if x is not None] + small
    p.pay = chosen
    p.pay_points = min(rules.pay_cap, sum(x.points for x in chosen))
    no_budget = next((f for f in _by(facts, "revenue_hint") if _value(f).get("kind") == "no_budget"), None)
    if no_budget is not None and best_money is None and best_revenue is None:
        p.can_pay, p.pay_points = "no", 0.0
        p.note("can_pay", [no_budget["id"]], f'no budget: "{str(no_budget.get("quote"))[:90]}"')
        return
    p.can_pay = "yes" if p.pay_points >= rules.yes_at else "likely" if p.pay_points >= rules.likely_at else "unknown"
    if chosen:
        p.note("can_pay", [i for x in chosen for i in x.ids], "; ".join(x.why for x in chosen))


def _is_startup(
    p: Profile,
    members: Sequence[Member],
    events: Sequence[Funding],
    batches: Sequence[Piece],
    facts: Sequence[Row],
    signals: Sequence[Row],
    now: datetime,
    rules: Rules,
) -> None:
    signs: list[Piece] = []
    early = [
        e for e in events if e.round in EARLY_NAMED | {"crowdfunding", "grant"} or (e.round == "unknown" and e.usd)
    ]
    if early:
        e = max(early, key=lambda e: e.on or date.min)
        amount = f" of {_usd_text(e.usd)}" if e.usd else ""
        signs.append(Piece("funding", e.ids, f"raised {_a(ROUND_WORDS.get(e.round, 'funding'))} round{amount}"))
    signs += list(batches)
    launch = next((s for s in signals if s["type"] == "launch"), None)
    if launch is not None:
        signs.append(
            Piece(
                "launch",
                (str(launch["id"]),),
                f"launched on {SOURCE_WORDS.get(str(launch.get('source')), 'a launch list')}",
            )
        )
    age = _age_years(p, now)
    founders = [m for m in members if m.founder]
    if age is not None and age <= 5 and founders and p.product_status != "unknown":
        since = p.founded_year or (p.online_since.year if p.online_since else "")
        ids = tuple(str(m.fact["id"]) for m in founders[:2]) + tuple(p.ids("product_status"))
        signs.append(Piece("young", ids, f"a young company (since {since}) with founders and a product"))
    agency = next((f for f in _by(facts, "is_agency_or_vendor") if fact_flag(f) is True), None)
    if agency is not None and not any(s.kind in ("funding", "accelerator") for s in signs):
        p.is_startup = False
        p.is_startup_why = f"Not a startup: sells services to other businesses ({p.ref(agency['id'])})."
        p.note("is_startup", [agency["id"]], p.is_startup_why)
        return
    if signs:
        p.is_startup = True
        p.is_startup_why = ("Startup: " + "; ".join(f"{s.why} ({p.ref(s.ids[0])})" for s in signs[:3]) + ".")[:300]
        p.note("is_startup", [i for s in signs for i in s.ids], p.is_startup_why)
        return
    if age is not None and age > rules.max_age_years:
        p.is_startup = False
        since = p.founded_year or (p.online_since.year if p.online_since else "")
        p.is_startup_why = f"Not a startup: an established business (since {since}) with no startup sign."
        p.note("is_startup", p.ids("founded_year") + p.ids("online_since"), p.is_startup_why)
        return
    p.is_startup_why = "Unknown: no funding, launch or founding date found yet."


def _disqualify(p: Profile, rules: Rules) -> None:
    """Grade D in score s3.0 (contract 4.3): too big, engineers, a late round, too much money, not a startup."""
    if p.team_size is not None and p.team_size > rules.max_team:
        p.disqualified.append(f"{p.team_size} people (more than {rules.max_team})")
    if p.tech_team == "has_engineers":
        p.disqualified.append("a team with engineers")
    if p.late_round is not None:
        p.disqualified.append(f"late stage funding: {ROUND_WORDS.get(p.late_round, p.late_round)}")
    if p.raised_usd is not None and p.raised_usd > rules.max_raise_usd:
        p.disqualified.append(f"raised about {_usd_text(p.raised_usd)} (more than {_usd_text(rules.max_raise_usd)})")
    if p.is_startup is False:
        p.disqualified.append("not a startup, " + p.is_startup_why.removeprefix("Not a startup: ").rstrip("."))


# =========================================================================
# Storing (startup_profiles, contract 4.3) and the phase
# =========================================================================

COLUMNS: Final = (
    "is_startup", "is_startup_why", "team_size", "team_size_source", "team_size_evidence", "tech_team",
    "tech_team_evidence", "can_pay", "can_pay_evidence", "product_status", "no_code_platform", "uses_ai",
    "funding_usd", "funding_round", "funding_at", "domain_created_at", "first_seen_at", "evidence",
)  # fmt: skip


def row_of(p: Profile) -> dict[str, Any]:
    """The `startup_profiles` columns of a profile (without business_id and the times)."""
    return {
        "is_startup": p.is_startup,
        "is_startup_why": p.is_startup_why or None,
        "team_size": p.team_size,
        "team_size_source": p.team_size_source,
        "team_size_evidence": p.ids("team_size"),
        "tech_team": p.tech_team,
        "tech_team_evidence": p.ids("tech_team"),
        "can_pay": p.can_pay,
        "can_pay_evidence": p.ids("can_pay"),
        "product_status": p.product_status,
        "no_code_platform": p.no_code_platform,
        "uses_ai": p.uses_ai,
        "funding_usd": round(p.funding_usd) if p.funding_usd is not None else None,
        "funding_round": p.funding_round,
        "funding_at": p.funding_at,
        "domain_created_at": p.domain_created_at,
        "first_seen_at": p.first_seen_at,
        "evidence": p.evidence,
    }


def _comparable(row: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: row.get(k) for k in COLUMNS}
    for k in ("team_size_evidence", "tech_team_evidence", "can_pay_evidence"):
        out[k] = [str(i) for i in out.get(k) or []]
    usd = out.get("funding_usd")
    if usd is not None:
        out["funding_usd"] = int(usd)
    out["evidence"] = out.get("evidence") or {}
    return out


_UPSERT: Final = f"""
insert into public.startup_profiles (business_id, {", ".join(COLUMNS)}, checked_at, updated_at)
values (%(business_id)s, {", ".join(f"%({c})s" for c in COLUMNS)}, %(now)s, %(now)s)
on conflict (business_id) do update set
  {", ".join(f"{c} = excluded.{c}" for c in COLUMNS)},
  checked_at = excluded.checked_at, updated_at = excluded.updated_at
"""

_PENDING: Final = """
select b.id::text as id
  from public.businesses b
  left join public.startup_profiles p on p.business_id = b.id
 where b.segment_id = any(%(segments)s)
   and b.status in ('researched', 'qualified', 'dormant')
   and not exists (select 1 from public.facts f where f.business_id = b.id and f.verified_at is null)
   and (p.business_id is null or p.checked_at is null or p.checked_at < %(stale)s
        or exists (select 1 from public.facts f where f.business_id = b.id and f.verified_at > p.checked_at)
        or exists (select 1 from public.signals s where s.business_id = b.id and s.created_at > p.checked_at))
 order by p.checked_at nulls first, b.researched_at desc nulls last, b.id
 limit %(limit)s
"""


def pending_ids(
    segment_ids: Sequence[str], limit: int | None, now: datetime, conn: Connection[Any] | None = None
) -> list[str]:
    """Verified startups never profiled, with facts or signals newer than their profile, or a month-old one."""
    params = {"segments": list(segment_ids), "limit": limit, "stale": now - RECHECK_AFTER}
    return [str(r["id"]) for r in db.fetch_all(_PENDING, params, conn=conn)]


def write(
    conn: Connection[Any], profiles: Sequence[Profile], existing: Mapping[str, Row], now: datetime
) -> Counter[str]:
    """Upsert the profiles that changed; an unchanged one only gets its checked_at moved on."""
    stats: Counter[str] = Counter()
    changed: list[dict[str, Any]] = []
    same: list[dict[str, Any]] = []
    for p in profiles:
        row = row_of(p)
        old = existing.get(p.business_id)
        if old is not None and _comparable(old) == _comparable(row):
            same.append({"id": p.business_id, "now": now})
            continue
        stats["profiles.new" if old is None else "profiles.changed"] += 1
        changed.append({**row, "business_id": p.business_id, "now": now, "evidence": db.Jsonb(p.evidence)})
    with conn.cursor() as cur:
        if changed:
            cur.executemany(_UPSERT, changed)
        if same:
            cur.executemany("update public.startup_profiles set checked_at = %(now)s where business_id = %(id)s", same)
    stats["profiles.same"] += len(same)
    return stats


def startup_segments(rc: RunContext) -> dict[str, Segment]:
    """The run's enabled segments that hold startups (domain firms)."""
    return {k: v for k, v in enabled_segments(rc).items() if v.domain == "firms"}


def run(rc: RunContext, **_: Any) -> dict[str, Any]:
    """Work out the profile of every startup with new evidence and store it (dry runs store nothing)."""
    now = datetime.now(UTC)
    segments = startup_segments(rc)
    if not segments:
        rc.stats["qualify"] = {"skipped": "no startup segment enabled"}
        return dict(rc.stats["qualify"])
    max_team, max_raise = limits()
    rules = {sid: Rules.for_segment(seg, max_team=max_team, max_raise_usd=max_raise) for sid, seg in segments.items()}
    stats: Counter[str] = Counter()
    ids = pending_ids(list(segments), rc.opts.limit, now)
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start : start + CHUNK]
        biz, facts, signals = evidence.businesses(chunk), evidence.verified_facts(chunk), evidence.signals_for(chunk)
        profiles: list[Profile] = []
        for bid in chunk:
            b = biz.get(bid)
            seg = segments.get(str((b or {}).get("segment_id")))
            if b is None or seg is None:
                continue
            try:
                p = assess(b, facts.get(bid, []), signals.get(bid, []), now, rules[seg.id], currency=seg.currency)
            except Exception as exc:  # one odd record must not stop the run; it is tried again next run
                stats["errors"] += 1
                log.error("qualify.business_failed", business_id=bid, error=f"{type(exc).__name__}: {exc}")
                continue
            profiles.append(p)
            stats[f"tech_team.{p.tech_team}"] += 1
            stats[f"can_pay.{p.can_pay}"] += 1
            stats[f"is_startup.{'unknown' if p.is_startup is None else str(p.is_startup).lower()}"] += 1
            stats["disqualified"] += bool(p.disqualified)
        stats["businesses"] += len(profiles)
        if profiles and not rc.opts.dry_run:
            existing = {
                str(r["business_id"]): r
                for r in db.fetch_all(
                    "select * from public.startup_profiles where business_id = any(%s::uuid[])",
                    [[p.business_id for p in profiles]],
                )
            }
            with db.tx("engine", {"run_id": rc.run_id, "stage": "qualify"}) as conn:
                stats.update(write(conn, profiles, existing, now))
    result = dict(sorted(stats.items()))
    rc.stats["qualify"] = result
    log.info("qualify.done", **{k.replace(".", "_"): v for k, v in result.items()})
    return result
