"""Stationary bootstrap  (§6 M18, day/week blocks).

A bootstrap that resamples single observations destroys serial dependence — and serial
dependence is most of what makes a trading return series hard. Resample it away and every
confidence interval comes out too narrow, which is to say every result looks more significant
than it is.

The stationary bootstrap (Politis & Romano) resamples BLOCKS of random geometric length, so
runs survive. Two details do the work:

**It wraps.** The series is treated as a circle, which is what "stationary" refers to: without
wrapping, observations near the end can only ever appear at the end of a block, and the tail of
the sample is systematically under-represented.

**Blocks are geometric, not fixed.** A fixed block length imposes a period on the resample and
leaves a signature at that frequency. Random lengths with the right mean do not.

**The test that matters is the one an IID bootstrap fails.** Everything structural here — right
length, valid indices, reproducible under a seed — is equally true of resampling single
observations. If the suite does not measure whether dependence SURVIVED, it passes for the
bootstrap this one exists to replace.
"""

from __future__ import annotations

import statistics
from decimal import Decimal

import pytest

from pips.validation.bootstrap import bootstrap_indices, stationary_bootstrap


def ar1(n: int = 400, phi: float = 0.9) -> list[Decimal]:
    """A strongly autocorrelated series, deterministic so the tests are exact."""
    out: list[Decimal] = []
    value = 0.0
    for t in range(n):
        shock = ((t * 7919) % 1000 - 500) / 10_000.0
        value = phi * value + shock
        out.append(Decimal(str(round(value, 8))))
    return out


def lag1_autocorrelation(series: list[Decimal]) -> float:
    values = [float(v) for v in series]
    mean = statistics.fmean(values)
    numerator = sum((values[i] - mean) * (values[i - 1] - mean) for i in range(1, len(values)))
    denominator = sum((v - mean) ** 2 for v in values)
    return numerator / denominator if denominator else 0.0


# ------------------------------------------- the test an IID bootstrap fails ------------


def test_block_resampling_preserves_serial_dependence() -> None:
    """The whole reason this exists, and the only test an IID bootstrap cannot pass.

    An AR(1) with phi 0.9 has strong lag-1 autocorrelation. Resampled in blocks averaging 20
    observations, most of it survives; resampled one observation at a time (mean block length
    1, which IS the IID bootstrap) it is destroyed.
    """
    series = ar1()
    original = lag1_autocorrelation(series)
    assert original > 0.7, f"the fixture must actually be autocorrelated, got {original}"

    blocked = [
        lag1_autocorrelation(r)
        for r in stationary_bootstrap(series, n_resamples=20, mean_block_length=20, seed=7)
    ]
    iid = [
        lag1_autocorrelation(r)
        for r in stationary_bootstrap(series, n_resamples=20, mean_block_length=1, seed=7)
    ]

    assert statistics.fmean(blocked) > 0.5, "block resampling must keep most of the dependence"
    assert statistics.fmean(iid) < 0.2, "single-observation resampling must destroy it"
    assert statistics.fmean(blocked) > statistics.fmean(iid) + 0.3


# ------------------------------------------------------------ wrapping -----------------


def test_the_series_is_treated_as_a_circle() -> None:
    """Without wrapping, the tail is systematically under-represented.

    A block starting near the end would have to stop there, so late observations could only
    ever appear at a block's end — a bias in the resample that has nothing to do with the
    data.
    """
    # With a mean block of 10,000 the jump probability is 1e-4, so ten steps is one unbroken
    # walk. On a circle that visits every index exactly once, whatever the start. Clamped at
    # the end instead, it would stall on the last index and repeat it.
    #
    # My first version asserted `wrapped or indices[0] != 0`, and that escape clause is true
    # for nine starts out of ten — a mutation removing the wrap survived it.
    for seed in range(6):
        indices = bootstrap_indices(n=10, mean_block_length=10_000, seed=seed)
        assert sorted(indices) == list(range(10)), (
            f"seed {seed}: an unbroken walk on a circle visits every index once, got {indices}"
        )


def test_every_index_is_inside_the_series() -> None:
    for index in bootstrap_indices(n=50, mean_block_length=10, seed=11):
        assert 0 <= index < 50


def test_the_resample_is_the_same_length_as_the_original() -> None:
    series = ar1(n=120)
    for resample in stationary_bootstrap(series, n_resamples=5, mean_block_length=10, seed=1):
        assert len(resample) == 120


# ------------------------------------------------------------ determinism --------------


