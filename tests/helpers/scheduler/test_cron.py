"""Tests for cecli.helpers.scheduler.cron (tests.md cases 40-44).

Self-contained (no conftest fixtures required).
"""

from datetime import datetime, timedelta
from datetime import timezone
from datetime import timezone as dt_timezone

import pytest

from cecli.helpers.scheduler.cron import (
    is_due,
    next_run,
    parse_schedule,
    resolve_timezone,
)


def _dt(text: str) -> datetime:
    """Parse an ISO string (``Z`` suffix allowed) into an aware UTC datetime."""

    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


# ── case 40: plain 5-field cron from a fixed datetime ─────────────────


def test_next_run_half_past_and_every_thirty():
    result = next_run("*/30 * * * *", _dt("2026-10-10T12:07:00Z"))

    assert result == _dt("2026-10-10T12:30:00Z")
    assert next_run("*/30 * * * *", _dt("2026-10-10T12:30:00Z")) > _dt("2026-10-10T12:30:00Z")


def test_next_run_hour_of_day():
    assert next_run("15 9 * * *", _dt("2026-10-10T09:15:00Z")) == _dt("2026-10-11T09:15:00Z")


def test_next_run_returns_aware_utc_for_naive_input():
    result = next_run("*/30 * * * *", datetime(2026, 10, 10, 12, 7))

    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)
    assert result == _dt("2026-10-10T12:30:00Z")


# ── case 41: presets ───────────────────────────────────────────────────


def test_preset_hourly():
    assert next_run("@hourly", _dt("2026-10-10T12:22:00Z")) == _dt("2026-10-10T13:00:00Z")


def test_preset_daily():
    assert next_run("@daily", _dt("2026-10-10T12:22:00Z")) == _dt("2026-10-11T00:00:00Z")


def test_preset_weekly():
    # 2026-10-10 is a Saturday; next Sunday 00:00 is 2026-10-11
    assert next_run("@weekly", _dt("2026-10-10T12:22:00Z")) == _dt("2026-10-11T00:00:00Z")


def test_preset_every_interval():
    assert next_run("@every 15m", _dt("2026-10-10T12:22:00Z")) == _dt("2026-10-10T12:37:00Z")
    assert next_run("@every 2h", _dt("2026-10-10T12:22:00Z")) == _dt("2026-10-10T14:22:00Z")
    assert next_run("@every 1d", _dt("2026-10-10T12:22:00Z")) == _dt("2026-10-11T12:22:00Z")


def test_parse_schedule_engines():
    assert parse_schedule("*/30 * * * *") == ("cron", "*/30 * * * *")
    assert parse_schedule("@hourly") == ("cron", "0 * * * *")
    assert parse_schedule("@every 90m")[0] == "interval"
    assert parse_schedule("@every 90m")[1] == timedelta(minutes=90)
    assert parse_schedule(None) == ("manual", None)
    assert parse_schedule("") == ("manual", None)
    assert parse_schedule("   ") == ("manual", None)


# ── case 42: month rollover + DST ─────────────────────────────────────


def test_month_rollover():
    assert next_run("0 0 1 * *", _dt("2026-01-15T00:00:00Z")) == _dt("2026-02-01T00:00:00Z")
    assert next_run("0 12 28-31 * *", _dt("2026-01-28T13:00:00Z")) == _dt("2026-01-29T12:00:00Z")
    # daily at 00:00 Europe/Berlin from Feb 27 05:00Z -> Feb 27 23:00Z (CET)
    assert next_run("0 0 * * *", _dt("2026-02-27T05:00:00Z"), timezone="Europe/Berlin") == _dt(
        "2026-02-27T23:00:00Z"
    )


