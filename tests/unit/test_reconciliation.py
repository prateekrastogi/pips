"""F1-vs-vectorized reconciliation  [C-FILL-01] (§6 M14's third Verify).

The Verify is not "the two engines agree". They must NOT agree — F0 assumes every intended
trade happens at the bar price, and F1 models the ways it does not. The claim is stronger and
more useful: **every paise of the difference is named.**

So the decomposition is exhaustive by construction, and the residual is the test. If F0 and F1
differ by an amount the decomposition cannot attribute to slippage, to quantity that never
traded, or to a broker square-off, then one of the two engines is wrong — and a reconciliation
that reports that as a small number instead of a failure is how a wrong engine stays in
service. `unexplained_paise` must be exactly zero, in integer paise, with no tolerance.

This is the same discipline M10 applied inside F0 (`pnl_gross - costs == pnl_net`), now applied
BETWEEN the two engines, which is the only place a disagreement between them can be caught.
"""

from __future__ import annotations

import pytest

from pips.sim.protected_limit import Fill, Side
from pips.sim.reconcile import (
    IntendedTrade,
    ReconciliationError,
    reconcile,
)

REF = 100_000


def trade(side: Side = Side.BUY, quantity: int = 1_000, ref: int = REF) -> IntendedTrade:
    return IntendedTrade(
        instrument_id="RELIND", side=side, quantity=quantity, reference_price_paise=ref
    )


def fill(quantity: int, price: int, bar: int = 0) -> Fill:
    return Fill(bar_index=bar, quantity=quantity, price_paise=price)


# ------------------------------------------------------------ the identity -------------


def test_a_frictionless_f1_reconciles_to_zero_against_f0() -> None:
    """When F1's frictions all vanish it must equal F0 exactly, to the paise.

    If it does not, the two engines disagree about something other than execution — which
    means one of them is wrong about the trade itself, and no amount of friction modelling
    will explain the gap.
    """
    result = reconcile([(trade(), [fill(1_000, REF)], [])])
    assert result.unexplained_paise == 0
    assert result.slippage_paise == 0
    assert result.unfilled_notional_paise == 0
    assert result.forced_notional_paise == 0
    assert result.f0_cash_paise == result.f1_cash_paise


def test_slippage_is_named_and_signed_so_it_cannot_cancel_across_sides() -> None:
    """A buy filled above the reference and a sell filled below are BOTH F0 overstating.

    Get the sign wrong on one and a mixed book cancels: the two errors offset, the residual
    stays zero, and the reconciliation certifies an engine that is wrong in both directions.
    """
    buy = reconcile([(trade(Side.BUY), [fill(1_000, REF + 50)], [])])
    sell = reconcile([(trade(Side.SELL), [fill(1_000, REF - 50)], [])])
    assert buy.slippage_paise == 50_000
    assert sell.slippage_paise == 50_000

    both = reconcile(
        [
            (trade(Side.BUY), [fill(1_000, REF + 50)], []),
            (trade(Side.SELL), [fill(1_000, REF - 50)], []),
        ]
    )
    assert both.slippage_paise == 100_000, "the two must ADD, not cancel"
    assert both.unexplained_paise == 0


def test_quantity_that_never_traded_is_named_separately_from_price() -> None:
    # F0 booked 1,000 shares; F1 traded 300. The other 700 is not slippage — it is a trade
    # that did not happen, and calling it slippage would hide a fill-rate problem inside a
    # price-quality number.
    result = reconcile([(trade(), [fill(300, REF)], [])])
    assert result.slippage_paise == 0
    assert result.unfilled_notional_paise == -700 * REF
    assert result.unexplained_paise == 0


def test_a_forced_square_off_is_named_separately_from_voluntary_slippage() -> None:
    """Execution the strategy chose and execution the broker imposed are different facts.

    Merging them makes square-off invisible in exactly the number a live system watches to
    decide whether its flatten schedule is early enough.
    """
    result = reconcile([(trade(Side.SELL), [fill(300, REF)], [fill(700, REF - 200)])])
    assert result.slippage_paise == 0
    assert result.forced_notional_paise == 700 * 200
    assert result.unexplained_paise == 0


# ------------------------------------------------------------ the residual -------------


def test_an_overfill_is_caught_structurally_because_the_residual_never_could() -> None:
    """The check I nearly shipped as vacuous.

    These fills total MORE than the trade asked for — an F1 result inconsistent with its own
    intent. My first version relied on `unexplained_paise` to catch it, and it does not:
    `unfilled` is defined as *intended minus traded*, so the components close the identity by
    construction and an overfill is absorbed as a NEGATIVE unfilled quantity, reporting a
    residual of exactly zero.

    A decomposition that always closes is an identity, not a test. So the structural
    conditions are checked directly and unconditionally — a fill must be positive, and the
    traded total must not exceed the intent — while the residual is documented as the
    arithmetic self-check it actually is.
    """
    with pytest.raises(ReconciliationError, match=r"overfill|inconsistent"):
        reconcile([(trade(quantity=1_000), [fill(1_200, REF)], [])])


def test_the_residual_alone_would_have_reported_the_overfill_as_fine() -> None:
    """Pins WHY the structural check exists, so nobody removes it as redundant.

    Computed without the structural guard, the overfill's residual is exactly zero. If a future
    reader assumes `unexplained_paise` covers this, the guard looks like belt-and-braces and
    gets deleted.
    """
    from pips.sim.reconcile import _cash

    intended = trade(quantity=1_000)
    f0 = _cash(intended.side, intended.quantity, REF)
    f1 = _cash(intended.side, 1_200, REF)
    unfilled = _cash(intended.side, intended.quantity - 1_200, REF)
    assert (f0 - f1) - unfilled == 0, "the identity closes even on an impossible fill"


def test_a_non_positive_fill_is_refused() -> None:
    for bad in (0, -100):
        with pytest.raises(ReconciliationError, match="not a fill"):
            reconcile([(trade(), [fill(bad, REF)], [])])


# ------------------------------------------------------------ shape --------------------


def test_everything_is_integer_paise() -> None:
    result = reconcile([(trade(Side.BUY), [fill(333, REF + 7)], [fill(667, REF + 13)])])
    for value in (
        result.f0_cash_paise,
        result.f1_cash_paise,
        result.slippage_paise,
        result.unfilled_notional_paise,
        result.forced_notional_paise,
        result.unexplained_paise,
    ):
        assert isinstance(value, int)


def test_an_empty_book_of_trades_is_refused() -> None:
    # Reconciling nothing trivially succeeds, which is exactly the green that means nothing.
    with pytest.raises(ValueError, match="no trades"):
        reconcile([])


def test_the_same_input_reconciles_identically() -> None:
    book = [(trade(Side.BUY), [fill(400, REF + 5)], [fill(600, REF + 9)])]
    assert reconcile(book) == reconcile(book)
