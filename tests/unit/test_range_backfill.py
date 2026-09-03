"""Range-spanning backfill: one call covering many sessions  (§6 M4).

The per-symbol-day fetcher is right for 1-minute data — 375 candles fill a call, and a manifest
keyed per symbol-day makes a resume granular. It is wrong for everything coarser: the per-day
toll is paid whatever the interval, so three years of DAILY bars costs 782 calls per symbol and
returns one candle for each. The vendor allows <=1,000 candles over an arbitrary range, which
makes the same three years **one call**. That gap is the entire cost of a universe seed.

**Unverified against the live API, deliberately and on the record.** `ist_window` exists because
SAL-0002 found that Breeze reads these timestamps as IST and *silently clips* a UTC window rather
than erroring — the mistake shows up as missing bars, not as a failure. A multi-day window has
never been tried, so it may clip too, or cap below 1,000 candles. These tests fix the SHAPE of
the request and the accounting around it; only a live probe can confirm the vendor honours it,
and the manifest is what makes that probe cheap to repeat.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data.breeze.backfill import (
    CANDLES_PER_CALL,
    Manifest,
    RangeTruncatedError,
    run_range_backfill,
)
from pips.data.breeze.budget import DailyBudgetExceededError
from pips.data.breeze.probe import ist_range

START, END = date(2023, 9, 1), date(2026, 8, 31)
SYMBOLS = ["RELIND", "ICIBAN"]

OK = {
    "Status": 200,
    "Success": [
        {"datetime": "2026-08-28", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}
    ],
}
EMPTY = {"Status": 200, "Success": []}
RATE = {"Status": 5, "Error": "Limit exceed: please try after some time.", "Success": None}
ERROR = {"Status": 500, "Error": "upstream exploded"}


class FakeRangeFetcher:
    def __init__(self, replies: dict[str, object] | None = None, default: object = OK) -> None:
        self.replies = replies or {}
        self.default = default
        self.calls: list[tuple[str, date, date]] = []

    def __call__(self, symbol: str, start: date, end: date) -> object:
        self.calls.append((symbol, start, end))
        return self.replies.get(symbol, self.default)


def test_the_window_spans_the_whole_range_in_ist() -> None:
    """One request, opening bell of the first session to closing bell of the last.

    Same wall-clock convention as `ist_window`, because it is the same vendor quirk: these are
    read as IST and a UTC window is clipped in silence.
    """
    frm, to = ist_range(START, END)
    assert frm == "2023-09-01T09:15:00.000Z"
    assert to == "2026-08-31T15:30:00.000Z"


def test_one_call_per_symbol_covers_the_whole_range(tmp_path: Path) -> None:
    """The point of the exercise: 2 symbols x 3 years = 2 calls, not 1,564."""
    fetcher = FakeRangeFetcher()
    result = run_range_backfill(
        SYMBOLS, START, END, "1day", fetcher, tmp_path / "bronze", tmp_path / "m.json"
    )
    assert [c[0] for c in fetcher.calls] == SYMBOLS
    assert all(c[1:] == (START, END) for c in fetcher.calls)
    assert result.fetched == 2
    assert result.complete


def test_the_record_carries_the_range_it_covers_and_no_trade_date(tmp_path: Path) -> None:
    """A range record has no single trading day, which is why promotion had to learn to
    quarantine a shape it cannot read rather than raising KeyError over it."""
    run_range_backfill(
        ["RELIND"], START, END, "1day", FakeRangeFetcher(), tmp_path / "bronze", tmp_path / "m.json"
    )
    written = list((tmp_path / "bronze").rglob("*.json"))
    assert len(written) == 1
    record = json.loads(written[0].read_text())
    assert record["request"] == {
        "symbol": "RELIND",
        "interval": "1day",
        "from": START.isoformat(),
        "to": END.isoformat(),
    }
    assert "trade_date" not in record["request"]
    assert record["payload"] == OK
    assert record["received_at_ns"] > 0


def test_a_finished_range_costs_no_calls_on_a_rerun(tmp_path: Path) -> None:
    """The same promise the per-day campaign makes, at a coarser grain."""
    first = FakeRangeFetcher()
    run_range_backfill(SYMBOLS, START, END, "1day", first, tmp_path / "bronze", tmp_path / "m.json")
    second = FakeRangeFetcher()
    result = run_range_backfill(
        SYMBOLS, START, END, "1day", second, tmp_path / "bronze", tmp_path / "m.json"
    )
    assert second.calls == []
    assert result.skipped == 2


def test_a_different_interval_or_range_is_a_different_key(tmp_path: Path) -> None:
    """Otherwise a daily seed would mark a 1-second seed done, and the archive would hold
    neither while the manifest claimed both."""
    fetcher = FakeRangeFetcher()
    args = (["RELIND"], START, END)
    run_range_backfill(*args, "1day", fetcher, tmp_path / "bronze", tmp_path / "m.json")
    run_range_backfill(*args, "1second", fetcher, tmp_path / "bronze", tmp_path / "m.json")
    run_range_backfill(
        ["RELIND"],
        START,
        date(2026, 8, 30),
        "1day",
        fetcher,
        tmp_path / "bronze",
        tmp_path / "m.json",
    )
    assert len(fetcher.calls) == 3
    assert len(Manifest.load(tmp_path / "m.json").outcomes) == 3


def test_a_rate_limited_range_is_not_marked_done(tmp_path: Path) -> None:
    """The rule the whole module exists for, at range grain: marking it done would record a
    three-year hole that no later QC can tell from a delisted name."""
    fetcher = FakeRangeFetcher(replies={"RELIND": RATE})
    result = run_range_backfill(
        SYMBOLS, START, END, "1day", fetcher, tmp_path / "bronze", tmp_path / "m.json"
    )
    assert result.stopped_on_rate_limit
    assert len(fetcher.calls) == 1, "the run stops rather than collecting more rejections"
    assert not Manifest.load(tmp_path / "m.json").is_done_range("RELIND", "1day", START, END)
    assert list((tmp_path / "bronze").rglob("*.json")) == []


def test_an_errored_range_is_not_marked_and_writes_no_bronze(tmp_path: Path) -> None:
    fetcher = FakeRangeFetcher(replies={"RELIND": ERROR})
    result = run_range_backfill(
        SYMBOLS, START, END, "1day", fetcher, tmp_path / "bronze", tmp_path / "m.json"
    )
    assert result.errored == 1
    assert result.fetched == 1, "the other symbol still ran"
    assert not result.complete
    assert not Manifest.load(tmp_path / "m.json").is_done_range("RELIND", "1day", START, END)
    assert len(list((tmp_path / "bronze").rglob("*.json"))) == 1


def test_an_empty_range_is_an_answer_and_is_marked(tmp_path: Path) -> None:
    """A name that did not trade in three years is delisted or never listed — a real answer,
    and the record is the evidence we asked."""
    fetcher = FakeRangeFetcher(default=EMPTY)
    result = run_range_backfill(
        ["RELIND"], START, END, "1day", fetcher, tmp_path / "bronze", tmp_path / "m.json"
    )
    assert result.empty == 1
    assert Manifest.load(tmp_path / "m.json").is_done_range("RELIND", "1day", START, END)
    assert len(list((tmp_path / "bronze").rglob("*.json"))) == 1


def test_budget_exhaustion_stops_the_range_run_cleanly(tmp_path: Path) -> None:
    class Budgeted(FakeRangeFetcher):
        def __call__(self, symbol: str, start: date, end: date) -> object:
            self.calls.append((symbol, start, end))
            if len(self.calls) > 1:
                raise DailyBudgetExceededError("out of budget")
            return OK

    fetcher = Budgeted()
    # THREE symbols, not two: with only two, `continue` and `break` both end the loop after the
    # second call and the fixture cannot tell a clean stop from a grind. A budgeted run that
    # continues asks the fetcher once per remaining symbol -- 1,800 times on the real seed.
    result = run_range_backfill(
        [*SYMBOLS, "TCSLTD"], START, END, "1day", fetcher, tmp_path / "bronze", tmp_path / "m.json"
    )
    assert result.stopped_on_budget
    assert len(fetcher.calls) == 2, "one call discovers the limit; none follow it"
    assert result.fetched == 1


def test_a_range_backfill_refuses_to_write_into_the_repository(tmp_path: Path) -> None:
    """Rule 14, on the new path too — a guard that only covers the old one is not a guard."""
    with pytest.raises(ValueError, match="rule 14"):
        run_range_backfill(
            ["RELIND"],
            START,
            END,
            "1day",
            FakeRangeFetcher(),
            Path("data/bronze"),
            tmp_path / "m.json",
        )


def test_an_inverted_range_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="before start"):
        run_range_backfill(
            ["RELIND"],
            END,
            START,
            "1day",
            FakeRangeFetcher(),
            tmp_path / "bronze",
            tmp_path / "m.json",
        )


def test_the_ranged_fetcher_asks_for_one_window_and_pays_one_call(tmp_path: Path) -> None:
    """It is the budget that makes this worth building: one acquire, not 782.

    `budgeted_fetcher` calls `budget.acquire()` per symbol-day. Its range counterpart calls it
    once per symbol, which is what turns a 15.6-quota-day seed into a 0.02-quota-day one — and
    the pacing still applies, because the vendor's per-minute limit does not care how many
    candles a call returns.
    """
    from pips.data.breeze.budget import CallBudget
    from pips.data.breeze.client import ranged_fetcher

    asked: dict[str, object] = {}

    class FakeClient:
        def get_historical_data_v2(self, **kw: object) -> object:
            asked.update(kw)
            return OK

    budget = CallBudget(
        100, 75, 32, tmp_path / "s.json", "2026-09-03", lambda _s: None, lambda: 0.0
    )
    fetch = ranged_fetcher(FakeClient(), budget, interval="1day")
    assert fetch("RELIND", START, END) == OK

    assert budget.calls_made == 1, "a three-year range is one call"
    assert asked["interval"] == "1day"
    assert asked["from_date"] == "2023-09-01T09:15:00.000Z"
    assert asked["to_date"] == "2026-08-31T15:30:00.000Z"
    assert asked["stock_code"] == "RELIND"


def test_the_ranged_fetcher_stops_when_the_budget_is_spent(tmp_path: Path) -> None:
    """Same clean stop as the per-day fetcher, so `run_range_backfill` can resume tomorrow."""
    from pips.data.breeze.budget import CallBudget
    from pips.data.breeze.client import ranged_fetcher

    class FakeClient:
        def get_historical_data_v2(self, **_kw: object) -> object:
            return OK

    budget = CallBudget(1, 75, 32, tmp_path / "s.json", "2026-09-03", lambda _s: None, lambda: 0.0)
    fetch = ranged_fetcher(FakeClient(), budget, interval="1day")
    with pytest.raises(DailyBudgetExceededError):
        fetch("RELIND", START, END)


# ------------------------------------------------- found by the live probe (2026-09-03) ---


def test_a_reply_at_the_candle_cap_is_refused_as_probably_truncated(tmp_path: Path) -> None:
    """The vendor drops the OLDEST bars at the cap, silently, with Status 200 and no Error.

    Measured, not assumed. Asked for three days of 1-minute bars from 09:15 on the 24th and got
    exactly 1,000 candles beginning **11:07 on the 24th** — 1,125 requested, 1,000 is the
    documented cap, and the first 125 were simply absent. `classify_response` reads that as OK
    because it is a 200 carrying rows, so `run_range_backfill` would mark the range done and
    record a hole at its start that no later QC can distinguish from a quiet market.

    A range that genuinely contains exactly the cap is indistinguishable from one that was
    truncated, which is why this refuses rather than guesses — and why it raises rather than
    retrying: the same range will truncate identically next time. The fix is a narrower range,
    which is the caller's to choose.
    """
    at_cap = {
        "Status": 200,
        "Success": [{"datetime": f"2026-08-24 {i}", "close": 1.0} for i in range(CANDLES_PER_CALL)],
    }
    fetcher = FakeRangeFetcher(default=at_cap)

    with pytest.raises(RangeTruncatedError, match="1000"):
        run_range_backfill(
            ["RELIND"], START, END, "1minute", fetcher, tmp_path / "bronze", tmp_path / "m.json"
        )

    assert list((tmp_path / "bronze").rglob("*.json")) == [], "nothing is stored"
    assert Manifest.load(tmp_path / "m.json").outcomes == {}, "and nothing is marked done"


def test_a_reply_below_the_cap_is_a_complete_range(tmp_path: Path) -> None:
    """The seed shape, and the reason the cheap plan works.

    Three years of DAILY bars came back as 742 candles for one call — comfortably under the cap,
    so the range was served whole. That is the case the universe seed depends on and it must not
    be caught by the guard above.
    """
    under_cap = {
        "Status": 200,
        "Success": [{"datetime": f"2023-09-{i:02d}", "close": 1.0} for i in range(1, 29)],
    }
    fetcher = FakeRangeFetcher(default=under_cap)

    result = run_range_backfill(
        ["RELIND"], START, END, "1day", fetcher, tmp_path / "bronze", tmp_path / "m.json"
    )

    assert result.fetched == 1
    assert Manifest.load(tmp_path / "m.json").is_done_range("RELIND", "1day", START, END)
