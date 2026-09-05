"""The daily panel -> `DailyStats`: the pre-rank's real population.

`promote_daily` writes `bars_1d.parquet`; this reads it back and, per symbol, computes the three
spread-free liquidity inputs over a trailing window of `lookback_sessions` ending at `as_of`
INCLUSIVE. It is the last step between the seed and an actual 500.

Four things it refuses to do quietly:

* look past `as_of` -- rows dated after it are filtered before anything is computed (rule 2);
* rank a name on a short window as if it were a full one -- fewer than `lookback_sessions`
  visible sessions is an exclusion WITH the count, not a smaller sample;
* double-count a duplicated `(symbol, trade_date)` row -- that is a panel-integrity failure and
  raises, because a duplicated day doubles a volume and halves a return;
* compute on a non-positive close -- `median_rupee_volume` refuses it, and the refusal becomes
  that symbol's exclusion reason rather than the whole population's crash.

The corporate-action explainer is passed straight through to `gap_rate`; this module has no
opinion about what a verdict means.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path

import polars as pl

from pips.core.money import PAISE_PER_RUPEE
from pips.data.pit.explain import JumpExplainer
from pips.universe.liquidity import amihud_ratio, gap_rate, median_rupee_volume
from pips.universe.prerank import DailyStats


@dataclass(frozen=True)
class DailyStatsReport:
    """What the reader produced, and what it left out and why."""

    stats: tuple[DailyStats, ...]
    excluded: Mapping[str, str]
    as_of: date
    lookback_sessions: int


def daily_stats_from_panel(
    panel: Path | pl.DataFrame,
    *,
    as_of: date,
    lookback_sessions: int,
    gap_threshold: float,
    explain: JumpExplainer | None = None,
) -> DailyStatsReport:
    """Per-symbol `DailyStats` over the trailing `lookback_sessions` ending at `as_of`."""
    if lookback_sessions < 1:
        raise ValueError(f"lookback_sessions must be >= 1, got {lookback_sessions}")
    frame = pl.read_parquet(panel) if isinstance(panel, Path) else panel
    # Date order is what `tail` needs; symbol order is imposed once, on the way out.
    visible = frame.filter(pl.col("trade_date") <= as_of).sort("trade_date")
    dupes = visible.group_by(["symbol", "trade_date"]).len().filter(pl.col("len") > 1)
    if dupes.height:
        where = ", ".join(
            f"{row['symbol']} on {row['trade_date']}"
            for row in dupes.sort("symbol").iter_rows(named=True)
        )
        raise ValueError(f"duplicate session rows in the daily panel: {where}")

    stats: list[DailyStats] = []
    excluded: dict[str, str] = {}
    for key, rows in visible.group_by(["symbol"], maintain_order=True):
        symbol = str(key[0])
        window = rows.tail(lookback_sessions)
        if window.height < lookback_sessions:
            excluded[symbol] = (
                f"{window.height} of {lookback_sessions} sessions visible at {as_of.isoformat()}"
            )
            continue
        days: list[date] = window["trade_date"].to_list()
        opens: list[int] = window["open_paise"].to_list()
        closes: list[int] = window["close_paise"].to_list()
        volumes: list[int] = window["volume"].to_list()
        try:
            median = median_rupee_volume(list(zip(closes, volumes, strict=True)))
        except ValueError as error:
            excluded[symbol] = str(error)
            continue
        rupee_volume = [c * v / PAISE_PER_RUPEE for c, v in zip(closes, volumes, strict=True)]
        returns = [c / p - 1.0 for p, c in pairwise(closes)]
        stats.append(
            DailyStats(
                symbol=symbol,
                median_rupee_volume=median,
                amihud=amihud_ratio(returns, rupee_volume[1:]),
                gap_rate=gap_rate(
                    list(zip(days, opens, closes, strict=True)),
                    threshold=gap_threshold,
                    explain=explain,
                    symbol=symbol,
                ),
            )
        )
    stats.sort(key=lambda s: s.symbol)
    return DailyStatsReport(tuple(stats), excluded, as_of, lookback_sessions)
