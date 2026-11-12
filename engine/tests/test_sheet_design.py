"""The sheet design: stage map, parsers, links, and the next-step twin of the live formulas (Step 13.11)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest

from nument_engine import models
from nument_engine.sheet import design as d

TODAY = dt.date(2026, 11, 12)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def test_stage_map_matches_the_contract() -> None:
    assert tuple(d.STAGES) == models.STAGES
    assert {k: v[0] for k, v in d.STAGES.items()} == models.STAGE_LABELS
    assert d.CLOSED == models.CLOSED_STAGES
    assert set(d.FUNNEL) == set(models.STAGES)


@pytest.mark.parametrize("value", list(d.STAGES))
def test_canon_stage_maps_every_label_and_value_both_ways(value: str) -> None:
    label = d.stage_label(value)
    assert d.canon_stage(label) == (value, label)
    assert d.canon_stage(label.upper())[0] == value
    assert d.canon_stage(f"  {label.lower()} ")[0] == value
    assert d.canon_stage(value)[0] == value


@pytest.mark.parametrize("text", ["Maybe later", "Intrested", "123", "?", "N/A"])
def test_unknown_stage_text_is_kept_and_never_raises(text: str) -> None:
    assert d.canon_stage(text) == (None, text)
    assert d.stage_style("maybe_later") == d.UNKNOWN_STAGE_STYLE
    assert d.stage_label("maybe_later") == "maybe_later"


def test_blank_stage_means_new() -> None:
    assert d.canon_stage("")[0] == "new"
    assert d.canon_stage(None)[0] == "new"


def test_old_wrong_contact_capitals_are_read() -> None:
    """The 12 Nov 2026 history says 'Wrong Contact' (capital C)."""
    assert d.canon_stage("Wrong Contact")[0] == "wrong_contact"


# ---------------------------------------------------------------------------
# Parsers (13.7.2, 13.7.6)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("₹1.2L", "120000"),
        ("1.2 lakh", "120000"),
        ("₹2 Cr", "20000000"),
        ("45K", "45000"),
        ("1,50,000", "150000"),
        (150000, "150000"),
        (150000.0, "150000"),
        (1500.5, "1500.5"),
        ("₹3L to 8L", ""),
        ("≈ ₹5L", ""),
        ("", ""),
        (None, ""),
        ("abc", None),
        ("call me", None),
    ],
)
def test_money_parse(cell: Any, expected: str | None) -> None:
    assert d.parse_money_cell(cell) == expected


def test_estimates_never_parse_as_edits() -> None:
    for low, high in ((300000, 800000), (500000, 500000), (None, 200000)):
        assert d.parse_money_cell(d.estimate_text(low, high)) == ""
    assert d.estimate_text(300000, 800000) == "₹3L to 8L"
    assert d.estimate_text(None, 500000) == "≈ ₹5L"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (46338, "2026-11-12"),
        (46338.625, "2026-11-12"),  # "12 Nov 3pm": the time is dropped
        ("2026-11-12", "2026-11-12"),
        ("12/11/2026", "2026-11-12"),  # day first, the Indian way
        ("12 Nov 2026", "2026-11-12"),
        ("", ""),
        (None, ""),
        ("tomorrow", None),
        (True, None),
        (-3, None),
    ],
)
def test_date_parse(cell: Any, expected: str | None) -> None:
    assert d.parse_date_cell(cell) == expected


def test_serial_round_trip() -> None:
    assert d.serial(TODAY) == 46338
    assert d.from_serial(46338) == TODAY
    noon_ist = dt.datetime(2026, 11, 12, 6, 30, tzinfo=dt.UTC)  # 12:00 IST
    assert d.serial(noon_ist) == 46338
    late_utc = dt.datetime(2026, 11, 11, 20, 0, tzinfo=dt.UTC)  # 01:30 IST on the 12th
    assert d.as_date(late_utc) == TODAY


@pytest.mark.parametrize(("value", "text"), [(None, ""), (150000, "150000"), (150000.0, "150000"), (1500.50, "1500.5")])
def test_money_str(value: Any, text: str) -> None:
    from decimal import Decimal

    assert d.money_str(value) == text
    if value is not None:
        assert d.money_str(Decimal(str(value))) == text


# ---------------------------------------------------------------------------
# Links and text
# ---------------------------------------------------------------------------
def test_whatsapp_web_link_only_for_mobiles() -> None:
    link = d.wa_web_link("+919800000123", "mobile", "Hi Dr. Rao, saw your post?\n\nWe're Nument")
    assert link.startswith("https://web.whatsapp.com/send?phone=919800000123&text=Hi%20Dr.%20Rao")
    assert "%0A%0A" in link and "?" not in link.split("text=")[1]
    assert d.wa_web_link("+911145678901", "landline", "Hi") == ""
    assert d.wa_web_link(None, "mobile", "Hi") == ""


def test_phone_display() -> None:
    assert d.phone_display("+919800000123") == "+91 98000 00123"
    assert d.phone_display("+971501234567") == "+971 50 123 4567"
    assert d.phone_display(None) == ""


def test_names() -> None:
    assert d.clean_org("Hometrust Realty Private Limited (HomeTrust)") == "Hometrust Realty"
    assert d.short_name("Dr Joshi Holistic Multispecialty Research & Healthcare") == "Dr Joshi Holistic"
    assert d.person_short("Dr. Asha Kiranmayee Rao") == "Dr. Asha Rao"
    assert d.person_role("Adwait Dash", "Founder (per LinkedIn snippet); co-director") == "Adwait Dash, Founder"
    assert d.inr(120000) == "₹1.2L" and d.inr(45000) == "₹45K" and d.inr(25_000_000) == "₹2.5 Cr"


def test_text_height_grows_with_text() -> None:
    short, long = d.text_height("Hi", 420), d.text_height("word " * 200, 420)
    assert short < 40 < long


def test_sheet_copy_has_no_dashes() -> None:
    texts = [*d.NOTES.values(), *(v[0] for v in d.STAGES.values()), *d.FOUNDER_STEPS, d.EMPTY_TODO]
    dashes = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")  # en and em dash
    assert not [t for t in texts if dashes.search(t)]


# ---------------------------------------------------------------------------
# The next-step twin equals the live formulas (13.5.4, test_next_step_twin)
# ---------------------------------------------------------------------------
class _Blank:
    """An empty cell: equal to "" and worth 0 in arithmetic, like Google Sheets."""

    def __eq__(self, other: object) -> bool:
        return other == "" or other == 0 or isinstance(other, _Blank)

    def __hash__(self) -> int:
        return 0

    def __add__(self, other: Any) -> Any:
        return other

    __radd__ = __add__

    def __lt__(self, other: Any) -> bool:
        return other > 0

    def __le__(self, other: Any) -> bool:
        return other >= 0

    def __gt__(self, other: Any) -> bool:
        return other < 0


BLANK = _Blank()
LETTERS = {
    "stage": "F",
    "wa": "G",
    "call": "H",
    "d3": "I",
    "d7": "J",
    "meeting": "K",
    "next": "L",
    "dd": "Q",
    "queue": "R",
}


def _evaluate(formula: str, cells: dict[str, Any], today: int) -> Any:
    """Evaluate one of our IFS formulas in Python (a small subset of the Sheets language)."""
    parts = formula[1:].split('"')
    for i in range(0, len(parts), 2):  # code outside string literals
        code = re.sub(r"\$([A-Z]{1,2})\d+", lambda m: f'C("{m.group(1)}")', parts[i])
        code = code.replace("<>", "!=").replace("TODAY()", "TODAY").replace("TRUE", "True")
        parts[i] = re.sub(r"(?<![<>!=])=(?!=)", "==", code)
    expr = '"'.join(parts)

    def ifs(*args: Any) -> Any:
        for cond, value in zip(args[::2], args[1::2], strict=True):
            if cond:
                return value
        raise ValueError("no IFS branch matched")

    def num(x: Any) -> float:
        return 0 if isinstance(x, _Blank) or x == "" else x

    env = {
        "C": lambda c: cells.get(c, BLANK),
        "IFS": ifs,
        "IF": lambda c, a, b: a if c else b,
        "OR": lambda *a: any(a),
        "AND": lambda *a: all(a),
        "MAX": lambda *a: max(num(x) for x in a),
        "ISNUMBER": lambda x: isinstance(x, int | float) and not isinstance(x, bool),
        "TODAY": today,
    }
    return eval(expr, {"__builtins__": {}}, env)


def _case(stage: str, wa: int | None = None, call: int | None = None, d3: int | None = None, d7: int | None = None,
          meeting: int | None = None, queue: int | None = None) -> tuple[str, dict[str, Any]]:  # fmt: skip
    """A row as day offsets from TODAY; returns the stage and the dates dict for the twin."""

    def day(offset: int | None) -> dt.date | None:
        return None if offset is None else TODAY + dt.timedelta(days=offset)

    return stage, {
        "wa_at": day(wa),
        "call_at": day(call),
        "d3_at": day(d3),
        "d7_at": day(d7),
        "meeting_at": day(meeting),
        "queue": queue,
    }


CASES = [
    _case("new", queue=1),
    _case("new", queue=60),
    _case("new"),
    _case("new", wa=-1),
    _case("contacted"),
    _case("contacted", wa=-2),
    _case("contacted", wa=-5, call=-4),
    _case("contacted", wa=-8, call=-7, d3=-5),
    _case("contacted", wa=-9, call=-8, d3=-6, d7=-2),
    _case("talking"),
    _case("talking", wa=-3, call=-1),
    _case("discovery_booked"),
    _case("discovery_booked", meeting=2),
    _case("discovery_done", meeting=-1),
    _case("discovery_done"),
    _case("proposal_sent", meeting=-3),
    _case("proposal_sent"),
    _case("won", wa=-30),
    _case("retainer"),
    _case("lost", wa=-10),
    _case("not_a_fit"),
    _case("not_now"),
    _case("not_now", wa=-12, d7=-5),
    _case("wrong_contact", wa=0),
]


@pytest.mark.parametrize(("stage", "dates"), CASES)
@pytest.mark.parametrize(("first_touch", "step2"), [("Send WhatsApp", "Call"), ("Send email", "Follow up")])
def test_next_step_twin(stage: str, dates: dict[str, Any], first_touch: str, step2: str) -> None:
    fx = d.pipeline_formulas(LETTERS, 3, 3, 50, first_touch, step2, "You", "Aditya")
    today = d.serial(TODAY)
    assert today is not None
    cells: dict[str, Any] = {"F": d.stage_label(stage)}
    for key, letter in (("wa_at", "G"), ("call_at", "H"), ("d3_at", "I"), ("d7_at", "J"), ("meeting_at", "K")):
        cells[letter] = d.serial(dates[key]) if dates[key] else BLANK
    cells["R"] = dates["queue"] if dates["queue"] is not None else BLANK
    sheet_next = _evaluate(fx["next"], cells, today)
    sheet_due = _evaluate(fx["dd"], cells, today)
    step, due = d.next_step_and_due(stage, dates, TODAY, dates["queue"], 50, first_touch, step2)
    assert sheet_next == step
    assert (sheet_due if sheet_due != "" else None) == (d.serial(due) if due else None)


def test_who_column_marks_founder_steps() -> None:
    fx = d.pipeline_formulas(LETTERS, 3, 3, 50, "Send WhatsApp", "Call", "Founder", "You")
    for step in d.FOUNDER_STEPS:
        assert f'"{step}"' in fx["who"]
    assert fx["who"].endswith('"Founder","You"))')
