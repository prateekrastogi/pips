"""The joint fixed point of tau* and h*  (§6.3, M19).

§6.1 optimises when to exit; §6.2 optimises what to enter. They INTERACT: alpha(h) depends on
the admitted population, so raising the bar changes the edge curve, and the variance a trade
carries depends on how long it is held, so the hold changes the threshold. The doc solves them
by coordinate descent — alternate `(tau | h)` and `(h | tau)` until fixed point.

Solving them separately, as the previous tick did, answers a different question: each is optimal
against an edge curve and a trade volatility that the other one moves.

What makes this dangerous rather than merely approximate is the failure mode. Coordinate
descent on a map that is not a contraction does not diverge loudly — it oscillates, and the
last iterate looks exactly like a converged one. So non-convergence RAISES here and there is no
path that returns the final iterate as an answer.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pips.selection.turnover import (
    CostLine,
    EdgeCurve,
    FixedPointError,
    JointOptimum,
    optimal_hold_power_law,
    optimal_threshold,
    rotation_residual,
    solve_joint,
)

C = 0.0005
A0 = 0.000274
GAMMA = 0.5
HORIZON = 120.0


def converging_curve(k: float = 0.2) -> Callable[[float], EdgeCurve]:
    """A higher bar admits better opportunities, so the fitted edge scale rises with tau."""

    def curve(tau: float) -> EdgeCurve:
        return EdgeCurve(a=A0 * (1 + k * tau / C), gamma=GAMMA)

    return curve


def sqrt_sigma(s0: float = 0.0002) -> Callable[[float], float]:
    """Longer holds carry more variance."""

    def sigma(h: float) -> float:
        return float(s0 * h**0.5)

    return sigma


def solve(**over: object) -> JointOptimum:
    kwargs: dict[str, object] = {
        "edge_curve": converging_curve(),
        "trade_sigma": sqrt_sigma(),
        "cost": CostLine(C),
        "lam": 0.5,
        "fitted_horizon": HORIZON,
        "start_threshold": C,
    }
    kwargs.update(over)
    return solve_joint(**kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------ the fixed point ----------


def test_the_answer_satisfies_both_conditions_at_once() -> None:
    """The definition of the joint solution, and the only test that can confirm it.

    Asserting a converged pair against remembered decimals would pass for a loop that settled
    on the wrong point. At a true fixed point the Faustmann residual vanishes on the edge curve
    of the population admitted at tau*, AND tau* is the §6.2 threshold for the volatility of a
    trade held h*.
    """
    result = solve()
    curve = converging_curve()(result.threshold)

    def alpha(h: float) -> float:
        return float(curve.a * h**curve.gamma)

    assert rotation_residual(alpha, result.hold, C) == pytest.approx(0.0, abs=1e-9)
    assert result.threshold == pytest.approx(
        optimal_threshold(CostLine(C), lam=0.5, sigma_trade=sqrt_sigma()(result.hold)),
        rel=1e-9,
    )


def test_the_joint_answer_differs_from_solving_them_separately() -> None:
    """Otherwise §6.3 would be ceremony.

    Solved alone, h* uses the edge curve of the population admitted at the STARTING threshold.
    The fixed point moves both.
    """
    result = solve()
    alone = optimal_hold_power_law(a=converging_curve()(C).a, gamma=GAMMA, cost=C)
    assert abs(result.hold - alone) > 1e-6


def test_the_iterations_and_the_path_are_reported() -> None:
    result = solve()
    assert 1 < result.iterations < 50
    assert len(result.history) == result.iterations
    assert result.start_threshold == C


def test_the_solve_is_deterministic() -> None:
    first, second = solve(), solve()
    assert (first.threshold, first.hold) == (second.threshold, second.hold)


# ------------------------------------------------------------ non-convergence ----------


def test_an_oscillating_coupling_is_refused_not_reported_as_an_answer() -> None:
    """The failure this module exists to catch.

    With sigma growing linearly in the hold, the composite map overshoots: tau alternates
    between about 5.3e-4 and 3.2e-2 forever. Neither subproblem is wrong — the joint map simply
    is not a contraction. The last iterate is a perfectly ordinary number and returning it
    would be indistinguishable from a converged solve.
    """

    def linear_sigma(h: float) -> float:
        return 0.01 * h

    with pytest.raises(FixedPointError, match="cycle"):
        solve(edge_curve=converging_curve(k=1.0), trade_sigma=linear_sigma, lam=1.0)


def test_a_cycle_is_named_as_a_cycle_rather_than_as_running_out_of_iterations() -> None:
    """They call for different actions, so they must not report the same way.

    'Needs more iterations' invites raising max_iter, which for a cycle burns time and returns
    the same non-answer.
    """

    def linear_sigma(h: float) -> float:
        return 0.01 * h

    with pytest.raises(FixedPointError) as excinfo:
        solve(edge_curve=converging_curve(k=1.0), trade_sigma=linear_sigma, lam=1.0)
    message = str(excinfo.value)
    assert "cycle" in message
    assert "period 2" in message


def test_exhausting_the_iteration_budget_is_refused() -> None:
    with pytest.raises(FixedPointError, match="max_iter"):
        solve(max_iter=2)


def test_there_is_no_way_to_get_the_last_iterate_of_a_failed_solve() -> None:
    """No `strict=False`, no `allow_unconverged`, no partial return.

    The sealed lockbox raises rather than handing back what it can, for the same reason: a
    shorter answer and a wrong answer look identical downstream.
    """
    import inspect

    from pips.selection.turnover import solve_joint as fn

    names = set(inspect.signature(fn).parameters)
    assert not names & {"strict", "allow_unconverged", "best_effort", "raise_on_failure"}


# ------------------------------------------------------------ tolerance and units ------


def test_convergence_is_judged_relatively_so_the_units_of_h_do_not_matter() -> None:
    """tau is ~5e-4 and h is ~8. One absolute epsilon cannot be right for both.

    At 1e-6 absolute it is meaninglessly loose on tau (0.2 percent) and painfully tight on h.
    The same problem expressed in seconds rather than minutes must give the same threshold and
    a hold scaled by exactly 60 — which only holds if each coordinate is judged against its own
    magnitude.
    """
    minutes = solve()

    scale = 60.0

    # alpha(h) = a*h^gamma in minutes becomes a/scale^gamma in seconds, for the same edge.
    def curve_seconds(tau: float) -> EdgeCurve:
        base = converging_curve()(tau)
        return EdgeCurve(a=base.a / scale**base.gamma, gamma=base.gamma)

    def sigma_seconds(h: float) -> float:
        return sqrt_sigma()(h / scale)

    seconds = solve(
        edge_curve=curve_seconds,
        trade_sigma=sigma_seconds,
        fitted_horizon=HORIZON * scale,
    )
    assert seconds.threshold == pytest.approx(minutes.threshold, rel=1e-9)
    assert seconds.hold == pytest.approx(minutes.hold * scale, rel=1e-9)


def test_a_non_positive_tolerance_is_refused() -> None:
    with pytest.raises(ValueError, match="tol"):
        solve(rel_tol=0.0)


# ------------------------------------------------------------ the horizon --------------


def test_an_intermediate_iterate_beyond_the_fitted_horizon_is_refused() -> None:
    """Checking only the final answer would accept a path that left the data and came back.

    Every iterate is a hold the solver evaluated alpha(h) at. If that h was never measured, the
    edge value driving the next step is an extrapolation, and the fixed point it walks to
    inherits that whether or not it lands back inside the range.
    """
    start = converging_curve()(C)
    first_hold = optimal_hold_power_law(a=start.a, gamma=GAMMA, cost=C)
    with pytest.raises(FixedPointError, match="fitted horizon"):
        solve(fitted_horizon=first_hold * 0.5)


def test_a_start_threshold_below_the_cost_line_is_refused() -> None:
    # tau* is never below c: the marginal trade would not clear costs. Starting there asks the
    # first iterate to price a population that would not be admitted at any optimum.
    with pytest.raises(ValueError, match="cost line"):
        solve(start_threshold=C / 2)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "joint-turnover" in CHECK_REGISTRY
    resolve_check("joint-turnover")


def test_starting_at_the_fixed_point_converges_immediately() -> None:
    """Not a curiosity: walk-forward seeds each fold with the previous fold's answer.

    A solver that always burns a second pass would report an iteration count that says the
    optimum moved when it did not — and the fold-to-fold behaviour of (tau*, h*) is itself the
    robustness statistic §6.3 asks for.
    """
    settled = solve()
    again = solve(start_threshold=settled.threshold)
    assert again.iterations == 1
    assert again.threshold == pytest.approx(settled.threshold, rel=1e-9)
    assert again.hold == pytest.approx(settled.hold, rel=1e-9)


def test_a_later_iterate_leaving_the_fitted_range_is_refused_too() -> None:
    """The first hold is INSIDE the measured range; the path walks out of it afterwards.

    A fixture that violates the horizon on step 0 cannot tell a check on every iterate from a
    check on the first one — and the whole reason to check every iterate is the excursion that
    happens partway through. Here a higher bar admits fewer opportunities, so the curve fitted
    on them has a lower scale, so the optimal hold lengthens: h goes 13.3 -> 39.9 -> 68.2 while
    the horizon is 20.
    """

    def thinning_curve(tau: float) -> EdgeCurve:
        return EdgeCurve(a=A0 * (C / tau), gamma=GAMMA)

    with pytest.raises(FixedPointError, match="iterate 1") as excinfo:
        solve(edge_curve=thinning_curve, fitted_horizon=20.0)
    assert "fitted horizon" in str(excinfo.value)
