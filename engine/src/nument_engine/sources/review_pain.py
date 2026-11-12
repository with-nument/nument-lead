"""Review pain from public review texts: Practo patient stories and Google Maps reviews (Step 7.5.5 for sources
that are not the Places API).

One cheap `classify_reviews` call per business reads its recent reviews (at most 90 days old, newest first, at
most 10, each cut to 600 characters) and names the front-desk complaints: calls not answered, slow replies,
booking trouble, long waits, a rude front desk. Code keeps the answer only when its quote is a sentence that
really is in one of the complaining reviews; a quote it cannot find drops the finding (never invent evidence).
Without a router (or when the router refuses) the same flags are found by the Places review patterns.

Unlike Places API content (A.4.4), these reviews are public pages, so the signal keeps one quoted sentence as
evidence, with no reviewer name. The review texts themselves are never stored.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from ..normalize import clean_text
from ..segments import Segment
from .base import DEFAULT_POINTS, QUOTE_MAX, Signal, SourceContext, field_of
from .places import REVIEW_FLAGS

TASK: Final = "classify_reviews"
MAX_AGE_DAYS: Final = 90
MAX_REVIEWS: Final = 10
MAX_CHARS: Final = 600
FLAGS: Final = ("unanswered_calls", "slow_replies", "booking_trouble", "long_wait", "rude_front_desk")
SOURCE_LABELS: Final[dict[str, str]] = {
    "practo": "Practo patient stories",
    "maps_reviews": "Google Maps reviews",
}
# The Places patterns name slow replies after WhatsApp; here every channel counts.
_RULE_FLAG: Final[dict[str, str]] = {"slow_whatsapp": "slow_replies"}
_RULES: Final = {_RULE_FLAG.get(flag, flag): [re.compile(p, re.I) for p in pats] for flag, pats in REVIEW_FLAGS.items()}
_SENTENCE: Final = re.compile(r"(?<=[.!?\n])\s+")
_NORM: Final = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True)
class ReviewText:
    """One public review held in memory: its text, its age in days (None when unknown) and its stars."""

    text: str
    age_days: int | None
    rating: float | None = None


@dataclass
class Pain:
    flags: list[str]
    matching_reviews: int
    of_reviews: int
    newest_flag_age_days: int | None
    quote: str
    how: str  # "ai" or "rules"
    details: dict[str, Any] = field(default_factory=dict)


def recent(reviews: Sequence[ReviewText], max_age: int = MAX_AGE_DAYS) -> list[ReviewText]:
    """Reviews with text and a known age of at most `max_age` days, newest first. An unknown date is never
    taken for a recent one."""
    kept = [r for r in reviews if r.text.strip() and r.age_days is not None and r.age_days <= max_age]
    return sorted(kept, key=lambda r: r.age_days or 0)[:MAX_REVIEWS]


def _norm(text: str) -> str:
    return _NORM.sub(" ", text.lower()).strip()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.replace("\r", "")) if s.strip()]


def find_quote(quote: str | None, texts: Sequence[str]) -> tuple[int, str] | None:
    """(index of the review, the sentence as written) when the quote is in one of the reviews, else None."""
    wanted = _norm(quote or "")
    if len(wanted) < 8:
        return None
    for i, text in enumerate(texts):
        if wanted not in _norm(text):
            continue
        for sentence in sentences(text):
            if wanted in _norm(sentence) or _norm(sentence) in wanted:
                return i, sentence
        return i, (quote or "").strip()
    return None


def age_label(days: int) -> str:
    if days <= 0:
        return "today"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


def by_rules(texts: Sequence[ReviewText]) -> Pain | None:
    """The Places review patterns over the recent reviews, with the matching sentence as the quote."""
    flags: set[str] = set()
    matching: list[ReviewText] = []
    quote = ""
    for r in texts:
        hit = {flag for flag, pats in _RULES.items() if any(p.search(r.text) for p in pats)}
        if not hit:
            continue
        flags |= hit
        matching.append(r)
        if not quote:
            quote = next(
                (s for s in sentences(r.text) if any(p.search(s) for flag in hit for p in _RULES[flag])), r.text
            )
    if not matching:
        return None
    ages = [age for r in matching if (age := r.age_days) is not None]
    return Pain(sorted(flags), len(matching), len(texts), min(ages) if ages else None, quote, "rules")


def classify(ctx: SourceContext, reviews: Sequence[ReviewText], *, business_name: str, source: str) -> Pain | None:
    """Review pain in the recent reviews of one business, or None. One AI call when there is a recent review."""
    texts = recent(reviews)
    if not texts:
        ctx.add(f"{source}.reviews_none_recent")
        return None
    inputs = {
        "business_name": business_name,
        "source": SOURCE_LABELS.get(source, source),
        "reviews": [
            {
                "n": i + 1,
                "age": age_label(r.age_days or 0),
                "rating": r.rating,
                "text": r.text.strip()[:MAX_CHARS],
            }
            for i, r in enumerate(texts)
        ],
    }
    out = ctx.ai(TASK, inputs)
    if out is None:
        ctx.add(f"{source}.reviews_by_rules")
        return by_rules(texts)
    ctx.add(f"{source}.reviews_classified")
    if not field_of(out, "has_pain"):
        return None
    flags = sorted({str(f) for f in field_of(out, "flags", []) or [] if str(f) in FLAGS})
    found = find_quote(field_of(out, "quote"), [r.text[:MAX_CHARS] for r in texts])
    if not flags or found is None:
        ctx.add(f"{source}.reviews_quote_not_found")
        return None
    numbers = {int(n) for n in field_of(out, "complaining_reviews", []) or [] if 1 <= int(n) <= len(texts)}
    numbers.add(found[0] + 1)
    ages = [age for n in numbers if (age := texts[n - 1].age_days) is not None]
    return Pain(flags, len(numbers), len(texts), min(ages) if ages else None, found[1], "ai")


def pain_signal(
    pain: Pain,
    *,
    source: str,
    business_id: str,
    url: str | None,
    seg: Segment | None = None,
    now: datetime | None = None,
) -> Signal:
    """The `review_pain` signal: the newest complaint dates it, one quoted sentence proves it, one a month.
    Points as for Places review pain: the segment's points, one more when two reviews complain."""
    now = now or datetime.now(UTC)
    default = DEFAULT_POINTS["review_pain"]
    base = float(seg.signal_points.get("review_pain", default) if seg is not None else default)
    points = min(base + 1, max(base, 7.0)) if pain.matching_reviews >= 2 else base
    newest = pain.newest_flag_age_days
    return Signal(
        type="review_pain",
        source=source,
        observed_at=now - timedelta(days=int(newest or 0)),
        url=url,
        quote=clean_text(pain.quote, QUOTE_MAX),
        evidence_key=f"{source}|{business_id}|{now:%Y-%m}",
        business_id=business_id,
        details={
            "flags": pain.flags,
            "matching_reviews": pain.matching_reviews,
            "of_reviews": pain.of_reviews,
            "newest_flag_age_days": newest,
            "how": pain.how,
            "where": SOURCE_LABELS.get(source, source),
            **pain.details,
        },
        points=points,
    )
