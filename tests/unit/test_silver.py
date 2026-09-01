"""Bronze -> silver: raw vendor replies become bars anyone can read  (§6 M6).

There are three trading days of real RELIND minute bars sitting in bronze on arb-vm and the
silver layer is empty — the data has been fetched and never turned into anything. `normalize_
candles` already produces close-labelled integer-paise bars; nothing persists them.

Three things must not go wrong quietly.

**The vendor code is not the symbol.** Bronze is keyed by RELIND; the exchange calls it
RELIANCE. Only 172 of 5,851 instruments have the two equal, so passing the vendor code through
as the symbol would mislabel almost every name — and the bars would look perfectly ordinary.

**A reply that is not data must never be written as data.** Breeze answers rate limits and
errors with HTTP 200 and a body; `classify_response` already tells them apart, and anything that
is not OK goes to quarantine WITH its reason.

**Promotion is idempotent.** Re-promoting the same bronze must produce identical silver, or the
snapshot root of a rebuilt panel stops matching the one that was pinned (rule 1, [C-DATA-02]).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore
from pips.data.silver import promote_bronze

KNOWN_ON = date(2026, 8, 29)
TRADE_DAY = date(2026, 8, 26)


def candle(minute: int, close: float = 1309.6) -> dict[str, object]:
    return {
        "datetime": f"2026-08-26 {9 + (15 + minute) // 60:02d}:{(15 + minute) % 60:02d}:00",
        "open": 1311.1,
        "high": 1314.6,
        "low": 1308.6,
        "close": close,
        "volume": 162289,
        "stock_code": "RELIND",
        "exchange_code": "NSE",
    }


def write_bronze(root: Path, payload: dict[str, object], symbol: str = "RELIND") -> Path:
    path = root / symbol / TRADE_DAY.isoformat() / "1788174382222188421.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "request": {
                    "symbol": symbol,
                    "trade_date": TRADE_DAY.isoformat(),
                    "interval": "1minute",
                },
                "received_at_ns": 1788174382222188421,
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    return path


def ok(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"Success": rows, "Status": 200, "Error": None}


@pytest.fixture
def master(tmp_path: Path) -> InstrumentMaster:
    m = InstrumentMaster(PitStore(tmp_path / "pit"))
    m.upsert(
        Instrument(
            isin="INE002A01018",
            exchange_token="2885",
            symbol="RELIANCE",
            name="Reliance Industries",
            series="EQ",
            lot_size=1,
            tick_size_paise=5,
            vendor_code="RELIND",
        ),
        known_from=date(2026, 8, 1),
        valid_from=date(2026, 8, 1),
    )
    m.upsert(
        Instrument(
            isin="INE467B01029",
            exchange_token="11536",
            symbol="TCS",
            name="Tata Consultancy Services",
            series="EQ",
            lot_size=1,
            tick_size_paise=5,
            vendor_code="TCSLTD",
        ),
        known_from=date(2026, 8, 1),
        valid_from=date(2026, 8, 1),
    )
    return m


# ------------------------------------------------------------ identity ---------------


def test_the_exchange_symbol_is_used_not_the_vendor_code(
    tmp_path: Path, master: InstrumentMaster
) -> None:
    """Bronze says RELIND; the panel must say RELIANCE.

    Only 172 of 5,851 instruments have the two equal, so passing the vendor code through would
    mislabel almost every name — and the bars would look perfectly ordinary while joining to
    nothing.
    """
    write_bronze(tmp_path / "bronze", ok([candle(0), candle(1)]))
    report = promote_bronze(tmp_path / "bronze", tmp_path / "silver", master, known_on=KNOWN_ON)
    assert report.bars_written == 2
    assert {row["symbol"] for row in report.rows} == {"RELIANCE"}


def test_an_unresolvable_vendor_code_is_quarantined(
    tmp_path: Path, master: InstrumentMaster
) -> None:
    """Not passed through under its own name.

    A bar whose instrument is unknown is a bar nobody can join to a universe, a cost model or a
    corporate action. Writing it under the vendor code would make it look joinable.
    """
    write_bronze(tmp_path / "bronze", ok([candle(0)]), symbol="NOSUCH")
    report = promote_bronze(tmp_path / "bronze", tmp_path / "silver", master, known_on=KNOWN_ON)
    assert report.bars_written == 0
    assert len(report.quarantined) == 1
    assert "NOSUCH" in report.quarantined[0].reason


# ------------------------------------------------------------ not-data ---------------


@pytest.mark.parametrize(
    "payload",
    [
        {"Success": None, "Status": 429, "Error": "rate limit"},
        {"Success": None, "Status": 500, "Error": "server"},
        {"Success": [], "Status": 200, "Error": None},
    ],
)
def test_a_reply_that_is_not_data_is_quarantined_with_its_reason(
    tmp_path: Path, master: InstrumentMaster, payload: dict[str, object]
) -> None:
    """Breeze answers rate limits with HTTP 200 and a body.

    Written as data, a throttled fetch becomes a day with no bars — indistinguishable from a
    holiday, and it silently shortens every series built on it.
    """
    write_bronze(tmp_path / "bronze", payload)
    report = promote_bronze(tmp_path / "bronze", tmp_path / "silver", master, known_on=KNOWN_ON)
    assert report.bars_written == 0
    assert report.quarantined

    # The reason must name the CLASSIFICATION. Without the response check these files still get
    # quarantined — by the empty-bars fallback further down — so "there is some reason" passes
    # with the guard deleted. What distinguishes them is what the reason says.
    assert "classified" in report.quarantined[0].reason


# ------------------------------------------------------------ the bars ---------------


def test_an_ok_reply_whose_candles_all_fall_outside_the_session_is_quarantined(
    tmp_path: Path, master: InstrumentMaster
) -> None:
    """OK, well-formed, and nothing survives the session clip.

    Pre-open and post-close prints are not on the continuous tape (§3.5), so a reply made
    entirely of them yields no bars. Counting that file as promoted would report a day as
    covered when nothing was written for it.
    """
    stray = dict(candle(0))
    stray["datetime"] = "2026-08-26 03:00:00"
    write_bronze(tmp_path / "bronze", ok([stray]))
    report = promote_bronze(tmp_path / "bronze", tmp_path / "silver", master, known_on=KNOWN_ON)
    assert report.bars_written == 0
    assert report.files_promoted == 0
    assert "no bars survived" in report.quarantined[0].reason


def test_the_file_order_the_filesystem_yields_does_not_change_the_output(
    tmp_path: Path, master: InstrumentMaster, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling it twice proves nothing: rglob yields the same order both times.

    Filesystem order is not guaranteed across machines, and silver that moves with it would
    hash differently on the laptop and on arb-vm for identical bronze.
    """
    root = tmp_path / "bronze"
    write_bronze(root, ok([candle(0)]))
    write_bronze(root, ok([candle(1)]), symbol="TCSLTD")
    forward = promote_bronze(root, tmp_path / "a", master, known_on=KNOWN_ON)

    # Two files that both quarantine, because the ROWS are sorted at the end and so cannot show
    # file-order dependence at all. The quarantine list is not sorted afterwards, so it is the
    # thing that carries the filesystem's order into the report — and a quarantine list that
    # differs between machines is a report two people cannot compare.
    write_bronze(root, ok([candle(0)]), symbol="NOSUCHA")
    write_bronze(root, ok([candle(0)]), symbol="NOSUCHB")
    forward = promote_bronze(root, tmp_path / "a2", master, known_on=KNOWN_ON)

    original = Path.rglob
    monkeypatch.setattr(
        Path, "rglob", lambda self, pattern: reversed(list(original(self, pattern)))
    )
    reversed_run = promote_bronze(root, tmp_path / "b", master, known_on=KNOWN_ON)
    assert reversed_run.rows == forward.rows
    assert [q.source for q in reversed_run.quarantined] == [q.source for q in forward.quarantined]


