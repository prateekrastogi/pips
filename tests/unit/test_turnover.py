"""Turnover calculus: the Faustmann hold h* and the selectivity threshold tau*  (§6 M19).

From Quantitative Foundations §6.1-§6.2. Both are C2 rules — "every rule is an optimum", the
argmax of a stated objective under the measured cost line, never a round number that felt right.

**§6.1** Rotating capital repeatedly, value accrues at rate `rho(h) = (alpha(h) - c) / h`.
Setting `rho'(h) = 0` gives `alpha'(h*) = (alpha(h*) - c) / h* = rho(h*)`: extend the hold until
the marginal rate of edge accrual falls to the average net rate. That is the Faustmann rotation
condition from renewable-resource economics, transplanted intact. For the concave power family
`alpha(h) = a*h^gamma` with `0 < gamma < 1` it closes:

    h* = [c / (a(1-gamma))]^(1/gamma),  alpha(h*) = c/(1-gamma),  net edge = c*gamma/(1-gamma)

**§6.2** With opportunities arriving at conditional edge `g` and density `n(g)`,
`dPi/dtau = -(tau - c)*n(tau)`, so `tau* = c` risk-neutral and `tau* = c + lambda*sigma_trade`
risk-adjusted. The marginal admitted trade breaks even against the all-in cost line.

**Turnover is an OUTPUT.** `T* = integral_{tau*}^inf n(g) dg * ticket / capital` — it falls out
of the threshold. There is deliberately no way to ask for a turnover and get a threshold back;
that inversion is what the section exists to refuse.
"""

from __future__ import annotations

import functools
import math

import pytest

from pips.selection.turnover import (
    CostLine,
    TurnoverPlan,
    optimal_hold,
    optimal_hold_power_law,
    optimal_threshold,
    optimal_turnover,
    rotation_residual,
)

# Intraday scale: h in minutes, edges as fractions. alpha(30min) ~ 15bps for these constants.
A = 0.000274
GAMMA = 0.5
COST = 0.0005  # 5 bps all-in, per §4 an effective-dated measurement rather than an assumption


def power_law(h: float, a: float = A, gamma: float = GAMMA) -> float:
    return float(a * h**gamma)


# ------------------------------------------------------------ §6.1 closed form ---------


def test_the_closed_form_satisfies_the_faustmann_condition() -> None:
    """`alpha'(h*) == rho(h*)`. The definition, checked against the algebra that solved it.

    Asserting h* against a hardcoded decimal would pass just as well for a formula that is
    wrong in the same way twice; this checks the first-order condition itself.
    """
    h = optimal_hold_power_law(a=A, gamma=GAMMA, cost=COST)
    assert rotation_residual(power_law, h, COST) == pytest.approx(0.0, abs=1e-9)


def test_gross_edge_at_the_optimum_is_the_stated_identity() -> None:
    # alpha(h*) = c/(1-gamma), independent of `a`. If h* is wrong this breaks.
    for gamma in (0.25, 0.5, 0.75, 0.9):
        h = optimal_hold_power_law(a=A, gamma=gamma, cost=COST)
        assert power_law(h, gamma=gamma) == pytest.approx(COST / (1 - gamma), rel=1e-9)


def test_at_gamma_one_half_gross_edge_is_exactly_twice_the_cost() -> None:
    """The screening heuristic the doc calls out as a corollary — a golden worth pinning."""
    h = optimal_hold_power_law(a=A, gamma=0.5, cost=COST)
    assert power_law(h, gamma=0.5) == pytest.approx(2 * COST, rel=1e-9)


def test_net_edge_per_trade_is_the_stated_identity() -> None:
    for gamma in (0.25, 0.5, 0.75):
        h = optimal_hold_power_law(a=A, gamma=gamma, cost=COST)
        net = power_law(h, gamma=gamma) - COST
        assert net == pytest.approx(COST * gamma / (1 - gamma), rel=1e-9)


def test_the_stationary_point_is_a_maximum_not_a_minimum() -> None:
    """The doc's second-order check, verified numerically instead of taken on trust.

    A sign error in the derivation would land on a stationary point that MINIMISES the accrual
    rate, and every first-order test above would still pass.
    """
    h = optimal_hold_power_law(a=A, gamma=GAMMA, cost=COST)

    def rho(x: float) -> float:
        return (power_law(x) - COST) / x

    assert rho(h) > rho(h * 0.5)
    assert rho(h) > rho(h * 2.0)


def test_cheaper_costs_shorten_the_optimal_hold_superlinearly() -> None:
    # h* scales as (c/a)^(1/gamma): halving costs at gamma=0.5 quarters the hold.
    full = optimal_hold_power_law(a=A, gamma=0.5, cost=COST)
    half = optimal_hold_power_law(a=A, gamma=0.5, cost=COST / 2)
    assert half == pytest.approx(full / 4, rel=1e-9)


