"""When a capture session should be running, and what a late start leaves behind (§6 M4).

The capture service will run in a Debian container, whose clock is **UTC**. The session it is
capturing is 09:15-15:30 **IST**. Every property here exists because that gap is six hours
wide and silent: a comparison done in the wrong zone starts capture at 14:45 IST and stops it
at 21:00, and the archive that results looks like a market that was quiet all morning.

The second theme is the same one the GAP record exists for. A service that restarts at 11:00
should capture the rest of the day rather than refuse -- but the missing 09:15-11:00 has to be
*stated*, or the archive silently lacks the open, which is the part of the day the whole
milestone is for.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pips.core.calendar import load_calendar
from pips.data.breeze.capture_plan import plan_capture

ROOT = Path(__file__).resolve().parents[2]
CAL = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")
IST = ZoneInfo("Asia/Kolkata")

# 2026-09-03 is a Thursday. 09:15 IST is 03:45 UTC.
OPEN = datetime(2026, 9, 3, 9, 15, tzinfo=IST)
CLOSE = datetime(2026, 9, 3, 15, 30, tzinfo=IST)


def test_a_clock_without_a_timezone_is_refused() -> None:
    """The whole point. A naive datetime is a number that LOOKS like a time, and comparing one
    to 09:15 silently means "09:15 wherever this process happens to be running" -- UTC in the
    container, IST on the developer's laptop. The bug would pass every local test and capture
    the wrong six hours in production.
    """
    with pytest.raises(ValueError, match="timezone"):
        plan_capture(CAL, datetime(2026, 9, 3, 9, 30))


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kolkata", "Australia/Sydney"])
def test_the_same_instant_decides_the_same_way_in_every_zone(zone: str) -> None:
    """One instant, four spellings, one answer.

    A fixture written only in IST cannot tell a correct conversion from no conversion at all --
    the same defect as testing a session boundary on a machine that happens to be in IST. Los
    Angeles is in the list because it is on the previous DATE at this hour, so a comparison
    that reads the local date rather than the exchange's gets a different trading day too.
    """
    instant = OPEN + timedelta(hours=2)
    decision = plan_capture(CAL, instant.astimezone(ZoneInfo(zone)))

    assert decision.should_run is True
    assert decision.late_by_seconds == 7200


def test_capture_starts_at_the_open_with_no_hole_behind_it() -> None:
    decision = plan_capture(CAL, OPEN)

    assert decision.should_run is True
    assert decision.late_by_seconds == 0
    assert decision.opens_at == OPEN
    assert decision.closes_at == CLOSE


def test_a_late_start_states_the_hole_it_leaves() -> None:
    """A restart at 11:00 should capture the rest of the day -- refusing would throw away four
    good hours. But the missing 09:15-11:00 must be a number the caller can record, or the
    archive lacks the open and nothing says why.
    """
    decision = plan_capture(CAL, datetime(2026, 9, 3, 11, 0, tzinfo=IST))

    assert decision.should_run is True
    assert decision.late_by_seconds == 105 * 60


def test_before_the_open_capture_does_not_run() -> None:
    decision = plan_capture(CAL, OPEN - timedelta(seconds=1))

    assert decision.should_run is False
    assert "opens" in decision.reason
    assert decision.late_by_seconds == 0, "a hole is only meaningful once the session is open"


def test_the_last_second_of_the_session_is_still_captured() -> None:
    assert plan_capture(CAL, CLOSE - timedelta(seconds=1)).should_run is True


def test_the_close_itself_ends_the_session() -> None:
    """The boundary, stated explicitly because an inclusive one keeps the socket open past the
    close and an exclusive one at the wrong end drops the final second of trading."""
    decision = plan_capture(CAL, CLOSE)

    assert decision.should_run is False
    assert "closed" in decision.reason


def test_a_weekend_is_not_a_session() -> None:
    """2026-09-05 is a Saturday. Opening a socket would record an empty day, which reads as an
    outage rather than as a market that was shut."""
    decision = plan_capture(CAL, datetime(2026, 9, 5, 11, 0, tzinfo=IST))

    assert decision.should_run is False
    assert "not a trading day" in decision.reason


def test_a_listed_holiday_is_not_a_session() -> None:
    calendar = CAL.model_copy(update={"holidays": [date(2026, 9, 3)]})
    decision = plan_capture(calendar, datetime(2026, 9, 3, 11, 0, tzinfo=IST))

    assert decision.should_run is False
    assert "not a trading day" in decision.reason


def test_the_decision_says_whether_the_holiday_list_was_verified() -> None:
    """An empty day on an UNVERIFIED calendar is unknown, not quiet.

    The shipped calendar has no holidays and says so (`holidays_verified` false), so on Diwali
    this plan plans a session, the socket opens and nothing arrives. Carrying the verification
    flag onto the decision is what lets the record distinguish "the exchange was shut" from
    "the feed was dead" -- without it, the two are the same zero.
    """
    assert plan_capture(CAL, OPEN).holidays_verified is False

    verified = CAL.model_copy(
        update={"holidays_source": "NSE circular", "holidays_verified_on": date(2026, 1, 1)}
    )
    assert plan_capture(verified, OPEN).holidays_verified is True


def test_the_window_comes_from_the_calendar_and_is_not_hardcoded() -> None:
    """A muhurat session runs 18:15-19:15. A hardcoded 09:15 would capture nothing that day and
    record a session that never opened."""
    muhurat = CAL.model_copy(
        update={
            "continuous_session": CAL.continuous_session.model_copy(
                update={"start": "18:15:00", "end": "19:15:00"}
            )
        }
    )
    at_seven = datetime(2026, 9, 3, 19, 0, tzinfo=IST)

    assert plan_capture(muhurat, at_seven).should_run is True
    assert plan_capture(CAL, at_seven).should_run is False
    assert plan_capture(muhurat, OPEN).should_run is False


def test_the_day_is_the_exchange_s_day_not_the_caller_s() -> None:
    """22:00 in Los Angeles on Wednesday is 10:30 IST on Thursday -- a live session.

    Reading the trading day off the caller's calendar date would consult the wrong day's
    holiday list, and on the day either side of a holiday that is the difference between
    capturing a session and capturing nothing.
    """
    in_la = datetime(2026, 9, 2, 22, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert in_la.astimezone(UTC).astimezone(IST).date() == date(2026, 9, 3)

    decision = plan_capture(CAL, in_la)
    assert decision.should_run is True
    assert decision.opens_at == OPEN


class _NoOffset(tzinfo):
    """A tzinfo that supplies no offset -- Python's own definition of a NAIVE datetime is
    ``tzinfo is None or tzinfo.utcoffset(d) is None``, and the second half is reachable."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "NOWHERE"

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None


