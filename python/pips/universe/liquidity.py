"""M7's liquidity score and the universe it ranks  (§6 M7, `[C-UNIV-01]`).

`U300` is not a list somebody supplies. It is **computed**: M7 specifies

    z(log median ₹vol) - 0.75·z(spread) - 0.50·z(Amihud) - 0.25·z(gap-rate)

with weights that are *fixed, stress-tested, never P&L-tuned*, and N ∈ {50, 100, 150, 300}.

That phrase is the design. **A weight the caller can pass is a weight somebody will tune** until
the universe contains the names their strategy already liked — and a universe tuned on P&L is a
selection effect wearing the costume of an eligibility rule, applied before every measurement
downstream. So the weights are constants and the scorer takes none.

**The z-scores are cross-sectional**, across symbols on one day: a name is liquid relative to
the others it competes with for the same capital. A time-series z would ask "is this name liquid
for itself lately", which every illiquid name passes.

**Volume enters as a log.** Rupee volume spans orders of magnitude, and without it one mega-cap
dominates the z and flattens every other name's contribution into noise.

**A symbol missing any component cannot be scored**, and is excluded rather than defaulted:
a missing spread read as zero makes an illiquid name look tight, which is the flattering
direction.

The signs are stated because a single flip ranks the worst names first and nothing downstream
would notice: volume helps; spread, Amihud and gap-rate hurt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "SUPPORTED_N",
    "WEIGHTS",
    "SymbolStats",
    "liquidity_scores",
    "stable_core",
    "top_n",
]

WEIGHTS: dict[str, float] = {
    "median_rupee_volume": 1.0,
    "relative_spread": -0.75,
    "amihud": -0.50,
    "gap_rate": -0.25,
}
"""M7's coefficients, verbatim and closed. Not a default, not a parameter: *fixed,
stress-tested, never P&L-tuned* is the property that makes the universe an eligibility rule
rather than a second selection stage."""

SUPPORTED_N: frozenset[int] = frozenset({50, 100, 150, 300})
"""The universe sizes M7 registers. An arbitrary N is a universe nobody pre-registered, and
choosing it after seeing scores is the multiplicity problem moved one layer down."""


@dataclass(frozen=True)
class SymbolStats:
    """One symbol's liquidity inputs for one day. All four are required."""

    symbol: str
    median_rupee_volume: float
    relative_spread: float
    amihud: float
    gap_rate: float


def _usable(stat: SymbolStats) -> bool:
    """Every component present, finite, and loggable where a log is taken."""
    values = (stat.relative_spread, stat.amihud, stat.gap_rate)
    if not all(math.isfinite(v) for v in values):
        return False
    # A name that traded nothing has no log-volume, and clamping it to a floor invents one.
    return math.isfinite(stat.median_rupee_volume) and stat.median_rupee_volume > 0


def _z(values: Mapping[str, float]) -> dict[str, float]:
    """Cross-sectional z-scores. Zero everywhere when the cross-section is degenerate.

    `min == max` rather than `std == 0.0`: the standard deviation of identical values is exactly
    zero only at some lengths, and dividing by 1e-19 of float noise gives a z around 1e15 —
    one name would take the whole universe. The same trap `gate_s4` had.
    """
    # Kept although `liquidity_scores` never reaches it with fewer than two, and although the
    # `min == max` guard below already answers the one-value case identically. What it uniquely
    # protects is the EMPTY mapping, where `min(())` raises -- so this is the guard for a second
    # caller, the same reason `_TERMINAL` is kept in the backfill. Unreachable today, and a
    # mutation of it is correspondingly equivalent.
    if len(values) < 2:
        return dict.fromkeys(values, 0.0)
    ordered = list(values.values())
    if min(ordered) == max(ordered):
        return dict.fromkeys(values, 0.0)
    mean = sum(ordered) / len(ordered)
    spread = math.sqrt(sum((v - mean) ** 2 for v in ordered) / len(ordered))
    return {name: (value - mean) / spread for name, value in values.items()}


