"""The supervisor that drives forward WS capture  (§6 M4, `[C-M4-04]`).

:class:`~pips.data.breeze.capture.CaptureWriter` knows how to record a message and how to record
a hole. Nothing drove it -- no CLI command, no Make target, no compose service -- so "forward WS
capture from day one" had no day one. That matters more than an unrun backfill: history can be
fetched later, and a session that passes uncaptured is spread and depth that cannot be bought
back at any price.

Two properties carry the weight here, and they pull against each other:

**A disconnect must leave a mark.** A supervisor that reconnects quietly produces an archive
whose gaps are invisible, which is exactly the failure the GAP record exists to prevent.

**A deliberate stop must not.** Recording a gap at every clean shutdown -- end of session,
deploy, an operator stopping the service -- fills the archive with outages that never happened,
and a reader who learns to skip gap records has lost the one signal that matters. So a clean
stop is a distinct exception (:class:`CaptureStopped`) rather than "the loop ended".

**The feed seam is a protocol, not the vendor's client.** Breeze's SDK is callback-driven and
cannot be exercised without a socket; the vendor adapter is a thin implementation of
:class:`Feed` and is the only part that cannot be tested here.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from pips.data.breeze.capture import CaptureWriter, MessageKind

__all__ = ["CaptureReport", "CaptureStopped", "Feed", "run_capture"]


class CaptureStopped(Exception):  # noqa: N818 -- a signal, not an error condition
    """A deliberate stop. Distinct from a disconnect, and never recorded as a gap."""


class Feed(Protocol):
    """One connected subscription. A drop is a `ConnectionError` out of :meth:`messages`."""

    def subscribe(self, symbols: list[str]) -> None: ...

    def messages(self) -> Iterator[tuple[MessageKind, Any]]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class CaptureReport:
    """What one supervised capture did, and why it ended."""

    messages: int
    gaps: int
    reconnects: int
    stopped_cleanly: bool
    reason: str


def run_capture(
    *,
    feeds: Iterable[Feed],
    writer: CaptureWriter,
    symbols: list[str],
    clock: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], None] = time.sleep,
    backoff_seconds: float = 1.0,
    max_reconnects: int = 10,
) -> CaptureReport:
    """Drive ``writer`` from successive ``feeds``, recording every hole between them.

    ``feeds`` is an iterable of connections rather than a factory so the supervisor never owns
    the vendor import: each item is one already-connected subscription, and exhausting them is a
    failure to reconnect rather than a clean finish.

    The gap is written **after** the reconnection succeeds, because both of its timestamps are
    needed to state the outage and the second is not known until then. A disconnect that never
    reconnects therefore leaves no gap record -- the report says why, and the stream simply
    stops, which is the honest shape: an outage with no end is not a gap, it is where the
    archive ends.
    """
    messages = gaps = reconnects = 0
    disconnected_at: int | None = None
    disconnect_reason = ""
    wait = backoff_seconds

    for feed in feeds:
        if disconnected_at is not None:
            sleep(wait)
            wait *= 2
            reconnects += 1

        try:
            feed.subscribe(symbols)
            for kind, payload in feed.messages():
                if disconnected_at is not None:
                    # Reconnected and receiving again: the hole now has both ends.
                    writer.record_gap(disconnected_at, clock(), disconnect_reason)
                    gaps += 1
                    disconnected_at = None
                    wait = backoff_seconds
                writer.write(kind, payload)
                messages += 1
        except CaptureStopped as stop:
            # No `feed.close()` here: the `finally` below covers every exit from this block,
            # and a second call was dead code that made removing the `finally` look harmless.
            return CaptureReport(messages, gaps, reconnects, True, str(stop))
        except ConnectionError as dropped:
            # The FIRST drop, not the latest failed attempt -- time AND reason together. A
            # gap stamped from the last retry reports the final few seconds of a two-hour
            # outage, understating the hole in the direction that makes the archive look
            # healthier than it was; and a reason taken from the last retry describes why the
            # outage persisted rather than what caused it, so the record would be a mixture of
            # two events rather than an account of one.
            if disconnected_at is None:
                disconnected_at = clock()
                disconnect_reason = str(dropped)
        finally:
            feed.close()

        if disconnected_at is None:
            # The feed ended without dropping and without being stopped. Not a hole, but not a
            # stop either -- nobody asked it to end, so it is reported rather than swallowed.
            return CaptureReport(messages, gaps, reconnects, True, "feed ended")

        if reconnects >= max_reconnects:
            break

    return CaptureReport(
        messages,
        gaps,
        reconnects,
        False,
        f"gave up after {reconnects} reconnection attempt(s): {disconnect_reason}",
    )
