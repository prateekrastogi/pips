"""Correlation clustering, so near-variants count once  (§6 M19).

A search that sweeps lookback 20, 21, 22, 23 produces four configs that are the same idea. All
four can sit on the Pareto frontier, and the frontier then reports four survivors where there
is one — which overstates how much the selection found and, worse, feeds four correlated
entries into a multiplicity correction that assumes it is counting distinct attempts.

So the frontier is collapsed on `1 - corr` of daily returns: configs that move together are one
cluster and contribute one representative. Nothing is discarded silently — every collapsed
member is reported, because a selection that quietly loses candidates has the wrong denominator
(rule 4).
"""

from __future__ import annotations

import math

import pytest

from pips.selection.cluster import (
    Linkage,
    cluster_by_correlation,
    correlation_distance,
)

# A deterministic, irregular base series. Coprime multiplier so `(a·t) % m` does not cycle
# through a short staircase with a mean of its own.
BASE = [((t * 37) % 101 - 50) / 1000 for t in range(101)]
SHIFTED = [((t * 53) % 101 - 50) / 1000 for t in range(101)]


def scaled(series: list[float], factor: float) -> list[float]:
    return [v * factor for v in series]


def noisy(series: list[float], amount: float, offset: int) -> list[float]:
    return [v + ((t * 29 + offset * 17) % 97 - 48) / 1000 * amount for t, v in enumerate(series)]


# ------------------------------------------------------------ the distance -------------


def test_a_series_has_no_distance_from_itself() -> None:
    assert correlation_distance(BASE, BASE) == pytest.approx(0.0, abs=1e-12)


def test_a_rescaled_series_is_the_same_idea() -> None:
    """Correlation is scale-free, which is the reason to use it.

    Two configs differing only in position size trace the same shape at different amplitudes.
    A distance built on returns themselves would call them different.
    """
    assert correlation_distance(BASE, scaled(BASE, 3.0)) == pytest.approx(0.0, abs=1e-12)


def test_an_inverted_series_is_maximally_distant() -> None:
    """`1 - corr`, per §6, so a perfectly anticorrelated pair sits at distance 2.

    Worth stating because the alternative convention `1 - |corr|` is defensible and gives the
    OPPOSITE answer: it would call a short variant of a long strategy the same idea. Under the
    spec's convention it is a different one, and a long/short pair of the same rule is
    therefore never collapsed.
    """
    assert correlation_distance(BASE, scaled(BASE, -1.0)) == pytest.approx(2.0, abs=1e-12)


def test_unrelated_series_land_near_one() -> None:
    assert 0.5 < correlation_distance(BASE, SHIFTED) < 1.5


# ------------------------------------------------------------ refusals -----------------


def test_a_flat_series_is_refused_rather_than_called_uncorrelated() -> None:
    """A config that never traded has zero variance, so its correlation is 0/0.

    Reading undefined as 'uncorrelated with everything' makes it maximally distinct: it forms
    its own cluster and is reported as a novel idea. It is the absence of a result, not a
    diverse one.
    """
    with pytest.raises(ValueError, match="variance"):
        correlation_distance(BASE, [0.0] * len(BASE))


def test_series_of_different_lengths_are_refused() -> None:
    """Alignment is the caller's problem and it must not be guessed here.

    Truncating to the shorter one aligns at index 0, which is only correct if both start on the
    same day. A config that began a month later would be compared day-1-to-day-1 against
    another's day-30, and the correlation of that is not a number about either of them.
    """
    with pytest.raises(ValueError, match="length"):
        correlation_distance(BASE, BASE[:50])


def test_a_non_finite_observation_is_refused() -> None:
    broken = [*BASE[:-1], math.nan]
    with pytest.raises(ValueError, match="finite"):
        correlation_distance(BASE, broken)


def test_a_series_too_short_to_correlate_is_refused() -> None:
    # Two points are perfectly correlated with any other two points. The number exists and
    # means nothing.
    with pytest.raises(ValueError, match="observations"):
        correlation_distance([0.01, 0.02], [0.03, 0.05])


# ------------------------------------------------------------ clustering ---------------


def test_near_variants_collapse_into_one_cluster() -> None:
    series = {f"lookback-{n}": noisy(BASE, 0.05, n) for n in (20, 21, 22, 23)}
    report = cluster_by_correlation(series, threshold=0.2)
    assert len(report.clusters) == 1
    assert set(report.clusters[0].members) == set(series)


def test_genuinely_different_strategies_stay_apart() -> None:
    series = {"a": BASE, "b": SHIFTED}
    report = cluster_by_correlation(series, threshold=0.2)
    assert len(report.clusters) == 2


def test_complete_linkage_refuses_to_chain() -> None:
    """The failure that makes single linkage unusable here.

    With A~B close and B~C close but A~C far, single linkage merges all three through B — and
    repeated across a population it walks the whole search into one cluster, one marginal
    similarity at a time. Complete linkage requires every pair in a cluster to be within the
    threshold, so A and C are never grouped just because B sits between them.
    """
    middle = [(a + b) / 2 for a, b in zip(BASE, SHIFTED, strict=True)]
    series = {"a": BASE, "b": middle, "c": SHIFTED}
    report = cluster_by_correlation(series, threshold=0.55, linkage=Linkage.COMPLETE)
    assert not any({"a", "c"} <= set(c.members) for c in report.clusters), (
        "a and c are far apart and must not be joined through b"
    )


