"""Flatten scheduler  [C-FILL-01] (§6 M14, §3.15 FLATTEN_ONLY).

Intraday positions must be flat by the broker's square-off time, which comes from the daily
capability snapshot — 15:00 for Flattrade MIS, and marked unverified.

**A missed flatten is not a position that persists.** That is the modelling error this file
exists to prevent, and it flatters in a specific way: a simulator that carries an unflattened
position into the next bar has the strategy holding exposure it did not choose to hold and
could not have held — the broker squares it off, at the broker's timing and the broker's price.
Carrying it forward gives the backtest a free overnight option.

**Scheduling the flatten AT the cutoff is not scheduling it.** An F1 order needs up to
`timeout_bars x (reprice_cap + 1)` bars to conclude. Starting at the deadline guarantees it
does not finish, so the scheduler works backwards from the cutoff rather than forwards from
the signal.

**The forced square-off is not given an invented slippage.** It fills at the touch, like any
marketable order. What it costs is not a fudged number of ticks; it is the loss of control over
timing and price, and the honest way to represent that is to RECORD it — flagged, countable,
available to TCA — rather than to guess a penalty nobody can falsify.
"""

from __future__ import annotations

import pytest

from pips.sim.flatten import (
    FlattenOutcome,
    plan_flatten,
    simulate_flatten,
)
from pips.sim.protected_limit import BookEvent, OrderIntent, Side


def intent(**over: object) -> OrderIntent:
    base: dict[str, object] = {
        "instrument_id": "RELIND",
        "side": Side.SELL,  # flattening a long
        "quantity": 1_000,
        "tick_size_paise": 5,
        "protection_ticks": 2,
        "reprice_cap": 2,
        "timeout_bars": 1,
    }
    base.update(over)
    return OrderIntent(**base)  # type: ignore[arg-type]


def book(bar: int, qty: int = 0, bid: int = 99_990, ask: int = 100_000) -> BookEvent:
    return BookEvent(bar_index=bar, bid_paise=bid, ask_paise=ask, available_qty=qty, rejected=False)


# ------------------------------------------------------------ the schedule --------------


def test_starting_at_the_cutoff_does_not_fit() -> None:
    """The scheduler must work backwards, not forwards.

    An order with one timeout bar and two repricings can occupy three bars before it concludes.
    Released at the cutoff it has none of them.
    """
    plan = plan_flatten(intent(), cutoff_bar=100, start_bar=100)
    assert plan.bars_required == 3
    assert not plan.fits


def test_starting_exactly_bars_required_before_the_cutoff_fits() -> None:
    plan = plan_flatten(intent(), cutoff_bar=100, start_bar=97)
    assert plan.fits
    assert plan.latest_start_bar == 97


def test_one_bar_later_than_the_latest_start_does_not_fit() -> None:
    # The control for the test above: without it, `fits` could be a constant.
    assert not plan_flatten(intent(), cutoff_bar=100, start_bar=98).fits


def test_a_bigger_reprice_budget_needs_an_earlier_start() -> None:
    tight = plan_flatten(intent(reprice_cap=0), cutoff_bar=100, start_bar=99)
    loose = plan_flatten(intent(reprice_cap=5), cutoff_bar=100, start_bar=99)
    assert tight.fits and not loose.fits
    assert loose.bars_required > tight.bars_required


# ------------------------------------------------- the forced square-off ----------------


def test_an_unflattened_remainder_is_forced_not_carried() -> None:
    """The error that hands the backtest a free overnight option.

    300 of 1,000 flatten voluntarily; the rest does not trade. At the cutoff the broker squares
    off the remaining 700. A simulator that carries those 700 forward has the strategy holding
    exposure it did not choose and could not have held.
    """
    events = [book(0, qty=300), book(1), book(2), book(3)]
    result = simulate_flatten(intent(), events, cutoff_bar=3)

    assert result.outcome is FlattenOutcome.FORCED_SQUARE_OFF
    assert result.voluntary_quantity == 300
    assert result.forced_quantity == 700
    assert result.voluntary_quantity + result.forced_quantity == 1_000


def test_a_completed_flatten_reports_no_forced_quantity() -> None:
    events = [book(0, qty=600), book(1, qty=400), book(2)]
    result = simulate_flatten(intent(), events, cutoff_bar=2)
    assert result.outcome is FlattenOutcome.FLAT_IN_TIME
    assert result.forced_quantity == 0
    assert result.voluntary_quantity == 1_000


def test_the_forced_fill_is_recorded_separately_from_the_voluntary_ones() -> None:
    """A forced fill must never be indistinguishable from a chosen one.

    The two are different facts about the same trade: one is execution, the other is a
    consequence. Merging them makes broker square-off invisible to TCA, which is precisely the
    number a live system needs to watch.
    """
    events = [book(0, qty=300), book(1), book(2), book(3)]
    result = simulate_flatten(intent(), events, cutoff_bar=3)
    assert len(result.forced_fills) == 1
    assert result.forced_fills[0].quantity == 700
    assert all(f.quantity == 300 for f in result.voluntary_fills)


def test_the_forced_fill_is_priced_at_the_touch_not_at_an_invented_penalty() -> None:
    # Inventing a slippage would be a parameter nobody could falsify. What the forced
    # square-off costs is the loss of control, and the honest representation of that is to
    # record it, not to guess a number of ticks.
    events = [book(0), book(1), book(2), book(3, bid=98_000, ask=98_010)]
    result = simulate_flatten(intent(), events, cutoff_bar=3)
    assert result.forced_fills[0].price_paise == 98_000, "a forced SELL fills at the bid"


def test_no_position_is_reported_as_nothing_to_flatten() -> None:
    """ "There was nothing to do" and "we did it" are different facts.

    The absence is expressed as `None`, not as a zero-quantity order: `OrderIntent` already
    refuses a quantity of zero, because an order for no shares is not a thing a venue accepts.
    The first draft of this test tried to smuggle the empty case in as an order and was
    refused at construction — correctly.
    """
    result = simulate_flatten(None, [book(0)], cutoff_bar=0)
    assert result.outcome is FlattenOutcome.NOTHING_TO_FLATTEN
    assert result.voluntary_quantity == 0 and result.forced_quantity == 0


def test_a_cutoff_before_the_first_event_forces_everything() -> None:
    result = simulate_flatten(intent(), [book(0, qty=1_000)], cutoff_bar=-1)
    assert result.outcome is FlattenOutcome.FORCED_SQUARE_OFF
    assert result.forced_quantity == 1_000


def test_the_same_events_replay_identically() -> None:
    events = [book(0, qty=300), book(1), book(2, qty=200), book(3)]
    assert simulate_flatten(intent(), events, cutoff_bar=3) == simulate_flatten(
        intent(), events, cutoff_bar=3
    )


def test_a_flatten_against_an_empty_book_is_refused() -> None:
    # A forced square-off with no quote has no price to reference. Inventing one would put a
    # fabricated fill into the accounting, which is worse than failing.
    with pytest.raises(ValueError, match="empty book"):
        simulate_flatten(intent(), [], cutoff_bar=0)
