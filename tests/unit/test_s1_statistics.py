"""S1 statistics: BH-FDR, Newey-West t, half-life, monotonicity (§6 M13).

The statistics that decide what survives S1. Two of them exist specifically because the naive
alternative overstates significance:

* **Newey-West** because minute-bar IC series are autocorrelated, and an OLS t-statistic on
  autocorrelated data reports a confidence nobody has earned — §7's rejection list names
  "minute-Sharpe annualized as independent" as the same error;
* **BH-FDR within family x universe** because a family sweep is many tests, and an
  uncorrected best-of-N is the "unlimited grids branded exhaustive" line of that same list.
"""

from __future__ import annotations

import numpy as np
import pytest

from pips.validation.fdr import benjamini_hochberg
from pips.validation.stats import (
    coverage,
    ic_half_life,
    is_monotone_in_horizon,
    newey_west_t,
)

# ------------------------------------------------------------------ BH-FDR --------------


def test_bh_on_the_literature_example() -> None:
    """Benjamini & Hochberg (1995), their worked example (Needleman et al. p-values).

    All FIFTEEN values, deliberately. An earlier version of this test truncated the list to
    ten and expected four rejections — but n enters the threshold k/n*q, so dropping the
    insignificant tail makes every remaining test EASIER to reject and the correct answer
    becomes eight. The implementation was right and the test was wrong, which is worth
    recording: a multiple-testing correction quietly loosens when you stop counting the
    tests you ran.
    """
    p = [
        0.0001,
        0.0004,
        0.0019,
        0.0095,
        0.0201,
        0.0278,
        0.0298,
        0.0344,
        0.0459,
        0.3240,
        0.4262,
        0.5719,
        0.6528,
        0.7590,
        1.0000,
    ]
    rejected = benjamini_hochberg(p, q=0.05)
    assert rejected == [True, True, True, True] + [False] * 11


def test_dropping_the_insignificant_tail_loosens_the_correction() -> None:
    # The mechanism behind the bug above, pinned as a property. This is exactly the
    # "hidden/deleted trials" failure on §7's rejection list, in arithmetic form: a trial you
    # stop counting makes every other trial easier to promote.
    full = [
        0.0001,
        0.0004,
        0.0019,
        0.0095,
        0.0201,
        0.0278,
        0.0298,
        0.0344,
        0.0459,
        0.3240,
        0.4262,
        0.5719,
        0.6528,
        0.7590,
        1.0000,
    ]
    truncated = full[:10]
    assert sum(benjamini_hochberg(full, q=0.05)) == 4
    assert sum(benjamini_hochberg(truncated, q=0.05)) == 8


def test_bh_rejects_nothing_when_nothing_is_significant() -> None:
    assert benjamini_hochberg([0.4, 0.6, 0.9], q=0.05) == [False, False, False]


def test_bh_is_a_step_up_not_a_per_test_threshold() -> None:
    # The step-up property: a large p-value can still be rejected if enough smaller ones
    # clear the line. A naive "p < q" filter would reject only the first here.
    p = [0.01, 0.02, 0.03, 0.04]
    assert benjamini_hochberg(p, q=0.05) == [True, True, True, True]
    assert [x < 0.05 / 4 for x in p] == [True, False, False, False]


def test_bh_preserves_input_order() -> None:
    rejected = benjamini_hochberg([0.9, 0.0001, 0.5], q=0.05)
    assert rejected == [False, True, False]


def test_bh_refuses_an_invalid_q() -> None:
    for bad in (0.0, 1.5, -0.1):
        with pytest.raises(ValueError, match="q"):
            benjamini_hochberg([0.1], q=bad)


def test_bh_refuses_p_values_outside_the_unit_interval() -> None:
    with pytest.raises(ValueError, match="p-value"):
        benjamini_hochberg([0.1, 1.4], q=0.05)


# ------------------------------------------------------------- Newey-West ---------------


def test_newey_west_matches_ols_on_iid_data() -> None:
    rng = np.random.default_rng(20260831)
    series = rng.normal(loc=0.05, scale=1.0, size=2000)
    nw = newey_west_t(series, lags=5)
    naive = float(series.mean() / (series.std(ddof=1) / np.sqrt(series.size)))
    assert abs(nw - naive) < 0.25, f"NW {nw} vs naive {naive} on iid data"


def test_newey_west_is_smaller_than_naive_under_positive_autocorrelation() -> None:
    # The reason this statistic exists. Positive autocorrelation means fewer independent
    # observations than the sample size suggests, so the honest t is SMALLER. A pipeline
    # reporting the naive t here would claim significance it has not earned.
    rng = np.random.default_rng(7)
    noise = rng.normal(size=4000)
    series = np.zeros(4000)
    for i in range(1, 4000):
        series[i] = 0.8 * series[i - 1] + noise[i]
    series += 0.10
    nw = newey_west_t(series, lags=20)
    naive = float(series.mean() / (series.std(ddof=1) / np.sqrt(series.size)))
    assert nw < naive, f"NW {nw} should be below naive {naive} under autocorrelation"
    assert nw < naive * 0.6


def test_newey_west_needs_enough_observations() -> None:
    with pytest.raises(ValueError, match="observations"):
        newey_west_t(np.zeros(3), lags=5)


def test_newey_west_of_a_zero_mean_series_is_near_zero() -> None:
    rng = np.random.default_rng(3)
    assert abs(newey_west_t(rng.normal(size=1000), lags=5)) < 3.0


# ------------------------------------------------- horizon curve diagnostics ------------


def test_monotonicity_detects_a_decaying_curve() -> None:
    # A01's falsifier: "require monotone rank-IC". A curve that rises then falls is not the
    # decay a horizon story predicts, and the difference must be detectable.
    assert is_monotone_in_horizon([0.05, 0.04, 0.03, 0.02])
    assert not is_monotone_in_horizon([0.02, 0.05, 0.01, 0.04])


def test_monotonicity_accepts_a_flat_curve_but_not_a_hump() -> None:
    assert is_monotone_in_horizon([0.03, 0.03, 0.03])
    assert not is_monotone_in_horizon([0.01, 0.06, 0.01])


def test_half_life_of_a_decaying_ic_curve() -> None:
    # IC halves every two horizons here, so the half-life is ~2 horizon steps.
    hl = ic_half_life([0.08, 0.057, 0.04, 0.028, 0.02])
    assert hl is not None
    assert 1.5 < hl < 2.5


def test_half_life_is_undefined_for_a_non_decaying_curve() -> None:
    # Returning a number here would invent a decay rate for something that is not decaying.
    assert ic_half_life([0.02, 0.03, 0.05]) is None


def test_coverage_is_the_fraction_of_decisions_with_a_forecast() -> None:
    assert coverage(n_forecasts=750, n_opportunities=1000) == pytest.approx(0.75)
    assert coverage(n_forecasts=0, n_opportunities=0) == 0.0


def test_coverage_above_one_is_refused() -> None:
    # More forecasts than opportunities means the opportunity count is wrong, and a silently
    # clipped value would hide it.
    with pytest.raises(ValueError, match="coverage"):
        coverage(n_forecasts=10, n_opportunities=5)
