"""Plateau-centroid selection  (§6 M15, §3.6).

The rule that stops "pick the best of N".

A parameter surface always has a maximum. On pure noise it has one too — and that maximum is
the single most over-fitted point available, chosen from among every point precisely because it
scored highest. Selecting it is the multiplicity error this project is built against, committed
at the last possible moment, after every correction has already been applied.

So selection asks a different question: **is there a broad region where this works?** A wide
plateau of decent scores is evidence of structure, because structure is smooth in its own
parameters. An isolated spike surrounded by mediocrity is evidence of noise, however tall.
A07's falsifier says the same thing from the other side — *"reject if small changes to
range_end or buffer reverse the result"* — and A08's fit protocol asks for a surface so the
plateau requirement can be CHECKED rather than asserted.

Two refusals carry the weight:

**No plateau means no selection.** Not a fall back to the peak. If nothing survives its own
neighbours there is no robust configuration, and returning the peak anyway would be the exact
error this rule exists to prevent, performed by the machinery meant to prevent it.

**The centroid must be an evaluated point.** An interpolated centre is a configuration that was
never run, and deploying one means trading a parameter set with no score attached to it.

Adjacency is along the axes, never diagonal. Two blocks touching at a corner are two regions;
joining them would let a pair of narrow ridges masquerade as a wide plateau — the spike
argument again, assembled from parts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["MIN_PERTURBATIONS", "ParameterPoint", "plateau_centroid", "plateau_ratio"]

MIN_PERTURBATIONS = 2
"""Evaluated neighbours needed before a median means anything. A "median" over one
perturbation is that perturbation, and a lone neighbour equal to its centre would read as
a perfectly flat plateau."""


@dataclass(frozen=True)
class ParameterPoint:
    """One evaluated configuration: its grid coordinates and what it scored."""

    coords: tuple[int, ...]
    score: Decimal


def _neighbours(coords: tuple[int, ...]) -> list[tuple[int, ...]]:
    """Axis-adjacent coordinates only -- one step, one dimension."""
    out: list[tuple[int, ...]] = []
    for axis in range(len(coords)):
        for step in (-1, 1):
            moved = list(coords)
            moved[axis] += step
            out.append(tuple(moved))
    return out


def _components(good: set[tuple[int, ...]]) -> list[set[tuple[int, ...]]]:
    """Connected regions of good points, found by flood fill over axis adjacency."""
    unvisited = set(good)
    found: list[set[tuple[int, ...]]] = []
    while unvisited:
        # `min` rather than `pop`: a set's iteration order is stable within a run but the
        # seed still decides nothing here, and starting from the lowest coordinate makes the
        # component ORDER deterministic across runs, which the tie-break below relies on.
        seed = min(unvisited)
        stack, region = [seed], set()
        while stack:
            here = stack.pop()
            if here in region:
                continue
            region.add(here)
            stack.extend(n for n in _neighbours(here) if n in unvisited and n not in region)
        unvisited -= region
        found.append(region)
    return found


def plateau_centroid(
    points: list[ParameterPoint], min_plateau_size: int, good_fraction: Decimal
) -> ParameterPoint | None:
    """The most central evaluated point of the widest good region, or ``None``.

    ``None`` means there is no plateau large enough, and it is the answer — not a signal to
    try something more permissive.
    """
    if not points:
        raise ValueError(
            "plateau_centroid called with no points. An empty surface has no maximum and no "
            "plateau; selecting from it would be selecting from nothing."
        )

    best = max(p.score for p in points)
    if best <= 0:
        # `score >= fraction * best` INVERTS on a negative best: with best -1 and fraction
        # 0.6, every point above -0.6 qualifies — every point that loses LESS. The widest
        # region of a losing surface would be selected and reported as robust.
        raise ValueError(
            f"the best score on this surface is {best}, which is not positive. A plateau of "
            "losses is not a plateau, and the good-fraction test inverts on a negative best: "
            "it would select the widest region of a losing surface and call it robust."
        )

    threshold = good_fraction * best
    by_coords = {p.coords: p for p in points}
    good = {p.coords for p in points if p.score >= threshold}
    if not good:
        return None

    regions = [r for r in _components(good) if len(r) >= min_plateau_size]
    if not regions:
        return None

    # Widest first; ties broken by the lowest coordinate in the region, so the answer does not
    # depend on iteration order. A selection rule that moves between runs is not a rule.
    widest = max(regions, key=lambda r: (len(r), tuple(-c for c in min(r))))

    dimensions = len(next(iter(widest)))
    centre = [sum(c[axis] for c in widest) / len(widest) for axis in range(dimensions)]

    def distance_to_centre(coords: tuple[int, ...]) -> tuple[float, tuple[int, ...]]:
        return (
            sum((coords[axis] - centre[axis]) ** 2 for axis in range(dimensions)),
            coords,  # deterministic tie-break among equidistant points
        )

    return by_coords[min(widest, key=distance_to_centre)]


def plateau_ratio(points: list[ParameterPoint], centre: tuple[int, ...]) -> Decimal | None:
    """Median neighbour score over the centre's score — `[G-P4-PLATEAU]`'s measurement.

    The blueprint's S3 battery asks for *median perturbed net SR ≥ 70% of center* under ±20-30%
    parameter perturbation. On an evaluated grid, one step along an axis IS that perturbation,
    so this is the ratio the gate compares against 0.70.

    Distinct from :func:`plateau_centroid`, which SELECTS a configuration. A gate needs a value:
    a dossier storing a selection cannot be re-checked against the bar it was certified under
    (`[C-DOSS-01]`).

    **Every evaluated neighbour counts, including the bad ones.** Taking the median over only
    the good ones would guarantee a ratio above the bar, because the bar is what "good" means —
    and the perturbations that went badly are the evidence the gate is asking for.

    ``None`` where the ratio is undefined, never a number:

    * the centre was not evaluated — dividing by a score nobody measured invents the denominator;
    * a non-positive centre — against zero it is undefined, and against a negative one it
      INVERTS, so a worse neighbour divides to a larger number and reads as a flatter plateau;
    * fewer than :data:`MIN_PERTURBATIONS` evaluated neighbours.

    Not capped at 1. A neighbourhood better than its centre is a real observation — it says the
    centre was not the peak — and clamping would hide it.
    """
    scores = {p.coords: p.score for p in points}
    anchor = scores.get(centre)
    if anchor is None or anchor <= 0:
        return None

    around = sorted(scores[c] for c in _neighbours(centre) if c in scores)
    if len(around) < MIN_PERTURBATIONS:
        return None

    middle = len(around) // 2
    median = (
        around[middle]
        if len(around) % 2
        # Decimal throughout: the comparison against 0.70 happens at a boundary someone will
        # argue about, and a float median would decide it by representation.
        else (around[middle - 1] + around[middle]) / Decimal(2)
    )
    return median / anchor
