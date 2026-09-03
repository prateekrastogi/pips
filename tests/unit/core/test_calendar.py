"""Exchange calendar and session structure [C-SESS-01] (§3.15, ADR-0004).

Two things this file defends hardest:

* **the broker cutoff is data, never a constant.** §3.15 says session eligibility comes from
  the daily capability snapshot. A test that passes with a hard-coded 15:12 would let that
  constant live in the code forever and break silently the day a broker moves it;
* **CAS is disabled as an alpha venue** (ADR-0004) until auction data and broker support are
  verified. Nothing may quietly start trading it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.core.calendar import (
    ExchangeCalendar,
    SessionState,
    load_calendar,
)
from pips.core.time import ts_from_iso

ROOT = Path(__file__).resolve().parents[3]
DAY = "2026-06-01"  # a Monday
CUTOFF = ts_from_iso(f"{DAY}T15:12:00")  # a broker's MIS cutoff, supplied as data


@pytest.fixture
def cal() -> ExchangeCalendar:
    return load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")


def at(hhmmss: str) -> int:
    return ts_from_iso(f"{DAY}T{hhmmss}")


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        ("09:15:00", SessionState.OPEN_SHOCK),  # the opening instant is in-session
        ("09:29:59", SessionState.OPEN_SHOCK),
        ("09:30:00", SessionState.OPEN_DIGEST),  # half-open [start, end)
        ("10:29:59", SessionState.OPEN_DIGEST),
        ("10:30:00", SessionState.MID),
        ("14:29:59", SessionState.MID),
        ("14:30:00", SessionState.LATE_CTS),
        ("15:11:59", SessionState.LATE_CTS),
        ("15:12:00", SessionState.FLATTEN_ONLY),  # exactly at the cutoff
        ("15:29:59", SessionState.FLATTEN_ONLY),
    ],
)
def test_session_states_partition_the_continuous_session(
    cal: ExchangeCalendar, clock: str, expected: SessionState
) -> None:
    assert cal.session_at(at(clock), broker_cutoff_ns=CUTOFF) is expected


def test_before_the_open_is_outside_the_continuous_session(cal: ExchangeCalendar) -> None:
    # Pre-open is excluded from continuous bars (§3.5); it is not a session state.
    assert cal.session_at(at("09:14:59"), broker_cutoff_ns=CUTOFF) is None


def test_after_the_close_is_outside_the_continuous_session(cal: ExchangeCalendar) -> None:
    assert cal.session_at(at("15:30:00"), broker_cutoff_ns=CUTOFF) is None


def test_the_broker_cutoff_is_data_not_a_constant(cal: ExchangeCalendar) -> None:
    # The same instant is LATE_CTS under one broker's cutoff and FLATTEN_ONLY under another.
    # If this ever stops holding, a cutoff has been baked into the code.
    instant = at("15:20:00")
    late = ts_from_iso(f"{DAY}T15:25:00")
    assert cal.session_at(instant, broker_cutoff_ns=late) is SessionState.LATE_CTS
    assert cal.session_at(instant, broker_cutoff_ns=CUTOFF) is SessionState.FLATTEN_ONLY


def test_a_cutoff_outside_the_session_is_refused(cal: ExchangeCalendar) -> None:
    with pytest.raises(ValueError, match="cutoff"):
        cal.session_at(at("11:00:00"), broker_cutoff_ns=at("16:00:00"))


def test_cas_is_a_separate_venue_not_a_continuous_phase(cal: ExchangeCalendar) -> None:
    # CAS is 15:15-15:35 while the continuous session ends 15:30 — they overlap in wall
    # clock, so CAS cannot be a phase of the continuous session.
    assert cal.in_cas_window(at("15:20:00"))
    assert cal.session_at(at("15:20:00"), broker_cutoff_ns=CUTOFF) is SessionState.FLATTEN_ONLY
    assert not cal.in_cas_window(at("15:14:59"))
    assert not cal.in_cas_window(at("15:35:00"))


def test_cas_is_disabled_as_an_alpha_venue(cal: ExchangeCalendar) -> None:
    # ADR-0004. Until auction data and broker support are verified, nothing trades CAS.
    assert cal.cas_enabled_as_alpha is False
    assert SessionState.CAS.tradeable_as_alpha is False


@pytest.mark.parametrize(
    ("state", "tradeable"),
    [
        (SessionState.OPEN_SHOCK, True),
        (SessionState.OPEN_DIGEST, True),
        (SessionState.MID, True),
        (SessionState.LATE_CTS, True),
        (SessionState.CAS, False),
        (SessionState.FLATTEN_ONLY, False),
    ],
)
def test_only_risk_reducing_states_are_untradeable(state: SessionState, tradeable: bool) -> None:
    assert state.tradeable_as_alpha is tradeable


def test_weekends_are_not_trading_days(cal: ExchangeCalendar) -> None:
    assert not cal.is_trading_day(date(2026, 6, 6))  # Saturday
    assert not cal.is_trading_day(date(2026, 6, 7))  # Sunday
    assert cal.is_trading_day(date(2026, 6, 1))  # Monday


def test_the_calendar_admits_its_holidays_are_unverified(cal: ExchangeCalendar) -> None:
    # Costs are effective-dated data with source + verified_on (rule 6); a calendar is the
    # same kind of object. Shipping invented holiday dates would be worse than shipping none,
    # because an invented date looks exactly like a verified one.
    assert cal.holidays_verified is False
    with pytest.raises(RuntimeError, match="not verified"):
        cal.require_verified_holidays()


def test_an_unverified_calendar_still_answers_weekday_questions(cal: ExchangeCalendar) -> None:
    # Unverified must not mean unusable: P0-P2 research runs on fixtures and needs the
    # session structure long before the holiday list is sourced at M6.
    assert cal.is_trading_day(date(2026, 6, 1)) is True


def test_calendar_identity_is_content_addressed(cal: ExchangeCalendar) -> None:
    # The calendar hash is part of trial identity [C-ID-01] and the bundle [C-BNDL-01],
    # so it must be stable and it must change when the calendar does.
    assert len(cal.content_hash()) == 64
    assert (
        cal.content_hash()
        == load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml").content_hash()
    )


# --------------------------------------------------------- found by mutation sweep ---


def test_a_listed_holiday_is_not_a_trading_day(cal: ExchangeCalendar) -> None:
    """The half of `is_trading_day` that the shipped calendar cannot exercise.

    `holidays` is empty and `holidays_verified` is false — M6 has yet to source the list — so
    `day not in self.holidays` has been vacuously true since it was written and no test has
    ever supplied a holiday. Dropping the check entirely changes nothing today and everything
    on the day the real list arrives, which is precisely when nobody will be looking at this
    line. A holiday counted as a trading day inflates `outer_fold_count`'s panel and plans
    fetches for sessions that never happened.
    """
    holiday = date(2026, 6, 3)  # a Wednesday
    with_holiday = cal.model_copy(update={"holidays": (holiday,)})

    assert not with_holiday.is_trading_day(holiday)
    assert with_holiday.is_trading_day(date(2026, 6, 2)), "the Tuesday beside it still trades"
    assert cal.is_trading_day(holiday), "and the shipped calendar, with no list, still says yes"


def test_verified_holidays_need_both_a_source_and_a_date(cal: ExchangeCalendar) -> None:
    """Either alone is a claim without the other half.

    A source with no verification date says where the list came from and not that anyone
    checked it; a date with no source says somebody checked something. `require_verified_
    holidays` guards the path to real capital, so both halves have to be present for it to
    mean anything — and neither half alone was tested.
    """
    sourced_only = cal.model_copy(
        update={"holidays_source": "NSE circular", "holidays_verified_on": None}
    )
    dated_only = cal.model_copy(
        update={"holidays_source": "", "holidays_verified_on": date(2026, 6, 1)}
    )

    assert not sourced_only.holidays_verified
    assert not dated_only.holidays_verified
    for incomplete in (sourced_only, dated_only):
        with pytest.raises(RuntimeError, match="not verified"):
            incomplete.require_verified_holidays()

    both = cal.model_copy(
        update={"holidays_source": "NSE circular", "holidays_verified_on": date(2026, 6, 1)}
    )
    assert both.holidays_verified
    both.require_verified_holidays()


def test_the_continuous_session_is_measured_in_minutes(cal: ExchangeCalendar) -> None:
    """375, and both ways of getting it wrong give a plausible-looking number.

    Subtracting in the wrong order gives -375, and dropping the minute term gives 360 — six
    hours, which is close enough to the truth to pass a glance. This value sets what a complete
    day should contain, so QC's coverage floor and the campaign planner's candle counts are both
    computed from it.
    """
    assert cal.continuous_session_minutes == 375


def test_the_cas_window_includes_its_opening_instant(cal: ExchangeCalendar) -> None:
    """Half-open at the end, closed at the start — the same convention as the session states.

    The bar labelled exactly at the start belongs to the window that begins there; the one at
    the end belongs to whatever comes next. The end boundary was tested and the start was not.
    """
    start = cal.cas_window.start
    assert cal.in_cas_window(ts_from_iso(f"{DAY}T{start}:00"))


def test_the_flatten_deadline_precedes_the_broker_cutoff(cal: ExchangeCalendar) -> None:
    """§3.14: broker auto-square-off is a failure path, never the primary exit.

    A deadline equal to the cutoff is a race with the broker; one after it means the broker
    always wins and the engine's scheduler is decorative. Either way positions are closed by
    somebody else's logic at somebody else's price, which is the outcome the independent
    scheduler exists to prevent.
    """
    open_ns = ts_from_iso(f"{DAY}T09:15:00")

    deadline = cal.flatten_deadline_ns(open_ns, CUTOFF)

    assert deadline < CUTOFF, "the engine must be finished before the broker starts"
    assert deadline > open_ns


def test_a_cutoff_before_the_open_is_refused(cal: ExchangeCalendar) -> None:
    """It would put the flatten deadline before the session started, and the arithmetic would
    not complain — it would return a negative-length day and look like a number."""
    open_ns = ts_from_iso(f"{DAY}T09:15:00")
    with pytest.raises(ValueError, match="after the session open"):
        cal.flatten_deadline_ns(open_ns, open_ns - 1)
