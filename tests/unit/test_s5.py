"""S5 — ensemble and turnover: the stage that actually runs the selection chain  (§6 M19).

Six correct modules that nothing invokes are six modules that can rot without a test noticing.
This is the stage: frontier -> clustering -> correlation gate -> netting fixed point -> tau*/h*
at the RE-PRICED cost line -> order budget on the combined blotter.

Two failures belong to the composition rather than to any piece.

**A step that rejects everything looks exactly like a step that is working well.** Forty
candidates becoming three is either a selective search or a broken filter, and "3 selected" is
the same output for both. So the funnel is reported step by step, with every dropped id
attributed to the step that dropped it.

**The order budget is about the ENSEMBLE, not its members.** Three strategies each sending 2
orders/second are individually fine and together breach the 5/s governor. Checking members
one at a time passes a combination that cannot run.
"""

from __future__ import annotations

import itertools
from decimal import Decimal

import pytest

from pips.search.s5 import S5Result, TurnoverInputs, run_s5
from pips.selection.netting import BlotterOrder
from pips.selection.order_budget import NSE_RETAIL_BUDGET
from pips.selection.pareto import Candidate, Direction, Objective
from pips.selection.turnover import CostLine, EdgeCurve

SECOND = 1_000_000_000
OPEN = 1_772_000_000 * SECOND
RETURN = Objective("net_return", Direction.MAXIMIZE)
DRAWDOWN = Objective("max_drawdown", Direction.MINIMIZE)
TWO = [RETURN, DRAWDOWN]

BASE = [((t * 37) % 101 - 50) / 1000 for t in range(101)]
OTHER = [((t * 53) % 101 - 50) / 1000 for t in range(101)]
THIRD = [((t * 61) % 101 - 50) / 1000 for t in range(101)]


def blend(a: list[float], b: list[float], w: float) -> list[float]:
    return [w * x + (1 - w) * y for x, y in zip(a, b, strict=True)]


TURNOVER = TurnoverInputs(
    cost_lines={
        ("FLATTRADE", "2L"): CostLine(0.00025),
        ("ZERODHA", "2L"): CostLine(0.00060),
    },
    edge_curve=lambda tau: EdgeCurve(a=0.000274 * (1 + 0.3 * tau / 0.0005), gamma=0.5),
    trade_sigma=lambda h: 0.0005 * h,
    fitted_horizon=100_000.0,
    lam=0.5,
    density={0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0},
    ticket=50_000.0,
    capital=2_000_000.0,
)


def cand(cid: str, ret: float, dd: float) -> Candidate:
    return Candidate(cid, {"net_return": ret, "max_drawdown": dd})


def quiet_blotter(ids: tuple[str, ...], cost: CostLine) -> list[BlotterOrder]:
    """One order per member per second, in its own symbol: comfortably inside every limit."""
    return [
        BlotterOrder(cid, f"SYM{i}", OPEN + s * SECOND, 100, Decimal("100.00"))
        for i, cid in enumerate(ids)
        for s in range(10)
    ]


