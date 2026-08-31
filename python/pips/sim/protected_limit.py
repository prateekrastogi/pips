"""F1 protected marketable-limit state machine  [C-FILL-01] (§6 M14, §3.8).

§3.8 defines F1 as *"next-event protected marketable-limit with partial/reject/timeout/
reprice-cap states, integer shares, tick rounding"*, and every T1 spec's execution policy names
it: ``order_type: protected marketable limit``, ``reprice_cap: 2``, ``timeout_bars: 1``.

What this exists to get right is the unsuccessful order, because that is where a simulator
flatters. Three rules carry the weight:

**The outcome is reported, never the intent.** An order for 1,000 shares that got 300 and then
timed out leaves the strategy holding 300. Recording 1,000 computes P&L on a position that
never existed, in whichever direction the model assumed, and no downstream check can find it
because the position series is internally consistent.

**The reprice cap is a hard cap.** ``reprice_cap: 2`` means two, not "two unless it is nearly
filled". An order that keeps chasing is an order with no worst case, and its backtest is a
promise the venue never made.

**Repricing is costed by the market, not by a penalty.** Each reprice re-marks the limit to the
touch as it then is — usually worse, because that is why the order did not fill. Nothing is
added on top: an invented penalty is a parameter nobody can falsify, and a parameter nobody can
falsify is a parameter that gets tuned.

Rounding is conservative in both directions — a buy limit rounds UP to the tick grid, a sell
DOWN. A buy rounded down is a limit the exchange would have rejected, filling in the backtest
at a price that was never available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "BookEvent",
    "Fill",
    "OrderIntent",
    "OrderOutcome",
    "OrderState",
    "Side",
    "simulate",
]


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderState(StrEnum):
    """Terminal states only -- an in-flight order is not a result."""

    FILLED = "FILLED"
    """The full quantity traded."""

    EXPIRED = "EXPIRED"
    """Repricings exhausted, or events ran out, with quantity outstanding."""

    REJECTED = "REJECTED"
    """The venue refused it. Terminal, and NOT retried: a rejection is information."""


@dataclass(frozen=True)
class OrderIntent:
    """What the strategy asked for. Not what it got."""

    instrument_id: str
    side: Side
    quantity: int
    tick_size_paise: int
    protection_ticks: int
    reprice_cap: int
    timeout_bars: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(
                f"quantity must be a positive whole number of shares, got {self.quantity}"
            )
        if self.tick_size_paise <= 0:
            raise ValueError(f"tick_size_paise must be positive, got {self.tick_size_paise}")
        if self.reprice_cap < 0:
            raise ValueError(f"reprice_cap must not be negative, got {self.reprice_cap}")
        if self.timeout_bars < 1:
            raise ValueError(f"timeout_bars must be at least 1, got {self.timeout_bars}")


@dataclass(frozen=True)
class BookEvent:
    """One bar of the venue as the order sees it."""

    bar_index: int
    bid_paise: int
    ask_paise: int
    available_qty: int
    """Shares that could trade against a marketable order in this bar. Zero is a real answer."""
    rejected: bool = False


@dataclass(frozen=True)
class Fill:
    bar_index: int
    quantity: int
    price_paise: int


@dataclass(frozen=True)
class OrderOutcome:
    """What actually happened, in whole shares and integer paise."""

    state: OrderState
    fills: list[Fill] = field(default_factory=list)
    reprices: int = 0
    limit_history: list[int] = field(default_factory=list)

    @property
    def filled_quantity(self) -> int:
        return sum(f.quantity for f in self.fills)

    @property
    def filled_notional_paise(self) -> int:
        """Exact, because both factors are integers. No rounding slack anywhere."""
        return sum(f.quantity * f.price_paise for f in self.fills)

    @property
    def unfilled_quantity(self) -> int:
        """Reported rather than dropped -- the difference between intent and outcome."""
        return self._requested - self.filled_quantity

    _requested: int = 0


def _round_to_tick(price_paise: int, tick: int, side: Side) -> int:
    """Round a limit onto the tick grid, always against the order.

    A buy rounded DOWN would be a limit the exchange rejects, filling in the backtest at a
    price that was never available; a sell rounded UP is the same error mirrored.
    """
    if side is Side.BUY:
        return -(-price_paise // tick) * tick
    return (price_paise // tick) * tick


def _limit_for(intent: OrderIntent, event: BookEvent) -> int:
    """A marketable limit with protection: cross the touch, but only by so much."""
    protection = intent.protection_ticks * intent.tick_size_paise
    raw = event.ask_paise + protection if intent.side is Side.BUY else event.bid_paise - protection
    return _round_to_tick(raw, intent.tick_size_paise, intent.side)


def simulate(intent: OrderIntent, events: list[BookEvent]) -> OrderOutcome:
    """Walk one order through a bar sequence. Pure, deterministic, integer throughout."""
    fills: list[Fill] = []
    limits: list[int] = []
    remaining = intent.quantity
    reprices = 0
    bars_at_limit = 0
    state = OrderState.EXPIRED

    for event in events:
        if event.rejected:
            # Terminal, and whatever filled before it stands. Retrying a rejection inside the
            # simulator would model a venue that does not exist, and would do it silently.
            return OrderOutcome(
                state=OrderState.REJECTED,
                fills=fills,
                reprices=reprices,
                limit_history=limits,
                _requested=intent.quantity,
            )

        limit = _limit_for(intent, event)
        limits.append(limit)

        traded = min(remaining, max(0, event.available_qty))
        if traded:
            # The fill happens at the touch, not at the limit: the limit is a ceiling on what
            # we would pay, and paying it when the market was better would flatter nothing —
            # it would just be wrong in the other direction.
            price = event.ask_paise if intent.side is Side.BUY else event.bid_paise
            fills.append(Fill(bar_index=event.bar_index, quantity=traded, price_paise=price))
            remaining -= traded
            bars_at_limit = 0
            if remaining == 0:
                state = OrderState.FILLED
                break
            continue

        bars_at_limit += 1
        if bars_at_limit >= intent.timeout_bars:
            if reprices >= intent.reprice_cap:
                break  # the cap is a cap; the remainder is simply not ours
            reprices += 1
            bars_at_limit = 0

    return OrderOutcome(
        state=state,
        fills=fills,
        reprices=reprices,
        limit_history=limits,
        _requested=intent.quantity,
    )
