"""Median daily ₹-volume: the third daily-derivable term of §4.1's score.

§4.1 gives `z(log median ₹-volume)` with weight +1.0, and the policy grid says "prefer
median/lower quartile over one-day volume" — so a MEDIAN over the lookback, not a mean and not a
single session. That is the whole of what the blueprint specifies.

A ZERO-VOLUME DAY IS DATA HERE, and that is the one place this differs sharply from
`amihud_ratio`. Amihud drops a day with no volume because `|r| / 0` is undefined — the day
carries no information about that ratio. A day on which nothing traded carries a great deal of
information about how liquid a name is, and dropping it would let a stock that trades twice a
month rank beside one that trades every session. So it counts, and it drags the median down,
which is correct.
"""

from __future__ import annotations

import math

import pytest

from pips.universe.liquidity import median_rupee_volume


def bars(*pairs: tuple[int, int]) -> list[tuple[int, int]]:
    """(close_paise, volume) per session."""
    return list(pairs)


def test_it_is_close_times_volume_in_rupees() -> None:
    # 10000 paise = ₹100, times 50 shares = ₹5,000
    assert median_rupee_volume(bars((10000, 50))) == pytest.approx(5000.0)


def test_it_is_the_median_not_the_mean() -> None:
    """The fixture has to separate them, or it tests neither.

    Values ₹1,000 / ₹2,000 / ₹90,000: median ₹2,000, mean ₹31,000. One mega-day would drag a
    mean far from anything this name typically trades, which is exactly why §4.1 asks for a
    median.
    """
    series = bars((10000, 10), (10000, 20), (10000, 900))
    assert median_rupee_volume(series) == pytest.approx(2000.0)
    assert median_rupee_volume(series) != pytest.approx(31000.0)


def test_an_even_count_takes_the_midpoint() -> None:
    assert median_rupee_volume(bars((10000, 10), (10000, 20))) == pytest.approx(1500.0)


def test_a_zero_volume_day_counts_and_drags_the_median_down() -> None:
    """The property that separates this from Amihud.

    Three sessions where one had no trades at all. Counted, the median is the middle of
    {0, 1000, 2000} = ₹1,000. Dropped, it would be the middle of {1000, 2000} = ₹1,500 — a name
    that failed to trade for a third of the window would look HALF AGAIN as liquid as it is.
    """
    with_a_dead_day = bars((10000, 0), (10000, 10), (10000, 20))
    assert median_rupee_volume(with_a_dead_day) == pytest.approx(1000.0)
    assert median_rupee_volume(with_a_dead_day) != pytest.approx(1500.0)


def test_a_name_that_never_traded_is_zero_not_nan() -> None:
    """Zero is the truth here, and it is the LEAST liquid reading rather than the most.

    Opposite of `amihud_ratio`, where zero would mean perfectly liquid and NaN is the honest
    answer. `log(0)` is what `_usable` refuses downstream, so the name still leaves the ranking
    — but for having traded nothing, which is a fact, not for want of data.
    """
    assert median_rupee_volume(bars((10000, 0), (10000, 0))) == 0.0


def test_no_sessions_at_all_is_nan() -> None:
    """No observations is not the same as observing nothing traded."""
    assert math.isnan(median_rupee_volume([]))


def test_a_non_positive_price_is_refused_rather_than_multiplied() -> None:
    """A zero or negative close is a broken bar, not a quiet session.

    QC quarantines these upstream; if one reaches here it must not silently contribute ₹0 and be
    mistaken for a day with no trades, which is a different and legitimate thing.
    """
    with pytest.raises(ValueError, match="close"):
        median_rupee_volume(bars((0, 10)))
    with pytest.raises(ValueError, match="close"):
        median_rupee_volume(bars((-100, 10)))


def test_a_negative_volume_is_refused() -> None:
    with pytest.raises(ValueError, match="volume"):
        median_rupee_volume(bars((10000, -5)))
