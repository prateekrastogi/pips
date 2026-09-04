"""QC runner over bronze, and the seeded-corruption verify (§6 M5).

§6 M5's Verify is "seeded corrupt fixtures caught". Not "the checks pass in isolation" —
end to end, from a bronze record on disk to a quarantine entry with a reason. A check suite
that has only been exercised through its own unit tests has never met the parsing, the
normalization or the file layout it will actually run against.

The other property here is that quarantine **retains**. A record that fails QC is moved with
its reason attached, never dropped: the corrupt record is the evidence for the corruption, and
deleting it makes the finding unverifiable.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pytest
import yaml

from pips.data.qc import runner as runner_module
from pips.data.qc.checks import Finding, Severity
from pips.data.qc.runner import (
    CORRUPTIONS,
    main,
    run_qc,
    seed_corrupt_bronze,
    seed_two_sessions,
)


@pytest.fixture
def clean(tmp_path: Path) -> Path:
    seed_corrupt_bronze(tmp_path / "bronze", corruption=None)
    return tmp_path


def test_a_clean_session_passes(clean: Path) -> None:
    # The control. Without it, a runner that quarantined everything would "catch" every
    # seeded corruption and look perfect.
    report = run_qc(clean / "bronze", clean / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    assert report.findings == []
    assert report.quarantined == 0
    assert report.checked == 1


@pytest.mark.parametrize("corruption", sorted(CORRUPTIONS))
def test_every_seeded_corruption_is_caught(tmp_path: Path, corruption: str) -> None:
    seed_corrupt_bronze(tmp_path / "bronze", corruption=corruption)
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    assert report.findings, f"seeded corruption {corruption!r} was not caught"
    # Which check should catch which corruption, stated explicitly. Requiring the names to
    # coincide would have forced a check per corruption, and an empty session is genuinely
    # a coverage problem rather than a category of its own.
    expected = {"empty": "session_coverage"}.get(corruption, corruption)
    assert expected in {f.check for f in report.findings}, (
        f"{corruption!r} was caught, but by {sorted({f.check for f in report.findings})} "
        f"rather than {expected!r}"
    )


def test_a_quarantined_record_is_moved_with_its_reason(tmp_path: Path) -> None:
    seed_corrupt_bronze(tmp_path / "bronze", corruption="bar_sanity")
    run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    entries = list((tmp_path / "quarantine").rglob("*.json"))
    assert entries, "a quarantined record must be written, not dropped"
    entry = json.loads(entries[0].read_text())
    assert entry["findings"], "the reason must travel with the record"
    assert entry["source"].endswith(".json")


def test_quarantine_retains_the_original_record(tmp_path: Path) -> None:
    # The corrupt record is the evidence for the corruption. Deleting it makes the finding
    # unverifiable, and a QC report nobody can check is a QC report nobody should trust.
    seed_corrupt_bronze(tmp_path / "bronze", corruption="bar_sanity")
    run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    entry = json.loads(next((tmp_path / "quarantine").rglob("*.json")).read_text())
    assert entry["payload"], "the original payload must be retained"


def test_bronze_is_never_modified_by_qc(tmp_path: Path) -> None:
    # Bronze is append-only and raw (§3.4). QC reads it and writes elsewhere; a QC pass that
    # edited bronze would destroy the only unmodified copy of what the vendor actually sent.
    seed_corrupt_bronze(tmp_path / "bronze", corruption="bar_sanity")
    before = {p: p.read_bytes() for p in (tmp_path / "bronze").rglob("*.json")}
    run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    after = {p: p.read_bytes() for p in (tmp_path / "bronze").rglob("*.json")}
    assert before == after


def test_a_key_absent_from_the_manifest_is_reported_as_unfetched(tmp_path: Path) -> None:
    # The cross-check that only exists because M4 kept the manifest: bronze alone cannot tell
    # "nothing traded" from "we never got an answer".
    seed_corrupt_bronze(tmp_path / "bronze", corruption="empty")
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys=set())
    assert any("not fetched" in f.detail.lower() for f in report.findings)


def test_the_report_is_reportable(tmp_path: Path) -> None:
    seed_corrupt_bronze(tmp_path / "bronze", corruption="spike")
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    summary = report.describe()
    assert "checked" in summary and "quarantined" in summary


def test_coverage_is_measured_against_the_real_session_not_the_fixture(tmp_path: Path) -> None:
    """A truncated REAL session must be caught.

    This was vacuous on real data. `run_qc` passed `expected_minutes=len(_rows())` — the seed
    fixture's 30 minutes — so a genuine 375-minute session arriving with 50 bars scored 50/30
    and sailed through. QC ran against the first six real records, reported zero findings, and
    the number was meaningless for this check.

    Caught by asking why a pass was a pass, not by a failure. The expectation now comes from
    the exchange calendar, so it describes the session rather than the test data.
    """
    import json
    import time

    rows = [
        {
            "datetime": f"2026-08-28 {9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00",
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.1,
            "volume": 10,
        }
        for i in range(50)  # 50 of ~375: badly truncated
    ]
    directory = tmp_path / "bronze" / "REAL" / "2026-08-28"
    directory.mkdir(parents=True)
    (directory / f"{time.time_ns()}.json").write_text(
        json.dumps(
            {
                "request": {"symbol": "REAL", "trade_date": "2026-08-28", "interval": "1minute"},
                "received_at_ns": time.time_ns(),
                "payload": {"Status": 200, "Success": rows},
            }
        )
    )
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"REAL:2026-08-28"})
    assert any(f.check == "session_coverage" for f in report.findings), (
        "50 bars of a 375-minute session must be flagged as truncated"
    )


def test_a_full_real_session_is_not_flagged(tmp_path: Path) -> None:
    # The control for the above. The M3 probe measured a real session at 370 of 375 minutes,
    # because untraded minutes are omitted — so the floor must sit well below that.
    import json
    import time

    rows = [
        {
            "datetime": f"2026-08-28 {9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00",
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.1,
            "volume": 10,
        }
        for i in range(370)
    ]
    directory = tmp_path / "bronze" / "REAL" / "2026-08-28"
    directory.mkdir(parents=True)
    (directory / f"{time.time_ns()}.json").write_text(
        json.dumps(
            {
                "request": {"symbol": "REAL", "trade_date": "2026-08-28", "interval": "1minute"},
                "received_at_ns": time.time_ns(),
                "payload": {"Status": 200, "Success": rows},
            }
        )
    )
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"REAL:2026-08-28"})
    assert not [f for f in report.findings if f.check == "session_coverage"]


def test_every_check_the_suite_defines_is_actually_run() -> None:
    """A check that exists, is unit-tested, and never runs is worth nothing.

    `check_unexplained_ratio_jump` was exactly that: written at M5, tested in isolation, and
    never called by the runner. It was found by accident while rewiring it to the M6
    corporate-action master — nothing pointed at it, because a suite of six passing checks and
    a suite of seven where one is dead look identical from the outside.

    This is the same shape as the coverage check that compared against the fixture's own row
    count: a green that means nothing looks exactly like a green that means everything.
    """
    from pips.data.qc import checks as checks_module

    runner_source = Path(runner_module.__file__).read_text(encoding="utf-8")
    defined = {n for n in checks_module.__all__ if n.startswith("check_")}
    unused = sorted(n for n in defined if n not in runner_source)
    assert not unused, (
        f"{unused} are defined in the check suite but never called by the runner — they "
        "cannot fail on real data, so they protect nothing"
    )


def test_a_split_shaped_jump_between_consecutive_sessions_is_quarantined(tmp_path: Path) -> None:
    seed_two_sessions(tmp_path / "bronze", second_open_paise=50_000, first_close_paise=100_000)
    report = run_qc(
        tmp_path / "bronze",
        tmp_path / "quarantine",
        fetched_keys={"CLEAN:2026-08-27", "CLEAN:2026-08-28"},
        calendar_path=Path("config/calendars/nse_equity.yaml"),
    )
    assert any(f.check == "ratio_jump" for f in report.findings), (
        f"a 2x overnight jump must be quarantined; got {[f.check for f in report.findings]}"
    )


def test_a_jump_across_a_gap_is_not_treated_as_overnight(tmp_path: Path) -> None:
    """The false positive this guard exists to prevent.

    Bronze is not guaranteed contiguous — a backfill can be partial, and a symbol can be
    missing days. Comparing a close from a week ago against today's open produces a ratio that
    means nothing, and quarantining on it would train everyone to ignore the finding.
    """
    seed_two_sessions(
        tmp_path / "bronze",
        second_open_paise=50_000,
        first_close_paise=100_000,
        first_day=date(2026, 8, 20),  # not the preceding trading day
    )
    report = run_qc(
        tmp_path / "bronze",
        tmp_path / "quarantine",
        fetched_keys={"CLEAN:2026-08-20", "CLEAN:2026-08-28"},
        calendar_path=Path("config/calendars/nse_equity.yaml"),
    )
    assert not any(f.check == "ratio_jump" for f in report.findings)


def test_the_cli_path_actually_reaches_the_ratio_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`make qc` must exercise every check, not just `run_qc` in a test.

    Found by running QC on the real VM archive: 6 records, 0 findings — and the number meant
    nothing, because `main()` called `run_qc` WITHOUT a calendar and the ratio check is
    skipped when adjacency cannot be established. The check had moved from "never called" to
    "called only from tests", which is the same vacuous green one layer up.

    So this goes through `main()`, exactly as the Make target does.
    """
    seed_two_sessions(tmp_path / "bronze", first_close_paise=100_000, second_open_paise=50_000)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "backfill-manifest.json").write_text(
        json.dumps({"outcomes": {"CLEAN:2026-08-27": "OK", "CLEAN:2026-08-28": "OK"}}),
        encoding="utf-8",
    )
    assert main([str(tmp_path)]) == 1
    assert "ratio_jump" in capsys.readouterr().out


