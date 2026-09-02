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
from pips.data.breeze.budget import DailyBudgetExceededError
from pips.data.breeze.ingest import ResponseKind

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


# --------------------------------------------------------- found by mutation sweep ---


def test_a_transient_error_writes_no_bronze_and_is_not_counted_as_empty(tmp_path: Path) -> None:
    """An error is not an answer, so it leaves no record and claims no outcome.

    Falling through to the bronze write puts an error body in the data zone and increments
    `empty` — which reads, in the report and in the manifest's absence, as "we asked and there
    was genuinely nothing". The difference between that and "we never got an answer" is the
    one distinction this whole module exists to preserve.
    """
    fetcher = FakeFetcher(default=ERROR)
    result = run_backfill(["RELIND"], [DAYS[0]], fetcher, bronze(tmp_path), tmp_path / "m.json")

    assert result.errored == 1
    assert result.empty == 0
    assert result.fetched == 0
    assert list(bronze(tmp_path).rglob("*.json")) == []
    assert not Manifest.load(tmp_path / "m.json").is_done("RELIND", DAYS[0])


def test_a_holiday_writes_bronze_as_the_evidence_that_we_asked(tmp_path: Path) -> None:
    """EMPTY is an answer, and the record is what makes it one.

    Marking a holiday done with nothing on disk leaves the manifest asserting an outcome no
    later reader can check. `[C-QC-02]`'s coverage check needs exactly this record to tell a
    quiet market from a hole.
    """
    fetcher = FakeFetcher(default=EMPTY)
    result = run_backfill(["RELIND"], [DAYS[0]], fetcher, bronze(tmp_path), tmp_path / "m.json")

    assert result.empty == 1
    records = list(bronze(tmp_path).rglob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["payload"] == EMPTY
    assert Manifest.load(tmp_path / "m.json").outcome("RELIND", DAYS[0]) == "EMPTY"


def test_a_run_with_transient_errors_is_not_complete(tmp_path: Path) -> None:
    """`complete` is what a campaign driver reads to decide whether to run again.

    Errors are deliberately left unmarked so the next run retries them — which is only useful
    if something says a next run is needed.
    """
    errored = BackfillResult(
        attempted=2,
        fetched=1,
        empty=0,
        errored=1,
        skipped=0,
        stopped_on_budget=False,
        stopped_on_rate_limit=False,
    )
    assert not errored.complete
    clean = BackfillResult(
        attempted=2,
        fetched=2,
        empty=0,
        errored=0,
        skipped=0,
        stopped_on_budget=False,
        stopped_on_rate_limit=False,
    )
    assert clean.complete


def test_budget_exhaustion_stops_the_run_rather_than_grinding_through_it(tmp_path: Path) -> None:
    """A clean stop means the fetcher is not asked again.

    Continuing instead of breaking calls the fetcher once per remaining key — 234,900 times
    on the real campaign — each raising the same exception. The run still reports
    `stopped_on_budget`, so the difference is invisible in the result and visible only in the
    hour it takes to finish doing nothing.
    """

    class BudgetedFetcher(FakeFetcher):
        def __call__(self, symbol: str, day: date) -> object:
            self.calls.append((symbol, day))
            if len(self.calls) > 2:
                raise DailyBudgetExceededError("out of budget")
            return OK

    fetcher = BudgetedFetcher()
    result = run_backfill(SYMBOLS, DAYS, fetcher, bronze(tmp_path), tmp_path / "m.json")

    assert result.stopped_on_budget
    assert len(fetcher.calls) == 3, "one call discovers the limit; none follow it"
    assert result.fetched == 2


def test_an_unreadable_manifest_costs_calls_rather_than_leaving_holes(tmp_path: Path) -> None:
    """The documented choice, and the one that is cheap to get backwards.

    Not knowing what is done is recoverable by re-fetching; assuming it is all done writes
    silent holes into the archive. Raising instead would be a third, worse option on a
    multi-day campaign: the manifest is rewritten once per key, so a process killed mid-write
    leaves exactly this file, and aborting there strands the campaign.
    """
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text('{"outcomes": {"RELIND:2026-08-26": "OK"', encoding="utf-8")

    loaded = Manifest.load(manifest_path)
    assert loaded.outcomes == {}, "an unparseable manifest is not a partial manifest"

    fetcher = FakeFetcher()
    result = run_backfill(["RELIND"], [DAYS[0]], fetcher, bronze(tmp_path), manifest_path)
    assert result.fetched == 1, "the campaign continues, paying for what it cannot prove"


def test_a_crash_mid_write_does_not_destroy_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole file is rewritten once per key; each rewrite is a window.

    `write_text` truncates before it writes, so a process killed part-way through leaves a
    truncated manifest — which `load` correctly treats as unreadable and starts empty from.
    On the 3-year x U300 campaign that is 234,900 rewrites and, on the wrong one, the loss of
    every key already paid for: the restart that was supposed to cost zero calls costs all of
    them. The write has to land atomically or not at all.
    """
    path = tmp_path / "m.json"
    manifest = Manifest.load(path)
    manifest.mark("RELIND", DAYS[0], ResponseKind.OK)

    real_write = Path.write_text

    def killed_halfway(self: Path, data: str, **kwargs: object) -> int:
        real_write(self, data[: len(data) // 2], **kwargs)  # type: ignore[arg-type]
        raise OSError("process killed mid-write")

    monkeypatch.setattr(Path, "write_text", killed_halfway)
    with pytest.raises(OSError, match="killed mid-write"):
        manifest.mark("ICIBAN", DAYS[0], ResponseKind.OK)
    monkeypatch.undo()

    recovered = Manifest.load(path)
    assert recovered.is_done("RELIND", DAYS[0]), (
        "the key already paid for must survive a crash while writing the next one"
    )
