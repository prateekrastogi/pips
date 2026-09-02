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

import itertools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

import polars as pl

from pips.search.registry import Registry
from pips.selection.cluster import Cluster, correlation_distance
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
from pips.selection.turnover import (
    CostLine,
    EdgeCurve,
    JointPlan,
    UnsolvedVenue,
    plan_joint_per_broker_tier,
)

__all__ = [
    "RegistryIntake",
    "S5Result",
    "StageStep",
    "TurnoverInputs",
    "run_s5",
    "run_s5_from_registry",
]


@dataclass(frozen=True)
class TurnoverInputs:
    """Everything §6.1-§6.2 needs, grouped so the stage signature stays readable.

    `cost_lines` is per (broker, tier) because c differs by both and h* scales as
    (c/a)^(1/gamma) -- using one venue's line for another is a superlinear error, not a small
    one.
    """

    cost_lines: Mapping[tuple[str, str], CostLine]
    edge_curve: Callable[[float], EdgeCurve]
    """tau -> the alpha(h) curve of the population admitted at that bar."""
    trade_sigma: Callable[[float], float]
    """h -> the volatility a trade held that long carries."""
    fitted_horizon: float
    lam: float
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
class RegistryIntake:
    """What the registry offered and what survived reading it.

    Each exclusion is counted rather than filtered: a run dropped here never reaches the
    frontier, so a silent drop shrinks the population the whole selection reports on, and a
    trial that was run and viewed still counts (rule 4).
    """

    rows_read: int
    admitted: int
    excluded_other_stage: int
    excluded_not_completed: int
    excluded_viewed: int
    excluded_no_returns: int


@dataclass(frozen=True)
class S5Result:
    ensemble: tuple[Candidate, ...]
    funnel: tuple[StageStep, ...]
    netting: NettingFixedPoint
    gross_cost: CostLine
    effective_cost: CostLine
    plans: tuple[JointPlan, ...]
    unsolved_venues: tuple[UnsolvedVenue, ...]
    budget: BudgetVerdict
    pairwise_correlations: Mapping[tuple[str, str], float] = field(default_factory=dict)
    """Every pair the gate measured, kept and dropped alike. The evidence behind its verdict."""
    clusters: tuple[Cluster, ...] = ()
    """Which candidates collapsed together and which one speaks for each.

    The funnel says how many the clustering removed; it does not say which stood in for which,
    and that is what someone checking a collapsed near-variant needs.
    """
    intake: RegistryIntake | None = None
    """Present when the candidates came from the registry; None when they were handed in."""

    @property
    def admissible(self) -> bool:
        """Derived, never assigned: a field that can be set independently can say 'fine'.

        An ensemble with no SOLVED venue is inadmissible even when it breaches nothing — there
        is no rule to run it under, and "no breaches" would otherwise read as approval.
        """
        return self.budget.admissible and bool(self.ensemble) and bool(self.plans)


def _correlation_gate(
    survivors: Sequence[Candidate],
    series: Mapping[str, Sequence[float]],
    limit: float,
) -> tuple[list[Candidate], list[str], dict[tuple[str, str], float]]:
    """Greedy, in frontier order: keep a candidate unless it is too close to one already kept.

    Greedy rather than "drop both of a bad pair": dropping both discards a usable member for the
    sin of having a neighbour, and which one survives has to be decided by SOME rule. Frontier
    order is the rule, and it is stated rather than emergent.
    """
    kept: list[Candidate] = []
    dropped: list[str] = []
    # EVERY pair among the survivors, not only the offending ones. A gate that reports its
    # rejections alone cannot be audited for the pairs it let through, which is the half that
    # decides what runs — and the limit it turns on is a judgement call, so the numbers behind
    # it are exactly what a reader needs in order to disagree with it.
    measured: dict[tuple[str, str], float] = {}
    for left, right in itertools.combinations(survivors, 2):
        measured[(left.id, right.id)] = 1.0 - correlation_distance(
            series[left.id], series[right.id]
        )

    for candidate in survivors:
        against = [
            measured.get((candidate.id, other.id), measured.get((other.id, candidate.id), 0.0))
            for other in kept
        ]
        if any(value > limit for value in against):
            dropped.append(candidate.id)
        else:
            kept.append(candidate)
    return kept, dropped, measured


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

    ensemble, gated, correlations = _correlation_gate(
        representatives, series, max_pairwise_correlation
    )
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
    # JOINTLY, per §6.3 -- not `plan_per_broker_tier`, which solves §6.1 and §6.2 in sequence
    # and leaves each optimal against an input the other one moves. A venue whose coordinate
    # descent does not settle is reported, not dropped and not answered by the weaker solver.
    planned = plan_joint_per_broker_tier(
        {key: CostLine(line.total * float(keep)) for key, line in turnover.cost_lines.items()},
        edge_curve=turnover.edge_curve,
        trade_sigma=turnover.trade_sigma,
        fitted_horizon=turnover.fitted_horizon,
        lam=turnover.lam,
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
        pairwise_correlations=correlations,
        clusters=selection.clusters,
        plans=planned.plans,
        unsolved_venues=planned.unsolved,
        budget=verdict,
    )


