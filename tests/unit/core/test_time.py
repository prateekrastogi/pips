"""Bar labelling and session conventions [C-BAR-01]."""

from __future__ import annotations

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
