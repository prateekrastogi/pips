"""QC runner over bronze, and the seeded corruption generator  (§6 M5).

Reads bronze, normalizes, runs every check, and writes anything that fails to the quarantine
zone **with its reason attached**. Three properties hold throughout:

* **bronze is never modified.** It is the only unmodified copy of what the vendor actually
  sent (§3.4), and a QC pass that edited it would destroy the thing every later question is
  answered against.
* **quarantine retains.** The corrupt record is the evidence for the corruption; deleting it
  makes the finding unverifiable, and a QC report nobody can check is one nobody should trust.
* **the manifest is consulted.** Inside the bars, "nothing traded" and "we never got an
  answer" look identical. Only the backfill manifest can tell them apart, and they are very
  different claims.

:func:`seed_corrupt_bronze` writes deliberately broken records. §6 M5's Verify asks for exactly
that -- a check suite that has only met its own unit tests has never met the parsing, the
normalization or the file layout it will run against.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final

from pips.data.breeze.ingest import ResponseKind, classify_response, normalize_candles
from pips.data.qc.checks import (
    Finding,
    Severity,
    check_bar_sanity,
    check_decimal_shift,
    check_monotonic_labels,
    check_raw_row_order,
    check_session_coverage,
    check_spikes,
)

__all__ = ["CORRUPTIONS", "QcReport", "main", "run_qc", "seed_corrupt_bronze"]

CORRUPTIONS: Final = frozenset(
    {"bar_sanity", "label_order", "spike", "decimal_shift", "session_coverage", "empty"}
)

_SEED_DAY = date(2026, 8, 28)
_SEED_SYMBOL = "CLEAN"
_MAX_MOVE_BPS = 1_000
_EXPECTED_MINUTES = 375


@dataclass
class QcReport:
    """What one QC pass found."""

    checked: int = 0
    quarantined: int = 0
    findings: list[Finding] = field(default_factory=list)

    def describe(self) -> str:
        return (
            f"qc: checked {self.checked} record(s), quarantined {self.quarantined}, "
            f"{len(self.findings)} finding(s)"
        )


def _rows(minutes: int = _EXPECTED_MINUTES) -> list[dict[str, Any]]:
    """A clean minute series. Prices in rupees, as the vendor sends them.

    A FULL session by default, because the coverage check measures against a real session and
    a 30-minute fixture would be flagged as truncated — correctly. A fixture that does not
    look like the data is a fixture that tests something else.
    """
    return [
        {
            "datetime": f"2026-08-28 {9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00",
            "open": 100.00 + i * 0.01,
            "high": 100.50 + i * 0.01,
            "low": 99.50 + i * 0.01,
            "close": 100.10 + i * 0.01,
            "volume": 1000 + i,
        }
        for i in range(minutes)
    ]


def seed_corrupt_bronze(bronze_root: Path, corruption: str | None) -> Path:
    """Write one bronze record, optionally corrupted in a named way."""
    rows = _rows()
    if corruption == "bar_sanity":
        rows[5]["high"] = 98.00  # below open and close
    elif corruption == "label_order":
        rows[10], rows[11] = rows[11], rows[10]
    elif corruption == "spike":
        rows[15]["close"] = 500.00
        rows[16]["close"] = 100.25  # returns, but the move itself is implausible
    elif corruption == "decimal_shift":
        for field_name in ("open", "high", "low", "close"):
            rows[20][field_name] = float(rows[20][field_name]) * 10
    elif corruption == "session_coverage":
        rows = rows[:2]
    elif corruption == "empty":
        rows = []
    elif corruption is not None:
        raise ValueError(
            f"unknown corruption {corruption!r}; expected one of {sorted(CORRUPTIONS)}"
        )

    directory = bronze_root / _SEED_SYMBOL / _SEED_DAY.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{time.time_ns()}.json"
    path.write_text(
        json.dumps(
            {
                "request": {
                    "symbol": _SEED_SYMBOL,
                    "trade_date": _SEED_DAY.isoformat(),
                    "interval": "1minute",
                },
                "received_at_ns": time.time_ns(),
                "payload": {"Status": 200, "Success": rows},
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def run_qc(
    bronze_root: Path,
    quarantine_root: Path,
    fetched_keys: set[str],
    calendar_path: Path | None = None,
) -> QcReport:
    """Check every bronze record; quarantine what fails, with reasons.

    ``fetched_keys`` comes from the backfill manifest -- ``"SYMBOL:YYYY-MM-DD"`` for every key
    that returned an answer. Without it an empty session is indistinguishable from a hole.
    """
    from pips.core.calendar import SESSION_MINUTES_DEFAULT, load_calendar

    calendar = load_calendar(calendar_path) if calendar_path else None
    expected_minutes = calendar.continuous_session_minutes if calendar else SESSION_MINUTES_DEFAULT

    report = QcReport()
    for path in sorted(bronze_root.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        request = record["request"]
        symbol, day = request["symbol"], date.fromisoformat(request["trade_date"])
        key = f"{symbol}:{day.isoformat()}"
        report.checked += 1

        payload = record["payload"]
        findings: list[Finding] = []
        if classify_response(payload) is ResponseKind.RATE_LIMITED:
            findings.append(
                Finding("rate_limited", Severity.QUARANTINE, "bronze holds a rate rejection")
            )
            bars = []
        else:
            # Before normalization, because the normalizer's sort hides row disorder.
            findings += check_raw_row_order(payload.get("Success") or [])
            bars = normalize_candles(payload, day, interval_minutes=1)
            findings += check_bar_sanity(bars)
            findings += check_monotonic_labels(bars)
            findings += check_spikes(bars, max_move_bps=_MAX_MOVE_BPS)
            findings += check_decimal_shift(bars)

        # From the CALENDAR, not from the fixture. This read `len(_rows())` — the seed
        # fixture's 30 minutes — which made the check vacuous on real data: a genuine
        # 375-minute session arriving with 50 bars scored 50/30 and passed. The expectation
        # must describe the session, not the test data.
        findings += check_session_coverage(
            bars, expected_minutes=expected_minutes, fetch_succeeded=key in fetched_keys
        )

        if findings:
            report.findings.extend(findings)
            if any(f.severity is Severity.QUARANTINE for f in findings):
                report.quarantined += 1
                _quarantine(quarantine_root, path, record, findings)
    return report


def _quarantine(root: Path, source: Path, record: dict[str, Any], findings: list[Finding]) -> None:
    """Write the record and its reasons to quarantine. Bronze is left untouched."""
    directory = root / record["request"]["symbol"] / record["request"]["trade_date"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / source.name).write_text(
        json.dumps(
            {
                "source": str(source),
                "quarantined_at_ns": time.time_ns(),
                "request": record["request"],
                "findings": [
                    {
                        "check": f.check,
                        "severity": f.severity.value,
                        "detail": f.detail,
                        "label": f.label,
                    }
                    for f in findings
                ],
                # Retained on purpose: the corrupt record is the evidence for the corruption.
                "payload": record["payload"],
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``pips qc [data_root]``. Non-zero when anything was quarantined.

    Non-zero on findings is deliberate: a QC pass that always exits 0 is a QC pass nobody
    reads. `make qc` is meant to fail loudly when the archive has a problem.
    """
    import os
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(args[0]) if args else Path(os.environ.get("PIPS_DATA_ROOT", "/srv/pips"))
    bronze, quarantine = root / "bronze", root / "quarantine"
    if not bronze.exists():
        print(f"qc: no bronze at {bronze} — nothing to check.")
        print("    That is not a pass. Run a backfill first (ops/runbooks/backfill.md).")
        return 0

    manifest_path = root / "state" / "backfill-manifest.json"
    fetched: set[str] = set()
    if manifest_path.exists():
        outcomes = json.loads(manifest_path.read_text(encoding="utf-8")).get("outcomes", {})
        fetched = {k for k, v in outcomes.items() if v in ("OK", "EMPTY")}
    else:
        print(f"qc: WARNING no manifest at {manifest_path} — every session will be reported")
        print("    as unfetched, because nothing else can distinguish a hole from a quiet day.")

    report = run_qc(bronze, quarantine, fetched)
    print(report.describe())
    by_check: dict[str, int] = {}
    for finding in report.findings:
        by_check[finding.check] = by_check.get(finding.check, 0) + 1
    for check, count in sorted(by_check.items()):
        print(f"  {check}: {count}")
    if report.quarantined:
        print(f"  quarantined records are in {quarantine} WITH their reasons — not deleted.")
        return 1
    return 0
