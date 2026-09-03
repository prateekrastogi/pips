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
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

from pips.core.calendar import ExchangeCalendar
from pips.data.breeze.ingest import ResponseKind, classify_response, normalize_candles
from pips.data.pit.explain import JumpExplainer, jump_explainer
from pips.data.qc.checks import (
    Finding,
    QcVerdicts,
    Severity,
    check_bar_sanity,
    check_calendar_gaps,
    check_decimal_shift,
    check_monotonic_labels,
    check_raw_row_order,
    check_session_coverage,
    check_spikes,
    check_unexplained_ratio_jump,
)

__all__ = [
    "CORRUPTIONS",
    "QcReport",
    "main",
    "run_qc",
    "seed_corrupt_bronze",
    "seed_two_sessions",
]

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
    # COVERAGE OF THE OVERNIGHT-RATIO CHECK, counted rather than assumed. "0 findings" is not
    # a result unless you know what was examined: a run that compared nothing prints the same
    # clean line as one that compared everything. See `_previous_trading_day`.
    ratio_checks_run: int = 0
    ratio_checks_skipped: int = 0
    # COVERAGE OF THE CALENDAR-GAP CHECK, for the same reason. Zero means no calendar was
    # supplied and no day was compared -- which must not print the same line as a span that
    # was examined and found whole, because that indistinguishability is exactly how the
    # missing check went unnoticed for a milestone.
    calendar_days_examined: int = 0
    # THE KEYS, not just the counts. `checked: int` cannot tell promotion WHICH records were
    # examined, and promotion has to know per record -- a count would let it assume the two
    # sets line up and promote an unchecked record as though QC had cleared it.
    examined_keys: set[str] = field(default_factory=set)
    quarantined_keys: set[str] = field(default_factory=set)

    def verdicts(self) -> QcVerdicts:
        """The seam `promote_bronze` consults. See :class:`QcVerdicts`."""
        return QcVerdicts(
            examined=frozenset(self.examined_keys), quarantined=frozenset(self.quarantined_keys)
        )

    def describe(self) -> str:
        calendar = (
            f"calendar days examined {self.calendar_days_examined}"
            if self.calendar_days_examined
            else "calendar gaps not checked (no calendar supplied)"
        )
        return (
            f"qc: checked {self.checked} record(s), quarantined {self.quarantined}, "
            f"{len(self.findings)} finding(s); "
            f"overnight-ratio comparisons made {self.ratio_checks_run}, "
            f"skipped {self.ratio_checks_skipped}; "
            f"{calendar}"
        )


def _rows(
    minutes: int = _EXPECTED_MINUTES,
    day: date = _SEED_DAY,
    base_rupees: float = 100.00,
) -> list[dict[str, Any]]:
    """A clean minute series. Prices in rupees, as the vendor sends them.

    A FULL session by default, because the coverage check measures against a real session and
    a 30-minute fixture would be flagged as truncated — correctly. A fixture that does not
    look like the data is a fixture that tests something else.
    """
    return [
        {
            "datetime": (f"{day.isoformat()} {9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00"),
            "open": base_rupees + i * 0.01,
            "high": base_rupees + 0.50 + i * 0.01,
            "low": base_rupees - 0.50 + i * 0.01,
            "close": base_rupees + 0.10 + i * 0.01,
            "volume": 1000 + i,
        }
        for i in range(minutes)
    ]


def _set_bar(row: dict[str, Any], price: float) -> None:
    """Move a whole bar to ``price``, keeping open/high/low/close mutually consistent."""
    row["open"] = price
    row["high"] = price + 0.50
    row["low"] = price - 0.50
    row["close"] = price