def test_dst_spring_forward_wall_clock():
    # 02:30 America/New_York. Mar 7 2026 (EST, UTC-5): 02:30 local == 07:30Z.
    assert next_run("30 2 * * *", _dt("2026-03-07T05:00:00Z"), timezone="America/New_York") == _dt(
        "2026-03-07T07:30:00Z"
    )
    # Mar 8 2026 02:30 does not exist (clocks jump 02:00->03:00); croniter rolls to 03:00.
    gap_result = next_run("30 2 * * *", _dt("2026-03-07T07:31:00Z"), timezone="America/New_York")
    assert gap_result == _dt("2026-03-08T07:00:00Z")
    # Mar 9 (EDT, UTC-4): 02:30 local == 06:30Z — one hour earlier in UTC than EST week.
    assert next_run("30 2 * * *", _dt("2026-03-09T05:00:00Z"), timezone="America/New_York") == _dt(
        "2026-03-09T06:30:00Z"
    )


def test_dst_fall_back_wall_clock():
    # Nov 1 2026 01:00 happens twice in New York (EDT 05:00Z, then EST 06:00Z).
    assert next_run("0 1 * * *", _dt("2026-11-01T04:30:00Z"), timezone="America/New_York") == _dt(
        "2026-11-01T05:00:00Z"
    )
    after_first = next_run("0 1 * * *", _dt("2026-11-01T05:30:00Z"), timezone="America/New_York")
    assert after_first in (_dt("2026-11-01T06:00:00Z"), _dt("2026-11-02T05:00:00Z"))
    assert after_first > _dt("2026-11-01T05:30:00Z")


def test_timezone_sentinel_local_means_utc():
    base = _dt("2026-10-10T12:07:00Z")

    assert next_run("*/30 * * * *", base, timezone="local") == _dt("2026-10-10T12:30:00Z")
    assert next_run("*/30 * * * *", base, timezone=None) == _dt("2026-10-10T12:30:00Z")
    assert next_run("*/30 * * * *", base, timezone="UTC") == _dt("2026-10-10T12:30:00Z")


# ── case 43: malformed schedules ──────────────────────────────────────


@pytest.mark.parametrize(
    "expr",
    [
        "bogus",
        "@hourlyy",
        "@every",
        "@every 15x",
        "@every 0m",
        "*/30 * * *",
        "61 * * * *",
        "0 0 * * * 2 8 2000",
    ],
)
def test_malformed_raises_value_error(expr):
    with pytest.raises(ValueError):
        next_run(expr, _dt("2026-10-10T12:00:00Z"))

    with pytest.raises(ValueError):
        parse_schedule(expr)


def test_unknown_timezone_raises_value_error():
    with pytest.raises(ValueError):
        next_run("*/30 * * * *", _dt("2026-10-10T12:00:00Z"), timezone="Mars/Olympus_Mons")


# ── case 43b: hosts with no IANA tz database (bare Windows) ───────────


@pytest.fixture
def no_tzdb(monkeypatch):
    """Pretend zoneinfo has no tz database to read (a Windows box without tzdata)."""
    import zoneinfo

    def explode(key):
        raise zoneinfo.ZoneInfoNotFoundError(key)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", explode)
    monkeypatch.setattr(zoneinfo, "available_timezones", lambda: set())


def test_utc_needs_no_tz_database(no_tzdb):
    base = _dt("2026-10-10T12:07:00Z")

    for name in ("UTC", "utc", " Zulu ", "Etc/UTC", "GMT", "local", ""):
        assert resolve_timezone(name) is dt_timezone.utc
        assert next_run("*/30 * * * *", base, timezone=name) == _dt("2026-10-10T12:30:00Z")


def test_named_zone_without_tz_database_blames_the_database(no_tzdb):
    with pytest.raises(ValueError, match="tzdata"):
        next_run("*/30 * * * *", _dt("2026-10-10T12:00:00Z"), timezone="Europe/Berlin")


# ── case 44: manual schedules ─────────────────────────────────────────


@pytest.mark.parametrize("expr", [None, "", "   "])
def test_manual_next_run_is_none(expr):
    assert next_run(expr, _dt("2026-10-10T12:00:00Z")) is None


# ── is_due helper ─────────────────────────────────────────────────────


def test_is_due():
    assert is_due("*/30 * * * *", _dt("2026-10-10T12:30:00Z"))
    assert not is_due("*/30 * * * *", _dt("2026-10-10T12:31:30Z"))
    assert not is_due(None, _dt("2026-10-10T12:30:00Z"))
