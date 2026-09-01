"""Hierarchical partial pooling for family means  (§6 M18).

Nine alpha families, each with a handful of configs. What is family F5's mean performance?

**No pooling** takes each family's own sample mean, which on small samples is mostly noise —
and the best-looking family is then the luckiest one, which is the multiplicity error wearing
a new hat. **Complete pooling** uses one grand mean for everyone, which throws away every real
difference between families. Partial pooling asks how much of the observed spread between
families is *real*, and shrinks each family toward the grand mean by exactly that much.

Same estimator as A12's slot shrinkage, one level up: the weight is
``tau^2 / (tau^2 + sigma^2/n)``, so a family with few observations or noisy ones barely moves
off the grand mean while a family with many consistent ones keeps most of its own.

**The trap is a negative variance estimate.** ``tau^2`` is estimated by method of moments —
the observed spread of family means, minus what within-family noise alone would produce. That
subtraction can go NEGATIVE when the families really are alike, and a negative ``tau^2`` gives
a negative weight, which pushes each family AWAY from the grand mean. Anti-shrinkage: the exact
inverse of the correction, arrived at silently, and it looks like a stronger result. It is
floored at zero, which is complete pooling — the right answer when nothing separates the
families.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.partial_pooling import partial_pool


def family(mean: str, n: int, noise: str = "0.002", offset: int = 0) -> list[Decimal]:
    """`n` observations around `mean`, with deterministic irregular noise.

    Coprime multipliers: `(a·t) % m` cycles through only `m / gcd(a, m)` values, and a shared
    factor turns the "noise" into a short staircase with a mean of its own.
    """
    return [
        Decimal(mean) + Decimal(((t * 37 + offset * 53) % 101) - 50) * Decimal(noise) / 50
        for t in range(n)
    ]


# ------------------------------------------------------------ the mechanism ------------


def test_a_family_with_fewer_observations_is_shrunk_harder() -> None:
    families = {
        "many": family("0.010", n=200, offset=1),
        "few": family("0.010", n=8, offset=2),
        "other": family("0.002", n=200, offset=3),
    }
    result = partial_pool(families)
    assert result.estimates["few"].weight < result.estimates["many"].weight


def test_every_estimate_lies_between_its_own_mean_and_the_grand_mean() -> None:
    """Shrinkage moves toward the grand mean and never past it.

    Overshooting would be a sign error in the weight, and the result would still look like a
    plausible set of family means.
    """
    families = {
        "a": family("0.010", n=40, offset=1),
        "b": family("0.002", n=40, offset=2),
        "c": family("-0.004", n=40, offset=3),
    }
    result = partial_pool(families)
    for estimate in result.estimates.values():
        low, high = sorted((estimate.raw_mean, result.grand_mean))
        assert low <= estimate.shrunk_mean <= high, estimate


def test_the_ordering_of_families_is_preserved() -> None:
    families = {
        "a": family("0.010", n=40, offset=1),
        "b": family("0.002", n=40, offset=2),
        "c": family("-0.004", n=40, offset=3),
    }
    result = partial_pool(families)
    by_raw = sorted(result.estimates, key=lambda k: result.estimates[k].raw_mean)
    by_shrunk = sorted(result.estimates, key=lambda k: result.estimates[k].shrunk_mean)
    assert by_raw == by_shrunk


# ------------------------------------------------------------ the two limits -----------


def test_families_that_differ_hugely_barely_shrink() -> None:
    # Real separation, low noise: the data says the families differ, so keep their means.
    families = {
        "high": family("0.100", n=200, noise="0.0005", offset=1),
        "low": family("-0.100", n=200, noise="0.0005", offset=2),
    }
    result = partial_pool(families)
    assert all(e.weight > 0.99 for e in result.estimates.values())


def test_families_that_differ_only_by_noise_are_shrunk_hard() -> None:
    """Nothing real separates them, so the honest estimate for each is close to everyone's."""
    families = {name: family("0.005", n=50, offset=i) for i, name in enumerate("abcd")}
    result = partial_pool(families)
    for estimate in result.estimates.values():
        assert estimate.weight < Decimal("0.2"), estimate
        assert abs(estimate.shrunk_mean - result.grand_mean) < Decimal("0.002"), estimate


