"""`pips capture` — plans by default, and cannot open a socket without being told to (§6 M4).

Forward capture is built end to end (`[C-M4-04]`…`[C-M4-09]`) and nothing starts it, because
starting it is a live market-data subscription that is the owner's to authorise. That left the
decision abstract: the parts exist, and there was no way to see what running them would actually
do without running them.

`backfill` already solved the shape of this — "`--dry-run` prints the plan and its cost without
opening a session. That is the default thing to do first: the plan is cheap and a mis-typed
range is not" — with a control test that a real run DOES reach the fetcher, so a `main` that
fetched nothing at all could not pass both.

**This inverts backfill's default, deliberately.** Backfill spends quota, which is recoverable
tomorrow. Capture opens a subscription nobody has authorised, so planning is what a bare
invocation does, and `--live` is what it takes to open anything. The constitution's "never
create or enable anything on the live path" is not satisfied by a flag that defaults to off if
the safe mode is the one you have to remember.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pips.data.breeze import capture_session as cs

IST = ZoneInfo("Asia/Kolkata")
OPEN = datetime(2026, 9, 3, 9, 15, tzinfo=IST)  # a Thursday
SATURDAY = datetime(2026, 9, 5, 11, 0, tzinfo=IST)


class Tripwire:
    """A feed factory that fails the test if anything asks it for a connection."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("a socket was opened")


def args(tmp_path: Path, *extra: str) -> list[str]:
    return [str(tmp_path), "--symbols", "RELIND,TCS", "--now", OPEN.isoformat(), *extra]


def test_a_bare_invocation_plans_and_opens_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default must be the safe one.

    A `--dry-run` flag that defaults to off puts the whole weight of "do not subscribe without
    authorisation" on whoever remembers to type it. Here the bare command is the plan.
    """
    tripwire = Tripwire()

    assert cs.main(args(tmp_path), feed_factory=tripwire) == 0

    assert tripwire.calls == 0
    out = capsys.readouterr().out
    assert "planned" in out.lower()
    assert not (tmp_path / "ws").exists(), "planning created a capture file"


def test_the_plan_says_what_it_would_subscribe_and_where_it_would_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plan nobody can read is not a plan. The point of this command is that the
    authorisation decision can be made from its output."""
    cs.main(args(tmp_path), feed_factory=Tripwire())
    out = capsys.readouterr().out

    assert "RELIND" in out and "TCS" in out
    assert "2 symbol" in out
    assert "09:15" in out and "15:30" in out
    assert str(tmp_path) in out


def test_live_actually_reaches_the_feed_factory(tmp_path: Path) -> None:
    """The control. Without this, a `main` that opened nothing under ANY flag would pass the
    test above and look correct -- which is the same trick as a check that never runs."""
    reached: list[str] = []

    def factory(*_a: Any, **_k: Any) -> Any:
        reached.append("asked")
        raise RuntimeError("stop here — the socket is not the subject of this test")

    with pytest.raises(RuntimeError, match="stop here"):
        cs.main(args(tmp_path, "--live"), feed_factory=factory)

    assert reached == ["asked"]


def test_live_outside_the_session_still_opens_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--live` authorises a subscription during a session, not at any hour.

    2026-09-05 is a Saturday. Opening a socket on it would spend a live subscription to record
    an empty file, and an empty file cannot be told from a session whose feed was dead.
    """
    tripwire = Tripwire()
    argv = [str(tmp_path), "--symbols", "RELIND", "--now", SATURDAY.isoformat(), "--live"]

    assert cs.main(argv, feed_factory=tripwire) == 0

    assert tripwire.calls == 0
    assert "not a trading day" in capsys.readouterr().out


def test_a_naive_clock_is_refused(tmp_path: Path) -> None:
    """The container runs in UTC and the session does not. A `--now` without a zone would be
    read as whatever the process happens to be in -- `plan_capture` refuses it, and the CLI
    must not paper over that by attaching a zone of its own choosing."""
    argv = [str(tmp_path), "--symbols", "RELIND", "--now", "2026-09-03T09:30:00"]

    with pytest.raises(ValueError, match="timezone"):
        cs.main(argv, feed_factory=Tripwire())


def test_no_symbols_is_refused_rather_than_capturing_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty subscription list records an empty archive and reports success -- the same
    shape as a QC pass over no records."""
    argv = [str(tmp_path), "--symbols", "", "--now", OPEN.isoformat()]

    assert cs.main(argv, feed_factory=Tripwire()) == 2
    assert "no symbols" in capsys.readouterr().err.lower()
