"""S5 — ensemble and turnover: the stage that runs the selection chain  (§6 M19).

Six correct modules that nothing invokes are six modules that can rot without a test noticing —
the standing lesson from ``check_unexplained_ratio_jump``, which passed its own unit tests for a
whole milestone while the runner never called it. This is the caller:

    frontier -> clustering -> correlation gate -> netting fixed point
             -> tau*/h* at the RE-PRICED line -> order budget on the combined blotter

Two failures belong to the composition rather than to any piece it composes.

**A step that rejects everything looks exactly like a step that is working well.** Forty
candidates becoming three is either a selective search or a broken filter, and "3 selected" is
the same output for both. So the funnel is reported step by step and every dropped id is
attributed to the step that dropped it — a candidate that vanishes between two counts is a
candidate nobody can account for (rule 4).

**The order budget is about the ENSEMBLE, not its members.** Three strategies each sending 2
orders/second are individually fine and together breach the 5/s governor. Measuring members one
at a time passes a combination the plant cannot run, which is the precise thing the constraint
exists to prevent.

**Two correlation numbers, two jobs.** The clustering threshold collapses near-variants so they
count once; the S5 gate demands the survivors be genuinely diverse (pairwise PnL correlation
<= 0.5 per the blueprint). Surviving the first does not imply passing the second: two
representatives at correlation 0.7 are far enough apart to be separate clusters and too close to
run together. Collapsing the two numbers into one would be a real error, so they are separate
parameters and separate funnel steps.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from pips.selection.cluster import correlation_distance
from pips.selection.frontier import select_frontier
from pips.selection.netting import (
    BlotterOrder,
    NettingFixedPoint,
    solve_netting_fixed_point,
)
from pips.selection.order_budget import (
    BudgetVerdict,
    OrderBudget,
    OrderEvent,
    check_order_budget,
)
from pips.selection.pareto import Candidate, Objective
from pips.selection.turnover import CostLine, TurnoverPlan, plan_per_broker_tier

__all__ = ["S5Result", "StageStep", "TurnoverInputs", "run_s5"]


@dataclass(frozen=True)
class TurnoverInputs:
    """Everything §6.1-§6.2 needs, grouped so the stage signature stays readable.

    `cost_lines` is per (broker, tier) because c differs by both and h* scales as
    (c/a)^(1/gamma) -- using one venue's line for another is a superlinear error, not a small
    one.
    """

    cost_lines: Mapping[tuple[str, str], CostLine]
    a: float
    gamma: float
    fitted_horizon: float
    lam: float
    sigma_trade: float
    density: Mapping[float, float]
    ticket: float
    capital: float


@dataclass(frozen=True)
class StageStep:
    """One narrowing, and exactly which candidates it removed."""

    name: str
    considered: int
    admitted: int
    dropped: tuple[str, ...]


@dataclass(frozen=True)
class S5Result:
    ensemble: tuple[Candidate, ...]
    funnel: tuple[StageStep, ...]
    netting: NettingFixedPoint
    gross_cost: CostLine
    effective_cost: CostLine
    plans: tuple[TurnoverPlan, ...]
    budget: BudgetVerdict

    @property
    def admissible(self) -> bool:
        """Derived, never assigned: a field that can be set independently can say 'fine'."""
        return self.budget.admissible and bool(self.ensemble)


def _correlation_gate(
    survivors: Sequence[Candidate],
    series: Mapping[str, Sequence[float]],
    limit: float,
) -> tuple[list[Candidate], list[str]]:
    """Greedy, in frontier order: keep a candidate unless it is too close to one already kept.

    Greedy rather than "drop both of a bad pair": dropping both discards a usable member for the
    sin of having a neighbour, and which one survives has to be decided by SOME rule. Frontier
    order is the rule, and it is stated rather than emergent.
    """
    kept: list[Candidate] = []
    dropped: list[str] = []
    for candidate in survivors:
        if any(
            1.0 - correlation_distance(series[candidate.id], series[other.id]) > limit
            for other in kept
        ):
            dropped.append(candidate.id)
        else:
            kept.append(candidate)
    return kept, dropped


def run_s5(
    *,
    candidates: Sequence[Candidate],
    series: Mapping[str, Sequence[float]],
    objectives: Sequence[Objective],
    cluster_threshold: float,
    max_pairwise_correlation: float,
    blotter_for: Callable[[tuple[str, ...], CostLine], Sequence[BlotterOrder]],
    gross_cost: CostLine,
    bucket_ns: int,
    budget: OrderBudget,
    turnover: TurnoverInputs,
) -> S5Result:
    """Run the ensemble stage and report the funnel that produced it."""
    if not candidates:
        raise ValueError(
            "S5 needs at least one candidate: an ensemble stage with nothing to ensemble is "
            "not an empty result, it is a missing input."
        )

    funnel: list[StageStep] = []
    entering = [c.id for c in candidates]

    selection = select_frontier(candidates, objectives, series, threshold=cluster_threshold)
    frontier_ids = {c.id for c in selection.frontier}
    funnel.append(
        StageStep(
            name="pareto-frontier",
            considered=len(candidates),
            admitted=len(selection.frontier),
            dropped=tuple(cid for cid in entering if cid not in frontier_ids),
        )
    )

    representatives = list(selection.representatives)
    kept_ids = {c.id for c in representatives}
    funnel.append(
        StageStep(
            name="correlation-clustering",
            considered=len(selection.frontier),
            admitted=len(representatives),
            dropped=tuple(c.id for c in selection.frontier if c.id not in kept_ids),
        )
    )

    ensemble, gated = _correlation_gate(representatives, series, max_pairwise_correlation)
    funnel.append(
        StageStep(
            name="pairwise-correlation-gate",
            considered=len(representatives),
            admitted=len(ensemble),
            dropped=tuple(gated),
        )
    )

    member_ids = tuple(c.id for c in ensemble)
    # The netting fixed point re-prices the cost line, and tau*/h* are solved against THAT --
    # §10.2's whole point is that the crossing changes each member's optimal threshold. Solving
    # at the gross line and reporting the ratio beside it would look identical in the output and
    # would be the wrong rule.
    netting = solve_netting_fixed_point(
        blotter_for=lambda cost: blotter_for(member_ids, cost),
        gross_cost=gross_cost,
        bucket_ns=bucket_ns,
    )

    final_blotter = blotter_for(member_ids, netting.effective_cost)
    verdict = check_order_budget(
        # Order events, not fills: the budget governs messages to the broker.
        [OrderEvent(ts_ns=o.ts_ns, symbol=o.symbol) for o in final_blotter],
        budget,
    )

    # One ratio, every venue's own line. The crossing is a property of the ORDER FLOW, not of
    # who executes it, so the measured ratio scales each broker x tier's gross line rather than
    # flattening them to a common number -- a cheap broker stays cheap after netting.
    keep = Decimal(1) - Decimal(str(netting.netting_ratio))
    plans = plan_per_broker_tier(
        {key: CostLine(line.total * float(keep)) for key, line in turnover.cost_lines.items()},
        a=turnover.a,
        gamma=turnover.gamma,
        fitted_horizon=turnover.fitted_horizon,
        lam=turnover.lam,
        sigma_trade=turnover.sigma_trade,
        density=turnover.density,
        ticket=turnover.ticket,
        capital=turnover.capital,
    )

    return S5Result(
        ensemble=tuple(ensemble),
        funnel=tuple(funnel),
        netting=netting,
        gross_cost=gross_cost,
        effective_cost=netting.effective_cost,
        plans=plans,
        budget=verdict,
    )