def test_rows_are_ordered_by_time_then_symbol(tmp_path: Path, master: InstrumentMaster) -> None:
    """A panel read in file order is a panel whose first bar depends on a directory listing.

    TCSLTD sorts before RELIND as a path and RELIANCE after TCS as a symbol, so insertion order
    and sorted order genuinely differ here.
    """
    root = tmp_path / "bronze"
    write_bronze(root, ok([candle(0), candle(1)]))
    write_bronze(root, ok([candle(0), candle(1)]), symbol="TCSLTD")
    rows = promote_bronze(root, tmp_path / "silver", master, known_on=KNOWN_ON).rows
    keys = [(r["close_ts_ns"], r["symbol"]) for r in rows]
    assert keys == sorted(keys)


def test_bars_are_close_labelled(tmp_path: Path, master: InstrumentMaster) -> None:
    """ADR-0001: Breeze is OPEN-labelled and ingest adds one interval.

    A 09:15 candle covers [09:15, 09:16), so it is the bar ending at 09:16. Off by one interval
    is a one-bar lookahead, which is the most expensive kind of leakage because backtests love
    it.
    """
    write_bronze(tmp_path / "bronze", ok([candle(0)]))
    report = promote_bronze(tmp_path / "bronze", tmp_path / "silver", master, known_on=KNOWN_ON)
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    stamped = datetime.fromtimestamp(report.rows[0]["close_ts_ns"] / 1e9, ist)
    assert stamped.strftime("%H:%M") == "09:16"


