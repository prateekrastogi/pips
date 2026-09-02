"""M7's universe snapshot: the six pieces in the order that matters  (`[C-UNIV-06]`).

The composition carries correctness the pieces do not.

**Eligibility is applied BEFORE scoring.** The liquidity score is a *cross-sectional* z, so every
name in the population shifts the mean and spread for every other one. A suspended name that
cannot be traded still moving everyone else's rank is a name influencing a selection it is barred
from — and the effect is invisible afterwards, because the ranking that comes out looks like any
other ranking.

**An ineligible incumbent exits regardless of the buffer.** The stable-core buffer exists to damp
*score* churn; it was never argued for as a reason to keep trading a suspended stock. Applying
hysteresis over an eligibility failure is the mechanism doing something nobody claimed for it.

**Every exclusion is named**, and the kinds stay apart: a name that failed a gate, a name whose
eligibility could not be determined, and a name whose statistics could not be computed are three
different problems with three different fixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pips.universe.eligibility import EligibilityInputs, eligible_on
from pips.universe.liquidity import SymbolStats, liquidity_scores, stable_core

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["UniverseCandidate", "UniverseSnapshot", "universe_snapshot"]


@dataclass(frozen=True)
class UniverseCandidate:
    """One name considered for a session: what it may do, and how it traded."""

    eligibility: EligibilityInputs
    stats: SymbolStats


@dataclass(frozen=True)
class UniverseSnapshot:
    members: tuple[str, ...]
    scores: Mapping[str, float]
    """Every name that entered the cross-section, and what it scored. Barred names are absent —
    not scored and discarded, but never scored at all."""
    excluded: Mapping[str, tuple[str, ...]]
    """Why each rejected name is out. Gate failures, undetermined gates and unscorable
    statistics are all named, because they are three different jobs to fix."""
    scored: int


def universe_snapshot(
    *,
    candidates: Sequence[UniverseCandidate],
    previous: Sequence[str],
    n: int,
    k: int,
    min_sessions_listed: int,
) -> UniverseSnapshot:
    """The universe for one session, from the six M7 pieces in order.

    Eligibility, then the cross-sectional score over what survived it, then the stable-core
    buffer over that ranking — and an incumbent that failed eligibility never reaches the buffer.
    """
    excluded: dict[str, tuple[str, ...]] = {}
    tradeable: list[SymbolStats] = []

    for candidate in candidates:
        symbol = candidate.eligibility.symbol
        verdict = eligible_on(candidate.eligibility, min_sessions_listed=min_sessions_listed)
        if not verdict.eligible:
            excluded[symbol] = verdict.ineligible + verdict.undetermined
            continue
        tradeable.append(candidate.stats)

    scores = liquidity_scores(tradeable)
    for stats in tradeable:
        if stats.symbol not in scores:
            excluded[stats.symbol] = (
                "eligible to trade, but its liquidity statistics could not be scored",
            )

    # An ineligible incumbent cannot survive the buffer, and that falls out of `stable_core`'s
    # own rule rather than needing a filter here: a name with no score today was not measured
    # today, and an ineligible name was never scored. Filtering `previous` first was a no-op --
    # the sixth thing this project has removed for being indistinguishable. The composed
    # behaviour is still asserted by a test, so if that rule ever loosened this would fail.
    members = stable_core(previous=previous, scores=scores, n=n, k=k)

    return UniverseSnapshot(
        members=members,
        scores=scores,
        excluded=excluded,
        scored=len(scores),
    )
