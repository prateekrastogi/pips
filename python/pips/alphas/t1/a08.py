"""A08 -- compression-to-expansion continuation (T1).

The spec states its own trap in the hypothesis: *"The claim is the directional component AFTER
controlling for unconditional volatility clustering — **expansion alone is a volatility
forecast, not an alpha**."* Its declared parent null is "a pure volatility forecast with no
direction", and its first falsifier is "reject if direction adds no information beyond a
volatility forecast".

That trap is easy to fall into and pleasant to be in. Volatility clustering is real, strong and
free — quiet begets quiet, bursts beget bursts — so an alpha scoring raw expansion magnitude
looks like it works, because it is forecasting variance. Variance is predictable and
directionally worthless.

The defence is structural rather than statistical: the score is the signed expansion **divided
by the name's own volatility forecast**, so an identical move means more for a quiet name than
for a loud one. Two names with the same absolute expansion and different volatilities must not
tie, and there is a test that says so.

All three missingness clauses mean *no forecast*, never a zero — and the third is the sharpest:
*"no volatility forecast => no directional claim, since direction is DEFINED relative to it."*
A still name has no denominator, so the question has no answer rather than the answer zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.alphas.t1._common import (
    SessionBars,
    build_forecast,
    sessions_by_symbol,
    stdev,
)
from pips.core.asof import AsOfPanelView

__all__ = ["A08Params", "compute"]


@dataclass(frozen=True)
class A08Params:
    """A point in the spec's bounded domain."""

    compression_window_m: int
    compression_percentile_c0: int
    expansion_threshold_e0_mad: Decimal
    hold_minutes: int
    horizon_ns: int

    def __post_init__(self) -> None:
        if not 10 <= self.compression_window_m <= 120:
            raise ValueError(
                f"compression_window_m {self.compression_window_m} is outside the "
                "pre-registered [10, 120] (§3.2)"
            )
        if not 5 <= self.compression_percentile_c0 <= 30:
            raise ValueError(
                f"compression_percentile_c0 {self.compression_percentile_c0} is outside [5, 30]"
            )
        if not Decimal(1) <= self.expansion_threshold_e0_mad <= Decimal(3):
            raise ValueError(
                f"expansion_threshold_e0_mad {self.expansion_threshold_e0_mad} is outside [1, 3]"
            )
        if not 10 <= self.hold_minutes <= 120:
            raise ValueError(f"hold_minutes {self.hold_minutes} is outside [10, 120]")

    def warmup_bars(self) -> int:
        """120 per the spec's feature DAG, and never fewer than two compression windows."""
        return max(120, self.compression_window_m * 2)


def _returns(closes: list[int]) -> list[Decimal]:
    return [
        Decimal(closes[i] - closes[i - 1]) / Decimal(closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def _percentile_of(value: Decimal, population: list[Decimal]) -> Decimal:
    """Fraction of the population at or below ``value``, as a percentage."""
    if not population:
        return Decimal(0)
    below = sum(1 for p in population if p <= value)
    return Decimal(100) * Decimal(below) / Decimal(len(population))


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def _mad(values: list[Decimal]) -> Decimal:
    """Median absolute deviation. Median-based so one burst cannot define its own normal."""
    if not values:
        return Decimal(0)
    centre = _median(values)
    return _median([abs(v - centre) for v in values])


def _all_bars(sessions: list[SessionBars]) -> tuple[list[int], list[int]]:
    closes: list[int] = []
    volumes: list[int] = []
    for session in sessions:
        closes += session.closes
        volumes += session.volumes
    return closes, volumes


def compute(view: AsOfPanelView, params: A08Params, spec: AlphaSpec) -> list[Forecast]:
    """Volatility-normalised directional expansion after compression. Pure and deterministic."""
    sessions = sessions_by_symbol(view)
    window = params.compression_window_m

    forecasts: list[Forecast] = []
    for symbol in sorted(sessions):
        closes, volumes = _all_bars(sessions[symbol])
        if len(closes) < params.warmup_bars():
            continue  # "insufficient history => no percentile, no state"

        returns = _returns(closes)
        # The trigger bar is the last one; the compression window is what came BEFORE it, so
        # the state that gates the trade is measured without the bar it is gating.
        trigger, history = returns[-1], returns[:-1]

        recent_vol = stdev(history[-window:])
        if recent_vol == 0:
            # "no volatility forecast => no directional claim, since direction is defined
            # relative to it". A still name has no denominator, so the question has no answer
            # — which is not the same answer as zero.
            continue

        prior_vols = [
            stdev(history[i - window : i]) for i in range(window, len(history) - window + 1, 1)
        ]
        prior_vols = [v for v in prior_vols if v > 0]
        if not prior_vols:
            continue

        volume_history = [Decimal(v) for v in volumes[:-1]]
        volume_mad = _mad(volume_history)
        range_mad = _mad([abs(r) for r in history])
        if volume_mad == 0 or range_mad == 0:
            continue  # "no MAD estimate => no trigger"

        compressed = _percentile_of(recent_vol, prior_vols) <= params.compression_percentile_c0
        expanded_range = (
            abs(trigger) - _median([abs(r) for r in history])
        ) >= params.expansion_threshold_e0_mad * range_mad
        expanded_volume = (
            Decimal(volumes[-1]) - _median(volume_history)
        ) >= params.expansion_threshold_e0_mad * volume_mad

        # Normalising by the name's OWN recent volatility is the control the hypothesis
        # demands. Without it an identical move scores identically for a quiet name and a
        # loud one, which is a variance forecast rather than a directional claim.
        score = (
            trigger / recent_vol
            if compressed and expanded_range and expanded_volume
            else Decimal(0)
        )
        forecasts.append(build_forecast(spec, symbol, score, view, params.horizon_ns))
    return forecasts