# ------------------------------------------------------------ §6.1 refusals ------------


@pytest.mark.parametrize("gamma", [1.0, 1.5, 2.0])
def test_a_non_concave_edge_curve_has_no_optimal_hold(gamma: float) -> None:
    """`gamma >= 1` means edge accrues at least linearly forever: there is no optimum.

    The closed form still evaluates. At gamma = 1 it divides by zero; above it, `1 - gamma` is
    negative and the expression returns a positive-looking number that is the argmax of
    nothing. A hold recommended on that basis is a recommendation to hold forever, arrived at
    silently.
    """
    with pytest.raises(ValueError, match="concave"):
        optimal_hold_power_law(a=A, gamma=gamma, cost=COST)


@pytest.mark.parametrize("gamma", [0.0, -0.5])
def test_a_non_positive_decay_exponent_is_refused(gamma: float) -> None:
    with pytest.raises(ValueError, match="concave"):
        optimal_hold_power_law(a=A, gamma=gamma, cost=COST)


@pytest.mark.parametrize("cost", [0.0, -0.0001])
def test_a_cost_line_that_is_not_positive_is_refused(cost: float) -> None:
    """Zero cost drives h* to zero: trade infinitely fast, infinitely often.

    Costs are effective-dated DATA (§4). A zero cost line is a missing measurement wearing the
    shape of a favourable one, and it produces the most profitable-looking answer available.
    """
    with pytest.raises(ValueError, match="cost"):
        optimal_hold_power_law(a=A, gamma=GAMMA, cost=cost)


def test_a_non_positive_edge_scale_is_refused() -> None:
    with pytest.raises(ValueError, match="edge"):
        optimal_hold_power_law(a=0.0, gamma=GAMMA, cost=COST)


# ------------------------------------------------------------ §6.1 general case --------


def test_the_numerical_solver_recovers_the_closed_form() -> None:
    """The cross-check that makes the general solver trustworthy on curves without one.

    Real alpha(h) is read off a measured IC-decay curve, not a formula. The only way to know
    the solver is right is to run it where the answer is known.
    """
    for gamma in (0.3, 0.5, 0.8):
        closed = optimal_hold_power_law(a=A, gamma=gamma, cost=COST)
        curve = functools.partial(power_law, gamma=gamma)
        numeric = optimal_hold(curve, COST, bracket=(0.1, 400.0))
        assert numeric == pytest.approx(closed, rel=1e-4)


def test_a_curve_that_never_clears_costs_has_no_optimal_hold() -> None:
    """Returning the least-bad hold would read as a recommendation.

    Every h loses money here. The argmax of a negative accrual rate is a real number and it is
    not an answer to "how long should this be held".
    """
    with pytest.raises(ValueError, match="never clears"):
        optimal_hold(lambda h: 0.00001 * h**0.5, COST, bracket=(0.1, 400.0))


def test_the_bracket_must_contain_the_optimum() -> None:
    # Silently returning an endpoint would report the boundary as an optimum.
    with pytest.raises(ValueError, match="bracket"):
        optimal_hold(power_law, COST, bracket=(200.0, 400.0))


# ------------------------------------------------------------ §6.2 threshold -----------


def test_the_risk_neutral_threshold_is_the_cost_line() -> None:
    assert optimal_threshold(CostLine(COST), lam=0.0, sigma_trade=0.01) == pytest.approx(COST)


def test_the_risk_adjusted_threshold_adds_the_priced_variance() -> None:
    tau = optimal_threshold(CostLine(COST), lam=0.5, sigma_trade=0.01)
    assert tau == pytest.approx(COST + 0.5 * 0.01)


def test_a_negative_lambda_is_refused() -> None:
    """A negative multiplier admits trades BELOW the cost line.

    lambda is the Lagrange multiplier on the vol-target constraint, not a free mood parameter;
    negative means the portfolio is paid to take variance, which is not a thing.
    """
    with pytest.raises(ValueError, match="lambda"):
        optimal_threshold(CostLine(COST), lam=-0.1, sigma_trade=0.01)


def test_a_negative_trade_volatility_is_refused() -> None:
    with pytest.raises(ValueError, match="sigma"):
        optimal_threshold(CostLine(COST), lam=0.5, sigma_trade=-0.01)


# ------------------------------------------------------------ turnover is output -------


def test_turnover_falls_out_of_the_threshold() -> None:
    """T* = (opportunities clearing tau*) x ticket / capital. An output, never an input."""
    density = {0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0}  # edge -> opportunities per day
    tau = optimal_threshold(CostLine(COST), lam=0.0, sigma_trade=0.01)
    turnover = optimal_turnover(density, tau, ticket=50_000.0, capital=2_000_000.0)
    assert turnover == pytest.approx((12.0 + 3.0) * 50_000.0 / 2_000_000.0)


