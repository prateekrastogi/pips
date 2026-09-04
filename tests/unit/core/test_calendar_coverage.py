"""A holiday list must say what it covers, or its silence means two different things.

`is_trading_day` answers `weekday < 5 and day not in holidays`. With a list that runs 2023-2026,
that returns True for 2019-04-17 — a real NSE holiday — because the date is simply not in a list
that never claimed to reach it. "Not a holiday" and "outside the data I have" are different
facts, and the code was reporting the second as the first.

This is the same shape as everything else found this week: an absence reading as a verified
absence. QC calling an unexamined record examined; a queued build reported as an unreachable
controller; a deleted `../past` reported as 21 broken donors.

So the calendar carries `holidays_covering_start` / `holidays_covering_end`, and a question
outside that range is REFUSED rather than answered.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.core.calendar import CalendarCoverageError, load_calendar

ROOT = Path(__file__).resolve().parents[3]
CAL = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")


def test_the_repo_calendar_now_carries_verified_holidays() -> None:
    assert CAL.holidays_verified, "sourced from NSE's own cash-market list on 2026-09-05"
    assert CAL.holidays, "a verified calendar with no holidays is a contradiction"


def test_a_known_holiday_is_not_a_trading_day() -> None:
    # Republic Day 2026, a Monday — so the weekday rule alone would call it tradeable.
    assert date(2026, 1, 26) in CAL.holidays
    assert CAL.is_trading_day(date(2026, 1, 26)) is False


def test_an_ordinary_weekday_inside_coverage_still_trades() -> None:
    assert CAL.is_trading_day(date(2026, 8, 25)) is True


def test_a_weekend_inside_coverage_does_not_trade() -> None:
    assert CAL.is_trading_day(date(2026, 8, 29)) is False  # Saturday


def test_a_date_outside_the_covered_range_is_refused_not_answered() -> None:
    """The property this file exists for.

    2019-04-17 was Mahavir Jayanti and NSE was shut. The list does not reach 2019, so answering
    "True, it traded" would be a fabrication dressed as a fact. Refusing says the one true thing
    available: this calendar does not know.
    """
    with pytest.raises(CalendarCoverageError) as raised:
        CAL.is_trading_day(date(2019, 4, 17))
    message = str(raised.value)
    assert "2019-04-17" in message
    assert "2023" in message and "2026" in message, "the refusal must state what IS covered"


def test_a_verified_calendar_states_its_bounds() -> None:
    """Verified without bounds would be the same silent answer in a better disguise."""
    assert CAL.holidays_covering_start is not None
    assert CAL.holidays_covering_end is not None


def test_the_boundary_days_themselves_are_inside_coverage() -> None:
    """Half-open ranges are where off-by-ones live, and one cost a day per symbol this week."""
    start, end = CAL.holidays_covering_start, CAL.holidays_covering_end
    assert start is not None and end is not None
    assert CAL.is_trading_day(start) in (True, False)
    assert CAL.is_trading_day(end) in (True, False)
    with pytest.raises(CalendarCoverageError):
        CAL.is_trading_day(date(start.year - 1, 12, 31))
    with pytest.raises(CalendarCoverageError):
        CAL.is_trading_day(date(end.year + 1, 1, 1))


def test_the_seeded_data_window_is_fully_covered() -> None:
    """The 3,101-symbol seed spans 2023-09-04..2026-09-03; QC over it must never hit a refusal."""
    start, end = CAL.holidays_covering_start, CAL.holidays_covering_end
    assert start is not None and end is not None
    assert start <= date(2023, 9, 4)
    assert end >= date(2026, 9, 3)
