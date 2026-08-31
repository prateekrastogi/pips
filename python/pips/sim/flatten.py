"""Flatten scheduler  [C-FILL-01] (§6 M14, §3.15 FLATTEN_ONLY).

Intraday positions must be flat by the broker's square-off time, which comes from the daily
capability snapshot (:mod:`pips.data.pit.capability_master`) — 15:00 for Flattrade MIS, and
still marked unverified.

Three things this gets right, each because getting it wrong flatters:

**A missed flatten is not a position that persists.** A simulator that carries an unflattened
position into the next bar has the strategy holding exposure it did not choose and could not
have held: the broker squares it off, at the broker's timing and the broker's price. Carrying it
forward hands the backtest a free overnight option — and one that only ever helps, because a
position the strategy wanted closed is a position whose continued gains it never earned.

**Scheduling the flatten AT the cutoff is not scheduling it.** An F1 order can occupy
``timeout_bars x (reprice_cap + 1)`` bars before it concludes. Released at the deadline it has
none of them, so :func:`plan_flatten` works backwards from the cutoff rather than forwards from
the signal.

**The forced square-off gets no invented slippage.** It fills at the touch, like any marketable
order. What it costs is not a fudged number of ticks; it is the loss of control over timing and
price — and the honest way to carry that is to RECORD it, flagged and countable and available
to TCA, rather than to guess a penalty nobody can falsify. The same reasoning as F1's reprice,
which is costed by the market having moved rather than by a constant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pips.sim.protected_limit import BookEvent, Fill, OrderIntent, Side, simulate

__all__ = ["FlattenOutcome", "FlattenPlan", "FlattenResult", "plan_flatten", "simulate_flatten"]


class FlattenOutcome(StrEnum):
    """How the flatten ended. Three outcomes, and they are not interchangeable."""

    FLAT_IN_TIME = "FLAT_IN_TIME"
    """The strategy closed its own position before the cutoff."""

    FORCED_SQUARE_OFF = "FORCED_SQUARE_OFF"
    """The broker closed some or all of it. Execution the strategy did not choose."""

    NOTHING_TO_FLATTEN = "NOTHING_TO_FLATTEN"
    """There was no position. Distinct from having successfully closed one -- reporting the
    second for the first overstates what the machinery has been shown to do."""


@dataclass(frozen=True)
class FlattenPlan:
    """When flattening must begin for it to have a chance of completing."""

    bars_required: int
    latest_start_bar: int
    start_bar: int
    cutoff_bar: int

    @property
    def fits(self) -> bool:
        return self.start_bar <= self.latest_start_bar


@dataclass(frozen=True)
class FlattenResult:
    """What actually closed the position, and who closed it."""

    outcome: FlattenOutcome
    voluntary_fills: list[Fill] = field(default_factory=list)
    forced_fills: list[Fill] = field(default_factory=list)

    @property
    def voluntary_quantity(self) -> int:
        return sum(f.quantity for f in self.voluntary_fills)

    @property
    def forced_quantity(self) -> int:
        return sum(f.quantity for f in self.forced_fills)

    @property
    def notional_paise(self) -> int:
        return sum(f.quantity * f.price_paise for f in (*self.voluntary_fills, *self.forced_fills))


def plan_flatten(intent: OrderIntent, cutoff_bar: int, start_bar: int) -> FlattenPlan:
    """Whether a flatten released at ``start_bar`` can conclude before ``cutoff_bar``.

    ``bars_required`` is the order's own worst case: each repricing gets a fresh timeout, and
    the initial attempt is one more. Nothing here is a safety margin — a margin would be a
    number to tune, and the worst case is a fact about the order.
    """
    bars_required = intent.timeout_bars * (intent.reprice_cap + 1)
    return FlattenPlan(
        bars_required=bars_required,
        latest_start_bar=cutoff_bar - bars_required,
        start_bar=start_bar,
        cutoff_bar=cutoff_bar,
    )


def simulate_flatten(
    intent: OrderIntent | None,
    events: list[BookEvent],
    cutoff_bar: int,
) -> FlattenResult:
    """Flatten voluntarily where possible; force the remainder at the cutoff.

    ``intent is None`` means there is no position, and the type says so rather than a
    zero-quantity order saying it. :class:`OrderIntent` already refuses a quantity of zero —
    an order for no shares is not a thing a venue accepts — so "nothing to flatten" cannot be
    expressed as an order and should not be smuggled in as one.
    """
    if intent is None:
        return FlattenResult(outcome=FlattenOutcome.NOTHING_TO_FLATTEN)

    before_cutoff = [e for e in events if e.bar_index < cutoff_bar]
    voluntary = simulate(intent, before_cutoff) if before_cutoff else None
    voluntary_fills = list(voluntary.fills) if voluntary else []
    remaining = intent.quantity - sum(f.quantity for f in voluntary_fills)

    if remaining == 0:
        return FlattenResult(outcome=FlattenOutcome.FLAT_IN_TIME, voluntary_fills=voluntary_fills)

    # The broker squares off the remainder at the cutoff bar, at the touch. If there is no
    # event at the cutoff there is still a square-off — a missing quote does not mean a
    # missing obligation — so the nearest available touch is used and the fill is flagged
    # exactly as any other forced one.
    at_cutoff = next((e for e in events if e.bar_index == cutoff_bar), None)
    reference = at_cutoff or (events[-1] if events else None)
    if reference is None:
        raise ValueError(
            "no book events at all, so the forced square-off has no price to reference. "
            "A flatten cannot be simulated against an empty book."
        )
    price = reference.bid_paise if intent.side is Side.SELL else reference.ask_paise
    return FlattenResult(
        outcome=FlattenOutcome.FORCED_SQUARE_OFF,
        voluntary_fills=voluntary_fills,
        forced_fills=[Fill(bar_index=cutoff_bar, quantity=remaining, price_paise=price)],
    )
