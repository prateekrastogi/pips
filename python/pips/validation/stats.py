"""S1 diagnostics: HAC t-statistics and horizon-curve shape (§6 M13).

The Newey-West statistic is here because the naive alternative is wrong in a specific,
flattering direction. Minute-bar IC series are autocorrelated, so the effective number of
independent observations is far below the sample size, and an OLS t-statistic therefore
reports a confidence nobody earned. §7's rejection list names the same error in another form:
"minute-Sharpe annualized as independent".
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

import numpy as np

__all__ = [
    "coverage",
    "ic_half_life",
    "is_monotone_in_horizon",
    "newey_west_t",
    "two_sided_t_p_value",
]

_MIN_OBSERVATIONS = 10


def newey_west_t(series: Sequence[float] | np.ndarray, lags: int) -> float:
    """t-statistic for the mean of ``series`` with a Newey-West HAC variance.

    Bartlett kernel with ``lags`` truncation. Under positive autocorrelation this is SMALLER
    than the OLS t -- which is the entire reason it exists, and the reason a pipeline that
    quietly used the OLS one would look more convincing while being less true.
    """
    values = np.asarray(series, dtype=float)
    if values.size < _MIN_OBSERVATIONS:
        raise ValueError(
            f"need at least {_MIN_OBSERVATIONS} observations for a HAC estimate, got {values.size}"
        )
    if lags < 0:
        raise ValueError(f"lags must be non-negative, got {lags}")

    n = values.size
    mean = values.mean()
    deviations = values - mean

    variance = float((deviations**2).sum() / n)
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1)  # Bartlett
        auto = float((deviations[lag:] * deviations[:-lag]).sum() / n)
        variance += 2.0 * weight * auto
    if variance <= 0:
        # A negative HAC variance is a known finite-sample artefact of the Bartlett kernel.
        # Reporting a t from it would be worse than reporting none.
        return 0.0
    return float(mean / np.sqrt(variance / n))


def is_monotone_in_horizon(ic_curve: Sequence[float]) -> bool:
    """Whether |IC| is non-increasing across the horizon grid.

    A01's falsifier requires a monotone rank-IC. A curve that rises then falls is not the
    decay a horizon story predicts -- it is a peak at one horizon, which is what a search over
    horizons finds in noise.
    """
    magnitudes = [abs(x) for x in ic_curve]
    return all(a >= b for a, b in pairwise(magnitudes))


def ic_half_life(ic_curve: Sequence[float]) -> float | None:
    """Horizon steps for |IC| to halve, or ``None`` if the curve does not decay.

    ``None`` rather than a number: inventing a decay rate for a curve that is not decaying
    would put a plausible-looking parameter into a report that has no referent.
    """
    magnitudes = [abs(x) for x in ic_curve]
    if len(magnitudes) < 2 or magnitudes[0] <= 0:
        return None
    if not is_monotone_in_horizon(magnitudes) or magnitudes[-1] >= magnitudes[0]:
        return None

    target = magnitudes[0] / 2.0
    for i, value in enumerate(magnitudes):
        if value <= target:
            if i == 0:
                return 0.0
            # Linear interpolation between the bracketing horizons.
            previous = magnitudes[i - 1]
            if previous == value:
                return float(i)
            return float(i - 1 + (previous - target) / (previous - value))
    return None


def coverage(n_forecasts: int, n_opportunities: int) -> float:
    """Fraction of decision opportunities that produced a forecast."""
    if n_opportunities == 0:
        return 0.0
    if n_forecasts > n_opportunities:
        raise ValueError(
            f"coverage would exceed 1: {n_forecasts} forecasts from {n_opportunities} "
            "opportunities — the opportunity count is wrong, and clipping would hide it"
        )
    return n_forecasts / n_opportunities


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """``I_x(a, b)`` by the standard continued fraction (Lentz's method).

    Here so the t-distribution can be evaluated without a SciPy dependency. Written out
    rather than approximated because the approximation is precisely what this replaces.
    """
    import math

    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    log_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(log_beta + a * math.log(x) + b * math.log(1 - x))

    # Continued fraction converges quickly for x < (a+1)/(a+b+2); otherwise use symmetry.
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _regularized_incomplete_beta(b, a, 1 - x)

    tiny = 1e-30
    f, c, d = 1.0, 1.0, 0.0
    for i in range(200):
        m = i // 2
        if i == 0:
            numerator = 1.0
        elif i % 2 == 0:
            numerator = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            numerator = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        d = tiny if abs(d) < tiny else d
        d = 1.0 / d
        c = 1.0 + numerator / c
        c = tiny if abs(c) < tiny else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-12:
            break
    return front * (f - 1.0) / a


def two_sided_t_p_value(t_stat: float, df: int) -> float:
    """Two-sided p-value from Student's t with ``df`` degrees of freedom.

    NOT the normal approximation, and the difference is not cosmetic. Using a normal p-value
    on a t-statistic from ~10 observations over-rejects severely: the null-search calibration
    caught exactly that, surviving at 0.70 against a nominal q of 0.10. At small samples the
    t has much heavier tails than the normal, and pretending otherwise manufactures
    significance out of sample size.

    Two-sided because an alpha that is reliably WRONG is as much a finding as one that is
    reliably right; a one-sided test would quietly halve the correction for half the
    hypothesis space.
    """
    if df < 1:
        raise ValueError(f"degrees of freedom must be >= 1, got {df}")
    x = df / (df + t_stat * t_stat)
    return float(min(1.0, _regularized_incomplete_beta(df / 2.0, 0.5, x)))
