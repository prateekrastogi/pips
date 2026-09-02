"""Breeze feasibility probe  (§6 M3, §3.5, ADR-0001).

Answers the questions §6 M3 asks about the vendor, as **saved artifacts** rather than as
folklore: the bar-timestamp convention, the true history depth, and the real per-minute rate.

The convention question is the one that can quietly ruin everything downstream. pips labels
bars by CLOSE and treats them as usable at or after the label. If Breeze labels by OPEN and we
ingest without normalizing, every bar becomes usable one interval too early -- a one-bar
lookahead applied uniformly to every backtest, which is the most flattering bug available and
leaves no trace in any result.

**Ported from SAL-0002** (`intraday be8186d:src/volarb/adapters/breeze/history.py`), which
carries a fact worth more than the code around it: *`get_historical_data_v2` treats
`from_date`/`to_date` as IST wall-clock and ignores the trailing `Z`; sending UTC silently
CLIPS the window.* A full NSE session 09:15->15:30 returns 375 one-minute candles.
"""

from __future__ import annotations

from datetime import date, time
from enum import StrEnum
from typing import Any, Final

__all__ = [
    "BREEZE_BAR_LABELLING",
    "BarLabelling",
    "infer_bar_labelling",
    "ist_range",
    "ist_window",
    "session_minutes",
    "summarise_candles",
]


class BarLabelling(StrEnum):
    """Which end of its interval a vendor candle is stamped with."""

    OPEN_LABELLED = "OPEN_LABELLED"
    CLOSE_LABELLED = "CLOSE_LABELLED"
    AMBIGUOUS = "AMBIGUOUS"

    @property
    def intervals_to_add(self) -> int:
        """Intervals to add on ingest so the bar becomes close-labelled [C-BAR-01].

        ``AMBIGUOUS`` raises rather than returning 0. Zero is a decision -- specifically, the
        decision that the vendor is already close-labelled -- and making it by default is how
        an unverified convention becomes a silent lookahead.
        """
        if self is BarLabelling.AMBIGUOUS:
            raise ValueError(
                "bar labelling is ambiguous — no normalization shift can be justified. "
                "Re-probe on a full, unhalted session before ingesting anything (§3.5)."
            )
        return 1 if self is BarLabelling.OPEN_LABELLED else 0


def ist_window(day: date, start: str = "09:15", end: str = "15:30") -> tuple[str, str]:
    """``(from_date, to_date)`` for one NSE session, as IST wall-clock.

    From SAL-0002, verified on live data: Breeze reads these as IST and ignores the trailing
    ``Z``. Passing UTC silently clips the window rather than erroring, so the mistake shows up
    as missing bars rather than as a failure.
    """
    iso = day.isoformat()
    return f"{iso}T{start}:00.000Z", f"{iso}T{end}:00.000Z"


def ist_range(
    start: date, end: date, open_at: str = "09:15", close_at: str = "15:30"
) -> tuple[str, str]:
    """``(from_date, to_date)`` spanning many sessions, as IST wall-clock.

    Same convention as :func:`ist_window` and for the same reason: Breeze reads these as IST and
    ignores the trailing ``Z``, so a UTC window is silently CLIPPED rather than refused.

    **The multi-day span itself is UNVERIFIED.** SAL-0002 established the timestamp convention on
    single-session windows; nobody has asked this vendor for three years in one call. It may clip,
    or cap below the documented 1,000 candles. Only a live probe settles it, and the manifest is
    what makes that probe cheap to repeat.
    """
    return f"{start.isoformat()}T{open_at}:00.000Z", f"{end.isoformat()}T{close_at}:00.000Z"


def session_minutes(session_open: time, session_close: time) -> int:
    """Minutes in the continuous session -- 375 for a full NSE day."""
    return (session_close.hour * 60 + session_close.minute) - (
        session_open.hour * 60 + session_open.minute
    )


def infer_bar_labelling(
    first_bar_label: time,
    session_open: time,
    carries_day_open: bool,
    interval_minutes: int = 1,
) -> BarLabelling:
    """Decide the convention from the label of the bar that carries the day's opening price.

    **Counting candles cannot answer this.** A full NSE session returned 370 candles, not 375,
    because minutes with no trades are omitted rather than zero-filled; other days returned
    376. Endpoints are no better: 15:30 is present on some days and absent on others, so it is
    a traded minute rather than a structural boundary.

    What does decide it is a price identity. The day's opening price belongs to exactly one
    one-minute bar, and that bar's label gives the convention directly. ``carries_day_open``
    is that identity, established by the caller against the daily bar; without it a label
    proves nothing, because a widened window returns pre-open prints too.
    """
    if not carries_day_open:
        return BarLabelling.AMBIGUOUS

    label_minute = first_bar_label.hour * 60 + first_bar_label.minute
    open_minute = session_open.hour * 60 + session_open.minute
    if label_minute == open_minute:
        return BarLabelling.OPEN_LABELLED
    if label_minute == open_minute + interval_minutes:
        return BarLabelling.CLOSE_LABELLED
    return BarLabelling.AMBIGUOUS


# Probed live on 2026-08-28 (RELIND, NSE cash): the day's open 1285.4 matched the 09:15 bar's
# open, and the day's close 1287.0 matched the 15:29 bar's close. Breeze stamps a bar with the
# minute it STARTS. pips labels by close [C-BAR-01], so ingest adds one interval. See
# docs/reports/feasibility/breeze-bar-convention.md and ADR-0001.
BREEZE_BAR_LABELLING: Final = BarLabelling.OPEN_LABELLED


def summarise_candles(payload: dict[str, Any]) -> dict[str, Any]:
    """Endpoints, count and a sample from a ``get_historical_data_v2`` reply.

    Deliberately returns SHAPE, not data: this feeds a committed feasibility artifact, and
    market data belongs on the VM (rule 14), not in the repository.
    """
    rows = payload.get("Success") or payload.get("data") or []
    stamps = [str(r.get("datetime", "")) for r in rows if r.get("datetime")]
    return {
        "count": len(rows),
        "first": stamps[0] if stamps else None,
        "last": stamps[-1] if stamps else None,
        "second": stamps[1] if len(stamps) > 1 else None,
        "fields": sorted(rows[0].keys()) if rows else [],
    }
