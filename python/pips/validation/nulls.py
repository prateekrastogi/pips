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

__all__ = ["ShuffledFutureResult", "rank_ic", "shuffled_future_control"]

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
