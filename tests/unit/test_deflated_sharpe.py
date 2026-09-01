"""PSR and the Deflated Sharpe Ratio  (§6 M18, §3.6).

§6 M18 names one trap in its own text — *"kurtosis convention: γ₄ raw; excess+... guard in
code"* — and it is worth being precise about why that is the thing it names.

The PSR denominator contains ``(γ₄ - 1)/4 · SR²``. With a NORMAL return series the raw
kurtosis γ₄ is **3**; almost every library (numpy's `kurtosis` via scipy, pandas `.kurt()`)
returns **excess** kurtosis, which is 0 for the same series. Substitute 0 for 3 and the
denominator shrinks, the statistic inflates, and the PSR comes out **higher** — a
better-looking result from a units mistake, with nothing in the output to show for it.

So the guard is mathematical rather than heuristic: **γ₄ ≥ 1 + γ₃²** holds for every
distribution that has the moments. A value below that bound is not a raw kurtosis, and the only
plausible way to produce one is to pass excess kurtosis. It is refused, and the message says
so.

The DSR is the PSR evaluated against the Sharpe you would expect the BEST of N trials to show
under a true null — §3.6's answer to "we looked at many". Two properties keep it honest:
deflation can only ever lower the number, and it is evaluated as a BRACKET at
``N = M_erank`` and ``N = M`` (`search/multiplicity.py`), because neither end is the truth.
"""

from __future__ import annotations

import math

import pytest

from pips.validation.deflated_sharpe import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    normal_cdf,
    normal_ppf,
    probabilistic_sharpe_ratio,
)

NORMAL_KURTOSIS = 3.0


# ------------------------------------------------------- the kurtosis guard ------------


def test_excess_kurtosis_passed_as_raw_is_refused() -> None:
    """The mistake §6 M18 names, and it flatters.

    A normal series has raw γ₄ = 3 and excess γ₄ = 0. Substituting 0 shrinks the PSR
    denominator and raises the statistic — a better result from a units error, invisible in
    the output.
    """
    with pytest.raises(ValueError, match="kurtosis"):
        probabilistic_sharpe_ratio(sharpe=0.5, n=250, skew=0.0, kurtosis=0.0)


def test_the_bound_is_the_mathematical_one_not_a_guess() -> None:
    """γ₄ ≥ 1 + γ₃² holds for every distribution with the moments.

    A skewed series legitimately has kurtosis above 1, so a flat "must be ≥ 3" rule would
    reject real data. The bound moves with the skew because the mathematics does.
    """
    # Skew 2 requires kurtosis of at least 5; 4.9 is impossible, 5.1 is fine.
    with pytest.raises(ValueError, match="kurtosis"):
        probabilistic_sharpe_ratio(sharpe=0.5, n=250, skew=2.0, kurtosis=4.9)
    assert probabilistic_sharpe_ratio(sharpe=0.5, n=250, skew=2.0, kurtosis=5.1) > 0


def test_a_normal_series_kurtosis_is_accepted() -> None:
    assert 0 < probabilistic_sharpe_ratio(sharpe=0.5, n=250, skew=0.0, kurtosis=3.0) < 1


# ------------------------------------------------------- PSR behaviour -----------------


def test_the_normal_case_reduces_to_los_closed_form() -> None:
    """With γ₃ = 0 and γ₄ = 3 the denominator is √(1 + SR²/2) — Lo (2002).

    My first version of this golden asserted the denominator was 1, i.e. PSR = Φ(SR·√(n-1)).
    That is wrong, and the implementation was right: substituting γ₄ = 3 leaves
    (γ₄ - 1)/4 · SR² = SR²/2, which is exactly Lo's variance for the Sharpe estimator. The
    denominator can only equal 1 if γ₄ = 1, which no real distribution has.

    Pinning the correct reduction is worth more than the wrong one would have been: it now
    fixes both the kurtosis coefficient and the (n - 1) scaling.
    """
    sharpe, n = 0.4, 250
    got = probabilistic_sharpe_ratio(sharpe=sharpe, n=n, skew=0.0, kurtosis=NORMAL_KURTOSIS)
    expected = normal_cdf(sharpe * math.sqrt(n - 1) / math.sqrt(1.0 + sharpe * sharpe / 2.0))
    assert math.isclose(got, expected, rel_tol=1e-12)


def test_psr_rises_with_the_sharpe_and_with_the_sample() -> None:
    assert probabilistic_sharpe_ratio(
        sharpe=0.6, n=250, skew=0.0, kurtosis=NORMAL_KURTOSIS
    ) > probabilistic_sharpe_ratio(sharpe=0.3, n=250, skew=0.0, kurtosis=NORMAL_KURTOSIS)
    assert probabilistic_sharpe_ratio(sharpe=0.3, n=1000, skew=0.0, kurtosis=NORMAL_KURTOSIS) > (
        probabilistic_sharpe_ratio(sharpe=0.3, n=100, skew=0.0, kurtosis=NORMAL_KURTOSIS)
    )


