"""Non-dominated (Pareto) sort  (§6 M19).

M19 selects across net return, DSR, MDD/CVaR, cost share, turnover/order count and stability.
These do not reduce to one number, and inventing weights to make them reduce is how a search
picks whatever the weights favoured. A Pareto sort answers the question that can be answered
without weights: which candidates is nothing strictly better than.

**The direction of each objective is the whole risk.** Return is maximised, drawdown is
minimised, and a single objective pointed the wrong way silently inverts part of the frontier
while still producing a frontier — the right shape, the wrong members, and no way to tell from
the output. So direction is DECLARED per objective and never inferred from the name.
"""

from __future__ import annotations

import itertools

import pytest

from pips.selection.pareto import (
    Candidate,
    Direction,
    Objective,
    dominates,
    non_dominated_sort,
)

RETURN = Objective("net_return", Direction.MAXIMIZE)
DRAWDOWN = Objective("max_drawdown", Direction.MINIMIZE)
TWO = [RETURN, DRAWDOWN]


def candidate(cid: str, ret: float, dd: float, **extra: float) -> Candidate:
    return Candidate(cid, {"net_return": ret, "max_drawdown": dd, **extra})


# ------------------------------------------------------------ dominance ----------------


def test_better_on_both_objectives_dominates() -> None:
    better = candidate("a", ret=0.20, dd=0.05)
    worse = candidate("b", ret=0.10, dd=0.15)
    assert dominates(better, worse, TWO)
    assert not dominates(worse, better, TWO)


def test_better_on_one_and_equal_on_the_other_dominates() -> None:
    assert dominates(candidate("a", 0.20, 0.05), candidate("b", 0.10, 0.05), TWO)


def test_a_trade_off_is_not_domination() -> None:
    # Higher return AND higher drawdown: neither is strictly better. This is the whole point —
    # a frontier exists because these two cannot be ranked without a weight nobody has.
    high = candidate("a", ret=0.30, dd=0.25)
    safe = candidate("b", ret=0.10, dd=0.02)
    assert not dominates(high, safe, TWO)
    assert not dominates(safe, high, TWO)


def test_identical_candidates_do_not_dominate_each_other() -> None:
    """The trap that empties the frontier.

    Dominance needs BOTH clauses: at least as good everywhere, AND strictly better somewhere.
    Drop the second and every candidate dominates its own twin, so tied pairs eliminate each
    other and the frontier loses exactly the results that were reproduced.
    """
    a = candidate("a", 0.20, 0.05)
    b = candidate("b", 0.20, 0.05)
    assert not dominates(a, b, TWO)
    assert not dominates(b, a, TWO)


def test_nothing_dominates_itself() -> None:
    a = candidate("a", 0.20, 0.05)
    assert not dominates(a, a, TWO)


# ------------------------------------------------------------ direction ----------------


def test_the_declared_direction_is_actually_consulted() -> None:
    """Flip one objective's direction and the verdict must flip with it.

    A sort that ignores direction still returns a plausible frontier. This is the only test
    that can tell the difference.
    """
    low_dd = candidate("a", 0.10, 0.05)
    high_dd = candidate("b", 0.10, 0.30)
    assert dominates(low_dd, high_dd, [RETURN, DRAWDOWN])
    flipped = [RETURN, Objective("max_drawdown", Direction.MAXIMIZE)]
    assert dominates(high_dd, low_dd, flipped)


def test_minimising_a_value_equals_maximising_its_negation() -> None:
    # The structural statement of the same thing: direction is a real comparison flip, not a
    # label that happens to be carried alongside.
    minimise = non_dominated_sort([candidate("a", 0.1, 0.05), candidate("b", 0.1, 0.30)], TWO)
    negated = non_dominated_sort(
        [
            Candidate("a", {"net_return": 0.1, "neg_dd": -0.05}),
            Candidate("b", {"net_return": 0.1, "neg_dd": -0.30}),
        ],
        [RETURN, Objective("neg_dd", Direction.MAXIMIZE)],
    )
    assert [[c.id for c in f] for f in minimise] == [[c.id for c in f] for f in negated]


