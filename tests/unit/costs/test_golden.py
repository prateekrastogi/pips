"""Cost goldens [C-COST-01] [C-COST-02] [C-COST-03] (§3.7).

These numbers are the contract. §3.7 pins them at ₹1,00,000/side, fees only, schedules as
verified Aug 2026, and a golden that drifts is a release blocker, not a rounding curiosity —
every downstream claim about whether an edge survives costs rests on them.

If a verified rate change breaks a golden, the fix is: update the YAML, the golden and
`verified_on` **in one commit**, and log a `D-COST-*` decision (§3.7). Never the golden alone.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pips.costs.schedule import load_cost_schedule
from pips.costs.statutory import Broker, OrderSide, order_cost, round_trip_cost

ROOT = Path(__file__).resolve().parents[3]
SCHEDULE = load_cost_schedule(ROOT / "config" / "costs" / "nse_equity_intraday.yaml")
TRADE_DAY = date(2026, 8, 31)
ONE_LAKH = 100_000 * 100  # paise


def rupees(paise: int) -> str:
    return f"{paise // 100}.{paise % 100:02d}"


# ------------------------------------------------------------------ Flattrade ----------


def test_flattrade_1l_buy() -> None:
    cost = order_cost(SCHEDULE, Broker.FLATTRADE, OrderSide.BUY, ONE_LAKH, TRADE_DAY)
    assert rupees(cost.total_paise) == "6.74"


def test_flattrade_1l_sell() -> None:
    cost = order_cost(SCHEDULE, Broker.FLATTRADE, OrderSide.SELL, ONE_LAKH, TRADE_DAY)
    assert rupees(cost.total_paise) == "28.74"


def test_flattrade_1l_rt() -> None:
    """[C-COST-01] — the headline golden: ₹35.48 = 3.548 bps round trip."""
    rt = round_trip_cost(SCHEDULE, Broker.FLATTRADE, ONE_LAKH, TRADE_DAY)
    assert rupees(rt.total_paise) == "35.48"
    assert rt.bps == Decimal("3.548")


# --------------------------------------------------- the high-cost reference line ------


def test_high_cost_line_1l_rt() -> None:
    """[C-COST-02] — retained as a stress line, not a venue (ADR-0010)."""
    rt = round_trip_cost(SCHEDULE, Broker.HIGH_COST_REFERENCE, ONE_LAKH, TRADE_DAY)
    assert rupees(rt.buy.total_paise) == "30.34"
    assert rupees(rt.sell.total_paise) == "52.34"
    assert rupees(rt.total_paise) == "82.68"
    assert rt.bps == Decimal("8.268")


@pytest.mark.parametrize(
    ("notional_rupees", "expected_bps"),
    [(50_000, "10.63"), (200_000, "5.91"), (500_000, "4.49")],
)
def test_high_cost_line_across_capital_tiers(notional_rupees: int, expected_bps: str) -> None:
    # §3.7 pins these three. They are the evidence that the rate set is right rather than
    # merely tuned to one notional: the brokerage cap (0.03% or ₹20, whichever is lower)
    # binds at 50k and not above it, so the three points do not share a formula.
    rt = round_trip_cost(SCHEDULE, Broker.HIGH_COST_REFERENCE, notional_rupees * 100, TRADE_DAY)
    assert str(rt.bps.quantize(Decimal("0.01"))) == expected_bps


def test_the_brokerage_cap_actually_binds_at_the_small_tier() -> None:
    # If this stopped holding, the tier goldens above would still pass by coincidence while
    # the brokerage rule had silently become a flat fee.
    small = order_cost(SCHEDULE, Broker.HIGH_COST_REFERENCE, OrderSide.BUY, 50_000 * 100, TRADE_DAY)
    large = order_cost(
        SCHEDULE, Broker.HIGH_COST_REFERENCE, OrderSide.BUY, 500_000 * 100, TRADE_DAY
    )
    assert small.brokerage_paise == 15_00  # 0.03% of 50k, under the cap
    assert large.brokerage_paise == 20_00  # capped


# ------------------------------------------------------------ structure of the stack ----


def test_the_sell_minus_buy_gap_is_stt_less_stamp() -> None:
    # An invariant, not a number: STT is sell-only and stamp duty is buy-only, so the gap is
    # the same ₹22.00 for every broker at ₹1L. It is how the rate set was derived.
    for broker in (Broker.FLATTRADE, Broker.HIGH_COST_REFERENCE):
        buy = order_cost(SCHEDULE, broker, OrderSide.BUY, ONE_LAKH, TRADE_DAY)
        sell = order_cost(SCHEDULE, broker, OrderSide.SELL, ONE_LAKH, TRADE_DAY)
        assert sell.total_paise - buy.total_paise == 22_00


def test_stt_is_sell_side_only_and_stamp_is_buy_side_only() -> None:
    buy = order_cost(SCHEDULE, Broker.FLATTRADE, OrderSide.BUY, ONE_LAKH, TRADE_DAY)
    sell = order_cost(SCHEDULE, Broker.FLATTRADE, OrderSide.SELL, ONE_LAKH, TRADE_DAY)
    assert buy.stt_paise == 0 and sell.stt_paise == 25_00
    assert sell.stamp_paise == 0 and buy.stamp_paise == 3_00


def test_gst_applies_to_brokerage_and_exchange_fees_but_not_to_stt_or_stamp() -> None:
    # GST is on the *service* component. Applying it to STT or stamp duty would be a tax on
    # a tax and would silently inflate every cost estimate in the funnel.
    cost = order_cost(SCHEDULE, Broker.HIGH_COST_REFERENCE, OrderSide.SELL, ONE_LAKH, TRADE_DAY)
    taxable = cost.brokerage_paise + cost.exchange_paise + cost.ipft_paise + cost.sebi_paise
    assert cost.gst_paise == round(taxable * Decimal("0.18"))


def test_every_component_is_integer_paise() -> None:
    # [C-NUM-01]: no float crosses a schema boundary.
    cost = order_cost(SCHEDULE, Broker.FLATTRADE, OrderSide.SELL, ONE_LAKH, TRADE_DAY)
    for name, value in cost.components().items():
        assert isinstance(value, int), f"{name} is {type(value).__name__}, not int"


# --------------------------------------------- effective dating [C-COST-03] ------------


def test_the_schedule_carries_a_source_and_a_verification_date() -> None:
    assert SCHEDULE.source
    assert SCHEDULE.verified_on == date(2026, 8, 31)


def test_a_trade_date_outside_the_schedule_validity_is_refused() -> None:
    # Costs are effective-dated DATA (rule 6). Silently applying today's rates to a 2023 trade
    # would make every historical backtest quietly wrong in the direction that flatters it.
    with pytest.raises(LookupError, match="no cost schedule"):
        order_cost(SCHEDULE, Broker.FLATTRADE, OrderSide.BUY, ONE_LAKH, date(2023, 1, 1))


def test_costs_scale_linearly_with_notional_once_the_cap_binds() -> None:
    a = round_trip_cost(SCHEDULE, Broker.FLATTRADE, ONE_LAKH, TRADE_DAY)
    b = round_trip_cost(SCHEDULE, Broker.FLATTRADE, 2 * ONE_LAKH, TRADE_DAY)
    assert b.total_paise == 2 * a.total_paise  # Flattrade has no per-order component
