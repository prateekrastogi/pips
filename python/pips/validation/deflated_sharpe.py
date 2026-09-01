"""PSR and the Deflated Sharpe Ratio  (§6 M18, §3.6).

§6 M18 names one trap in its own text — *"kurtosis convention: γ₄ raw; excess+... guard in
code"* — and it is worth being precise about why.

The PSR denominator contains ``(γ₄ - 1)/4 · SR²``. With a NORMAL return series the raw kurtosis
γ₄ is **3**; almost every library returns **excess** kurtosis, which is 0 for the same series.
Substitute 0 for 3 and the denominator shrinks, the statistic inflates, and the PSR comes out
HIGHER — a better-looking result produced by a units mistake, with nothing in the output to
show for it. It is the exact shape this project keeps meeting: a wrong number that looks like a
right one.

So the guard is mathematical, not heuristic. **γ₄ ≥ 1 + γ₃²** holds for every distribution
possessing the moments, so a value below that bound is not a raw kurtosis at all. The bound
moves with the skew because the mathematics does — a flat "must be at least 3" rule would
reject genuinely skewed data.

The DSR is the PSR measured against the Sharpe the BEST of N trials would be expected to show
under a true null — §3.6's answer to "we looked at many". Deflation can only ever lower the
number, and :mod:`pips.search.multiplicity` evaluates it as a BRACKET at ``N = M_erank`` and
``N = M``, because neither end is the truth.

``normal_ppf`` inverts by bisection rather than a rational approximation. Bisection is exact to
the tolerance asked for and, more importantly, deterministic to the last bit on every machine
(rule 1) — an approximation carries its own error profile into every DSR that uses it.
"""

from __future__ import annotations

import math
from typing import Final

__all__ = [
    "deflated_sharpe_ratio",
    "expected_max_sharpe",
    "normal_cdf",
    "normal_ppf",
    "probabilistic_sharpe_ratio",
]

EULER_MASCHERONI: Final = 0.5772156649015329
_PPF_TOLERANCE: Final = 1e-12
_PPF_BOUND: Final = 40.0


def normal_cdf(x: float) -> float:
    """Standard normal CDF, via ``math.erf`` — stdlib, exact, no dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Inverse standard normal CDF, by bisection.

    Bisection rather than a rational approximation: it is deterministic to the last bit on
    every machine (rule 1), and an approximation would carry its own error profile into every
    DSR computed from it.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"probability must be strictly between 0 and 1, got {p}")
    low, high = -_PPF_BOUND, _PPF_BOUND
    while high - low > _PPF_TOLERANCE:
        middle = (low + high) / 2.0
        if normal_cdf(middle) < p:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _check_kurtosis(skew: float, kurtosis: float) -> None:
    """Refuse a kurtosis that cannot be a RAW one.

    γ₄ ≥ 1 + γ₃² for every distribution with the moments. Below that bound the value is not a
    raw kurtosis, and the overwhelmingly likely cause is excess kurtosis passed by mistake —
    which inflates the PSR, so it fails in the flattering direction.
    """
    floor = 1.0 + skew * skew
    if kurtosis < floor:
        raise ValueError(
            f"kurtosis {kurtosis} is below the mathematical floor 1 + skew² = {floor:.4f}, so "
            "it cannot be a RAW kurtosis (γ₄). The likely cause is EXCESS kurtosis, which is "
            f"0 for a normal series where the raw value is 3 — add 3 to get {kurtosis + 3}. "
            "This matters: excess kurtosis shrinks the PSR denominator and inflates the "
            "result (§6 M18)."
        )


def probabilistic_sharpe_ratio(
    sharpe: float, n: int, skew: float, kurtosis: float, benchmark: float = 0.0
) -> float:
    """Probability the true Sharpe exceeds ``benchmark``, given the sample's shape.

    ``kurtosis`` is RAW (γ₄), normal = 3. See :func:`_check_kurtosis`.
    """
    if n < 2:
        raise ValueError(f"need at least 2 observations to estimate a Sharpe, got {n}")
    _check_kurtosis(skew, kurtosis)

    variance = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe * sharpe
    if variance <= 0:
        raise ValueError(
            f"the PSR variance term is {variance}, which is not positive. The moments supplied "
            "do not describe a distribution this estimator can stand on."
        )
    return normal_cdf((sharpe - benchmark) * math.sqrt(n - 1) / math.sqrt(variance))


def expected_max_sharpe(n_trials: int, variance: float) -> float:
    """Sharpe the BEST of ``n_trials`` would be expected to show under a true null.

    Zero for a single trial: with nothing selected between, there is no selection to correct
    for, and inventing a penalty there would deflate an honest result out of nowhere.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be at least 1, got {n_trials}")
    if variance < 0:
        raise ValueError(f"variance must not be negative, got {variance}")
    if n_trials == 1:
        return 0.0
    gamma = EULER_MASCHERONI
    return math.sqrt(variance) * (
        (1.0 - gamma) * normal_ppf(1.0 - 1.0 / n_trials)
        + gamma * normal_ppf(1.0 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(
    sharpe: float,
    n: int,
    skew: float,
    kurtosis: float,
    n_trials: int,
    sharpe_variance: float,
) -> float:
    """PSR measured against the expected maximum of ``n_trials`` (§3.6).

    Deflation can only ever lower the probability: looking at more things cannot make one of
    them more believable.
    """
    benchmark = expected_max_sharpe(n_trials, sharpe_variance)
    return probabilistic_sharpe_ratio(sharpe, n, skew, kurtosis, benchmark=benchmark)
