"""Forward websocket capture  (§6 M4).

**From scratch, and pre-authorised.** SAL-0025 is NONE_FOUND after a full sweep of every ref in
``../past``: no capture code exists anywhere. The one artifact the sweep did turn up --
``logs/websocketLogs.log`` in ``intraday`` -- is absent at every commit that references it, so
it carries no traffic shapes either.

**The failure this design exists to prevent is a silent hole.** A capture service that
reconnects and resumes produces an archive whose gaps are invisible, and months later nobody
can tell a quiet market from an outage. It is the same shape as the rate-limit lesson from the
backfill: the dangerous failure is not the one that stops you, it is the one that looks like
data.

So a disconnect writes a **GAP record into the stream itself**, carrying
``messages_missed: null``. After a disconnect the count is genuinely unknowable; recording zero
would assert that nothing was missed, which the capture cannot support. Null is the honest
value and a reader can act on it -- quarantine the window, or fill it from the historical API.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pips.core.locality import refuse_repo_paths

__all__ = ["CaptureWriter", "MessageKind"]


class MessageKind(StrEnum):
    """What a captured record is. GAP is written by us, not received."""

    TICK = "TICK"
    QUOTE = "QUOTE"
    DEPTH = "DEPTH"


_GAP = "GAP"


@dataclass
class CaptureWriter:
    """Append-only JSONL capture, one file per session per day.

    JSONL because a capture must survive being killed mid-write: a truncated final line loses
    one record, where a truncated JSON array loses the file.
    """

    root: Path
    session_id: str
    day: str = field(default_factory=lambda: datetime.now(UTC).date().isoformat())
    _seq: int = field(default=0, init=False)
    gap_count: int = field(default=0, init=False)
    outage_ns: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        refuse_repo_paths(self.root, what="tick capture")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Resume the sequence from what is already on disk. A restart is the most likely
        # moment to reuse a sequence number, and two records sharing one make the stream
        # unorderable -- which is precisely what the gap records exist to keep it from being.
        self._close_partial_line()
        self._seq = self._last_seq_on_disk()

    @property
    def path(self) -> Path:
        return self.root / "ws" / self.day / f"{self.session_id}.jsonl"

    def _close_partial_line(self) -> None:
        """Terminate a half-written final line before appending after it.

        A kill mid-write leaves a line with no newline, and "a" mode appends straight onto it
        -- fusing the fragment and the first record written after the restart into one line
        that neither parses. ONE lost record silently becomes two, and the JSONL claim in the
        class docstring stops being true. Closing the line keeps the loss to the record that
        was actually half-written.
        """
        if not self.path.exists():
            return
        with self.path.open("rb") as handle:
            if handle.seek(0, 2) == 0:
                return
            handle.seek(-1, 2)
            if handle.read(1) == b"\n":
                return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n")

    def _last_seq_on_disk(self) -> int:
        if not self.path.exists():
            return 0
        last = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                last = max(last, int(json.loads(line)["seq"]))
            except (ValueError, KeyError, TypeError):
                # A truncated final line from a kill mid-write. Skipping it is right: the
                # record is lost either way, and refusing to start would turn one lost message
                # into an outage.
                #
                # TypeError belongs here with the others: a line of valid JSON that is not an
                # object -- `null`, a bare number, a list -- indexes as `None["seq"]`, and
                # concatenated fragments and hand-repaired files both produce them. Both are
                # things people do to a capture after an outage.
                continue
        return last

    def _append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def write(self, kind: MessageKind, payload: Any) -> int:
        """Append one received message. Returns its sequence number."""
        self._seq += 1
        self._append(
            {
                "seq": self._seq,
                # The vendor stamp says when the market moved; this says when we knew.
                "received_at_ns": time.time_ns(),
                "kind": kind.value,
                "session_id": self.session_id,
                "payload": payload,
            }
        )
        return self._seq

    def record_gap(self, disconnected_at_ns: int, reconnected_at_ns: int, reason: str) -> int:
        """Record an outage **in the stream**, so the hole is visible to any reader.

        ``messages_missed`` is always ``None``. The count is unknowable after the fact, and a
        zero would be a claim that nothing was missed.
        """
        if reconnected_at_ns < disconnected_at_ns:
            raise ValueError(
                f"reconnected_at_ns {reconnected_at_ns} precedes disconnected_at_ns "
                f"{disconnected_at_ns} — a gap cannot end before it begins"
            )
        self._seq += 1
        self.gap_count += 1
        self.outage_ns += reconnected_at_ns - disconnected_at_ns
        self._append(
            {
                "seq": self._seq,
                "received_at_ns": time.time_ns(),
                "kind": _GAP,
                "session_id": self.session_id,
                "disconnected_at_ns": disconnected_at_ns,
                "reconnected_at_ns": reconnected_at_ns,
                "reason": reason,
                # Unknowable by construction. See the module docstring.
                "messages_missed": None,
            }
        )
        return self._seq
