"""The supervisor around the capture writer  (§6 M4, `[C-M4-04]`).

`CaptureWriter` knows how to record a message and how to record a hole. Nothing drove it: no CLI
command, no Make target, no compose service, so "forward WS capture from day one" had no day
one — and unlike a backfill, a session that passes uncaptured is spread and depth that cannot be
fetched later at any price. This is the loop that would run it.

Two properties carry the weight, and they pull in opposite directions:

**A disconnect must leave a mark.** A supervisor that reconnects quietly produces an archive
whose gaps are invisible, which is the whole failure the GAP record exists to prevent.

**A deliberate stop must NOT.** Recording a gap at every clean shutdown fills the archive with
outages that never happened, and a reader who learns to ignore gap records has lost the one
signal that matters.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pips.data.breeze.capture import CaptureWriter, MessageKind
from pips.data.breeze.ws_capture import CaptureStopped, run_capture

TICK = {"symbol": "RELIND", "ltp": 1285.4}


class FakeFeed:
    """Yields scripted messages, then either ends or drops."""

    def __init__(self, script: list[object], name: str = "feed") -> None:
        self.script = script
        self.name = name
        self.subscribed: list[str] = []
        self.closed = False

    def subscribe(self, symbols: list[str]) -> None:
        self.subscribed.extend(symbols)

    def messages(self) -> Iterator[tuple[MessageKind, object]]:
        for item in self.script:
            if isinstance(item, Exception):
                raise item
            yield MessageKind.TICK, item

    def close(self) -> None:
        self.closed = True


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000_000
        self.slept: list[float] = []

    def __call__(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += int(seconds * 1_000_000_000)


def _writer(tmp_path: Path) -> CaptureWriter:
    return CaptureWriter(tmp_path / "cap", "s1")


def _records(writer: CaptureWriter) -> list[dict[str, Any]]:
    import json

    return [json.loads(line) for line in writer.path.read_text().splitlines() if line.strip()]


def test_every_message_reaches_the_writer(tmp_path: Path) -> None:
    feeds = [FakeFeed([TICK, TICK, TICK])]
    writer = _writer(tmp_path)
    report = run_capture(
        feeds=iter(feeds), writer=writer, symbols=["RELIND"], clock=Clock(), sleep=lambda _s: None
    )
    assert report.messages == 3
    assert feeds[0].subscribed == ["RELIND"]
    assert [r["kind"] for r in _records(writer)] == ["TICK"] * 3


def test_a_disconnect_writes_a_gap_and_the_capture_resumes(tmp_path: Path) -> None:
    """The hole is in the stream, where a reader of the stream will find it."""
    clock = Clock()
    feeds = [FakeFeed([TICK, ConnectionError("socket closed")]), FakeFeed([TICK, TICK])]
    writer = _writer(tmp_path)

    report = run_capture(
        feeds=iter(feeds), writer=writer, symbols=["RELIND"], clock=clock, sleep=clock.sleep
    )

    assert report.messages == 3
    assert report.gaps == 1
    kinds = [r["kind"] for r in _records(writer)]
    assert kinds == ["TICK", "GAP", "TICK", "TICK"], kinds
    gap = next(r for r in _records(writer) if r["kind"] == "GAP")
    assert gap["messages_missed"] is None
    assert int(gap["reconnected_at_ns"]) > int(gap["disconnected_at_ns"])
    assert "socket closed" in str(gap["reason"])
    assert writer.outage_ns > 0


def test_sequence_numbers_never_repeat_across_a_reconnect(tmp_path: Path) -> None:
    """The gap record takes a sequence number of its own, so the stream stays orderable."""
    clock = Clock()
    feeds = [FakeFeed([TICK, ConnectionError("drop")]), FakeFeed([TICK])]
    writer = _writer(tmp_path)
    run_capture(feeds=iter(feeds), writer=writer, symbols=["A"], clock=clock, sleep=clock.sleep)
    seqs = [r["seq"] for r in _records(writer)]
    assert seqs == [1, 2, 3]
    assert len(set(seqs)) == len(seqs)


def test_a_clean_stop_is_not_an_outage(tmp_path: Path) -> None:
    """The counterweight to the test above, and the reason it needs one.

    A supervisor that recorded a gap whenever the loop ended would stamp one on every clean
    shutdown — end of session, deploy, operator stopping the service — and an archive whose gap
    records are mostly false teaches its readers to skip them.
    """
    clock = Clock()
    feeds = [FakeFeed([TICK, CaptureStopped("end of session")])]
    writer = _writer(tmp_path)

    report = run_capture(
        feeds=iter(feeds), writer=writer, symbols=["A"], clock=clock, sleep=clock.sleep
    )

    assert report.messages == 1
    assert report.gaps == 0
    assert report.stopped_cleanly
    assert [r["kind"] for r in _records(writer)] == ["TICK"]


def test_reconnection_backs_off_rather_than_spinning(tmp_path: Path) -> None:
    """A tight reconnect loop against a refusing endpoint is how a client gets banned."""
    clock = Clock()
    feeds = [
        FakeFeed([ConnectionError("no")]),
        FakeFeed([ConnectionError("no")]),
        FakeFeed([TICK]),
    ]
    writer = _writer(tmp_path)

    run_capture(
        feeds=iter(feeds),
        writer=writer,
        symbols=["A"],
        clock=clock,
        sleep=clock.sleep,
        backoff_seconds=2.0,
    )

    assert clock.slept == [2.0, 4.0], f"doubling, not repeating: {clock.slept}"


def test_it_gives_up_after_a_bounded_number_of_attempts(tmp_path: Path) -> None:
    """And says so, rather than reconnecting forever against an endpoint that is gone.

    A supervisor that never gives up looks identical, from outside, to one that is capturing.
    """
    clock = Clock()
    feeds = [FakeFeed([ConnectionError("no")]) for _ in range(10)]
    writer = _writer(tmp_path)

    report = run_capture(
        feeds=iter(feeds),
        writer=writer,
        symbols=["A"],
        clock=clock,
        sleep=clock.sleep,
        max_reconnects=3,
    )

    assert not report.stopped_cleanly
    assert report.reconnects == 3
    assert report.gaps == 0, "no reconnection succeeded, so no gap was ever closed"
    assert "gave up" in report.reason


def test_the_feed_is_closed_on_the_way_out(tmp_path: Path) -> None:
    """A socket left open outlives the process that forgot it."""
    feed = FakeFeed([TICK, CaptureStopped("done")])
    writer = _writer(tmp_path)
    run_capture(
        feeds=iter([feed]), writer=writer, symbols=["A"], clock=Clock(), sleep=lambda _s: None
    )
    assert feed.closed


def test_running_out_of_feeds_is_not_a_clean_stop(tmp_path: Path) -> None:
    """The fixture's own edge, pinned so a test cannot pass by exhausting the script."""
    clock = Clock()
    writer = _writer(tmp_path)
    report = run_capture(
        feeds=iter([FakeFeed([ConnectionError("drop")])]),
        writer=writer,
        symbols=["A"],
        clock=clock,
        sleep=clock.sleep,
    )
    assert not report.stopped_cleanly


