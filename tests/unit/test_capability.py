"""Broker capability snapshots [C-DATA-01] (§3.4, M3 v0).

Square-off times, order types, rate limits and shortability are **data, not constants**
(§3.4). This is the table they live in, and the reason it exists is that a constant fails
silently on the day a broker changes it.

Two things this file defends:

* **point-in-time reads.** A snapshot taken later must not change what an earlier date saw,
  or every backtest spanning the change is quietly wrong;
* **honesty about what is verified.** An unverified fact must be usable for fixture research
  and refused for anything trading-path — and where a placeholder is unavoidable it must err
  in the safe direction.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pips.core.calendar import SessionState, load_calendar
from pips.core.time import ts_from_iso
from pips.data.pit.capability import (
    CapabilitySnapshot,
    launch_leverage,
    load_capability_csv,
)

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "config" / "brokers" / "flattrade_capability_v0.csv"


@pytest.fixture
def snap() -> CapabilitySnapshot:
    return load_capability_csv(CSV)


# ------------------------------------------------------------------ shipped facts ------


def test_flattrade_is_limit_only(snap: CapabilitySnapshot) -> None:
    # §3.7: the Flattrade API is limit-only, which is why protected marketable-limit is the
    # portable default order type everywhere. If this row ever grows MARKET, that design
    # premise changed and the execution policy must be revisited.
    row = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "RELIANCE", "BUY")
    assert row.order_types == ["LIMIT"]


def test_the_engine_governor_binds_before_the_broker_limit(snap: CapabilitySnapshot) -> None:
    # Rule 9: the engine caps at 5/s while Flattrade permits 10/s. The governor must be the
    # binding constraint, or we are relying on the broker to enforce our own compliance cap.
    row = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "RELIANCE", "BUY")
    assert row.rate_limit_per_second >= 5
    assert row.rate_limit_per_minute == 40


def test_launch_is_unlevered_whatever_the_broker_permits(snap: CapabilitySnapshot) -> None:
    # ADR-0003. The snapshot records what the broker OFFERS; policy decides what we use, and
    # broker-permitted leverage must not leak into sizing.
    row = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "RELIANCE", "BUY")
    assert row.max_leverage >= Decimal(1)
    assert launch_leverage() == Decimal(1)


# ------------------------------------------------------------------- point in time -----


def test_a_later_snapshot_does_not_change_an_earlier_read(snap: CapabilitySnapshot) -> None:
    early = snap.resolve(date(2026, 8, 1), "FLATTRADE", "MIS", "RELIANCE", "BUY")
    assert early.snapshot_date <= date(2026, 8, 1)


def test_reading_before_any_snapshot_is_refused(snap: CapabilitySnapshot) -> None:
    # Returning a default would silently invent capability for a date we have no data for.
    with pytest.raises(LookupError, match="no capability snapshot"):
        snap.resolve(date(2020, 1, 1), "FLATTRADE", "MIS", "RELIANCE", "BUY")


def test_an_instrument_specific_row_beats_the_wildcard(snap: CapabilitySnapshot) -> None:
    default = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "RELIANCE", "SELL")
    specific = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "YESBANK", "SELL")
    assert default.instrument_id == "*"
    assert specific.instrument_id == "YESBANK"
    assert specific.shortable is False and default.shortable is True


def test_an_unknown_broker_is_refused(snap: CapabilitySnapshot) -> None:
    with pytest.raises(LookupError):
        snap.resolve(date(2026, 8, 31), "SOME_OTHER_BROKER", "MIS", "RELIANCE", "BUY")


# ---------------------------------------------------------- verification honesty --------


def test_the_square_off_time_is_marked_unverified(snap: CapabilitySnapshot) -> None:
    # §3.7 records ~15:12/~15:25 for ZERODHA. Flattrade's are unknown until the M3 probe, so
    # the shipped value is a placeholder and must say so rather than look like a fact.
    row = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "RELIANCE", "BUY")
    assert row.square_off_verified is False
    with pytest.raises(RuntimeError, match="not verified"):
        row.require_verified_square_off()


def test_an_unverified_square_off_errs_early(snap: CapabilitySnapshot) -> None:
    # The safe direction is unambiguous: flattening earlier than necessary costs a little
    # edge, flattening later risks the broker's own auto-square-off, which §3.14 calls a
    # failure path. A placeholder that is not conservative is worse than no placeholder.
    cal = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")
    row = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "RELIANCE", "BUY")
    assert row.square_off_time is not None
    earliest_known_broker_cutoff = "15:12:00"
    assert row.square_off_time.isoformat() < earliest_known_broker_cutoff
    assert (
        cal.session_at(
            ts_from_iso("2026-08-31T15:11:00"),
            broker_cutoff_ns=row.square_off_ns(date(2026, 8, 31)),
        )
        is SessionState.FLATTEN_ONLY
    )


def test_verified_facts_carry_a_source_and_a_date(snap: CapabilitySnapshot) -> None:
    row = snap.resolve(date(2026, 8, 31), "FLATTRADE", "MIS", "RELIANCE", "BUY")
    assert row.source
    assert row.verified_on is not None


# --------------------------------------------------- the loop the calendar needs --------


def test_the_capability_cutoff_drives_the_session_state(snap: CapabilitySnapshot) -> None:
    # This is the whole point of the table: session_at() demands the cutoff as data, and
    # this is where that datum comes from. No constant anywhere in the path.
    cal = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")
    day = date(2026, 8, 31)
    cutoff_ns = snap.resolve(day, "FLATTRADE", "MIS", "RELIANCE", "BUY").square_off_ns(day)

    before = cal.session_at(ts_from_iso("2026-08-31T14:45:00"), broker_cutoff_ns=cutoff_ns)
    after = cal.session_at(ts_from_iso("2026-08-31T15:05:00"), broker_cutoff_ns=cutoff_ns)
    assert before is SessionState.LATE_CTS
    assert after is SessionState.FLATTEN_ONLY


def test_a_delivery_product_has_no_intraday_square_off(snap: CapabilitySnapshot) -> None:
    row = snap.resolve(date(2026, 8, 31), "FLATTRADE", "CNC", "RELIANCE", "BUY")
    assert row.square_off_time is None
