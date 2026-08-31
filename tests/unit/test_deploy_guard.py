"""Market-hours restart guard for the deploy rail [C-DEPLOY-01] (§2.2).

Research and data services roll on every main update. **Trading-path services never hot-swap
during market hours** — the rail holds their restart until after the close or before the open,
unless a human forces it.

This guard FAILS CLOSED, and that is the whole design. The donor this rail is ported from
(SAL-0010) carried a guard whose entire purpose was to avoid restarting mid-trade; it ran
`pgrep` inside a container that had no `procps`, the command exited 127, and the caller read
that as "not busy". The guard was inert and looked fine. Every uncertainty here therefore
resolves to *defer*: an unknown service is treated as trading-path, and an unreadable calendar
blocks rather than waves through.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.core.calendar import load_calendar
from pips.core.time import ts_from_iso
from pips.ops.deploy_guard import (
    ROLLING_SERVICES,
    TRADING_PATH_SERVICES,
    restart_decision,
)

ROOT = Path(__file__).resolve().parents[2]
CAL = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")
TRADING_DAY = "2026-06-01"  # a Monday
WEEKEND = "2026-06-06"  # a Saturday


def at(day: str, clock: str) -> int:
    return ts_from_iso(f"{day}T{clock}")


@pytest.mark.parametrize(
    ("clock", "permitted"),
    [
        ("08:44:59", True),  # before the protected window opens
        ("08:45:00", False),  # window opens
        ("12:00:00", False),
        ("15:34:59", False),
        ("15:35:00", True),  # after the close, per §2.2
        ("23:00:00", True),
    ],
)
def test_the_protected_window_is_0845_to_1535(clock: str, permitted: bool) -> None:
    d = restart_decision("breeze-reader", at(TRADING_DAY, clock), CAL)
    assert d.permitted is permitted, d.reason


def test_a_non_trading_day_is_always_open_for_restarts() -> None:
    assert restart_decision("live-engine", at(WEEKEND, "12:00:00"), CAL).permitted is True


@pytest.mark.parametrize("service", sorted(ROLLING_SERVICES))
def test_research_and_data_services_roll_even_mid_session(service: str) -> None:
    d = restart_decision(service, at(TRADING_DAY, "12:00:00"), CAL)
    assert d.permitted is True, d.reason


@pytest.mark.parametrize("service", sorted(TRADING_PATH_SERVICES))
def test_every_trading_path_service_is_held_mid_session(service: str) -> None:
    assert restart_decision(service, at(TRADING_DAY, "12:00:00"), CAL).permitted is False


def test_an_unknown_service_is_treated_as_trading_path() -> None:
    # FAIL CLOSED. A service added to compose but not to either list must be held, not waved
    # through — the donor's inert guard is what happens when the unknown case defaults to
    # "fine". Being wrong here costs a deferred deploy; being wrong the other way restarts
    # the order plane mid-session.
    d = restart_decision("some-new-service", at(TRADING_DAY, "12:00:00"), CAL)
    assert d.permitted is False
    assert "unknown" in d.reason.lower()


def test_the_two_service_lists_do_not_overlap() -> None:
    assert set() == TRADING_PATH_SERVICES & ROLLING_SERVICES


def test_a_human_force_is_permitted_but_names_the_recovery_path() -> None:
    # §2.2 allows a forced intraday restart, and requires it to follow the crash-recovery
    # path (journal replay + broker reconciliation, §3.13) like any other restart.
    d = restart_decision("live-engine", at(TRADING_DAY, "12:00:00"), CAL, force=True)
    assert d.permitted is True
    assert "journal" in d.reason.lower() and "reconcil" in d.reason.lower()


def test_a_deferred_decision_says_when_it_will_be_permitted() -> None:
    d = restart_decision("breeze-reader", at(TRADING_DAY, "12:00:00"), CAL)
    assert d.permitted is False
    assert "15:35" in d.reason


def test_an_unreadable_calendar_defers_rather_than_proceeding() -> None:
    # The uncertainty case. If we cannot tell whether it is market hours, it is market hours.
    d = restart_decision("breeze-reader", at(TRADING_DAY, "12:00:00"), calendar=None)
    assert d.permitted is False
    assert "calendar" in d.reason.lower()


def test_an_unverified_holiday_list_errs_toward_deferring() -> None:
    # The shipped calendar has an empty, unverified holiday list, so it can only ever
    # OVER-report trading days — never under-report one. Over-reporting defers a restart,
    # which is the safe direction. Pinned so a future holiday source cannot silently invert it.
    assert CAL.holidays_verified is False
    assert CAL.is_trading_day(date(2026, 6, 1)) is True  # a real trading Monday
    # If 2026-06-01 were in fact a holiday, the empty list would still call it a trading day,
    # and the guard would DEFER a restart it could have allowed. Wrong in the safe direction.
    assert restart_decision("live-engine", at(TRADING_DAY, "12:00:00"), CAL).permitted is False
