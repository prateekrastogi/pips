"""Backfill orchestrator (§6 M4, ported from SAL-0004).

The donor's architecture in one sentence: per key, fetch → classify → write bronze → mark done
in a persisted manifest, so a restart costs zero calls for work already finished.

Its best idea is what it refuses to mark done. A transient error is never marked, so the next
run retries it. pips extends that with the distinction the classification work at M4 made
available, and which the donor could not draw:

| outcome | marked done? | why |
|---|---|---|
| data returned | yes | the work is finished |
| empty (holiday) | yes | attempted, and there is genuinely nothing — a real answer |
| transient error | no | retry next run |
| **rate limited** | **no** | Breeze sends this as HTTP 200 with an empty body, so marking it
  done records a permanent gap indistinguishable from a holiday |

That last row is the whole point. A backfill that marks a rate-limited window "done, no data"
writes a hole into the archive that no later QC can distinguish from a quiet market.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data.breeze.backfill import BackfillResult, Manifest, run_backfill

DAYS = [date(2026, 8, 26), date(2026, 8, 27), date(2026, 8, 28)]
SYMBOLS = ["RELIND", "ICIBAN"]

OK = {
    "Status": 200,
    "Success": [
        {
            "datetime": "2026-08-28 09:15:00",
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1,
        }
    ],
}
EMPTY = {"Status": 200, "Success": []}
RATE = {"Status": 5, "Error": "Limit exceed: please try after some time.", "Success": None}
ERROR = {"Status": 500, "Error": "upstream exploded"}


class FakeFetcher:
    """Returns scripted replies and counts calls. No network, ever."""

    def __init__(
        self, replies: dict[tuple[str, date], object] | None = None, default: object = OK
    ) -> None:
        self.replies = replies or {}
        self.default = default
        self.calls: list[tuple[str, date]] = []

    def __call__(self, symbol: str, day: date) -> object:
        self.calls.append((symbol, day))
        return self.replies.get((symbol, day), self.default)


def bronze(tmp_path: Path) -> Path:
    return tmp_path / "bronze"


# ------------------------------------------------------------------ the happy path ------


def test_it_fetches_every_symbol_day_and_writes_bronze(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    result = run_backfill(SYMBOLS, DAYS, fetcher, bronze(tmp_path), tmp_path / "manifest.json")
    assert len(fetcher.calls) == 6
    assert result.fetched == 6
    assert not result.stopped_on_budget
    assert len(list(bronze(tmp_path).rglob("*.json"))) == 6


def test_bronze_records_the_exact_payload_and_a_receive_timestamp(tmp_path: Path) -> None:
    # §3.4: bronze is "raw, append-only, exact payloads + receive timestamps". A bronze record
    # that has been cleaned is not bronze, and there is then nowhere left to check the
    # cleaning against.
    run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(), bronze(tmp_path), tmp_path / "m.json")
    record = json.loads(next(bronze(tmp_path).rglob("*.json")).read_text())
    assert record["payload"] == OK
    assert record["received_at_ns"] > 0
    assert record["request"]["symbol"] == "RELIND"


def test_bronze_is_append_only_and_a_rerun_does_not_overwrite(tmp_path: Path) -> None:
    b, m = bronze(tmp_path), tmp_path / "m.json"
    run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(), b, m)
    before = next(b.rglob("*.json")).read_text()
    m.unlink()  # force a re-fetch of already-written work
    run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(), b, m)
    assert len(list(b.rglob("*.json"))) == 2, "a second observation is a new record, not an edit"
    assert before in [p.read_text() for p in b.rglob("*.json")]


# ------------------------------------------------------------------ resumability --------


def test_a_restart_costs_zero_calls_for_finished_work(tmp_path: Path) -> None:
    b, m = bronze(tmp_path), tmp_path / "m.json"
    run_backfill(SYMBOLS, DAYS, FakeFetcher(), b, m)
    second = FakeFetcher()
    result = run_backfill(SYMBOLS, DAYS, second, b, m)
    assert second.calls == [], "already-done keys must not be re-fetched"
    assert result.skipped == 6


def test_only_the_unfinished_keys_are_retried(tmp_path: Path) -> None:
    b, m = bronze(tmp_path), tmp_path / "m.json"
    run_backfill(["RELIND"], DAYS, FakeFetcher(), b, m)
    second = FakeFetcher()
    run_backfill(SYMBOLS, DAYS, second, b, m)
    assert {s for s, _ in second.calls} == {"ICIBAN"}


# ------------------------------------------- what may and may not be marked done --------


def test_an_empty_day_is_marked_done_because_it_is_a_real_answer(tmp_path: Path) -> None:
    # A holiday returns Status 200 with no rows. That is information, not a failure, and
    # re-fetching it every run would burn the budget on days that will never have data.
    b, m = bronze(tmp_path), tmp_path / "m.json"
    run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(default=EMPTY), b, m)
    second = FakeFetcher(default=EMPTY)
    run_backfill(["RELIND"], [DAYS[0]], second, b, m)
    assert second.calls == []


def test_a_transient_error_is_never_marked_done(tmp_path: Path) -> None:
    b, m = bronze(tmp_path), tmp_path / "m.json"
    run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(default=ERROR), b, m)
    second = FakeFetcher()
    run_backfill(["RELIND"], [DAYS[0]], second, b, m)
    assert second.calls == [("RELIND", DAYS[0])], "an error must be retried on the next run"


def test_a_rate_limited_reply_stops_the_run_and_marks_nothing(tmp_path: Path) -> None:
    # The distinction that matters most. Breeze answers HTTP 200 with Status 5 in the body;
    # marking it "done, no data" writes a permanent hole indistinguishable from a holiday.
    b, m = bronze(tmp_path), tmp_path / "m.json"
    fetcher = FakeFetcher(replies={("RELIND", DAYS[1]): RATE})
    result = run_backfill(["RELIND"], DAYS, fetcher, b, m)
    assert result.stopped_on_rate_limit
    assert len(fetcher.calls) == 2, "the run must stop at the rejection, not push on"

    resumed = FakeFetcher()
    run_backfill(["RELIND"], DAYS, resumed, b, m)
    assert ("RELIND", DAYS[1]) in resumed.calls, "the rate-limited key must be retried"


def test_a_rate_limited_key_writes_no_bronze_record(tmp_path: Path) -> None:
    b, m = bronze(tmp_path), tmp_path / "m.json"
    run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(default=RATE), b, m)
    assert list(b.rglob("*.json")) == [], "a rejection is not an observation"


# ------------------------------------------------------------------ budget stop ---------


def test_a_spent_budget_stops_cleanly_and_resumes(tmp_path: Path) -> None:
    from pips.data.breeze.budget import DailyBudgetExceededError

    b, m = bronze(tmp_path), tmp_path / "m.json"
    calls = {"n": 0}

    def stingy(symbol: str, day: date) -> object:
        calls["n"] += 1
        if calls["n"] > 2:
            raise DailyBudgetExceededError("spent")
        return OK

    result = run_backfill(SYMBOLS, DAYS, stingy, b, m)
    assert result.stopped_on_budget
    assert result.fetched == 2
    # Everything completed before the stop stays done; the rest is simply pending.
    resumed = FakeFetcher()
    run_backfill(SYMBOLS, DAYS, resumed, b, m)
    assert len(resumed.calls) == 4


def test_the_manifest_records_why_each_key_finished(tmp_path: Path) -> None:
    # "Done" alone cannot distinguish a day with data from a holiday, and a later reader needs
    # that to tell a real gap from an empty one.
    b, m = bronze(tmp_path), tmp_path / "m.json"
    run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(), b, m)
    run_backfill(["ICIBAN"], [DAYS[0]], FakeFetcher(default=EMPTY), b, m)
    manifest = Manifest.load(m)
    assert manifest.outcome("RELIND", DAYS[0]) == "OK"
    assert manifest.outcome("ICIBAN", DAYS[0]) == "EMPTY"


def test_the_result_is_reportable(tmp_path: Path) -> None:
    result = run_backfill(SYMBOLS, DAYS, FakeFetcher(), bronze(tmp_path), tmp_path / "m.json")
    assert isinstance(result, BackfillResult)
    assert result.attempted == 6


def test_it_refuses_a_bronze_path_inside_the_repository(tmp_path: Path) -> None:
    # Rule 14: ALL market data lives on the VM. A backfill pointed at the working tree would
    # put market data in git, and the mistake is easy to make from a laptop.
    repo_path = Path(__file__).resolve().parents[2] / "data" / "bronze"
    with pytest.raises(ValueError, match="repository"):
        run_backfill(["RELIND"], [DAYS[0]], FakeFetcher(), repo_path, tmp_path / "m.json")
