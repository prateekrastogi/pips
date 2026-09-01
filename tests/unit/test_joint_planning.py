"""tau* and h* solved JOINTLY per broker x tier  (§6.3, M19).

S5 was calling `plan_per_broker_tier`, which solves §6.1 and §6.2 independently. §6.3 says in
terms that S5 solves them *jointly* by coordinate descent, because tau* and h* interact through
alpha(h): raising the bar changes the admitted population and so the edge curve, and lengthening
the hold changes the variance a trade carries and so the bar. The independent answer is each
condition optimal against an input the other one moves.

**One venue failing does not invalidate another.** Cost differs by broker and tier, and the
joint map contracts at one cost line and not at another — the same coupling can settle for a
cheap broker and cycle for a dear one. So this reports per venue rather than raising, unlike
`solve_joint` itself.

**But a venue that could not be solved is NAMED, never omitted, and never quietly answered by
the independent solver.** A fallback would hand back a plan indistinguishable from a solved one
for a venue whose economics do not settle at all.
"""

from __future__ import annotations

import pytest

from pips.selection.turnover import (
    CostLine,
    EdgeCurve,
    JointPlanSet,
    plan_joint_per_broker_tier,
    plan_per_broker_tier,
)

A0 = 0.000274
GAMMA = 0.5
CHEAP = ("FLATTRADE", "2L")
DEAR = ("ZERODHA", "2L")
DENSITY = {0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0}


def edge_curve(tau: float) -> EdgeCurve:
    """A higher bar admits better opportunities, so the fitted edge scale rises with tau."""
    return EdgeCurve(a=A0 * (1 + 0.3 * tau / 0.0005), gamma=GAMMA)


def trade_sigma(h: float) -> float:
    return 0.0005 * h


