"""Stopping capture at the close (§6 M4).

`[C-M4-04]`'s supervisor blocks inside ``feed.messages()``, so nothing inside the loop can
notice 15:30 arriving. The deadline has to come from outside it, which makes this a timer --
and a timer has two failure modes that stay invisible until the day they matter.

**The supervisor rotates feeds.** ``run_capture`` iterates over successive connections, one per
reconnect, so a timer armed once on the first feed stops a connection that a disconnect already
replaced. A capture that dropped at 10:00 would then run until the process was killed. The
deadline is therefore armed **per feed**.

**A timer that is never cancelled outlives its feed.** Ten reconnects leave ten threads waiting
to stop feeds that are already closed, and a pending ``threading.Timer`` is non-daemon by
default -- the interpreter will not exit while one is outstanding, so the service would capture
the day correctly and then refuse to stop. Each timer is cancelled as its feed is retired, on
every exit path including the supervisor abandoning the iterator mid-stream.

This wraps the ITERATION, never the feed. A wrapper object would have to reimplement the whole
protocol, and the supervisor would then be talking to it instead of to the vendor.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from pips.data.breeze.ws_capture import Feed

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable
    from datetime import datetime

__all__ = ["Cancellable", "StoppableFeed", "arm_timer", "until_close"]


class Cancellable(Protocol):
    """What arming a timer returns."""

    def cancel(self) -> None: ...


class StoppableFeed(Feed, Protocol):
    """A feed that can be asked to end cleanly from another thread.

    Narrower than what the supervisor needs and wider than what it knows about: `Feed` has no
    `stop` because nothing inside the loop ever calls one. The deadline is outside the loop.
    """

    def stop(self, reason: str = ...) -> None: ...


def arm_timer(delay: float, callback: Callable[[], None]) -> Cancellable:
    """A real timer, started, and daemonised so a missed cancel cannot hold the process open."""
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


def until_close(
    feeds: Iterable[StoppableFeed],
    *,
    closes_at: datetime,
    clock: Callable[[], datetime],
    timer: Callable[[float, Callable[[], None]], Cancellable] = arm_timer,
) -> Generator[StoppableFeed, None, None]:
    """Yield ``feeds`` until the close, each armed to stop itself when the session ends.

    A generator rather than a plain iterator, deliberately: the supervisor returns as soon as a
    feed stops cleanly, abandoning this mid-stream, and it is ``close()`` on the generator that
    runs the ``finally`` and cancels the timer still armed for the feed it was holding.

    ``clock`` returns a timezone-aware instant in any zone: both operands are aware, so the
    comparison is on absolute instants.
    """
    for feed in feeds:
        # ONE read, used for both the decision and the delay. Reading it twice would let the
        # close fall between them and arm a negative delay -- and clamping that to zero would
        # be defending against a race this loop need not have.
        now = clock()
        if now >= closes_at:
            # A feed that drops at 15:29:59 must not be replaced at 15:30:01. The timer can
            # stop a feed the supervisor is already holding; it cannot stop one that has not
            # been handed over, so the refusal to hand it over is the only guard here.
            return

        armed = timer(
            (closes_at - now).total_seconds(),
            lambda feed=feed: feed.stop(  # type: ignore[misc]
                f"the session closed at {closes_at:%H:%M}"
            ),
        )
        try:
            yield feed
        finally:
            # Every exit path: the supervisor moving on, returning early on a clean stop, or
            # the generator being closed when it abandons the iterator mid-stream.
            armed.cancel()
