"""Daily bars get their own panel, beside silver rather than inside it (`BLK-0003`).

Silver is DEFINITIONALLY the one-minute intraday panel: `_INTERVAL_MINUTES = 1`, and its bar
model is `(trade_date, close_label)` with the label clipped to 09:15-15:30. A daily bar has no
intraday close label, and feeding one through `normalize_candles` yields ZERO bars — measured,
2026-09-04. So the seed's 3,101 symbols had no destination at all.

Two traps this module exists to avoid, both found by reading the intraday path:

1. `normalize_candles` IGNORES the candle's own date and stamps every bar with the single
   `trade_date` it is handed. Exploding a three-year range through it would date every bar to
   one day, and every bar would look ordinary. Here the candle's OWN date decides.
2. The vendor code is resolved PER DAY, because a code can point at different instruments over
   three years — which is the whole reason `resolve_vendor_code` takes a date.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, cast

from pips.data.daily import promote_daily

RANGE_RECORD: dict[str, Any] = {
    "request": {
        "symbol": "RELIND",
        "interval": "1day",
        "from": "2026-08-24T00:00:00.000Z",
        "to": "2026-08-26T15:30:00.000Z",
    },
    "received_at_ns": 1788500053085438160,
    "payload": {
        "Status": 200,
        "Error": None,
        "Success": [
            {
                "datetime": "2026-08-24 00:00:00",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000,
                "stock_code": "RELIND",
                "exchange_code": "NSE",
            },
            {
                "datetime": "2026-08-25 00:00:00",
                "open": 105.0,
                "high": 112.0,
                "low": 104.0,
                "close": 111.0,
                "volume": 2000,
                "stock_code": "RELIND",
                "exchange_code": "NSE",
            },
            {
                "datetime": "2026-08-26 00:00:00",
                "open": 111.0,
                "high": 115.0,
                "low": 110.0,
                "close": 114.0,
                "volume": 3000,
                "stock_code": "RELIND",
                "exchange_code": "NSE",
            },
        ],
    },
}


class FakeInstrument:
    def __init__(self, symbol: str, isin: str) -> None:
        self.symbol = symbol
        self.isin = isin


class FakeMaster:
    """Resolves RELIND, and records the dates it was asked about."""

    def __init__(self, resolves: bool = True) -> None:
        self.resolves = resolves
        self.asked: list[date] = []

    def resolve_vendor_code(self, code: str, on: date, *, known_on: date | None) -> Any:
        self.asked.append(on)
        return FakeInstrument("RELIANCE", "INE002A01018") if self.resolves else None


def write(root: Path, record: dict[str, Any], name: str = "r.json") -> Path:
    d = root / "RELIND" / "1day" / "2026-08-24_2026-08-26"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(record), encoding="utf-8")
    return d / name


def test_a_range_record_becomes_one_row_per_day(tmp_path: Path) -> None:
    write(tmp_path / "bronze", RANGE_RECORD)
    master = FakeMaster()
    report = promote_daily(
        tmp_path / "bronze", tmp_path / "daily", cast("Any", master), known_on=date(2026, 9, 5)
    )
    assert report.rows == 3, report.describe()
    assert report.files_promoted == 1


def test_each_bar_keeps_its_own_date(tmp_path: Path) -> None:
    """The trap. `normalize_candles` would stamp all three with one date."""
    write(tmp_path / "bronze", RANGE_RECORD)
    report = promote_daily(
        tmp_path / "bronze",
        tmp_path / "daily",
        cast("Any", FakeMaster()),
        known_on=date(2026, 9, 5),
    )
    assert [r["trade_date"] for r in report.written] == [
        date(2026, 8, 24),
        date(2026, 8, 25),
        date(2026, 8, 26),
    ]
    # And the prices travel with their own day, not merely the dates being right.
    closes = {r["trade_date"]: r["close_paise"] for r in report.written}
    assert closes[date(2026, 8, 24)] == 10500
    assert closes[date(2026, 8, 26)] == 11400


def test_the_vendor_code_is_resolved_for_each_day_not_once(tmp_path: Path) -> None:
    """A vendor code can point at different instruments across three years."""
    write(tmp_path / "bronze", RANGE_RECORD)
    master = FakeMaster()
    promote_daily(
        tmp_path / "bronze", tmp_path / "daily", cast("Any", master), known_on=date(2026, 9, 5)
    )
    assert master.asked == [date(2026, 8, 24), date(2026, 8, 25), date(2026, 8, 26)]


def test_prices_are_integer_paise(tmp_path: Path) -> None:
    """Rule: money is integer paise, never a float (C-NUM-01)."""
    write(tmp_path / "bronze", RANGE_RECORD)
    report = promote_daily(
        tmp_path / "bronze",
        tmp_path / "daily",
        cast("Any", FakeMaster()),
        known_on=date(2026, 9, 5),
    )
    for row in report.written:
        for field in ("open_paise", "high_paise", "low_paise", "close_paise"):
            assert isinstance(row[field], int), field


def test_a_symbol_that_resolves_to_no_instrument_is_quarantined_not_written(
    tmp_path: Path,
) -> None:
    """Same rule silver keeps: refusing to write bars under a vendor code nothing joins to."""
    write(tmp_path / "bronze", RANGE_RECORD)
    report = promote_daily(
        tmp_path / "bronze",
        tmp_path / "daily",
        cast("Any", FakeMaster(resolves=False)),
        known_on=date(2026, 9, 5),
    )
    assert report.rows == 0
    assert report.quarantined, "an unresolvable code must be reported, not silently skipped"


def test_a_day_keyed_record_is_skipped_rather_than_crashed(tmp_path: Path) -> None:
    """Bronze holds both shapes. This panel is for ranges; the other belongs to silver.

    Skipped and COUNTED, never quarantined: a day-keyed record is not corrupt, it is simply
    somebody else's. The count is what stops an empty run reading as a clean one.
    """
    day_record = json.loads(json.dumps(RANGE_RECORD))
    day_record["request"] = {"symbol": "RELIND", "trade_date": "2026-08-24"}
    write(tmp_path / "bronze", day_record, "day.json")
    report = promote_daily(
        tmp_path / "bronze",
        tmp_path / "daily",
        cast("Any", FakeMaster()),
        known_on=date(2026, 9, 5),
    )
    assert report.rows == 0
    assert report.other_shape == 1
    assert not report.quarantined
    assert "other shape" in report.describe()


def test_an_empty_run_says_so_rather_than_reading_as_clean(tmp_path: Path) -> None:
    (tmp_path / "bronze").mkdir()
    report = promote_daily(
        tmp_path / "bronze",
        tmp_path / "daily",
        cast("Any", FakeMaster()),
        known_on=date(2026, 9, 5),
    )
    assert report.rows == 0
    assert "0 row" in report.describe()


def test_a_record_without_a_usable_received_at_is_refused(tmp_path: Path) -> None:
    """Knowledge time is provenance. A 0 reads as known-since-1970, which is EARLY, not absent."""
    bad = json.loads(json.dumps(RANGE_RECORD))
    bad["received_at_ns"] = 0
    write(tmp_path / "bronze", bad)
    report = promote_daily(
        tmp_path / "bronze",
        tmp_path / "daily",
        cast("Any", FakeMaster()),
        known_on=date(2026, 9, 5),
    )
    assert report.rows == 0
    assert any("received_at_ns" in q.reason for q in report.quarantined)
