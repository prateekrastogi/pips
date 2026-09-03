"""Stopping capture at the close (§6 M4).

The supervisor blocks inside ``feed.messages()``, so nothing inside the loop can notice 15:30
arriving. The deadline has to come from outside it, and the mechanism has two failure modes
that are invisible until the day they matter.

**The supervisor rotates feeds.** ``run_capture`` iterates over successive connections, one per
reconnect, so a timer armed on the first feed stops a feed that a disconnect already replaced.
The deadline is armed per feed, not per session, or a capture that dropped once at 10:00 runs
until the process is killed.

**A timer that is never cancelled outlives its feed.** Ten reconnects leave ten threads waiting
to stop feeds that are already closed, and a pending `threading.Timer` keeps the interpreter
alive after the session ends -- a service that captured correctly and then would not exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pips.data.breeze.deadline import until_close

IST = ZoneInfo("Asia/Kolkata")
OPEN = datetime(2026, 9, 3, 9, 15, tzinfo=IST)
CLOSE = datetime(2026, 9, 3, 15, 30, tzinfo=IST)


@dataclass
class FakeTimer:
    delay: float
    callback: Any
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


@dataclass
class Armory:
    """A timer factory that records what was armed, and never fires on its own."""

    armed: list[FakeTimer] = field(default_factory=list)

    def __call__(self, delay: float, callback: Any) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.armed.append(timer)
        return timer


@dataclass
class FakeFeed:
    name: str
    stopped_with: str | None = None

    def subscribe(self, symbols: list[str]) -> None: ...

    def messages(self) -> Any:
        return iter(())

    def close(self) -> None: ...

    def stop(self, reason: str = "stopped") -> None:
        self.stopped_with = reason


def test_each_feed_is_armed_with_the_time_left_until_the_close() -> None:
    """Per feed, not per session. A timer armed once on the first connection stops a feed a
    disconnect already replaced, and the replacement runs past the close unwatched."""
    feeds = [FakeFeed("a"), FakeFeed("b")]
    armory = Armory()
    at = iter([OPEN, OPEN + timedelta(hours=2)])

    list(until_close(feeds, closes_at=CLOSE, clock=lambda: next(at), timer=armory))

    assert [t.delay for t in armory.armed] == [6.25 * 3600, 4.25 * 3600]


def test_the_timer_stops_the_feed_it_was_armed_for() -> None:
    """And says why: the reason reaches `CaptureStopped`, and from there the session report.
    "feed ended" and "the session closed" are different facts about a day."""
    feed = FakeFeed("a")
    armory = Armory()

    list(until_close([feed], closes_at=CLOSE, clock=lambda: OPEN, timer=armory))
    armory.armed[0].callback()

    assert feed.stopped_with is not None
    assert "closed" in feed.stopped_with
    assert "15:30" in feed.stopped_with


def test_a_feeds_timer_is_cancelled_when_the_supervisor_moves_on() -> None:
    """Ten reconnects must not leave ten armed timers. Each is cancelled as its feed is
    retired -- a real `threading.Timer` left pending also keeps the interpreter alive, so the
    service would capture correctly and then refuse to exit."""
    feeds = [FakeFeed("a"), FakeFeed("b"), FakeFeed("c")]
    armory = Armory()
    at = iter([OPEN, OPEN, OPEN])

    consumed = list(until_close(feeds, closes_at=CLOSE, clock=lambda: next(at), timer=armory))

    assert len(consumed) == 3
    assert [t.cancelled for t in armory.armed] == [True, True, True]


def test_the_timer_is_cancelled_when_the_loop_exits_early() -> None:
    """The supervisor returns as soon as a feed stops cleanly, abandoning the iterator
    mid-stream. The pending timer must go with it rather than surviving the session."""
    feeds = [FakeFeed("a"), FakeFeed("b")]
    armory = Armory()
    stream = until_close(feeds, closes_at=CLOSE, clock=lambda: OPEN, timer=armory)

    next(stream)
    assert armory.armed[0].cancelled is False, "still in use while the supervisor holds it"
    stream.close()

    assert armory.armed[0].cancelled is True


def test_no_feed_is_handed_out_once_the_close_has_passed() -> None:
    """A feed that drops at 15:29:59 must not be replaced at 15:30:01.

    The timer stops a feed the supervisor is already holding; it cannot stop one it has not
    been given yet. Without this the supervisor would reconnect into a shut market, and the
    archive would carry a subscription made after the last trade.
    """
    feeds = [FakeFeed("a"), FakeFeed("b")]
    armory = Armory()
    at = iter([CLOSE - timedelta(seconds=1), CLOSE + timedelta(seconds=1)])

    consumed = list(until_close(feeds, closes_at=CLOSE, clock=lambda: next(at), timer=armory))

    assert consumed == feeds[:1]
    assert len(armory.armed) == 1


def test_the_clock_is_read_once_per_feed() -> None:
    """The decision and the delay come from the same instant.

    Two reads would let the close fall between them and arm a negative delay -- and the fix
    for that would be a clamp defending against a race the loop need not have. One read makes
    the delay consistent with the decision by construction, so the clamp is not merely absent
    but unnecessary.
    """
    reads = 0

    def counting_clock() -> datetime:
        nonlocal reads
        reads += 1
        return OPEN

    list(
        until_close(
            [FakeFeed("a"), FakeFeed("b")],
            closes_at=CLOSE,
            clock=counting_clock,
            timer=Armory(),
        )
    )

    assert reads == 2


def test_the_feeds_pass_through_unchanged() -> None:
    """The deadline wraps the iteration, never the feed: a wrapper object would have to
    reimplement the protocol, and the supervisor would be talking to it rather than the
    vendor."""
    feeds = [FakeFeed("a"), FakeFeed("b")]

    consumed = list(until_close(feeds, closes_at=CLOSE, clock=lambda: OPEN, timer=Armory()))

    assert consumed[0] is feeds[0]
    assert consumed[1] is feeds[1]


def test_a_feed_offered_exactly_at_the_close_is_refused() -> None:
    """The boundary, and it must be the SAME boundary `plan_capture` uses.

    Two places decide whether the session is over -- the one that declines to start and the one
    that declines to reconnect -- and they are a character apart from disagreeing. If this were
    exclusive while `plan_capture` is inclusive, a drop landing exactly on the bell would be
    answered with a subscription to a market the other half of the system had already called
    shut.
    """
    armory = Armory()

    consumed = list(
        until_close([FakeFeed("a")], closes_at=CLOSE, clock=lambda: CLOSE, timer=armory)
    )

    assert consumed == []
    assert armory.armed == []


def test_the_real_timer_cannot_hold_the_process_open() -> None:
    """`threading.Timer` is a non-daemon thread by default, and a pending one keeps the
    interpreter alive: the service would capture the day correctly and then refuse to exit.

    The cancel discipline covers every path this module controls; the daemon flag covers the
    one it does not, which is a cancel that never runs because something above it died. Both
    are needed, and only one of them is visible in the loop.
    """
    from pips.data.breeze.deadline import arm_timer

    armed = arm_timer(3600.0, lambda: None)
    try:
        assert armed.daemon is True  # type: ignore[attr-defined]
    finally:
        armed.cancel()
