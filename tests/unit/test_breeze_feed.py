"""The vendor adapter behind the capture supervisor (§6 M4).

Breeze's stream is CALLBACK-driven -- ``breeze.on_ticks = fn``, invoked from a socketio
thread -- and :class:`~pips.data.breeze.ws_capture.Feed` is an iterator. The adapter is the
bridge, and bridging is where things go wrong without a socket: messages lost between the
callback and the consumer, a disconnect that never reaches the supervisor, or a subscription
that failed and said nothing.

That last one is not hypothetical. The vendor's ``subscribe_feeds`` ends in::

    except Exception as e:
        return f"Exception while subscribing to feeds {e}"

so a failed subscription *returns normally*, and returns ``None`` outright when the socket was
never connected. An adapter that ignores the return value would sit in ``messages()`` waiting
forever on a subscription that does not exist, and the day's archive would be empty for a
reason nothing recorded. Forward capture cannot be backfilled, so this is the one defect here
that costs something permanent.

**Live behaviour remains unverified.** Whether a drop really shows up as ``sio.connected``
going false, and what the wire payload holds beyond the keys named below, are things only a
live session settles. Everything tested here is ours: the bridge, the subscription, the
refusals.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from pips.data.breeze.capture import MessageKind
from pips.data.breeze.feed import (
    LIVENESS_PATH,
    BreezeFeed,
    FeedUnsupportedError,
    SubscriptionFailedError,
)
from pips.data.breeze.ws_capture import CaptureStopped

POLL = 0.01


class FakeSio:
    def __init__(self) -> None:
        self.connected = True


class FakeHandler:
    def __init__(self) -> None:
        self.sio = FakeSio()


class FakeBreeze:
    """Only the surface the adapter touches, with the vendor's own return shapes."""

    def __init__(self, *, response: Any = "default") -> None:
        self.on_ticks: Any = None
        self.subscribed: list[dict[str, Any]] = []
        self.connects = 0
        self.disconnects = 0
        self.disconnected = False
        self.sio_rate_refresh_handler: Any = FakeHandler()
        self._response = response

    def ws_connect(self) -> None:
        self.connects += 1

    def subscribe_feeds(self, **kwargs: Any) -> Any:
        self.subscribed.append(kwargs)
        if self._response == "default":
            return {"message": f"stock {kwargs.get('stock_code')} subscribed"}
        return self._response

    def ws_disconnect(self) -> list[dict[str, str]]:
        self.disconnects += 1
        self.disconnected = True
        self.sio_rate_refresh_handler = None
        return [{"message": "disconnected"}]


def drain(feed: BreezeFeed, *, deadline_seconds: float = 5.0) -> list[tuple[MessageKind, Any]]:
    """Read until the feed says it is finished, the way the supervisor does -- but not forever.

    `messages()` is `while True` and ends only when `stop()` was called or the socket reports a
    disconnect. A test that drains a fake which stays "connected" and forgets `stop()` therefore
    spins on `queue.Empty` indefinitely. Three pytest processes doing exactly that were found on
    2026-09-05, orphaned and two days old, from drafts of this file before the `stop()` calls
    went in.

    THE BOUND LIVES OUTSIDE THE GENERATOR ON PURPOSE. A first attempt checked a deadline between
    `next()` calls, and hung for five minutes anyway: `next()` never RETURNS while the feed is
    alive and silent, so a check between calls is never reached. The consumer runs in a daemon
    thread and the deadline is enforced with `join(timeout)`, which holds whatever the generator
    does. A daemon thread dies with the process, so a hung drain cannot outlive the test run --
    the two-day orphans were exactly that outliving.
    """
    out: list[tuple[MessageKind, Any]] = []
    failure: list[BaseException] = []

    def consume() -> None:
        try:
            out.extend(feed.messages())
        except CaptureStopped:
            return
        except BaseException as exc:
            failure.append(exc)

    worker = threading.Thread(target=consume, name="drain", daemon=True)
    worker.start()
    worker.join(timeout=deadline_seconds)
    if worker.is_alive():
        feed.stop("drain deadline")  # let the thread wind down; it is daemon either way
        raise AssertionError(
            f"drain() exceeded {deadline_seconds}s: the feed never stopped. The test almost "
            "certainly forgot to call feed.stop() before draining -- without it messages() "
            "loops forever, and a hanging test reports nothing."
        )
    if failure:
        raise failure[0]
    return out


