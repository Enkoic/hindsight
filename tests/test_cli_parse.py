from datetime import date, datetime, timezone

import pytest
import typer

from hindsight.cli import _parse_day, _resolve_range


def test_parse_day_today():
    today = datetime.now(timezone.utc).date()
    assert _parse_day(None) == today
    assert _parse_day("today") == today


def test_parse_day_iso():
    assert _parse_day("2026-04-22") == date(2026, 4, 22)


def test_resolve_week():
    s, e = _resolve_range(None, None, "2026-W17", None)
    # ISO week 17 of 2026 is Mon..Sun
    assert s.weekday() == 0  # Monday
    assert e.weekday() == 6  # Sunday
    assert (e - s).days == 6


def test_resolve_month_april():
    s, e = _resolve_range(None, None, None, "2026-04")
    assert s == date(2026, 4, 1)
    assert e == date(2026, 4, 30)


def test_resolve_month_december_handles_year_rollover():
    s, e = _resolve_range(None, None, None, "2025-12")
    assert s == date(2025, 12, 1)
    assert e == date(2025, 12, 31)


def test_resolve_custom_range():
    s, e = _resolve_range("2026-04-20", "2026-04-26", None, None)
    assert s == date(2026, 4, 20)
    assert e == date(2026, 4, 26)


def test_resolve_requires_at_least_one_form():
    with pytest.raises(typer.BadParameter):
        _resolve_range(None, None, None, None)
