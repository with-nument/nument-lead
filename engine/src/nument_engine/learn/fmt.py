"""Number and table formatting shared by the weekly report, the audit, the eval and the health summary.

Plain words, no dashes: ranges are written "3 to 9%", missing values "n/a".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
NA = "n/a"


def group_indian(n: int) -> str:
    """12345678 -> '1,23,45,678' (lakh and crore grouping)."""
    sign, digits = ("-" if n < 0 else ""), str(abs(n))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join([*parts, tail])


def inr(value: float | None, decimals: int = 0) -> str:
    """'₹1,23,457', or '₹12.40' with decimals=2."""
    if value is None:
        return NA
    if decimals:
        whole = int(abs(value))
        frac = f"{abs(value) - whole:.{decimals}f}"[1:]
        return ("-" if value < 0 else "") + "₹" + group_indian(whole) + frac
    return "₹" + group_indian(round(value))


def money(value: float | None, currency: str = "INR") -> str:
    """'₹1,23,457' in rupees, 'USD 1,500' in any other currency (no conversion)."""
    if value is None:
        return NA
    return inr(value) if currency == "INR" else f"{currency} {value:,.0f}"


def amounts(by_currency: Mapping[str, float]) -> str:
    """{'USD': 1500, 'INR': 40000} -> '₹40,000 + USD 1,500' (rupees first, then by code)."""
    order = sorted(by_currency, key=lambda c: (c != "INR", c))
    return " + ".join(money(by_currency[c], c) for c in order) or NA


def pct(value: float | None, decimals: int | None = None) -> str:
    """0.1123 -> '11%', 0.031 -> '3.1%' (one decimal under 10% unless decimals is given)."""
    if value is None:
        return NA
    places = decimals if decimals is not None else (1 if abs(value) < 0.10 and value != 0 else 0)
    return f"{value * 100:.{places}f}%"


def pct_range(ci: Sequence[float] | None) -> str:
    """(0.031, 0.094) -> '3.1 to 9.4%'."""
    if not ci:
        return NA
    low, high = ci[0] * 100, ci[1] * 100
    return f"{low:.1f} to {high:.1f}%"


def num(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return NA
    return f"{value:,.{decimals}f}"


def day(value: date | datetime | str | None) -> str:
    """'9 Nov 2026' (IST for timestamps)."""
    if value is None:
        return NA
    if isinstance(value, str):
        value = datetime.fromisoformat(value) if "T" in value or " " in value else date.fromisoformat(value)
    if isinstance(value, datetime):
        value = value.astimezone(IST) if value.tzinfo else value
        return f"{value.day} {value:%b %Y}"
    return f"{value.day} {value:%b %Y}"


def when(value: datetime | None) -> str:
    """'9 Nov 2026, 02:14 IST'."""
    if value is None:
        return NA
    local = value.astimezone(IST)
    return f"{local.day} {local:%b %Y}, {local:%H:%M} IST"


def period(start: date, end: date) -> str:
    """'9 to 15 Nov 2026', '28 Nov to 4 Dec 2026'."""
    if start.year == end.year and start.month == end.month:
        return f"{start.day} to {end.day} {end:%b %Y}"
    if start.year == end.year:
        return f"{start.day} {start:%b} to {end.day} {end:%b %Y}"
    return f"{day(start)} to {day(end)}"


def cell(value: Any) -> str:
    """One markdown table cell: pipes escaped, new lines flattened."""
    text = NA if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip() or NA


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """A GitHub-flavoured markdown table."""
    lines = ["| " + " | ".join(cell(h) for h in headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)
