"""Successive halving  (§6 M15, constitution rule 4).

A budget allocator: run every candidate cheaply, keep the best fraction, give the survivors
more resources, repeat. It is the right way to search a large space on a small budget — and it
has one specific way of lying about itself.

**It views far more trials than it reports.** A run over 64 configurations ending with one
winner has *evaluated* 64 in the first round, 16 in the second, 4 in the third: 85 trials, one
survivor. Rule 4 is explicit — *every viewed trial counts* — and if the multiplicity ledger
sees the winner and not the 85 evaluations behind it, every p-value downstream is corrected
against an M that is off by two orders of magnitude, in the direction that manufactures
significance.

So :class:`HalvingResult` reports ``trials_viewed`` and keeps every eliminated candidate. The
losers are not debris; they are the denominator.

**The winner is judged at the LARGEST budget, not at its best moment.** A configuration that
looked brilliant on a tiny budget and mediocre on a full one has earned nothing. Taking its
early score would be cherry-picking across budget levels, which is the same error as
cherry-picking across parameter values, and it arrives wearing the clothes of an efficiency
technique.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

__all__ = ["HalvingResult", "HalvingRound", "successive_halving"]

ScoreFn = Callable[[str, int], Decimal]
"""``(config, budget) -> score``. Injected, so the search is pure and reproducible."""


@dataclass(frozen=True)
class HalvingRound:
    """One rung: who ran, at what budget, and who survived it."""

    round_index: int
    budget: int
    configs: tuple[str, ...]
    survivors: tuple[str, ...]
    scores: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class HalvingResult:
    """The whole search, INCLUDING everything it discarded."""

    rounds: tuple[HalvingRound, ...]
    winner: str | None

    @property
    def trials_viewed(self) -> int:
        """Every (config, budget) evaluation performed. The number rule 4 wants.

        NOT the number of survivors, and not the number of distinct configurations: a config
        evaluated at three budgets was looked at three times, and each look could have been
        the one that produced a flattering number.
        """
        return sum(len(r.configs) for r in self.rounds)

    @property
    def all_configs_viewed(self) -> tuple[str, ...]:
        """Every candidate ever evaluated, eliminated ones included, in first-seen order."""
        seen: dict[str, None] = {}
        for rung in self.rounds:
            for config in rung.configs:
                seen.setdefault(config, None)
        return tuple(seen)

    @property
    def configs_viewed(self) -> int:
        return len(self.all_configs_viewed)


def successive_halving(
    candidates: tuple[str, ...], score: ScoreFn, initial_budget: int, eta: int
) -> HalvingResult:
    """Run the halving schedule and return every rung of it."""
    if not candidates:
        raise ValueError(
            "successive_halving called with no candidates. A search over nothing returns a "
            "winner of nothing and a multiplicity of zero, both of which read as facts."
        )
    if eta < 2:
        raise ValueError(
            f"eta must be at least 2, got {eta}. An eta of 1 or less never reduces the pool, "
            "so the schedule does not terminate — and a search that cannot end cannot report "
            "how many trials it viewed."
        )
    if initial_budget <= 0:
        raise ValueError(f"initial_budget must be positive, got {initial_budget}")

    rounds: list[HalvingRound] = []
    pool, budget = tuple(candidates), initial_budget
    while True:
        scored = tuple((c, score(c, budget)) for c in pool)
        # Sort by score descending, then by NAME — never by pool order. A tie broken by
        # iteration order makes the search's answer depend on how the caller happened to list
        # its candidates, which is not a property of the alphas.
        ordered = sorted(scored, key=lambda pair: (-pair[1], pair[0]))
        keep = max(1, len(pool) // eta)
        survivors = tuple(c for c, _ in ordered[:keep])

        rounds.append(
            HalvingRound(
                round_index=len(rounds),
                budget=budget,
                configs=pool,
                survivors=survivors,
                scores=scored,
            )
        )
        if len(pool) == 1:
            break
        pool, budget = survivors, budget * eta

    return HalvingResult(rounds=tuple(rounds), winner=rounds[-1].survivors[0])
