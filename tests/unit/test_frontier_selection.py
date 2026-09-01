"""The frontier, collapsed so near-variants count once  (§6 M19).

This is what makes the Pareto sort and the correlation clustering live code rather than two
correct modules nothing calls. A frontier of twelve that is really three ideas with four
variants each overstates what the search found, and feeds twelve correlated entries into a
multiplicity correction that assumes it counts distinct attempts.

The order matters: sort FIRST, then cluster the survivors. Clustering the whole population
first would let a dominated variant represent a cluster whose frontier member it is strictly
worse than.
"""

from __future__ import annotations

import pytest

from pips.selection.frontier import select_frontier
from pips.selection.pareto import Candidate, Direction, Objective, dominates

RETURN = Objective("net_return", Direction.MAXIMIZE)
DRAWDOWN = Objective("max_drawdown", Direction.MINIMIZE)
TWO = [RETURN, DRAWDOWN]

BASE = [((t * 37) % 101 - 50) / 1000 for t in range(101)]
OTHER = [((t * 53) % 101 - 50) / 1000 for t in range(101)]


def variant(shape: list[float], amount: float, offset: int) -> list[float]:
    return [v + ((t * 29 + offset * 17) % 97 - 48) / 1000 * amount for t, v in enumerate(shape)]


def test_near_variants_on_the_frontier_collapse_to_one_representative() -> None:
    candidates = [
        Candidate(f"v{i}", {"net_return": 0.10 + 0.01 * i, "max_drawdown": 0.05 + 0.01 * i})
        for i in range(4)
    ]
    series = {f"v{i}": variant(BASE, 0.05, i) for i in range(4)}
    selection = select_frontier(candidates, TWO, series, threshold=0.2)

    assert len(selection.representatives) == 1
    assert selection.considered == 4
    assert selection.collapsed == 3


def test_distinct_ideas_on_the_frontier_all_survive() -> None:
    candidates = [
        Candidate("a", {"net_return": 0.20, "max_drawdown": 0.20}),
        Candidate("b", {"net_return": 0.05, "max_drawdown": 0.02}),
    ]
    series = {"a": BASE, "b": OTHER}
    selection = select_frontier(candidates, TWO, series, threshold=0.2)
    assert {c.id for c in selection.representatives} == {"a", "b"}
    assert selection.collapsed == 0


def test_dominated_candidates_never_reach_the_clustering() -> None:
    """Sort first, then cluster. The other order lets a dominated variant speak for a cluster.

    `loser` correlates with `winner` and is strictly worse on both objectives. Clustering first
    would put them together and could return `loser` as the representative of an idea whose
    better version was right there.
    """
    candidates = [
        Candidate("winner", {"net_return": 0.30, "max_drawdown": 0.05}),
        Candidate("loser", {"net_return": 0.10, "max_drawdown": 0.25}),
    ]
    series = {"winner": BASE, "loser": variant(BASE, 0.02, 1)}
    selection = select_frontier(candidates, TWO, series, threshold=0.2)
    assert [c.id for c in selection.representatives] == ["winner"]
    assert selection.considered == 1, "only the frontier is clustered"


def test_a_frontier_member_without_a_returns_series_is_refused() -> None:
    """Keeping it would make it its own cluster and inflate the count of distinct ideas.

    It cannot be compared to anything, which is not the same as being different from
    everything — the distinction the whole module exists to preserve.
    """
    candidates = [
        Candidate("a", {"net_return": 0.20, "max_drawdown": 0.20}),
        Candidate("b", {"net_return": 0.05, "max_drawdown": 0.02}),
    ]
    with pytest.raises(ValueError, match="no daily returns"):
        select_frontier(candidates, TWO, {"a": BASE}, threshold=0.2)


def test_a_representative_never_dominates_its_own_cluster_mates() -> None:
    """The arbitrariness is structural, and stating it is the honest thing to do.

    Everything in a cluster came off the same front, so by definition none dominates another.
    There is no 'best' member being computed and no weights being invented to find one — the
    representative is the first in input order and the rest are REPORTED, not discarded.
    """
    candidates = [
        Candidate(f"v{i}", {"net_return": 0.10 + 0.01 * i, "max_drawdown": 0.05 + 0.01 * i})
        for i in range(4)
    ]
    series = {f"v{i}": variant(BASE, 0.05, i) for i in range(4)}
    selection = select_frontier(candidates, TWO, series, threshold=0.2)

    by_id = {c.id: c for c in candidates}
    for cluster in selection.clusters:
        rep = by_id[cluster.representative]
        for member in cluster.members:
            assert not dominates(rep, by_id[member], TWO)
            assert not dominates(by_id[member], rep, TWO)


def test_every_frontier_member_is_reported_somewhere() -> None:
    # Nothing may vanish between the sort and the selection: a collapsed candidate is still a
    # trial that was run and viewed (rule 4).
    candidates = [
        Candidate(
            f"v{i}", {"net_return": 0.10 + 0.01 * (i % 2), "max_drawdown": 0.05 + 0.01 * (i % 2)}
        )
        for i in range(6)
    ]
    series = {f"v{i}": variant(BASE if i % 2 else OTHER, 0.05, i) for i in range(6)}
    selection = select_frontier(candidates, TWO, series, threshold=0.2)

    reported = [m for c in selection.clusters for m in c.members]
    assert sorted(reported) == sorted(c.id for c in selection.frontier)
    assert len(reported) == selection.considered


def test_an_empty_population_selects_nothing() -> None:
    selection = select_frontier([], TWO, {}, threshold=0.2)
    assert selection.representatives == ()
    assert selection.considered == 0


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "frontier-selection" in CHECK_REGISTRY
    resolve_check("frontier-selection")


def test_the_representative_is_the_one_the_clustering_named() -> None:
    """The wiring must pass the choice through, not make its own.

    Returning some other cluster member gives the same counts and the same non-domination
    property, so every test above still passes while the selection reports a different config
    than the one it claims in `clusters`.
    """
    candidates = [
        Candidate(f"v{i}", {"net_return": 0.10 + 0.01 * i, "max_drawdown": 0.05 + 0.01 * i})
        for i in range(4)
    ]
    series = {f"v{i}": variant(BASE, 0.05, i) for i in range(4)}
    selection = select_frontier(candidates, TWO, series, threshold=0.2)
    assert [c.id for c in selection.representatives] == [
        c.representative for c in selection.clusters
    ]


def test_the_default_linkage_does_not_chain_the_frontier_into_one_idea() -> None:
    """Single linkage would walk a whole frontier into one cluster through intermediates.

    Three mutually non-dominated candidates: `a` and `c` are unrelated, `b` sits between them.
    Under single linkage all three become one idea and the search reports that it found one
    thing; under complete linkage `a` and `c` stay apart, which is what they are.
    """
    middle = [(x + y) / 2 for x, y in zip(BASE, OTHER, strict=True)]
    candidates = [
        Candidate("a", {"net_return": 0.30, "max_drawdown": 0.30}),
        Candidate("b", {"net_return": 0.20, "max_drawdown": 0.15}),
        Candidate("c", {"net_return": 0.10, "max_drawdown": 0.02}),
    ]
    series = {"a": BASE, "b": middle, "c": OTHER}
    selection = select_frontier(candidates, TWO, series, threshold=0.55)
    assert selection.considered == 3, "all three must reach the clustering"
    assert not any({"a", "c"} <= set(cluster.members) for cluster in selection.clusters), (
        "the default must not chain a and c together through b"
    )
