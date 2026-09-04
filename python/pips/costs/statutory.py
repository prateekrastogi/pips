"""The NSE cash-equity intraday charge stack  [C-COST-01] [C-COST-02] (§3.7).

Every charge is computed in **integer paise** [C-NUM-01]: rates are ``Decimal``, the maths is
exact, and the only rounding is one half-to-even step per order — which is what a contract
note does. Rounding per component instead would drift against the goldens and, worse, would
drift differently at different notionals.

The rate set lives in ``config/costs/*.yaml`` with its source and verification date, because
costs are effective-dated data and not constants (rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from pips.costs.schedule import CostSchedule

__all__ = ["Broker", "OrderCost", "OrderSide", "RoundTripCost", "order_cost", "round_trip_cost"]


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Broker(StrEnum):
    FLATTRADE = "FLATTRADE"
    # Not a venue (ADR-0010). Retained as the P3 gate's stress line at full severity.
    HIGH_COST_REFERENCE = "HIGH_COST_REFERENCE"


def _to_paise(value: Decimal) -> int:
    """Half-to-even to whole paise -- the project's rounding rule [C-NUM-01]."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class OrderCost:
    """The charge breakdown for one order, in paise."""

    broker: Broker
    side: OrderSide
    notional_paise: int
    brokerage_paise: int
    exchange_paise: int
    ipft_paise: int
    sebi_paise: int
    stt_paise: int
    stamp_paise: int
    gst_paise: int
    total_paise: int

    def components(self) -> dict[str, int]:
        """Every charge line, for a report or a contract-note reconciliation.

        **These do not generally sum to** :attr:`total_paise`, and a reconciliation has to know
        that. Each line is rounded on its own for display; the total is one half-to-even step on
        the EXACT sum, which is what a contract note does and what the goldens are stated in.
        Summing rounded lines drifts, and drifts differently at different notionals.

        The gap is at most a paise or two, and it is real: over 399 notionals sampled from ₹250
        to ₹1,00,000 the lines disagree with the total at 219 of them. At ₹1,00,000 they happen
        to agree, which is why it is easy to believe they always do.
        """
        return {
            "brokerage": self.brokerage_paise,
            "exchange": self.exchange_paise,
            "ipft": self.ipft_paise,
            "sebi": self.sebi_paise,
            "stt": self.stt_paise,
            "stamp": self.stamp_paise,
            "gst": self.gst_paise,
        }

    @property
    def bps(self) -> Decimal:
        """Cost in basis points of notional."""
        return (Decimal(self.total_paise) / Decimal(self.notional_paise) * 10000).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_EVEN
        )


@dataclass(frozen=True)
class RoundTripCost:
    """A buy and its matching sell."""

    buy: OrderCost
    sell: OrderCost

    @property
    def total_paise(self) -> int:
        return self.buy.total_paise + self.sell.total_paise

    @property
    def bps(self) -> Decimal:
        """Round-trip cost in basis points of ONE side's notional.

        One side, not two: the convention §3.7's goldens use (₹35.48 on ₹1,00,000 is
        3.548 bps, not 1.774). Halving it would make every cost hurdle look half as high.
        """
        return (Decimal(self.total_paise) / Decimal(self.buy.notional_paise) * 10000).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_EVEN
        )


def order_cost(
    schedule: CostSchedule,
    broker: Broker,
    side: OrderSide,
    notional_paise: int,
    trade_date: date,
) -> OrderCost:
    """Total statutory + brokerage charge for one order."""
    schedule.require_applies_on(trade_date)
    if broker.value not in schedule.brokers:
        raise LookupError(f"schedule has no brokerage rule for {broker.value}")
    if notional_paise <= 0:
        raise ValueError(f"notional must be positive, got {notional_paise}")

    rates = schedule.statutory
    notional = Decimal(notional_paise)

    brokerage = schedule.brokers[broker.value].brokerage_for(notional_paise)
    exchange = notional * rates.exchange_txn_rate
    ipft = notional * rates.ipft_rate
    sebi = notional * rates.sebi_turnover_rate

    # STT is sell-side only for intraday equity; stamp duty is buy-side only. That asymmetry
    # is why a round trip is not twice a one-way cost, and it is pinned by a test.
    stt = notional * rates.stt_sell_rate if side is OrderSide.SELL else Decimal(0)
    stamp = notional * rates.stamp_buy_rate if side is OrderSide.BUY else Decimal(0)

    # GST applies to the SERVICE component only. STT and stamp duty are taxes; taxing them
    # would be a tax on a tax and would inflate every cost estimate in the funnel.
    gst = (brokerage + exchange + ipft + sebi) * rates.gst_rate

    total = brokerage + exchange + ipft + sebi + stt + stamp + gst
    return OrderCost(
        broker=broker,
        side=side,
        notional_paise=notional_paise,
        brokerage_paise=_to_paise(brokerage),
        exchange_paise=_to_paise(exchange),
        ipft_paise=_to_paise(ipft),
        sebi_paise=_to_paise(sebi),
        stt_paise=_to_paise(stt),
        stamp_paise=_to_paise(stamp),
        gst_paise=_to_paise(gst),
        # Rounded ONCE, from the exact sum — not from the rounded components. Summing
        # rounded parts drifts, and drifts differently at different notionals, which is
        # exactly how a golden starts failing for a reason nobody can name.
        total_paise=_to_paise(total),
    )


def round_trip_cost(
    schedule: CostSchedule, broker: Broker, notional_paise: int, trade_date: date
) -> RoundTripCost:
    """Buy plus sell at the same notional -- the shape §3.7's goldens are stated in."""
    return RoundTripCost(
        buy=order_cost(schedule, broker, OrderSide.BUY, notional_paise, trade_date),
        sell=order_cost(schedule, broker, OrderSide.SELL, notional_paise, trade_date),
    )
