"""Vectorized screening engine, F0 tier (§6 M10, §3.8).

F0 is deliberately crude — "next-bar return minus conservative rough cost", permitted for
*feature triage only* (§3.8). What must be exact even at F0 is the accounting: §7 asserts
`pnl_gross - costs == pnl_net` continuously, and the §6 Verify is a three-day toy case
reconciled **to the paisa**.

The engine hands each decision an `AsOfPanelView`, so a signal that peeks dies here rather
than in review — the leakage canary's guarantee, made concrete at the place signals run.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from pips.core.asof import AsOfPanelView, CausalityViolationError
from pips.costs.schedule import load_cost_schedule
from pips.costs.statutory import Broker
from pips.sim.vector import (
    FillTier,
    ScreenResult,
    forward_returns,
    long_flat,
    run_screen,
    tolerance_neutral,
    top_k,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEDULE = load_cost_schedule(ROOT / "config" / "costs" / "nse_equity_intraday.yaml")
CAPITAL = 100_000 * 100  # ₹1,00,000 in paise
NS = 1_000_000_000


def toy_panel() -> pl.DataFrame:
    """Two symbols, four daily bars — chosen so every return is exactly ±10%."""
    days = [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 4)]
    rows = []
    for i, day in enumerate(days):
        ts = (i + 1) * 86_400 * NS
        rows.append(
            {
                "close_ts_ns": ts,
                "day": day,
                "symbol": "A",
                "close_paise": [10_000, 11_000, 12_100, 13_310][i],
            }
        )
        rows.append(
            {
                "close_ts_ns": ts,
                "day": day,
                "symbol": "B",
                "close_paise": [10_000, 9_000, 8_100, 7_290][i],
            }
        )
    return pl.DataFrame(rows)


def always_prefer_a(view: AsOfPanelView, symbols: list[str]) -> dict[str, Decimal]:
    """A trivially honest signal: it reads nothing from the future."""
    _ = view.column("close_paise")  # a real read, so the audit is not empty
    return {s: (Decimal(1) if s == "A" else Decimal(-1)) for s in symbols}


# ----------------------------------------------------- portfolio wrappers ---------------


def test_top_k_selects_exactly_k_and_weights_them_equally() -> None:
    scores = {"A": Decimal(3), "B": Decimal(2), "C": Decimal(1)}
    w = top_k(scores, k=2)
    assert sorted(n for n, v in w.items() if v != 0) == ["A", "B"]
    assert w["A"] == w["B"] == Decimal("0.5")


def test_top_k_of_more_than_the_universe_is_refused() -> None:
    with pytest.raises(ValueError, match="k=5"):
        top_k({"A": Decimal(1)}, k=5)


def test_long_flat_never_goes_short() -> None:
    w = long_flat({"A": Decimal(1), "B": Decimal(-1)}, threshold=Decimal(0))
    assert all(v >= 0 for v in w.values())
    assert w["B"] == 0


def test_long_flat_with_nothing_above_the_threshold_holds_nothing() -> None:
    w = long_flat({"A": Decimal(-1)}, threshold=Decimal(0))
    assert sum(w.values(), Decimal(0)) == 0


def test_tolerance_neutral_keeps_net_exposure_inside_the_tolerance() -> None:
    scores = {"A": Decimal(3), "B": Decimal(1), "C": Decimal(-1), "D": Decimal(-3)}
    w = tolerance_neutral(scores, tolerance=Decimal("0.05"))
    assert abs(sum(w.values(), Decimal(0))) <= Decimal("0.05")


def test_tolerance_neutral_is_not_forced_to_exact_neutrality() -> None:
    # §7's anti-voodoo list rejects "exact neutrality regardless of ticket economics".
    # A tolerance band is the point: it permits a small imbalance rather than trading to
    # remove one that costs more than it is worth.
    odd = {"A": Decimal(1), "B": Decimal(-1), "C": Decimal(1)}
    w = tolerance_neutral(odd, tolerance=Decimal("0.2"))
    assert abs(sum(w.values(), Decimal(0))) <= Decimal("0.2")


# ----------------------------------------------------- forward returns ------------------


def test_forward_returns_are_the_next_bar_and_the_last_is_undefined() -> None:
    r = forward_returns(toy_panel(), "A")
    assert r[0] == Decimal("0.1")
    assert r[-1] is None  # no bar after the last one


# ----------------------------------------------------- the toy case ---------------------


def test_three_day_toy_case_reconciles_to_the_paisa() -> None:
    """The §6 M10 Verify, computed by hand.

    ₹1,00,000 long A for three days, flattened each day (pips is intraday, §3.14).
    Each day: gross = 100000_00 paise * 10% = 1,000,000 paise.
    Each day: one round trip at ₹1L on Flattrade = ₹35.48 = 3,548 paise (the §3.7 golden).
    Three days: gross 3,000,000 · cost 10,644 · net 2,989,356 paise (₹29,893.56).
    """
    result = run_screen(
        panel=toy_panel(),
        signal=always_prefer_a,
        wrapper=lambda scores: top_k(scores, k=1),
        capital_paise=CAPITAL,
        schedule=SCHEDULE,
        broker=Broker.FLATTRADE,
    )
    assert result.gross_pnl_paise == 3_000_000
    assert result.cost_paise == 10_644
    assert result.net_pnl_paise == 2_989_356
    assert result.n_round_trips == 3


def test_the_accounting_identity_holds() -> None:
    # §7 asserts this continuously: pnl_gross - costs == pnl_net.
    result = run_screen(
        panel=toy_panel(),
        signal=always_prefer_a,
        wrapper=lambda scores: top_k(scores, k=1),
        capital_paise=CAPITAL,
        schedule=SCHEDULE,
        broker=Broker.FLATTRADE,
    )
    assert result.net_pnl_paise == result.gross_pnl_paise - result.cost_paise
    assert all(
        isinstance(v, int)
        for v in (result.gross_pnl_paise, result.cost_paise, result.net_pnl_paise)
    )


def test_holding_nothing_costs_nothing() -> None:
    result = run_screen(
        panel=toy_panel(),
        signal=lambda view, symbols: dict.fromkeys(symbols, Decimal(-1)),
        wrapper=lambda scores: long_flat(scores, threshold=Decimal(0)),
        capital_paise=CAPITAL,
        schedule=SCHEDULE,
        broker=Broker.FLATTRADE,
    )
    assert result.gross_pnl_paise == 0
    assert result.cost_paise == 0
    assert result.n_round_trips == 0


# ----------------------------------------------------- causality at the engine ----------


def test_a_peeking_signal_dies_inside_the_engine() -> None:
    # The engine hands the signal an AsOfPanelView, so the leakage canary's guarantee holds
    # at the place signals actually run — not merely in a test that calls the guard directly.
    def peeking(view: AsOfPanelView, symbols: list[str]) -> dict[str, Decimal]:
        view.shifted("close_paise", -1)  # tomorrow's close, today
        return dict.fromkeys(symbols, Decimal(1))

    with pytest.raises(CausalityViolationError, match="forward"):
        run_screen(
            panel=toy_panel(),
            signal=peeking,
            wrapper=lambda scores: top_k(scores, k=1),
            capital_paise=CAPITAL,
            schedule=SCHEDULE,
            broker=Broker.FLATTRADE,
        )


# ----------------------------------------------------- tier stamping (§3.8) -------------


def test_every_result_is_stamped_with_its_fill_tier() -> None:
    result = run_screen(
        panel=toy_panel(),
        signal=always_prefer_a,
        wrapper=lambda scores: top_k(scores, k=1),
        capital_paise=CAPITAL,
        schedule=SCHEDULE,
        broker=Broker.FLATTRADE,
    )
    assert result.fill_tier is FillTier.F0


def test_cross_tier_comparison_is_refused() -> None:
    # §3.8: "Every result is stamped with its tier; cross-tier comparisons are refused by
    # report code." An F0 screen number and an F2 certification number are not the same
    # quantity, and comparing them silently is how a triage result becomes a claim.
    a = ScreenResult(FillTier.F0, 1, 1, 0, 1)
    b = ScreenResult(FillTier.F2, 1, 1, 0, 1)
    with pytest.raises(ValueError, match="cross-tier"):
        a.compare_to(b)
    assert a.compare_to(ScreenResult(FillTier.F0, 2, 2, 0, 1)) < 0


def test_f0_declares_what_it_may_be_used_for() -> None:
    # F0 permits feature triage only (§3.8). A tier that cannot say what it permits invites
    # its numbers to be quoted as if they were certification.
    assert "triage" in FillTier.F0.permits.lower()
    assert FillTier.F0.permits != FillTier.F2.permits
