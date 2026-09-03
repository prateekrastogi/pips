"""Whether a capture session should be running now, and what a late start left behind (§6 M4).

The capture service runs in a Debian container whose clock is **UTC**; the session it captures
is 09:15-15:30 **IST**. That six-hour gap is the reason this module exists and is a function
rather than three lines inside a loop. A boundary comparison done in the wrong zone starts
capture at 14:45 IST and stops at 21:00 -- and the archive that results does not look broken,
it looks like a market that was quiet all morning. So the instant is required to carry a
timezone, and the exchange's own zone decides both the clock and the DAY.

A late start is allowed, because refusing one throws away the hours still to come. But it is
reported as a number of seconds, for the same reason `[C-M4-04]` writes a GAP record: an
archive missing 09:15-11:00 with nothing to say so is indistinguishable from a quiet open, and
the open is the part of the day the milestone is for.

Pure: no socket, no vendor, no clock of its own. Everything that can be got wrong quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from datetime import datetime

    from pips.core.calendar import ExchangeCalendar

__all__ = ["CaptureDecision", "plan_capture"]


@dataclass(frozen=True)
class CaptureDecision:
    """Whether to capture, and everything the caller needs to record either way."""

    should_run: bool
    reason: str
    opens_at: datetime | None
    closes_at: datetime | None
    late_by_seconds: int
    holidays_verified: bool
    """Whether the calendar's holiday list has a source and a verification date.

    Carried here because an empty capture day on an UNVERIFIED calendar is *unknown*, not
    quiet: the shipped calendar lists no holidays, so this plans a session on Diwali, the
    socket opens and nothing arrives. Without this flag that zero is identical to a dead feed.
    """


def plan_capture(calendar: ExchangeCalendar, now: datetime) -> CaptureDecision:
    """Decide, for the instant ``now``, whether ``calendar``'s session is open.

    ``now`` must be timezone-aware. A naive datetime is a number that looks like a time, and
    comparing one to 09:15 silently means "09:15 wherever this process happens to run" -- which
    passes every test on a laptop in IST and captures the wrong six hours in a UTC container.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError(
            f"plan_capture needs a timezone-aware instant, got {now!r}. A naive clock would be "
            f"read in whatever zone this process runs in, and the session is {calendar.timezone}."
        )

    local = now.astimezone(ZoneInfo(calendar.timezone))
    # The exchange's day, not the caller's: 22:00 Wednesday in Los Angeles is 10:30 Thursday
    # in Mumbai, and reading the day off the caller's date consults the wrong holiday list.
    day = local.date()
    verified = calendar.holidays_verified

    if not calendar.is_trading_day(day):
        return CaptureDecision(False, f"{day} is not a trading day", None, None, 0, verified)

    opens_at, closes_at = calendar.session_bounds(day)

    if local < opens_at:
        return CaptureDecision(
            False, f"the session opens at {opens_at:%H:%M}", opens_at, closes_at, 0, verified
        )
    if local >= closes_at:
        # Exclusive at the close: an inclusive bound holds the socket open past the last bar,
        # and moving the strictness to the other end would drop the final second of trading.
        return CaptureDecision(
            False, f"the session closed at {closes_at:%H:%M}", opens_at, closes_at, 0, verified
        )

    return CaptureDecision(
        True,
        f"the session is open until {closes_at:%H:%M}",
        opens_at,
        closes_at,
        int((local - opens_at).total_seconds()),
        verified,
    )