# ------------------------------------------------------------ the fronts ---------------


def test_the_first_front_is_dominated_by_nobody() -> None:
    population = [
        candidate("best-return", 0.30, 0.25),
        candidate("best-risk", 0.05, 0.01),
        candidate("balanced", 0.20, 0.10),
        candidate("dominated", 0.04, 0.30),
    ]
    fronts = non_dominated_sort(population, TWO)
    assert {c.id for c in fronts[0]} == {"best-return", "best-risk", "balanced"}
    assert [c.id for c in fronts[1]] == ["dominated"]


def test_every_member_of_a_later_front_is_dominated_from_the_one_before() -> None:
    """The defining property of the layering, which a rank-by-count algorithm does not give.

    Counting how many candidates dominate each one and bucketing by the count produces
    plausible layers that do not satisfy this.
    """
    population = [
        candidate(f"c{i}", ret=0.05 * (i % 4), dd=0.02 * (i % 5) + 0.01 * (i % 3))
        for i in range(24)
    ]
    fronts = non_dominated_sort(population, TWO)
    for earlier, later in itertools.pairwise(fronts):
        for member in later:
            assert any(dominates(other, member, TWO) for other in earlier), member.id


def test_the_fronts_partition_the_population() -> None:
    # Every candidate appears exactly once across all fronts. An off-by-one in the layering
    # loop drops or duplicates candidates, and a selection that quietly loses a trial is a
    # selection whose denominator is wrong (rule 4).
    population = [candidate(f"c{i}", ret=0.01 * (i % 7), dd=0.01 * (i % 5)) for i in range(30)]
    fronts = non_dominated_sort(population, TWO)
    seen = [c.id for front in fronts for c in front]
    assert sorted(seen) == sorted(c.id for c in population)
    assert len(seen) == len(set(seen))


def test_ties_all_survive_on_the_same_front() -> None:
    population = [candidate("a", 0.2, 0.05), candidate("b", 0.2, 0.05), candidate("c", 0.1, 0.9)]
    fronts = non_dominated_sort(population, TWO)
    assert {c.id for c in fronts[0]} == {"a", "b"}


def test_input_order_is_preserved_within_a_front() -> None:
    # Rule 1: the same population must give byte-identical output, so no set iteration order
    # may reach the result.
    population = [candidate(c, 0.2, 0.05) for c in "dcba"]
    assert [c.id for c in non_dominated_sort(population, TWO)[0]] == ["d", "c", "b", "a"]


def test_an_empty_population_yields_no_fronts() -> None:
    assert non_dominated_sort([], TWO) == []


# ------------------------------------------------------------ refusals -----------------


def test_selecting_on_no_objectives_is_refused() -> None:
    """With nothing to compare, nothing dominates anything and the frontier is the whole search.

    That is not an empty result — it is a full one, and it looks like every candidate survived
    selection on merit.
    """
    with pytest.raises(ValueError, match="at least one objective"):
        non_dominated_sort([candidate("a", 0.2, 0.05)], [])


def test_a_candidate_missing_an_objective_is_refused() -> None:
    # Defaulting a missing metric to zero would place the candidate wherever zero happens to
    # rank, which for a drawdown is the best possible score.
    broken = Candidate("no-dd", {"net_return": 0.2})
    with pytest.raises(ValueError, match="max_drawdown"):
        non_dominated_sort([broken, candidate("b", 0.1, 0.1)], TWO)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_objective_is_refused(bad: float) -> None:
    """NaN is the dangerous one: every comparison with it is False.

    So a NaN candidate dominates nothing and is dominated by nothing, which lands it on the
    FIRST front — a broken measurement promoted to the frontier and reported as a winner.
    """
    with pytest.raises(ValueError, match="finite"):
        non_dominated_sort([candidate("bad", 0.2, bad), candidate("b", 0.1, 0.1)], TWO)


