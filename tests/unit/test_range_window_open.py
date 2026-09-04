"""A ranged DAILY fetch must include its first day.

MEASURED on the live API, 2026-09-05, three overlapping windows on RELIND at `1day`:

    ask 2026-08-25..2026-08-29 -> ['2026-08-26', '2026-08-27', '2026-08-28']   (25 missing)
    ask 2026-08-24..2026-08-29 -> ['2026-08-25', ..., '2026-08-28']            (24 missing)
    ask 2026-08-21..2026-08-26 -> ['2026-08-24', '2026-08-25', '2026-08-26']   (21 missing)

The `from_date` day is dropped every time and `to_date` is kept. None of the missing days is an
NSE holiday — checked against NSE's own cash-market list, which is now in the calendar.

CAUSE. `ist_range` opens the window at **09:15**, the session open, which is right for intraday
bars. A DAILY bar is stamped **00:00:00** — visible in every archived record — so it falls before
09:15 and the vendor excludes it. The end day survives only because the window closes at 15:30,
after that day's 00:00 stamp. An off-by-one made of a timestamp convention, not of arithmetic.

`ist_range`'s own docstring warned about exactly this: "**The multi-day span itself is
UNVERIFIED.** SAL-0002 established the timestamp convention on single-session windows; nobody has
asked this vendor for three years in one call." It could not have been found without asking.

BLAST RADIUS. Every ranged daily fetch, which is every symbol in the 2026-09-04 universe seed:
3,101 symbols, each missing 2023-09-04 (a Monday, and not a holiday).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from pips.data.breeze.budget import CallBudget
from pips.data.breeze.client import ranged_fetcher
from pips.data.breeze.probe import ist_range, range_open_time


def test_a_daily_window_opens_at_midnight_not_at_the_session_open() -> None:
    """The daily bar is stamped 00:00, so 09:15 is after it."""
    assert range_open_time("1day") == "00:00"


@pytest.mark.parametrize("interval", ["1minute", "5minute", "30minute", "1second"])
def test_an_intraday_window_still_opens_at_the_session_open(interval: str) -> None:
    """Widening intraday to midnight would pull in PRE-OPEN prints.

    That is the opposite error and a worse one: `normalize_candles` clips them out again, so the
    damage would be silent rather than visible as missing bars. The fix must not trade one for
    the other.
    """
    assert range_open_time(interval) == "09:15"


def test_the_daily_range_contains_its_own_first_day() -> None:
    frm, to = ist_range(date(2023, 9, 4), date(2026, 9, 3), open_at=range_open_time("1day"))
    assert frm == "2023-09-04T00:00:00.000Z", frm
    assert to == "2026-09-03T15:30:00.000Z", to
    # The bar this window exists to include is stamped exactly at its opening instant.
    assert frm.startswith("2023-09-04T00:00")


def test_the_fetcher_actually_uses_it() -> None:
    """The wiring, not just the helper.

    A correct `range_open_time` that no caller consults is the failure this project keeps
    finding: a fix that exists and is unreachable. So the assertion is on what the CLIENT is
    handed.
    """
    seen: dict[str, Any] = {}

    class FakeClient:
        def get_historical_data_v2(self, **kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"Success": [], "Status": 200, "Error": None}

    class FreeBudget(CallBudget):
        def __init__(self) -> None:  # no config, no state file, no pacing
            pass

        def acquire(self) -> None:
            return None

    fetch = ranged_fetcher(FakeClient(), FreeBudget(), interval="1day")
    fetch("RELIND", date(2026, 8, 25), date(2026, 8, 29))
    assert seen["from_date"] == "2026-08-25T00:00:00.000Z", seen["from_date"]
    assert seen["to_date"] == "2026-08-29T15:30:00.000Z", seen["to_date"]


def test_an_intraday_fetcher_is_not_widened_by_the_fix() -> None:
    seen: dict[str, Any] = {}

    class FakeClient:
        def get_historical_data_v2(self, **kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"Success": [], "Status": 200, "Error": None}

    class FreeBudget(CallBudget):
        def __init__(self) -> None:
            pass

        def acquire(self) -> None:
            return None

    fetch = ranged_fetcher(FakeClient(), FreeBudget(), interval="1minute")
    fetch("RELIND", date(2026, 8, 25), date(2026, 8, 29))
    assert seen["from_date"] == "2026-08-25T09:15:00.000Z", seen["from_date"]
