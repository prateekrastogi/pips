"""Bronze RANGE records -> a DAILY panel, beside silver rather than inside it (`BLK-0003`).

WHY A SEPARATE PANEL. Silver is definitionally the one-minute intraday panel: `_INTERVAL_MINUTES
= 1`, and its bar model is `(trade_date, close_label)` with the label clipped to the continuous
session. A daily bar has no intraday close label -- Breeze stamps it 00:00 -- so feeding one
through `normalize_candles` returns ZERO bars, measured on 2026-09-04. Giving silver an interval
dimension instead would change the meaning of every row already in it and put the certified
intraday panel in scope for a change it does not need. The daily bars have exactly one consumer,
the liquidity ranking that picks the 500, and it wants symbol-day rows.

TWO TRAPS, both found by reading the intraday path rather than by hitting them:

* `normalize_candles` IGNORES a candle's own date and stamps every bar with the single
  `trade_date` it is handed. Exploding a three-year range through it would date every bar to one
  day and every bar would look ordinary. Here the candle's OWN date decides.
* the vendor code is resolved PER DAY. A code can point at different instruments across three
  years, which is why `resolve_vendor_code` takes a date at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pips.data.breeze.ingest import ResponseKind, classify_response, rupees_to_paise

if TYPE_CHECKING:
    from pips.data.pit.instruments import InstrumentMaster

__all__ = ["DailyPromotionReport", "Quarantined", "main", "promote_daily"]


@dataclass(frozen=True)
class Quarantined:
    """A record, or a day inside one, that did not become a row -- and why."""

    source: str
    reason: str


@dataclass
class DailyPromotionReport:
    files_read: int = 0
    files_promoted: int = 0
    rows: int = 0
    other_shape: int = 0
    """Day-keyed records: silver's business, not this panel's. Counted, never quarantined."""
    quarantined: list[Quarantined] = field(default_factory=list)
    written: list[dict[str, Any]] = field(default_factory=list)

    def describe(self) -> str:
        text = (
            f"daily: read {self.files_read} file(s), promoted {self.files_promoted}, "
            f"{self.rows} row(s); {len(self.quarantined)} quarantined"
        )
        if self.other_shape:
            text += f"; skipped {self.other_shape} record(s) of another shape"
        return text


def promote_daily(
    bronze_root: Path,
    daily_root: Path,
    master: InstrumentMaster,
    *,
    known_on: date,
) -> DailyPromotionReport:
    """Explode every RANGE record under ``bronze_root`` into one row per trading day."""
    report = DailyPromotionReport()

    for path in sorted(Path(bronze_root).rglob("*.json")):
        report.files_read += 1
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            request = record["request"]
            payload = record["payload"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            report.quarantined.append(Quarantined(str(path), f"not a readable capture ({error!r})"))
            continue

        # A day-keyed record is not corrupt, it is silver's. Counted so an empty run cannot
        # read as a clean one -- the same reason `run_qc` counts what it skips.
        if "trade_date" in request:
            report.other_shape += 1
            continue

        vendor_code = str(request.get("symbol", ""))
        if classify_response(payload) is not ResponseKind.OK:
            report.quarantined.append(
                Quarantined(str(path), f"reply carries no data for {vendor_code}")
            )
            continue

        received = record.get("received_at_ns")
        if not isinstance(received, int) or isinstance(received, bool) or received <= 0:
            report.quarantined.append(
                Quarantined(
                    str(path),
                    f"capture carries no usable received_at_ns ({received!r}) for "
                    f"{vendor_code}. A 0 reads as known-since-1970, which is EARLY rather "
                    "than absent: it sorts inside every as-of window there is.",
                )
            )
            continue

        rows = _rows_for(record, payload, vendor_code, master, known_on, path, report)
        if rows:
            report.written.extend(rows)
            report.rows += len(rows)
            report.files_promoted += 1

    if report.written:
        _write(daily_root, report.written)
    return report


def _rows_for(
    record: dict[str, Any],
    payload: dict[str, Any],
    vendor_code: str,
    master: InstrumentMaster,
    known_on: date,
    path: Path,
    report: DailyPromotionReport,
) -> list[dict[str, Any]]:
    received = int(record["received_at_ns"])
    rows: list[dict[str, Any]] = []
    for candle in payload.get("Success") or []:
        try:
            # THE CANDLE'S OWN DATE. Not a date handed in from the request.
            day = datetime.strptime(str(candle["datetime"])[:10], "%Y-%m-%d").date()
        except (KeyError, ValueError) as error:
            report.quarantined.append(
                Quarantined(str(path), f"a candle carries no usable date ({error!r})")
            )
            continue

        instrument = master.resolve_vendor_code(vendor_code, day, known_on=known_on)
        if instrument is None:
            report.quarantined.append(
                Quarantined(
                    str(path),
                    f"vendor code {vendor_code!r} resolves to no instrument on {day}. "
                    "Refusing to write a bar under the vendor code: it would join to nothing "
                    "while looking ordinary.",
                )
            )
            continue

        try:
            row = {
                "trade_date": day,
                "symbol": instrument.symbol,
                "isin": instrument.isin,
                "open_paise": rupees_to_paise(candle["open"]),
                "high_paise": rupees_to_paise(candle["high"]),
                "low_paise": rupees_to_paise(candle["low"]),
                "close_paise": rupees_to_paise(candle["close"]),
                "volume": int(candle["volume"]),
                "received_at_ns": received,
            }
        except (KeyError, TypeError, ValueError) as error:
            report.quarantined.append(
                Quarantined(str(path), f"a candle on {day} is unreadable ({error!r})")
            )
            continue
        rows.append(row)
    return rows


def _write(daily_root: Path, rows: list[dict[str, Any]]) -> None:
    import polars as pl

    Path(daily_root).mkdir(parents=True, exist_ok=True)
    # Sorted so a rebuild produces the same file in the same order (rule 1).
    ordered = sorted(rows, key=lambda r: (r["symbol"], r["trade_date"]))
    pl.DataFrame(ordered).write_parquet(Path(daily_root) / "bars_1d.parquet")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``pips daily promote <data_root> --known-on YYYY-MM-DD``.

    `promote_daily` had no caller outside tests since `BLK-0003`, which is why arb-vm held
    6,202 daily bronze records and no `bars_1d.parquet`. This is `pips promote`'s sibling: same
    root layout (`<root>/bronze`, `<root>/pit`, and `<root>/daily` beside silver), same
    undefaulted `--known-on`, same "no bronze is not a pass", same refusal without a master.
    There is no QC gate here: QC's checks are session-shaped and the daily panel is not on the
    path to capital -- it ranks names for capture, it does not trade them.
    """
    import argparse
    import os
    import sys

    from pips.data.pit.instruments import InstrumentMaster
    from pips.data.pit.store import PitStore

    parser = argparse.ArgumentParser(prog="pips daily promote")
    parser.add_argument("data_root", nargs="?", default=None, help="defaults to $PIPS_DATA_ROOT")
    parser.add_argument(
        "--known-on",
        required=True,
        help="the as-of knowledge date for instrument resolution; NOT defaulted, because a "
        "bitemporal read that moves is the one thing §3.4 forbids",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    root = (
        Path(args.data_root)
        if args.data_root
        else Path(os.environ.get("PIPS_DATA_ROOT", "/srv/pips"))
    )
    bronze, daily_root = root / "bronze", root / "daily"
    if not bronze.exists():
        print(f"daily promote: no bronze at {bronze} — nothing to promote.")
        print("    That is not a pass. Run a daily backfill first (ops/runbooks/backfill.md).")
        return 0
    pit = root / "pit"
    if not pit.exists():
        print(
            f"daily promote: no instrument master at {pit}. Every vendor code would resolve to "
            "nothing and every record would quarantine under an identity reason, which is a "
            "true statement about each record and a misleading one about the run.",
            file=sys.stderr,
        )
        return 2
    report = promote_daily(
        bronze,
        daily_root,
        InstrumentMaster(PitStore(pit)),
        known_on=date.fromisoformat(args.known_on),
    )
    if report.files_read == 0:
        print(f"daily promote: found no range records under {bronze} — nothing was written.")
        print("    That is not a pass either: an empty bronze tree is a backfill that did not run.")
        return 0
    print(
        f"daily promote: {report.files_promoted} of {report.files_read} range record(s) -> "
        f"{report.rows} row(s) in {daily_root / 'bars_1d.parquet'}"
    )
    if report.other_shape:
        print(f"    {report.other_shape} day-keyed record(s) skipped — those belong to silver")
    if report.quarantined:
        print(f"    {len(report.quarantined)} record(s) quarantined:")
        for item in report.quarantined[:5]:
            print(f"      {item.source}: {item.reason}")
        if len(report.quarantined) > 5:
            print(f"      ... and {len(report.quarantined) - 5} more")
    return 0
