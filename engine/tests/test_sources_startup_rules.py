"""The rules every startup source shares: the size gate, round words, the segment and founder names."""

from __future__ import annotations

from typing import Any

import pytest

from nument_engine.sources import startup


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pre-Seed", "pre_seed"),
        ("pre seed round", "pre_seed"),
        ("Seed", "seed"),
        ("Series A", "series_a"),
        ("series b extension", "series_b"),
        ("Reg CF crowdfunding", "crowdfunding"),
        ("angel round", "angel"),
        ("Y Combinator W26", "accelerator"),
        ("growth equity", "growth"),
        ("", "unknown"),
        (None, "unknown"),
        ("undisclosed", "unknown"),
    ],
)
def test_normalize_round(text: str | None, expected: str) -> None:
    assert startup.normalize_round(text) == expected


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({}, "ok"),  # everything unknown passes: qualification decides
        ({"team_size": 6, "funding_round": "seed", "amount_usd": 1_500_000}, "ok"),
        ({"team_size": 10}, "ok"),
        ({"team_size": 11}, "too_big"),
        ({"funding_round": "Series A"}, "late_round"),
        ({"amount_usd": 2_500_000}, "raise_too_big"),
        ({"is_startup": False}, "not_startup"),
    ],
)
def test_startup_gate(kwargs: dict[str, Any], reason: str) -> None:
    gate = startup.startup_gate(**kwargs)
    assert gate.reason == reason and gate.ok is (reason == "ok")


def test_startup_segment_follows_outreach_countries() -> None:
    segments: dict[str, Any] = {"firms-us": "US", "firms-de": "DE", "firms-in": "IN"}
    assert startup.startup_segment("US", segments) == "US"
    assert startup.startup_segment("in", segments) == "IN"
    assert startup.startup_segment("de", segments) is None  # cold email needs prior consent there
    assert startup.startup_segment("gb", segments) is None  # allowed, but the segment is off
    assert startup.startup_segment("zz", segments) is None
    assert startup.startup_segment(None, segments) is None


def test_founders_detail_cleans_and_caps() -> None:
    founders = [
        {"name": "Jane Doe", "role": "CEO & Co-founder"},
        {"name": "jane doe"},  # duplicate
        {"name": "info@acme.com"},  # not a name
        {"name": "A"},  # too short
        {"name": "Ravi Kumar", "source_url": "https://news.example.com/a"},
        *({"name": f"Person {chr(65 + i)}x"} for i in range(6)),
    ]
    out = startup.founders_detail(founders, source_url="https://feed.example.com/item")
    assert out[0] == {"name": "Jane Doe", "role": "CEO & Co-founder", "source_url": "https://feed.example.com/item"}
    assert out[1] == {"name": "Ravi Kumar", "role": "Founder", "source_url": "https://news.example.com/a"}
    assert len(out) == 5 and all("@" not in f["name"] for f in out)
