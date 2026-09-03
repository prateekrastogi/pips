"""`run_qc` notices the sessions that are not there (§6 M5, `[C-QC-01]`).

The pure check is tested in `test_calendar_gaps.py`. What is tested here is that the QC pass
actually runs it — and, when it cannot, says so instead of printing the same clean line.

That distinction is already the house style in this module: `QcReport` counts
`ratio_checks_run` and `ratio_checks_skipped` because *"0 findings is not a result unless you
know what was examined: a run that compared nothing prints the same clean line as one that
compared everything."* A calendar-gap check with no calendar is exactly that case.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pips.data.qc.runner import run_qc, seed_two_sessions

ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "config" / "calendars" / "nse_equity.yaml"

# 2026-08-27 Thu and 2026-08-31 Mon, so 2026-08-28 Fri is a trading day between them with
# nothing in the archive. The weekend either side of it is not.
FIRST, SECOND = date(2026, 8, 27), date(2026, 8, 31)
KEYS = {f"RELIND:{FIRST.isoformat()}", f"RELIND:{SECOND.isoformat()}"}


def test_a_trading_day_between_two_records_is_reported_as_a_gap(tmp_path: Path) -> None:
    """The hole QC could not previously see. Both records are clean, both pass every per-record
    check, and the session between them was never fetched."""
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)

    report = run_qc(bronze, tmp_path / "q", KEYS, calendar_path=CALENDAR)

    gaps = [f for f in report.findings if f.check == "calendar_gap"]
    assert [f.label for f in gaps] == ["2026-08-28"]


def test_a_complete_span_reports_no_gaps_but_says_what_it_examined(tmp_path: Path) -> None:
    """ "No gaps" has to be distinguishable from "nothing was looked at"."""
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=date(2026, 8, 28))

    report = run_qc(
        bronze,
        tmp_path / "q",
        {f"RELIND:{FIRST.isoformat()}", "RELIND:2026-08-28"},
        calendar_path=CALENDAR,
    )

    assert [f for f in report.findings if f.check == "calendar_gap"] == []
    assert report.calendar_days_examined == 2
    assert "calendar days examined 2" in report.describe()


def test_without_a_calendar_the_gap_check_is_reported_as_not_run(tmp_path: Path) -> None:
    """The failure this whole tick is about, one level up.

    With no calendar there is no way to tell a trading day from a holiday, so the check cannot
    run. Skipping it silently would make a run that examined nothing print the same clean
    calendar line as one that examined three years — which is how the missing check went
    unnoticed for a milestone in the first place.
    """
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)

    report = run_qc(bronze, tmp_path / "q", KEYS)

    assert report.calendar_days_examined == 0
    assert "not checked" in report.describe()


def test_the_span_examined_is_what_the_archive_covers_and_the_report_says_so(
    tmp_path: Path,
) -> None:
    """A stated limitation, not a hidden one.

    The span comes from the records present, so a hole BEFORE the first record or AFTER the
    last is outside what the archive can self-report — nothing in it knows the range that was
    requested. Reporting the number of days examined is what lets a reader see the edge of the
    check rather than trusting its silence; closing that edge needs the campaign's range, which
    `run_qc` is not given.
    """
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)

    report = run_qc(bronze, tmp_path / "q", KEYS, calendar_path=CALENDAR)

    # Thu 27th, Fri 28th, Mon 31st: three trading days spanned, one of them missing.
    assert report.calendar_days_examined == 3


def test_each_symbol_is_compared_against_the_calendar_on_its_own(tmp_path: Path) -> None:
    """One shared set of days would make every symbol's holes disappear into every other's.

    RELIND has Thu the 27th and Mon the 31st, so Fri the 28th is a hole in ITS span. TCS has
    only the 28th. Merged into one set the days are {27, 28, 31} over a span of 27..31 — every
    trading day present, no gaps, and RELIND's hole filled in by another symbol's record.

    The distinction has to be built deliberately. My first attempt gave RELIND {27, 28} and TCS
    {31}, which reports no gaps and three days examined under BOTH behaviours: a fixture too
    tidy to tell the property from its absence, written while testing for exactly that. The
    counts have to differ too — 4 days examined across two spans, not 3 across one.
    """
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)
    seed_two_sessions(
        bronze,
        10_000,
        10_000,
        first_day=date(2026, 8, 28),
        second_day=date(2026, 8, 28),
        symbol="TCS",
    )

    report = run_qc(
        bronze,
        tmp_path / "q",
        KEYS | {"TCS:2026-08-28"},
        calendar_path=CALENDAR,
    )

    gaps = [f.label for f in report.findings if f.check == "calendar_gap"]
    assert gaps == ["2026-08-28"], "RELIND's hole is not filled by TCS's record"
    assert report.calendar_days_examined == 4, "RELIND's three-day span plus TCS's one"
