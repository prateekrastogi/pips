"""The Forecast contract  [C-FCST-01] (§3.3).

Every alpha emits the same economics, independent of order logic. That is what lets the
portfolio layer compare A01 against A12 at all: without a common unit, "which alpha is better"
has no answer that is not an argument about implementations.

The trade gate is deliberately two-termed. ``|mu| > stressed_cost + kappa * SE(mu)`` refuses a
forecast that clears the cost but sits inside its own estimation error -- trading on an edge
smaller than the uncertainty in the edge is trading on noise, and it is the failure that looks
most like success in a backtest.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from pips.core.config import DecimalFromNumber, PipsConfig

__all__ = ["Forecast", "tradeable"]


class Forecast(PipsConfig):
    """One alpha's view on one instrument at one decision time (§3.3)."""

    strategy_id: str
    family_id: str
    instrument_id: str
    decision_ts: int
    expected_return_bps: DecimalFromNumber
    confidence: DecimalFromNumber
    horizon_ns: int
    half_life_ns: int
    valid_until_ns: int
    capacity_notional_paise: int
    validity_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherent_in_time(self) -> Forecast:
        if self.valid_until_ns <= self.decision_ts:
            raise ValueError(
                f"valid_until_ns {self.valid_until_ns} is not after decision_ts "
                f"{self.decision_ts} — a forecast that expires before it is made cannot be acted on"
            )
        if self.horizon_ns <= 0:
            raise ValueError(f"horizon must be positive, got {self.horizon_ns}")
        if self.half_life_ns <= 0:
            raise ValueError(f"half_life must be positive, got {self.half_life_ns}")
        if not (0 <= self.confidence <= 1):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        return self

    @property
    def is_valid(self) -> bool:
        """Whether this forecast is usable at all. Any flag disqualifies it."""
        return not self.validity_flags


def tradeable(
    forecast: Forecast,
    stressed_cost_bps: Decimal,
    kappa: Decimal,
    se_bps: Decimal,
) -> bool:
    """§3.3's gate: trade only where ``|mu| > stressed marginal cost + kappa * SE(mu)``.

    Symmetric in sign -- a -12bps short is as tradeable as a +12bps long. A flagged forecast
    is never tradeable regardless of the numbers, because a flag is the forecast saying "do
    not use me" without the caller having to infer it.
    """
    if not forecast.is_valid:
        return False
    hurdle = stressed_cost_bps + kappa * se_bps
    return abs(forecast.expected_return_bps) > hurdle
