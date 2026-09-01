"""Correlation clustering, so near-variants count once  (§6 M19).

A search that sweeps lookback 20, 21, 22, 23 produces four configs that are the same idea. All
four can sit on the Pareto frontier, and the frontier then reports four survivors where there
is one. That overstates what the selection found, and it feeds four correlated entries into a
multiplicity correction (§3.6) that assumes it is counting distinct attempts — so the error
does not stay cosmetic, it makes the deflation too weak in the direction that flatters.

The frontier is therefore collapsed on ``1 - corr`` of daily returns. Nothing is discarded
silently: every collapsed member is reported, because a selection that quietly loses candidates
has the wrong denominator (rule 4).

**Complete linkage, not single.** Single linkage merges two clusters when ANY pair is close
enough, so A joins C whenever some B sits between them — and repeated across a population that
walks the whole search into one cluster, one marginal similarity at a time. Complete linkage
requires EVERY pair in a cluster to be within the threshold. The difference between the two is
pinned by a test rather than asserted here, so the default cannot be changed quietly.

**``1 - corr``, per §6, so an inverted series sits at distance 2.** The alternative convention
``1 - |corr|`` is defensible and gives the opposite answer: it would call a short variant of a
long strategy the same idea. Under the spec's convention it is a different one, and a
long/short pair of the same rule is never collapsed.

Three refusals, each of which otherwise yields a number that exists and means nothing:

* **a flat series** — zero variance makes the correlation 0/0, and reading undefined as
  "uncorrelated with everything" makes a config that never traded maximally distinct, so it
  survives clustering as a novel idea;
* **unequal lengths** — truncating to the shorter aligns at index 0, which is only correct when
  both start on the same day. Alignment is the caller's problem and guessing it compares one
  config's day 1 against another's day 30;
* **fewer than three observations** — any two points correlate perfectly with any other two.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "Cluster",
    "ClusterReport",
    "Linkage",
    "cluster_by_correlation",
    "correlation_distance",
]

MIN_OBSERVATIONS = 3
MAX_DISTANCE = 2.0


class Linkage(enum.Enum):
    COMPLETE = "complete"
    """Every pair in a cluster is within the threshold. The default: it cannot chain."""

    SINGLE = "single"
    """Any one pair suffices. Kept so the chaining failure can be demonstrated, not used."""


@dataclass(frozen=True)
class Cluster:
    members: tuple[str, ...]
    representative: str


@dataclass(frozen=True)
class ClusterReport:
    clusters: tuple[Cluster, ...]
    inputs: int
    threshold: float
    linkage: Linkage

    @property
    def collapsed(self) -> int:
        """How many candidates the clustering removed. Reported, never merely implied."""
        return self.inputs - len(self.clusters)


def _checked(name: str, series: Sequence[float]) -> list[float]:
    values = list(series)
    if len(values) < MIN_OBSERVATIONS:
        raise ValueError(
            f"{name} has {len(values)} observations; at least {MIN_OBSERVATIONS} are needed. "
            "Any two points correlate perfectly with any other two."
        )
    for value in values:
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a non-finite observation ({value!r})")
    return values


def correlation_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """``1 - pearson(a, b)``. Zero for the same shape, 2 for its inverse."""
    left = _checked("the first series", a)
    right = _checked("the second series", b)
    if len(left) != len(right):
        raise ValueError(
            f"series length mismatch ({len(left)} vs {len(right)}). Alignment is the caller's "
            "problem: truncating to the shorter one aligns at index 0, which compares one "
            "config's first day against another's thirtieth unless both start together."
        )

    n = len(left)
    mean_l = sum(left) / n
    mean_r = sum(right) / n
    dev_l = [v - mean_l for v in left]
    dev_r = [v - mean_r for v in right]
    var_l = sum(v * v for v in dev_l)
    var_r = sum(v * v for v in dev_r)
    if var_l <= 0 or var_r <= 0:
        raise ValueError(
            "a series has zero variance, so its correlation is 0/0. Refusing rather than "
            "reading undefined as uncorrelated: that would make a config which never traded "
            "maximally distinct from everything and let it survive clustering as a novel idea."
        )
    covariance = sum(x * y for x, y in zip(dev_l, dev_r, strict=True))
    return 1.0 - covariance / math.sqrt(var_l * var_r)


def _linkage_distance(
    left: Sequence[str],
    right: Sequence[str],
    distances: Mapping[tuple[str, str], float],
    linkage: Linkage,
) -> float:
    pairs = [distances[(a, b)] for a in left for b in right]
    return max(pairs) if linkage is Linkage.COMPLETE else min(pairs)


def cluster_by_correlation(
    series: Mapping[str, Sequence[float]],
    *,
    threshold: float,
    linkage: Linkage = Linkage.COMPLETE,
) -> ClusterReport:
    """Group configs whose returns move together; one representative each."""
    if not 0.0 <= threshold <= MAX_DISTANCE:
        raise ValueError(
            f"threshold {threshold} is outside the range of `1 - corr`, which is [0, "
            f"{MAX_DISTANCE}]. Above it everything is one cluster; below it nothing ever "
            "merges. Both are well-formed answers to a question nobody asked."
        )

    names = list(series)
    if not names:
        return ClusterReport((), 0, threshold, linkage)

    distances: dict[tuple[str, str], float] = {}
    for i, a in enumerate(names):
        for b in names[i:]:
            d = 0.0 if a == b else correlation_distance(series[a], series[b])
            distances[(a, b)] = distances[(b, a)] = d

    # Input order is preserved throughout so the same population gives byte-identical output
    # (rule 1): candidate pairs are scanned in order and ties therefore resolve the same way
    # on every run.
    groups: list[list[str]] = [[name] for name in names]
    for _ in range(len(names)):  # each pass merges at most one pair, so N passes suffice
        best: tuple[float, int, int] | None = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                d = _linkage_distance(groups[i], groups[j], distances, linkage)
                if d <= threshold and (best is None or d < best[0]):
                    best = (d, i, j)
        if best is None:
            break
        _, i, j = best
        groups[i] = groups[i] + groups[j]
        del groups[j]

    clusters = tuple(
        # The representative is the FIRST member in input order. Which variant speaks for a
        # cluster is a real choice, and the sort's objectives are the right basis for it —
        # which this module does not have. Naming the rule keeps the arbitrariness visible
        # rather than leaving it to whatever the merge order happened to produce.
        Cluster(members=tuple(group), representative=group[0])
        for group in groups
    )
    return ClusterReport(clusters, len(names), threshold, linkage)