# ------------------------------------------------- the check's own coverage -------------


def test_the_report_says_how_many_ratio_comparisons_it_actually_made(tmp_path: Path) -> None:
    """ "0 findings" is not a result unless you know what was examined.

    The overnight-ratio check only runs between GENUINELY adjacent sessions, which is correct
    — comparing last week's close to today's open yields a meaningless ratio. But the skips
    were invisible, so a run that compared nothing at all reported exactly the same clean
    line as one that compared everything.

    This matters more than it looks, because the holiday list is empty and unverified. With
    no holidays, `is_trading_day` calls every weekday a trading day — so two sessions really
    separated by a holiday compute as NON-adjacent, and their comparison is skipped. A
    genuine overnight jump across a holiday goes unexamined, in the flattering direction,
    and nothing in the output hints at it.
    """
    seed_two_sessions(tmp_path / "bronze", first_close_paise=100_000, second_open_paise=99_900)
    report = run_qc(
        tmp_path / "bronze",
        tmp_path / "quarantine",
        fetched_keys={"CLEAN:2026-08-27", "CLEAN:2026-08-28"},
        calendar_path=Path("config/calendars/nse_equity.yaml"),
    )
    assert report.ratio_checks_run == 1
    assert report.ratio_checks_skipped == 1, "the first session of a symbol has no predecessor"


