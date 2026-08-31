"""Null models and the shuffled-future control (§6 M12, §7).

**What the control catches:** a measurement pipeline that reports an edge where none exists.
Permute the outcomes so no relationship can remain, recompute the statistic, and compare. If a
positive result survives permutation, the number was never measuring the relationship.

**What it does not catch:** lookahead. An alpha that reads tomorrow's close has a genuinely
strong in-sample relationship and clears a permutation test comfortably. Leakage is the as-of
view's job (it refuses the read) and the canary's job (it proves the refusal works). Citing
this control as leakage evidence would be a category error, and
``tests/unit/test_shuffled_future.py`` asserts that boundary so nobody has to take it on faith.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np

from pips.validation.fdr import benjamini_hochberg
from pips.validation.stats import newey_west_t, two_sided_t_p_value

__all__ = [
    "NullSearchCalibration",
    "ShuffledFutureResult",
    "null_search_calibration",
    "rank_ic",
    "shuffled_future_control",
]

_MIN_OBSERVATIONS = 20
_PROMOTION_ALPHA = Decimal("0.05")


def _q(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def rank_ic(scores: np.ndarray, outcomes: np.ndarray) -> float:
    """Spearman rank correlation between scores and realised outcomes."""
    if scores.size < 2:
        return 0.0
    score_ranks = np.argsort(np.argsort(scores)).astype(float)
    outcome_ranks = np.argsort(np.argsort(outcomes)).astype(float)
    if score_ranks.std() == 0 or outcome_ranks.std() == 0:
        return 0.0
    return float(np.corrcoef(score_ranks, outcome_ranks)[0, 1])


@dataclass(frozen=True)
class ShuffledFutureResult:
    """Observed statistic against its permutation null."""

    observed_ic: Decimal
    shuffled_ics: list[Decimal]
    p_value: Decimal

    @property
    def promotes(self) -> bool:
        """Whether the observed statistic beats its own permutation null.

        Necessary, not sufficient. §7's invariant is that a shuffled future *fails*
        promotion; clearing this control is the floor, and DSR/PBO/SPA (M18) are the bar.
        """
        return self.p_value < _PROMOTION_ALPHA


def shuffled_future_control(
    scores: np.ndarray,
    outcomes: np.ndarray,
    n_permutations: int,
    seed: int,
) -> ShuffledFutureResult:
    """Permutation test of ``rank_ic(scores, outcomes)`` against a destroyed future.

    Deterministic for a given ``seed`` (rule 1). The p-value is one-sided on ``|IC|``: an
    alpha that is reliably *wrong* is as much a finding as one that is reliably right, and
    treating only positive IC as signal would hide the sign-flipped case.
    """
    scores = np.asarray(scores, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    if scores.shape != outcomes.shape:
        raise ValueError(f"length mismatch: {scores.shape} vs {outcomes.shape}")
    if scores.size < _MIN_OBSERVATIONS:
        raise ValueError(
            f"need at least {_MIN_OBSERVATIONS} observations for a permutation test, got "
            f"{scores.size} — a p-value from a handful of points is a number without a claim"
        )
    if n_permutations < 1:
        raise ValueError(f"n_permutations must be positive, got {n_permutations}")

    observed = abs(rank_ic(scores, outcomes))
    rng = np.random.default_rng(seed)
    shuffled: list[float] = []
    for _ in range(n_permutations):
        shuffled.append(abs(rank_ic(scores, rng.permutation(outcomes))))

    # +1 in numerator and denominator: the observed value is itself one draw from the null
    # under H0, so a p-value of exactly 0 is not attainable and should not be reported.
    at_least_as_extreme = sum(1 for s in shuffled if s >= observed)
    p_value = Decimal(at_least_as_extreme + 1) / Decimal(n_permutations + 1)

    return ShuffledFutureResult(
        observed_ic=_q(observed),
        shuffled_ics=[_q(s) for s in shuffled],
        p_value=p_value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN),
    )


@dataclass(frozen=True)
class NullSearchCalibration:
    """Whether the S1 statistics chain rejects at the rate it claims to."""

    q: float
    n_searches: int
    n_candidates: int
    survivor_rate: float
    searches_with_a_survivor: int

    @property
    def calibrated(self) -> bool:
        """Within Monte-Carlo error of ``q``.

        The band widens with fewer searches, because a rate estimated from 50 draws simply
        cannot distinguish 0.08 from 0.12 -- claiming otherwise would be a precision the
        experiment does not have.
        """
        standard_error = float((self.q * (1 - self.q) / self.n_searches) ** 0.5)
        return bool(abs(self.survivor_rate - self.q) <= max(3 * standard_error, 0.03))


def null_search_calibration(
    n_searches: int,
    n_candidates: int,
    n_observations: int,
    q: float,
    seed: int,
) -> NullSearchCalibration:
    """Run the whole S1 chain on destroyed data and measure the survivor rate (§6 M13).

    Each "search" is ``n_candidates`` null alphas scored against unrelated outcomes. Their
    rank ICs go through a Newey-West t, a normal p-value and BH at ``q`` -- the identical path
    a real sweep takes. Under the complete null BH's FDR equals its FWER, so the fraction of
    searches producing at least one survivor should sit near ``q``.

    This is the only check that can see a miscalibration in the chain *as a whole*: a
    Newey-West statistic with the wrong lag policy, a p-value from the wrong tail, or a BH
    implemented as a per-test threshold would each leave every individual number looking
    plausible while this rate drifts away from ``q``.
    """
    if not 0 < q < 1:
        raise ValueError(f"q must be in (0, 1), got {q}")
    if min(n_searches, n_candidates) < 1:
        raise ValueError("need at least one search and one candidate")

    rng = np.random.default_rng(seed)
    # n_observations is the number of IC OBSERVATIONS, each computed over a block of raw
    # points — which is how a real sweep works: one cross-sectional IC per decision time,
    # tested as a series. Calibrating on a shorter series than S1 will actually use would
    # tell us nothing about S1.
    block = 10
    lags = max(1, int(n_observations**0.25))  # standard HAC truncation rule
    with_survivor = 0

    for _ in range(n_searches):
        p_values: list[float] = []
        for _ in range(n_candidates):
            # Feature and label destroyed independently: by construction there is nothing to
            # find, so every rejection below is a false one.
            scores = rng.normal(size=n_observations * block)
            outcomes = rng.normal(size=n_observations * block)
            per_period = _per_period_ic(scores, outcomes)
            t_stat = newey_west_t(per_period, lags=lags)
            p_values.append(two_sided_t_p_value(t_stat, df=per_period.size - 1))
        if any(benjamini_hochberg(p_values, q=q)):
            with_survivor += 1

    return NullSearchCalibration(
        q=q,
        n_searches=n_searches,
        n_candidates=n_candidates,
        survivor_rate=with_survivor / n_searches,
        searches_with_a_survivor=with_survivor,
    )


def _per_period_ic(scores: np.ndarray, outcomes: np.ndarray, block: int = 10) -> np.ndarray:
    """Rank IC computed per block, so the t-statistic has a series to work on.

    A single IC over the whole sample has no dispersion to test. Real S1 computes a
    cross-sectional IC per decision time and tests the resulting series; blocking the null
    data the same way keeps the calibration honest about the statistic actually used.
    """
    n_blocks = max(2, scores.size // block)
    return np.array(
        [
            rank_ic(chunk_s, chunk_o)
            for chunk_s, chunk_o in zip(
                np.array_split(scores, n_blocks), np.array_split(outcomes, n_blocks), strict=True
            )
        ]
    )