def liquidity_scores(population: Sequence[SymbolStats]) -> dict[str, float]:
    """M7's score for every scorable symbol in one day's cross-section.

    A single symbol scores nothing: there is no cross-section to be liquid *relative to*, and
    returning a score anyway would let a one-name population pass an eligibility rule that
    exists to compare.
    """
    usable = [s for s in population if _usable(s)]
    if len(usable) < 2:
        return {}

    components = {
        "median_rupee_volume": _z({s.symbol: math.log(s.median_rupee_volume) for s in usable}),
        "relative_spread": _z({s.symbol: s.relative_spread for s in usable}),
        "amihud": _z({s.symbol: s.amihud for s in usable}),
        "gap_rate": _z({s.symbol: s.gap_rate for s in usable}),
    }
    return {
        s.symbol: sum(weight * components[name][s.symbol] for name, weight in WEIGHTS.items())
        for s in usable
    }


def top_n(scores: Mapping[str, float], n: int) -> tuple[str, ...]:
    """The ``n`` highest-scoring symbols, ties broken on the symbol.

    ``n`` is a MAXIMUM: fewer qualify when fewer were scored, and padding would name a universe
    member that was never measured — the same rule as the top-5 report.
    """
    if n not in SUPPORTED_N:
        raise ValueError(
            f"n={n} is not one of M7's registered universe sizes {sorted(SUPPORTED_N)}. An "
            "arbitrary N is a universe nobody pre-registered, and picking one after seeing the "
            "scores is the multiplicity problem moved down a layer."
        )
    ranked = sorted(scores, key=lambda symbol: (-scores[symbol], symbol))
    return tuple(ranked[:n])


def stable_core(
    *, previous: Sequence[str], scores: Mapping[str, float], n: int, k: int
) -> tuple[str, ...]:
    """The blueprint's stable-core buffer: *enter above N-k; exit below N+k*.

    **The asymmetry is the whole mechanism.** A newcomer must beat the tighter bar to get in; an
    incumbent survives until it falls past the looser one. Symmetric bars would just be a wider
    universe and would stabilise nothing — a name oscillating around rank N would enter and
    leave every refresh, and each round trip costs the panel a warm-up and the strategy a
    turnover it never asked for.

    **An unscored incumbent cannot be kept.** A name with no score today was not measured today
    — suspended, delisted, or simply absent from the cross-section — and carrying it forward
    would put a universe member in the panel with no bars behind it.

    ``k`` is a POLICY parameter, not a tuned one, and unlike :data:`WEIGHTS` it is meant to be
    searched: the blueprint lists the stable-core buffer among the policy dimensions whose
    guardrail is *"stress-tested for liquidity, not tuned to maximize strategy P&L"*. Its
    starter values are the one column of that table the blueprint leaves empty, so there is no
    registered set to validate against here — only that it cannot be negative, which would
    invert the bars and require a name to get WORSE to stay.

    Membership drifts inside the buffer by construction and is bounded by ``n + k``: hysteresis
    that let a U50 grow to 200 would not be the policy anybody registered.
    """
    if n not in SUPPORTED_N:
        raise ValueError(
            f"n={n} is not one of M7's registered universe sizes {sorted(SUPPORTED_N)}."
        )
    if k < 0:
        raise ValueError(
            f"k={k} is negative, which inverts the bars: a name would have to get WORSE to stay "
            "in the universe."
        )

    ranking = sorted(scores, key=lambda symbol: (-scores[symbol], symbol))
    rank = {symbol: position + 1 for position, symbol in enumerate(ranking)}
    incumbents = set(previous)

    kept = [
        symbol
        for symbol in ranking
        # Enter above n-k; incumbents survive until they fall past n+k.
        if rank[symbol] <= (n + k if symbol in incumbents else max(0, n - k))
    ]
    # No trailing slice. An incumbent is kept only at rank <= n+k and a newcomer only at
    # rank <= n-k, so the membership is already a subset of ranks <= n+k and a cap on top of
    # that is a bound nothing can reach. The fifth guard this project has removed for being
    # indistinguishable; the bound is a consequence of the rule, and a test asserts it.
    return tuple(kept)
