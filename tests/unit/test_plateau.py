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

from pips.validation.plateau import ParameterPoint, plateau_centroid


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