def test_the_data_plane_never_subscribes_to_order_notifications() -> None:
    """Rule 7: two planes, two credentials, two processes.

    ``subscribe_feeds`` takes ``get_order_notification``, and the read-only data plane must
    never ask for it. It is not merely unnecessary -- setting it makes the SDK connect the
    ORDER socket (``_ws_connect(..., order_flag=True)``) from a process holding data-plane
    credentials, which is the separation the rule exists to keep.
    """
    client = FakeBreeze()
    BreezeFeed(client).subscribe(["RELIND", "TCS"])

    assert client.subscribed, "nothing was subscribed"
    for call in client.subscribed:
        assert call["get_order_notification"] is False
        assert call["exchange_code"] == "NSE"
        assert call["interval"] == "", "an interval switches the SDK to the OHLC socket"
    assert [c["stock_code"] for c in client.subscribed] == ["RELIND", "TCS"]


def test_a_subscription_the_vendor_swallowed_is_refused() -> None:
    """The vendor returns its exceptions as a string instead of raising them.

    Ignoring that turns a total failure into a silent, empty capture: ``messages()`` would
    block on a subscription that was never made, and the report would say the feed simply
    ended. A refusal here is a session that fails at 09:14 and can be fixed by 09:15.
    """
    client = FakeBreeze(response="Exception while subscribing to feeds bad token")
    with pytest.raises(SubscriptionFailedError, match="RELIND"):
        BreezeFeed(client).subscribe(["RELIND"])


def test_a_subscription_made_without_a_connected_socket_is_refused() -> None:
    """The other silent path: with no rate-refresh handler the SDK falls off the end of
    ``subscribe_feeds`` and returns ``None`` -- subscribing nothing, reporting nothing."""
    client = FakeBreeze(response=None)
    with pytest.raises(SubscriptionFailedError, match="RELIND"):
        BreezeFeed(client).subscribe(["RELIND"])


def test_one_failure_among_many_symbols_is_not_hidden_by_the_successes() -> None:
    """A shortlist of 500 that subscribes 499 is not a working capture, and the arithmetic
    downstream would divide by a universe it does not have."""
    client = FakeBreeze()
    ok = {"message": "subscribed"}
    responses = iter([ok, "Exception while subscribing to feeds bad token", ok])
    client.subscribe_feeds = lambda **kw: next(responses)  # type: ignore[method-assign]

    with pytest.raises(SubscriptionFailedError, match="TCS"):
        BreezeFeed(client).subscribe(["RELIND", "TCS", "INFY"])


def test_every_callback_message_reaches_the_consumer_in_order() -> None:
    """The bridge. A message handed to the callback on the socketio thread and dropped before
    the loop reads it is a tick that never existed, and nothing downstream could tell."""
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=POLL)
    feed.subscribe(["RELIND"])

    for i in range(5):
        client.on_ticks({"symbol": "RELIND", "ltp": float(i)})
    feed.stop()

    assert [payload["ltp"] for _kind, payload in drain(feed)] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_a_dropped_socket_raises_after_the_buffer_is_delivered() -> None:
    """The supervisor writes a GAP record when ``messages()`` raises ``ConnectionError``; an
    adapter that returned quietly instead would look like a finished session and leave the
    outage unrecorded.

    The buffer is drained first because the ticks already in hand were received before the
    drop. Discarding them would widen the recorded hole past the real one.
    """
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=POLL)
    feed.subscribe(["RELIND"])
    client.on_ticks({"symbol": "RELIND", "ltp": 1.0})
    client.sio_rate_refresh_handler.sio.connected = False

    stream = feed.messages()
    assert next(stream)[1]["ltp"] == 1.0, "a tick received before the drop is still a tick"
    with pytest.raises(ConnectionError, match="disconnect"):
        next(stream)


def test_a_liveness_probe_that_cannot_find_the_socket_refuses_to_call_it_connected() -> None:
    """The probe reads into the SDK's internals, so a vendor upgrade can move it.

    Defaulting to "connected" would disable drop detection silently: every outage would be
    invisible and the archive would show a quiet market. Defaulting to "disconnected" would
    fake a drop nobody had. Neither is a measurement, so it refuses and names what it wanted.
    """
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=POLL)
    feed.subscribe(["RELIND"])
    del client.sio_rate_refresh_handler.sio.connected

    with pytest.raises(FeedUnsupportedError, match="connected"):
        next(feed.messages())


