"""`pips daily promote <root> --known-on YYYY-MM-DD`: the daily panel gets a caller.

`promote_daily` existed since BLK-0003 with no caller outside tests, which is why arb-vm has
6,202 daily bronze records and no `bars_1d.parquet`. This is the silver `pips promote`'s
sibling: same root layout, same undefaulted `--known-on`, same "no bronze is not a pass", same
refusal without a master, argparse-owned `--help`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from pips import cli
from pips.data import daily as daily_module
from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore

KNOWN_ON = "2026-09-04"


def range_record() -> dict[str, Any]:
    """Three day-stamped 1day bars for RELIND, the shape Breeze returns for a ranged fetch."""
    bars = [
        ("2026-08-24", 100.0, 105.0, 1000),
        ("2026-08-25", 105.0, 111.0, 2000),
        ("2026-08-26", 111.0, 114.0, 3000),
    ]
    return {
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
                    "datetime": f"{d} 00:00:00",
                    "open": o,
                    "high": max(o, c) + 1,
                    "low": min(o, c) - 1,
                    "close": c,
                    "volume": v,
                    "stock_code": "RELIND",
                    "exchange_code": "NSE",
                }
                for d, o, c, v in bars
            ],
        },
    }


def archive(tmp_path: Path, *, with_master: bool = True, with_records: bool = True) -> Path:
    d = tmp_path / "bronze" / "RELIND" / "1day" / "2026-08-24_2026-08-26"
    d.mkdir(parents=True)
    if with_records:
        (d / "r.json").write_text(json.dumps(range_record()), encoding="utf-8")
    if with_master:
        master = InstrumentMaster(PitStore(tmp_path / "pit"))
        master.upsert(
            Instrument(
                isin="INE002A01018",
                exchange_token="2885",
                symbol="RELIANCE",
                name="Reliance Industries Ltd",
                series="EQ",
                lot_size=1,
                tick_size_paise=5,
                vendor_code="RELIND",
            ),
            known_from=date(2020, 1, 1),
        )
    return tmp_path


def test_it_promotes_the_daily_panel_and_reports_what_it_did(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path)
    assert daily_module.main([str(root), "--known-on", KNOWN_ON]) == 0
    panel = pl.read_parquet(root / "daily" / "bars_1d.parquet")
    assert panel.height == 3
    assert panel["symbol"].unique().to_list() == ["RELIANCE"]
    out = capsys.readouterr().out
    assert "bars_1d.parquet" in out
    assert "3 " in out or " 3" in out  # the row count is reported, not implied


def test_no_bronze_is_reported_as_nothing_to_do_not_as_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert daily_module.main([str(tmp_path), "--known-on", KNOWN_ON]) == 0
    out = capsys.readouterr().out
    assert "not a pass" in out
    assert not (tmp_path / "daily" / "bars_1d.parquet").exists()


def test_bronze_with_no_range_records_says_so_rather_than_reading_as_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, with_records=False)
    assert daily_module.main([str(root), "--known-on", KNOWN_ON]) == 0
    out = capsys.readouterr().out
    # "0 of 0 range record(s) -> 0 row(s)" is the clean-looking line this test exists to forbid.
    assert "found no range records" in out
    assert "not a pass" in out


def test_no_instrument_master_is_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, with_master=False)
    assert daily_module.main([str(root), "--known-on", KNOWN_ON]) == 2
    assert "instrument master" in capsys.readouterr().err


def test_known_on_is_required_not_defaulted(tmp_path: Path) -> None:
    root = archive(tmp_path)
    with pytest.raises(SystemExit) as stop:
        daily_module.main([str(root)])
    assert stop.value.code == 2


def test_the_dispatcher_routes_daily_promote(tmp_path: Path) -> None:
    root = archive(tmp_path)
    assert cli.main(["daily", "promote", str(root), "--known-on", KNOWN_ON]) == 0
    assert (root / "daily" / "bars_1d.parquet").exists()


def test_help_through_the_dispatcher_is_the_central_guard_and_does_no_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Two-word commands (`ledger check`, `daily promote`) get the dispatcher's own help, the same
    # guard that stopped `fixtures generate --help` from writing files. It returns rather
    # than exiting.
    root = archive(tmp_path)
    assert cli.main(["daily", "promote", str(root), "--help"]) == 0
    assert "--known-on" in capsys.readouterr().out
    assert not (root / "daily").exists()


def test_help_on_the_module_itself_is_argparse_owned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path)
    with pytest.raises(SystemExit) as stop:
        daily_module.main([str(root), "--help"])
    assert stop.value.code == 0
    assert "--known-on" in capsys.readouterr().out
    assert not (root / "daily").exists()


def test_the_command_is_documented_in_the_usage_table() -> None:
    assert any(line.strip().startswith("daily promote") for line in cli._USAGE.splitlines())


def test_known_on_governs_resolution_a_date_before_the_listing_quarantines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The instrument is known from 2020-01-01. Asked as of 2019, the master must not know it,
    # so every day quarantines under an identity reason and nothing is promoted. A CLI that
    # froze or defaulted known_on would resolve it anyway and write three rows.
    root = archive(tmp_path)
    assert daily_module.main([str(root), "--known-on", "2019-06-01"]) == 0
    out = capsys.readouterr().out
    assert "record(s) quarantined" in out  # the phrase, not a word tmp_path might contain
    panel = root / "daily" / "bars_1d.parquet"
    assert not panel.exists() or pl.read_parquet(panel).height == 0


def test_an_unwritable_daily_root_is_refused_before_any_record_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # arb-vm, 2026-09-05: 26 minutes of promotion, then PermissionError on mkdir('/srv/pips/daily').
    # The output root is checked FIRST; a run that cannot end in a write must not begin.
    root = archive(tmp_path)
    (root / "daily").write_text("a file where the directory should be")  # mkdir will fail
    assert daily_module.main([str(root), "--known-on", KNOWN_ON]) == 2
    captured = capsys.readouterr()
    assert "cannot write" in captured.err and str(root / "daily") in captured.err
    assert "range record" not in captured.out  # nothing was read, nothing was counted
