"""The permanent leakage canary (§7, constitution rule 2).

Three alphas that cheat, one per mechanical ban. Each is trivially spectacular when given a
raw frame and must be refused outright by :class:`~pips.core.asof.AsOfPanelView`. They exist
to detect a change in *our infrastructure*, not in the market: if a canary ever survives the
production path, a guard has been weakened or routed around.

Kept in the suite forever (§7). Not deleted, not skipped, not marked xfail.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import polars as pl

from pips.core.asof import AsOfPanelView

__all__ = [
    "CANARIES",
    "LeakageCanary",
    "canary_panel",
    "rank_ic",
    "realized_next_return",
]

NS: Final = 1_000_000_000
_BARS: Final = 48
_CENTER: Final = 250_000  # ₹2,500.00
_AMPLITUDE: Final = 20_000
_DECAY: Final = 0.9


def canary_panel() -> pl.DataFrame:
    """A deterministic panel where the future is knowable -- if you are allowed to look.

    The path is an alternating, decaying deviation from a centre:
    ``d_{t+1} = -0.9 * d_t``. That shape is chosen deliberately. Under AR mean reversion the
    next move is a linear function of the current deviation, so *level predicts velocity* and
    a feature that knows the day's centre scores near-perfectly. A sinusoid would not work:
    there level and velocity are 90 degrees out of phase and correlate to zero, which is how
    an earlier draft of this fixture produced a canary that was not spectacular.

    No randomness anywhere. A canary that flickers is a canary nobody trusts.
    """
    closes: list[int] = []
    deviation = float(_AMPLITUDE)
    for _ in range(_BARS):
        closes.append(_CENTER + int(deviation))
        deviation *= -_DECAY

    # The deviations alternate and decay, so the mean of the path is the centre to within a
    # rounding error -- which is exactly what makes the full-day aggregate below a cheat.
    day_vwap = sum(closes) // len(closes)

    # A smoothed state probability P(S_t | F_T): fitted over the WHOLE sample, so it already
    # knows how far each bar sits from where price is going. Graded, not binary -- a binary
    # indicator ties most of its ranks and caps the achievable IC below the threshold.
    forward = [closes[min(i + 1, _BARS - 1)] - c for i, c in enumerate(closes)]
    span = max(forward) - min(forward) or 1
    smoothed = [(f - min(forward)) / span for f in forward]

    return pl.DataFrame(
        {
            "close_ts_ns": [(i + 1) * 60 * NS for i in range(_BARS)],
            "symbol": ["CANARY"] * _BARS,
            "close_paise": closes,
            # Deliberately uninformative: the honest control needs a field that a real alpha
            # could read and still not be spectacular.
            "volume": [1_000 + (i * 37) % 91 for i in range(_BARS)],
            "day_vwap_paise": [day_vwap] * _BARS,
            "smoothed_regime_p": smoothed,
        }
    )


def realized_next_return(frame: pl.DataFrame) -> pl.Series:
    """The target every canary is scored against: next bar's return."""
    close = frame["close_paise"].cast(pl.Float64)
    return (close.shift(-1) / close - 1.0).alias("next_return")


def rank_ic(forecast: pl.Series, target: pl.Series) -> float:
    """Spearman rank IC over the rows where both are defined."""
    joined = pl.DataFrame({"f": forecast, "t": target}).drop_nulls()
    if joined.height < 3:
        return 0.0
    ranked = joined.select(
        pl.col("f").rank().alias("fr"),
        pl.col("t").rank().alias("tr"),
    )
    value = ranked.select(pl.corr("fr", "tr")).item()
    return 0.0 if value is None else float(value)


@dataclass(frozen=True)
class LeakageCanary:
    """One cheating alpha, in both its harnesses."""

    name: str
    ban: str
    expected_refusal: str
    unsafe: Callable[[pl.DataFrame], pl.Series]
    production: Callable[[AsOfPanelView], pl.Series]


def _lookahead_unsafe(frame: pl.DataFrame) -> pl.Series:
    # The classic: shift(-1). It *is* the target, so the IC is 1 by construction.
    return realized_next_return(frame)


def _lookahead_production(view: AsOfPanelView) -> pl.Series:
    return view.shifted("close_paise", -1)


def _full_day_unsafe(frame: pl.DataFrame) -> pl.Series:
    # Distance to the day's VWAP. Knowing the full-day average tells you which way price
    # must travel to reach it, which is a forecast of the rest of the day.
    close = frame["close_paise"].cast(pl.Float64)
    return (frame["day_vwap_paise"].cast(pl.Float64) - close).alias("to_vwap")


def _full_day_production(view: AsOfPanelView) -> pl.Series:
    return view.column("day_vwap_paise")


def _smoothed_unsafe(frame: pl.DataFrame) -> pl.Series:
    return frame["smoothed_regime_p"].cast(pl.Float64)


def _smoothed_production(view: AsOfPanelView) -> pl.Series:
    return view.column("smoothed_regime_p")


CANARIES: Final[tuple[LeakageCanary, ...]] = (
    LeakageCanary(
        name="next_bar_return",
        ban="lookahead",
        expected_refusal="forward in time",
        unsafe=_lookahead_unsafe,
        production=_lookahead_production,
    ),
    LeakageCanary(
        name="distance_to_day_vwap",
        ban="full-day",
        expected_refusal="full-day",
        unsafe=_full_day_unsafe,
        production=_full_day_production,
    ),
    LeakageCanary(
        name="smoothed_regime",
        ban="smoothed-state",
        expected_refusal="smoothed",
        unsafe=_smoothed_unsafe,
        production=_smoothed_production,
    ),
)
