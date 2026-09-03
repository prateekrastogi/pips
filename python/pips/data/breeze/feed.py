"""The Breeze WebSocket adapter: a callback-driven vendor stream as an iterator (§6 M4).

:class:`~pips.data.breeze.ws_capture.Feed` is an iterator because a supervisor that owns the
reconnect loop needs to see a drop as an exception at a point it controls. Breeze is the other
shape: ``breeze.on_ticks = fn`` is invoked from a socketio thread, a disconnect surfaces as an
attribute on the SDK's handler, and nothing ever returns to the caller. This module is the
seam between the two, and it is deliberately the only place in the tree that knows the vendor
stream exists.

Two things about the SDK shape the design.

**A failed subscription returns normally.** ``subscribe_feeds`` wraps its whole body in
``except Exception as e: return f"Exception while subscribing to feeds {e}"``, and falls off
the end returning ``None`` when the socket was never connected. Both look like a call that
worked. Since the only symptom would be a ``messages()`` loop waiting on a subscription that
does not exist, the response is checked and a failure is raised: an empty capture day cannot
be backfilled, so it has to fail while someone can still fix it.

**Liveness has to be read out of the SDK's internals.** There is no public "am I connected".
``sio_rate_refresh_handler.sio.connected`` is what the SDK itself tests, so it is what this
reads -- but if a vendor upgrade moves it, the probe refuses rather than guessing. Guessing
"connected" would make every outage invisible; guessing "disconnected" would invent one.

What runs here is not what runs against the exchange: the wire payload and the exact shape of
a real drop are unverified until a live session. The bridge, the subscription, and the two
refusals are not.
"""

from __future__ import annotations

import queue
from collections.abc import Iterator
from typing import Any, Final, Protocol

from pips.data.breeze.capture import MessageKind
from pips.data.breeze.ws_capture import CaptureStopped

__all__ = [
    "BreezeFeed",
    "FeedUnsupportedError",
    "SubscriptionFailedError",
    "WebSocketClient",
]

DEPTH_KEY: Final = "depth"
"""Where the SDK's ``parse_data`` puts market depth. Its absence is not proof of a tick."""

LIVENESS_PATH: Final = "sio_rate_refresh_handler.sio.connected"
"""The SDK's own disconnect test, read here because it exposes no public equivalent."""

_MISSING: Final = object()


class SubscriptionFailedError(RuntimeError):
    """A subscription the vendor accepted in form and refused in fact."""


class FeedUnsupportedError(RuntimeError):
    """The SDK no longer looks the way this adapter reads it."""


class WebSocketClient(Protocol):
    """The slice of ``BreezeConnect`` this adapter uses."""

    on_ticks: Any

    def ws_connect(self) -> None: ...

    def subscribe_feeds(self, **kwargs: Any) -> Any: ...

    def ws_disconnect(self) -> Any: ...


class BreezeFeed:
    """One connected Breeze subscription, read as an iterator of messages."""

    def __init__(
        self,
        client: WebSocketClient,
        *,
        exchange: str = "NSE",
        product: str = "cash",
        poll_seconds: float = 0.25,
    ) -> None:
        self._client = client
        self._exchange = exchange
        self._product = product
        self._poll_seconds = poll_seconds
        self._queue: queue.Queue[Any] = queue.Queue()
        self._stop_reason: str | None = None
        self._closed = False
        # Registered before subscribing: the socketio thread can deliver the moment the
        # subscription lands, and a tick arriving before the callback exists is gone.
        client.on_ticks = self._receive

    def subscribe(self, symbols: list[str]) -> None:
        """Connect and subscribe, refusing any symbol the vendor did not actually take.

        Every symbol is checked, not just the first: a shortlist that subscribes all but one
        is not a working capture, and the one it dropped would be missing from the archive
        with nothing to say so.
        """
        self._client.ws_connect()
        for symbol in symbols:
            response = self._client.subscribe_feeds(
                stock_code=symbol,
                exchange_code=self._exchange,
                product_type=self._product,
                # An interval switches the SDK to the OHLC socket; raw ticks are the point.
                interval="",
                get_exchange_quotes=True,
                get_market_depth=True,
                # Rule 7. Setting this connects the ORDER socket from a process holding
                # data-plane credentials, which is the separation the rule exists to keep.
                get_order_notification=False,
            )
            if not isinstance(response, dict):
                # The success path returns ``{"message": ...}``; the swallowed-exception path
                # returns a string and the never-connected path returns None.
                raise SubscriptionFailedError(f"{symbol}: subscription not accepted: {response!r}")

    def messages(self) -> Iterator[tuple[MessageKind, Any]]:
        """Yield messages as they arrive, ending only for a stated reason.

        Buffered messages are delivered before any reason to end is considered: a tick already
        in hand was received before the drop, and discarding it would widen the recorded hole
        past the real one.
        """
        while True:
            try:
                payload = self._queue.get(timeout=self._poll_seconds)
            except queue.Empty:
                if self._stop_reason is not None:
                    raise CaptureStopped(self._stop_reason) from None
                if not self._connected():
                    raise ConnectionError(f"{LIVENESS_PATH} reports a disconnect") from None
                continue
            yield self._classify(payload), payload

    def stop(self, reason: str = "stopped") -> None:
        """Ask the feed to end cleanly. Read by the loop once the buffer has drained."""
        if self._stop_reason is None:
            self._stop_reason = reason

    def close(self) -> None:
        """Disconnect the socket. Idempotent: the supervisor closes in a ``finally``.

        Closing also records a stop, so a read after close reports the deliberate end rather
        than the disconnect it caused -- a spurious gap on every clean session otherwise.
        """
        if self._closed:
            return
        self._closed = True
        self.stop("closed")
        self._client.on_ticks = None
        self._client.ws_disconnect()

    def _receive(self, payload: Any) -> None:
        """The vendor callback. Runs on the socketio thread; does nothing that can block."""
        self._queue.put(payload)

    def _classify(self, payload: Any) -> MessageKind:
        """Label the message, defaulting to TICK for a shape this does not recognise.

        The callback does not say which channel delivered a message, so this is a guess. The
        payload is written verbatim either way, which keeps a mislabelling recoverable from
        the record -- unlike refusing the message, which would discard the only evidence of
        what the vendor sent.
        """
        if isinstance(payload, dict) and DEPTH_KEY in payload:
            return MessageKind.DEPTH
        return MessageKind.TICK

    def _connected(self) -> bool:
        """Whether the vendor still has a socket, by the SDK's own test."""
        handler = getattr(self._client, "sio_rate_refresh_handler", None)
        if handler is None:
            # Not a default: the SDK sets this to None in ``ws_disconnect`` and leaves it None
            # before ``ws_connect``. Both are genuinely "no socket", not "unknown".
            return False
        connected = getattr(getattr(handler, "sio", None), "connected", _MISSING)
        if connected is _MISSING:
            raise FeedUnsupportedError(
                f"cannot read {LIVENESS_PATH}: this adapter can no longer tell a live socket "
                f"from a dropped one, and will not report either without measuring it"
            )
        return bool(connected)
