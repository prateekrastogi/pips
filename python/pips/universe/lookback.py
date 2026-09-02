"""M7's liquidity lookback  (§4.1, `[C-UNIV-05]`).

The blueprint's guardrail is two rules in one line: **"Use prior sessions; prefer median/lower
quartile over one-day volume."**

**Prior sessions only.** The window for a session excludes that session, for the reason §4.2
gives outright: *the completed day's volume cannot retrospectively add a stock to that day's
universe.* A window that includes its own session admits names on the strength of what they went
on to trade, and the panel afterwards looks exactly like one selected honestly.

**An incomplete window is refused, not shortened.** A 20-session median computed over three
sessions is not a 20-session median. Silently shortening it admits names on thin evidence at the
start of every panel — which is precisely where a backfill begins, and precisely where nobody
looks.

**Median or lower quartile, never a mean and never the latest day.** One day's spike is what the
guardrail exists to exclude, and a mean carries it straight through. There is deliberately no way
to ask for one.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

__all__ = [
    "SUPPORTED_LOOKBACKS",
    "SUPPORTED_STATISTICS",
    "robust_level",
    "window_for",
]

SUPPORTED_LOOKBACKS: frozenset[int] = frozenset({20, 40, 60})
"""The blueprint's registered liquidity lookbacks. An unregistered one is a policy nobody
declared, chosen after seeing which names it admits."""

SUPPORTED_STATISTICS: frozenset[str] = frozenset({"median", "lower_quartile"})
"""*prefer median/lower quartile over one-day volume*. `mean` is absent on purpose: it carries a
single day's spike straight through, which is the thing the guardrail excludes."""

_QUANTILE = {"median": 0.5, "lower_quartile": 0.25}


def window_for(sessions: Sequence[date], *, session: date, lookback: int) -> tuple[date, ...]:
    """The ``lookback`` sessions immediately BEFORE ``session``.

    Raises rather than returning a short window: the caller asked for a 20-session level and a
    3-session one is a different measurement wearing the same name.
    """
    if lookback not in SUPPORTED_LOOKBACKS:
        raise ValueError(
            f"lookback={lookback} is not one of the registered {sorted(SUPPORTED_LOOKBACKS)}."
        )
    ordered = list(sessions)
    try:
        position = ordered.index(session)
    except ValueError as exc:
        raise LookupError(
            f"{session} is not a session in the supplied series. 'The {lookback} before it' "
            "would otherwise mean the ones before wherever it would have sorted."
        ) from exc

    if position < lookback:
        raise LookupError(
            f"{session} has only {position} prior session(s), fewer than the {lookback} "
            "requested. Refused rather than shortened: a shorter window is a different "
            "measurement under the same name, and it admits names on thin evidence at exactly "
            "the start of a panel."
        )
    return tuple(ordered[position - lookback : position])


def robust_level(values: Sequence[float], *, statistic: str) -> float:
    """A one-day-spike-resistant level for a liquidity series.

    Nearest-rank quantiles: deterministic to the last bit on every machine, with no
    interpolation convention to argue about — the same choice `romano_wolf._quantile` makes.
    """
    if statistic not in SUPPORTED_STATISTICS:
        raise ValueError(
            f"statistic {statistic!r} is not one of {sorted(SUPPORTED_STATISTICS)}. `mean` is "
            "absent on purpose: it carries a single day's spike straight through."
        )
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot take a level of an empty series")
    quantile = _QUANTILE[statistic]
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]