def run_s5_from_registry(
    *,
    registry: Registry,
    stage: str,
    objectives: Sequence[Objective],
    cluster_threshold: float,
    max_pairwise_correlation: float,
    blotter_for: Callable[[tuple[str, ...], CostLine], Sequence[BlotterOrder]],
    gross_cost: CostLine,
    bucket_ns: int,
    budget: OrderBudget,
    turnover: TurnoverInputs,
    extra_metrics: Mapping[str, Mapping[str, float]] | None = None,
) -> S5Result:
    """Read completed runs at ``stage`` and run S5 over them.

    ``extra_metrics`` carries values DERIVED at selection time rather than recorded with the
    run — the deflated Sharpe above all (`[G-S4-DSR]`), which is computed against every trial in
    the ledger and so cannot have been in a row written before those trials existed. It may not
    overwrite a recorded metric: the runs table is append-only precisely so a ranking cannot be
    changed after the fact, and a keyword argument that silently replaced `net_return` would
    undo that. A run named here that is not among the candidates is refused rather than ignored,
    because a stale mapping means the rest of it has not been checked either.

    ``stage`` is REQUIRED with no default. S5 selects from what survived the earlier stages, and
    pooling every run in the registry mixes S1 exploratory trials with S4 survivors — producing
    a frontier over a population that never existed as a cohort, which looks exactly like a
    frontier over the right one.

    Candidates are keyed by ``run_id`` rather than ``config_hash``. Two runs of one config are
    then two candidates, which is correct here: the correlation clustering collapses them, so
    the duplicate is removed by the mechanism that exists for it rather than by a dedup rule
    invented at the intake.
    """
    rows = registry.all_runs()
    other_stage = not_completed = viewed = no_returns = 0
    candidates: list[Candidate] = []
    series: dict[str, list[float]] = {}

    for row in rows:
        if row["status"] == "viewed":
            viewed += 1
            continue
        if row["status"] != "completed":
            not_completed += 1
            continue
        if row["stage"] != stage:
            other_stage += 1
            continue
        if not row["daily_returns_ref"]:
            # It cannot be clustered, and that is not the same as being uncorrelated with
            # everything — which is what carrying it through would silently claim.
            no_returns += 1
            continue

        run_id = str(row["run_id"])
        recorded = json.loads(row["metrics"])
        derived = (extra_metrics or {}).get(run_id, {})
        if clash := sorted(set(recorded) & set(derived)):
            raise ValueError(
                f"run {run_id} already recorded {clash}, so a derived value cannot replace it. "
                "The runs table is append-only so that a ranking cannot be changed after the "
                "fact; overwriting here would undo that from the caller's side."
            )
        # Merge order cannot matter: the two are disjoint by the check above, and
        # swapping them is an equivalent mutant. That is the point of refusing the
        # clash rather than resolving it by precedence -- a precedence rule is a silent
        # decision about which value wins, made once and forgotten.
        candidates.append(Candidate(run_id, {**recorded, **derived}))
        series[run_id] = [
            float(v) for v in pl.read_parquet(row["daily_returns_ref"])["daily_return"]
        ]

    if unknown := sorted(set(extra_metrics or {}) - {c.id for c in candidates}):
        raise ValueError(
            f"extra_metrics names run(s) {unknown} that are not candidates at stage {stage!r}. "
            "A mapping that has drifted from the population is a mapping nobody has checked, "
            "so the rest of it is not applied either."
        )

    intake = RegistryIntake(
        rows_read=len(rows),
        admitted=len(candidates),
        excluded_other_stage=other_stage,
        excluded_not_completed=not_completed,
        excluded_viewed=viewed,
        excluded_no_returns=no_returns,
    )
    if not candidates:
        raise ValueError(
            f"no completed runs at stage {stage!r} with preserved daily returns "
            f"({len(rows)} rows read). Refusing rather than returning an empty ensemble, which "
            "would read as 'nothing survived selection' instead of 'nothing was selected from'."
        )

    lengths = {len(v) for v in series.values()}
    if len(lengths) > 1:
        detail = ", ".join(f"{k}={len(v)}" for k, v in sorted(series.items()))
        raise ValueError(
            f"preserved return series have different lengths ({detail}). Refusing rather than "
            "truncating to the common length as `daily_returns_matrix` does: that aligns at "
            "index 0, which is only correct if every run started on the same day. A run that "
            "began a month later would be compared day-1-to-day-1 against another's day-30."
        )

    result = run_s5(
        candidates=candidates,
        series=series,
        objectives=objectives,
        cluster_threshold=cluster_threshold,
        max_pairwise_correlation=max_pairwise_correlation,
        blotter_for=blotter_for,
        gross_cost=gross_cost,
        bucket_ns=bucket_ns,
        budget=budget,
        turnover=turnover,
    )
    return replace(
        result,
        funnel=(
            StageStep(
                name="registry-intake",
                considered=len(rows),
                admitted=len(candidates),
                dropped=tuple(str(r["run_id"]) for r in rows if str(r["run_id"]) not in series),
            ),
            *result.funnel,
        ),
        intake=intake,
    )
