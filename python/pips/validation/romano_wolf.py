"""Romano-Wolf stepdown  (§6 M18, "final survivors").

The last gate before a config is called a survivor: **of the models that look good, which can
we claim — controlling the chance that ANY of them is a false positive?**

Bonferroni answers by dividing alpha by the number of tests. Correct, and wasteful: it ignores
that the statistics are correlated, and on correlated strategies — which a family of alphas
over one universe certainly is — it throws away most of the power. Romano-Wolf uses the
bootstrap JOINT distribution, so correlation is accounted for rather than assumed away.

**The stepdown is where the power comes from.** The first pass compares every statistic against
the ``1 - alpha`` quantile of the maximum across ALL hypotheses. Having rejected some, the
second pass recomputes that maximum over only the SURVIVORS: a smaller maximum, a lower
threshold, and rejections the first pass could not make. Repeat until nothing new falls.

The single-step version is implemented alongside, for the reason the Reality Check sits beside
SPA: a claim that stepping down buys power is worth making only if the version that does not
step down can be run next to it.

**The bootstrap draws are computed once and reused across rounds.** Regenerating them per round
would add sampling noise between steps, so a threshold could rise — and the guarantee that
stepping down never rejects fewer would quietly stop holding, for a reason unrelated to the
procedure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from pips.validation.bootstrap import bootstrap_indices

__all__ = ["RomanoWolfResult", "romano_wolf"]


@dataclass(frozen=True)
class RomanoWolfResult:
    """Which hypotheses were rejected, and the threshold at each round."""

    rejected: tuple[str, ...]
    thresholds: tuple[float, ...]
    statistics: dict[str, float]
    adjusted_p: dict[str, float]
    """Per-hypothesis stepdown-adjusted p-value: the smallest family-wise level at which this
    hypothesis is rejected.

    The quantity `spa_test` cannot give. Its p-value is family-wise and earned by the BEST
    model; writing it into every candidate's dossier would hand candidate five the evidence
    candidate one produced. This is per-hypothesis and defensible for each on its own.

    Monotone across rounds by construction. A later round tests against a SMALLER surviving
    set, so its raw bootstrap frequency is smaller — and without the running maximum a weak
    model rejected last would print a better number than the strong one rejected first.
    """
    rounds: int
    stepdown: bool

    def describe(self) -> str:
        mode = "stepdown" if self.stepdown else "single-step"
        return (
            f"Romano-Wolf ({mode}): {len(self.rejected)} rejected in {self.rounds} round(s); "
            f"thresholds {[round(t, 4) for t in self.thresholds]}; "
            f"rejected {sorted(self.rejected)}"
        )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    centre = _mean(values)
    return sum((v - centre) ** 2 for v in values) / (len(values) - 1)


def _quantile(sorted_values: list[float], q: float) -> float:
    """Upper quantile by nearest-rank. Deterministic, and no interpolation to argue about."""
    if not sorted_values:
        return math.inf
    index = min(len(sorted_values) - 1, max(0, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[index]


def romano_wolf(
    models: dict[str, list[Decimal]],
    alpha: float,
    n_bootstrap: int,
    block_length: int,
    seed: int,
    stepdown: bool = True,
) -> RomanoWolfResult:
    """Stepdown multiple testing over per-period performance differentials."""
    if not models:
        raise ValueError(
            "romano_wolf called with no models. A family-wise error rate over an empty family "
            "is vacuously controlled, which reads as a result."
        )
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")
    lengths = {len(v) for v in models.values()}
    if len(lengths) != 1:
        raise ValueError(f"every model must have the same length, got {sorted(lengths)}")

    n = lengths.pop()
    names = sorted(models)
    series = {k: [float(v) for v in models[k]] for k in names}
    means = {k: _mean(series[k]) for k in names}
    scale = {k: math.sqrt(max(_variance(series[k]), 1e-12) / n) for k in names}
    statistics = {k: means[k] / scale[k] for k in names}

    # ONE set of bootstrap draws, reused every round. See the module docstring: regenerating
    # per round would let a later threshold rise on sampling noise alone.
    draws: list[dict[str, float]] = []
    for b in range(n_bootstrap):
        indices = bootstrap_indices(n, block_length, seed + b)
        draws.append(
            {k: (sum(series[k][i] for i in indices) / n - means[k]) / scale[k] for k in names}
        )

    rejected: list[str] = []
    thresholds: list[float] = []
    adjusted: dict[str, float] = {}
    floor = 0.0
    """The running maximum that makes the adjusted p-values monotone across rounds."""
    surviving = set(names)
    rounds = 0
    # A BOUND, not a belief. Each round either rejects at least one hypothesis or breaks, so
    # the count cannot exceed the family size — but that was implicit, and an implementation
    # that stopped shrinking `surviving` looped forever instead of failing. A procedure that
    # cannot terminate is not a procedure, so the guarantee is written down.
    max_rounds = len(names) + 1
    while surviving:
        rounds += 1
        if rounds > max_rounds:
            raise AssertionError(
                f"romano_wolf exceeded {max_rounds} rounds over {len(names)} hypotheses, so "
                "the surviving set is not shrinking. Each round must reject at least one "
                "hypothesis or stop."
            )
        maxima = sorted(max(draw[k] for k in surviving) for draw in draws)
        threshold = _quantile(maxima, 1.0 - alpha)
        thresholds.append(threshold)

        # The bootstrap frequency with which the maximum over the CURRENT surviving set reaches
        # each statistic. Computed for everyone still standing, because the round a hypothesis
        # is not rejected in is the round that fixes its p-value.
        for k in sorted(surviving):
            frequency = sum(1 for draw in draws if max(draw[j] for j in surviving) >= statistics[k])
            adjusted[k] = max(floor, frequency / len(draws))

        newly = {k for k in surviving if statistics[k] > threshold}
        if not newly:
            break
        floor = max([floor, *(adjusted[k] for k in newly)])
        rejected.extend(sorted(newly))
        surviving -= newly
        if not stepdown:
            # Single-step: one threshold, taken over the whole family, and no recomputation.
            break

    return RomanoWolfResult(
        rejected=tuple(sorted(rejected)),
        thresholds=tuple(thresholds),
        statistics=statistics,
        adjusted_p=adjusted,
        rounds=rounds,
        stepdown=stepdown,
    )
