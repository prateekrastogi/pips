"""Backfill campaign planning (§6 M4).

The planning half is pure and tested here; only the session and the HTTP call are not.

The property worth guarding is that a campaign **states its cost before spending it**. A
backfill that starts fetching and finds out later how many calls it needed can exhaust a
day's quota on a range nobody meant to request — and the mistake is a typo away, since a
date range is two strings.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.data.breeze.campaign import CampaignPlan, plan_campaign

ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "config" / "calendars" / "nse_equity.yaml"


def test_weekends_are_excluded_from_the_plan() -> None:
    # 2026-06-05 is a Friday, 06/07 the weekend, 08 the Monday.
    plan = plan_campaign(["RELIND"], date(2026, 6, 5), date(2026, 6, 8), CALENDAR)
    assert plan.days == [date(2026, 6, 5), date(2026, 6, 8)]


def test_the_call_count_is_symbols_times_days() -> None:
    plan = plan_campaign(["A", "B", "C"], date(2026, 6, 1), date(2026, 6, 5), CALENDAR)
    assert plan.days == [date(2026, 6, d) for d in (1, 2, 3, 4, 5)]
    assert plan.estimated_calls == 15


def test_an_inverted_range_is_refused() -> None:
    with pytest.raises(ValueError, match="before"):
        plan_campaign(["A"], date(2026, 6, 10), date(2026, 6, 1), CALENDAR)


def test_an_empty_symbol_list_is_refused() -> None:
    with pytest.raises(ValueError, match="symbol"):
        plan_campaign([], date(2026, 6, 1), date(2026, 6, 5), CALENDAR)


def test_a_range_with_no_trading_days_is_refused() -> None:
    # A weekend-only range is almost certainly a mistake, and silently doing nothing would
    # look like a completed campaign.
    with pytest.raises(ValueError, match="no trading days"):
        plan_campaign(["A"], date(2026, 6, 6), date(2026, 6, 7), CALENDAR)


def test_the_plan_warns_when_it_exceeds_the_daily_budget() -> None:
    # Stating the cost before spending it. A three-year U300 campaign is ~85k calls, which
    # fits one day's budget (ADR-0012) — but a wider request must say so rather than
    # discovering it at call 90,000.
    plan = plan_campaign(
        [f"S{i}" for i in range(500)], date(2020, 1, 1), date(2026, 1, 1), CALENDAR
    )
    assert plan.estimated_calls > 100_000
    assert plan.exceeds_budget(daily_budget=90_000)
    assert not plan.exceeds_budget(daily_budget=10_000_000)


def test_the_plan_is_reportable_before_anything_is_fetched() -> None:
    plan = plan_campaign(["A", "B"], date(2026, 6, 1), date(2026, 6, 3), CALENDAR)
    summary = plan.describe()
    assert "2 symbols" in summary and "3 trading days" in summary and "6" in summary
    assert isinstance(plan, CampaignPlan)