def run(**over: object) -> S5Result:
    kwargs: dict[str, object] = {
        "candidates": [cand("a", 0.30, 0.30), cand("b", 0.10, 0.02)],
        "series": {"a": BASE, "b": OTHER},
        "objectives": TWO,
        "cluster_threshold": 0.2,
        "max_pairwise_correlation": 0.5,
        "blotter_for": quiet_blotter,
        "gross_cost": CostLine(0.0005),
        "bucket_ns": SECOND,
        "budget": NSE_RETAIL_BUDGET,
        "turnover": TURNOVER,
    }
    kwargs.update(over)
    return run_s5(**kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------ the funnel --------------


def test_every_drop_is_attributed_to_the_step_that_made_it() -> None:
    """Forty into three is either a selective search or a broken filter.

    "3 selected" is the same output for both, so the count alone cannot be the report.
    """
    candidates = [
        cand("keep-a", 0.30, 0.30),
        cand("keep-b", 0.10, 0.02),
        cand("dominated", 0.05, 0.40),
    ]
    result = run(
        candidates=candidates,
        series={"keep-a": BASE, "keep-b": OTHER, "dominated": THIRD},
    )
    steps = {step.name: step for step in result.funnel}
    assert steps["pareto-frontier"].dropped == ("dominated",)
    assert steps["correlation-clustering"].dropped == ()
    assert {c.id for c in result.ensemble} == {"keep-a", "keep-b"}


def test_the_funnel_accounts_for_every_candidate_that_entered() -> None:
    candidates = [cand(f"c{i}", 0.30 - 0.01 * i, 0.02 + 0.01 * i) for i in range(4)]
    series = {f"c{i}": blend(BASE, OTHER, i / 3) for i in range(4)}
    result = run(candidates=candidates, series=series)

    dropped = [cid for step in result.funnel for cid in step.dropped]
    assert sorted(dropped + [c.id for c in result.ensemble]) == sorted(c.id for c in candidates)
    assert len(dropped) == len(set(dropped)), "a candidate cannot be dropped twice"


def test_a_step_that_rejects_everything_says_so() -> None:
    """The failure mode the funnel exists for: an empty ensemble must name its cause.

    A clustering threshold wide enough to collapse everything is a configuration error, and its
    output — one survivor — is indistinguishable from a genuinely convergent search unless the
    step reports what it swallowed.
    """
    candidates = [cand("a", 0.30, 0.30), cand("b", 0.10, 0.02)]
    result = run(candidates=candidates, series={"a": BASE, "b": OTHER}, cluster_threshold=2.0)
    step = next(s for s in result.funnel if s.name == "correlation-clustering")
    assert step.considered == 2
    assert step.admitted == 1
    assert step.dropped == ("b",)


# ------------------------------------------------------------ two thresholds ----------


def test_surviving_the_clustering_does_not_imply_passing_the_correlation_gate() -> None:
    """The two numbers do different jobs and collapsing them would be a real error.

    Clustering at distance 0.2 (corr >= 0.8) collapses near-variants. The S5 gate demands the
    SURVIVORS be genuinely diverse: pairwise PnL correlation <= 0.5. Two representatives at
    corr 0.7 are far enough apart to be separate clusters and too close to run together.
    """
    # corr(BASE, middling) = 0.743, so distance 0.257 > the 0.2 clustering threshold (separate
    # clusters) while 0.743 > the 0.5 gate. A blend at 0.75 sits at corr 0.95 and merely
    # clusters, which would demonstrate nothing.
    middling = blend(BASE, OTHER, 0.5)
    candidates = [cand("a", 0.30, 0.30), cand("b", 0.20, 0.12)]
    result = run(candidates=candidates, series={"a": BASE, "b": middling}, cluster_threshold=0.2)

    clustering = next(s for s in result.funnel if s.name == "correlation-clustering")
    assert clustering.admitted == 2, "they are separate clusters"
    gate = next(s for s in result.funnel if s.name == "pairwise-correlation-gate")
    assert gate.dropped == ("b",), "and still too correlated to run together"


def test_a_genuinely_diverse_pair_passes_the_gate() -> None:
    result = run(series={"a": BASE, "b": OTHER})
    gate = next(s for s in result.funnel if s.name == "pairwise-correlation-gate")
    assert gate.dropped == ()
    assert len(result.ensemble) == 2


# ------------------------------------------------------------ the ensemble budget -----


def test_the_order_budget_is_measured_on_the_combined_blotter() -> None:
    """Three members at 2 orders/second each are fine alone and breach the 5/s governor.

    Checking members one at a time is the mistake: it passes a combination that the plant
    cannot run, which is exactly what the constraint exists to prevent.
    """

    def two_per_second_each(ids: tuple[str, ...], cost: CostLine) -> list[BlotterOrder]:
        return [
            BlotterOrder(
                cid, f"SYM{i}", OPEN + s * SECOND + half * SECOND // 2, 100, Decimal("100.00")
            )
            for i, cid in enumerate(ids)
            for s in range(5)
            for half in range(2)
        ]

    candidates = [cand("a", 0.30, 0.30), cand("b", 0.20, 0.15), cand("c", 0.10, 0.02)]
    result = run(
        candidates=candidates,
        series={"a": BASE, "b": OTHER, "c": THIRD},
        blotter_for=two_per_second_each,
    )
    assert len(result.ensemble) == 3
    assert not result.budget.admissible
    assert result.budget.peak_global_per_second == 6
    assert not result.admissible, "the stage cannot certify an ensemble that breaches"


def test_a_quiet_ensemble_is_admissible() -> None:
    result = run()
    assert result.budget.admissible
    assert result.admissible


# ------------------------------------------------------------ the re-priced line ------


def test_the_thresholds_are_solved_at_the_repriced_line_not_the_gross_one() -> None:
    """Netting lowers the cost line, and tau*/h* must be re-solved against what was measured.

    Solving at the gross line and reporting the netting ratio beside it would look identical in
    the output and would be the wrong rule: §10.2's whole point is that the crossing changes
    each member's optimal threshold.
    """

    def crossing_blotter(ids: tuple[str, ...], cost: CostLine) -> list[BlotterOrder]:
        return [
            BlotterOrder(ids[0], "RELIANCE", OPEN, +100, Decimal("100.00")),
            BlotterOrder(ids[-1], "RELIANCE", OPEN, -60, Decimal("100.00")),
        ]

    result = run(blotter_for=crossing_blotter)
    assert result.netting.netting_ratio == pytest.approx(0.75)
    assert result.effective_cost.total < result.gross_cost.total

    # A `for` over an empty collection asserts nothing and passes. This loop did exactly that
    # while `plans` was still a stub, so the emptiness is checked before the loop runs.
    assert result.plans, "no plans means the loop below verifies nothing"
    for plan in result.plans:
        gross = TURNOVER.cost_lines[(plan.broker, plan.tier)]
        assert plan.cost.total == pytest.approx(gross.total * 0.25, rel=1e-9)
        assert plan.cost.total < gross.total


def test_each_broker_keeps_its_own_line_through_the_re_pricing() -> None:
    """The netting ratio is a property of the ORDER FLOW, not of who executes it.

    So one ratio scales every venue's own gross line; it does not flatten them to a common
    number. A cheap broker stays cheap after netting, and its tau* stays lower.
    """

    def crossing_blotter(ids: tuple[str, ...], cost: CostLine) -> list[BlotterOrder]:
        return [
            BlotterOrder(ids[0], "RELIANCE", OPEN, +100, Decimal("100.00")),
            BlotterOrder(ids[-1], "RELIANCE", OPEN, -60, Decimal("100.00")),
        ]

    result = run(blotter_for=crossing_blotter)
    by_key = {(p.broker, p.tier): p for p in result.plans}
    cheap = by_key[("FLATTRADE", "2L")]
    dear = by_key[("ZERODHA", "2L")]
    assert cheap.cost.total < dear.cost.total
    assert cheap.threshold < dear.threshold
    assert cheap.hold < dear.hold


# ------------------------------------------------------------ refusals ----------------


def test_a_candidate_without_returns_is_refused_rather_than_carried() -> None:
    with pytest.raises(ValueError, match="no daily returns"):
        run(series={"a": BASE})


def test_an_empty_candidate_set_is_refused() -> None:
    with pytest.raises(ValueError, match="at least"):
        run(candidates=[], series={})


def test_the_stage_is_deterministic() -> None:
    first, second = run(), run()
    assert [c.id for c in first.ensemble] == [c.id for c in second.ensemble]
    assert [s.dropped for s in first.funnel] == [s.dropped for s in second.funnel]


def test_admissible_is_derived_and_cannot_be_set_independently() -> None:
    result = run()
    assert result.admissible == (
        result.budget.admissible and bool(result.ensemble) and bool(result.plans)
    )


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "s5-ensemble" in CHECK_REGISTRY
    resolve_check("s5-ensemble")


def test_rejected_candidates_contribute_no_orders_to_netting_or_the_budget() -> None:
    """Both are measured on what will ACTUALLY run, not on everything considered.

    Including rejected candidates inflates the crossing — which lowers the cost line and admits
    trades on a saving that will never happen — and inflates the order traffic, which fails the
    governor for volume the plant was never going to send. The first error flatters and the
    second does not, and both are wrong.

    `b` is correlated with `a` and is dropped by the gate, so exactly two members remain.
    """
    middling = blend(BASE, OTHER, 0.5)
    candidates = [cand("a", 0.30, 0.30), cand("b", 0.20, 0.12), cand("c", 0.10, 0.02)]
    result = run(candidates=candidates, series={"a": BASE, "b": middling, "c": OTHER})

    gate = next(s for s in result.funnel if s.name == "pairwise-correlation-gate")
    assert gate.dropped == ("b",)
    assert {c.id for c in result.ensemble} == {"a", "c"}
    # quiet_blotter emits ten orders per member, so three candidates would give thirty.
    assert result.budget.total_orders == 20


def test_a_venue_whose_joint_solve_does_not_settle_is_reported_by_the_stage() -> None:
    """§6.3 solves tau* and h* jointly, and the joint map does not contract everywhere.

    The dear venue cycles under this coupling while the cheap one settles. The stage must carry
    that through: a caller reading only `plans` would otherwise see one venue where two were
    priced, and the missing one is exactly the one whose economics do not settle.
    """
    turnover = TurnoverInputs(
        cost_lines={("FLATTRADE", "2L"): CostLine(0.00025), ("ZERODHA", "2L"): CostLine(0.00090)},
        edge_curve=lambda tau: EdgeCurve(a=0.000274 * (1 + 0.3 * tau / 0.0005), gamma=0.5),
        trade_sigma=lambda h: 0.0005 * h,
        fitted_horizon=100_000.0,
        lam=0.5,
        density={0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0},
        ticket=50_000.0,
        capital=2_000_000.0,
    )
    result = run(turnover=turnover)

    assert [(p.broker, p.tier) for p in result.plans] == [("FLATTRADE", "2L")]
    assert [(u.broker, u.tier) for u in result.unsolved_venues] == [("ZERODHA", "2L")]
    assert "cycle" in result.unsolved_venues[0].reason


def test_an_ensemble_with_no_solvable_venue_is_not_admissible() -> None:
    """No breaches is not approval when there is no rule to run under.

    Every venue failing leaves an ensemble that passes the order budget trivially — it has no
    thresholds, so it sends nothing — and that must not read as a certifiable result.
    """
    turnover = TurnoverInputs(
        cost_lines={("ZERODHA", "2L"): CostLine(0.00090)},
        edge_curve=lambda tau: EdgeCurve(a=0.000274 * (1 + 0.3 * tau / 0.0005), gamma=0.5),
        trade_sigma=lambda h: 0.0005 * h,
        fitted_horizon=100_000.0,
        lam=0.5,
        density={0.0002: 40.0},
        ticket=50_000.0,
        capital=2_000_000.0,
    )
    result = run(turnover=turnover)

    assert result.plans == ()
    assert result.unsolved_venues != ()
    assert result.budget.admissible, "nothing breached"
    assert not result.admissible, "and still not certifiable"


# ------------------------------------------------------------ the gate's evidence -----
#
# The gate drops a candidate for being too correlated with one already kept, and reported only
# that it had. A verdict without its measurement is a verdict nobody can check — and the
# threshold it turns on (0.5) is a judgement call, so the numbers behind it are exactly what a
# reader needs to disagree with.


def test_the_pairwise_correlations_are_reported() -> None:
    result = run(series={"a": BASE, "b": OTHER})
    assert result.pairwise_correlations
    assert ("a", "b") in result.pairwise_correlations or ("b", "a") in result.pairwise_correlations


def test_every_pair_the_gate_considered_appears() -> None:
    """Not just the offending ones. A gate that reports only its rejections cannot be audited
    for the pairs it let through, which is the half that decides what runs."""
    candidates = [
        cand("a", 0.30, 0.30),
        cand("b", 0.20, 0.15),
        cand("c", 0.10, 0.02),
    ]
    series = {"a": BASE, "b": blend(BASE, OTHER, 0.5), "c": OTHER}
    result = run(candidates=candidates, series=series)

    # The REPRESENTATIVES, not the raw frontier: clustering runs first, so the gate never sees
    # the collapsed near-variants. Asserting against the frontier would demand pairs the gate
    # had no reason to measure.
    considered = {frozenset(pair) for pair in result.pairwise_correlations}
    representatives = [cluster.representative for cluster in result.clusters]
    expected = {frozenset(p) for p in itertools.combinations(representatives, 2)}
    assert considered == expected


def test_the_reported_number_is_the_one_the_gate_acted_on() -> None:
    """A dropped candidate must show a correlation above the limit against something kept.

    Reporting a number the decision did not use would be worse than reporting nothing: it would
    look like the evidence.
    """
    candidates = [cand("a", 0.30, 0.30), cand("b", 0.20, 0.12)]
    result = run(candidates=candidates, series={"a": BASE, "b": blend(BASE, OTHER, 0.5)})

    gate = next(s for s in result.funnel if s.name == "pairwise-correlation-gate")
    assert gate.dropped == ("b",)
    kept = {c.id for c in result.ensemble}
    offending = [
        value
        for (left, right), value in result.pairwise_correlations.items()
        if "b" in (left, right) and (left in kept or right in kept)
    ]
    assert offending and max(offending) > 0.5


def test_a_passing_pair_is_reported_below_the_limit() -> None:
    result = run(series={"a": BASE, "b": OTHER})
    assert all(v <= 0.5 for v in result.pairwise_correlations.values())
    assert len(result.ensemble) == 2
