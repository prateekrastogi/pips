"""When the server refuses the socket.io namespace, the feed keeps the server's reason.

BLK-0004 evidence (container `pips-capture-20260904`): `ConnectionError: One or more namespaces
failed to connect` and nothing about WHY. python-socketio delivers the server's refusal payload on
the `connect_error` event; the vendor SDK registers its own handler for it and the payload never
reached our log. The feed registers a listener of its own when the client exposes its socket.io
client, records the payload, and puts it in the failure it raises.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pips.data.breeze.feed import BreezeFeed


class FakeSio:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., Any]] = {}

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self.handlers[event] = handler


class RefusingClient:
    """Connects at the transport, is refused at the namespace, like 2026-09-04."""

    on_ticks: Any = None

    def __init__(self, payload: Any) -> None:
        self.sio = FakeSio()
        self.payload = payload

    def ws_connect(self) -> None:
        handler = self.handlers_for("connect_error")
        if handler is not None:
            handler(self.payload)
        raise Exception("Failed to connect to live stream")

    def handlers_for(self, event: str) -> Callable[..., Any] | None:
        return self.sio.handlers.get(event)

    def subscribe_feeds(self, **kwargs: Any) -> Any:
        raise AssertionError("never reached")

    def ws_disconnect(self) -> Any:
        return None


class ClientWithoutSio:
    on_ticks: Any = None

    def ws_connect(self) -> None:
        raise Exception("Failed to connect to live stream")

    def subscribe_feeds(self, **kwargs: Any) -> Any:
        raise AssertionError("never reached")

    def ws_disconnect(self) -> Any:
        return None


def test_the_servers_refusal_payload_is_kept_and_named_in_the_failure() -> None:
    client = RefusingClient({"message": "Invalid session", "code": 401})
    feed = BreezeFeed(client)
    with pytest.raises(Exception, match=r"Invalid session") as raised:
        feed.subscribe(["RELIND"])
    assert "Failed to connect to live stream" in str(raised.value)
    assert feed.connect_error_detail == {"message": "Invalid session", "code": 401}


def test_a_refusal_without_a_payload_still_says_the_server_refused_the_namespace() -> None:
    client = RefusingClient(None)
    feed = BreezeFeed(client)
    with pytest.raises(Exception, match=r"no payload"):
        feed.subscribe(["RELIND"])


def test_a_client_that_hides_its_socketio_client_still_works_and_says_nothing_was_captured() -> (
    None
):
    feed = BreezeFeed(ClientWithoutSio())
    with pytest.raises(Exception, match=r"Failed to connect to live stream") as raised:
        feed.subscribe(["RELIND"])
    assert feed.connect_error_detail is None
    # a missing listener must not read as a silent server: the two are different facts
    assert "no connect_error listener" in str(raised.value)
    assert "no payload" not in str(raised.value)
