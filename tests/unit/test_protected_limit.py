"""F1 protected marketable-limit state machine  [C-FILL-01] (§6 M14, §3.8).

§3.8 defines F1 as *"next-event protected marketable-limit with partial/reject/timeout/
reprice-cap states, integer shares, tick rounding"*, and every T1 spec's execution policy
names it: `order_type: protected marketable limit`, `reprice_cap: 2`, `timeout_bars: 1`.

The tests that matter here are not the ones where an order fills. They are the ones where it
does not:

**A partial fill that then expires must never be recorded as a fill.** This is the whole
family of errors this project keeps finding, arriving in the place where it costs actual money:
an order for 1,000 shares that got 300 and then timed out leaves the strategy holding 300, not
1,000. A backtest that records the intent rather than the outcome computes P&L on a position
that never existed — and it does so in whichever direction the model assumed, silently.

**The reprice cap is a hard cap.** `reprice_cap: 2` means two, not "two unless it is nearly
filled". An order that keeps chasing is an order with no worst case.

**Repricing is costed by the market, not by a fudge factor.** Each reprice re-marks the limit
to the touch as it then is — usually worse. Nothing is added on top, because an invented
penalty is a parameter nobody can falsify.
"""

from __future__ import annotations

import pytest

from pips.sim.protected_limit import (
    BookEvent,
    OrderIntent,
    OrderState,
    Side,
    simulate,
)


def intent(**over: object) -> OrderIntent:
    base: dict[str, object] = {
        "instrument_id": "RELIND",
        "side": Side.BUY,
        "quantity": 1_000,
        "tick_size_paise": 5,
        "protection_ticks": 2,
        "reprice_cap": 2,
        "timeout_bars": 1,
    }
    base.update(over)
    return OrderIntent(**base)  # type: ignore[arg-type]


def book(
    bar: int, bid: int = 99_990, ask: int = 100_000, qty: int = 0, **over: object
) -> BookEvent:
    base: dict[str, object] = {
        "bar_index": bar,
        "bid_paise": bid,
        "ask_paise": ask,
        "available_qty": qty,
        "rejected": False,
    }
    base.update(over)
    return BookEvent(**base)  # type: ignore[arg-type]


# ------------------------------------------------- the outcome, not the intent ----------


def test_a_partial_fill_that_expires_reports_what_actually_filled() -> None:
    """The error that costs money.

    1,000 requested, 300 filled, then the order runs out of repricings. The strategy holds
    300 shares. Recording 1,000 would compute P&L on a position that never existed, in
    whichever direction the model assumed.
    """
    events = [book(0, qty=300), book(1, qty=0), book(2, qty=0), book(3, qty=0), book(4, qty=0)]
    outcome = simulate(intent(), events)

    assert outcome.filled_quantity == 300
    assert outcome.unfilled_quantity == 700
    assert outcome.state is OrderState.EXPIRED
    assert sum(f.quantity for f in outcome.fills) == outcome.filled_quantity


def test_an_unfilled_order_is_not_a_zero_cost_success() -> None:
    outcome = simulate(intent(), [book(i) for i in range(6)])
    assert outcome.filled_quantity == 0
    assert outcome.unfilled_quantity == 1_000
    assert outcome.state is OrderState.EXPIRED
    assert outcome.fills == []


def test_partials_accumulate_and_never_overfill() -> None:
    events = [book(0, qty=400), book(1, qty=400), book(2, qty=400)]
    outcome = simulate(intent(), events)
    assert outcome.filled_quantity == 1_000, "the third bar must fill only the 200 remaining"
    assert outcome.state is OrderState.FILLED
    assert [f.quantity for f in outcome.fills] == [400, 400, 200]


# ------------------------------------------------- the reprice cap ----------------------


def test_the_reprice_cap_is_a_hard_cap() -> None:
    # An order that keeps chasing is an order with no worst case.
    outcome = simulate(intent(reprice_cap=2), [book(i) for i in range(20)])
    assert outcome.reprices == 2
    assert outcome.state is OrderState.EXPIRED


def test_a_zero_reprice_cap_means_one_attempt_only() -> None:
    outcome = simulate(intent(reprice_cap=0), [book(i) for i in range(10)])
    assert outcome.reprices == 0
    assert outcome.state is OrderState.EXPIRED


