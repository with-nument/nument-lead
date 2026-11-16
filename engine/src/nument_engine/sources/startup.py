"""Rules every startup source shares (15 Nov 2026): the size gate, the funding round words and the segment a
startup belongs to.

The target is a startup of 2 to 10 people, idea to small seed (under about $2M raised), with no tech team.
Sources drop what is clearly outside that (a Series A, a $10M round, 40 staff) before anything is stored;
everything else goes on to qualification, where "unknown" is allowed.

Founder names found by a source travel with the signal as `details["founders"]` (see `founders_detail`); the
people stage turns them into contacts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from .. import db
from ..normalize import clean_text
from ..segments import Segment, load_yaml_config

DEFAULT_MAX_TEAM = 10
DEFAULT_MAX_RAISE_USD = 2_000_000

# Funding rounds, normalised. A late round means a funded tech team, which is not our client.
EARLY_ROUNDS = frozenset(
    {"idea", "pre_seed", "seed", "angel", "grant", "crowdfunding", "accelerator", "friends_family", "unknown"}
)
LATE_ROUNDS = frozenset(
    {"series_a", "series_b", "series_c", "series_d", "series_e", "growth", "late", "private_equity", "ipo",
     "acquired", "debt"}
)  # fmt: skip
_ROUND_WORDS: tuple[tuple[str, str], ...] = (
    (r"pre[\s-]*seed", "pre_seed"),
    (r"seed", "seed"),
    (r"angel", "angel"),
    (r"grant", "grant"),
    (r"crowd[\s-]*fund|reg(?:ulation)?\s*cf|form\s*c\b", "crowdfunding"),
    (r"accelerator|incubator|y\s*combinator|techstars", "accelerator"),
    (r"friends\s*(?:and|&)\s*family", "friends_family"),
    (r"series[\s_]*[b-z][\s_]*plus|series[\s_]*[b-z]\+", "series_b"),
    (r"series\s*a\b", "series_a"),
    (r"series[\s_]*b\b", "series_b"),
    (r"series\s*c\b", "series_c"),
    (r"series\s*d\b", "series_d"),
    (r"series\s*[e-z]\b", "series_e"),
    (r"growth|late[\s-]*stage", "growth"),
    (r"private\s*equity|buyout", "private_equity"),
    (r"\bipo\b|initial public offering", "ipo"),
    (r"acqui", "acquired"),
    (r"\bdebt\b|venture debt|loan", "debt"),
)


def normalize_round(text: str | None) -> str:
    """'Pre-Seed' -> 'pre_seed', 'Series A' -> 'series_a', nothing recognisable -> 'unknown'."""
    if not text:
        return "unknown"
    low = text.strip().lower()
    if low in EARLY_ROUNDS or low in LATE_ROUNDS:
        return low
    for pattern, name in _ROUND_WORDS:  # pre-seed is tested before seed, series before growth
        if re.search(pattern, low):
            return name
    return "unknown"


@dataclass(frozen=True)
class Gate:
    ok: bool
    reason: str  # ok | not_startup | too_big | late_round | raise_too_big


def limits() -> tuple[int, float]:
    """(most people, most money raised in USD) from settings startup.max_team and startup.max_raise_usd."""
    return (
        int(db.get_setting("startup.max_team", DEFAULT_MAX_TEAM)),
        float(db.get_setting("startup.max_raise_usd", DEFAULT_MAX_RAISE_USD)),
    )


def startup_gate(
    *,
    is_startup: bool | None = None,
    team_size: int | None = None,
    funding_round: str | None = None,
    amount_usd: float | None = None,
    max_team: int = DEFAULT_MAX_TEAM,
    max_raise_usd: float = DEFAULT_MAX_RAISE_USD,
) -> Gate:
    """Drop only what is clearly outside the target; unknown values pass (qualification decides later)."""
    if is_startup is False:
        return Gate(False, "not_startup")
    if team_size is not None and team_size > max_team:
        return Gate(False, "too_big")
    if normalize_round(funding_round) in LATE_ROUNDS:
        return Gate(False, "late_round")
    if amount_usd is not None and amount_usd > max_raise_usd:
        return Gate(False, "raise_too_big")
    return Gate(True, "ok")


@cache
def _countries() -> tuple[frozenset[str], frozenset[str]]:
    cfg = load_yaml_config("outreach")
    allowed = frozenset(str(c).lower() for c in cfg.get("allowed_countries", []))
    blocked = frozenset(str(c).lower() for c in cfg.get("blocked_countries", []))
    return allowed, blocked


def startup_segment(country: str | None, segments: Mapping[str, Segment]) -> Segment | None:
    """The enabled `firms-<country>` segment for a startup, or None: no country, a country where cold email needs
    prior consent (config/outreach.yaml blocked_countries), a country we do not write to, or a segment that is
    off. `segments` is the run's enabled segments."""
    cc = (country or "").strip().lower()
    if len(cc) != 2:
        return None
    allowed, blocked = _countries()
    if cc in blocked or cc not in allowed:
        return None
    return segments.get(f"firms-{cc}")


def founders_detail(founders: Iterable[Mapping[str, Any]], source_url: str | None = None) -> list[dict[str, str]]:
    """Founder names for `Signal.details["founders"]`: [{"name", "role", "source_url"}], cleaned, deduplicated,
    at most 5. A name must look like a person's name (2 to 80 characters, letters, no @ or digits)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for f in founders:
        name = clean_text(str(f.get("name") or ""), 80).strip(" ,.;:")
        if not (2 <= len(name) <= 80) or re.search(r"[@\d]", name) or not re.search(r"[^\W\d_]", name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        item = {"name": name, "role": clean_text(str(f.get("role") or "Founder"), 60) or "Founder"}
        url = f.get("source_url") or source_url
        if url:
            item["source_url"] = str(url)
        out.append(item)
        if len(out) == 5:
            break
    return out
