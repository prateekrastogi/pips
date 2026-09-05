"""The pacer is wired into the fetchers, and it remembers what it learned.

Two facts about the campaign shape this, and the second was found by reading `backfill.py`
rather than assumed:

1. Owner, 2026-09-05: *"run it to maximum and without any limits, basis real time responding
   conditions of api."* So no preset per-minute constant governs the call rate.
2. **`run_backfill` already STOPS on the first `RATE_LIMITED` reply** — `_decide(kind)` returns
   STOP and the run breaks, because "pushing on would collect more rejections, and marking this
   key done would record a hole that looks like a holiday forever."

Together those mean the multiplicative decrease is nearly unused WITHIN a run: the run is over
the moment it fires. Its value is ACROSS runs. So the learned interval is PERSISTED — a rejection
teaches tomorrow's run to start slower, and a long clean run teaches it to start faster. Without
that, every run would re-derive the limit from the same optimistic starting point and re-discover
it by getting rejected, which is the one outcome that costs a whole day's progress.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pips.data.breeze.ingest import ResponseKind
from pips.data.breeze.pacing import AdaptivePacer


def test_it_persists_the_interval_it_learned(tmp_path: Path) -> None:
    state = tmp_path / "pace.json"
    p = AdaptivePacer(start_interval=1.0, step=0.1, state_path=state, sleep=lambda _s: None)
    p.observe(ResponseKind.OK)
    p.observe(ResponseKind.OK)
    assert state.exists(), "a learned rate that is not written down is relearned by rejection"
    assert json.loads(state.read_text())["interval"] == pytest.approx(0.8)


def test_a_later_run_starts_from_what_the_last_one_learned(tmp_path: Path) -> None:
    state = tmp_path / "pace.json"
    first = AdaptivePacer(start_interval=1.0, state_path=state, sleep=lambda _s: None)
    first.observe(ResponseKind.RATE_LIMITED)  # the vendor pushed back
    learned = first.interval

    second = AdaptivePacer(start_interval=1.0, state_path=state, sleep=lambda _s: None)
    assert second.interval == pytest.approx(learned), (
        "tomorrow must not restart at yesterday's optimistic rate and rediscover the limit "
        "by being rejected again — that costs a day"
    )
    assert second.interval > 1.0


def test_a_missing_or_unreadable_state_file_falls_back_to_the_start(tmp_path: Path) -> None:
    """A corrupt state file must not stop a campaign, and must not read as a learned rate."""
    bad = tmp_path / "pace.json"
    bad.write_text("{not json", encoding="utf-8")
    p = AdaptivePacer(start_interval=0.7, state_path=bad, sleep=lambda _s: None)
    assert p.interval == pytest.approx(0.7)


def test_the_ranged_fetcher_paces_and_observes_through_it(tmp_path: Path) -> None:
    """Wiring, not just capability. A pacer nothing consults is this project's signature failure."""
    from pips.data.breeze.client import ranged_fetcher

    calls: list[str] = []

    class FakeClient:
        def get_historical_data_v2(self, **kw: Any) -> dict[str, Any]:
            calls.append(str(kw["stock_code"]))
            return {"Status": 200, "Error": None, "Success": [{"datetime": "2026-08-25 00:00:00"}]}

    p = AdaptivePacer(
        start_interval=1.0, step=0.25, state_path=tmp_path / "pace.json", sleep=lambda _s: None
    )
    from datetime import date

    fetch = ranged_fetcher(FakeClient(), p, interval="1day")
    fetch("RELIND", date(2026, 8, 24), date(2026, 8, 26))

    assert calls == ["RELIND"]
    assert p.calls == 1, "the fetcher must acquire through the pacer"
    assert p.interval == pytest.approx(0.75), "and must feed the reply back into it"


def test_a_rate_limited_reply_reaches_the_pacer_from_the_fetcher(tmp_path: Path) -> None:
    """The reply is classified from the BODY (Status 5), not an HTTP code, so the fetcher has to
    look. A pacer that only ever sees successes learns only to speed up."""
    from datetime import date

    from pips.data.breeze.client import ranged_fetcher

    class ThrottlingClient:
        def get_historical_data_v2(self, **kw: Any) -> dict[str, Any]:
            return {"Status": 5, "Error": "Limit exceed: ...", "Success": None}

    p = AdaptivePacer(start_interval=1.0, state_path=tmp_path / "pace.json", sleep=lambda _s: None)
    fetch = ranged_fetcher(ThrottlingClient(), p, interval="1day")
    fetch("RELIND", date(2026, 8, 24), date(2026, 8, 26))
    assert p.rejections == 1
    assert p.interval > 1.0
