"""Accelerator lists (15 Nov 2026): Y Combinator companies from yc-oss (`yc-oss.github.io/api`, MIT licence, built
from YC's public company directory), filtered to young, small, active companies with a website.

Only yc-oss is read. No other accelerator we know publishes its portfolio as an openly licensed dataset, and the
DPIIT startup list (India) has no open licence, so neither is used.

A run reads `meta.json` (the batches), picks the newest `startup_lists.batches` (3) batches that have companies,
and reads each batch's list: four requests, no AI. A company is kept when it is active, not a non-profit, has a
company website, has at most `startup.max_team` people (an unknown size passes, as everywhere), is in a country we
write to (from the list's regions, else its first location), and launched on YC's directory within the last 30
days: a launch is news for 30 days, and an older company would only add a business without a live signal.
Signal `launch`, dated when the company launched on the directory, with its YC page as the evidence and
`details` batch, team_size, team_size_source 'list' and yc_id. Companies already linked are skipped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..http import SourceBlocked
from ..normalize import clean_text, homepage
from ..segments import Segment
from . import health, startup
from .base import QUOTE_MAX, WINDOW_DAYS, Signal, SourceAdapter, SourceContext
from .rss import COUNTRY_NAMES, Pass, Sink, guarded, is_company_site, route, to_sink, unseen

NAME = "startup_lists"
BASE = "https://yc-oss.github.io/api"
META_URL = f"{BASE}/meta.json"
BATCH_URL = BASE + "/batches/{key}.json"
HOST = "yc-oss.github.io"
BATCHES_SETTING = "startup_lists.batches"
DEFAULT_BATCHES = 3
LAUNCH_DAYS = WINDOW_DAYS["launch"] or 30
SEASONS = {"winter": 1, "spring": 2, "summer": 3, "fall": 4}
_BATCH_KEY = re.compile(r"^(winter|spring|summer|fall)-(\d{4})$")


def newest_batches(meta: Mapping[str, Any], count: int) -> list[str]:
    """Keys of the `count` newest batches that have companies (`fall-2026`, ...), newest first."""
    ranked: list[tuple[int, int, str]] = []
    for key, info in (meta.get("batches") or {}).items():
        m = _BATCH_KEY.match(str(key))
        if m is None or not isinstance(info, dict) or int(info.get("count") or 0) <= 0:
            continue
        ranked.append((int(m.group(2)), SEASONS[m.group(1)], str(key)))
    return [key for _, _, key in sorted(ranked, reverse=True)[: max(0, count)]]


def country_of(company: Mapping[str, Any]) -> str | None:
    """The company's country: the one country among its regions, else the country of its first location
    ("Bengaluru, KA, India"). Region groups ("America / Canada", "Remote") are not countries."""
    regions = (COUNTRY_NAMES.get(str(r).strip().lower()) for r in company.get("regions") or [])
    codes = list(dict.fromkeys(c for c in regions if c))
    if len(codes) == 1:
        return codes[0]
    first = str(company.get("all_locations") or "").split(";")[0]
    named = COUNTRY_NAMES.get(first.rsplit(",", 1)[-1].strip().lower()) if first else None
    return named or (codes[0] if codes else None)


def launched(company: Mapping[str, Any]) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(company["launched_at"]), UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


def team_size(company: Mapping[str, Any]) -> int | None:
    value = company.get("team_size")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def quote_of(company: Mapping[str, Any]) -> str | None:
    """The company's one-liner as written in the list, else the first sentence of its description."""
    line = clean_text(str(company.get("one_liner") or ""), QUOTE_MAX)
    if len(line) >= 5:
        return line
    first = re.split(r"(?<=[.!?])\s", clean_text(str(company.get("long_description") or "")), maxsplit=1)[0]
    first = clean_text(first, QUOTE_MAX)
    return first if len(first) >= 5 else None


