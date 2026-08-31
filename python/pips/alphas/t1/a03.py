"""A03 -- cross-sectional short-horizon reversal (T1).

Temporary inventory and liquidity shocks may reverse once urgent flow is absorbed. Two things
the card insists on, and both are enforced here:

* the claim is about an **extreme** residual move, so A03 is gated on a tail. Without the gate
  it becomes an always-on contrarian, which is a different (and much weaker) claim;
* the direction is the **negation** of A01's. A01 says residual moves continue and A03 says
  they revert. On the same data the two must disagree in sign, and they share
  ``_common.cross_sectional_residuals`` precisely so that disagreement is between hypotheses
  rather than between two implementations of "residual".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.alphas.t1._common import (
    MIN_UNIVERSE,
    build_forecast,
    closes_by_symbol,
    cross_sectional_residuals,
    returns_by_symbol,
    robust_z,
    stdev,
)
from pips.core.asof import AsOfPanelView

__all__ = ["A03Params", "compute"]


@dataclass(frozen=True)
class A03Params:
    shock_window: int
    tail: Decimal | float
    horizon_ns: int

    def warmup_bars(self) -> int:
        return self.shock_window * 4 + 1


def compute(view: AsOfPanelView, params: A03Params, spec: AlphaSpec) -> list[Forecast]:
    """Negated residual shock, fired only on a tail. Pure and deterministic."""
    closes = closes_by_symbol(view)
    if len(closes) < MIN_UNIVERSE:
        raise ValueError(f"a cross-section needs at least {MIN_UNIVERSE} names, got {len(closes)}")
    if min(len(s) for s in closes.values()) < params.warmup_bars():
        return []

    residuals = cross_sectional_residuals(returns_by_symbol(closes))
    tail = Decimal(str(params.tail))

    raw: dict[str, Decimal] = {}
    for symbol, series in residuals.items():
        shock = sum(series[-params.shock_window :])
        sigma = stdev(series)
        raw[symbol] = shock / sigma if sigma > 0 else Decimal(0)

    scores = robust_z(raw)
    return [
        build_forecast(
            spec,
            symbol,
            # NEGATED: the reversal claim. And gated -- a name inside the tail is not a
            # liquidity shock, so A03 has nothing to say about it and says nothing.
            -score if abs(score) >= tail else Decimal(0),
            view,
            params.horizon_ns,
        )
        for symbol, score in sorted(scores.items())
    ]