def test_single_linkage_does_chain_which_is_why_it_is_not_the_default() -> None:
    # Pinned so the difference between the two is a tested fact rather than a claim in a
    # docstring, and so the default cannot be changed without this failing.
    middle = [(a + b) / 2 for a, b in zip(BASE, SHIFTED, strict=True)]
    series = {"a": BASE, "b": middle, "c": SHIFTED}
    chained = cluster_by_correlation(series, threshold=0.55, linkage=Linkage.SINGLE)
    complete = cluster_by_correlation(series, threshold=0.55, linkage=Linkage.COMPLETE)
    assert len(chained.clusters) < len(complete.clusters)


def test_the_default_linkage_is_complete() -> None:
    middle = [(a + b) / 2 for a, b in zip(BASE, SHIFTED, strict=True)]
    series = {"a": BASE, "b": middle, "c": SHIFTED}
    assert cluster_by_correlation(series, threshold=0.55).clusters == (
        cluster_by_correlation(series, threshold=0.55, linkage=Linkage.COMPLETE).clusters
    )


# ------------------------------------------------------------ accounting ---------------


def test_every_input_appears_in_exactly_one_cluster() -> None:
    series = {f"s{i}": noisy(BASE if i % 2 else SHIFTED, 0.4, i) for i in range(12)}
    report = cluster_by_correlation(series, threshold=0.3)
    members = [m for c in report.clusters for m in c.members]
    assert sorted(members) == sorted(series)
    assert len(members) == len(set(members))


def test_the_representative_is_named_and_the_collapsed_members_are_reported() -> None:
    # A frontier of four that becomes one must say it collapsed three, not just return one.
    series = {f"lookback-{n}": noisy(BASE, 0.05, n) for n in (20, 21, 22, 23)}
    report = cluster_by_correlation(series, threshold=0.2)
    only = report.clusters[0]
    assert only.representative in only.members
    assert report.collapsed == 3
    assert report.inputs == 4


def test_clustering_is_deterministic_in_membership_and_order() -> None:
    series = {f"s{i}": noisy(BASE if i % 3 else SHIFTED, 0.5, i) for i in range(9)}
    first = cluster_by_correlation(series, threshold=0.4)
    second = cluster_by_correlation(dict(series), threshold=0.4)
    assert [c.members for c in first.clusters] == [c.members for c in second.clusters]
    assert [c.representative for c in first.clusters] == [c.representative for c in second.clusters]


def test_the_representative_is_the_first_member_in_input_order() -> None:
    """Deterministic and STATED, rather than whichever the merge order happened to leave.

    Which variant represents a cluster is a real choice; the sort's objectives are the right
    basis for it and this module does not have them. Naming the rule keeps the arbitrariness
    visible instead of burying it in a merge loop.
    """
    series = {f"lookback-{n}": noisy(BASE, 0.05, n) for n in (23, 20, 22, 21)}
    report = cluster_by_correlation(series, threshold=0.2)
    assert report.clusters[0].representative == "lookback-23"


# ------------------------------------------------------------ edges --------------------


def test_a_single_series_is_one_cluster() -> None:
    report = cluster_by_correlation({"only": BASE}, threshold=0.2)
    assert [c.members for c in report.clusters] == [("only",)]
    assert report.collapsed == 0


def test_an_empty_population_yields_no_clusters() -> None:
    report = cluster_by_correlation({}, threshold=0.2)
    assert report.clusters == ()
    assert report.inputs == 0


def test_a_threshold_outside_the_distance_range_is_refused() -> None:
    # `1 - corr` lives in [0, 2]. A threshold above 2 puts everything in one cluster; below 0,
    # nothing ever merges. Both are well-formed answers to a question nobody asked.
    for bad in (-0.1, 2.1):
        with pytest.raises(ValueError, match="threshold"):
            cluster_by_correlation({"a": BASE, "b": SHIFTED}, threshold=bad)


def test_a_threshold_of_zero_merges_only_identical_shapes() -> None:
    series = {"a": BASE, "a-scaled": scaled(BASE, 2.0), "b": SHIFTED}
    report = cluster_by_correlation(series, threshold=0.0)
    assert len(report.clusters) == 2


def test_an_exact_tie_merges_the_earlier_pair() -> None:
    """Greedy merging means the tie-break changes the ANSWER, not just the order.

    A and C are placed symmetrically about B, so `d(A,B)` and `d(C,B)` are exactly equal floats
    while `d(A,C)` is far larger. Merging (A,B) first gives [{A,B}, {C}]; merging (B,C) first
    gives [{A}, {B,C}] — both stable, both deterministic, and different. Determinism alone does
    not pin this down, so the rule is stated: the earlier pair in input order wins.

    Exact ties are not exotic. Two configs that produce identical return series sit at distance
    exactly 0, and a symmetric sweep produces them by construction.
    """
    series = {
        "a": [2.0, 0.0, 0.0, -2.0],
        "b": [1.0, -1.0, 1.0, -1.0],
        "c": [0.0, -2.0, 2.0, 0.0],
    }
    report = cluster_by_correlation(series, threshold=0.3)
    assert [c.members for c in report.clusters] == [("a", "b"), ("c",)]