def test_prices_are_integer_paise(tmp_path: Path, master: InstrumentMaster) -> None:
    write_bronze(tmp_path / "bronze", ok([candle(0, close=1309.6)]))
    report = promote_bronze(tmp_path / "bronze", tmp_path / "silver", master, known_on=KNOWN_ON)
    row = report.rows[0]
    assert row["close_paise"] == 130960
    assert all(isinstance(row[k], int) for k in ("open_paise", "high_paise", "low_paise"))


def test_missing_minutes_stay_missing(tmp_path: Path, master: InstrumentMaster) -> None:
    # A zero-volume bar is not a missing bar and a missing bar is not a zero (§3.4). Filling the
    # gap would invent a price nobody traded at.
    write_bronze(tmp_path / "bronze", ok([candle(0), candle(5)]))
    report = promote_bronze(tmp_path / "bronze", tmp_path / "silver", master, known_on=KNOWN_ON)
    assert report.bars_written == 2


# ------------------------------------------------------------ idempotence ------------


def test_promotion_is_idempotent(tmp_path: Path, master: InstrumentMaster) -> None:
    """Re-promoting the same bronze must produce identical silver.

    Otherwise a rebuilt panel's snapshot root stops matching the one a trial pinned, and
    [C-DATA-02] turns from a guarantee into a coin flip.
    """
    write_bronze(tmp_path / "bronze", ok([candle(0), candle(1)]))
    first = promote_bronze(tmp_path / "bronze", tmp_path / "a", master, known_on=KNOWN_ON)
    second = promote_bronze(tmp_path / "bronze", tmp_path / "b", master, known_on=KNOWN_ON)
    assert first.rows == second.rows
    assert (tmp_path / "a").exists() and (tmp_path / "b").exists()


def test_the_report_accounts_for_every_bronze_file(
    tmp_path: Path, master: InstrumentMaster
) -> None:
    root = tmp_path / "bronze"
    write_bronze(root, ok([candle(0)]))
    write_bronze(root, ok([candle(0)]), symbol="NOSUCH")
    report = promote_bronze(root, tmp_path / "silver", master, known_on=KNOWN_ON)
    assert report.files_read == 2
    assert report.files_promoted + len(report.quarantined) == report.files_read
