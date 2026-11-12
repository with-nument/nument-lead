"""Kill switches, block backoff, request counting and quota counting (Steps 5.3, 18.1.5, 18.1.7, 19.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nument_engine import db
from nument_engine.http import SourceBlocked
from nument_engine.sources import health
from nument_engine.sources.apna import ApnaAdapter

from .sources_helpers import clean_db, ctx, mock_transport, no_network

__all__ = ["clean_db", "no_network"]


def _row(source: str) -> dict[str, object]:
    row = db.fetch_one("select * from public.source_health where source = %s", [source])
    assert row is not None
    return row


def test_settings_switch_turns_a_source_off(clean_db: str) -> None:
    assert health.source_status("apna") == (True, "")
    flags = db.get_setting("sources_enabled")
    db.set_setting("sources_enabled", {**flags, "apna": False})
    usable, why = health.source_status("apna")
    assert not usable and "settings.sources_enabled" in why
    assert health.source_status("adzuna")[0] is False  # off by default (no keys yet)
    assert health.source_status("practo")[0] is True  # founder approved (migration 0010)


def test_disabled_and_paused_sources(clean_db: str) -> None:
    db.execute("update public.source_health set enabled = false where source = 'gdelt'")
    assert health.source_status("gdelt")[0] is False
    db.execute("update public.source_health set blocked_until = now() + interval '1 hour' where source = 'osm'")
    usable, why = health.source_status("osm")
    assert not usable and why.startswith("blocked until")
    db.execute("update public.source_health set blocked_until = now() - interval '1 hour' where source = 'osm'")
    assert health.source_status("osm")[0] is True


def test_block_backoff_ladder_24h_72h_7d(clean_db: str) -> None:
    now = datetime.now(UTC)
    ends = [health.record_block("art_registry", f"block {i}", grey=False) for i in range(4)]
    assert ends[0] - now == pytest.approx(timedelta(hours=24), abs=timedelta(minutes=1))
    assert ends[1] - now == pytest.approx(timedelta(hours=72), abs=timedelta(minutes=1))
    assert ends[2] - now == pytest.approx(timedelta(days=7), abs=timedelta(minutes=1))
    assert ends[3] - now == pytest.approx(timedelta(days=7), abs=timedelta(minutes=1))
    row = _row("art_registry")
    assert row["enabled"] is True and len(row["recent_blocks"]) == 4  # type: ignore[arg-type]


def test_a_grey_source_blocked_twice_in_a_week_is_switched_off(clean_db: str) -> None:
    health.record_block("apna", "403", grey=True)
    assert _row("apna")["enabled"] is True
    health.record_block("apna", "captcha", grey=True)
    assert _row("apna")["enabled"] is False
    assert "disabled in source_health" in health.source_status("apna")[1]


def test_quota_errors_pause_until_midnight(clean_db: str) -> None:
    until = health.next_ist_midnight()
    end = health.record_block("places", "RESOURCE_EXHAUSTED", grey=False, until=until)
    assert end == until and _row("places")["blocked_until"] == until


def test_request_counts_add_up_within_a_day_and_reset_on_a_new_day(clean_db: str) -> None:
    db.execute(
        "update public.source_health set requests_today = 7, requests_day = current_date - 3 where source = 'gdelt'"
    )
    health.mark_ok("gdelt", requests=5)
    health.add_requests("gdelt", 2)
    row = _row("gdelt")
    assert row["requests_today"] == 7 and row["last_ok_at"] is not None


async def test_kill_switch_means_no_requests(clean_db: str) -> None:
    """Step 5.16 test 5: sources_enabled.apna = false makes the adapter do nothing at all."""
    flags = db.get_setting("sources_enabled")
    db.set_setting("sources_enabled", {**flags, "apna": False})
    transport, seen = mock_transport({"*": (200, "x")})
    async with ApnaAdapter(ctx(), transport=transport) as apna:
        assert not apna.enabled()
        assert await apna.safe_call(apna.job_sitemaps) is None
    assert seen == []


async def test_a_block_inside_an_adapter_pauses_the_source(clean_db: str) -> None:
    transport, _ = mock_transport({"https://apna.co/robots.txt": (200, "User-agent: *\nAllow: /\n"), "*": (403, "no")})
    context = ctx()
    async with ApnaAdapter(context, transport=transport) as apna:
        assert await apna.safe_call(apna.job_sitemaps) is None
    row = _row("apna")
    assert row["blocked_until"] is not None and "403" in str(row["last_error"])
    assert context.alerts and "apna blocked" in context.alerts[0]
    assert isinstance(SourceBlocked("apna", "apna.co", "x"), Exception)
