"""Bar labelling and session conventions [C-BAR-01]."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from pips.core.time import NS_PER_MINUTE, bar_label_ns, is_usable_at, to_ist, ts_from_iso

OPEN = ts_from_iso("2026-06-01T09:15:00")


def test_naive_timestamps_are_ist_not_machine_local() -> None:
    assert ts_from_iso("2026-06-01T09:15:00") == ts_from_iso("2026-06-01T03:45:00+00:00")


def test_first_bar_includes_the_opening_instant() -> None:
    assert bar_label_ns(OPEN, NS_PER_MINUTE, OPEN) == OPEN + NS_PER_MINUTE


def test_interior_boundary_trade_joins_the_bar_ending_there() -> None:
    boundary = OPEN + NS_PER_MINUTE
    assert bar_label_ns(boundary, NS_PER_MINUTE, OPEN) == boundary


def test_mid_bar_trade_rounds_up_to_its_close() -> None:
    assert bar_label_ns(OPEN + 30 * 10**9, NS_PER_MINUTE, OPEN) == OPEN + NS_PER_MINUTE


def test_trade_before_the_open_is_refused() -> None:
    with pytest.raises(ValueError, match="precedes session open"):
        bar_label_ns(OPEN - 1, NS_PER_MINUTE, OPEN)


def test_non_positive_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        bar_label_ns(OPEN, 0, OPEN)


def test_a_bar_is_not_usable_before_its_label() -> None:
    label = OPEN + NS_PER_MINUTE
    assert not is_usable_at(label, label - 1)
    assert is_usable_at(label, label)


def test_ist_rendering() -> None:
    assert to_ist(OPEN).strftime("%Y-%m-%d %H:%M") == "2026-06-01 09:15"


# --------------------------------------------------------- found by mutation sweep ---


def test_a_naive_timestamp_means_ist_on_any_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The docstring's claim — *the same string means the same instant on every machine* — is
    the one thing this suite could not check, because the machine it runs on is in IST.

    Deleting `replace(tzinfo=IST)` makes `astimezone` fall back to the **machine's** zone, and
    on a developer's laptop in India that is the same answer. The property is real and the test
    was accidental: it passed because of where it ran. Jenkins runs containerised, so the two
    would disagree there and nowhere else — a failure that appears only in CI and only for
    whoever next touches this line.

    Forcing the process zone is what makes it machine-independent. Anything that reads a
    session start out of a config string depends on this: the exchange clock is IST, and a
    boundary read in the wrong zone shifts every bar label by hours.
    """
    expected = int(datetime(2026, 6, 1, 3, 45, tzinfo=UTC).timestamp()) * 1_000_000_000  # 09:15 IST

    for zone in ("UTC", "America/New_York", "Asia/Kolkata"):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
        assert ts_from_iso("2026-06-01T09:15:00") == expected, zone

    monkeypatch.delenv("TZ", raising=False)
    time.tzset()


def test_sub_second_precision_survives_the_parse() -> None:
    """Nanoseconds are the unit, and nothing tested below a whole second.

    `received_at_ns` and every bar label are nanosecond quantities; dropping the microsecond
    term truncates each to its second, and scaling it wrongly is off by a thousand. Both leave
    a plausible timestamp — ordered correctly, in the right era — which is why neither would be
    noticed downstream.
    """
    base = ts_from_iso("2026-06-01T09:15:00")

    assert ts_from_iso("2026-06-01T09:15:00.000001") == base + 1_000
    assert ts_from_iso("2026-06-01T09:15:00.5") == base + 500_000_000
    assert ts_from_iso("2026-06-01T09:15:00.999999") == base + 999_999_000