def test_a_clock_that_is_aware_in_name_only_is_refused() -> None:
    """`tzinfo is not None` is not the test for awareness.

    A tzinfo whose `utcoffset` returns None makes a datetime that LOOKS aware and behaves as
    naive: `astimezone()` on it raises "cannot be applied to a naive datetime" from six frames
    down. Catching it here turns an obscure crash inside the session loop into the sentence
    that names the problem.
    """
    with pytest.raises(ValueError, match="timezone"):
        plan_capture(CAL, datetime(2026, 9, 3, 9, 30, tzinfo=_NoOffset()))


def test_the_decision_is_made_in_the_exchange_s_zone_and_not_in_utc() -> None:
    """Reading the clock in UTC agrees with the exchange's zone for NSE -- and only by luck.

    Both sides of every comparison are timezone-aware, so the comparison itself is on absolute
    instants and the display zone cannot change it. The zone is read exactly once that matters:
    `local.date()`, which picks the trading day. NSE's 09:15-15:30 IST never crosses a UTC date
    boundary, so for THIS calendar the two agree everywhere -- which is why a sweep of the
    shipped hours cannot tell them apart.

    A session inside 00:00-05:29 IST is the window where it becomes observable, because those
    instants fall on the PREVIOUS UTC date. It is not a session NSE will ever run; it is the
    case that distinguishes "correct" from "correct by coincidence", and the coincidence is a
    property of the current calendar values rather than of the code.
    """
    overnight = CAL.model_copy(
        update={
            "continuous_session": CAL.continuous_session.model_copy(
                update={"start": "02:00:00", "end": "04:00:00"}
            )
        }
    )
    at_three_ist = datetime(2026, 9, 3, 3, 0, tzinfo=IST)
    assert at_three_ist.astimezone(UTC).date() == date(2026, 9, 2), "the premise of the test"

    decision = plan_capture(overnight, at_three_ist)

    assert decision.should_run is True
    assert decision.opens_at == datetime(2026, 9, 3, 2, 0, tzinfo=IST)
