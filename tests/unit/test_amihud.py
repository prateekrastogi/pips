"""Amihud (2002) illiquidity, ported from `../past` under rule 13 (`SAL-0015`).

DONOR: convexity `c13fccaf3dfa`, `src/convexity/cost/friction/spread_impact.py::amihud_ratio`.
`salvage.yaml` records SAL-0015 as PORT for M7's liquidity score, and SAL-0013's note — which
downgraded the surrounding friction model to SKIP because its impact anchor was calibrated on a
crypto book — is explicit that the `amihud_ratio` *shape* still corroborates SAL-0015. So the
measure is taken and the calibration is not.

    Amihud_i = (1/D) * sum_d |r_i,d| / Vol_i,d

The donor's two judgements are the ones worth keeping, and both are tested below because both are
the kind of thing a rewrite silently gets wrong:

* a day with non-positive or non-finite volume is **dropped from the mean**, not divided into and
  not counted as zero;
* a name with no valid day is **NaN**, which `_usable` already refuses, rather than a number.

Per-symbol rather than the donor's (D, n_sym) matrix: `SymbolStats` is per-symbol, and a matrix
API here would exist only to be sliced apart again.
"""

from __future__ import annotations

import math

import pytest

from pips.universe.liquidity import SymbolStats, amihud_ratio, liquidity_scores


def test_it_is_the_mean_of_absolute_return_per_rupee_of_volume() -> None:
    # |r|/v over three days: 0.02/100 = 2e-4, 0.01/50 = 2e-4, 0.03/300 = 1e-4
    got = amihud_ratio([0.02, -0.01, 0.03], [100.0, 50.0, 300.0])
    assert got == pytest.approx((2e-4 + 2e-4 + 1e-4) / 3)


def test_the_sign_of_the_return_does_not_matter() -> None:
    """It is |r|: a name that fell 2% is exactly as illiquid as one that rose 2%."""
    assert amihud_ratio([-0.02], [100.0]) == amihud_ratio([0.02], [100.0])


@pytest.mark.parametrize("bad_volume", [0.0, -5.0, float("nan"), float("inf")])
def test_a_day_without_usable_volume_is_dropped_not_divided_into(bad_volume: float) -> None:
    """No division by zero, and no infinity smuggled into the mean."""
    got = amihud_ratio([0.02, 0.01], [100.0, bad_volume])
    assert got == pytest.approx(0.02 / 100.0), "the bad day should leave no trace"
    assert math.isfinite(got)


def test_dropping_a_day_is_not_the_same_as_counting_it_as_zero() -> None:
    """The fixture has to tell the two apart, or it tests nothing.

    Counting the untraded day as a zero contribution would divide by 2 instead of 1 and halve
    the answer. Both are finite and plausible; only one is right.
    """
    dropped = amihud_ratio([0.02, 0.01], [100.0, 0.0])
    counted_as_zero = (0.02 / 100.0 + 0.0) / 2
    assert dropped == pytest.approx(0.02 / 100.0)
    assert dropped != pytest.approx(counted_as_zero)


def test_a_non_finite_return_is_dropped_too() -> None:
    assert amihud_ratio([0.02, float("nan")], [100.0, 100.0]) == pytest.approx(2e-4)


def test_a_name_with_no_usable_day_is_nan_rather_than_a_number() -> None:
    """NaN, not 0.0. A zero Amihud is the MOST liquid name there is."""
    got = amihud_ratio([0.02, 0.01], [0.0, -1.0])
    assert math.isnan(got)


def test_that_nan_is_refused_by_the_score_rather_than_ranked() -> None:
    """The end-to-end reason NaN is the right answer: `_usable` already declines it."""
    unmeasurable = SymbolStats("NODATA", 1e7, 0.001, amihud_ratio([0.02], [0.0]), 0.01)
    ordinary = SymbolStats("FINE", 1e7, 0.001, 2e-4, 0.01)
    other = SymbolStats("ALSOFINE", 2e7, 0.002, 3e-4, 0.02)
    scores = liquidity_scores([unmeasurable, ordinary, other])
    assert "NODATA" not in scores
    assert {"FINE", "ALSOFINE"} <= set(scores)


def test_empty_input_is_nan_not_an_error() -> None:
    assert math.isnan(amihud_ratio([], []))


def test_misaligned_inputs_are_refused() -> None:
    """The donor raises rather than zipping to the shorter one, which would silently drop days."""
    with pytest.raises(ValueError, match="aligned"):
        amihud_ratio([0.02, 0.01], [100.0])
