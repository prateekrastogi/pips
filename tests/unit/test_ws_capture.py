"""Forward websocket capture (§6 M4).

No donor: SAL-0025 is NONE_FOUND after a full sweep, so this is from-scratch work that rule 13
pre-authorises.

**The failure this design exists to prevent is a silent hole.** A capture service that
reconnects and resumes produces an archive whose gaps are invisible — and months later nobody
can tell a quiet market from an outage. It is the same shape as the rate-limit lesson from the
backfill: the dangerous failure is not the one that stops you, it is the one that looks like
data.

So every disconnect writes a GAP record into the stream itself, and that record says
`messages_missed: null`. After a disconnect you cannot know how many messages you missed.
Recording zero would be a lie; recording null is the truth, and a reader can act on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pips.data.breeze.capture import CaptureWriter, MessageKind

TICK = {"symbol": "RELIND", "ltp": 1285.4}


def read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------ envelopes -----------


def test_every_message_carries_a_receive_timestamp_and_sequence(tmp_path: Path) -> None:
    # §3.4: bronze holds exact payloads WITH receive timestamps. Vendor timestamps describe
    # the market; the receive timestamp describes what we actually knew and when.
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    writer.write(MessageKind.TICK, TICK)
    writer.write(MessageKind.TICK, TICK)
    records = read(writer.path)
    assert [r["seq"] for r in records] == [1, 2]
    assert all(r["received_at_ns"] > 0 for r in records)
    assert records[0]["payload"] == TICK


def test_the_payload_is_stored_exactly(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    odd = {"a": None, "b": [1, 2, {"c": "x"}], "d": 1.5}
    writer.write(MessageKind.QUOTE, odd)
    assert read(writer.path)[0]["payload"] == odd


@pytest.mark.parametrize("kind", list(MessageKind))
def test_every_message_kind_round_trips(tmp_path: Path, kind: MessageKind) -> None:
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    writer.write(kind, TICK)
    assert read(writer.path)[0]["kind"] == kind.value


# ------------------------------------------------------------------ gaps ----------------


def test_a_disconnect_writes_a_gap_record_into_the_stream(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    writer.write(MessageKind.TICK, TICK)
    writer.record_gap(disconnected_at_ns=1000, reconnected_at_ns=5000, reason="socket closed")
    writer.write(MessageKind.TICK, TICK)

    records = read(writer.path)
    assert [r["kind"] for r in records] == ["TICK", "GAP", "TICK"]
    gap = records[1]
    assert gap["disconnected_at_ns"] == 1000
    assert gap["reconnected_at_ns"] == 5000
    assert gap["reason"] == "socket closed"


def test_a_gap_reports_missed_messages_as_unknown_not_zero(tmp_path: Path) -> None:
    # The load-bearing assertion. After a disconnect the count is genuinely unknowable, and
    # zero would read as "nothing was missed" — a claim the capture cannot support.
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    writer.record_gap(disconnected_at_ns=1, reconnected_at_ns=2, reason="x")
    assert read(writer.path)[0]["messages_missed"] is None


def test_the_sequence_continues_across_a_gap(tmp_path: Path) -> None:
    # A reset sequence would make the gap invisible to anyone counting messages.
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    writer.write(MessageKind.TICK, TICK)
    writer.record_gap(disconnected_at_ns=1, reconnected_at_ns=2, reason="x")
    writer.write(MessageKind.TICK, TICK)
    assert [r["seq"] for r in read(writer.path)] == [1, 2, 3]


def test_a_gap_that_ends_before_it_begins_is_refused(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    with pytest.raises(ValueError, match="reconnected"):
        writer.record_gap(disconnected_at_ns=5000, reconnected_at_ns=1000, reason="x")


def test_gaps_are_countable_for_the_daily_report(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "bronze", session_id="s1")
    writer.write(MessageKind.TICK, TICK)
    writer.record_gap(disconnected_at_ns=1, reconnected_at_ns=2, reason="a")
    writer.record_gap(disconnected_at_ns=3, reconnected_at_ns=9, reason="b")
    assert writer.gap_count == 2
    assert writer.outage_ns == 1 + 6


# ------------------------------------------------------------------ append-only ---------


def test_a_reopened_session_appends_rather_than_truncating(tmp_path: Path) -> None:
    root = tmp_path / "bronze"
    first = CaptureWriter(root, session_id="s1")
    first.write(MessageKind.TICK, TICK)
    second = CaptureWriter(root, session_id="s1")
    second.write(MessageKind.TICK, TICK)
    assert len(read(second.path)) == 2, "a restart must not truncate what was already captured"


def test_a_reopened_session_does_not_reuse_sequence_numbers(tmp_path: Path) -> None:
    # Two records sharing a seq would make the stream unorderable, and a restart is the most
    # likely moment for it to happen.
    root = tmp_path / "bronze"
    CaptureWriter(root, session_id="s1").write(MessageKind.TICK, TICK)
    second = CaptureWriter(root, session_id="s1")
    second.write(MessageKind.TICK, TICK)
    seqs = [r["seq"] for r in read(second.path)]
    assert len(seqs) == len(set(seqs))


def test_capture_refuses_a_path_inside_the_repository(tmp_path: Path) -> None:
    # Rule 14 again, and a live tick stream is the worst possible thing to write into git.
    repo = Path(__file__).resolve().parents[2] / "data" / "bronze"
    with pytest.raises(ValueError, match="repository"):
        CaptureWriter(repo, session_id="s1")