def _write_record(
    bronze_root: Path, day: date, rows: list[dict[str, Any]], symbol: str = _SEED_SYMBOL
) -> Path:
    directory = bronze_root / symbol / day.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{time.time_ns()}.json"
    path.write_text(
        json.dumps(
            {
                "request": {
                    "symbol": symbol,
                    "trade_date": day.isoformat(),
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


def seed_two_sessions(
    bronze_root: Path,
    first_close_paise: int,
    second_open_paise: int,
    first_day: date = date(2026, 8, 27),
    second_day: date = _SEED_DAY,
    symbol: str = _SEED_SYMBOL,
) -> None:
    """Two clean sessions whose overnight ratio is under the caller's control.

    Used to exercise the ratio-jump check, which needs two records to have anything to
    compare — the single-record seeder cannot reach it at all, which is part of why it went
    unrun for a milestone.
    """
    # The WHOLE bar is moved, not just the one field. Setting `close` alone left it below its
    # own row's low — the last row of a 375-minute ramp sits well above the base — so a
    # "clean" two-session fixture arrived with a bar_sanity violation baked in. A dirty
    # fixture in a seeder named for clean data hides whatever it is used to test.
    first = _rows(day=first_day, base_rupees=first_close_paise / 100.0)
    _set_bar(first[-1], first_close_paise / 100.0)
    second = _rows(day=second_day, base_rupees=second_open_paise / 100.0)
    _set_bar(second[0], second_open_paise / 100.0)
    _write_record(bronze_root, first_day, first, symbol)
    _write_record(bronze_root, second_day, second, symbol)


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

    return _write_record(bronze_root, _SEED_DAY, rows)


def _previous_trading_day(calendar: ExchangeCalendar, day: date, limit: int = 10) -> date | None:
    """The trading day immediately before ``day``, or ``None`` across a long closure."""
    for back in range(1, limit + 1):
        candidate = day - timedelta(days=back)
        if calendar.is_trading_day(candidate):
            return candidate
    return None


def run_qc(
    bronze_root: Path,
    quarantine_root: Path,
    fetched_keys: set[str],
    calendar_path: Path | None = None,
    explain_jump: JumpExplainer | None = None,
) -> QcReport:
    """Check every bronze record; quarantine what fails, with reasons.

    ``fetched_keys`` comes from the backfill manifest -- ``"SYMBOL:YYYY-MM-DD"`` for every key
    that returned an answer. Without it an empty session is indistinguishable from a hole.

    ``explain_jump`` is the seam to M6's corporate-action master: given a symbol, a date and
    the observed prices, it says whether a known action accounts for the move. It is
    **optional and defaults to None**, which FAILS CLOSED -- every common-ratio jump is
    quarantined, exactly the behaviour before the master existed.

    It is a callable rather than a master object because the master is keyed on ISIN and
    bronze carries a SYMBOL, and resolving one to the other as-of is the instrument master's
    job. Nothing has loaded real instruments yet, so the resolution is left to the caller
    instead of being faked here -- a seam that is honest about not being connected beats one
    that looks connected and silently resolves nothing.
    """
    from pips.core.calendar import SESSION_MINUTES_DEFAULT, load_calendar

    calendar = load_calendar(calendar_path) if calendar_path else None
    expected_minutes = calendar.continuous_session_minutes if calendar else SESSION_MINUTES_DEFAULT

    report = QcReport()
    # Per symbol, the last session seen and its closing price. Path order is symbol-then-date
    # (bronze/<symbol>/<date>/<ns>.json), so this walks each symbol's sessions in order.
    previous_session: dict[str, tuple[date, int]] = {}
    # Which sessions each symbol actually has. The per-record checks cannot see a day that is
    # absent -- there is no record to hand them -- so the set is compared to the calendar after
    # the walk.
    seen_days: dict[str, set[date]] = {}
    for path in sorted(bronze_root.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        request = record["request"]
        symbol, day = request["symbol"], date.fromisoformat(request["trade_date"])
        key = f"{symbol}:{day.isoformat()}"
        seen_days.setdefault(symbol, set()).add(day)
        report.examined_keys.add(key)
        report.checked += 1

        payload = record["payload"]
        findings: list[Finding] = []
        rejected = classify_response(payload) is ResponseKind.RATE_LIMITED
        if rejected:
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
        # Not for a rejection. We already know why there are no bars, and coverage would add
        # "truncated response rather than thin trading" -- a claim about the DATA, on a record
        # whose problem is our QUOTA. The two findings contradict each other about the same
        # record, and a finding that is sometimes false is one everybody learns to skip.
        if not rejected:
            findings += check_session_coverage(
                bars, expected_minutes=expected_minutes, fetch_succeeded=key in fetched_keys
            )

        # The overnight ratio, but ONLY across genuinely adjacent sessions. Bronze is not
        # guaranteed contiguous -- a partial backfill leaves holes -- and comparing a close
        # from last week against today's open yields a ratio that means nothing. Quarantining
        # on that would train everyone to ignore the finding, which is worse than not having
        # it. Needs a calendar to establish adjacency; without one the check is skipped.
        if bars:
            prior = previous_session.get(symbol)
            adjacent = (
                prior is not None
                and calendar is not None
                and prior[0] == _previous_trading_day(calendar, day)
            )
            if adjacent:
                report.ratio_checks_run += 1
            else:
                report.ratio_checks_skipped += 1
            if adjacent and prior is not None:
                prior_close = prior[1]
                findings += check_unexplained_ratio_jump(
                    previous_close_paise=prior_close,
                    first_open_paise=bars[0].open_paise,
                    verdict=(
                        explain_jump(symbol, day, prior_close, bars[0].open_paise)
                        if explain_jump
                        else None
                    ),
                )
            previous_session[symbol] = (day, bars[-1].close_paise)

        if findings:
            report.findings.extend(findings)
            if any(f.severity is Severity.QUARANTINE for f in findings):
                report.quarantined += 1
                report.quarantined_keys.add(key)
                _quarantine(quarantine_root, path, record, findings)

    if calendar is not None:
        for symbol in sorted(seen_days):
            days = seen_days[symbol]
            first, last = min(days), max(days)
            # THE SPAN IS WHAT THE ARCHIVE COVERS, which is a stated limitation rather than a
            # hidden one: a hole before the first record or after the last is outside anything
            # the archive knows, since no record carries the range that was requested. Closing
            # that edge needs the campaign's range, which `run_qc` is not given -- so the days
            # examined are counted and reported, and a reader can see the edge of the check
            # instead of trusting its silence.
            report.findings.extend(check_calendar_gaps(days, calendar, first, last))
            report.calendar_days_examined += sum(
                calendar.is_trading_day(first + timedelta(days=offset))
                for offset in range((last - first).days + 1)
            )
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

    # THE CALENDAR IS NOT OPTIONAL HERE. Without it `run_qc` cannot establish that two
    # sessions are adjacent, so the overnight-ratio check is skipped — silently. That is how
    # a QC pass over the real archive reported "6 records, 0 findings" while the check it had
    # just been given never ran: the number was true and meant nothing.
    calendar_path = Path("config/calendars/nse_equity.yaml")
    if not calendar_path.exists():
        print(f"qc: WARNING no calendar at {calendar_path} — the overnight-ratio check needs")
        print("    one to tell adjacent sessions from a gap, and will be SKIPPED without it.")
    # The verdict seam, connected to the M6 masters when a PIT store exists. Without one
    # there is no explainer and the ratio check fails closed — which is correct, and is said
    # out loud rather than looking like a clean pass.
    explain = jump_explainer(root / "pit")
    if explain is None:
        print(f"qc: no PIT store at {root / 'pit'} — no corporate action can explain a jump,")
        print("    so every ratio jump will be quarantined. That is fail-closed, not a pass.")

    report = run_qc(
        bronze,
        quarantine,
        fetched,
        calendar_path=calendar_path if calendar_path.exists() else None,
        explain_jump=explain,
    )
    if calendar_path.exists():
        from pips.core.calendar import load_calendar

        if not load_calendar(calendar_path).holidays_verified:
            print("qc: WARNING the holiday list is EMPTY and UNVERIFIED, so every weekday counts")
            print("    as a trading day. Two sessions really separated by a holiday therefore")
            print("    compute as NON-adjacent and their overnight-ratio comparison is SKIPPED —")
            print("    a genuine jump across a holiday goes unexamined. The skip count below is")
            print("    the honest measure of this check's coverage.")
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