# ------------------------------------------------------------ the trap -----------------


def test_a_negative_between_family_variance_is_floored_not_used() -> None:
    """The trap, and it fails in the flattering direction.

    The method-of-moments estimate of tau^2 subtracts the within-family noise contribution
    from the observed spread of family means, and that goes NEGATIVE when the families really
    are alike. A negative tau^2 gives a negative weight, which pushes each family AWAY from
    the grand mean — anti-shrinkage, the exact inverse of the correction, and it makes the
    spread between families look larger than the data supports.

    Floored at zero it becomes complete pooling, which is the right answer when nothing
    separates them.

    Constructed so the negative is guaranteed rather than arrived at near a boundary: each
    family is a PERMUTATION of one shared set of values, so every family mean is exactly equal
    (observed spread exactly 0) while within-family variance stays large. The raw estimate is
    then ``0 - sigma^2/n``, strictly negative by construction.
    """
    values = [Decimal(v) for v in ("-0.030", "-0.010", "0.005", "0.020", "0.035", "0.050")]
    families = {name: values[i:] + values[:i] for i, name in enumerate("abcde")}
    result = partial_pool(families)

    assert result.between_variance_raw < 0, "the fixture must exercise the floor"
    assert result.between_variance == 0
    for estimate in result.estimates.values():
        assert estimate.weight == 0
        assert estimate.shrunk_mean == result.grand_mean


def test_no_estimate_is_ever_pushed_away_from_the_grand_mean() -> None:
    # The general form of the same guarantee, over a range of shapes.
    for noise in ("0.001", "0.01", "0.05"):
        for n in (5, 20, 100):
            families = {
                name: family("0.005", n=n, noise=noise, offset=i) for i, name in enumerate("abcd")
            }
            result = partial_pool(families)
            for estimate in result.estimates.values():
                assert abs(estimate.shrunk_mean - result.grand_mean) <= abs(
                    estimate.raw_mean - result.grand_mean
                ) + Decimal("1e-12"), (noise, n, estimate)


# ------------------------------------------------------------ refusals -----------------


def test_a_single_family_cannot_be_pooled() -> None:
    """With one family there is no between-family variance to estimate.

    Falling back to "no shrinkage" would report the raw mean as though it had been pooled,
    which is a stronger claim than the data supports and indistinguishable in the output.
    """
    with pytest.raises(ValueError, match="at least 2 families"):
        partial_pool({"only": family("0.01", n=50)})


def test_a_family_with_too_few_observations_is_refused() -> None:
    # One observation has no within-family variance, so sigma^2 cannot be estimated from it
    # and the family would silently borrow everyone else's.
    with pytest.raises(ValueError, match="observations"):
        partial_pool({"a": family("0.01", n=50), "tiny": family("0.02", n=1)})


def test_an_empty_input_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 2 families"):
        partial_pool({})


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "partial-pooling" in CHECK_REGISTRY
    resolve_check("partial-pooling")


# ------------------------------------------------------------ exact arithmetic ---------
#
# The tests above assert relationships (this weight is smaller, this ordering holds), and a
# mutation run showed six of them are satisfiable by a wrong implementation: the divisors, the
# choice of centre, and the direction of the shrinkage all survived being broken. Relationships
# constrain the shape of the answer. These constrain the answer.


