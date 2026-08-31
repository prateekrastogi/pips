"""Machinery shared by the T1 plugins.

Extracted so the four momentum/reversal alphas compute their *residuals* the same way. That
matters more than saving lines: A01 claims residual continuation and A03 claims residual
reversal, and if they residualized differently their disagreement would be an artefact of two
implementations rather than a genuine contradiction between two hypotheses.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.core.asof import AsOfPanelView

__all__ = [
    "MIN_UNIVERSE",
    "build_forecast",
    "closes_by_symbol",
    "cross_sectional_residuals",
    "returns_by_symbol",
    "robust_z",
    "stdev",
]

MIN_UNIVERSE = 2

# A residual smaller than this is arithmetic residue, not a price move.
#
# THIS IS NOT A COSMETIC TOLERANCE. Decimal carries 28 significant digits, so for three
# identical names `(r + r + r) / 3` does not return exactly `r` — it leaves ~1e-30 behind. The
# residuals are then all ~1e-30, their sigma is ~1e-30 too, and `residual / sigma` turns pure
# rounding noise into a score of order 1. Three perfectly co-moving names were scoring 3.1
# when the correct answer is 0, and the alpha's own mechanism test is what caught it.
#
# 1e-18 sits ~12 orders above the residue and ~13 orders below the smallest real move
# available (one 5-paise tick on a Rs2,500 stock is 2e-5), so it can only ever remove noise.
RESIDUAL_EPSILON = Decimal("1e-18")


def closes_by_symbol(view: AsOfPanelView) -> dict[str, list[int]]:
    """Visible closes per symbol, in bar order. Records the access for the leakage audit."""
    visible = view.visible()
    view.accessed_fields.add("close_paise")
    return {
        symbol: visible.filter(pl.col("symbol") == symbol)
        .sort("close_ts_ns")["close_paise"]
        .to_list()
        for symbol in sorted(set(visible["symbol"].to_list()))
    }


def returns_by_symbol(closes: dict[str, list[int]]) -> dict[str, list[Decimal]]:
    """Simple per-bar returns. A zero prior close yields no return, never a division."""
    out: dict[str, list[Decimal]] = {}
    for symbol, series in closes.items():
        out[symbol] = [
            Decimal(series[i] - series[i - 1]) / Decimal(series[i - 1])
            for i in range(1, len(series))
            if series[i - 1] != 0
        ]
    return out


def cross_sectional_residuals(returns: dict[str, list[Decimal]]) -> dict[str, list[Decimal]]:
    """Return minus the contemporaneous equal-weighted cross-sectional mean.

    The market leg only. The reference cards residualize against market *and sector*; pips has
    no sector map until M6's PIT masters, and every plugin using this says so rather than
    implying the fuller model.
    """
    symbols = sorted(returns)
    n_bars = min(len(returns[s]) for s in symbols)
    residuals: dict[str, list[Decimal]] = {s: [] for s in symbols}
    for i in range(n_bars):
        cross_section = [returns[s][i] for s in symbols]
        factor = sum(cross_section) / Decimal(len(cross_section))
        for symbol in symbols:
            residual = returns[symbol][i] - factor
            # Below the epsilon there is no dislocation to measure, and pretending otherwise
            # divides one piece of rounding noise by another.
            residuals[symbol].append(Decimal(0) if abs(residual) < RESIDUAL_EPSILON else residual)
    return residuals


def stdev(values: list[Decimal]) -> Decimal:
    """Population standard deviation. Zero when there is no dispersion, never a NaN."""
    if not values:
        return Decimal(0)
    mean = sum(values) / Decimal(len(values))
    variance = sum((v - mean) ** 2 for v in values) / Decimal(len(values))
    if variance <= 0:
        return Decimal(0)
    sigma = variance.sqrt()
    # Same guard, at the point of use: a sigma this small is not dispersion, and every caller
    # divides by it.
    return Decimal(0) if sigma < RESIDUAL_EPSILON else sigma


def robust_z(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Median-centred, MAD-scaled cross-sectional score.

    Median and MAD rather than mean and sigma, so one dislocated name cannot define the scale
    every other name is measured against.
    """
    ordered = sorted(values.values())
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    deviations = sorted(abs(v - median) for v in values.values())
    mad = deviations[n // 2] if n % 2 else (deviations[n // 2 - 1] + deviations[n // 2]) / 2
    if mad == 0:
        return dict.fromkeys(values, Decimal(0))
    return {name: (value - median) / mad for name, value in values.items()}


def build_forecast(
    spec: AlphaSpec, symbol: str, score: Decimal, view: AsOfPanelView, horizon_ns: int
) -> Forecast:
    """Wrap a score as a Forecast, flagged UNCALIBRATED until M15 maps score -> bps.

    Capacity is zero and the validity flag is set on purpose: nothing downstream may mistake
    a ranked score for a calibrated expected return.
    """
    return Forecast(
        strategy_id=spec.strategy_id,
        family_id=spec.id,
        instrument_id=symbol,
        decision_ts=view.decision_ts,
        expected_return_bps=score.quantize(Decimal("0.0001")),
        confidence=Decimal("0.5"),
        horizon_ns=horizon_ns,
        half_life_ns=max(1, horizon_ns // 2),
        valid_until_ns=view.decision_ts + horizon_ns,
        capacity_notional_paise=0,
        validity_flags=["UNCALIBRATED_SCORE"],
    )