def test_a_non_adjacent_pair_is_counted_as_skipped_not_as_examined(tmp_path: Path) -> None:
    seed_two_sessions(
        tmp_path / "bronze",
        first_close_paise=100_000,
        second_open_paise=50_000,
        first_day=date(2026, 8, 20),
    )
    report = run_qc(
        tmp_path / "bronze",
        tmp_path / "quarantine",
        fetched_keys={"CLEAN:2026-08-20", "CLEAN:2026-08-28"},
        calendar_path=Path("config/calendars/nse_equity.yaml"),
    )
    assert report.ratio_checks_run == 0
    assert report.ratio_checks_skipped == 2
    assert not any(f.check == "ratio_jump" for f in report.findings)


def test_the_cli_reports_coverage_and_warns_about_the_unverified_holiday_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_two_sessions(tmp_path / "bronze", first_close_paise=100_000, second_open_paise=99_900)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "backfill-manifest.json").write_text(
        json.dumps({"outcomes": {"CLEAN:2026-08-27": "OK", "CLEAN:2026-08-28": "OK"}}),
        encoding="utf-8",
    )
    # The repo calendar's holidays are SOURCED since 2026-09-05, so it no longer triggers this
    # warning -- correctly. The warning is about an UNVERIFIED list, so the test supplies one
    # rather than being deleted: strip the holidays and their provenance into a temp calendar.
    shipped = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2] / "config" / "calendars" / "nse_equity.yaml"
        ).read_text(encoding="utf-8")
    )
    shipped.update(
        holidays=[],
        holidays_source=None,
        holidays_verified_on=None,
        holidays_covering_start=None,
        holidays_covering_end=None,
    )
    # `main` resolves its calendar RELATIVELY ("config/calendars/nse_equity.yaml"), so placing
    # an unverified copy at that path under a chdir is enough -- no CLI flag needed, and no
    # patching of module internals.
    bare = tmp_path / "config" / "calendars"
    bare.mkdir(parents=True, exist_ok=True)
    (bare / "nse_equity.yaml").write_text(yaml.safe_dump(shipped, sort_keys=False), "utf-8")
    monkeypatch.chdir(tmp_path)

    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "overnight-ratio comparisons" in out
    assert "holiday list" in out, (
        "an unverified holiday list makes real adjacent sessions look non-adjacent, so the "
        "run must say so rather than presenting its coverage as complete"
    )


# --------------------------------------------------------- found by mutation sweep ---


def _quarantine_records(root: Path) -> list[dict[str, object]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.rglob("*.json"))]


