"""The netting fixed point  (§10.2, M19).

§10.2: the combined-blotter simulation measures the netting ratio and RE-PRICES the ensemble's
cost line, which in turn shifts each member's optimal threshold — and S5 iterates that to a
fixed point.

The loop closes because the pieces feed each other. If the ensemble's external turnover is
`(1 - ratio)` of the members' summed turnover, then the costs actually paid, attributed per unit
of intended turnover, are `c * (1 - ratio)`. Each member prices its trades at that lower line,
so tau* falls, so more trades are admitted, so the blotter changes — and the ratio has to be
measured again.

**The feedback runs the flattering way.** Every pass can only lower the cost line, which can only
admit more trades. A generator whose crossing improves with volume drives `c` toward zero, and
a cost line of zero admits everything. So this refuses to converge on a degenerate answer rather
than reporting one.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from pips.selection.netting import (
    BlotterOrder,
    NettingFixedPointError,
    solve_netting_fixed_point,
)
from pips.selection.turnover import CostLine

MINUTE = 60 * 1_000_000_000
OPEN = 1_772_000_000 * 1_000_000_000
GROSS = CostLine(0.0005)


def o(symbol: str, minute: int, qty: int, price: str = "100.00") -> BlotterOrder:
    return BlotterOrder(
        "F1" if qty > 0 else "F5", symbol, OPEN + minute * MINUTE, qty, Decimal(price)
    )


# ------------------------------------------------------------ the loop ----------------


def test_a_blotter_with_no_crossing_leaves_the_cost_line_alone() -> None:
    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        return [o("RELIANCE", 0, +100), o("TCS", 0, +50)]

    result = solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)
    assert result.netting_ratio == pytest.approx(0.0)
    assert result.effective_cost.total == GROSS.total


def test_the_repriced_line_is_the_gross_line_scaled_by_what_did_not_cross() -> None:
    """The defining identity: `c_eff = c * (1 - ratio)`.

    Not `c * ratio` and not `c / (1 - ratio)`. Each of those is a plausible-looking rescaling
    that moves the threshold the wrong way or the right way by the wrong amount.
    """

    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        return [o("RELIANCE", 0, +100), o("RELIANCE", 0, -60)]

    result = solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)
    assert result.netting_ratio == pytest.approx(0.75)
    assert result.effective_cost.total == pytest.approx(GROSS.total * 0.25, rel=1e-9)


def test_the_first_pass_prices_at_the_gross_line() -> None:
    """The conservative start: assume nothing crossed until the blotter says it did.

    Starting from an optimistic ratio would admit trades on a saving that has not been measured
    yet, and the fixed point it walks to inherits that.
    """
    seen: list[float] = []

    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        seen.append(cost.total)
        return [o("RELIANCE", 0, +100), o("RELIANCE", 0, -60)]

    solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)
    assert seen[0] == GROSS.total


def test_a_blotter_that_responds_to_the_cost_line_still_settles() -> None:
    # A cheaper line admits an extra name, which happens to cross — so the ratio rises, the
    # line falls again, and the loop has to actually converge rather than assume one pass.
    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        orders = [o("RELIANCE", 0, +100), o("RELIANCE", 0, -60)]
        if cost.total < 0.00045:
            orders += [o("TCS", 0, +40), o("TCS", 0, -30)]
        return orders

    result = solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)
    assert result.iterations > 1
    assert result.effective_cost.total == pytest.approx(
        GROSS.total * (1 - result.netting_ratio), rel=1e-9
    )


def test_the_solve_is_deterministic() -> None:
    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        return [o("RELIANCE", 0, +100), o("RELIANCE", 0, -60)]

    first = solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)
    second = solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)
    assert first.effective_cost.total == second.effective_cost.total
    assert first.iterations == second.iterations


# ------------------------------------------------------------ degenerate answers ------


def test_a_ratio_of_one_is_refused_rather_than_pricing_costs_at_zero() -> None:
    """Perfect crossing means the ensemble sends nothing to the market.

    Its cost per unit of intended turnover is then not zero but undefined — there is no external
    trade to attribute a cost to. Reporting zero would set tau* = c = 0, which admits every
    opportunity regardless of edge, and it would look like the best result the search ever found.
    """

    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        return [o("RELIANCE", 0, +100), o("RELIANCE", 0, -100)]

    with pytest.raises(NettingFixedPointError, match="entirely internal"):
        solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)


def test_an_oscillating_generator_is_refused_not_reported() -> None:
    """The same failure shape as §6.3: the last pass is an ordinary-looking number.

    Here a cheaper line admits a name that does NOT cross, which lowers the ratio, which raises
    the line again, which drops the name. Nothing about either half is wrong.
    """

    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        orders = [o("RELIANCE", 0, +100), o("RELIANCE", 0, -60)]
        if cost.total < 0.0004:
            orders += [o("TCS", 0, +900)]
        return orders

    # The PERIOD is asserted, not just the word "cycle": the label is computed from a position
    # in the history and an off-by-one there is invisible to a bare `match="cycle"`.
    with pytest.raises(NettingFixedPointError, match="cycle of period 2"):
        solve_netting_fixed_point(blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE)


def test_exhausting_the_pass_budget_is_refused() -> None:
    def generate(cost: CostLine) -> Sequence[BlotterOrder]:
        # A ratio that creeps every pass and never settles inside the budget.
        extra = int(cost.total * 1_000_000)
        return [o("RELIANCE", 0, +100), o("RELIANCE", 0, -(50 + extra % 7))]

    with pytest.raises(NettingFixedPointError, match="max_passes"):
        solve_netting_fixed_point(
            blotter_for=generate, gross_cost=GROSS, bucket_ns=MINUTE, max_passes=2
        )


def test_there_is_no_way_to_get_the_last_pass_of_a_failed_solve() -> None:
    import inspect

    names = set(inspect.signature(solve_netting_fixed_point).parameters)
    assert not names & {"strict", "allow_unconverged", "best_effort"}


def test_a_generator_that_produces_nothing_is_refused() -> None:
    # An empty blotter has no ratio (nothing traded is not nothing crossed), and that has to
    # surface as the refusal it is rather than as a cost line left untouched.
    with pytest.raises(ValueError, match="no turnover"):
        solve_netting_fixed_point(blotter_for=lambda cost: [], gross_cost=GROSS, bucket_ns=MINUTE)
