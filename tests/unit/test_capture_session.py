"""Composing one capture session: decide, record the hole, then capture (§6 M4).

`[C-M4-07]` computes how late a start was; `[C-M4-04]` knows how to write a hole into the
stream. Nothing joined them, so `late_by_seconds` was a number computed and thrown away -- the
decision knew the archive was missing 09:15-11:00 and the archive did not.

The two properties that matter here pull against each other, and are the same pair the
supervisor already balances between feeds. A late start must leave a mark, or the missing open
reads as a quiet market. An ON-TIME start must not, or every clean session begins with a
zero-length outage and a reader who learns to skip gap records has lost the signal entirely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pips.core.calendar import load_calendar
from pips.data.breeze.capture import CaptureWriter, MessageKind
from pips.data.breeze.capture_session import run_session

ROOT = Path(__file__).resolve().parents[2]
CAL = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")
IST = ZoneInfo("Asia/Kolkata")

OPEN = datetime(2026, 9, 3, 9, 15, tzinfo=IST)  # a Thursday
DAY = "2026-09-03"


def ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000_000)


@dataclass
class SpyFeed:
    """A feed that records whether it was ever touched, and yields a fixed message."""

    subscribed: list[str] | None = None
    closed: bool = False

    def subscribe(self, symbols: list[str]) -> None:
        self.subscribed = list(symbols)

    def messages(self) -> Any:
        yield (MessageKind.TICK, {"ltp": 2801.0})

    def close(self) -> None:
        self.closed = True


def records(writer: CaptureWriter) -> list[dict[str, Any]]:
    return [json.loads(line) for line in writer.path.read_text().splitlines() if line.strip()]


def test_an_on_time_start_writes_no_gap(tmp_path: Path) -> None:
    """A zero-length outage at the head of every clean session would fill the archive with
    holes that never happened, and a reader who learns to skip them has lost the one signal
    the gap record exists to carry."""
    writer = CaptureWriter(root=tmp_path, session_id="s1", day=DAY)
    feed = SpyFeed()

    report = run_session(
        calendar=CAL,
        now=OPEN,
        feeds=[feed],
        writer=writer,
        symbols=["RELIND"],
        clock=lambda: ns(OPEN),
        sleep=lambda _s: None,
    )

    assert report.ran is True
    assert report.opening_gap_seconds == 0
    assert [r["kind"] for r in records(writer)] == ["TICK"]


def test_a_late_start_writes_the_missing_open_into_the_stream(tmp_path: Path) -> None:
    """The hole runs from the session open to the moment capture actually began, and it is the
    FIRST record in the file -- an archive that opens with a tick at 11:00 and explains the
    missing hour later is one nobody reads in order."""
    started = OPEN + timedelta(hours=1, minutes=45)
    writer = CaptureWriter(root=tmp_path, session_id="s1", day=DAY)

    report = run_session(
        calendar=CAL,
        now=started,
        feeds=[SpyFeed()],
        writer=writer,
        symbols=["RELIND"],
        clock=lambda: ns(started),
        sleep=lambda _s: None,
    )

    assert report.ran is True
    assert report.opening_gap_seconds == 105 * 60

    written = records(writer)
    assert [r["kind"] for r in written] == ["GAP", "TICK"]
    gap = written[0]
    assert gap["disconnected_at_ns"] == ns(OPEN)
    assert gap["reconnected_at_ns"] == ns(started)
    assert gap["messages_missed"] is None, "the count is unknowable; a zero would be a claim"
    assert "late" in gap["reason"]


def test_a_closed_market_never_opens_a_socket(tmp_path: Path) -> None:
    """Not merely "captures nothing" -- the feed must not be TOUCHED.

    Subscribing on a holiday spends a live subscription to record an empty file, and an empty
    file is indistinguishable from a session whose feed was dead. Declining before the socket
    is the difference between "the exchange was shut" and "we do not know".
    """
    writer = CaptureWriter(root=tmp_path, session_id="s1", day="2026-09-05")
    feed = SpyFeed()

    report = run_session(
        calendar=CAL,
        now=datetime(2026, 9, 5, 11, 0, tzinfo=IST),  # a Saturday
        feeds=[feed],
        writer=writer,
        symbols=["RELIND"],
        clock=lambda: 0,
        sleep=lambda _s: None,
    )

    assert report.ran is False
    assert "not a trading day" in report.reason
    assert feed.subscribed is None, "the socket was opened on a day with no session"
    assert feed.closed is False
    assert report.capture is None
    assert not writer.path.exists(), "an empty file would read as a session that produced nothing"


def test_a_start_before_the_open_declines_rather_than_waits(tmp_path: Path) -> None:
    """08:00 is not an error and not a session. The caller decides whether to sleep until 09:15;
    this says only that now is not the time, and says which time is."""
    writer = CaptureWriter(root=tmp_path, session_id="s1", day=DAY)
    feed = SpyFeed()

    report = run_session(
        calendar=CAL,
        now=OPEN - timedelta(hours=1),
        feeds=[feed],
        writer=writer,
        symbols=["RELIND"],
        clock=lambda: 0,
        sleep=lambda _s: None,
    )

    assert report.ran is False
    assert "opens at 09:15" in report.reason
    assert feed.subscribed is None


def test_the_capture_report_is_carried_through_rather_than_summarised(tmp_path: Path) -> None:
    """The supervisor's own account of the session -- messages, gaps, why it ended -- is what a
    reader needs; re-deriving it here would let the two disagree."""
    writer = CaptureWriter(root=tmp_path, session_id="s1", day=DAY)

    report = run_session(
        calendar=CAL,
        now=OPEN,
        feeds=[SpyFeed()],
        writer=writer,
        symbols=["RELIND"],
        clock=lambda: ns(OPEN),
        sleep=lambda _s: None,
    )

    assert report.capture is not None
    assert report.capture.messages == 1
    assert report.capture.reason == "feed ended"
    assert report.symbols_requested == 1


def test_the_session_subscribes_the_symbols_it_was_given(tmp_path: Path) -> None:
    writer = CaptureWriter(root=tmp_path, session_id="s1", day=DAY)
    feed = SpyFeed()

    run_session(
        calendar=CAL,
        now=OPEN,
        feeds=[feed],
        writer=writer,
        symbols=["RELIND", "TCS"],
        clock=lambda: ns(OPEN),
        sleep=lambda _s: None,
    )

    assert feed.subscribed == ["RELIND", "TCS"]


def test_the_decision_says_whether_the_holiday_list_was_verified(tmp_path: Path) -> None:
    """Carried onto the session report for the same reason it is on the decision: a capture day
    with no messages, on a calendar with no verified holidays, is UNKNOWN rather than quiet."""
    writer = CaptureWriter(root=tmp_path, session_id="s1", day=DAY)

    report = run_session(
        calendar=CAL,
        now=OPEN,
        feeds=[SpyFeed()],
        writer=writer,
        symbols=["RELIND"],
        clock=lambda: ns(OPEN),
        sleep=lambda _s: None,
    )

    assert report.holidays_verified is False