def test_the_same_seed_reproduces_the_same_resamples() -> None:
    # Rule 1. A bootstrap that moves between runs cannot anchor a confidence interval to
    # anything, and no result computed from it is reproducible.
    series = ar1(n=100)
    first = stationary_bootstrap(series, n_resamples=4, mean_block_length=8, seed=42)
    second = stationary_bootstrap(series, n_resamples=4, mean_block_length=8, seed=42)
    assert first == second


def test_different_seeds_give_different_resamples() -> None:
    # The control: identical output for every seed would also satisfy the test above.
    series = ar1(n=100)
    a = stationary_bootstrap(series, n_resamples=4, mean_block_length=8, seed=1)
    b = stationary_bootstrap(series, n_resamples=4, mean_block_length=8, seed=2)
    assert a != b


def test_no_global_random_state_is_touched() -> None:
    """Seeding the global RNG must not change the answer, and vice versa.

    A bootstrap reading `random.random()` is reproducible only until something else in the
    process draws a number — which is a determinism guarantee that holds right up until it
    matters.
    """
    import random

    series = ar1(n=80)
    random.seed(1)
    first = stationary_bootstrap(series, n_resamples=3, mean_block_length=6, seed=5)
    random.seed(999)
    [random.random() for _ in range(50)]
    second = stationary_bootstrap(series, n_resamples=3, mean_block_length=6, seed=5)
    assert first == second


# ------------------------------------------------------------ shape --------------------


def test_the_mean_block_length_is_about_what_was_asked_for() -> None:
    # Geometric blocks with mean L: the observed mean run length should land near L.
    indices = bootstrap_indices(n=2000, mean_block_length=10, seed=4)
    runs, current = [], 1
    for i in range(1, len(indices)):
        if indices[i] == (indices[i - 1] + 1) % 2000:
            current += 1
        else:
            runs.append(current)
            current = 1
    runs.append(current)
    assert 7.0 < statistics.fmean(runs) < 14.0, statistics.fmean(runs)


def test_a_block_length_below_one_is_refused() -> None:
    for bad in (0, -3):
        with pytest.raises(ValueError, match="block length"):
            bootstrap_indices(n=50, mean_block_length=bad, seed=1)


def test_an_empty_series_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        stationary_bootstrap([], n_resamples=3, mean_block_length=5, seed=1)


def test_zero_resamples_is_refused() -> None:
    # An empty set of resamples yields an empty confidence interval, which reads as a result.
    with pytest.raises(ValueError, match="resamples"):
        stationary_bootstrap(ar1(n=50), n_resamples=0, mean_block_length=5, seed=1)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "stationary-bootstrap" in CHECK_REGISTRY
    resolve_check("stationary-bootstrap")


def test_longer_blocks_preserve_more_dependence() -> None:
    """A monotone relationship is a stronger claim than any single threshold.

    The original AR(1) has lag-1 autocorrelation 0.83. Resampled, the recovered dependence
    climbs toward it with the block length and collapses to zero at length 1:

        block   1 -> -0.008   (the IID bootstrap; dependence destroyed)
        block   5 ->  0.649
        block  20 ->  0.782
        block  50 ->  0.804   (approaching the original 0.827)

    A single "> 0.5" assertion passes for an implementation whose block length does nothing.
    """
    series = ar1()
    recovered = [
        statistics.fmean(
            lag1_autocorrelation(r)
            for r in stationary_bootstrap(series, n_resamples=20, mean_block_length=L, seed=7)
        )
        for L in (1, 5, 20, 50)
    ]
    assert recovered == sorted(recovered), f"not monotone in block length: {recovered}"
    assert recovered[0] < 0.05, "length 1 is the IID bootstrap and must destroy dependence"
    assert recovered[-1] < lag1_autocorrelation(series), (
        "resampling cannot manufacture MORE dependence than the series had"
    )


def test_the_resamples_within_one_call_are_not_all_identical() -> None:
    """A bootstrap returning N copies of one resample gives a ZERO-WIDTH interval.

    That is the most extreme version of the failure this whole module exists to prevent —
    an interval too narrow, and hence a result too significant. Nothing else here caught it:
    "same seed reproduces" and "different seeds differ" are both satisfied by a function that
    derives every resample in a call from the same seed. A mutation doing exactly that
    survived until this test existed.
    """
    resamples = stationary_bootstrap(ar1(n=100), n_resamples=10, mean_block_length=8, seed=3)
    distinct = {tuple(r) for r in resamples}
    assert len(distinct) > 1, "every resample is identical; the interval would have no width"
    assert len(distinct) >= 8, f"only {len(distinct)} distinct resamples out of 10"