def test_negative_skew_lowers_the_psr() -> None:
    # Left-tailed returns make the same Sharpe less trustworthy, and the formula says so.
    fair = probabilistic_sharpe_ratio(sharpe=0.5, n=250, skew=0.0, kurtosis=4.0)
    ugly = probabilistic_sharpe_ratio(sharpe=0.5, n=250, skew=-1.5, kurtosis=4.0)
    assert ugly < fair


def test_a_sample_of_one_is_refused() -> None:
    with pytest.raises(ValueError, match="observations"):
        probabilistic_sharpe_ratio(sharpe=0.5, n=1, skew=0.0, kurtosis=3.0)


# ------------------------------------------------------- deflation ---------------------


def test_deflation_can_only_lower_the_probability() -> None:
    """Looking at more things cannot make one of them more believable."""
    plain = probabilistic_sharpe_ratio(sharpe=0.8, n=250, skew=0.0, kurtosis=NORMAL_KURTOSIS)
    deflated = deflated_sharpe_ratio(
        sharpe=0.8, n=250, skew=0.0, kurtosis=NORMAL_KURTOSIS, n_trials=50, sharpe_variance=1.0
    )
    assert deflated < plain


def test_more_trials_deflate_further() -> None:
    def dsr(n_trials: int) -> float:
        return deflated_sharpe_ratio(
            sharpe=0.8,
            n=250,
            skew=0.0,
            kurtosis=NORMAL_KURTOSIS,
            n_trials=n_trials,
            sharpe_variance=1.0,
        )

    assert dsr(500) < dsr(5)


def test_the_expected_max_sharpe_grows_with_the_number_of_trials() -> None:
    assert expected_max_sharpe(n_trials=1000, variance=1.0) > expected_max_sharpe(
        n_trials=10, variance=1.0
    )


def test_the_expected_max_sits_where_extreme_value_theory_says_it_should() -> None:
    """Monotonicity alone could not see a wrong first term.

    Replacing Φ⁻¹(1 - 1/N) with Φ⁻¹(1/N) flips that term's sign, but the second term is large
    enough that the SUM still increases with N — so the ordering test passed while the value
    was 0.64 instead of 3.26. A mutation showed exactly that.

    The maximum of N standard normals concentrates just below √(2 ln N), the Gumbel correction
    accounting for the gap. That is a bound from theory rather than from my own output, so it
    checks the formula rather than merely pinning it.
    """
    for n_trials in (10, 100, 1000, 10_000):
        got = expected_max_sharpe(n_trials=n_trials, variance=1.0)
        ceiling = math.sqrt(2.0 * math.log(n_trials))
        assert 0.7 * ceiling < got < ceiling, (
            f"N={n_trials}: {got:.4f} is outside (0.7·√(2 ln N), √(2 ln N)) = "
            f"({0.7 * ceiling:.4f}, {ceiling:.4f})"
        )


def test_the_expected_max_is_pinned_to_its_values() -> None:
    """A golden alongside the theory bound: the bound proves it is roughly right, this
    detects any change at all. Regenerating these needs a reason, not an edit."""
    for n_trials, expected in (
        (2, 0.519755),
        (10, 1.574598),
        (100, 2.530603),
        (1000, 3.255122),
    ):
        assert math.isclose(
            expected_max_sharpe(n_trials=n_trials, variance=1.0), expected, abs_tol=1e-6
        )


def test_the_variance_scales_the_expected_max() -> None:
    # E[max] scales with the standard deviation, so quadrupling the variance doubles it.
    one = expected_max_sharpe(n_trials=100, variance=1.0)
    four = expected_max_sharpe(n_trials=100, variance=4.0)
    assert math.isclose(four, 2.0 * one, rel_tol=1e-12)


def test_a_single_trial_deflates_by_nothing_measurable() -> None:
    # With one trial there is no selection to correct for; the benchmark must not be inflated
    # into a penalty out of nowhere.
    assert expected_max_sharpe(n_trials=1, variance=1.0) == 0.0


def test_zero_or_negative_trials_are_refused() -> None:
    for bad in (0, -3):
        with pytest.raises(ValueError, match="trials"):
            expected_max_sharpe(n_trials=bad, variance=1.0)


# ------------------------------------------------------- the normal helpers ------------


def test_the_cdf_and_its_inverse_round_trip() -> None:
    for x in (-2.5, -0.7, 0.0, 0.3, 1.9):
        assert math.isclose(normal_ppf(normal_cdf(x)), x, abs_tol=1e-9)


def test_the_cdf_matches_known_values() -> None:
    assert math.isclose(normal_cdf(0.0), 0.5, abs_tol=1e-15)
    assert math.isclose(normal_cdf(1.959963985), 0.975, abs_tol=1e-9)


def test_the_inverse_refuses_probabilities_outside_the_open_interval() -> None:
    for bad in (0.0, 1.0, -0.1, 1.2):
        with pytest.raises(ValueError, match="probability"):
            normal_ppf(bad)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "deflated-sharpe" in CHECK_REGISTRY
    resolve_check("deflated-sharpe")