def plan(**over: object) -> JointPlanSet:
    kwargs: dict[str, object] = {
        "cost_lines": {CHEAP: CostLine(0.00025)},
        "edge_curve": edge_curve,
        "trade_sigma": trade_sigma,
        "fitted_horizon": 100_000.0,
        "lam": 0.5,
        "density": DENSITY,
        "ticket": 50_000.0,
        "capital": 2_000_000.0,
    }
    kwargs.update(over)
    return plan_joint_per_broker_tier(**kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------ the joint answer --------


def test_each_venue_is_solved_at_its_own_cost_line() -> None:
    result = plan(cost_lines={CHEAP: CostLine(0.00025), DEAR: CostLine(0.00040)})
    assert result.unsolved == ()
    by_key = {(p.broker, p.tier): p for p in result.plans}
    assert by_key[CHEAP].threshold < by_key[DEAR].threshold
    assert by_key[CHEAP].hold < by_key[DEAR].hold


def test_the_joint_answer_differs_from_the_independent_one() -> None:
    """Otherwise swapping the solvers is ceremony.

    The independent planner reads alpha(h) at whatever curve it is handed and never revisits it;
    the joint solve moves the curve as tau moves and settles where both conditions hold.
    """
    lines = {CHEAP: CostLine(0.00025)}
    joint = plan(cost_lines=lines)
    independent = plan_per_broker_tier(
        lines,
        a=edge_curve(0.00025).a,
        gamma=GAMMA,
        fitted_horizon=100_000.0,
        lam=0.5,
        sigma_trade=trade_sigma(10.0),
        density=DENSITY,
        ticket=50_000.0,
        capital=2_000_000.0,
    )
    assert joint.plans[0].hold != independent[0].hold
    assert joint.plans[0].threshold != independent[0].threshold


def test_the_plan_reports_how_many_passes_it_took() -> None:
    result = plan()
    assert result.plans[0].iterations >= 1


# ------------------------------------------------------------ partial answers ---------


def test_a_venue_that_cannot_be_solved_is_named_not_dropped() -> None:
    """The dear venue cycles under this coupling while the cheap one settles.

    Omitting it would leave a caller comparing one venue where two were priced, and the missing
    one is precisely the one whose economics do not settle.
    """
    result = plan(cost_lines={CHEAP: CostLine(0.00025), DEAR: CostLine(0.00090)})

    assert [(p.broker, p.tier) for p in result.plans] == [CHEAP]
    assert [(u.broker, u.tier) for u in result.unsolved] == [DEAR]
    assert "cycle" in result.unsolved[0].reason


def test_every_venue_appears_exactly_once_across_plans_and_unsolved() -> None:
    lines = {CHEAP: CostLine(0.00025), DEAR: CostLine(0.00090)}
    result = plan(cost_lines=lines)
    seen = [(p.broker, p.tier) for p in result.plans] + [
        (u.broker, u.tier) for u in result.unsolved
    ]
    assert sorted(seen) == sorted(lines)


def test_an_unsolved_venue_is_not_answered_by_the_independent_solver() -> None:
    """No silent fallback. A fallback plan is indistinguishable from a solved one.

    Reported as unsolved AND absent from `plans` — both, because either alone would let a caller
    that reads only one of them proceed as though the venue had a rule.
    """
    result = plan(cost_lines={CHEAP: CostLine(0.00025), DEAR: CostLine(0.00090)})
    assert DEAR not in {(p.broker, p.tier) for p in result.plans}


def test_there_is_no_fallback_switch_to_find() -> None:
    import inspect

    names = set(inspect.signature(plan_joint_per_broker_tier).parameters)
    assert not names & {"fallback", "on_failure", "allow_independent", "best_effort"}


def test_every_venue_failing_does_not_look_like_no_venues_configured() -> None:
    """An empty `plans` with an empty `unsolved` would mean "nothing was asked".

    Here everything was asked and nothing settled, which is a finding about the coupling.
    """
    result = plan(cost_lines={DEAR: CostLine(0.00090), ("X", "2L"): CostLine(0.00120)})
    assert result.plans == ()
    assert len(result.unsolved) == 2


# ------------------------------------------------------------ refusals ----------------


def test_no_cost_lines_is_refused() -> None:
    with pytest.raises(ValueError, match="cost line"):
        plan(cost_lines={})


def test_the_result_is_deterministic_and_ordered() -> None:
    lines = {DEAR: CostLine(0.00040), CHEAP: CostLine(0.00025)}
    first = plan(cost_lines=lines)
    second = plan(cost_lines=dict(reversed(list(lines.items()))))
    assert [(p.broker, p.tier) for p in first.plans] == [(p.broker, p.tier) for p in second.plans]


def test_each_venue_starts_from_its_own_cost_line() -> None:
    """tau* is never below c, so the venue's own line is the conservative start.

    A shared start would price one venue's first pass against another's population.
    """
    seen: list[float] = []

    def watching_curve(tau: float) -> EdgeCurve:
        seen.append(tau)
        return edge_curve(tau)

    plan(
        cost_lines={CHEAP: CostLine(0.00025), DEAR: CostLine(0.00040)},
        edge_curve=watching_curve,
    )
    assert 0.00025 in seen
    assert 0.00040 in seen


def test_turnover_is_computed_at_the_solved_threshold_not_the_cost_line() -> None:
    """tau* sits ABOVE c whenever lambda > 0, so the two admit different populations.

    At the solved tau* of 0.000673 only the 0.0020 bucket clears (3/day, turnover 0.075); at
    the cost line 0.00025 the 0.0006 bucket clears too (15/day, turnover 0.375). Using c is the
    risk-neutral threshold — it understates selectivity and overstates turnover five-fold here,
    and §6.2 is explicit that turnover is what the CHOSEN threshold implies.
    """
    result = plan(cost_lines={CHEAP: CostLine(0.00025)})
    only = result.plans[0]
    assert only.threshold == pytest.approx(0.000673, abs=1e-6)
    assert only.turnover == pytest.approx(0.075)
