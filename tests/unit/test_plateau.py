"""Plateau-centroid selection  (§6 M15, §3.6).

The rule that stops "pick the best of N".

A parameter surface always has a maximum. On noise it has one too — and that maximum is the
single most over-fitted point available, chosen from among every point precisely because it
scored highest. Selecting it is the multiplicity error this project is built against, committed
at the last possible moment, after every correction has already been applied.

So selection asks a different question: **is there a broad region where this works?** A wide
plateau of decent scores is evidence of structure, because structure is smooth in its own
parameters. An isolated spike surrounded by mediocrity is evidence of noise, however tall.
A07's falsifier says the same thing from the other side — *"reject if small changes to
range_end or buffer reverse the result"* — and A08's fit protocol asks for a surface so "the
plateau requirement can be CHECKED rather than asserted".

Two refusals carry the weight:

**No plateau means no selection.** Not "fall back to the peak". If there is no region where
this survives its own neighbours, there is no robust configuration, and returning the peak
anyway is the exact error the rule exists to prevent — performed by the machinery meant to
prevent it.

**The centroid must be an evaluated point.** An interpolated centre is a configuration that was
never run, and deploying one means trading a parameter set nobody has ever scored.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.plateau import ParameterPoint, plateau_centroid, plateau_ratio


def surface(scores: dict[tuple[int, int], float]) -> list[ParameterPoint]:
    return [
        ParameterPoint(coords=coords, score=Decimal(str(value)))
        for coords, value in sorted(scores.items())
    ]


def grid(default: float, **_: object) -> dict[tuple[int, int], float]:
    return {(x, y): default for x in range(7) for y in range(7)}


# ------------------------------------------------------------ the spike ----------------


def test_an_isolated_spike_is_not_selected() -> None:
    """The whole point, in one fixture.

    A lone 10.0 in a field of 1.0, next to a 3x3 block of 7.0. The spike is the best score on
    the surface and the most over-fitted point on it. Selection must come from the block.
    """
    scores = grid(1.0)
    scores[(0, 0)] = 10.0
    for x in (3, 4, 5):
        for y in (3, 4, 5):
            scores[(x, y)] = 7.0

    chosen = plateau_centroid(surface(scores), min_plateau_size=9, good_fraction=Decimal("0.6"))
    assert chosen is not None
    assert chosen.coords != (0, 0), "the spike is the argmax and must not be the selection"
    assert chosen.coords in {(x, y) for x in (3, 4, 5) for y in (3, 4, 5)}


def test_the_selection_is_the_centre_of_the_plateau_not_its_best_point() -> None:
    """The plateau is NOT uniform, and that is the whole test.

    With every point in the block scoring the same, "the centre" and "the highest" pick the
    same coordinate for unrelated reasons, and a mutation replacing one with the other killed
    nothing. Here the block's best point sits at a CORNER: centre and argmax disagree, and
    only the centre is the robust answer. Real surfaces are not flat either.
    """
    scores = grid(1.0)
    for x in (3, 4, 5):
        for y in (3, 4, 5):
            scores[(x, y)] = 7.0
    scores[(3, 3)] = 8.0  # the plateau's own peak, at its edge

    chosen = plateau_centroid(surface(scores), min_plateau_size=9, good_fraction=Decimal("0.6"))
    assert chosen is not None
    assert chosen.coords == (4, 4), "the centre, not the corner that happens to score highest"


def test_the_widest_plateau_wins_over_a_narrower_higher_one() -> None:
    """A taller but narrower region is the spike argument again, one size up.

    Three points at 9.0 in a line versus nine at 7.0 in a block: the line scores better and is
    thinner. Robustness is the criterion, not height.
    """
    scores = grid(1.0)
    for y in (0, 1, 2):
        scores[(0, y)] = 9.0
    for x in (3, 4, 5):
        for y in (3, 4, 5):
            scores[(x, y)] = 7.0

    # min_plateau_size 3, not 5: at 5 the taller line is filtered out by the SIZE FLOOR before
    # the widest-versus-tallest choice is ever made, so the test passed for an implementation
    # that picks the tallest region. Both regions must qualify for the choice to be tested.
    chosen = plateau_centroid(surface(scores), min_plateau_size=3, good_fraction=Decimal("0.6"))
    assert chosen is not None
    assert chosen.coords == (4, 4), "the wider region must win over the taller one"


# ------------------------------------------------------------ the refusals -------------


def test_no_plateau_means_no_selection_not_a_fallback_to_the_peak() -> None:
    """The refusal that matters most.

    Every good point here is isolated. There is no configuration that survives its own
    neighbours, so there is no robust choice — and returning the peak anyway would be the
    exact error this rule exists to prevent, committed by the machinery meant to prevent it.
    """
    scores = grid(1.0)
    for coords in ((0, 0), (0, 6), (6, 0), (6, 6)):
        scores[coords] = 9.0
    assert (
        plateau_centroid(surface(scores), min_plateau_size=4, good_fraction=Decimal("0.6")) is None
    )


def test_a_plateau_one_short_of_the_minimum_is_refused() -> None:
    # The control for the test above: without it, `None` could be what this function always
    # returns for anything but a perfect fixture.
    scores = grid(1.0)
    for x in (3, 4):
        for y in (3, 4):
            scores[(x, y)] = 7.0
    assert (
        plateau_centroid(surface(scores), min_plateau_size=5, good_fraction=Decimal("0.6")) is None
    )
    assert (
        plateau_centroid(surface(scores), min_plateau_size=4, good_fraction=Decimal("0.6"))
        is not None
    )


def test_a_surface_whose_best_score_is_not_positive_is_refused() -> None:
    """A plateau of losses is not a plateau.

    `good >= fraction x best` inverts when `best` is negative: with best = -1 and fraction
    0.6, every point above -0.6 qualifies — which is every point that loses LESS. The widest
    plateau on a losing surface would be selected and reported as robust.
    """
    losing = surface({(x, y): -1.0 for x in range(7) for y in range(7)})
    with pytest.raises(ValueError, match="positive"):
        plateau_centroid(losing, min_plateau_size=4, good_fraction=Decimal("0.6"))


def test_an_empty_surface_is_refused() -> None:
    with pytest.raises(ValueError, match="no points"):
        plateau_centroid([], min_plateau_size=4, good_fraction=Decimal("0.6"))


# ------------------------------------------------------------ shape --------------------


def test_the_selection_is_a_point_that_was_actually_evaluated() -> None:
    # An interpolated centre is a configuration nobody ever ran. Deploying one means trading
    # a parameter set with no score attached to it at all.
    scores = grid(1.0)
    for x in (2, 3, 4, 5):
        for y in (3, 4, 5):
            scores[(x, y)] = 7.0
    points = surface(scores)
    chosen = plateau_centroid(points, min_plateau_size=9, good_fraction=Decimal("0.6"))
    assert chosen is not None
    assert chosen in points


def test_ties_are_broken_deterministically() -> None:
    scores = grid(1.0)
    for x in (2, 3):
        for y in (2, 3):
            scores[(x, y)] = 7.0
    points = surface(scores)
    first = plateau_centroid(points, min_plateau_size=4, good_fraction=Decimal("0.6"))
    for _ in range(5):
        assert plateau_centroid(points, min_plateau_size=4, good_fraction=Decimal("0.6")) == first


def test_diagonal_neighbours_do_not_join_two_plateaus() -> None:
    """Adjacency is along the axes, not diagonal.

    Two blocks touching only at a corner are two regions, not one. Joining them would let a
    pair of narrow ridges masquerade as a wide plateau — the spike argument again, assembled
    from parts.
    """
    scores = grid(1.0)
    for x, y in ((0, 0), (0, 1), (1, 0), (1, 1)):
        scores[(x, y)] = 7.0
    for x, y in ((2, 2), (2, 3), (3, 2), (3, 3)):
        scores[(x, y)] = 7.0
    assert (
        plateau_centroid(surface(scores), min_plateau_size=8, good_fraction=Decimal("0.6")) is None
    )


# --------------------------------------------- the plateau MEASUREMENT `[G-P4-PLATEAU]` -----


def point(coords: tuple[int, ...], score: str) -> ParameterPoint:
    return ParameterPoint(coords=coords, score=Decimal(score))


def cross(centre: str, *neighbours: str) -> list[ParameterPoint]:
    """A centre at (1, 1) and up to four axis neighbours, in a fixed order."""
    places = [(0, 1), (2, 1), (1, 0), (1, 2)]
    return [point((1, 1), centre)] + [
        point(place, value) for place, value in zip(places, neighbours, strict=False)
    ]


def test_the_ratio_is_the_median_neighbour_over_the_centre() -> None:
    """`G-P4-PLATEAU`: median perturbed net SR >= 0.70 x centre. This is that number.

    `plateau_centroid` SELECTS a point; the gate needs a value to record and compare, and a
    dossier that stores a selection cannot be re-checked against the bar.
    """
    ratio = plateau_ratio(cross("1.00", "0.90", "0.80", "0.70", "0.60"), centre=(1, 1))
    assert ratio == Decimal("0.75")


def test_only_the_evaluated_neighbours_count() -> None:
    points = cross("1.00", "0.80", "0.60")
    assert plateau_ratio(points, centre=(1, 1)) == Decimal("0.70")


def test_a_bad_neighbour_is_not_filtered_out() -> None:
    """The failure that would make every plateau look wide.

    Taking the median over only the GOOD neighbours guarantees a ratio above the bar, because
    the bar is what "good" was defined by. The perturbations that went badly are the evidence.
    """
    generous = plateau_ratio(cross("1.00", "0.95", "0.90"), centre=(1, 1))
    honest = plateau_ratio(cross("1.00", "0.95", "0.90", "0.10", "0.05"), centre=(1, 1))
    assert generous is not None and honest is not None
    assert honest < generous
    assert honest < Decimal("0.70")


def test_diagonals_are_not_neighbours() -> None:
    """Same adjacency rule as the centroid: a corner touch is not a perturbation of one axis.

    The diagonal is set to a value that would MOVE the median if it counted — 0.60/0.80 gives
    0.70, and adding 1.00 gives 0.80. My first fixture had a single axis neighbour, which the
    minimum-perturbations rule refuses outright, so it tested that rule rather than this one.
    """
    points = [
        point((1, 1), "1.00"),
        point((0, 1), "0.60"),
        point((2, 1), "0.80"),
        point((0, 0), "1.00"),
        point((2, 2), "1.00"),
    ]
    assert plateau_ratio(points, centre=(1, 1)) == Decimal("0.70")


def test_a_centre_with_too_few_neighbours_has_no_ratio() -> None:
    """A median over one perturbation is not a median, and 1.0 from a lone neighbour would read
    as a perfectly flat plateau."""
    assert plateau_ratio([point((1, 1), "1.00"), point((0, 1), "0.90")], centre=(1, 1)) is None


def test_a_centre_that_was_not_evaluated_has_no_ratio() -> None:
    """Dividing by a score nobody measured is inventing the denominator.

    The centre here is missing while its neighbours are present — otherwise the
    minimum-perturbations rule refuses first and this check never runs, which is what my first
    version of the test did (it pointed at (5, 5), where nothing at all was evaluated).
    """
    surrounded = [
        point((0, 1), "0.90"),
        point((2, 1), "0.80"),
        point((1, 0), "0.70"),
        point((1, 2), "0.60"),
    ]
    assert plateau_ratio(surrounded, centre=(1, 1)) is None
    assert plateau_ratio(cross("1.00", "0.9", "0.8", "0.7"), centre=(5, 5)) is None


def test_a_non_positive_centre_has_no_ratio() -> None:
    """A ratio against a zero or negative centre is undefined, and against a negative one it
    INVERTS: a worse neighbour divides to a larger number and reads as a flatter plateau."""
    assert plateau_ratio(cross("0.00", "0.9", "0.8", "0.7"), centre=(1, 1)) is None
    assert plateau_ratio(cross("-0.50", "-0.1", "-0.2", "-0.3"), centre=(1, 1)) is None


def test_the_ratio_is_not_capped_at_one() -> None:
    """A neighbourhood better than its centre is a real observation — it means the centre was
    not the peak — and clamping it to 1.0 would hide that."""
    ratio = plateau_ratio(cross("1.00", "1.50", "1.40", "1.30"), centre=(1, 1))
    assert ratio is not None
    assert ratio > Decimal("1")


def test_the_ratio_is_exact_not_floating_point() -> None:
    """The comparison against 0.70 happens at a boundary someone will argue about."""
    ratio = plateau_ratio(cross("1.00", "0.70", "0.70", "0.70"), centre=(1, 1))
    assert ratio == Decimal("0.7")
    assert isinstance(ratio, Decimal)


def test_one_catastrophic_perturbation_does_not_drag_the_statistic() -> None:
    """Why the blueprint says MEDIAN and not mean, and the only test that separates them.

    Three neighbours at 0.10, 0.80 and 0.90 have a median of 0.80 and a mean of 0.60 — one
    result either side of the 0.70 bar. My other fixtures all had symmetric neighbours, where
    the two agree exactly and the choice is invisible.
    """
    ratio = plateau_ratio(cross("1.00", "0.10", "0.80", "0.90"), centre=(1, 1))
    assert ratio == Decimal("0.80")


def test_the_median_is_over_the_neighbours_scores_not_their_enumeration_order() -> None:
    """`around[middle]` is a median only because the list was sorted first.

    `_neighbours` enumerates axis by axis — for (1,1) that is (0,1), (2,1), (1,0), (1,2) — and
    that order has nothing to do with the scores. Dropping the sort takes the middle *position*
    instead of the middle *value*, which is not a median and is not stable under anything: the
    same neighbourhood measured with its axes declared in a different order gives a different
    plateau ratio, and the gate compares that number against a fixed 0.70.

    The scores here are placed so the two answers are far apart, and deliberately not symmetric
    — a symmetric neighbourhood cannot tell the middle position from the middle value.
    """
    points = [
        point((1, 1), "1.00"),
        point((0, 1), "0.95"),  # first in enumeration order, highest in value
        point((2, 1), "0.20"),
        point((1, 0), "0.30"),
        point((1, 2), "0.90"),
    ]

    ratio = plateau_ratio(points, (1, 1))

    # sorted: 0.20, 0.30, 0.90, 0.95 -> median (0.30 + 0.90) / 2 = 0.60
    assert ratio == Decimal("0.60"), (
        "in enumeration order the two middle entries are 0.20 and 0.30, which would read 0.25 "
        f"and fail a gate the neighbourhood actually clears; got {ratio}"
    )
