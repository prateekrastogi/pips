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

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pips.core.calendar import load_calendar
from pips.data.breeze.capture import CaptureWriter
from pips.data.breeze.capture_plan import plan_capture
from pips.data.breeze.deadline import arm_timer, until_close
from pips.data.breeze.ws_capture import run_capture

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pips.core.calendar import ExchangeCalendar
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


def main(
    argv: list[str] | None = None,
    *,
    feed_factory: Callable[..., Any] | None = None,
) -> int:
    """CLI: ``pips capture [data_root] --symbols A,B [--now ISO] [--live]``.

    **A bare invocation PLANS. `--live` is what opens a socket.** That inverts `backfill`, whose
    `--dry-run` is opt-in, and the inversion is the point: backfill spends quota, which is
    recoverable tomorrow, while this opens a market-data subscription nobody has authorised.
    "Never create or enable anything on the live path" is not satisfied by a safe mode you have
    to remember to ask for.

    Planning exists so the authorisation decision can be made from something concrete: what
    would be subscribed, over which window, writing where. It opens nothing and creates nothing.

    ``feed_factory`` is injected so the tests can prove both halves -- that planning reaches no
    socket, and that `--live` DOES reach one. Without the second, a `main` that opened nothing
    under any flag would look correct.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="pips capture")
    parser.add_argument("data_root", nargs="?", default=None, help="defaults to $PIPS_DATA_ROOT")
    parser.add_argument("--symbols", required=True, help="comma-separated Breeze stock codes")
    parser.add_argument("--now", default=None, help="ISO instant WITH a timezone; defaults to now")
    parser.add_argument("--calendar", default="config/calendars/nse_equity.yaml")
    parser.add_argument("--live", action="store_true", help="open the socket and capture")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print(
            "capture: no symbols. An empty subscription records an empty archive and reports "
            "success, which cannot be told from a session whose feed was dead.",
            file=sys.stderr,
        )
        return 2

    root = (
        Path(args.data_root)
        if args.data_root
        else Path(os.environ.get("PIPS_DATA_ROOT", "/srv/pips"))
    )
    calendar = load_calendar(Path(args.calendar))
    # A naive `--now` is refused by `plan_capture` and NOT repaired here: attaching a zone of
    # this module's choosing is exactly the guess that makes a UTC container capture the wrong
    # six hours.
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    decision = plan_capture(calendar, now)

    opens = decision.opens_at.strftime("%H:%M") if decision.opens_at else "—"
    closes = decision.closes_at.strftime("%H:%M") if decision.closes_at else "—"
    print(f"capture: {len(symbols)} symbol(s): {', '.join(symbols)}")
    print(f"  session {opens}-{closes} {calendar.timezone} — {decision.reason}")
    print(f"  would write under {root}")
    if decision.late_by_seconds:
        print(f"  starting {decision.late_by_seconds}s late; the missed open is recorded as a GAP")
    if not decision.holidays_verified:
        print("  NOTE: the holiday list is unverified, so a shut exchange and a dead feed")
        print("        produce the same empty file. See `[C-M4-07]`.")

    if not decision.should_run:
        # Before the socket, and before `--live` is even consulted: authorising a subscription
        # is not authorising one at any hour.
        print("  nothing to capture now — planned only, nothing opened.")
        return 0
    if not args.live:
        print("  planned only, nothing opened. Re-run with --live to subscribe.")
        return 0

    factory = feed_factory or _breeze_feeds
    writer = CaptureWriter(root=root, session_id=f"{decision.opens_at:%Y%m%d}-capture")
    report = run_session(
        calendar=calendar,
        now=now,
        feeds=factory(symbols),
        writer=writer,
        symbols=symbols,
    )
    print(f"  {report.reason}: {report.capture.messages if report.capture else 0} message(s)")
    return 0


def _breeze_feeds(symbols: list[str]) -> Iterable[StoppableFeed]:
    """The real thing: successive connections to Breeze, one per reconnect.

    Imported lazily and built here rather than at module scope, so importing this module never
    reaches the vendor SDK or the credentials it reads.
    """
    from breeze_connect import BreezeConnect

    from pips.data.breeze.client import build_session
    from pips.data.breeze.feed import BreezeFeed

    del symbols  # each feed subscribes them itself, via `run_capture`
    while True:
        session: BreezeConnect = build_session()
        yield BreezeFeed(session)