class StartupListsAdapter(SourceAdapter):
    name = NAME
    policy = "open_data"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.failure: str | None = None

    async def _json(self, url: str) -> Any:
        """One JSON file of the dataset, or None. A block pauses the source."""
        res = await self.http.get(url, raise_on_block=False, retries=1)
        if res.state == "blocked":
            raise SourceBlocked(NAME, HOST, res.reason, res.status)
        if res.status != 200:
            self.ctx.add(f"{NAME}.http_{res.status or res.state}")
            return None
        try:
            return res.json()
        except ValueError:
            self.ctx.add(f"{NAME}.bad_json")
            return None

    async def companies(self) -> list[dict[str, Any]]:
        """Companies of the newest batches (each batch file read once)."""
        meta = await self._json(META_URL)
        if not isinstance(meta, dict):
            self.failure = "yc-oss meta.json could not be read"
            return []
        out: list[dict[str, Any]] = []
        for key in newest_batches(meta, health.setting_int(BATCHES_SETTING, DEFAULT_BATCHES)):
            data = await self._json(BATCH_URL.format(key=key))
            if isinstance(data, list):
                out += [c for c in data if isinstance(c, dict)]
                self.ctx.add(f"{NAME}.batches_read")
        self.ctx.add(f"{NAME}.companies", len(out))
        return out

    def signal_for(
        self,
        company: Mapping[str, Any],
        segments: Mapping[str, Segment],
        *,
        max_team: int,
        now: datetime | None = None,
    ) -> tuple[Signal | None, str]:
        """(signal or None, why) for one company of the list."""
        now = now or datetime.now(UTC)
        if str(company.get("status") or "") != "Active":
            return None, "not_active"
        if company.get("nonprofit") is True:
            return None, "nonprofit"
        website = str(company.get("website") or "")
        if not is_company_site(website):
            return None, "no_website"
        team = team_size(company)
        gate = startup.startup_gate(team_size=team, max_team=max_team)
        if not gate.ok:
            return None, gate.reason
        when = launched(company)
        if when is None or when > now + timedelta(days=1):
            return None, "no_date"
        if when + timedelta(days=LAUNCH_DAYS) <= now:
            return None, "too_old"
        seg, why = route(country_of(company), segments)
        if seg is None:
            return None, why
        name = clean_text(str(company.get("name") or ""), 120)
        slug = str(company.get("slug") or "")
        yc_id = company.get("id")
        if not name or not isinstance(yc_id, int) or not re.fullmatch(r"[a-z0-9-]+", slug):
            return None, "bad_record"
        details: dict[str, Any] = {"dataset": "yc-oss", "yc_id": yc_id, "country_from": "list"}
        if company.get("batch"):
            details["batch"] = clean_text(str(company["batch"]), 40)
        if team is not None:
            details["team_size"] = team
            details["team_size_source"] = "list"
        return (
            Signal(
                type="launch",
                source=NAME,
                observed_at=min(when, now),
                url=f"https://www.ycombinator.com/companies/{slug}",
                quote=quote_of(company),
                evidence_key=f"yc:{yc_id}",
                business_hint={"name": name, "website": homepage(website)},
                details=details,
                segment_id=seg.id,
            ),
            "signal",
        )

    async def collect(self, segments: Mapping[str, Segment], run: Pass) -> list[Signal]:
        """Launch signals for the newest batches' small, active companies, routed to the startup segments."""
        if not any(s.domain == "firms" for s in segments.values()):
            self.ctx.add(f"{NAME}.no_startup_segments")
            return []
        companies = await self.companies()
        max_team, _ = startup.limits()
        fresh = unseen(NAME, [f"yc:{c.get('id')}" for c in companies])
        out: list[Signal] = []
        for company in companies:
            if f"yc:{company.get('id')}" not in fresh:
                self.ctx.add(f"{NAME}.seen_before")
                continue
            sig, why = self.signal_for(company, segments, max_team=max_team)
            self.ctx.add(f"{NAME}.{why}")
            if sig is not None:
                out.append(sig)
            if run.cap and len(out) >= run.cap:
                break
        return out


async def collect(
    ctx: SourceContext,
    segments: Mapping[str, Segment],
    sink: Sink,
    run: Pass,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """One pass of the source into the sink, behind its kill switch."""
    async with StartupListsAdapter(ctx, transport=transport) as adapter:
        to_sink(await guarded(adapter, lambda: adapter.collect(segments, run)), segments, sink)


async def watch(
    ctx: SourceContext,
    segments: dict[str, Segment],
    sink: Sink,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """The nightly pass: companies that launched on YC's directory in the last 30 days and are new to us."""
    await collect(ctx, segments, sink, Pass(days=LAUNCH_DAYS, cap=ctx.limit or 0), transport=transport)


async def backlog(
    ctx: SourceContext,
    segments: dict[str, Segment],
    sink: Sink,
    run: Pass,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """The backlog pass: the same read (a launch is news for 30 days, whatever the backlog's window)."""
    await collect(ctx, segments, sink, run, transport=transport)