def test_raising_the_threshold_cannot_raise_turnover() -> None:
    density = {0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0}
    low = optimal_turnover(density, 0.0001, ticket=50_000.0, capital=2_000_000.0)
    high = optimal_turnover(density, 0.0010, ticket=50_000.0, capital=2_000_000.0)
    assert high < low


def test_there_is_no_way_to_ask_for_a_turnover_and_get_a_threshold() -> None:
    """`turnover is an output` is enforced by the API surface, not by a comment.

    A `threshold_for_turnover` helper would invert §6.2 into "pick the selectivity that hits
    the turnover we wanted", which is the exact reasoning the section refuses.
    """
    import pips.selection.turnover as module

    inverted = [n for n in dir(module) if "for_turnover" in n or "given_turnover" in n]
    assert inverted == []


def test_zero_capital_is_refused_rather_than_dividing() -> None:
    with pytest.raises(ValueError, match="capital"):
        optimal_turnover({0.002: 3.0}, 0.001, ticket=50_000.0, capital=0.0)


# ------------------------------------------------------------ per broker x tier --------


def test_a_cheaper_broker_earns_a_shorter_hold_and_a_lower_threshold() -> None:
    """Why these are computed per broker x tier at all: c differs, so the whole rule differs.

    Using one broker's cost line for another is not a small error — h* moves superlinearly in c.
    """
    cheap = CostLine(0.00025)
    dear = CostLine(0.00100)
    assert optimal_hold_power_law(a=A, gamma=GAMMA, cost=cheap.total) < optimal_hold_power_law(
        a=A, gamma=GAMMA, cost=dear.total
    )
    assert optimal_threshold(cheap, lam=0.5, sigma_trade=0.01) < optimal_threshold(
        dear, lam=0.5, sigma_trade=0.01
    )


def test_a_cost_line_reports_what_it_is_made_of() -> None:
    # An all-in number with no breakdown cannot be checked against a broker's schedule, and
    # cost is the one input that decides both rules.
    line = CostLine(total=0.0005, components={"brokerage": 0.0002, "impact": 0.0003})
    assert line.total == pytest.approx(sum(line.components.values()))


def test_components_that_do_not_sum_to_the_total_are_refused() -> None:
    """A breakdown that disagrees with the headline is worse than no breakdown.

    It is checkable and wrong, so it will be checked once, believed, and reused.
    """
    with pytest.raises(ValueError, match="sum"):
        CostLine(total=0.0005, components={"brokerage": 0.0002, "impact": 0.0001})


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "turnover-calculus" in CHECK_REGISTRY
    resolve_check("turnover-calculus")


def test_the_solver_is_deterministic() -> None:
    first = optimal_hold(power_law, COST, bracket=(0.1, 400.0))
    second = optimal_hold(power_law, COST, bracket=(0.1, 400.0))
    assert first == second
    assert math.isfinite(first)


def test_an_opportunity_exactly_at_the_threshold_is_admitted() -> None:
    """The boundary convention, pinned because the two sources disagree.

    §6.2 integrates `Trading all opportunities with g >= tau`, and the Part II family rules say
    `trade name i iff |g~(m_i)| > c + lambda*sigma`. For a continuous density the difference is
    a measure-zero set and nobody notices. This density is DISCRETE — the edge grid is a real
    dict — so the marginal opportunity lands exactly on tau and the convention decides whether
    it trades.

    Implemented as §6.2 states it, because that is the section this module derives, and pinned
    here so the choice is visible rather than whatever the comparison operator happened to be.
    At g == tau the trade breaks exactly even against the all-in line.
    """
    tau = optimal_threshold(CostLine(COST), lam=0.0, sigma_trade=0.01)
    density = {tau: 7.0, tau * 2: 2.0}
    turnover = optimal_turnover(density, tau, ticket=10_000.0, capital=1_000_000.0)
    assert turnover == pytest.approx((7.0 + 2.0) * 10_000.0 / 1_000_000.0)


# ------------------------------------------------------------ per broker x tier --------
#
# The M19 line item is "tau*, h* per broker x tier", and this is the thing anyone actually
# calls. It is where the closed form stops being pure algebra and becomes a recommendation,
# so it carries the check the algebra cannot.