def test_repricing_follows_the_market_rather_than_an_invented_penalty() -> None:
    """Each reprice re-marks the limit to the touch as it then is.

    The cost of chasing is the market having moved, which is a fact. An added penalty would be
    a parameter nobody could falsify, and it would be tuned.
    """
    events = [
        book(0, bid=99_990, ask=100_000),
        book(1, bid=100_090, ask=100_100),  # market ran away
        book(2, bid=100_190, ask=100_200, qty=1_000),
    ]
    outcome = simulate(intent(), events)
    assert outcome.filled_quantity == 1_000
    # THE EXACT PRICE, not merely a bound. `> 100_000` was satisfied by the ORIGINAL limit
    # (100_010 after protection and rounding), so filling at the starting limit passed it —
    # which is the precise bug the test was written to catch.
    assert outcome.fills[0].price_paise == 100_200, (
        "the fill must be at the market where it happened, not where the order started"
    )


# ------------------------------------------------- shape and rounding -------------------


def test_a_buy_limit_rounds_up_to_the_tick_and_a_sell_rounds_down() -> None:
    """Rounding is conservative: against the order, both ways.

    A buy limit rounded DOWN to the tick would be a limit you could not actually have posted,
    and it would fill in the backtest at a price the exchange would have rejected.
    """
    # PROTECTION IS ZERO HERE, on purpose. With protection ticks the raw limit sits well past
    # the touch, so "the limit is at least the ask" holds under either rounding direction and
    # the assertion proves nothing — a mutation run confirmed it. Stripping the protection
    # puts the raw limit exactly on the ask, where the two directions straddle it.
    off_grid = dict(tick_size_paise=25, protection_ticks=0)
    buy = simulate(intent(side=Side.BUY, **off_grid), [book(0, ask=100_010, qty=1_000)])
    sell = simulate(intent(side=Side.SELL, **off_grid), [book(0, bid=99_990, qty=1_000)])

    assert buy.limit_history[0] % 25 == 0
    assert sell.limit_history[0] % 25 == 0
    assert buy.limit_history[0] == 100_025, "a buy limit must round UP; 100_000 is below the ask"
    assert sell.limit_history[0] == 99_975, "a sell limit must round DOWN; 100_000 is above the bid"


def test_fills_are_whole_shares() -> None:
    events = [book(0, qty=333), book(1, qty=333), book(2, qty=333), book(3, qty=333)]
    outcome = simulate(intent(quantity=999), events)
    assert all(isinstance(f.quantity, int) and f.quantity > 0 for f in outcome.fills)
    assert outcome.filled_quantity == 999


def test_a_zero_or_negative_quantity_is_refused() -> None:
    for bad in (0, -100):
        with pytest.raises(ValueError, match="quantity"):
            intent(quantity=bad)


def test_a_tick_size_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="tick"):
        intent(tick_size_paise=0)


# ------------------------------------------------- rejects ------------------------------


def test_a_reject_is_terminal_and_is_not_silently_retried() -> None:
    events = [book(0, qty=400), book(1, rejected=True), book(2, qty=1_000)]
    outcome = simulate(intent(), events)
    assert outcome.state is OrderState.REJECTED
    assert outcome.filled_quantity == 400, "the fill before the reject stands; nothing after it"


# ------------------------------------------------- determinism --------------------------


def test_the_same_event_sequence_replays_identically() -> None:
    # §6 M14's first Verify. A simulator whose result depends on anything but its inputs
    # cannot anchor a backtest to a snapshot root.
    events = [book(0, qty=300), book(1, qty=0), book(2, qty=250), book(3, qty=0)]
    first, second = simulate(intent(), events), simulate(intent(), events)
    assert first == second


def test_the_accounting_identity_holds_over_the_fills() -> None:
    # §6 M14: filled notional must reconcile to the paise, with no rounding slack anywhere.
    events = [book(0, qty=400), book(1, qty=600)]
    outcome = simulate(intent(), events)
    assert outcome.filled_notional_paise == sum(f.quantity * f.price_paise for f in outcome.fills)