def test_the_gap_is_stamped_from_the_first_drop_not_the_last_retry(tmp_path: Path) -> None:
    """A two-hour outage must not be recorded as its final thirty seconds.

    Each failed reconnection is part of the same hole, so re-stamping the disconnect time at
    every attempt shortens the recorded outage every time it retries — understating it in the
    direction that makes the archive look healthier than it was.
    """
    clock = Clock()
    first_drop = clock.now
    feeds = [
        FakeFeed([TICK, ConnectionError("drop")]),
        FakeFeed([ConnectionError("still down")]),
        FakeFeed([ConnectionError("still down")]),
        FakeFeed([TICK]),
    ]
    writer = _writer(tmp_path)

    run_capture(
        feeds=iter(feeds),
        writer=writer,
        symbols=["A"],
        clock=clock,
        sleep=clock.sleep,
        backoff_seconds=60.0,
    )

    gap = next(r for r in _records(writer) if r["kind"] == "GAP")
    assert gap["disconnected_at_ns"] == first_drop, "stamped from the first drop"
    assert writer.outage_ns >= 420 * 1_000_000_000, (
        f"60 + 120 + 240 seconds of retries are all inside the hole, got {writer.outage_ns}"
    )
    assert "drop" in str(gap["reason"]), "the reason is the one that started the outage"


def test_the_backoff_resets_after_a_successful_reconnect(tmp_path: Path) -> None:
    """Otherwise the next disconnect inherits an escalation it did not earn, and a service that
    drops briefly twice an hour ends the day waiting hours between attempts."""
    clock = Clock()
    feeds = [
        FakeFeed([TICK, ConnectionError("first")]),
        FakeFeed([TICK, ConnectionError("second")]),
        FakeFeed([TICK]),
    ]
    writer = _writer(tmp_path)

    run_capture(
        feeds=iter(feeds),
        symbols=["A"],
        writer=writer,
        clock=clock,
        sleep=clock.sleep,
        backoff_seconds=3.0,
    )

    assert clock.slept == [3.0, 3.0], f"each outage starts its own backoff: {clock.slept}"


def test_the_feed_is_closed_after_a_disconnect_too(tmp_path: Path) -> None:
    """Not only on the clean-stop path. A dropped socket still holds a file descriptor, and a
    supervisor that reconnects ten times leaks ten of them."""
    dropped = FakeFeed([ConnectionError("drop")])
    live = FakeFeed([TICK])
    writer = _writer(tmp_path)
    run_capture(
        feeds=iter([dropped, live]),
        writer=writer,
        symbols=["A"],
        clock=Clock(),
        sleep=lambda _s: None,
    )
    assert dropped.closed, "the dropped feed is closed"
    assert live.closed, "and so is the one that ran to the end"