def test_an_optimum_beyond_the_fitted_horizon_is_refused() -> None:
    """The trap the closed form cannot see: `a*h^gamma` grows without bound.

    So there is ALWAYS an h where gross edge clears any cost line, and the formula always
    returns a profitable-looking optimum — including at horizons far past where alpha(h) was
    ever measured. Real IC-decay curves saturate; the power law fitted to the first 60 minutes
    says nothing about 400, and extrapolating it produces a confident hold no data supports.

    The primitive stays pure algebra. The planner, which is what produces a recommendation,
    must be told the range the curve was fitted over and refuses an optimum outside it.
    """
    from pips.selection.turnover import plan_per_broker_tier

    with pytest.raises(ValueError, match="fitted"):
        plan_per_broker_tier(
            {("FLATTRADE", "2L"): CostLine(0.05)},  # a cost line so high h* lands far out
            a=A,
            gamma=GAMMA,
            fitted_horizon=60.0,
            lam=0.0,
            sigma_trade=0.01,
            density={0.06: 1.0},
            ticket=10_000.0,
            capital=1_000_000.0,
        )


def test_each_broker_and_tier_gets_its_own_rule() -> None:
    from pips.selection.turnover import plan_per_broker_tier

    plans = plan_per_broker_tier(
        {
            ("FLATTRADE", "2L"): CostLine(0.00025),
            ("FLATTRADE", "10L"): CostLine(0.00040),
            ("ZERODHA", "2L"): CostLine(0.00060),
        },
        a=A,
        gamma=GAMMA,
        fitted_horizon=120.0,
        lam=0.5,
        sigma_trade=0.001,
        density={0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0},
        ticket=50_000.0,
        capital=2_000_000.0,
    )
    assert len(plans) == 3
    by_key = {(p.broker, p.tier): p for p in plans}
    cheap = by_key[("FLATTRADE", "2L")]
    dear = by_key[("ZERODHA", "2L")]
    assert cheap.hold < dear.hold
    assert cheap.threshold < dear.threshold
    assert cheap.turnover >= dear.turnover


def test_the_plans_come_back_in_a_deterministic_order() -> None:
    from pips.selection.turnover import plan_per_broker_tier

    lines = {
        ("ZERODHA", "2L"): CostLine(0.00060),
        ("FLATTRADE", "10L"): CostLine(0.00040),
        ("FLATTRADE", "2L"): CostLine(0.00025),
    }

    def plan(source: dict[tuple[str, str], CostLine]) -> tuple[TurnoverPlan, ...]:
        return plan_per_broker_tier(
            source,
            a=A,
            gamma=GAMMA,
            fitted_horizon=120.0,
            lam=0.0,
            sigma_trade=0.001,
            density={0.0006: 12.0},
            ticket=50_000.0,
            capital=2_000_000.0,
        )

    first = plan(lines)
    second = plan(dict(reversed(list(lines.items()))))
    assert [(p.broker, p.tier) for p in first] == [(p.broker, p.tier) for p in second]


def test_a_broker_whose_costs_admit_nothing_is_reported_not_dropped() -> None:
    """A plan with zero admitted opportunities is a finding about that broker.

    Dropping it silently would leave a caller comparing two brokers where three were priced,
    and the missing one is precisely the one whose economics failed.
    """
    from pips.selection.turnover import plan_per_broker_tier

    plans = plan_per_broker_tier(
        {("CHEAP", "2L"): CostLine(0.00025), ("DEAR", "2L"): CostLine(0.00500)},
        a=A,
        gamma=GAMMA,
        fitted_horizon=100_000.0,
        lam=0.0,
        sigma_trade=0.001,
        density={0.0006: 12.0},
        ticket=50_000.0,
        capital=2_000_000.0,
    )
    assert len(plans) == 2
    dear = next(p for p in plans if p.broker == "DEAR")
    assert dear.turnover == 0.0
    assert dear.admits_nothing


def test_an_empty_set_of_cost_lines_is_refused() -> None:
    from pips.selection.turnover import plan_per_broker_tier

    with pytest.raises(ValueError, match="cost line"):
        plan_per_broker_tier(
            {},
            a=A,
            gamma=GAMMA,
            fitted_horizon=120.0,
            lam=0.0,
            sigma_trade=0.001,
            density={0.0006: 12.0},
            ticket=50_000.0,
            capital=2_000_000.0,
        )


def test_an_optimum_exactly_at_the_fitted_horizon_is_admitted() -> None:
    """The boundary is inclusive: the horizon is the last point the curve WAS measured at.

    Refusing there would reject an optimum the data supports, and the difference between `>`
    and `>=` is invisible on any fixture whose h* does not land exactly on the edge — so the
    horizon is computed from the cost line rather than guessed, to put it exactly there.
    """
    from pips.selection.turnover import plan_per_broker_tier

    cost = CostLine(0.00025)
    exact = optimal_hold_power_law(a=A, gamma=GAMMA, cost=cost.total)
    plans = plan_per_broker_tier(
        {("FLATTRADE", "2L"): cost},
        a=A,
        gamma=GAMMA,
        fitted_horizon=exact,
        lam=0.0,
        sigma_trade=0.001,
        density={0.0006: 12.0},
        ticket=50_000.0,
        capital=2_000_000.0,
    )
    assert plans[0].hold == exact
