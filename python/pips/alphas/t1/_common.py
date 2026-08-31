"""Machinery shared by the T1 plugins.

Extracted so the four momentum/reversal alphas compute their *residuals* the same way. That
matters more than saving lines: A01 claims residual continuation and A03 claims residual
reversal, and if they residualized differently their disagreement would be an artefact of two
implementations rather than a genuine contradiction between two hypotheses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum

import polars as pl

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.core.asof import AsOfPanelView

__all__ = [
    "MIN_UNIVERSE",
    "EventStatus",
    "EventStatusSource",
    "SessionBars",
    "average_true_range",
    "build_forecast",
    "closes_by_symbol",
    "cross_sectional_residuals",
    "require_high_low",
    "returns_by_symbol",
    "robust_z",
    "stdev",
]

MIN_UNIVERSE = 2

# A residual smaller than this is arithmetic residue, not a price move.
#
# THIS IS NOT A COSMETIC TOLERANCE. Decimal carries 28 significant digits, so for three
# identical names `(r + r + r) / 3` does not return exactly `r` — it leaves ~1e-30 behind. The
# residuals are then all ~1e-30, their sigma is ~1e-30 too, and `residual / sigma` turns pure
# rounding noise into a score of order 1. Three perfectly co-moving names were scoring 3.1
# when the correct answer is 0, and the alpha's own mechanism test is what caught it.
#
# 1e-18 sits ~12 orders above the residue and ~13 orders below the smallest real move
# available (one 5-paise tick on a Rs2,500 stock is 2e-5), so it can only ever remove noise.
RESIDUAL_EPSILON = Decimal("1e-18")


def closes_by_symbol(view: AsOfPanelView) -> dict[str, list[int]]:
    """Visible closes per symbol, in bar order. Records the access for the leakage audit."""
    visible = view.visible()
    view.accessed_fields.add("close_paise")
    return {
        symbol: visible.filter(pl.col("symbol") == symbol)
        .sort("close_ts_ns")["close_paise"]
        .to_list()
        for symbol in sorted(set(visible["symbol"].to_list()))
    }


def returns_by_symbol(closes: dict[str, list[int]]) -> dict[str, list[Decimal]]:
    """Simple per-bar returns. A zero prior close yields no return, never a division."""
    out: dict[str, list[Decimal]] = {}
    for symbol, series in closes.items():
        out[symbol] = [
            Decimal(series[i] - series[i - 1]) / Decimal(series[i - 1])
            for i in range(1, len(series))
            if series[i - 1] != 0
        ]
    return out


def cross_sectional_residuals(returns: dict[str, list[Decimal]]) -> dict[str, list[Decimal]]:
    """Return minus the contemporaneous equal-weighted cross-sectional mean.

    The market leg only. The reference cards residualize against market *and sector*; pips has
    no sector map until M6's PIT masters, and every plugin using this says so rather than
    implying the fuller model.
    """
    symbols = sorted(returns)
    n_bars = min(len(returns[s]) for s in symbols)
    residuals: dict[str, list[Decimal]] = {s: [] for s in symbols}
    for i in range(n_bars):
        cross_section = [returns[s][i] for s in symbols]
        factor = sum(cross_section) / Decimal(len(cross_section))
        for symbol in symbols:
            residual = returns[symbol][i] - factor
            # Below the epsilon there is no dislocation to measure, and pretending otherwise
            # divides one piece of rounding noise by another.
            residuals[symbol].append(Decimal(0) if abs(residual) < RESIDUAL_EPSILON else residual)
    return residuals


def stdev(values: list[Decimal]) -> Decimal:
    """Population standard deviation. Zero when there is no dispersion, never a NaN."""
    if not values:
        return Decimal(0)
    mean = sum(values) / Decimal(len(values))
    variance = sum((v - mean) ** 2 for v in values) / Decimal(len(values))
    if variance <= 0:
        return Decimal(0)
    sigma = variance.sqrt()
    # Same guard, at the point of use: a sigma this small is not dispersion, and every caller
    # divides by it.
    return Decimal(0) if sigma < RESIDUAL_EPSILON else sigma


def robust_z(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Median-centred, MAD-scaled cross-sectional score.

    Median and MAD rather than mean and sigma, so one dislocated name cannot define the scale
    every other name is measured against.
    """
    ordered = sorted(values.values())
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    deviations = sorted(abs(v - median) for v in values.values())
    mad = deviations[n // 2] if n % 2 else (deviations[n // 2 - 1] + deviations[n // 2]) / 2
    if mad == 0:
        return dict.fromkeys(values, Decimal(0))
    return {name: (value - median) / mad for name, value in values.items()}


def build_forecast(
    spec: AlphaSpec, symbol: str, score: Decimal, view: AsOfPanelView, horizon_ns: int
) -> Forecast:
    """Wrap a score as a Forecast, flagged UNCALIBRATED until M15 maps score -> bps.

    Capacity is zero and the validity flag is set on purpose: nothing downstream may mistake
    a ranked score for a calibrated expected return.
    """
    return Forecast(
        strategy_id=spec.strategy_id,
        family_id=spec.id,
        instrument_id=symbol,
        decision_ts=view.decision_ts,
        expected_return_bps=score.quantize(Decimal("0.0001")),
        confidence=Decimal("0.5"),
        horizon_ns=horizon_ns,
        half_life_ns=max(1, horizon_ns // 2),
        valid_until_ns=view.decision_ts + horizon_ns,
        capacity_notional_paise=0,
        validity_flags=["UNCALIBRATED_SCORE"],
    )


# ---------------------------------------------------------------- session structure ------

IST = timezone(timedelta(hours=5, minutes=30))


class EventStatus(StrEnum):
    """What we know about corporate events on a name — three states, not two.

    A06's spec makes the distinction mandatory: *missing event metadata => EXCLUDE the name,
    never assume no event.* A boolean cannot carry that. With a two-state flag, an empty
    corporate-action master and a market with no events produce the identical answer, and the
    alpha trades through an unknown as if it were a known quiet.
    """

    CLEAR = "CLEAR"
    """We have coverage for this name and date, and there is no event."""

    FLAGGED = "FLAGGED"
    """We have coverage, and there IS an event. Excluded."""

    UNKNOWN = "UNKNOWN"
    """We have no coverage. Excluded — the conservative direction, and the default."""


EventStatusSource = Callable[[str], EventStatus | None]
"""``symbol -> status``. ``None`` means UNKNOWN, so a plain ``dict.get`` is a valid source."""


@dataclass(frozen=True)
class SessionBars:
    """One symbol's bars for one trading session, in order.

    ``highs``/``lows`` are empty when the panel carries no such columns. That is a
    CONFIGURATION state, not a data gap, and callers that need them say so by calling
    :func:`require_high_low` rather than quietly producing no signal.
    """

    day: object
    closes: list[int]
    volumes: list[int]
    highs: list[int] = field(default_factory=list)
    lows: list[int] = field(default_factory=list)

    @property
    def first_close(self) -> int:
        return self.closes[0]

    @property
    def last_close(self) -> int:
        return self.closes[-1]


def require_high_low(view: AsOfPanelView) -> None:
    """Refuse a panel with no high/low columns, loudly.

    A per-symbol missing ATR is a data gap the specs answer with "no signal". A panel that has
    no high/low columns AT ALL is a different thing: every name silently produces nothing, and
    a disabled alpha reports as a working one that found no opportunities. The two must not
    share a code path.
    """
    missing = [c for c in ("high_paise", "low_paise") if c not in view.frame.columns]
    if missing:
        raise ValueError(
            f"panel has no {', '.join(missing)} column(s), so no true range can be computed. "
            "This is a misconfigured panel, not an absence of signal — every name would "
            "silently produce nothing and the alpha would look like it had simply found no "
            "opportunities."
        )


def average_true_range(session: SessionBars) -> Decimal | None:
    """Mean true range over a completed session, in fractional terms. ``None`` if unmeasurable.

    ``None`` and zero are different answers and the specs treat them differently: A07's
    `volatility_buffer` node says *"no ATR estimate => no buffer, and therefore no signal"*.
    A zero buffer is not the absence of a buffer — it is the widest possible signal.
    """
    if len(session.closes) < 2 or not session.highs or not session.lows:
        return None
    ranges: list[Decimal] = []
    for i in range(1, len(session.closes)):
        prior_close = session.closes[i - 1]
        if prior_close == 0:
            continue
        true_range = max(
            session.highs[i] - session.lows[i],
            abs(session.highs[i] - prior_close),
            abs(session.lows[i] - prior_close),
        )
        ranges.append(Decimal(true_range) / Decimal(prior_close))
    if not ranges:
        return None
    atr = sum(ranges) / Decimal(len(ranges))
    return None if atr <= 0 else atr


def sessions_by_symbol(view: AsOfPanelView) -> dict[str, list[SessionBars]]:
    """Visible bars grouped into sessions by IST date, oldest first.

    The session boundary comes from the bar label's IST date rather than from a gap in the
    timestamps: a halted or thin session can leave minute-scale holes mid-day, and a
    gap-based split would cut a session in two and invent an overnight gap inside it.
    """
    visible = view.visible()
    view.accessed_fields.update({"close_paise", "volume", "close_ts_ns"})
    out: dict[str, list[SessionBars]] = {}
    for symbol in sorted(set(visible["symbol"].to_list())):
        rows = visible.filter(pl.col("symbol") == symbol).sort("close_ts_ns")
        has_hl = {"high_paise", "low_paise"} <= set(rows.columns)
        if has_hl:
            view.accessed_fields.update({"high_paise", "low_paise"})
        highs = rows["high_paise"].to_list() if has_hl else [0] * rows.height
        lows = rows["low_paise"].to_list() if has_hl else [0] * rows.height

        buckets: dict[object, tuple[list[int], list[int], list[int], list[int]]] = {}
        for ts, close, volume, high, low in zip(
            rows["close_ts_ns"].to_list(),
            rows["close_paise"].to_list(),
            rows["volume"].to_list(),
            highs,
            lows,
            strict=True,
        ):
            day = datetime.fromtimestamp(ts / 1e9, IST).date()
            bucket = buckets.setdefault(day, ([], [], [], []))
            bucket[0].append(int(close))
            bucket[1].append(int(volume))
            if has_hl:
                bucket[2].append(int(high))
                bucket[3].append(int(low))
        out[symbol] = [
            SessionBars(day=day, closes=c, volumes=v, highs=h, lows=lo)
            for day, (c, v, h, lo) in sorted(buckets.items())
        ]
    return out


def session_gaps(sessions: dict[str, list[SessionBars]]) -> dict[str, Decimal]:
    """Overnight gap per symbol, measured to the FIRST BAR'S CLOSE — not the opening print.

    A05's first falsifier is *"reject if the result depends on the first untradeable print"*.
    Measuring from the opening print would build the alpha on exactly the number that
    falsifier distrusts: an auction-determined price nobody could transact at. The close of
    the first minute is a price the strategy could actually have traded, so the gap is a
    tradeable one, and the falsifier's stress has much less to remove.

    Symbols without a prior session are ABSENT from the result rather than zero — no prior
    close means no gap measure, which the spec distinguishes from a gap of zero.
    """
    gaps: dict[str, Decimal] = {}
    for symbol, days in sessions.items():
        if len(days) < 2 or days[-2].last_close == 0:
            continue
        prior = Decimal(days[-2].last_close)
        gaps[symbol] = (Decimal(days[-1].first_close) - prior) / prior
    return gaps


def idiosyncratic_gaps(
    gaps: dict[str, Decimal], sessions: dict[str, list[SessionBars]]
) -> dict[str, Decimal]:
    """Gap minus the peer-median gap, scaled by prior-day volatility.

    The peer-median subtraction is the entire "idiosyncratic" claim. Without it a day when
    the whole market gaps up scores every name strongly — which is A05's third falsifier
    ("reject if it is not distinct from market direction") failing by construction.
    """
    if not gaps:
        return {}
    ordered = sorted(gaps.values())
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2

    out: dict[str, Decimal] = {}
    for symbol, gap in gaps.items():
        prior = sessions[symbol][-2]
        sigma = stdev(
            [
                Decimal(prior.closes[i] - prior.closes[i - 1]) / Decimal(prior.closes[i - 1])
                for i in range(1, len(prior.closes))
                if prior.closes[i - 1] != 0
            ]
        )
        if sigma == 0:
            continue  # no prior-day volatility: the spec says no gap measure, not a raw one
        out[symbol] = (gap - median) / sigma
    return out


def opening_volume_ratio(sessions: list[SessionBars]) -> Decimal | None:
    """Mean volume so far today over mean volume per bar yesterday. ``None`` if unmeasurable."""
    today, prior = sessions[-1], sessions[-2]
    if not today.volumes or not prior.volumes:
        return None
    prior_mean = Decimal(sum(prior.volumes)) / Decimal(len(prior.volumes))
    if prior_mean == 0:
        return None
    return (Decimal(sum(today.volumes)) / Decimal(len(today.volumes))) / prior_mean


def peer_breadth(symbol: str, gaps: dict[str, Decimal]) -> Decimal | None:
    """Fraction of PEERS gapping the same way. ``None`` when there are no peers.

    Excludes the name itself: including it puts a floor of 1/n on every breadth reading, so a
    name that no peer confirms still scores above zero purely by counting itself.
    """
    own = gaps[symbol]
    peers = [g for s, g in gaps.items() if s != symbol]
    if not peers:
        return None
    same = sum(1 for g in peers if (g > 0) == (own > 0))
    return Decimal(same) / Decimal(len(peers))


def range_continuation(sessions: list[SessionBars], direction: Decimal, sigma: Decimal) -> Decimal:
    """How far today's move has extended IN THE GAP'S DIRECTION, in prior-day sigmas.

    Negative means the session has retraced against the gap, which is the shape A06's
    weak-confirmation gate is looking for.
    """
    today = sessions[-1]
    if today.first_close == 0 or sigma == 0:
        return Decimal(0)
    move = Decimal(today.last_close - today.first_close) / Decimal(today.first_close)
    sign = Decimal(1) if direction >= 0 else Decimal(-1)
    return sign * move / sigma


def prior_day_sigma(sessions: list[SessionBars]) -> Decimal:
    prior = sessions[-2]
    return stdev(
        [
            Decimal(prior.closes[i] - prior.closes[i - 1]) / Decimal(prior.closes[i - 1])
            for i in range(1, len(prior.closes))
            if prior.closes[i - 1] != 0
        ]
    )