def test_the_arithmetic_is_exact_on_a_hand_computed_case() -> None:
    """Two families, four numbers, every intermediate checkable by hand.

    a=[0,2] -> mean 1, b=[4,6] -> mean 5, grand 3.
    within  = (2 + 2) / (1 + 1) = 2          <- pooled, divisor sum(n_j - 1)
    observed= ((1-3)^2 + (5-3)^2) / (2 - 1) = 8   <- divisor J - 1
    noise   = mean(2/2, 2/2) = 1
    tau^2   = 8 - 1 = 7 ;  weight = 7 / 8 = 0.875
    shrunk  = 0.875*1 + 0.125*3 = 1.25  and  0.875*5 + 0.125*3 = 4.75
    """
    result = partial_pool(
        {
            "a": [Decimal(0), Decimal(2)],
            "b": [Decimal(4), Decimal(6)],
        }
    )
    assert result.grand_mean == Decimal(3)
    assert result.within_variance == Decimal(2)
    assert result.between_variance_raw == Decimal(7)
    assert result.estimates["a"].weight == Decimal("0.875")
    assert result.estimates["a"].shrunk_mean == Decimal("1.25")
    assert result.estimates["b"].shrunk_mean == Decimal("4.75")


def test_a_confidently_separated_family_keeps_its_own_mean() -> None:
    """Weight near 1 must mean the family KEEPS its mean, not that it moves to the grand one.

    Asserting the weight alone leaves the direction of the combination untested, and a swapped
    weight is still a convex combination — it stays between the two means and preserves the
    ordering, so every relational test above passes while every number is wrong.
    """
    families = {
        "high": family("0.100", n=200, noise="0.0005", offset=1),
        "low": family("-0.100", n=200, noise="0.0005", offset=2),
    }
    result = partial_pool(families)
    for estimate in result.estimates.values():
        assert abs(estimate.shrunk_mean - estimate.raw_mean) < Decimal("0.001"), estimate
        assert abs(estimate.shrunk_mean - result.grand_mean) > Decimal("0.09"), estimate


def test_the_centre_is_unweighted_so_a_large_family_cannot_drag_it() -> None:
    """The design decision, stated in the module docstring and otherwise untested.

    'big' has four observations and 'small' two. The unweighted centre is 5; pooling all six
    observations instead gives 6.67, dragged two thirds of the way to the larger family. That
    is the path by which one big family's luck becomes contagious: every smaller family gets
    shrunk toward it.
    """
    result = partial_pool(
        {
            "big": [Decimal(9), Decimal(11), Decimal(9), Decimal(11)],
            "small": [Decimal(-1), Decimal(1)],
        }
    )
    assert result.grand_mean == Decimal(5)


def test_families_that_are_constant_and_identical_do_not_divide_by_zero() -> None:
    # Both variances are zero, so the weight's denominator is zero. Reachable with real data:
    # every config in every family reporting the same number is a degenerate run, not an
    # impossible one, and it should report that rather than raise ZeroDivisionError.
    result = partial_pool({"a": [Decimal(3), Decimal(3)], "b": [Decimal(3), Decimal(3)]})
    for estimate in result.estimates.values():
        assert estimate.weight == 0
        assert estimate.shrunk_mean == Decimal(3)


def test_the_noise_term_is_averaged_across_families_not_taken_at_its_worst() -> None:
    """An unbalanced design, which is the only shape that can tell the two apart.

    ``sigma^2/n_j`` differs between families only when their sample sizes do, so every balanced
    fixture above is blind to how the per-family noise terms are combined. Taking the worst one
    instead of the average over-subtracts, understating how much the families really differ and
    shrinking everything harder than the data warrants — conservative, but not the estimator,
    and silently so.

    big=[9,11,9,11] -> mean 10, small=[-1,1] -> mean 0, grand 5.
    within = (4 + 2) / (3 + 1) = 1.5 ;  observed = ((10-5)^2 + (0-5)^2) / 1 = 50
    noise  = mean(1.5/4, 1.5/2) = 0.5625   ->  tau^2 = 49.4375
             max (1.5/4, 1.5/2) = 0.75     ->  tau^2 = 49.25
    """
    result = partial_pool(
        {
            "big": [Decimal(9), Decimal(11), Decimal(9), Decimal(11)],
            "small": [Decimal(-1), Decimal(1)],
        }
    )
    assert result.within_variance == Decimal("1.5")
    assert result.between_variance_raw == Decimal("49.4375")
