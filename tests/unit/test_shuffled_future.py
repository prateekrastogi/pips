"""Shuffled-future control (§6 M12, §7 `shuffled_future_alpha_fails_promotion`).

**What this catches, precisely:** a measurement pipeline that reports an edge where none
exists. Destroy the relationship between scores and outcomes by permuting the outcomes; if a
positive result survives, the number was never measuring the relationship in the first place.

**What it does NOT catch:** lookahead. A cheating alpha that reads tomorrow's close has a
genuinely strong in-sample relationship, so it clears a permutation test comfortably. That is
the as-of view's job and the leakage canary's job. Conflating the two would be exactly the
decorative assurance this project rejects — so the tests below assert the boundary explicitly
rather than leaving it to be assumed.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from pips.validation.nulls import shuffled_future_control


def test_a_real_relationship_survives_permutation() -> None:
    rng = np.random.default_rng(20260831)
    scores = rng.normal(size=400)
    outcomes = scores * 0.5 + rng.normal(size=400) * 0.5  # genuine, noisy relationship
    result = shuffled_future_control(scores, outcomes, n_permutations=200, seed=1)
    assert result.promotes
    assert result.p_value < Decimal("0.05")


def test_pure_noise_does_not_promote() -> None:
    rng = np.random.default_rng(7)
    result = shuffled_future_control(
        rng.normal(size=400), rng.normal(size=400), n_permutations=200, seed=1
    )
    assert not result.promotes
    assert result.p_value > Decimal("0.05")


def test_shuffling_actually_destroys_the_relationship() -> None:
    # The self-test of the measurement. If the shuffled ICs are not centred near zero, the
    # harness is misaligning scores and outcomes and every number it produces is suspect —
    # including the ones that look like failures.
    rng = np.random.default_rng(3)
    scores = rng.normal(size=600)
    outcomes = scores * 0.8 + rng.normal(size=600) * 0.2
    result = shuffled_future_control(scores, outcomes, n_permutations=300, seed=1)
    mean_shuffled = sum(result.shuffled_ics, Decimal(0)) / Decimal(len(result.shuffled_ics))
    assert abs(mean_shuffled) < Decimal("0.1"), (
        f"shuffled ICs centre on {mean_shuffled}, not ~0 — the harness is not destroying "
        "the relationship it claims to destroy"
    )


def test_it_is_deterministic_for_a_given_seed() -> None:
    rng = np.random.default_rng(11)
    scores, outcomes = rng.normal(size=200), rng.normal(size=200)
    a = shuffled_future_control(scores, outcomes, n_permutations=50, seed=42)
    b = shuffled_future_control(scores, outcomes, n_permutations=50, seed=42)
    assert a.observed_ic == b.observed_ic and a.p_value == b.p_value


def test_a_cheating_alpha_passes_this_control_and_that_is_expected() -> None:
    # The boundary, asserted rather than assumed. An alpha that reads the future has a REAL
    # in-sample relationship, so a permutation test cannot see the cheat. If someone ever
    # cites this control as leakage evidence, this test is the reason they should not.
    rng = np.random.default_rng(5)
    outcomes = rng.normal(size=300)
    cheating_scores = outcomes.copy()  # perfect foresight
    result = shuffled_future_control(cheating_scores, outcomes, n_permutations=200, seed=1)
    assert result.promotes, (
        "a permutation test cannot detect lookahead — that is the AsOf view's job"
    )
    assert result.observed_ic > Decimal("0.99")


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="length"):
        shuffled_future_control(np.zeros(10), np.zeros(9), n_permutations=10, seed=1)


def test_too_few_observations_are_refused() -> None:
    # A permutation test on a handful of points reports a p-value it has no right to.
    with pytest.raises(ValueError, match="observations"):
        shuffled_future_control(np.zeros(3), np.zeros(3), n_permutations=10, seed=1)


# ------------------------------------------------- null-search calibration (§6 M13) -----


def test_a_null_search_survives_at_approximately_q() -> None:
    """§6 M13's Verify: feature/label destruction => survivor rate ~ q.

    This is the self-test of the entire S1 statistics chain — rank IC, Newey-West t, normal
    p-value, BH step-up — run end to end on data with nothing in it. Under the complete null
    BH's FDR equals its FWER, so the fraction of SEARCHES producing at least one survivor
    should sit near q.

    If it comes out far above q the correction is too weak and S1 will promote noise. If it
    comes out near zero the chain is too conservative and will discard real alphas. Either
    way the number that matters is not any single p-value but this rate, and it is the only
    check that can see a miscalibration in the chain as a whole.
    """
    from pips.validation.nulls import null_search_calibration

    result = null_search_calibration(
        n_searches=200, n_candidates=10, n_observations=200, q=0.10, seed=1407
    )
    assert 0.04 <= result.survivor_rate <= 0.20, (
        f"survivor rate {result.survivor_rate} is not near q={result.q} — the S1 statistics "
        "chain is miscalibrated"
    )
    assert result.calibrated


def test_null_search_calibration_is_deterministic() -> None:
    from pips.validation.nulls import null_search_calibration

    kwargs = {"n_searches": 50, "n_candidates": 5, "n_observations": 120, "q": 0.10, "seed": 3}
    a = null_search_calibration(**kwargs)  # type: ignore[arg-type]
    b = null_search_calibration(**kwargs)  # type: ignore[arg-type]
    assert a.survivor_rate == b.survivor_rate


def test_a_broken_correction_is_detected_as_miscalibrated() -> None:
    # The control on the control. At q=0.9 the "correction" is barely correcting, so the
    # survivor rate must rise far above a sensible q — proving this harness can actually
    # SEE a miscalibration rather than always reporting calibrated.
    from pips.validation.nulls import null_search_calibration

    loose = null_search_calibration(
        n_searches=200, n_candidates=10, n_observations=200, q=0.90, seed=1407
    )
    tight = null_search_calibration(
        n_searches=200, n_candidates=10, n_observations=200, q=0.10, seed=1407
    )
    assert loose.survivor_rate > tight.survivor_rate * 3