def test_a_rate_limited_record_is_quarantined_as_a_rate_limit(tmp_path: Path) -> None:
    """The right verdict for the wrong reason is not the right verdict.

    Breeze puts the rejection in the BODY, not the HTTP status, so a throttled fetch is a 200
    carrying no candles. Delete the rate-limit branch and the record still gets quarantined —
    by the coverage check, as "truncated response rather than thin trading". The archive then
    records a data problem where there was a quota problem, and the backfill that caused it
    reads as clean.
    """
    day = date(2026, 8, 28)
    path = tmp_path / "bronze" / "CLEAN" / day.isoformat() / "1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "request": {"symbol": "CLEAN", "trade_date": day.isoformat()},
                "received_at_ns": 1,
                "payload": {"Success": None, "Status": 5, "Error": "API rate limit exceeded"},
            }
        ),
        encoding="utf-8",
    )

    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})

    assert report.quarantined == 1
    assert {f.check for f in report.findings} == {"rate_limited"}, (
        "a quota rejection must not be recorded as a data problem"
    )


def test_the_quarantine_record_carries_the_severity_and_when_it_was_written(
    tmp_path: Path,
) -> None:
    """The reason travels with the record, and so does its weight and its date.

    A severity of "" makes every finding equally loud, and a `quarantined_at_ns` of 0 dates
    the quarantine to 1970 — the same falsified provenance `[C-SILVER-01]` refuses for bars,
    for the same reason: an epoch stamp is not "unknown", it is early, and it sorts and
    filters as though it were.
    """
    seed_corrupt_bronze(tmp_path / "bronze", corruption="bar_sanity")
    before = time.time_ns()
    run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    after = time.time_ns()

    records = _quarantine_records(tmp_path / "quarantine")
    assert len(records) == 1
    stamp = records[0]["quarantined_at_ns"]
    assert isinstance(stamp, int) and before <= stamp <= after, (
        f"quarantined_at_ns {stamp} is not a time this run could have written"
    )
    findings = records[0]["findings"]
    assert isinstance(findings, list) and findings
    assert {f["severity"] for f in findings} == {"QUARANTINE"}


def test_a_warn_only_record_is_not_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quarantine is for QUARANTINE findings, and the distinction is dormant, not absent.

    Every check ships QUARANTINE today, so `if findings:` and `if any(... QUARANTINE ...)`
    behave identically and nothing notices the difference. That is exactly when the semantics
    are cheapest to pin: the first WARN check anyone adds would otherwise start pulling
    records out of the archive, and it would look like the check working.
    """
    seed_corrupt_bronze(tmp_path / "bronze", corruption=None)
    monkeypatch.setattr(
        runner_module,
        "check_bar_sanity",
        lambda bars: [Finding("noticed", Severity.WARN, "worth a look, not a quarantine")],
    )

    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})

    assert [f.check for f in report.findings] == ["noticed"], "the finding is still reported"
    assert report.quarantined == 0, "but it does not pull the record"
    assert _quarantine_records(tmp_path / "quarantine") == []


def test_without_a_calendar_the_ratio_check_is_skipped_not_crashed(tmp_path: Path) -> None:
    """Adjacency needs a calendar; absence of one is a skip with a count, not an exception.

    `_previous_trading_day` takes a calendar, so dropping the `calendar is not None` guard
    does not weaken the check — it raises AttributeError the first time two sessions of one
    symbol appear, which is the normal case on real bronze.
    """
    seed_two_sessions(tmp_path / "bronze", first_close_paise=10_000, second_open_paise=5_000)

    report = run_qc(
        tmp_path / "bronze",
        tmp_path / "quarantine",
        fetched_keys={"CLEAN:2026-08-27", "CLEAN:2026-08-28"},
        calendar_path=None,
    )

    assert report.ratio_checks_run == 0
    assert report.ratio_checks_skipped == 2
    assert "ratio_jump" not in {f.check for f in report.findings}


def test_the_close_carried_into_tomorrow_is_the_sessions_last_bar(tmp_path: Path) -> None:
    """Not its first.

    The seeder ramps a cent a minute and then sets the closing bar, so the first bar's close
    sits 10 paise above the last one's. Carrying the wrong one forward shifts every overnight
    ratio by the intraday move — small enough to keep looking plausible, and enough to walk a
    genuine 1:2 split out of tolerance or an ordinary night into it.
    """
    seed_two_sessions(tmp_path / "bronze", first_close_paise=10_000, second_open_paise=5_000)

    report = run_qc(
        tmp_path / "bronze",
        tmp_path / "quarantine",
        fetched_keys={"CLEAN:2026-08-27", "CLEAN:2026-08-28"},
        calendar_path=Path("config/calendars/nse_equity.yaml"),
    )

    jumps = [f for f in report.findings if f.check == "ratio_jump"]
    assert len(jumps) == 1
    assert "ratio 2.000" in jumps[0].detail, (
        f"expected the last bar's 10000 paise close over 5000, got {jumps[0].detail!r}"
    )
