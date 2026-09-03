"""`effective_rank`, on its own terms  (§3.6, rule 4).

M_erank is the denominator of the DSR's optimistic bracket, and the direction of its errors is
the whole reason it needs its own tests: **understating the number of trials RAISES the deflated
Sharpe**. Every mistake here flatters the result, which is the direction nobody notices.

Exercised until now only through the search suites, which reach it with realistic matrices and
therefore never with a degenerate one.
"""

from __future__ import annotations

import numpy as np
import pytest

from pips.search.multiplicity import effective_rank


def test_no_trials_is_refused_rather_than_counted_as_one() -> None:
    """An empty search is not a search with one trial in it.

    Without the guard the zero-column matrix falls through to the single-trial floor and reports
    **1.0** — one trial's worth of multiplicity, from none. A DSR deflated against one trial
    when none were run is the most flattering number this function can produce, and it looks
    exactly like the ordinary case.
    """
    with pytest.raises(ValueError, match="no trials"):
        effective_rank(np.zeros((10, 0)))


def test_a_series_that_is_not_a_matrix_is_refused_by_name() -> None:
    """One trial's returns, handed over without the second axis.

    A plausible call, and without the guard it is an `IndexError` on `.shape[1]` from inside a
    multiplicity calculation — a traceback that names neither the argument nor what was wrong
    with it.
    """
    with pytest.raises(ValueError, match="observations x trials"):
        effective_rank(np.array([0.1, -0.2, 0.3]))


def test_identical_trials_count_as_one() -> None:
    """The property M_erank exists for: ten copies of one idea are one idea.

    Rule 4 counts every trial that was viewed; the effective count asks how many INDEPENDENT
    ones there were. Perfectly correlated columns share every eigenvalue with each other, so
    `(Σλ)²/Σλ²` collapses to 1.
    """
    one = np.array([0.1, -0.2, 0.3, 0.05, -0.15, 0.22, -0.08, 0.11])
    assert effective_rank(np.column_stack([one] * 10)) == pytest.approx(1.0, abs=1e-9)


def test_independent_trials_count_as_themselves() -> None:
    """And the other end: uncorrelated columns approach their own number.

    Not asserted exactly — finite samples correlate a little by chance, so the effective rank of
    four independent trials sits just under four rather than at it. The bound is what matters:
    it must be far above the collapsed case and no more than the literal count.
    """
    rng = np.random.default_rng(20260903)
    independent = rng.normal(size=(400, 4))
    erank = effective_rank(independent)
    assert 3.0 < erank <= 4.0, erank


def test_a_trial_that_never_traded_neither_helps_nor_hurts() -> None:
    """A constant column carries no information and shares none.

    Left in, it makes `np.corrcoef` produce a row and column of NaN, which poisons the
    eigenvalues for every *other* trial — so the count would be wrong for the trials that did
    trade, not merely for the one that did not.
    """
    rng = np.random.default_rng(7)
    real = rng.normal(size=(200, 3))
    with_dud = np.column_stack([real, np.zeros(200)])

    assert effective_rank(with_dud) == pytest.approx(effective_rank(real), abs=1e-9)
    assert not np.isnan(effective_rank(with_dud))
