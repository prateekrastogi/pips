"""Hansen's SPA test  (§6 M18).

SPA asks whether the BEST model in a set genuinely beats a benchmark, given that you looked at
all of them. Its predecessor, White's Reality Check, answers the same question too
conservatively — and the reason IS the content of "Hansen recentering", so it is worth stating
precisely.

**The Reality Check lets hopeless models inflate the null.** It builds the null by recentering
every model on its own sample mean, so a model that lost badly still contributes a draw to the
maximum. Add enough irrelevant bad models and the null's maximum drifts upward, the p-value
rises, and a genuinely superior model stops being detectable — **you fail to reject because of
models nobody would ever have traded.**

Hansen's fix: a model whose sample mean sits far enough below zero cannot plausibly be the
best, so it is recentered to zero rather than to its mean and stops contributing. The threshold
is ``-A_k`` with ``A_k = sqrt(var_k / n) * sqrt(2 log log n)`` — the law of the iterated
logarithm, which is what makes it shrink at the right rate as the sample grows rather than
being a number somebody picked.

Both recenterings are implemented, and that is deliberate: the claim "recentering stops
hopeless models mattering" is only worth making if the alternative can be run alongside it.
The suite compares them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pips.validation.bootstrap import bootstrap_indices

__all__ = ["SPAResult", "spa_test"]

Recentering = Literal["hansen", "reality-check"]
_MIN_BOOTSTRAP = 50


@dataclass(frozen=True)
class SPAResult:
    """The test statistic, its p-value, and what the recentering did."""

    p_value: float
    statistic: float
    best_model: str
    n_models: int
    recentered_to_zero: int
    recentering: str

    def describe(self) -> str:
        return (
            f"SPA ({self.recentering}): p={self.p_value:.4f}, T={self.statistic:.4f}, "
            f"best={self.best_model} of {self.n_models} models, "
            f"{self.recentered_to_zero} recentered to zero"
        )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    centre = _mean(values)
    return sum((v - centre) ** 2 for v in values) / (len(values) - 1)


def spa_test(
    models: dict[str, list[Decimal]],
    n_bootstrap: int,
    block_length: int,
    seed: int,
    recentering: Recentering = "hansen",
) -> SPAResult:
    """Test whether the best of ``models`` beats the benchmark it is measured against.

    ``models`` maps a name to that model's per-period performance DIFFERENTIAL against the
    benchmark: positive means the model won that period.
    """
    if not models:
        raise ValueError(
            "spa_test called with no models. The maximum over an empty set is undefined, and "
            "returning a p-value for it would be inventing one."
        )
    if recentering not in ("hansen", "reality-check"):
        raise ValueError(
            f"unknown recentering {recentering!r}; expected 'hansen' or 'reality-check'"
        )
    if n_bootstrap < _MIN_BOOTSTRAP:
        raise ValueError(
            f"n_bootstrap must be at least {_MIN_BOOTSTRAP}, got {n_bootstrap}. A p-value from "
            "a handful of resamples has a resolution coarser than the thresholds it will be "
            "compared against, and still reads like a measurement."
        )
    lengths = {len(v) for v in models.values()}
    if len(lengths) != 1:
        raise ValueError(f"every model must have the same length, got {sorted(lengths)}")

    n = lengths.pop()
    if n < 2:
        raise ValueError(f"need at least 2 observations per model, got {n}")

    names = sorted(models)
    series = {k: [float(v) for v in models[k]] for k in names}
    means = {k: _mean(series[k]) for k in names}
    # Studentised by each model's own dispersion, so a model is not favoured merely for being
    # noisier. A zero-variance model gets a floor rather than a division: constant outperformance
    # is not infinitely significant, it is a sample with no evidence about its own variability.
    scale = {k: math.sqrt(max(_variance(series[k]), 1e-12) / n) for k in names}

    studentised = {k: means[k] / scale[k] for k in names}
    best_model = max(names, key=lambda k: (studentised[k], k))
    statistic = max(0.0, max(studentised.values()))

    # HANSEN RECENTERING. A model whose mean sits below -A_k cannot plausibly be the best, so
    # it is recentered to zero and stops contributing to the null. The threshold comes from the
    # law of the iterated logarithm, which is why it shrinks at the right rate with n rather
    # than being a constant somebody chose.
    log_log = math.sqrt(2.0 * math.log(math.log(n))) if n > math.e else 1.0
    recentered: dict[str, float] = {}
    zeroed = 0
    for k in names:
        if recentering == "reality-check":
            recentered[k] = means[k]
            continue
        threshold = -scale[k] * log_log
        if means[k] < threshold:
            recentered[k] = 0.0
            zeroed += 1
        else:
            recentered[k] = means[k]

    exceedances = 0
    for b in range(n_bootstrap):
        indices = bootstrap_indices(n, block_length, seed + b)
        draw = 0.0
        for k in names:
            values = series[k]
            resampled_mean = sum(values[i] for i in indices) / n
            draw = max(draw, (resampled_mean - recentered[k]) / scale[k])
        if draw >= statistic:
            exceedances += 1

    return SPAResult(
        p_value=exceedances / n_bootstrap,
        statistic=statistic,
        best_model=best_model,
        n_models=len(names),
        recentered_to_zero=zeroed,
        recentering=recentering,
    )