def test_a_stopped_feed_reports_a_stop_and_not_a_drop() -> None:
    """Market close is not an outage. ``CaptureStopped`` is what the supervisor reads as a
    clean end; a ``ConnectionError`` here would append a spurious gap to every session."""
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=POLL)
    feed.subscribe(["RELIND"])
    feed.stop("market closed")

    with pytest.raises(CaptureStopped, match="market closed"):
        next(feed.messages())


def test_closing_the_feed_disconnects_the_socket() -> None:
    """A socket left open outlives the process that forgot it, and the supervisor closes each
    feed in a ``finally`` precisely so that a drop does not leak one per reconnect."""
    client = FakeBreeze()
    BreezeFeed(client).close()
    assert client.disconnected


def test_closing_a_feed_twice_disconnects_once() -> None:
    """``run_capture`` closes in a ``finally`` reachable after an explicit close, so the second
    call must be a no-op -- not merely survivable.

    Asserting only that it does not raise tested the fake's tolerance rather than the adapter's
    guard: both the real SDK and this fake accept a redundant ``ws_disconnect``. The count is
    the property. A second disconnect tears down a socket a later feed may already hold, and
    the supervisor builds the next feed from the same client.
    """
    client = FakeBreeze()
    feed = BreezeFeed(client)
    feed.close()
    feed.close()
    assert client.disconnects == 1


def test_a_vendor_side_disconnect_is_a_drop_and_not_a_live_socket() -> None:
    """``ws_disconnect`` sets the handler to ``None``, and anything else in the process can
    call it. Reading a missing handler as connected would leave the loop polling a socket that
    no longer exists: no ticks, no drop, no gap, no reconnect -- an outage that reads as a
    quiet market, which is the one failure the whole supervisor exists to prevent.
    """
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=POLL)
    feed.subscribe(["RELIND"])
    client.sio_rate_refresh_handler = None

    with pytest.raises(ConnectionError, match="disconnect"):
        next(feed.messages())


def test_the_reason_a_feed_stopped_survives_the_close_that_follows_it() -> None:
    """``close`` records its own stop, so the last writer would win.

    The supervisor closes every feed in a ``finally``, which means a session ended for a real
    reason -- market close, a shutdown signal -- is closed immediately afterwards. Keeping the
    later reason would make every report say "closed": an account of the tidying up rather
    than of what ended the capture, which is the same defect the gap record avoids by stamping
    the first drop rather than the last retry.
    """
    feed = BreezeFeed(FakeBreeze(), poll_seconds=POLL)
    feed.stop("market closed")
    feed.close()

    with pytest.raises(CaptureStopped, match="market closed"):
        next(feed.messages())


def test_a_depth_message_is_recorded_as_depth() -> None:
    """Grounded in the SDK: ``parse_data`` puts market depth under a ``"depth"`` key."""
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=POLL)
    feed.subscribe(["RELIND"])
    client.on_ticks({"symbol": "RELIND", "depth": [{"BestBuyRate-1": "2801.5"}]})
    feed.stop()

    assert [kind for kind, _payload in drain(feed)] == [MessageKind.DEPTH]


def test_a_message_is_recorded_even_when_its_kind_is_unclear() -> None:
    """Classification is a guess; the payload is not.

    The callback does not say which channel a message arrived on, so an unfamiliar shape could
    be mislabelled. The payload is written verbatim either way, which keeps a mislabelling
    recoverable from the record -- and is why an unknown shape defaults to TICK rather than
    being refused. Refusing it would discard the only evidence of what the vendor actually
    sent.
    """
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=POLL)
    feed.subscribe(["RELIND"])
    client.on_ticks({"something": "unfamiliar"})
    feed.stop()

    assert drain(feed) == [(MessageKind.TICK, {"something": "unfamiliar"})]


def test_reading_after_close_reports_the_stop_and_not_the_disconnect_it_caused() -> None:
    """Closing drops the socket, so the liveness probe afterwards says "disconnected" -- and
    reporting that would append a gap to the end of every clean session. The deliberate end
    is the true reason, and it is the one that survives."""
    feed = BreezeFeed(FakeBreeze(), poll_seconds=POLL)
    feed.close()

    with pytest.raises(CaptureStopped, match="closed"):
        next(feed.messages())


