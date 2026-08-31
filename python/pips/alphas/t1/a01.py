"""A01 -- cross-sectional residual momentum (T1)  [C-SPEC-01] [C-FCST-01].

The pre-registration is ``config/search_spaces/A01_residual_momentum.yaml``; this is its
``compute`` plugin, which §3.2 requires to be **pure, deterministic and warm-up-declared**.

The claim is *idiosyncratic* continuation after removing contemporaneously estimable common
moves -- not winner-chasing. So the common move is projected out first, and a name that moved
exactly with the cross-section produces no signal at all. That property is what distinguishes
this from ranking raw returns, and it is tested directly.

**Scope, stated rather than implied.** The reference's A01 card removes market *and sector*
moves via rolling WLS on a factor set. pips has no sector map until M6's PIT masters, so the
factor here is the equal-weighted cross-sectional mean return -- the market leg only. That is
a faithful first implementation of the same estimand, not the whole card, and the sector leg
lands with the masters. The spec's own falsifier "reject if performance disappears after
sector neutralization" is precisely the test this implementation cannot yet run.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

import polars as pl

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.core.asof import AsOfPanelView

__all__ = ["A01Params", "compute"]

_MIN_UNIVERSE = 2


@dataclass(frozen=True)
class A01Params:
    """A point in the spec's bounded parameter domain."""

    residual_lookback: int
    scale_window: int
    horizon_ns: int

    def warmup_bars(self) -> int:
        """Declared warm-up: below this there is no forecast, not a zero (§3.2)."""
        return max(self.residual_lookback, self.scale_window) + 1


def _robust_z(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Cross-sectional robust z: median-centred, MAD-scaled.

    Median and MAD rather than mean and sigma because a single dislocated name should not
    define the scale every other name is measured against.
    """
    ordered = sorted(values.values())
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    deviations = sorted(abs(v - median) for v in values.values())
    mad = deviations[n // 2] if n % 2 else (deviations[n // 2 - 1] + deviations[n // 2]) / 2
    if mad == 0:
        # No cross-sectional dispersion: every name is at the median, so nothing is ranked
        # above anything. Zero is the correct score here, not an artefact.
        return dict.fromkeys(values, Decimal(0))
    return {name: (value - median) / mad for name, value in values.items()}


def compute(view: AsOfPanelView, params: A01Params, spec: AlphaSpec) -> list[Forecast]:
    """Forecasts for every eligible name at ``view.decision_ts``. Pure and deterministic."""
    visible = view.visible()
    symbols = sorted(set(visible["symbol"].to_list()))
    if len(symbols) < _MIN_UNIVERSE:
        raise ValueError(
            f"a cross-section needs at least {_MIN_UNIVERSE} names, got {len(symbols)} — "
            "a cross-sectional score over one name is not a cross-section"
        )

    view.accessed_fields.add("close_paise")
    closes: dict[str, list[int]] = {}
    for symbol in symbols:
        series = (
            visible.filter(pl.col("symbol") == symbol).sort("close_ts_ns")["close_paise"].to_list()
        )
        closes[symbol] = series

    if min(len(s) for s in closes.values()) < params.warmup_bars():
        return []  # declared warm-up not met: silence, not a zero

    # Per-bar simple returns, then the contemporaneous common move projected out.
    returns: dict[str, list[Decimal]] = {
        symbol: [
            Decimal(series[i] - series[i - 1]) / Decimal(series[i - 1])
            for i in range(1, len(series))
        ]
        for symbol, series in closes.items()
    }
    n_bars = min(len(r) for r in returns.values())
    residuals: dict[str, list[Decimal]] = {s: [] for s in symbols}
    for i in range(n_bars):
        cross_section = [returns[s][i] for s in symbols]
        factor = sum(cross_section) / Decimal(len(cross_section))
        for symbol in symbols:
            residuals[symbol].append(returns[symbol][i] - factor)

    raw: dict[str, Decimal] = {}
    for symbol in symbols:
        window = residuals[symbol][-params.residual_lookback :]
        scale_window = residuals[symbol][-params.scale_window :]
        momentum = sum(window)
        mean = sum(scale_window) / Decimal(len(scale_window))
        variance = sum((x - mean) ** 2 for x in scale_window) / Decimal(len(scale_window))
        sigma = variance.sqrt() if variance > 0 else Decimal(0)
        raw[symbol] = momentum / sigma if sigma > 0 else Decimal(0)

    scores = _robust_z(raw)
    half_life = params.horizon_ns // 2
    return [
        Forecast(
            strategy_id=spec.strategy_id,
            family_id=spec.id,
            instrument_id=symbol,
            decision_ts=view.decision_ts,
            # A score is not a return. Until the calibration in M15 maps score -> bps, the
            # forecast reports the score scaled to bps and its capacity is left minimal, so
            # nothing downstream can mistake it for a calibrated expectation.
            expected_return_bps=score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN),
            confidence=Decimal("0.5"),
            horizon_ns=params.horizon_ns,
            half_life_ns=half_life,
            valid_until_ns=view.decision_ts + params.horizon_ns,
            capacity_notional_paise=0,
            validity_flags=["UNCALIBRATED_SCORE"],
        )
        for symbol, score in sorted(scores.items())
    ]
