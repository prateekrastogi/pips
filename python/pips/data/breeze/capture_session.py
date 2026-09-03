"""One capture session, composed: decide, record the hole, then capture (§6 M4).

`[C-M4-07]` works out whether the session is open and how late a start is; `[C-M4-04]` knows
how to write a hole into the stream and how to supervise reconnections. Nothing joined them,
which left `late_by_seconds` computed and discarded -- the decision knew the archive was
missing 09:15-11:00 and the archive did not. This module is that join and nothing else.

The two properties pull against each other, and they are the same pair the supervisor already
balances between feeds:

* A **late start** must leave a mark. An archive whose first tick is at 11:00, with nothing to
  say the hour before is missing rather than silent, reports a quiet open that never happened.
* An **on-time start** must not. A zero-length outage at the head of every clean session fills
  the archive with holes that did not occur, and a reader who learns to skip gap records has
  lost the one signal they carry.

A closed market is declined **before the socket**, not after. Subscribing on a holiday spends a
live subscription to produce an empty file, and an empty file cannot be told from a session
whose feed was dead.

Deliberately not here: **stopping at the close.** The supervisor blocks inside
``feed.messages()``, so a deadline has to arrive from outside the loop -- a timer or a signal --
and that mechanism is its own unit with its own failure modes. Starting is decided here;
stopping is not, and saying so is better than a half-built deadline that looks like a whole one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pips.data.breeze.capture_plan import plan_capture
from pips.data.breeze.deadline import arm_timer, until_close
from pips.data.breeze.ws_capture import run_capture

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pips.core.calendar import ExchangeCalendar
    from pips.data.breeze.capture import CaptureWriter
    from pips.data.breeze.deadline import Cancellable, StoppableFeed
    from pips.data.breeze.ws_capture import CaptureReport

__all__ = ["SessionReport", "run_session"]


@dataclass(frozen=True)
class SessionReport:
    """What one session did, including the case where it correctly did nothing."""

    ran: bool
    reason: str
    opening_gap_seconds: int
    symbols_requested: int
    holidays_verified: bool
    capture: CaptureReport | None
    """The supervisor's own account, carried through rather than re-derived.

    Summarising it here would let the two disagree about the same session, and the supervisor's
    is the one with the messages in front of it.
    """


def _to_ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000_000)


def run_session(
    *,
    calendar: ExchangeCalendar,
    now: datetime,
    feeds: Iterable[StoppableFeed],
    writer: CaptureWriter,
    symbols: list[str],
    clock: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], None] = time.sleep,
    timer: Callable[[float, Callable[[], None]], Cancellable] = arm_timer,
    **capture_kwargs: Any,
) -> SessionReport:
    """Capture ``symbols`` for the session containing ``now``, or explain why not.

    ``now`` must be timezone-aware; :func:`plan_capture` refuses a naive clock, because the
    container runs in UTC and the session does not.
    """
    decision = plan_capture(calendar, now)
    if not decision.should_run:
        # Before the socket, not after: nothing is subscribed, nothing is closed, and no file
        # is created. An empty capture file is indistinguishable from a dead feed.
        return SessionReport(
            ran=False,
            reason=decision.reason,
            opening_gap_seconds=0,
            symbols_requested=len(symbols),
            holidays_verified=decision.holidays_verified,
            capture=None,
        )

    if decision.late_by_seconds > 0:
        if decision.opens_at is None:
            # Unreachable today -- `should_run` is only true once the window is known -- and
            # kept as a refusal rather than an `assert`, which `python -O` strips. Skipping the
            # gap instead would be the failure this module exists to prevent, written by the
            # very code that prevents it: a late start with no mark on the archive.
            raise RuntimeError(
                f"the session is open and {decision.late_by_seconds}s late, but its opening "
                f"instant is unknown, so the hole cannot be stated"
            )
        # Written BEFORE the first message, so the archive reads open -> hole -> first tick.
        writer.record_gap(
            _to_ns(decision.opens_at),
            clock(),
            f"capture started {decision.late_by_seconds}s late; the session opened at "
            f"{decision.opens_at:%H:%M} and nothing was recorded until then",
        )

    # `closes_at` is not None for the same reason `opens_at` is not: `should_run` is only true
    # once the window is known. Refused rather than asserted -- see the branch above.
    if decision.closes_at is None:
        raise RuntimeError("the session is open but its closing instant is unknown")

    capture = run_capture(
        feeds=until_close(
            feeds,
            closes_at=decision.closes_at,
            # ONE clock, not two. A wall clock beside the nanosecond clock is two accounts of
            # the same instant, and the day they disagree is the day capture stops at the wrong
            # time while every timestamp it wrote still looks right.
            clock=lambda: datetime.fromtimestamp(clock() / 1_000_000_000, tz=UTC),
            timer=timer,
        ),
        writer=writer,
        symbols=symbols,
        clock=clock,
        sleep=sleep,
        **capture_kwargs,
    )
    return SessionReport(
        ran=True,
        reason=decision.reason,
        opening_gap_seconds=decision.late_by_seconds,
        symbols_requested=len(symbols),
        holidays_verified=decision.holidays_verified,
        capture=capture,
    )
