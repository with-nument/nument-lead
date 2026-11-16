"""Helpers for the startup feed tests (lane E1a): fixtures with fresh dates, a default classifier answer, and a
fixture that removes request gaps and retry waits so tests never sleep."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from nument_engine import http
from nument_engine.models import StartupItemClassification
from nument_engine.sources.gdelt import GdeltAdapter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e1a"
RSS_TYPE = "application/rss+xml; charset=UTF-8"
ATOM_TYPE = "application/atom+xml; charset=utf-8"


def fixture(name: str) -> str:
    return FIXTURES.joinpath(name).read_text(encoding="utf-8")


def ago(hours: float = 0, days: float = 0) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours, days=days)


def fresh_dates(xml: str, *hours_ago: float) -> str:
    """The feed with its item dates replaced, in order, by dates `hours_ago` before now (RSS pubDate, Atom
    published and updated). Items past the list keep their dates."""
    stamps = list(hours_ago)

    def rss(m: re.Match[str]) -> str:
        return f"<pubDate>{format_datetime(ago(stamps.pop(0)))}</pubDate>" if stamps else m.group(0)

    if "<pubDate>" in xml:
        return re.sub(r"<pubDate>[^<]*</pubDate>", rss, xml)
    out: list[str] = []
    for i, entry in enumerate(re.split(r"(?=<entry>)", xml)):
        if i and i - 1 < len(stamps):
            when = ago(stamps[i - 1]).strftime("%Y-%m-%dT%H:%M:%SZ")
            entry = re.sub(r"<published>[^<]*</published>", f"<published>{when}</published>", entry)
            entry = re.sub(r"<updated>[^<]*</updated>", f"<updated>{when}</updated>", entry)
        out.append(entry)
    return "".join(out)


def feed(xml: str, content_type: str = RSS_TYPE, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=xml.encode("utf-8"), headers={"content-type": content_type})


def html(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})


def answer(**changes: Any) -> StartupItemClassification:
    """A classifier answer for a small US startup's pre-seed round; `changes` override fields."""
    base: dict[str, Any] = {
        "is_relevant": True,
        "event": "funding",
        "company_name": "Brightcart",
        "company_website": "brightcart.io",
        "hq_country": "us",
        "city": "Austin",
        "is_startup": True,
        "team_size": 3,
        "round": "pre_seed",
        "amount_usd": 600000.0,
        "founders": ["Maya Chen", "Leo Park"],
        "investors": ["Northlight Ventures"],
        "evidence_quote": "raised $600K in a pre-seed round",
        "confidence": 0.9,
    }
    return StartupItemClassification(**{**base, **changes})


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No request gaps and no retry waits (the polite gaps are tested in test_http.py)."""
    for policy in list(http.POLICY_GAP_S):
        monkeypatch.setitem(http.POLICY_GAP_S, policy, 0.0)
    monkeypatch.setattr(GdeltAdapter, "min_gap_s", 0.0)

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_wait)
    http.reset_caches()
    yield
    http.reset_caches()
