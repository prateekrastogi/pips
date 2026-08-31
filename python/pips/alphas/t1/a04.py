"""A04 -- residual mean reversion / factor-neutral dislocation (T1).

The card draws a sharp line and the implementation has to honour it: the estimand is the
**conditional error-correction response of a factor-relative log-price state**, *not* "the
unconditional tendency of a return or price to revisit a moving average".

The difference is testable and it is the whole alpha. A steadily trending name sits above its
own moving average forever, so an MA-reversion implementation shorts it forever. Measured
against a factor-relative state, a name whose peers trend with it is dislocated from nothing
and produces no signal at all.

Entry and exit are a band, not a threshold: a state inside the band is flat, which is a
position, not a missing value.
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
    stdev,
)
from pips.core.asof import AsOfPanelView

__all__ = ["A04Params", "compute"]


@dataclass(frozen=True)
class A04Params:
    z_window: int
    entry_z: Decimal | float
    exit_z: Decimal | float
    horizon_ns: int

    def warmup_bars(self) -> int:
        return self.z_window + 2


def compute(view: AsOfPanelView, params: A04Params, spec: AlphaSpec) -> list[Forecast]:
    """Error-correction response of the factor-relative state. Pure and deterministic."""
    closes = closes_by_symbol(view)
    if len(closes) < MIN_UNIVERSE:
        raise ValueError(f"a cross-section needs at least {MIN_UNIVERSE} names, got {len(closes)}")
    if min(len(s) for s in closes.values()) < params.warmup_bars():
        return []

    residuals = cross_sectional_residuals(returns_by_symbol(closes))
    entry = Decimal(str(params.entry_z))

    forecasts: list[Forecast] = []
    for symbol in sorted(residuals):
        series = residuals[symbol]
        # The factor-relative STATE: cumulative residual over the window, i.e. how far this
        # name has drifted from the manifold, not how far it is from its own average.
        state = sum(series[-params.z_window :])
        sigma = stdev(series[-params.z_window :])
        z = state / sigma if sigma > 0 else Decimal(0)
        # Outside the band, forecast the correction: back toward the manifold, so the sign is
        # opposite the dislocation. Inside it, flat.
        score = -z if abs(z) >= entry else Decimal(0)
        forecasts.append(build_forecast(spec, symbol, score, view, params.horizon_ns))
    return forecasts
