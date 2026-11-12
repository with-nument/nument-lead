"""Code checks for messages, no AI (Steps 12.5 to 12.7).

- `lint`: the voice rules ported from the old engine's `wa_to_edits.py` and extended (A.2.3, voice v2 of
  `whatsapp_playbook.md`): length, greeting, Nument named once, exactly one question, no links, dashes,
  emojis, prices or banned phrases.
- `claim_problems`: every cited id must be this business's evidence, and every number and capitalised name
  in the message must appear in what it cites (catches invented numbers and names).
- `opener`, `closing_question`, `similarity`: the daily variety checks.
The web app runs the same lint in the browser and warns, but never blocks a founder's edit (12.13).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from rapidfuzz import fuzz

from .evidence import resolve_cited_id

EMOJI: Final = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F1E6-\U0001F1FF]")
PRICE: Final = re.compile(
    r"₹|\brs\.?\s*\d|\binr\b|\baed\b|\$\s*\d|\blakh\b|\bcrore\b|\bper month\b|/month|\bk\b\s*(?:per|/)", re.I
)
LINK: Final = re.compile(r"https?://|www\.|\.com\b|\.in\b|\.ae\b|\.io\b", re.I)
DASH: Final = re.compile(r"[\u2013\u2014]| - ")
BANNED: Final = (
    "businesses like yours",
    "ai-powered",
    "ai powered",
    "hope you are",
    "hope you're",
    "hope this finds",
    "reaching out",
    "synergy",
    "leverage",
    "cutting-edge",
    "cutting edge",
    "game-changer",
    "game changer",
    "revolutioni",
    "quick 10-minute call",
    "just following up",
    "just bumping",
    "greetings",
    "dear sir",
    "dear madam",
    "respected",
    "kindly",
    "revert",
    "we are a leading",
    "state-of-the-art",
    "world-class",
    "one-stop",
    "guaranteed results",
)
WORDS: Final[dict[str, tuple[int, int]]] = {
    "message": (30, 60),
    "message_alt": (30, 60),
    "followup_d3": (15, 45),
    "followup_d7": (10, 30),
    "email_subject": (3, 8),
    "email_body": (50, 110),
}
FIRST_MESSAGES: Final = ("message", "message_alt")


def word_count(text: str) -> int:
    return len(text.split())


def lint(text: str, kind: str = "message") -> list[str]:
    """Voice problems in one text; an empty list means it passes (12.5)."""
    text = text or ""
    lo, hi = WORDS[kind]
    problems: list[str] = []
    words = word_count(text)
    if not lo <= words <= hi:
        problems.append(f"{words} words (want {lo} to {hi})")
    if kind in FIRST_MESSAGES:
        if not text.startswith(("Hi ", "Hi,")):
            problems.append("must start with 'Hi'")
        named = text.count("Nument")
        if named == 0:
            problems.append("does not name Nument")
        elif named > 1:
            problems.append("names Nument more than once")
    if kind == "email_body" and "Nument" not in text:
        problems.append("does not name Nument")
    questions = text.count("?")
    if kind in ("message", "message_alt", "followup_d3", "followup_d7") and questions != 1:
        problems.append(f"{questions} question marks (want exactly 1)")
    if kind == "email_subject" and questions:
        problems.append("subject asks a question")
    if LINK.search(text):
        problems.append("contains a link")
    if DASH.search(text):
        problems.append("contains a dash")
    if EMOJI.search(text):
        problems.append("contains an emoji")
    if PRICE.search(text):
        problems.append("mentions a price")
    low = text.lower()
    problems += [f"banned phrase '{b}'" for b in BANNED if b in low]
    return problems


# ---------------------------------------------------------------------------
# 12.6 Claim check
# ---------------------------------------------------------------------------

NUMBER_WORDS: Final[dict[str, str]] = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "fifteen": "15",
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "hundred": "100",
}
_NUM: Final = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NUM_WORD: Final = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)
# Numbers about how our product works ("in 5 seconds", "at 11 pm", "24/7") are not claims about them.
_PRODUCT_NUMBER: Final = re.compile(
    r"\b\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|pm|am)\b|\b24/7\b|\b24x7\b", re.I
)
_CAP_SEQ: Final = re.compile(r"[A-Z][\w'\u2019\u00a7]*(?:[ \t]+[A-Z][\w'\u2019\u00a7]*)*")
_TITLE_DOT: Final = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof|St)\.")
_SENTENCES: Final = re.compile(r"(?<=[.!?])\s+|\n+")
WEEKDAYS: Final = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS: Final = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
ALWAYS_OK: Final = frozenset(
    {
        "hi",
        "hey",
        "hello",
        "nument",
        "i",
        "i'm",
        "i'd",
        "i'll",
        "i've",
        "ai",
        "whatsapp",
        "google",
        "crm",
        "dr",
        "dr.",
        "mr",
        "mr.",
        "ms",
        "ms.",
        "mrs",
        "mrs.",
        "ok",
        "okay",
        *WEEKDAYS,
        *MONTHS,
    }
)


def _numbers(text: str) -> list[str]:
    """Numbers in a message, digits normalised ('1,500' -> '1500'), number words mapped to digits."""
    clean = _PRODUCT_NUMBER.sub(" ", text)
    found = [m.group(0).replace(",", "").rstrip(".") for m in _NUM.finditer(clean)]
    found += [NUMBER_WORDS[m.group(1).lower()] for m in _NUM_WORD.finditer(clean)]
    return found


def _evidence_numbers(text: str) -> set[str]:
    out = {m.group(0).replace(",", "").rstrip(".") for m in _NUM.finditer(text)}
    out |= {NUMBER_WORDS[m.group(1).lower()] for m in _NUM_WORD.finditer(text)}
    return out


def _tokens(text: str) -> set[str]:
    """Lowercase words of a text, each also without a possessive 's."""
    out: set[str] = set()
    for t in re.findall(r"[\w'\u2019.]+", text):
        word = t.strip(".'\u2019").lower()
        out |= {word, _bare(word)}
    return out


