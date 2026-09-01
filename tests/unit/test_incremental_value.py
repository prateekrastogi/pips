"""Does the alpha beat its declared parent null?  [C-SPEC-01] (§6 M16, rule 5).

Three of the sixteen unbound falsifiers are one question in three costumes:

- A04: *"Reject if residualization adds no value over raw reversal"*
- A05: *"Reject if it is not distinct from market direction"*
- A08: *"Reject if direction adds no information beyond a volatility forecast"*

And every one of those baselines is already written down. Rule 5 makes each spec declare its
`null_models` before the search, and the parents are named there in so many words — *"raw
reversal without residualization — the simpler parent this must beat"*, *"market direction over
the same window"*, *"a pure volatility forecast with no direction — the parent this must beat"*.

So the check does not choose a baseline. **It requires the caller to name one the spec
pre-registered**, which is the difference between testing a claim and constructing a
comparison the alpha wins.

Three design choices:

**Paired, not two independent samples.** The alpha and the null see the same periods. Treating
them as independent discards the pairing and inflates the variance — which makes it easier to
conclude "no significant difference", i.e. easier to *reject*, but for the wrong reason, and
the same mistake would flatter in the other direction on a different dataset.

**A tie is a FAILURE.** The falsifiers say "adds no information" is grounds for rejection, so
the burden is on the alpha and equal performance rejects. A check that passed on a tie would
read the pre-registration backwards.

**Too few observations is NOT_MEASURED, not a pass** — the third outcome again.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from pips.alphas.spec import load_alpha_spec
from pips.validation.incremental_value import beats_null

SPEC_DIR = Path("config/search_spaces")
A08 = load_alpha_spec(SPEC_DIR / "A08_compression_expansion.yaml")
PARENT = "a pure volatility forecast with no direction — the parent this must beat"


def paired(alpha: list[float], null: list[float]) -> tuple[list[Decimal], list[Decimal]]:
    return ([Decimal(str(v)) for v in alpha], [Decimal(str(v)) for v in null])


def series(
    base: float, lift: float, n: int = 60, lift_noise: float = 0.003
) -> tuple[list[Decimal], list[Decimal]]:
    """A null series with structure, and an alpha adding `lift` plus its OWN noise.

    The lift must be noisy or the test is not the test. My first version added a CONSTANT
    lift, which makes the paired difference identical in every period — a perfectly consistent
    edge, which is not "a tiny lift inside the noise" but the most informative signal
    imaginable. It produced a t-statistic of 1.4e14.

    Fourth time this session a tidy arithmetic fixture has produced degenerate statistics.
    """
    null = [base + ((i * 7) % 11 - 5) * 0.002 for i in range(n)]
    alpha = [v + lift + ((i * 13) % 7 - 3) * lift_noise for i, v in enumerate(null)]
    return paired(alpha, null)


# ------------------------------------------------------------ the claim ----------------


def test_an_alpha_that_adds_real_information_beats_its_parent() -> None:
    alpha, null = series(0.01, lift=0.004)
    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05)
    assert verdict.beats
    assert verdict.mean_difference > 0


def test_an_alpha_identical_to_its_parent_does_not_beat_it() -> None:
    """A tie rejects. The falsifier's condition is "adds no information", so the burden is on
    the alpha and equal performance is exactly the case it names.

    `lift_noise=0` too: "identical" means identical. With the alpha's own noise still on, it
    is not the same series — a different (and also failing) case.
    """
    alpha, null = series(0.01, lift=0.0, lift_noise=0.0)
    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05)
    assert not verdict.beats
    assert verdict.mean_difference == 0
    assert verdict.measured is True, (
        "a tie is perfectly MEASURED — the alpha adds exactly nothing, which is the "
        "falsifier's condition met, not a failure to look. Reporting it as unmeasured would "
        "conflate 'we could not tell' with 'we could tell, and the answer is no'."
    )


def test_an_alpha_worse_than_its_parent_does_not_beat_it() -> None:
    alpha, null = series(0.01, lift=-0.004)
    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05)
    assert not verdict.beats


def test_a_tiny_lift_inside_the_noise_does_not_beat_it() -> None:
    """The case that separates a test from a comparison.

    A lift of one ten-thousandth against noise of two thousandths is not evidence, however
    consistently positive the mean happens to be. An implementation that only checked the
    SIGN of the mean difference would pass this.
    """
    alpha, null = series(0.01, lift=0.00001)
    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05)
    assert verdict.mean_difference > 0, "the mean does favour the alpha"
    assert not verdict.beats, "but not significantly, and the sign alone is not the test"


# ------------------------------------------------------------ the pre-registration -----


def test_the_null_must_be_one_the_spec_declared() -> None:
    """The heart of it. A baseline chosen now is a comparison built to be won.

    Rule 5 makes the parent a pre-registration; this refuses anything else, so the check can
    never be pointed at a weaker opponent after the results are in.
    """
    alpha, null = series(0.01, lift=0.004)
    with pytest.raises(ValueError, match=r"not one of .*null_models"):
        beats_null(A08, "a baseline I just made up", alpha, null, alpha_level=0.05)


def test_every_declared_null_is_accepted() -> None:
    # The other direction: the check must not quietly accept only the one null I tested with.
    alpha, null = series(0.01, lift=0.004)
    for declared in A08.null_models:
        assert beats_null(A08, declared, alpha, null, alpha_level=0.05) is not None


# ------------------------------------------------------------ the refusals -------------


def test_unequal_series_lengths_are_refused() -> None:
    # Unequal lengths mean the pairing is wrong, and a paired test on mispaired data is a
    # confident answer to a question nobody asked.
    alpha, null = series(0.01, lift=0.004)
    with pytest.raises(ValueError, match="paired"):
        beats_null(A08, PARENT, alpha, null[:-3], alpha_level=0.05)


def test_too_few_observations_is_not_measured_rather_than_passed() -> None:
    alpha, null = series(0.01, lift=0.004, n=4)
    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05, min_observations=20)
    assert verdict.measured is False
    assert verdict.beats is False, "not measured is not a pass"


def test_a_zero_variance_difference_is_not_infinitely_significant() -> None:
    """Every period identical: the paired difference has no dispersion.

    A t-statistic divides by that dispersion, so a constant difference is infinitely
    significant on the arithmetic and worth nothing in fact. It is treated as unmeasured.
    """
    alpha, null = paired([0.014] * 60, [0.010] * 60)  # difference constant to the digit
    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05)
    assert verdict.measured is False
    assert not verdict.beats


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "beats-declared-null" in CHECK_REGISTRY
    resolve_check("beats-declared-null")


def test_a_constant_non_zero_difference_is_unassessable_not_a_tie() -> None:
    """The other half of the same branch, and it is a different answer.

    A difference of exactly 0.004 every period has no dispersion to judge it against, so its
    significance cannot be assessed — unlike a difference of exactly zero, which is assessed
    completely. Sharing a code path is fine; sharing an answer is not.
    """
    alpha, null = paired([0.014] * 60, [0.010] * 60)
    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05)
    assert verdict.measured is False
    assert not verdict.beats
    assert verdict.mean_difference > 0, "it does favour the alpha — and that is not enough"


def test_decimal_residue_is_not_mistaken_for_dispersion() -> None:
    """The guard that `variance <= 0` misses.

    These differences are constant to any meaningful precision but not to all 28 of Decimal's
    digits, so the variance is around 1e-33 rather than 0. Dividing by that reports a
    t-statistic of order 1e14 — a perfectly consistent tiny edge, which no real series
    produces. A mutation replacing the epsilon with `<= 0` survived until this test existed.
    """
    # Built through float -> str -> Decimal, which is how the real fixture produced it: the
    # str() rounds to 17 significant digits, so a "constant" lift lands on two distinct
    # Decimal values. Pure Decimal arithmetic would be exact and variance would be zero,
    # which `variance <= 0` also catches — my first version of this test did that and the
    # mutation survived it.
    null_floats = [0.01 + ((i * 7) % 11 - 5) * 0.002 for i in range(60)]
    alpha = [Decimal(str(v + 0.00001)) for v in null_floats]
    null = [Decimal(str(v)) for v in null_floats]

    differences = {a - n for a, n in zip(alpha, null, strict=True)}
    assert len(differences) > 1, "the fixture must actually carry residue"

    verdict = beats_null(A08, PARENT, alpha, null, alpha_level=0.05)
    assert verdict.measured is False
    assert not verdict.beats, "5.6e-19 of dispersion is residue, not evidence"
