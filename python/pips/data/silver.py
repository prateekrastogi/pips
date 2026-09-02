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
from typing import TYPE_CHECKING, Any

import polars as pl

from pips.data.breeze.ingest import ResponseKind, classify_response, normalize_candles

if TYPE_CHECKING:
    from pathlib import Path

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
) -> PromotionReport:
    """Turn every bronze capture under ``bronze_root`` into silver bars."""
    rows: list[dict[str, Any]] = []
    quarantined: list[Quarantined] = []
    files_read = files_promoted = 0

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
    )
