"""M7's liquidity lookback  (§4.1, `[C-UNIV-05]`).

The blueprint's guardrail is two rules in one line: **"Use prior sessions; prefer median/lower
quartile over one-day volume."**

**Prior sessions only.** The window for a session excludes that session, for the same reason
§4.2 gives: *the completed day's volume cannot retrospectively add a stock to that day's
universe.* A window that includes its own session admits names on the strength of what they went
on to trade.

**An incomplete window is refused, not shortened.** A 20-session median computed over three
sessions is not a 20-session median. Shortening it silently admits names on thin evidence at the
start of every panel — precisely where a backfill begins, and precisely where nobody looks.

**Median or lower quartile, never a mean and never the latest day.** One day's spike is what the
guardrail exists to exclude, and a mean carries that spike straight through.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pips.universe.lookback import (
    SUPPORTED_LOOKBACKS,
    SUPPORTED_STATISTICS,
    robust_level,
    window_for,
)


def sessions(count: int) -> list[date]:
    start = date(2026, 1, 5)
    out: list[date] = []
    day = start
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


# ------------------------------------------------------------------- prior sessions -----


def test_the_window_excludes_its_own_session() -> None:
    """§4.2's rule again: today's volume cannot decide today's membership."""
    days = sessions(30)
    window = window_for(days, session=days[25], lookback=20)

    assert days[25] not in window
    assert window[-1] == days[24], "the window ends the session before"
    assert len(window) == 20


def test_the_window_is_the_sessions_immediately_before() -> None:
    days = sessions(30)
    window = window_for(days, session=days[25], lookback=20)
    assert list(window) == days[5:25]


def test_an_incomplete_window_is_refused() -> None:
    """A 20-session median over three sessions is not a 20-session median, and shortening it
    admits names on thin evidence exactly where a backfill starts."""
    days = sessions(30)
    with pytest.raises(LookupError, match="20"):
        window_for(days, session=days[3], lookback=20)


def test_the_boundary_is_exact() -> None:
    """Position 20 has twenty priors and is allowed; position 19 has nineteen and is not.

    Testing only a clearly-short window (position 3) leaves the boundary free: an off-by-one
    there produces an EMPTY window rather than a short one, which reads as "no liquidity" for
    every name on that session.
    """
    days = sessions(30)
    assert len(window_for(days, session=days[20], lookback=20)) == 20

    with pytest.raises(LookupError, match="19 prior"):
        window_for(days, session=days[19], lookback=20)


def test_a_session_not_in_the_list_is_refused() -> None:
    """A session the caller invented has no position in the series, and 'the twenty before it'
    would silently mean the twenty before wherever it would have sorted."""
    days = sessions(30)
    with pytest.raises(LookupError, match="not a session"):
        window_for(days, session=date(2026, 1, 4), lookback=20)


def test_an_unregistered_lookback_is_refused() -> None:
    days = sessions(30)
    with pytest.raises(ValueError, match="20"):
        window_for(days, session=days[25], lookback=25)
    assert frozenset({20, 40, 60}) == SUPPORTED_LOOKBACKS


# ----------------------------------------------------------- robust, not one-day -----


def test_the_median_ignores_a_single_spike() -> None:
    """The guardrail's whole point: one day's volume must not admit a name."""
    # The spike FIRST, so the series is unsorted. Every fixture here was already in order,
    # which let a mutation dropping the `sorted()` survive: the quantile then indexes whatever
    # position the caller happened to supply.
    quiet = [1_000_000.0, *([1.0] * 19)]
    assert robust_level(quiet, statistic="median") == pytest.approx(1.0)


def test_a_mean_is_not_offered() -> None:
    """Structural. A mean carries the spike straight through, which is what the guardrail
    excludes — so there is no way to ask for one."""
    assert "mean" not in SUPPORTED_STATISTICS
    assert frozenset({"median", "lower_quartile"}) == SUPPORTED_STATISTICS


def test_the_lower_quartile_is_the_more_conservative_reading() -> None:
    values = [float(i) for i in range(1, 21)]
    assert robust_level(values, statistic="lower_quartile") < robust_level(
        values, statistic="median"
    )


def test_quantiles_are_nearest_rank() -> None:
    """Deterministic, and no interpolation convention to argue about — the same choice
    `romano_wolf._quantile` makes, and for the same reason."""
    values = [30.0, 10.0, 40.0, 20.0]  # deliberately unsorted
    assert robust_level(values, statistic="median") == 20.0
    assert robust_level(values, statistic="lower_quartile") == 10.0


def test_an_empty_series_has_no_level() -> None:
    with pytest.raises(ValueError, match="empty"):
        robust_level([], statistic="median")


def test_an_unregistered_statistic_is_refused() -> None:
    with pytest.raises(ValueError, match="median"):
        robust_level([1.0], statistic="p90")
