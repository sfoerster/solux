"""Tests for cron expression parsing and matching."""

from __future__ import annotations

from datetime import datetime, timezone

from solus.triggers.cron import _cron_matches


def _dt(minute=0, hour=0, day=1, month=1, year=2026, weekday_target=None):
    """Helper to create a datetime. weekday_target is ignored; use real dates."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Wildcard
# ---------------------------------------------------------------------------


def test_all_wildcards_always_matches() -> None:
    assert _cron_matches("* * * * *", _dt(minute=0, hour=0)) is True
    assert _cron_matches("* * * * *", _dt(minute=59, hour=23, day=31, month=12)) is True


# ---------------------------------------------------------------------------
# Exact values
# ---------------------------------------------------------------------------


def test_exact_minute() -> None:
    assert _cron_matches("30 * * * *", _dt(minute=30)) is True
    assert _cron_matches("30 * * * *", _dt(minute=15)) is False


def test_exact_hour() -> None:
    assert _cron_matches("0 8 * * *", _dt(minute=0, hour=8)) is True
    assert _cron_matches("0 8 * * *", _dt(minute=0, hour=9)) is False


def test_exact_day_of_month() -> None:
    assert _cron_matches("0 0 15 * *", _dt(day=15)) is True
    assert _cron_matches("0 0 15 * *", _dt(day=16)) is False


def test_exact_month() -> None:
    assert _cron_matches("0 0 1 6 *", _dt(month=6)) is True
    assert _cron_matches("0 0 1 6 *", _dt(month=7)) is False


# ---------------------------------------------------------------------------
# Step values (*/n)
# ---------------------------------------------------------------------------


def test_step_minute() -> None:
    assert _cron_matches("*/15 * * * *", _dt(minute=0)) is True
    assert _cron_matches("*/15 * * * *", _dt(minute=15)) is True
    assert _cron_matches("*/15 * * * *", _dt(minute=30)) is True
    assert _cron_matches("*/15 * * * *", _dt(minute=7)) is False


def test_step_hour() -> None:
    assert _cron_matches("0 */6 * * *", _dt(hour=0)) is True
    assert _cron_matches("0 */6 * * *", _dt(hour=6)) is True
    assert _cron_matches("0 */6 * * *", _dt(hour=3)) is False


def test_step_zero_returns_false() -> None:
    assert _cron_matches("*/0 * * * *", _dt(minute=0)) is False


def test_step_invalid_value_returns_false() -> None:
    assert _cron_matches("*/abc * * * *", _dt()) is False


# ---------------------------------------------------------------------------
# Comma-separated lists
# ---------------------------------------------------------------------------


def test_comma_list_minute() -> None:
    assert _cron_matches("0,15,30,45 * * * *", _dt(minute=15)) is True
    assert _cron_matches("0,15,30,45 * * * *", _dt(minute=10)) is False


def test_comma_list_hour() -> None:
    assert _cron_matches("0 8,12,18 * * *", _dt(hour=12)) is True
    assert _cron_matches("0 8,12,18 * * *", _dt(hour=10)) is False


# ---------------------------------------------------------------------------
# Range values (a-b)
# ---------------------------------------------------------------------------


def test_range_minute() -> None:
    assert _cron_matches("10-20 * * * *", _dt(minute=15)) is True
    assert _cron_matches("10-20 * * * *", _dt(minute=25)) is False
    assert _cron_matches("10-20 * * * *", _dt(minute=10)) is True
    assert _cron_matches("10-20 * * * *", _dt(minute=20)) is True


def test_range_hour() -> None:
    assert _cron_matches("0 9-17 * * *", _dt(hour=12)) is True
    assert _cron_matches("0 9-17 * * *", _dt(hour=20)) is False


# ---------------------------------------------------------------------------
# Day-of-week (Sunday=0 or 7)
# ---------------------------------------------------------------------------


def test_dow_monday() -> None:
    # 2026-01-05 is a Monday (weekday()=0, cron dow=1)
    dt = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    assert _cron_matches("* * * * 1", dt) is True
    assert _cron_matches("* * * * 2", dt) is False


def test_dow_sunday_as_0() -> None:
    # 2026-01-04 is a Sunday (weekday()=6, cron dow=0)
    dt = datetime(2026, 1, 4, 0, 0, tzinfo=timezone.utc)
    assert _cron_matches("* * * * 0", dt) is True


def test_dow_sunday_as_7() -> None:
    # 2026-01-04 is a Sunday — cron 7 should also match Sunday
    dt = datetime(2026, 1, 4, 0, 0, tzinfo=timezone.utc)
    assert _cron_matches("* * * * 7", dt) is True


def test_dow_range_weekdays() -> None:
    # Monday through Friday: 1-5
    monday = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 1, 3, 0, 0, tzinfo=timezone.utc)
    assert _cron_matches("* * * * 1-5", monday) is True
    assert _cron_matches("* * * * 1-5", saturday) is False


def test_dow_wrap_around() -> None:
    # 5-0 means Friday through Sunday (wrap around)
    friday = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)  # Friday
    sunday = datetime(2026, 1, 4, 0, 0, tzinfo=timezone.utc)  # Sunday
    wednesday = datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc)  # Wednesday
    assert _cron_matches("* * * * 5-0", friday) is True
    assert _cron_matches("* * * * 5-0", sunday) is True
    assert _cron_matches("* * * * 5-0", wednesday) is False


# ---------------------------------------------------------------------------
# Edge cases and invalid expressions
# ---------------------------------------------------------------------------


def test_too_few_fields() -> None:
    assert _cron_matches("* * *", _dt()) is False


def test_too_many_fields() -> None:
    assert _cron_matches("* * * * * *", _dt()) is False


def test_invalid_numeric_value() -> None:
    assert _cron_matches("abc * * * *", _dt()) is False


def test_out_of_range_value() -> None:
    # 60 is out of range for minutes (max 59), so it should never match any valid minute
    assert _cron_matches("60 * * * *", _dt(minute=0)) is False
    assert _cron_matches("-1 * * * *", _dt()) is False


def test_invalid_range_three_parts() -> None:
    assert _cron_matches("1-2-3 * * * *", _dt(minute=2)) is False


def test_invalid_range_non_numeric() -> None:
    assert _cron_matches("a-b * * * *", _dt()) is False


# ---------------------------------------------------------------------------
# Combined / real-world expressions
# ---------------------------------------------------------------------------


def test_weekday_mornings() -> None:
    # 0 8 * * 1-5 → 8:00 AM on weekdays
    monday_8am = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    monday_9am = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
    sunday_8am = datetime(2026, 1, 4, 8, 0, tzinfo=timezone.utc)
    assert _cron_matches("0 8 * * 1-5", monday_8am) is True
    assert _cron_matches("0 8 * * 1-5", monday_9am) is False
    assert _cron_matches("0 8 * * 1-5", sunday_8am) is False


def test_every_quarter_hour_business_hours() -> None:
    # */15 9-17 * * 1-5
    monday_930 = datetime(2026, 1, 5, 9, 30, tzinfo=timezone.utc)
    monday_930_ok = _cron_matches("*/15 9-17 * * 1-5", monday_930)
    assert monday_930_ok is True

    monday_907 = datetime(2026, 1, 5, 9, 7, tzinfo=timezone.utc)
    assert _cron_matches("*/15 9-17 * * 1-5", monday_907) is False
