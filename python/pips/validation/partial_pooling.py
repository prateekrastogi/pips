"""Hierarchical partial pooling for family means  (§6 M18).

Nine alpha families, each with a handful of configs, and the question is what F5's mean
performance actually is.

**No pooling** — each family's own sample mean — is mostly noise on small samples, and the
best-looking family is then the luckiest one. That is the multiplicity problem of §3.6 wearing
a new hat: the same reason a raw maximum Sharpe over N trials is not an estimate of anything.
**Complete pooling** — one grand mean for everyone — discards every real difference between
families, which is the whole reason the taxonomy exists.

Partial pooling asks how much of the observed spread between families is REAL, and moves each
family toward the grand mean by exactly that much. It is the same estimator as A12's slot
shrinkage one level up: the weight is ``tau^2 / (tau^2 + sigma^2/n)``, so a family with few
observations or noisy ones barely leaves the grand mean, while a family with many consistent
ones keeps most of its own.

**The trap is a negative variance estimate.** ``tau^2`` is estimated by method of moments — the
observed spread of family means minus what within-family noise alone would produce — and that
subtraction goes NEGATIVE whenever the families really are alike. A negative ``tau^2`` yields a
negative weight, and a negative weight pushes each family AWAY from the grand mean. That is
anti-shrinkage: the exact inverse of the intended correction, arrived at silently, producing a
spread between families wider than the data supports. It looks like a stronger result. It is
floored at zero here, which is complete pooling — the right answer when nothing separates them.

Both the floored and the raw estimate are reported. A run that floored is a run where the
families were indistinguishable, and that is a finding about the taxonomy rather than a detail
of the arithmetic — it should not be inferable only from the weights all being zero.

**The centre is the unweighted mean of family means**, not a precision-weighted one. Each
family is one unit of the estimand. Weighting the centre by sample size would let the largest
family dominate the target every smaller family is shrunk toward, which is precisely the path
by which one big family's luck becomes contagious.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["FamilyEstimate", "PoolingResult", "partial_pool"]

MIN_OBSERVATIONS = 2
MIN_FAMILIES = 2


@dataclass(frozen=True)
class FamilyEstimate:
    """One family's before and after, with the weight that separates them.

    The raw mean and the weight are kept alongside the shrunk mean deliberately: a shrunk mean
    on its own cannot be audited, because it is indistinguishable from a raw mean that happened
    to sit there.
    """

    name: str
    n: int
    raw_mean: Decimal
    shrunk_mean: Decimal
    weight: Decimal


@dataclass(frozen=True)
class PoolingResult:
    grand_mean: Decimal
    within_variance: Decimal
    between_variance: Decimal
    """The floored estimate actually used. Zero means complete pooling."""
    between_variance_raw: Decimal
    """Before the floor. Negative means the families were indistinguishable."""
    estimates: dict[str, FamilyEstimate]

    @property
    def floored(self) -> bool:
        """True when the raw between-family estimate was negative and got clamped."""
        return self.between_variance_raw < 0


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def partial_pool(families: dict[str, list[Decimal]]) -> PoolingResult:
    """Shrink each family's mean toward the grand mean by the share of spread that is real."""
    if len(families) < MIN_FAMILIES:
        raise ValueError(
            f"partial pooling needs at least 2 families, got {len(families)}. With one family "
            "there is no between-family variance to estimate, and falling back to no shrinkage "
            "would report the raw mean as though it had been pooled."
        )
    for name, observations in families.items():
        if len(observations) < MIN_OBSERVATIONS:
            raise ValueError(
                f"family {name!r} has {len(observations)} observations; at least "
                f"{MIN_OBSERVATIONS} are needed to estimate a within-family variance. A family "
                "that cannot supply one would silently borrow every other family's."
            )

    means = {name: _mean(obs) for name, obs in families.items()}
    grand = _mean(list(means.values()))

    # Pooled within-family variance: sigma^2, the noise each family's own mean is made of.
    dof = sum(len(obs) - 1 for obs in families.values())
    within = sum(
        sum((x - means[name]) ** 2 for x in obs) for name, obs in families.items()
    ) / Decimal(dof)

    # Observed spread of the family means, and the part of it that noise alone explains.
    observed = sum((m - grand) ** 2 for m in means.values()) / Decimal(len(families) - 1)
    noise_share = _mean([within / Decimal(len(obs)) for obs in families.values()])
    between_raw = observed - noise_share
    # The floor. A negative tau^2 would invert the correction rather than weaken it.
    between = max(Decimal(0), between_raw)

    estimates: dict[str, FamilyEstimate] = {}
    for name, obs in families.items():
        precision = within / Decimal(len(obs))
        denominator = between + precision
        weight = Decimal(0) if denominator == 0 else between / denominator
        estimates[name] = FamilyEstimate(
            name=name,
            n=len(obs),
            raw_mean=means[name],
            shrunk_mean=weight * means[name] + (Decimal(1) - weight) * grand,
            weight=weight,
        )

    return PoolingResult(
        grand_mean=grand,
        within_variance=within,
        between_variance=between,
        between_variance_raw=between_raw,
        estimates=estimates,
    )
