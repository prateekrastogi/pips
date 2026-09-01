"""Non-dominated (Pareto) sort  (§6 M19).

M19 selects across net return, DSR, MDD/CVaR, cost share, turnover/order count and stability.
Those do not reduce to one number, and inventing weights to make them reduce is how a search
ends up picking whatever the weights favoured rather than whatever the evidence supports. A
Pareto sort answers the question that CAN be answered without weights: which candidates is
nothing strictly better than. It narrows the field honestly and leaves the trade-off to a
decision someone has to make out loud.

**The direction of each objective is the whole risk.** Return is maximised, drawdown and cost
and turnover are minimised, and one objective pointed the wrong way silently inverts part of
the frontier while still producing a frontier — the right shape, the wrong members, nothing in
the output to say so. So direction is DECLARED on the objective and never inferred from its
name: ``max_drawdown`` and ``neg_drawdown`` are equally plausible conventions and only the
caller knows which one the metric follows.

Two refusals are worth naming because both produce a confident, well-formed, meaningless
answer:

* **No objectives.** Nothing dominates anything, so the frontier is the entire population. That
  is not an empty result but a full one, and it reads as though every candidate survived
  selection on merit.
* **A non-finite objective.** Every comparison with NaN is false, so a NaN candidate dominates
  nothing and is dominated by nothing — which puts it on the FIRST front. A broken measurement
  is promoted to the frontier and reported as a winner.

Dominance requires BOTH clauses: at least as good on every objective, and strictly better on at
least one. Dropping the second makes every candidate dominate its own twin, so tied pairs
eliminate each other and the frontier loses precisely the results that reproduced.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = ["Candidate", "Direction", "Objective", "dominates", "non_dominated_sort"]


class Direction(enum.Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True)
class Objective:
    """One axis of the comparison, and which way is better along it."""

    name: str
    direction: Direction


@dataclass(frozen=True)
class Candidate:
    """One trial, carrying every metric it recorded. Objectives name the ones that count."""

    id: str
    metrics: Mapping[str, float]


def _value(candidate: Candidate, objective: Objective) -> float:
    """The candidate's score on this axis, ORIENTED so that larger is always better.

    Doing the flip once here rather than at each comparison is what keeps the dominance test
    free of direction logic — there is no second place for a sign to go wrong.
    """
    raw = candidate.metrics[objective.name]
    return -raw if objective.direction is Direction.MINIMIZE else raw


def dominates(a: Candidate, b: Candidate, objectives: Sequence[Objective]) -> bool:
    """True when ``a`` is at least as good as ``b`` everywhere and strictly better somewhere."""
    strictly_better_somewhere = False
    for objective in objectives:
        left, right = _value(a, objective), _value(b, objective)
        if left < right:
            return False
        if left > right:
            strictly_better_somewhere = True
    return strictly_better_somewhere


def _validate(candidates: Sequence[Candidate], objectives: Sequence[Objective]) -> None:
    if not objectives:
        raise ValueError(
            "a Pareto sort needs at least one objective. With none, nothing dominates anything "
            "and the frontier is the whole population — a full result, not an empty one, and "
            "it reads as though every candidate survived selection on merit."
        )
    names = [objective.name for objective in objectives]
    if len(set(names)) != len(names):
        raise ValueError(
            f"duplicate objective in {names}: one name listed twice doubles its weight in the "
            "comparison, and if the two disagree on direction the verdict depends on which is "
            "checked first."
        )
    ids = [candidate.id for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate candidate id: a selection cannot report the same trial twice")

    for candidate in candidates:
        for objective in objectives:
            if objective.name not in candidate.metrics:
                raise ValueError(
                    f"candidate {candidate.id!r} has no {objective.name!r} metric. Refusing "
                    "rather than defaulting it: a default ranks the candidate wherever that "
                    "value happens to fall, which for a minimised metric is the best score "
                    "available."
                )
            value = candidate.metrics[objective.name]
            if not math.isfinite(value):
                raise ValueError(
                    f"candidate {candidate.id!r} has a non-finite {objective.name!r} "
                    f"({value!r}); every objective must be finite. NaN compares false against "
                    "everything, so it would be dominated by nothing and land on the FIRST "
                    "front — a broken measurement reported as a winner."
                )


def non_dominated_sort(
    candidates: Sequence[Candidate], objectives: Sequence[Objective]
) -> list[list[Candidate]]:
    """Layer the population into fronts: front 0 is the Pareto frontier, front 1 what it hides.

    Input order is preserved within each front so the same population gives byte-identical
    output (rule 1).
    """
    _validate(candidates, objectives)

    remaining = list(candidates)
    fronts: list[list[Candidate]] = []
    # BOUNDED, not `while remaining`. Every front removes at least one candidate, so there can
    # be at most one front per candidate. The bound is what turns a broken comparator into an
    # error instead of a hang: Romano-Wolf's unbounded loop once hung a ten-minute mutation
    # batch, and a stall reports nothing at all, which is worse than reporting a failure.
    for _ in range(len(candidates)):
        if not remaining:
            break
        front = [
            candidate
            for candidate in remaining
            if not any(dominates(other, candidate, objectives) for other in remaining)
        ]
        fronts.append(front)
        placed = {id(candidate) for candidate in front}
        remaining = [c for c in remaining if id(c) not in placed]

    if remaining:
        # The bound ran out with candidates unplaced, which means some pass produced no
        # non-dominated member: `dominates` called something better than itself, so no front
        # could ever close. Raising beats returning the partial layering — a selection missing
        # candidates is a selection whose denominator is wrong (rule 4), and it looks complete.
        raise RuntimeError(
            f"layering did not terminate with {len(remaining)} candidates unplaced: "
            "`dominates` is not a strict partial order, so no front could be closed."
        )
    return fronts
