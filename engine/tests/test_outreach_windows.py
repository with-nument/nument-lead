"""Sending windows in the recipient's local time: zones, weekdays, and daylight-saving changes (lane E5a)."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from nument_engine.outreach import windows as w

WINDOWS = w.parse_windows([["08:30", "11:30"], ["13:30", "16:30"]])
NEW_YORK = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
SYDNEY = ZoneInfo("Australia/Sydney")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("country", "city", "address", "zone"),
    [
        ("us", "San Francisco, CA", None, "America/Los_Angeles"),
        ("us", "Austin", None, "America/Chicago"),
        ("US", "  new york city ", None, "America/New_York"),
        ("us", None, None, "America/New_York"),  # the country's main zone
        ("us", "Springfield", "1 Main St, Springfield, IL 62701", "America/Chicago"),  # state from the address
        ("us", "Spokane, Washington", None, "America/Los_Angeles"),  # the state, not the city of Washington
        ("us", "Washington, DC", None, "America/New_York"),
        ("us", "Phoenix", None, "America/Phoenix"),
        ("us", "St. Louis", None, "America/Chicago"),
        ("ca", "Vancouver", None, "America/Vancouver"),
        ("ca", "Oakville, ON", None, "America/Toronto"),
        ("au", "Perth", None, "Australia/Perth"),
        ("au", "Bondi", "1 Beach Rd, Bondi NSW 2026", "Australia/Sydney"),
        ("br", "São Paulo", None, "America/Sao_Paulo"),
        ("mx", "Tijuana", None, "America/Tijuana"),
        ("in", "Pune", None, "Asia/Kolkata"),
        ("gb", "Unknown Town", None, "Europe/London"),
    ],
)
def test_zone_for_city_region_and_country(country: str, city: str | None, address: str | None, zone: str) -> None:
    assert w.zone_for(country, city, address) == ZoneInfo(zone)


@pytest.mark.parametrize("country", ["xx", "", None])
def test_no_zone_for_an_unknown_country(country: str | None) -> None:
    assert w.zone_for(country, "Somewhere") is None


def test_every_allowed_and_blocked_country_has_a_zone() -> None:
    from nument_engine.outreach.compose import country_codes
    from nument_engine.outreach.net import outreach_config

    cfg = outreach_config()
    codes = country_codes([*cfg["allowed_countries"], *cfg["blocked_countries"]])
    assert "no" in codes  # Norway, which YAML reads as false
    for code in codes:
        assert w.zone_for(code) is not None, code


def test_parse_windows_validates() -> None:
    assert w.parse_windows([["13:30", "16:30"], ["08:30", "11:30"]]) == (
        (time(8, 30), time(11, 30)),
        (time(13, 30), time(16, 30)),
    )
    with pytest.raises(ValueError, match="start before it ends"):
        w.parse_windows([["11:30", "08:30"]])
    with pytest.raises(ValueError, match="start and an end"):
        w.parse_windows([["08:30"]])
    assert w.config_windows() == WINDOWS


def test_window_edges_and_lunch_gap() -> None:
    # Tuesday 10 Mar 2026, New York on daylight time (UTC-4)
    assert w.in_window(utc(2026, 3, 10, 12, 30), NEW_YORK, WINDOWS)  # 08:30 opens
    assert not w.in_window(utc(2026, 3, 10, 12, 29), NEW_YORK, WINDOWS)
    assert not w.in_window(utc(2026, 3, 10, 15, 30), NEW_YORK, WINDOWS)  # 11:30 closes
    assert not w.in_window(utc(2026, 3, 10, 16, 0), NEW_YORK, WINDOWS)  # lunch
    assert w.next_window_start(utc(2026, 3, 10, 16, 0), NEW_YORK, WINDOWS) == utc(2026, 3, 10, 17, 30)
    assert w.in_window(utc(2026, 3, 10, 20, 29), NEW_YORK, WINDOWS)  # 16:29
    assert not w.in_window(utc(2026, 3, 10, 20, 30), NEW_YORK, WINDOWS)


def test_weekends_are_closed() -> None:
    saturday_morning = utc(2026, 3, 14, 14, 0)  # 10:00 in New York
    assert not w.in_window(saturday_morning, NEW_YORK, WINDOWS)
    assert w.next_window_start(saturday_morning, NEW_YORK, WINDOWS) == utc(2026, 3, 16, 12, 30)  # Monday 08:30


def test_the_same_utc_time_is_inside_after_spring_forward_but_not_before() -> None:
    # 12:45 UTC is 07:45 on Friday 6 Mar (EST, UTC-5) but 08:45 on Monday 9 Mar (EDT, UTC-4).
    assert not w.in_window(utc(2026, 3, 6, 12, 45), NEW_YORK, WINDOWS)
    assert w.in_window(utc(2026, 3, 6, 13, 45), NEW_YORK, WINDOWS)
    assert w.in_window(utc(2026, 3, 9, 12, 45), NEW_YORK, WINDOWS)


def test_next_window_across_the_us_daylight_saving_weekends() -> None:
    # Friday 17:00 EST, DST starts Sunday 8 Mar: Monday 08:30 EDT is 12:30 UTC, not 13:30.
    assert w.next_window_start(utc(2026, 3, 6, 22, 0), NEW_YORK, WINDOWS) == utc(2026, 3, 9, 12, 30)
    # Friday 17:00 EDT, DST ends Sunday 1 Nov: Monday 08:30 EST is 13:30 UTC.
    assert w.next_window_start(utc(2026, 10, 30, 21, 0), NEW_YORK, WINDOWS) == utc(2026, 11, 2, 13, 30)


def test_europe_changes_on_its_own_date() -> None:
    # London moves to BST on Sunday 29 Mar 2026, three weeks after New York.
    assert not w.in_window(utc(2026, 3, 27, 7, 45), LONDON, WINDOWS)  # 07:45 GMT
    assert w.next_window_start(utc(2026, 3, 27, 7, 45), LONDON, WINDOWS) == utc(2026, 3, 27, 8, 30)
    assert w.in_window(utc(2026, 3, 30, 7, 45), LONDON, WINDOWS)  # 08:45 BST


def test_southern_hemisphere_daylight_saving_ends_in_april() -> None:
    # Saturday 4 Apr 09:00 AEDT; Sydney leaves daylight time on Sunday 5 Apr: Monday 08:30 AEST is 22:30 UTC.
    assert w.next_window_start(utc(2026, 4, 3, 22, 0), SYDNEY, WINDOWS) == utc(2026, 4, 5, 22, 30)


def test_zones_without_daylight_saving() -> None:
    assert w.in_window(utc(2026, 11, 16, 3, 0), ZoneInfo("Asia/Kolkata"), WINDOWS)  # Monday 08:30 IST
    # Arizona keeps UTC-7 all year: 08:30 is 15:30 UTC on both sides of the US change.
    phoenix = ZoneInfo("America/Phoenix")
    assert w.next_window_start(utc(2026, 3, 6, 12, 0), phoenix, WINDOWS) == utc(2026, 3, 6, 15, 30)
    assert w.next_window_start(utc(2026, 3, 9, 12, 0), phoenix, WINDOWS) == utc(2026, 3, 9, 15, 30)


def test_inside_a_window_the_time_is_kept() -> None:
    at = utc(2026, 3, 10, 14, 7, 3)
    assert w.next_window_start(at, NEW_YORK, WINDOWS) == at


def test_followups_keep_the_local_clock_across_daylight_saving() -> None:
    sent = utc(2026, 3, 5, 15, 0)  # Thursday 10:00 EST
    # day 3 is Sunday 8 Mar: moved to Monday 08:30 EDT
    assert w.followup_at(sent, 3, NEW_YORK, WINDOWS) == utc(2026, 3, 9, 12, 30)
    # day 7 and day 12 stay at 10:00 local, which is now 14:00 UTC (24-hour steps would give 15:00)
    assert w.followup_at(sent, 7, NEW_YORK, WINDOWS) == utc(2026, 3, 12, 14, 0)
    assert w.followup_at(sent, 12, NEW_YORK, WINDOWS) == utc(2026, 3, 17, 14, 0)


def test_followup_from_a_friday_goes_to_monday() -> None:
    sent = utc(2026, 11, 13, 4, 0)  # Friday 09:30 IST
    assert w.followup_at(sent, 3, ZoneInfo("Asia/Kolkata"), WINDOWS) == utc(2026, 11, 16, 4, 0)  # Monday 09:30


def test_a_time_skipped_by_the_clock_change_moves_forward() -> None:
    # 02:30 does not exist in New York on 8 Mar 2026; a 02:00 to 03:00 window would open at 03:00 EDT.
    night = w.parse_windows([["02:30", "04:00"]])
    # Sundays are closed anyway, so check the helper directly: 02:30 that day comes out as 03:30 EDT.
    assert w._at_local(datetime(2026, 3, 8).date(), time(2, 30), NEW_YORK) == utc(2026, 3, 8, 7, 30)
    assert w.next_window_start(utc(2026, 3, 9, 4, 0), NEW_YORK, night) == utc(2026, 3, 9, 6, 30)


def test_no_windows_is_an_error() -> None:
    with pytest.raises(ValueError, match="no sending window"):
        w.next_window_start(utc(2026, 3, 9, 4, 0), NEW_YORK, ())
