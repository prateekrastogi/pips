"""Successive halving  (§6 M15, constitution rule 4).

Successive halving is a budget allocator: run every candidate cheaply, keep the best fraction,
give the survivors more resources, repeat. It is the right way to search a large space on a
small budget — and it has one specific way of lying about itself.

**It views far more trials than it reports.** A run over 64 configurations that ends with one
winner has *evaluated* 64 in the first round, 16 in the second, 4 in the third. Rule 4 is
explicit: *every viewed trial counts*. If the multiplicity ledger sees the winner and not the
85 evaluations behind it, every p-value downstream is computed against an M that is off by two
orders of magnitude — and it is off in the direction that makes results look significant.

That is the load-bearing test here, and it is not about halving at all. It is about the count.

The second trap is subtler: **the winner is the best under the LARGEST budget, not the best
score seen anywhere.** A configuration that looked brilliant on a tiny budget and mediocre on a
full one has not earned anything; taking its early score would be cherry-picking across budget
levels, which is the same error as cherry-picking across parameter values.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.search.halving import successive_halving


def scorer(table: dict[tuple[str, int], float]):  # type: ignore[no-untyped-def]
    """A deterministic injected scorer, so the search is pure and the tests are exact."""

    def score(config: str, budget: int) -> Decimal:
        return Decimal(str(table.get((config, budget), 0.0)))

    return score


def flat_scorer(ranking: dict[str, float]):  # type: ignore[no-untyped-def]
    def score(config: str, budget: int) -> Decimal:
        return Decimal(str(ranking[config]))

    return score


CONFIGS = tuple(f"c{i:02d}" for i in range(64))
RANKING = {c: float(len(CONFIGS) - i) for i, c in enumerate(CONFIGS)}


# ------------------------------------------------------------ the count ----------------


def test_every_evaluation_counts_as_a_viewed_trial() -> None:
    """Rule 4, at the point where a search is most tempted to forget it.

    64 configs at eta 4: 64 evaluated, then 16, then 4, then 1. That is 85 trials viewed, not
    1. A multiplicity ledger fed the winner alone corrects for one test when eighty-five were
    run, and understates in the direction that manufactures significance.
    """
    result = successive_halving(CONFIGS, flat_scorer(RANKING), initial_budget=1, eta=4)
    assert [len(r.configs) for r in result.rounds] == [64, 16, 4, 1]
    assert result.trials_viewed == 85
    assert result.trials_viewed != 1


def test_the_viewed_count_is_the_sum_of_the_rounds_not_the_survivors() -> None:
    result = successive_halving(CONFIGS, flat_scorer(RANKING), initial_budget=1, eta=4)
    assert result.trials_viewed == sum(len(r.configs) for r in result.rounds)
    assert result.configs_viewed == 64


def test_a_config_eliminated_in_the_first_round_is_still_in_the_record() -> None:
    # Deletion does not un-count a trial (rule 4). The record has to carry the losers, or the
    # ledger cannot count them.
    result = successive_halving(CONFIGS, flat_scorer(RANKING), initial_budget=1, eta=4)
    worst = CONFIGS[-1]
    assert worst in result.rounds[0].configs
    assert worst not in result.rounds[0].survivors
    assert worst in result.all_configs_viewed


# ------------------------------------------------------------ the winner ---------------


def test_the_winner_is_judged_at_the_largest_budget_not_at_its_best_moment() -> None:
    """Cherry-picking across budget levels is cherry-picking.

    `cheap` is spectacular at budget 1 and mediocre at budget 4; `deep` is the reverse. Taking
    the best score SEEN would crown `cheap` on a number produced by an evaluation nobody would
    trade on.
    """
    configs = ("cheap", "deep", "bad1", "bad2")
    table = {
        ("cheap", 1): 100.0,
        ("cheap", 2): 2.0,
        ("deep", 1): 3.0,
        ("deep", 2): 50.0,
        ("bad1", 1): 1.0,
        ("bad2", 1): 0.5,
    }
    result = successive_halving(configs, scorer(table), initial_budget=1, eta=2)
    assert result.winner == "deep"


def test_ties_do_not_depend_on_the_order_the_caller_listed_candidates() -> None:
    """Re-running the SAME input is not a determinism test.

    Python's sort is stable, so without an explicit tie-break the result is already identical
    across repeated runs on identical input — my first version asserted exactly that, and a
    mutation removing the tie-break killed nothing.

    The property that matters is stronger: with every candidate scoring the same, the winner
    must not depend on the order the caller happened to list them. Otherwise the search's
    answer is a fact about the caller's loop, not about the alphas.
    """
    tied = flat_scorer(dict.fromkeys(CONFIGS, 1.0))
    forwards = successive_halving(CONFIGS, tied, initial_budget=1, eta=4)
    backwards = successive_halving(tuple(reversed(CONFIGS)), tied, initial_budget=1, eta=4)
    rotated = successive_halving(CONFIGS[7:] + CONFIGS[:7], tied, initial_budget=1, eta=4)

    assert forwards.winner == backwards.winner == rotated.winner
    assert forwards.trials_viewed == backwards.trials_viewed == rotated.trials_viewed


def test_repeating_the_same_search_gives_the_same_result() -> None:
    tied = flat_scorer(dict.fromkeys(CONFIGS, 1.0))
    first = successive_halving(CONFIGS, tied, initial_budget=1, eta=4)
    for _ in range(3):
        assert successive_halving(CONFIGS, tied, initial_budget=1, eta=4) == first


# ------------------------------------------------------------ the schedule -------------


def test_the_budget_multiplies_by_eta_each_round() -> None:
    result = successive_halving(CONFIGS, flat_scorer(RANKING), initial_budget=3, eta=4)
    assert [r.budget for r in result.rounds] == [3, 12, 48, 192]


def test_an_eta_that_does_not_reduce_the_pool_is_refused() -> None:
    for bad in (1, 0, -2):
        with pytest.raises(ValueError, match="eta"):
            successive_halving(CONFIGS, flat_scorer(RANKING), initial_budget=1, eta=bad)


def test_an_empty_candidate_set_is_refused() -> None:
    with pytest.raises(ValueError, match="no candidates"):
        successive_halving((), flat_scorer({}), initial_budget=1, eta=4)


def test_a_non_positive_budget_is_refused() -> None:
    with pytest.raises(ValueError, match="budget"):
        successive_halving(CONFIGS, flat_scorer(RANKING), initial_budget=0, eta=4)


def test_the_search_terminates_on_a_pool_that_does_not_divide_evenly() -> None:
    # 10 configs at eta 3 gives 10 -> 3 -> 1. An implementation that floors to zero survivors
    # loses the winner entirely; one that never reaches 1 does not terminate.
    configs = tuple(f"x{i}" for i in range(10))
    result = successive_halving(
        configs,
        flat_scorer({c: float(10 - i) for i, c in enumerate(configs)}),
        initial_budget=1,
        eta=3,
    )
    assert [len(r.configs) for r in result.rounds] == [10, 3, 1]
    assert result.winner == "x0"
