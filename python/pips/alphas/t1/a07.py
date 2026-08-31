"""A07 -- opening-range breakout (T1).

The claim: an opening range aggregates overnight information, and a LATER escape from it,
accompanied by abnormal participation, indicates unresolved directional demand.

Every interesting decision here is the same one — **a missing input is not a default one** —
and the spec names all three:

``opening_range``
    *"session shorter than the endpoint => no range, no forecast."*

``volatility_buffer``
    *"no ATR estimate => no buffer, and therefore no signal."* This is the one that invites a
    quiet mistake. A zero buffer is not the absence of a buffer; it is the WIDEST possible
    signal, firing on every marginal touch of the raw range. Falling back to it would answer
    the alpha's own falsifier — *"reject if small changes to range_end or buffer reverse the
    result"* — by construction, in the flattering direction.

``breakout_flag``
    *"a breach on the same bar as the range endpoint is not a breach."* The causality guard,
    and its falsifier says what it is for: *"reject if most P&L comes from same-bar fills"*. A
    bar that both closes the range and breaks it means deciding on a price simultaneously used
    to define the threshold.

``range_end_minutes`` is one of four PREDECLARED values, per the fit protocol. Accepting an
arbitrary integer would turn a four-point grid into a continuous search over exactly the
parameter the first falsifier distrusts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.alphas.t1._common import (
    SessionBars,
    average_true_range,
    build_forecast,
    require_high_low,
    sessions_by_symbol,
)
from pips.core.asof import AsOfPanelView

__all__ = ["A07Params", "compute"]

RANGE_END_CHOICES: Final = (5, 10, 15, 30)


@dataclass(frozen=True)
class A07Params:
    """A point in the spec's bounded domain."""

    range_end_minutes: int
    buffer_atr: Decimal
    hold_minutes: int
    min_participation: Decimal
    horizon_ns: int

    def __post_init__(self) -> None:
        if self.range_end_minutes not in RANGE_END_CHOICES:
            raise ValueError(
                f"range_end_minutes {self.range_end_minutes} is not one of the four "
                f"predeclared values {RANGE_END_CHOICES} (§3.2 fit protocol). An arbitrary "
                "endpoint turns a four-point grid into a continuous search over the very "
                "parameter A07's first falsifier distrusts."
            )
        if not Decimal(0) <= self.buffer_atr <= Decimal(1):
            raise ValueError(
                f"buffer_atr {self.buffer_atr} is outside the pre-registered [0.0, 1.0]"
            )
        if not 15 <= self.hold_minutes <= 120:
            raise ValueError(f"hold_minutes {self.hold_minutes} is outside [15, 120]")


def _range_of(session: SessionBars, bars: int) -> tuple[int, int] | None:
    """High/low over the first ``bars`` bars, or ``None`` if the session is too short.

    Too short means "not strictly longer than the endpoint": a session of exactly ``bars``
    has a range and no bar after it, so there is nothing that could be a breach.
    """
    if len(session.closes) <= bars or not session.highs:
        return None
    return max(session.highs[:bars]), min(session.lows[:bars])


def compute(view: AsOfPanelView, params: A07Params, spec: AlphaSpec) -> list[Forecast]:
    """Buffered opening-range breakout with a participation gate. Pure and deterministic."""
    require_high_low(view)
    sessions = sessions_by_symbol(view)

    forecasts: list[Forecast] = []
    for symbol in sorted(sessions):
        days = sessions[symbol]
        if len(days) < 2:
            continue
        today, prior = days[-1], days[-2]

        atr = average_true_range(prior)
        if atr is None:
            continue  # "no ATR estimate => no buffer, and therefore no signal"

        bounds = _range_of(today, params.range_end_minutes)
        if bounds is None:
            continue  # "session shorter than the endpoint => no range, no forecast"
        high, low = bounds

        # The decision bar is the last VISIBLE bar. It is strictly after the endpoint by the
        # check above, which is what makes this not a same-bar decision.
        close = Decimal(today.last_close)
        buffer_paise = params.buffer_atr * atr * Decimal(high)
        upper, lower = Decimal(high) + buffer_paise, Decimal(low) - buffer_paise

        prior_mean_volume = Decimal(sum(prior.volumes)) / Decimal(len(prior.volumes))
        participation = (
            Decimal(today.volumes[-1]) / prior_mean_volume if prior_mean_volume > 0 else Decimal(0)
        )
        confirmed = participation >= params.min_participation

        breach = Decimal(0)
        if confirmed and close > upper:
            breach = (close - upper) / (Decimal(high) * atr)
        elif confirmed and close < lower:
            breach = (close - lower) / (Decimal(high) * atr)
        forecasts.append(build_forecast(spec, symbol, breach, view, params.horizon_ns))
    return forecasts
