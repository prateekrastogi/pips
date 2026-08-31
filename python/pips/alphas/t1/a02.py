"""A02 -- time-series momentum with volatility scaling (T1).

The claim is continuation in each instrument's **own** return process, not a cross-sectional
one: A02 works on a single name in isolation, and an implementation that needed a
cross-section would be A01 wearing A02's name.

Volatility scaling is not cosmetic. Without it the ranking is dominated by whichever names are
noisiest, which is a volatility sort presented as a momentum alpha.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.alphas.t1._common import build_forecast, closes_by_symbol, returns_by_symbol, stdev
from pips.core.asof import AsOfPanelView

__all__ = ["A02Params", "compute"]


@dataclass(frozen=True)
class A02Params:
    """A point in the spec's bounded domain. Horizons are PREDECLARED, 2-5 of them."""

    lookbacks: tuple[int, ...]
    vol_window: int
    horizon_ns: int

    def __post_init__(self) -> None:
        if len(self.lookbacks) < 2:
            raise ValueError(
                f"A02 needs at least two predeclared lookbacks, got {self.lookbacks} — its "
                "own falsifier is 'reject if only one lookback works', which a "
                "single-lookback configuration cannot even be evaluated against"
            )

    def warmup_bars(self) -> int:
        return max(max(self.lookbacks), self.vol_window) + 1


def compute(view: AsOfPanelView, params: A02Params, spec: AlphaSpec) -> list[Forecast]:
    """Vol-scaled multi-horizon own-return momentum. Pure and deterministic."""
    closes = closes_by_symbol(view)
    if not closes or min(len(s) for s in closes.values()) < params.warmup_bars():
        return []

    returns = returns_by_symbol(closes)
    forecasts: list[Forecast] = []
    for symbol in sorted(returns):
        series = returns[symbol]
        sigma = stdev(series[-params.vol_window :])
        if sigma == 0:
            continue  # no volatility estimate: no scaled claim, and a zero would be one
        # Average the predeclared lookbacks rather than picking the best — picking would be
        # the search the falsifier "reject if only one lookback works" exists to detect.
        signals = [sum(series[-lb:]) / sigma for lb in params.lookbacks]
        score = sum(signals) / Decimal(len(signals))
        forecasts.append(build_forecast(spec, symbol, score, view, params.horizon_ns))
    return forecasts