def test_the_adapter_and_the_supervisor_capture_across_a_drop(tmp_path: Any) -> None:
    """The two halves, together, on the shape they exist for: a drop mid-session.

    Each part is tested against a fake of the other, which leaves one thing unchecked -- that
    the exceptions the adapter raises are the exceptions the supervisor reads. Structural
    conformance to `Feed` is a type check; that a `CaptureStopped` ends the session cleanly
    and a `ConnectionError` becomes a gap record on disk is not, and a mismatch there would
    only show up during a real outage, on the one path that cannot be replayed.
    """
    from pips.data.breeze.capture import CaptureWriter
    from pips.data.breeze.ws_capture import run_capture

    first, second = FakeBreeze(), FakeBreeze()
    dropped = BreezeFeed(first, poll_seconds=POLL)
    resumed = BreezeFeed(second, poll_seconds=POLL)

    first.on_ticks({"symbol": "RELIND", "ltp": 2801.0})
    first.sio_rate_refresh_handler.sio.connected = False
    second.on_ticks({"symbol": "RELIND", "ltp": 2802.5})
    second.on_ticks({"symbol": "RELIND", "depth": [{"BestBuyRate-1": "2802.0"}]})
    resumed.stop("market closed")

    ticks = iter([1_000, 2_000, 3_000, 4_000])
    writer = CaptureWriter(root=tmp_path, session_id="s1", day="2026-09-03")
    report = run_capture(
        feeds=[dropped, resumed],
        writer=writer,
        symbols=["RELIND"],
        clock=lambda: next(ticks),
        sleep=lambda _seconds: None,
    )

    assert report.messages == 3
    assert report.gaps == 1
    assert report.reconnects == 1
    assert report.stopped_cleanly is True
    assert report.reason == "market closed"
    assert first.disconnected and second.disconnected, "both sockets were closed"

    records = [json.loads(line) for line in writer.path.read_text().splitlines() if line.strip()]
    assert [r["kind"] for r in records] == ["TICK", "GAP", "TICK", "DEPTH"]
    gap = records[1]
    assert (gap["disconnected_at_ns"], gap["reconnected_at_ns"]) == (1_000, 2_000)
    assert LIVENESS_PATH in gap["reason"], "the gap says what reported the drop"


def test_closing_a_feed_that_never_connected_does_not_mask_the_real_failure() -> None:
    """Found live, 2026-09-04, on the first real subscription attempt.

    The socket failed to connect (`Failed to connect to live stream`). `run_capture` then ran
    `feed.close()` from its `finally`, and the vendor's `ws_disconnect` emits on the namespace
    unconditionally — raising `BadNamespaceError: / is not a connected namespace` from inside
    the cleanup. **That exception replaced the one that mattered**, so the traceback ended in a
    socketio internal and the actual reason was three frames up under "During handling of the
    above exception".

    The supervisor closes every feed in a `finally` precisely so a drop cannot leak one, which
    means `close()` is reached on paths where the socket never opened. It must not raise there.
    """

    class NeverConnected(FakeBreeze):
        def ws_disconnect(self) -> list[dict[str, str]]:
            raise RuntimeError("/ is not a connected namespace")

    feed = BreezeFeed(NeverConnected())

    feed.close()  # must not raise


def test_a_failure_to_close_is_still_visible() -> None:
    """Swallowing is not the same as hiding. A disconnect that fails is worth knowing about --
    it can leak a socket -- so it is recorded on the feed rather than discarded, and a caller
    that wants to report cleanup trouble can. What it must not do is replace the reason the
    capture ended."""

    class NeverConnected(FakeBreeze):
        def ws_disconnect(self) -> list[dict[str, str]]:
            raise RuntimeError("/ is not a connected namespace")

    feed = BreezeFeed(NeverConnected())
    feed.close()

    assert feed.close_error is not None
    assert "not a connected namespace" in str(feed.close_error)


def test_draining_a_feed_that_was_never_stopped_fails_loudly_rather_than_hanging() -> None:
    """The hardening has to demonstrate itself, or it is a comment with a timer in it.

    Three orphaned pytest processes, two days old, were found on 2026-09-05 -- drafts of this
    file draining a fake that stays connected, with no `stop()`. `messages()` is `while True`
    and had nothing to end on. This is that exact shape, and it must end in seconds with the
    cause named, because a test that hangs reports nothing and takes the whole suite with it.
    """
    client = FakeBreeze()
    feed = BreezeFeed(client, poll_seconds=0.05)
    feed.subscribe(["RELIND"])
    # Deliberately NO feed.stop(). The fake reports connected forever.
    started = time.monotonic()
    with pytest.raises(AssertionError, match=r"forgot to call feed\.stop"):
        drain(feed, deadline_seconds=0.5)
    assert time.monotonic() - started < 3.0, "it must give up promptly, not merely eventually"