def test_duplicate_candidate_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        non_dominated_sort([candidate("a", 0.2, 0.05), candidate("a", 0.1, 0.9)], TWO)


def test_a_duplicated_objective_name_is_refused() -> None:
    # Two entries for one name silently double its weight in the comparison, and if they
    # disagree on direction the result depends on which is checked first.
    with pytest.raises(ValueError, match="duplicate"):
        non_dominated_sort([candidate("a", 0.2, 0.05)], [RETURN, RETURN])


def test_extra_metrics_the_objectives_do_not_name_are_ignored() -> None:
    # A registry row carries every metric it recorded; selecting on two of them is normal.
    rich = candidate("a", 0.2, 0.05, sharpe=1.4, n_trades=812)
    assert non_dominated_sort([rich], TWO)[0][0].id == "a"


def test_the_layering_loop_is_bounded_rather_than_spinning() -> None:
    """A comparator that says a candidate dominates itself leaves no non-dominated member.

    The loop would then never empty its remainder. Romano-Wolf hung a ten-minute mutation
    batch exactly this way; a stall is worse than a failure because it reports nothing at all.
    """
    import pips.selection.pareto as module

    original = module.dominates
    try:
        module.dominates = lambda a, b, objectives: True
        with pytest.raises(RuntimeError, match="dominat"):
            non_dominated_sort([candidate("a", 0.2, 0.05), candidate("b", 0.1, 0.1)], TWO)
    finally:
        module.dominates = original


def test_there_is_never_more_than_one_front_per_candidate() -> None:
    """The structural bound the loop relies on: each front removes at least one candidate.

    Asserting it here is what lets the loop be written with a hard iteration limit instead of
    `while remaining`, so a broken comparator FAILS rather than spinning.
    """
    population = [candidate(f"c{i}", ret=-0.01 * i, dd=0.01 * i) for i in range(12)]
    fronts = non_dominated_sort(population, TWO)
    assert 0 < len(fronts) <= len(population)
    assert all(front for front in fronts), "no front may be empty"


# ------------------------------------- objectives must be numbers `[C-SEL-01]` -----


def test_a_non_numeric_objective_is_refused_by_name() -> None:
    """The metric channel carries more than floats now — `stability.bootstrap_ci` is an interval
    — so an objective naming one has to fail legibly rather than as a TypeError inside a sort.

    A comparison error raised from `sorted` names neither the candidate nor the metric, and the
    reader is left bisecting a frontier to find which value was not a number.
    """
    bad = Candidate(id="A01", metrics={"net_return": (0.1, 0.3), "max_drawdown": 0.02})
    other = Candidate(id="A02", metrics={"net_return": 0.05, "max_drawdown": 0.01})

    with pytest.raises(TypeError, match="net_return"):
        non_dominated_sort([bad, other], [RETURN])


def test_a_boolean_objective_is_refused() -> None:
    """`True` is an `int` in Python and would sort as 1.0 — the same slip that would have made a
    flag rank as a perfect deflated Sharpe."""
    flag = Candidate(id="A01", metrics={"net_return": True})
    with pytest.raises(TypeError, match="net_return"):
        non_dominated_sort([flag], [RETURN])


def test_a_non_objective_metric_may_be_anything() -> None:
    """Only the axes have to be numbers. An interval riding alongside them is the point."""
    rich = Candidate(id="A01", metrics={"net_return": 0.05, "bootstrap_ci": (0.1, 0.3)})
    fronts = non_dominated_sort([rich], [RETURN])
    assert [c.id for c in fronts[0]] == ["A01"]


def test_dominates_refuses_a_non_numeric_objective_too() -> None:
    """`dominates` is public and skips `non_dominated_sort`'s validation, so it carries its own
    check — reachable by a caller comparing two candidates directly."""
    bad = Candidate(id="A01", metrics={"net_return": (0.1, 0.3)})
    other = Candidate(id="A02", metrics={"net_return": 0.05})

    with pytest.raises(TypeError, match="net_return"):
        dominates(bad, other, [RETURN])