def _bare(word: str) -> str:
    return word.removesuffix("'s").removesuffix("\u2019s")


def capitalised_names(text: str) -> list[str]:
    """Capitalised word sequences inside each sentence. A sentence's first word is capitalised anyway, so it
    is dropped ('Worth a look?' has no name, "We're Nument" leaves 'Nument'); 'Dr.' does not end a sentence."""
    protected = _TITLE_DOT.sub(lambda m: m.group(1) + "\u00a7", text or "")
    out: list[str] = []
    for sentence in _SENTENCES.split(protected):
        sentence = sentence.strip()
        for m in _CAP_SEQ.finditer(sentence):
            words = m.group(0).split()
            if m.start() == 0:
                words = words[1:]
            if words:
                out.append(" ".join(w.replace("\u00a7", ".") for w in words))
    return out


@dataclass
class ClaimContext:
    """What a message may mention without a citation, and what its cited evidence says."""

    known_ids: Mapping[str, str]  # lowercase id -> canonical id, verified facts and active signals only
    evidence_text: Mapping[str, str]  # canonical id -> value, quote and details as one text
    trusted_words: set[str] = field(default_factory=set)  # greeting name, business name, cities, our copy
    trusted_numbers: set[str] = field(default_factory=set)  # numbers in our own angle copy


def claim_problems(
    texts: Iterable[str], claim_ids: Iterable[Iterable[str]], ctx: ClaimContext, *, need_claim: bool = True
) -> list[str]:
    """12.6: unknown ids, and numbers or names that none of the cited evidence contains."""
    problems: list[str] = []
    cited: set[str] = set()
    any_claim = False
    for ids in claim_ids:
        any_claim = True
        for raw in ids:
            known = resolve_cited_id(raw, ctx.known_ids)
            if known is None:
                problems.append(f"cites unknown id '{raw}'")
            else:
                cited.add(known)
    if need_claim and not any_claim:
        problems.append("no claim cites a verified fact or signal")
    evidence = " ".join(ctx.evidence_text.get(i, "") for i in cited)
    ev_numbers = _evidence_numbers(evidence) | ctx.trusted_numbers
    ev_words = _tokens(evidence) | {_bare(w.lower()) for w in ctx.trusted_words} | ALWAYS_OK
    for text in texts:
        for n in _numbers(text):
            if n not in ev_numbers:
                problems.append(f"number '{n}' is not in the cited facts")
        for name in capitalised_names(text):
            missing = [
                w
                for w in name.split()
                if _bare(w.strip(".,'\u2019").lower()) not in ev_words and w.strip(".,'\u2019").lower() not in ev_words
            ]
            if missing:
                problems.append(f"name '{name}' is not in the cited facts")
    return list(dict.fromkeys(problems))


# ---------------------------------------------------------------------------
# 12.7 Daily variety
# ---------------------------------------------------------------------------

_GREETING: Final = re.compile(r"^\s*hi\b[^,]{0,40},\s*", re.I)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s?]", " ", (text or "").lower())).strip()


def opener(text: str) -> str:
    """The first four words after the greeting ('Hi Dr. Rao,' would make every opener unique)."""
    body = _GREETING.sub("", text or "")
    return " ".join(normalise(body).replace("?", "").split()[:4])


def closing_question(text: str) -> str:
    """The sentence that holds the question mark, normalised."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    asked = [p for p in parts if "?" in p]
    return normalise(asked[-1]) if asked else ""


def similarity(a: str, b: str) -> float:
    return float(fuzz.token_set_ratio(normalise(a), normalise(b)))
