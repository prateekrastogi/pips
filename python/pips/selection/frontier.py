"""The frontier, collapsed so near-variants count once  (§6 M19).

This is the caller that makes :mod:`pips.selection.pareto` and :mod:`pips.selection.cluster`
live code rather than two correct modules nothing consults — the standing lesson from
``check_unexplained_ratio_jump``, which passed its own unit tests for a milestone while the
runner never called it.

**Sort first, then cluster the survivors.** The other order lets a dominated variant represent a
cluster whose frontier member it is strictly worse than: clustering is about shape, and shape
says nothing about which of two correlated configs is better.

**A frontier member with no returns series is refused.** It cannot be compared to anything,
which is not the same as being different from everything, and keeping it would make it its own
cluster and inflate the count of distinct ideas — the precise error this module exists to stop.

**The representative is arbitrary, by construction, and said so.** Everything in a cluster came
off the same front, so none dominates another; there is no "best" member to compute and no
weights are invented to find one. The first in input order speaks for the cluster and every
other member is REPORTED, because a collapsed candidate is still a trial that was run and
viewed (rule 4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pips.selection.cluster import Cluster, Linkage, cluster_by_correlation
from pips.selection.pareto import Candidate, Objective, non_dominated_sort

__all__ = ["FrontierSelection", "select_frontier"]


@dataclass(frozen=True)
class FrontierSelection:
    representatives: tuple[Candidate, ...]
    """One per cluster: what the search actually found, as distinct ideas."""

    frontier: tuple[Candidate, ...]
    """Front 0 before collapsing, so the reduction can be audited."""

    clusters: tuple[Cluster, ...]
    considered: int
    threshold: float

    @property
    def collapsed(self) -> int:
        return self.considered - len(self.representatives)


def select_frontier(
    candidates: Sequence[Candidate],
    objectives: Sequence[Objective],
    series: Mapping[str, Sequence[float]],
    *,
    threshold: float,
    linkage: Linkage = Linkage.COMPLETE,
) -> FrontierSelection:
    """Take front 0, collapse correlated members, and report what was collapsed."""
    fronts = non_dominated_sort(candidates, objectives)
    if not fronts:
        return FrontierSelection((), (), (), 0, threshold)
    frontier = fronts[0]

    missing = [c.id for c in frontier if c.id not in series]
    if missing:
        raise ValueError(
            f"frontier members have no daily returns: {missing}. Refusing rather than passing "
            "them through: a candidate that cannot be compared is not a candidate that differs "
            "from everything, and keeping it would make it its own cluster and overstate how "
            "many distinct ideas survived."
        )

    report = cluster_by_correlation(
        {c.id: series[c.id] for c in frontier}, threshold=threshold, linkage=linkage
    )
    by_id = {c.id: c for c in frontier}
    return FrontierSelection(
        representatives=tuple(by_id[c.representative] for c in report.clusters),
        frontier=tuple(frontier),
        clusters=report.clusters,
        considered=len(frontier),
        threshold=threshold,
    )
