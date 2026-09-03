"""Sessions missing from the archive entirely (§6 M5, `[C-QC-01]`).

M5's spec promises "calendar gaps" and the code had a coverage RATIO floor instead. Those are
not the same check, and `docs/state/CURRENT.md` had it backwards — it read the difference as
prose overpromising, to be fixed by correcting the prose. The prose is right.

`check_session_coverage` takes one session's bars and asks whether that session is complete. It
is right to use a ratio and not a minute count: Breeze omits untraded minutes, so an exact
count would flag every illiquid session as broken. But it can only run on a session that
EXISTS. `run_qc` iterates `bronze_root.rglob("*.json")`, so a trading day never fetched
contributes no path, no record and no check — the hole is invisible to the entire QC pass. **A
check that never ran, reading as a check that passed**, in the layer whose job is to notice.

Absence of untraded *minutes* is normal. Absence of a whole *session* is not.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.core.calendar import load_calendar
from pips.data.qc.checks import Severity, check_calendar_gaps

ROOT = Path(__file__).resolve().parents[2]
CAL = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")

# 2026-08-31 Mon .. 2026-09-04 Fri, with 09-05/06 the weekend after.
MON, TUE, WED, THU, FRI = (date(2026, 8, 31), *(date(2026, 9, d) for d in (1, 2, 3, 4)))


def test_a_complete_week_reports_nothing() -> None:
    assert check_calendar_gaps({MON, TUE, WED, THU, FRI}, CAL, MON, FRI) == []


def test_a_missing_trading_day_is_reported_and_named() -> None:
    """Named, because a count is not actionable. "one gap" sends someone to diff two lists;
    "2026-09-02 is missing" sends them to re-fetch one day."""
    findings = check_calendar_gaps({MON, TUE, THU, FRI}, CAL, MON, FRI)

    assert len(findings) == 1
    assert findings[0].check == "calendar_gap"
    assert findings[0].label == "2026-09-02"
    assert "2026-09-02" in findings[0].detail


def test_a_missing_session_warns_rather_than_quarantining() -> None:
    """QUARANTINE acts on a record, and a missing session has no record to act on.

    The finding is about the ARCHIVE, not a row: there is nothing to move aside, nothing to
    retain with its reason. Quarantining here would mean inventing a record for a day we never
    saw, which is the one thing bronze must never contain.
    """
    findings = check_calendar_gaps({MON, TUE, THU, FRI}, CAL, MON, FRI)

    assert findings[0].severity is Severity.WARN


def test_a_weekend_is_not_a_gap() -> None:
    """The whole reason this consults the calendar rather than counting days."""
    assert check_calendar_gaps({MON, TUE, WED, THU, FRI}, CAL, MON, date(2026, 9, 6)) == []


def test_a_listed_holiday_is_not_a_gap() -> None:
    calendar = CAL.model_copy(
        update={
            "holidays": [WED],
            "holidays_source": "NSE circular",
            "holidays_verified_on": date(2026, 1, 1),
        }
    )

    assert check_calendar_gaps({MON, TUE, THU, FRI}, calendar, MON, FRI) == []


def test_an_unverified_holiday_list_makes_every_gap_a_maybe() -> None:
    """The shipped calendar lists no holidays, deliberately — so on Diwali this check sees a
    weekday with no data and cannot tell a shut exchange from a hole.

    Reported rather than assumed away, because that is the safe direction: a false gap costs
    someone a look at a calendar, and a missed gap costs a hole in the panel that no later QC
    can find. But the wording must not claim certainty it does not have, and the verified case
    must read differently — otherwise the reader cannot tell which they are looking at.
    """
    assert CAL.holidays_verified is False
    unverified = check_calendar_gaps({MON, TUE, THU, FRI}, CAL, MON, FRI)[0].detail

    verified_cal = CAL.model_copy(
        update={"holidays_source": "NSE circular", "holidays_verified_on": date(2026, 1, 1)}
    )
    verified = check_calendar_gaps({MON, TUE, THU, FRI}, verified_cal, MON, FRI)[0].detail

    assert "unverified" in unverified
    assert "unverified" not in verified
    assert verified != unverified


def test_an_archive_with_nothing_in_it_reports_every_trading_day() -> None:
    """Silence is the failure mode this check exists to prevent, so the empty case is the one
    that must not be silent. A symbol with no data at all is the largest possible hole."""
    findings = check_calendar_gaps(set(), CAL, MON, FRI)

    assert [f.label for f in findings] == [
        "2026-08-31",
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
        "2026-09-04",
    ]


def test_days_outside_the_span_are_not_reported() -> None:
    """The span is the claim being checked. Widening it silently would report every day before
    the archive began as a gap, and a check that cries wolf on its first run is one people
    learn to skip."""
    findings = check_calendar_gaps({WED}, CAL, WED, WED)

    assert findings == []


def test_the_span_includes_both_ends() -> None:
    """Off by one at either end hides a hole on the first or last day of the range."""
    assert [f.label for f in check_calendar_gaps({TUE, WED}, CAL, MON, THU)] == [
        "2026-08-31",
        "2026-09-03",
    ]


def test_gaps_come_back_in_date_order() -> None:
    """Rule 1. A set has no order, and a findings list that inherited one would make two runs
    over the same archive produce different reports."""
    findings = check_calendar_gaps({WED}, CAL, MON, FRI)

    assert [f.label for f in findings] == ["2026-08-31", "2026-09-01", "2026-09-03", "2026-09-04"]


def test_a_backwards_span_is_refused() -> None:
    """Two dates are one typo apart, and an empty findings list would read as "no gaps"."""
    with pytest.raises(ValueError, match="before"):
        check_calendar_gaps({WED}, CAL, FRI, MON)
