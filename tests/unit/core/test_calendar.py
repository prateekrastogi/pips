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
