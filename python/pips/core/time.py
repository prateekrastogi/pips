"""Time, sessions and bar labelling primitives  [C-BAR-01] [C-SESS-01].

Bars are labelled by **close time** and are usable at or after their label. A trade at
an interior boundary ``t`` belongs to the bar *ending* at ``t`` -- bars are half-open
``(label - interval, label]`` -- except the first bar of a session, which includes the
session's opening instant.

The full bar builder (sessions from the exchange calendar, watermarks, late events)
is M21's Rust ``bars`` crate; these are the shared conventions its fixtures pin.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Final, NewType

__all__ = [
    "IST",
    "NS_PER_MINUTE",
    "NS_PER_SECOND",
    "TimestampNs",
    "bar_label_ns",
    "is_usable_at",
    "to_ist",
    "ts_from_iso",
]

TimestampNs = NewType("TimestampNs", int)

NS_PER_SECOND: Final = 1_000_000_000
NS_PER_MINUTE: Final = 60 * NS_PER_SECOND
IST: Final = timezone(timedelta(hours=5, minutes=30), "IST")


def ts_from_iso(iso: str) -> TimestampNs:
    """Parse an ISO-8601 timestamp to nanoseconds since the Unix epoch.

    A naive timestamp is interpreted as IST -- the exchange's clock -- never as local
    machine time, so the same string means the same instant on every machine.
    """
    parsed = datetime.fromisoformat(iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return TimestampNs(
        int(parsed.astimezone(UTC).timestamp()) * NS_PER_SECOND + parsed.microsecond * 1000
    )


def to_ist(ts: int) -> datetime:
    """Render a nanosecond timestamp in IST for logs and reports."""
    return datetime.fromtimestamp(ts / NS_PER_SECOND, tz=IST)


def bar_label_ns(trade_ts: int, interval_ns: int, session_open_ns: int) -> TimestampNs:
    """Close-time label of the bar that a trade at ``trade_ts`` belongs to.

    Boundary rule: a trade exactly at an interior boundary belongs to the bar ending
    there. The session's opening instant belongs to the first bar (there is no bar
    ending at the open).
    """
    if interval_ns <= 0:
        raise ValueError(f"interval must be positive, got {interval_ns}")
    if trade_ts < session_open_ns:
        raise ValueError(f"trade at {trade_ts} precedes session open {session_open_ns}")
    elapsed = trade_ts - session_open_ns
    whole, remainder = divmod(elapsed, interval_ns)
    n = whole if remainder == 0 and whole > 0 else whole + 1
    return TimestampNs(session_open_ns + n * interval_ns)


def is_usable_at(bar_label: int, decision_ts: int) -> bool:
    """A close-labelled bar is measurable only at or after its label (causality)."""
    return decision_ts >= bar_label
