"""Does the alpha beat its declared parent null?  [C-SPEC-01] (§6 M16, rule 5).

Three pre-registered falsifiers are one question in three costumes — A04's *"reject if
residualization adds no value over raw reversal"*, A05's *"reject if it is not distinct from
market direction"*, A08's *"reject if direction adds no information beyond a volatility
forecast"*.

And every one of those baselines is already written down. Rule 5 makes each spec declare its
``null_models`` before the search, and the parents are named there in so many words. So this
check does not choose a baseline: **it requires the caller to name one the spec
pre-registered**, which is the difference between testing a claim and constructing a comparison
the alpha wins.

**Paired, not two independent samples.** The alpha and the null see the same periods, and
treating them as independent discards the pairing and inflates the variance. That direction
happens to make rejection easier here, but it is wrong rather than conservative — the same
mistake flatters on a different dataset.

**A tie is a FAILURE.** The falsifiers make "adds no information" the rejection condition, so
the burden sits on the alpha and equal performance rejects. Passing on a tie would read the
pre-registration backwards.

**Too few observations, or a difference with no dispersion, is NOT MEASURED** — never a pass. A
constant paired difference is infinitely significant on the arithmetic and worth nothing in
fact, because a t-statistic divides by a dispersion that is not there.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pips.alphas.t1._common import RESIDUAL_EPSILON
from pips.validation.stats import two_sided_t_p_value

if TYPE_CHECKING:
    from pips.alphas.spec import AlphaSpec

__all__ = ["IncrementalVerdict", "beats_null"]


@dataclass(frozen=True)
class IncrementalVerdict:
    """Whether the alpha's advantage over its declared parent is real."""

    null_model: str
    measured: bool
    n: int
    mean_difference: Decimal
    t_stat: float | None
    p_value: float | None
    _beats: bool = False

    @property
    def beats(self) -> bool:
        """Measured, positive, and significant. All three, or it does not beat."""
        return self._beats


def beats_null(
    spec: AlphaSpec,
    null_model: str,
    alpha_scores: list[Decimal],
    null_scores: list[Decimal],
    alpha_level: float,
    min_observations: int = 20,
) -> IncrementalVerdict:
    """Paired test of the alpha's per-period advantage over a PRE-REGISTERED null."""
    if null_model not in spec.null_models:
        raise ValueError(
            f"{spec.id}: {null_model!r} is not one of the spec's declared null_models "
            f"{spec.null_models}. Rule 5 makes the parent a pre-registration; a baseline "
            "chosen now is a comparison built to be won."
        )
    if len(alpha_scores) != len(null_scores):
        raise ValueError(
            f"paired test needs equal-length series, got {len(alpha_scores)} and "
            f"{len(null_scores)}. Unequal lengths mean the pairing is wrong, and a paired "
            "test on mispaired data is a confident answer to a question nobody asked."
        )

    differences = [a - n for a, n in zip(alpha_scores, null_scores, strict=True)]
    n = len(differences)
    if n < min_observations:
        return IncrementalVerdict(null_model, False, n, Decimal(0), None, None)

    mean = sum(differences, Decimal(0)) / Decimal(n)
    variance = sum((d - mean) ** 2 for d in differences) / Decimal(n - 1)
    # NOT `variance <= 0`. Decimal carries 28 significant digits, so a difference that is
    # constant in every meaningful sense still leaves residue around 1e-33 — and a t-statistic
    # dividing by that reports 1.4e14, which is exactly the "perfectly consistent tiny edge"
    # a real series never produces. Same reasoning and same constant as `RESIDUAL_EPSILON` in
    # the alpha plugins, where three identical names once scored 3.1 for the same reason.
    if variance.sqrt() < RESIDUAL_EPSILON:
        # TWO DIFFERENT ANSWERS SHARE THIS BRANCH, and collapsing them would repeat the
        # mistake this project keeps correcting. A difference that is identically ZERO is
        # perfectly measured: the alpha adds exactly nothing, which is the falsifier's own
        # rejection condition met, not a failure to look. A CONSTANT NON-ZERO difference is
        # genuinely unassessable — there is no dispersion against which to judge it.
        if abs(mean) < RESIDUAL_EPSILON:
            return IncrementalVerdict(null_model, True, n, mean, None, None, False)
        return IncrementalVerdict(null_model, False, n, mean, None, None)

    standard_error = (variance / Decimal(n)).sqrt()
    t_stat = float(mean / standard_error)
    p_value = two_sided_t_p_value(t_stat, df=n - 1)
    return IncrementalVerdict(
        null_model=null_model,
        measured=True,
        n=n,
        mean_difference=mean,
        t_stat=t_stat,
        p_value=p_value,
        # POSITIVE and significant. A significant difference in the null's favour is not the
        # alpha beating anything, and a two-sided p-value alone cannot tell the two apart.
        _beats=mean > 0 and p_value < alpha_level,
    )
