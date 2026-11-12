"""Formatting shared by the reports: Indian digit grouping, percentages, ranges, periods, tables."""

from __future__ import annotations

from datetime import date

import pytest

from nument_engine.learn import fmt
from nument_engine.learn.store import store_report


def test_formatting_helpers() -> None:
    assert fmt.inr(12345678) == "₹1,23,45,678" and fmt.inr(950) == "₹950" and fmt.inr(12.4, 2) == "₹12.40"
    assert fmt.inr(None) == "n/a"
    assert fmt.pct(0.1123) == "11%" and fmt.pct(0.031) == "3.1%" and fmt.pct(0) == "0%" and fmt.pct(None) == "n/a"
    assert fmt.pct_range((0.031, 0.094)) == "3.1 to 9.4%"
    assert fmt.period(date(2026, 12, 7), date(2026, 12, 13)) == "7 to 13 Dec 2026"
    assert fmt.period(date(2026, 11, 30), date(2026, 12, 6)) == "30 Nov to 6 Dec 2026"
    assert fmt.table(["A", "B"], [["x|y", None]]) == "| A | B |\n|---|---|\n| x\\|y | n/a |"


def test_store_report_rejects_unknown_kinds() -> None:
    with pytest.raises(ValueError, match="unknown report kind"):
        store_report("daily", None, None, {}, "")
