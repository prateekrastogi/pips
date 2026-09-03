"""Bronze -> silver: raw vendor replies become bars anyone can read  (§6 M6).

Three trading days of real RELIND minute bars have been sitting in bronze on arb-vm with the
silver layer empty — fetched and never turned into anything.
:func:`pips.data.breeze.ingest.normalize_candles` already produces close-labelled integer-paise
bars; nothing persisted them or gave them an identity.

Three things must not go wrong quietly.

**The vendor code is not the symbol.** Bronze is keyed by ``RELIND``; the exchange calls it
``RELIANCE``. Only 172 of 5,851 instruments have the two equal, so passing the vendor code
through as the symbol would mislabel almost every name — and the bars would look perfectly
ordinary while joining to no universe, cost model or corporate action.

**A reply that is not data must never be written as data.** Breeze answers rate limits with
HTTP 200 and a body, so a throttled fetch written as bars becomes a day with no bars —
indistinguishable from a holiday, silently shortening every series built on it. Anything that is
not an OK response goes to quarantine WITH its reason.

**Promotion is idempotent.** Re-promoting the same bronze produces identical silver, or the
snapshot root of a rebuilt panel stops matching the one a trial pinned and ``[C-DATA-02]`` turns
from a guarantee into a coin flip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from pips.data.breeze.ingest import ResponseKind, classify_response, normalize_candles
from pips.data.qc.checks import (
    QcVerdicts,
    Severity,
    check_bar_sanity,
    check_monotonic_labels,
)

if TYPE_CHECKING:
    from pips.data.pit.instruments import InstrumentMaster

__all__ = ["PromotionReport", "Quarantined", "promote_bronze"]

IST = timezone(timedelta(hours=5, minutes=30))
_INTERVAL_MINUTES = 1


@dataclass(frozen=True)
class Quarantined:
    """A bronze file that did not become bars, and why.

    §3.4: never silently dropped. A file that vanishes between bronze and silver is a gap
    nobody can distinguish from a market that was closed.
    """

    source: str
    reason: str


@dataclass(frozen=True)
class PromotionReport:
    files_read: int
    files_promoted: int
    bars_written: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)
    refused_by_qc: int = 0
    # COVERAGE OF THE QC GATE, counted rather than assumed. An empty quarantine and a QC pass
    # that never ran are the same evidence, so promotion has to say how many records it
    # promoted with no verdict behind them -- "0 quarantined" over a record nobody checked is
    # not a clean bill, it is no bill at all.
    promoted_without_qc: int = 0

    def describe(self) -> str:
        return (
            f"promotion: read {self.files_read} file(s), promoted {self.files_promoted}, "
            f"{self.bars_written} bar(s); {len(self.quarantined)} quarantined "
            f"({self.refused_by_qc} by QC); {self.promoted_without_qc} promoted without QC"
        )

    def require_qc_coverage(self) -> None:
        """Refuse a panel built on records QC never examined.

        Follows :meth:`~pips.core.calendar.ExchangeCalendar.require_verified_holidays`, and for
        the same reason: the archive stays usable without the evidence, so research on fixtures
        works, and anything on the path to real capital has to ASK. A count alone would leave
        the decision to whoever remembered to read it.
        """
        if self.promoted_without_qc:
            raise RuntimeError(
                f"{self.promoted_without_qc} record(s) were promoted to silver with no QC "
                f"verdict behind them, out of {self.files_promoted} promoted. QC was not run "
                f"over them, which is not the same as QC finding nothing -- run `make qc` and "
                f"pass its verdicts to `promote_bronze`, or accept an unchecked panel "
                f"deliberately by not calling this."
            )


def _row(bar: Any, symbol: str, isin: str, received_at_ns: int) -> dict[str, Any]:
    stamp = datetime.combine(bar.trade_date, bar.close_label, tzinfo=IST)
    return {
        "close_ts_ns": int(stamp.timestamp() * 1_000_000_000),
        "symbol": symbol,
        "isin": isin,
        "open_paise": bar.open_paise,
        "high_paise": bar.high_paise,
        "low_paise": bar.low_paise,
        "close_paise": bar.close_paise,
        "volume": bar.volume,
        # Knowledge time, carried from the capture. Silver keeps its provenance so a bar can be
        # traced to the reply that produced it (§3.4 bitemporality).
        "received_at_ns": received_at_ns,
    }


def promote_bronze(
    bronze_root: Path,
    silver_root: Path,
    master: InstrumentMaster,
    *,
    known_on: date,
    qc: QcVerdicts | None = None,
) -> PromotionReport:
    """Turn every bronze capture under ``bronze_root`` into silver bars.

    ``qc`` carries what a QC pass examined and what it rejected (:class:`QcVerdicts`). It is
    OPTIONAL and defaults to None, which promotes everything and counts every record as
    unchecked -- the old behaviour, kept usable but never quiet. `None` is not "QC passed".

    Promotion still runs the checks it can run itself, below. Those are the ones needing
    nothing beyond the record; QC's remaining checks need the backfill manifest, the previous
    session and the corporate-action master, and quarantining on a guess would be worse than
    not checking. What promotion could not do before was find out whether QC had run at all.
    """
    rows: list[dict[str, Any]] = []
    quarantined: list[Quarantined] = []
    files_read = files_promoted = 0
    refused_by_qc = promoted_without_qc = 0

    # Sorted, so a rebuild produces the same file in the same order (rule 1).
    for path in sorted(bronze_root.rglob("*.json")):
        files_read += 1
        # A record this function cannot READ is the fourth quarantine reason, not an exception.
        # Bronze will not hold one shape forever -- a range-spanning capture, which is what a
        # cheap universe seed needs, has no single `trade_date` -- and a bare KeyError here
        # takes the whole run down and discards every reason already collected for every other
        # file. `request` is required rather than defaulted, too: a missing one used to produce
        # an empty vendor code, which then failed to resolve and quarantined under a reason
        # about identity rather than about shape.
        try:
            capture = json.loads(path.read_text(encoding="utf-8"))
            request = capture["request"]
            vendor_code = str(request.get("symbol", ""))
            trade_date = date.fromisoformat(str(request["trade_date"]))
            payload = capture["payload"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            quarantined.append(
                Quarantined(
                    str(path),
                    f"not a readable symbol-day capture ({error!r}). Promotion reads "
                    "request.symbol, request.trade_date and payload; a record without them "
                    "may be a different capture shape, or half-written.",
                )
            )
            continue

        # BEFORE any work on the record: a verdict QC already reached is not re-litigated here,
        # and re-normalizing a record QC rejected only risks promoting it on a disagreement.
        key = f"{vendor_code}:{trade_date.isoformat()}"
        verdict = qc.verdict_for(key) if qc else "UNEXAMINED"
        if verdict == "QUARANTINED":
            quarantined.append(
                Quarantined(
                    str(path),
                    f"QC quarantined this record ({key}). Promotion declines it rather than "
                    "re-deriving the verdict: QC sees the backfill manifest, the previous "
                    "session and the corporate-action master, and promotion sees none of them.",
                )
            )
            refused_by_qc += 1
            continue

        kind = classify_response(payload)
        if kind is not ResponseKind.OK:
            quarantined.append(
                Quarantined(str(path), f"reply classified {kind.value}, not data: {vendor_code}")
            )
            continue

        instrument = master.resolve_vendor_code(vendor_code, trade_date, known_on=known_on)
        if instrument is None:
            quarantined.append(
                Quarantined(
                    str(path),
                    f"vendor code {vendor_code!r} resolves to no instrument as of "
                    f"{trade_date} (known_on={known_on}). Refusing to write bars under the "
                    "vendor code: only 172 of 5,851 names have it equal to the exchange "
                    "symbol, so they would join to nothing while looking ordinary.",
                )
            )
            continue

        bars = normalize_candles(payload, trade_date, _INTERVAL_MINUTES)
        # THE CHECKS THIS PATH CAN RUN ITSELF. `check_bar_sanity` has caught a negative price
        # since M5, but QC is a separate pass that nothing invokes -- so promotion wrote
        # impossible bars into the panel with `quarantined: 0`, and downstream they poison every
        # return, every cross-sectional z and every cost line that touches them while looking
        # like data the whole way.
        #
        # Only the checks that need NOTHING BEYOND THE RECORD belong here. `check_session_
        # coverage` would call a two-bar record truncated -- correctly, in a QC pass that knows
        # from the backfill manifest that the fetch succeeded; promotion knows no such thing and
        # would be quarantining partial records on a guess. Same for the ratio jump, which needs
        # the previous session and the corporate-action master.
        #
        # The record is quarantined WHOLE rather than having the bad bar dropped: a silent
        # repair hides the thing it repairs, and a record with one impossible bar is not
        # trustworthy in its others.
        failures = [
            f
            for f in (*check_bar_sanity(bars), *check_monotonic_labels(bars))
            if f.severity is Severity.QUARANTINE
        ]
        if failures:
            detail = "; ".join(f"{f.check}: {f.detail}" for f in failures[:3])
            more = "" if len(failures) <= 3 else f" (and {len(failures) - 3} more)"
            quarantined.append(
                Quarantined(
                    str(path),
                    f"{len(failures)} bar(s) fail the checks promotion runs -- {detail}{more}. "
                    "Refusing the record whole: dropping the bad bars would be a silent repair.",
                )
            )
            continue
        if not bars:
            quarantined.append(
                Quarantined(str(path), f"no bars survived normalization for {vendor_code}")
            )
            continue

        # Knowledge time is not optional. Defaulting a missing stamp to 0 wrote a bar claiming
        # it was known since 1970 -- which is not unknown, it is EARLY: it sorts before and
        # reads inside every as-of knowledge window there is (§3.4). A bar we cannot date is
        # the same kind of problem as a bar we cannot name, and gets the same answer.
        #
        # `bool` is an `int` and `True > 0`, so a stamp of `true` would otherwise pass and date
        # the bars one nanosecond after the epoch.
        received = capture.get("received_at_ns")
        if not isinstance(received, int) or isinstance(received, bool) or received <= 0:
            quarantined.append(
                Quarantined(
                    str(path),
                    f"capture carries no usable received_at_ns ({received!r}) for "
                    f"{vendor_code}. Refusing to stamp the bars with the epoch: silver's "
                    "knowledge time is its provenance, and a 0 reads as known-since-1970.",
                )
            )
            continue
        rows.extend(_row(bar, instrument.symbol, instrument.isin, received) for bar in bars)
        files_promoted += 1
        if verdict == "UNEXAMINED":
            # Counted HERE rather than at the top, so the number means "promoted with no
            # verdict" and not "seen with no verdict". A record QC never examined and promotion
            # then quarantined for its own reasons is not an unchecked bar in the panel.
            promoted_without_qc += 1

    rows.sort(key=lambda r: (r["close_ts_ns"], r["symbol"]))
    silver_root.mkdir(parents=True, exist_ok=True)
    if rows:
        pl.DataFrame(rows).write_parquet(silver_root / "bars_1m.parquet")

    return PromotionReport(
        files_read=files_read,
        files_promoted=files_promoted,
        bars_written=len(rows),
        rows=rows,
        quarantined=quarantined,
        refused_by_qc=refused_by_qc,
        promoted_without_qc=promoted_without_qc,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``pips promote <data_root> --known-on YYYY-MM-DD [--require-qc]``.

    `promote_bronze` had no caller outside tests, which left the QC gate unreachable: `pips qc`
    writes its verdicts and prints "pass them to promote_bronze(qc=...)", and nothing could.

    **The default is loud rather than strict**, unlike `pips capture`. Promotion spends nothing
    and touches no live path, so refusing without QC would make the fixture workflow unusable to
    prevent a harm that only exists downstream. It follows `require_verified_holidays` instead --
    usable without the evidence, never silent without it -- and `--require-qc` is the hard
    refusal for anything on the path to real capital.
    """
    import argparse
    import os
    import sys

    from pips.data.pit.instruments import InstrumentMaster
    from pips.data.pit.store import PitStore
    from pips.data.qc.checks import QcVerdicts

    parser = argparse.ArgumentParser(prog="pips promote")
    parser.add_argument("data_root", nargs="?", default=None, help="defaults to $PIPS_DATA_ROOT")
    parser.add_argument(
        "--known-on",
        required=True,
        help="the as-of knowledge date for instrument resolution; NOT defaulted, because a "
        "bitemporal read that moves is the one thing §3.4 forbids",
    )
    parser.add_argument("--require-qc", action="store_true", help="refuse unchecked records")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    root = (
        Path(args.data_root)
        if args.data_root
        else Path(os.environ.get("PIPS_DATA_ROOT", "/srv/pips"))
    )
    bronze, silver = root / "bronze", root / "silver"
    if not bronze.exists():
        print(f"promote: no bronze at {bronze} — nothing to promote.")
        print("    That is not a pass. Run a backfill first (ops/runbooks/backfill.md).")
        return 0

    pit = root / "pit"
    if not pit.exists():
        # Up front, not per record. Without a master every vendor code resolves to nothing and
        # every record quarantines under a reason about IDENTITY -- true of each record and
        # useless about the run, sending the operator after a data problem that is really a
        # missing PIT store.
        print(
            f"promote: no instrument master at {pit}. Every vendor code would resolve to "
            "nothing and every record would quarantine under an identity reason, which is a "
            "true statement about each record and a misleading one about the run.",
            file=sys.stderr,
        )
        return 2

    verdict_path = root / "state" / "qc-verdicts.json"
    qc = None
    if verdict_path.exists():
        qc = QcVerdicts.load(verdict_path, bronze_root=bronze)
        print(f"promote: QC verdicts from {verdict_path}")
    else:
        print(f"promote: no QC verdicts at {verdict_path} — every record counts as unchecked.")
        print("    Run `make qc` first; promotion does not re-derive what QC sees.")

    report = promote_bronze(
        bronze,
        silver,
        InstrumentMaster(PitStore(pit)),
        known_on=date.fromisoformat(args.known_on),
        qc=qc,
    )
    print(f"  {report.describe()}")
    for entry in report.quarantined[:5]:
        print(f"    quarantined {entry.source}: {entry.reason[:110]}")
    if len(report.quarantined) > 5:
        print(f"    ... and {len(report.quarantined) - 5} more")

    if args.require_qc:
        try:
            report.require_qc_coverage()
        except RuntimeError as refusal:
            print(f"promote: {refusal}", file=sys.stderr)
            return 1
    return 0
