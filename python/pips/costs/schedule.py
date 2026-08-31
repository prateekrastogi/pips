"""Effective-dated cost schedules  [C-COST-03] (§3.7, constitution rule 6).

A fee schedule is data with a source, a verification date and a validity window. Applying one
outside its window is refused rather than silently tolerated: using today's rates for a 2023
trade would make every historical backtest wrong in the direction that flatters it, and it
would do so invisibly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from pips.core.config import DecimalFromStr, PipsConfig, load_yaml

__all__ = ["BrokerSchedule", "CostSchedule", "StatutoryRates", "load_cost_schedule"]


class StatutoryRates(PipsConfig):
    """Rates that apply to every broker: they are the state's, not the venue's."""

    stt_sell_rate: DecimalFromStr
    exchange_txn_rate: DecimalFromStr
    ipft_rate: DecimalFromStr
    sebi_turnover_rate: DecimalFromStr
    stamp_buy_rate: DecimalFromStr
    gst_rate: DecimalFromStr


class BrokerSchedule(PipsConfig):
    """One broker's brokerage rule: a rate, optionally capped per order."""

    brokerage_rate: DecimalFromStr
    brokerage_cap_paise: int

    def brokerage_for(self, notional_paise: int) -> Decimal:
        """Brokerage in paise. A zero cap means *no cap*, not *no brokerage*."""
        charged = Decimal(notional_paise) * self.brokerage_rate
        if self.brokerage_cap_paise > 0:
            return min(charged, Decimal(self.brokerage_cap_paise))
        return charged


class CostSchedule(PipsConfig):
    """A dated fee schedule for one market x segment x product."""

    schema_version: int
    market: str
    segment: str
    product: str
    source: str
    verified_on: date
    valid_from: date
    valid_to: date | None
    statutory: StatutoryRates
    brokers: dict[str, BrokerSchedule]

    def applies_on(self, trade_date: date) -> bool:
        if trade_date < self.valid_from:
            return False
        return self.valid_to is None or trade_date <= self.valid_to

    def require_applies_on(self, trade_date: date) -> None:
        """Refuse a trade date this schedule does not cover."""
        if not self.applies_on(trade_date):
            window = f"{self.valid_from} to {self.valid_to or 'in force'}"
            raise LookupError(
                f"no cost schedule covers {trade_date} for {self.market}/{self.segment}/"
                f"{self.product} — this one is valid {window}. Costs are effective-dated "
                "data (rule 6); applying the wrong window silently flatters the backtest."
            )


def load_cost_schedule(path: Path) -> CostSchedule:
    """Load and validate a cost schedule from YAML."""
    return CostSchedule.model_validate(load_yaml(path))
