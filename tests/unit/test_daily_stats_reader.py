"""The reader that turns the daily panel into `DailyStats` — the pre-rank's real population.

`bars_1d.parquet` -> per symbol: median rupee volume, Amihud, gap rate, over a trailing window
of `lookback_sessions` ending at `as_of` INCLUSIVE. Four things it must not do: look past
`as_of` (rule 2), rank a name on a short window as if it were a full one, double-count a
duplicated row, or drop the corporate-action explainer on the floor.
"""

from __future__ import annotations

from datetime import date, timedelta
from math import isnan
from pathlib import Path

import polars as pl
import pytest

from pips.universe.daily_stats import daily_stats_from_panel
from pips.universe.liquidity import amihud_ratio

D0 = date(2026, 6, 1)


def sessions(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def panel(rows: list[tuple[str, date, int, int, int]]) -> pl.DataFrame:
    """`(symbol, trade_date, open_paise, close_paise, volume)` -> the panel as promoted."""
    return pl.DataFrame(
        {
            "trade_date": [r[1] for r in rows],
            "symbol": [r[0] for r in rows],
            "isin": [f"INE{r[0]}" for r in rows],
            "open_paise": [r[2] for r in rows],
            "high_paise": [max(r[2], r[3]) for r in rows],
            "low_paise": [min(r[2], r[3]) for r in rows],
            "close_paise": [r[3] for r in rows],
            "volume": [r[4] for r in rows],
            "received_at_ns": [0] * len(rows),
        }
    )


def flat(
    symbol: str, days: list[date], close: int = 10000, volume: int = 100
) -> list[tuple[str, date, int, int, int]]:
    return [(symbol, d, close, close, volume) for d in days]


def test_median_rupee_volume_is_computed_over_the_window_in_rupees() -> None:
    days = sessions(3)
    rows = [
        ("A", days[0], 10000, 10000, 100),
        ("A", days[1], 20000, 20000, 100),
        ("A", days[2], 30000, 30000, 100),
    ]
    report = daily_stats_from_panel(
        panel(rows), as_of=days[2], lookback_sessions=3, gap_threshold=0.03
    )
    (stat,) = report.stats
    assert stat.symbol == "A"
    assert stat.median_rupee_volume == pytest.approx(20000.0)  # 20000 paise * 100 / 100


def test_amihud_uses_close_to_close_returns_aligned_with_the_later_days_volume() -> None:
    days = sessions(3)
    rows = [
        ("A", days[0], 10000, 10000, 100),
        ("A", days[1], 20000, 20000, 100),
        ("A", days[2], 30000, 30000, 100),
    ]
    report = daily_stats_from_panel(
        panel(rows), as_of=days[2], lookback_sessions=3, gap_threshold=0.03
    )
    (stat,) = report.stats
    assert stat.amihud == pytest.approx(amihud_ratio([1.0, 0.5], [20000.0, 30000.0]))


def test_bars_after_as_of_are_invisible() -> None:
    days = sessions(4)
    rows = [*flat("A", days[:3]), ("A", days[3], 10000, 99999, 10**9)]  # a wild future bar
    report = daily_stats_from_panel(
        panel(rows), as_of=days[2], lookback_sessions=3, gap_threshold=0.03
    )
    (stat,) = report.stats
    # Not the median: a robust statistic cannot see one leaked bar, so it cannot test causality.
    # A flat window has zero gaps and zero Amihud; the leaked bar would make both non-zero.
    assert stat.gap_rate == 0.0
    assert stat.amihud == 0.0
    assert report.as_of == days[2]


def test_only_the_trailing_lookback_sessions_are_used() -> None:
    days = sessions(5)
    rows = [
        ("A", days[0], 10000, 10000, 10**6),
        ("A", days[1], 10000, 10000, 10**6),
        *flat("A", days[2:]),
    ]
    report = daily_stats_from_panel(
        panel(rows), as_of=days[4], lookback_sessions=3, gap_threshold=0.03
    )
    (stat,) = report.stats
    assert stat.median_rupee_volume == pytest.approx(10000.0)  # the two huge early days are outside


def test_a_short_window_is_excluded_with_the_count_not_ranked_as_if_full() -> None:
    days = sessions(5)
    rows = [*flat("FULL", days), *flat("SHORT", days[3:])]
    report = daily_stats_from_panel(
        panel(rows), as_of=days[4], lookback_sessions=5, gap_threshold=0.03
    )
    assert [s.symbol for s in report.stats] == ["FULL"]
    assert "SHORT" in report.excluded
    assert "2" in report.excluded["SHORT"] and "5" in report.excluded["SHORT"]


def test_gap_rate_gets_the_explainer_with_symbol_day_prev_close_and_open() -> None:
    days = sessions(3)
    rows = [
        ("A", days[0], 10000, 10000, 100),
        ("A", days[1], 10500, 10500, 100),
        ("A", days[2], 10500, 10500, 100),
    ]
    calls: list[tuple[str, date, int, int]] = []

    def explain(symbol: str, day: date, prev_close: int, open_paise: int) -> None:
        calls.append((symbol, day, prev_close, open_paise))
        return None

    report = daily_stats_from_panel(
        panel(rows), as_of=days[2], lookback_sessions=3, gap_threshold=0.03, explain=explain
    )
    (stat,) = report.stats
    assert stat.gap_rate == pytest.approx(0.5)  # one 5% gap in two overnight pairs
    assert ("A", days[1], 10000, 10500) in calls


def test_a_duplicated_session_row_is_refused_not_double_counted() -> None:
    days = sessions(3)
    rows = [*flat("A", days), ("A", days[1], 10000, 10000, 100)]
    with pytest.raises(ValueError, match=r"A.*duplicate|duplicate.*A"):
        daily_stats_from_panel(panel(rows), as_of=days[2], lookback_sessions=3, gap_threshold=0.03)


def test_an_empty_panel_yields_no_stats_and_no_crash() -> None:
    report = daily_stats_from_panel(panel([]), as_of=D0, lookback_sessions=3, gap_threshold=0.03)
    assert report.stats == ()
    assert report.excluded == {}


def test_output_is_sorted_by_symbol_regardless_of_panel_order() -> None:
    days = sessions(2)
    rows = [*flat("ZZZ", days), *flat("AAA", days), *flat("MMM", days)]
    report = daily_stats_from_panel(
        panel(rows), as_of=days[1], lookback_sessions=2, gap_threshold=0.03
    )
    assert [s.symbol for s in report.stats] == ["AAA", "MMM", "ZZZ"]


def test_a_parquet_path_reads_the_same_as_the_frame(tmp_path: Path) -> None:
    days = sessions(2)
    frame = panel(flat("A", days))
    path = tmp_path / "bars_1d.parquet"
    frame.write_parquet(path)
    a = daily_stats_from_panel(frame, as_of=days[1], lookback_sessions=2, gap_threshold=0.03)
    b = daily_stats_from_panel(path, as_of=days[1], lookback_sessions=2, gap_threshold=0.03)
    assert a.stats == b.stats


def test_a_name_with_no_usable_overnight_pair_carries_nan_not_zero_gap_rate() -> None:
    days = sessions(1)
    report = daily_stats_from_panel(
        panel(flat("A", days)), as_of=days[0], lookback_sessions=1, gap_threshold=0.03
    )
    (stat,) = report.stats
    assert isnan(stat.gap_rate)


def test_a_non_positive_close_excludes_that_symbol_with_the_reason_not_the_whole_population() -> (
    None
):
    days = sessions(2)
    rows = [
        *flat("GOOD", days),
        ("BAD", days[0], 10000, 10000, 100),
        ("BAD", days[1], 10000, 0, 100),
    ]
    report = daily_stats_from_panel(
        panel(rows), as_of=days[1], lookback_sessions=2, gap_threshold=0.03
    )
    assert [s.symbol for s in report.stats] == ["GOOD"]
    assert "BAD" in report.excluded and "0" in report.excluded["BAD"]


def test_panel_row_order_does_not_matter() -> None:
    days = sessions(4)
    # Two huge days OUTSIDE a two-day window: if the reader trusts row order instead of dates,
    # the unsorted tail is both huge days and the median moves. (One wrong day in three would
    # leave the median untouched -- that version of this test let the mutant live.)
    rows = [*flat("A", days[:2], volume=10**6), *flat("A", days[2:], volume=100)]
    shuffled = [rows[2], rows[3], rows[0], rows[1]]
    report = daily_stats_from_panel(
        panel(shuffled), as_of=days[3], lookback_sessions=2, gap_threshold=0.03
    )
    (stat,) = report.stats
    assert stat.median_rupee_volume == pytest.approx(10000.0)


def test_the_report_carries_each_symbols_isin_because_a_symbol_is_not_an_identity() -> None:
    # arb-vm, 2026-09-05: HDFCBANK resolves to two live instruments -- the equity and
    # "HDFC BANK WARRANT AUG 23" (series W3). Twenty symbols in the master are like that. The
    # panel rows carry the ISIN; the report must hand it on so downstream never resolves a name.
    days = sessions(2)
    report = daily_stats_from_panel(
        panel([*flat("AAA", days), *flat("BBB", days)]),
        as_of=days[1],
        lookback_sessions=2,
        gap_threshold=0.03,
    )
    assert report.isins == {"AAA": "INEAAA", "BBB": "INEBBB"}


def test_a_symbol_held_by_two_isins_in_the_window_is_excluded_with_both_named() -> None:
    days = sessions(2)
    frame = panel([*flat("GOOD", days), *flat("DUAL", days)])
    # DUAL's second session belongs to a different ISIN: a symbol handed over mid-window
    frame = frame.with_columns(
        pl.when((pl.col("symbol") == "DUAL") & (pl.col("trade_date") == days[1]))
        .then(pl.lit("INEOTHER"))
        .otherwise(pl.col("isin"))
        .alias("isin")
    )
    report = daily_stats_from_panel(frame, as_of=days[1], lookback_sessions=2, gap_threshold=0.03)
    assert [s.symbol for s in report.stats] == ["GOOD"]
    assert "INEDUAL" in report.excluded["DUAL"] and "INEOTHER" in report.excluded["DUAL"]
    assert "DUAL" not in report.isins
