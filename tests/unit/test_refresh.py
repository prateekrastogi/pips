"""M7's universe refresh cadence  (§4.1, `[C-UNIV-03]`).

The blueprint's guardrail is one line: **"Membership fixed for each session."** A universe that
changes mid-session is not a universe; it is a decision made after seeing part of the day.

So membership for a session comes from a refresh that happened **at or before** it, and a
session earlier than the first refresh has **no** membership — refused, not filled in with the
first refresh's list. Using a later refresh's members for an earlier session is lookahead
wearing the costume of a default, and it is invisible afterwards: the panel simply contains
names that were not eligible yet.

**Refreshes are computed over the SESSION list, never over calendar dates.** A weekly refresh is
the first *session* of each week, so a Monday holiday moves it to Tuesday by construction.
Deriving it from dates would place a refresh on a day the exchange was shut — and the project's
own calendar still carries `holidays_verified: false`, so the session list is the caller's to
supply and to have verified (`require_verified_holidays()`).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pips.universe.refresh import (
    SUPPORTED_CADENCES,
    governing_refresh,
    refresh_sessions,
)


def weekdays(start: date, count: int, skip: set[date] | None = None) -> list[date]:
    """Consecutive weekday sessions, minus any the exchange was shut."""
    out: list[date] = []
    day = start
    while len(out) < count:
        if day.weekday() < 5 and (skip is None or day not in skip):
            out.append(day)
        day += timedelta(days=1)
    return out


# ----------------------------------------------------------------- cadence over sessions -----


def test_weekly_takes_the_first_session_of_each_week() -> None:
    sessions = weekdays(date(2026, 1, 5), 15)  # three full weeks from a Monday
    picks = refresh_sessions(sessions, cadence="weekly")
    assert picks == (date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19))


def test_a_holiday_moves_the_refresh_to_the_next_session() -> None:
    """The reason this takes sessions and not dates.

    With Monday shut, the week's first SESSION is Tuesday. A date-based rule would schedule the
    refresh on a day with no data and either fail or silently reuse last week's membership.
    """
    shut = {date(2026, 1, 12)}
    sessions = weekdays(date(2026, 1, 5), 14, skip=shut)
    picks = refresh_sessions(sessions, cadence="weekly")

    assert date(2026, 1, 12) not in picks
    assert date(2026, 1, 13) in picks


def test_monthly_takes_the_first_session_of_each_month() -> None:
    sessions = weekdays(date(2026, 1, 28), 25)
    picks = refresh_sessions(sessions, cadence="monthly")
    assert picks[0] == date(2026, 1, 28), "the first session available begins the first month"
    assert date(2026, 2, 2) in picks, "February's first weekday session"


def test_daily_refreshes_every_session() -> None:
    """*daily as stress* — the policy that carries no stability at all, kept so the others can
    be compared against it."""
    sessions = weekdays(date(2026, 1, 5), 7)
    assert refresh_sessions(sessions, cadence="daily") == tuple(sessions)


def test_an_unregistered_cadence_is_refused() -> None:
    with pytest.raises(ValueError, match="weekly"):
        refresh_sessions(weekdays(date(2026, 1, 5), 5), cadence="fortnightly")
    assert frozenset({"weekly", "monthly", "daily"}) == SUPPORTED_CADENCES


def test_no_sessions_yields_no_refreshes() -> None:
    assert refresh_sessions([], cadence="weekly") == ()


def test_sessions_must_be_ordered() -> None:
    """An out-of-order list means the caller's session source is wrong, and "first session of
    the week" would name whichever row happened to come first."""
    jumbled = [date(2026, 1, 6), date(2026, 1, 5)]
    with pytest.raises(ValueError, match="order"):
        refresh_sessions(jumbled, cadence="weekly")


# --------------------------------------------------- membership is fixed for a session -----


def test_the_governing_refresh_is_the_latest_at_or_before() -> None:
    refreshes = (date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19))
    assert governing_refresh(date(2026, 1, 15), refreshes) == date(2026, 1, 12)


def test_a_session_on_a_refresh_day_uses_that_refresh() -> None:
    """The refresh is computed from prior sessions and applied at the open, so the day it lands
    on is governed by it — not by the one before."""
    refreshes = (date(2026, 1, 5), date(2026, 1, 12))
    assert governing_refresh(date(2026, 1, 12), refreshes) == date(2026, 1, 12)


def test_a_session_before_the_first_refresh_has_no_membership() -> None:
    """Refused, never defaulted. Falling back to the first refresh applies a membership decided
    LATER to an earlier session, which is lookahead that leaves no trace in the panel.
    """
    refreshes = (date(2026, 1, 12), date(2026, 1, 19))
    with pytest.raises(LookupError, match="before the first refresh"):
        governing_refresh(date(2026, 1, 5), refreshes)


def test_no_refreshes_at_all_is_refused() -> None:
    with pytest.raises(LookupError):
        governing_refresh(date(2026, 1, 5), ())


def test_the_same_iso_week_in_two_years_is_two_buckets() -> None:
    """Week 2 of 2026 and week 2 of 2027 are different weeks.

    The fixture must span MORE THAN A YEAR or the week numbers never repeat and bucketing on
    the number alone passes: my first attempt ran late-December into January, where the buckets
    are 53, 1, 2 — all distinct. Fourteen months make week 2 occur twice, and a year-less
    bucket then silently gives the second one no refresh.
    """
    sessions = weekdays(date(2026, 1, 5), 300)  # ~60 weeks
    picks = refresh_sessions(sessions, cadence="weekly")

    weeks_spanned = len({s.isocalendar()[:2] for s in sessions})
    assert weeks_spanned > 53, "the fixture must outlast one ISO year"
    assert len(picks) == weeks_spanned


def test_the_same_month_in_two_years_is_two_buckets() -> None:
    """Fourteen months, so January occurs twice."""
    sessions = weekdays(date(2026, 1, 5), 300)
    picks = refresh_sessions(sessions, cadence="monthly")

    months_spanned = len({(s.year, s.month) for s in sessions})
    assert months_spanned > 12, "the fixture must outlast one calendar year"
    assert len(picks) == months_spanned


def test_a_repeated_session_is_refused() -> None:
    """The same day listed twice means the caller's session source is wrong. Accepting it would
    count one session as two and put a refresh on the duplicate."""
    doubled = [date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 6)]
    with pytest.raises(ValueError, match="order"):
        refresh_sessions(doubled, cadence="weekly")
