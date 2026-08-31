"""Breeze response classification and bar normalization  (§6 M4).

**Ported from SAL-0002 and SAL-0003** (`intraday be8186d`), which between them carry three
facts that cost someone real time to learn and would cost it again:

1. *Rate rejection is not HTTP 429.* It arrives in the JSON body as ``{"Status": 5, "Error":
   "Limit exceed..."}``. A client that checks the HTTP status sees a 200 with an empty payload
   and records a gap — data corruption that no later QC can tell apart from a quiet market.
2. *``from_date``/``to_date`` are IST wall-clock and the trailing ``Z`` is ignored.* Sending
   real UTC silently clips the window rather than erroring.
3. *Real enforcement is stricter than published.* Pace well under the cap.

To which the M3 probe adds two more, measured here rather than inherited:

4. *Breeze is OPEN-labelled.* A candle stamped ``t`` covers ``[t, t+interval)``, so ingest adds
   one interval to reach pips' close-labelled convention [C-BAR-01]. Skipping that is a
   uniform one-bar lookahead across every backtest.
5. *A widened window returns bars from other market phases* — pre-open and post-close prints
   — without erroring. Ingest clips to the continuous session (§3.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

__all__ = [
    "NormalizedBar",
    "ResponseKind",
    "classify_response",
    "normalize_candles",
    "rupees_to_paise",
]

# The NSE continuous session. Held here rather than imported from the calendar because the
# calendar is per-exchange data and this is the vendor adapter; M6 wires them together.
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)


class ResponseKind(StrEnum):
    """What a Breeze reply actually is."""

    OK = "OK"
    EMPTY = "EMPTY"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"

    @property
    def carries_data(self) -> bool:
        """Only OK carries usable rows. Everything else must not be written as data."""
        return self is ResponseKind.OK


def classify_response(payload: dict[str, Any]) -> ResponseKind:
    """Classify a ``get_historical_data_v2`` reply.

    The RATE_LIMITED branch is the load-bearing one: the rejection is in the body, not the
    HTTP status, so a caller that does not look for it will happily record an empty window as
    "no trades". EMPTY is distinct and legitimate -- a non-trading day returns nothing, and
    treating that as an error would halt a backfill on every holiday.
    """
    status = payload.get("Status")
    error = str(payload.get("Error") or "")
    if status == 5 or "limit exceed" in error.lower():
        return ResponseKind.RATE_LIMITED
    if payload.get("Success"):
        return ResponseKind.OK
    if error or (status is not None and status != 200):
        return ResponseKind.ERROR
    return ResponseKind.EMPTY


def rupees_to_paise(value: Any) -> int:
    """Exact rupees -> integer paise [C-NUM-01].

    Via ``Decimal(str(...))``: the vendor sends JSON numbers, and ``float * 100`` on 1285.4
    gives 128539.99999999999. Truncating that loses a paisa on a value the exchange considers
    exact, and the error is not uniform across prices.
    """
    return int((Decimal(str(value)) * 100).to_integral_value())


@dataclass(frozen=True)
class NormalizedBar:
    """One bar in pips' conventions: close-labelled, integer paise."""

    trade_date: date
    close_label: time
    open_paise: int
    high_paise: int
    low_paise: int
    close_paise: int
    volume: int


def _parse_stamp(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "").strip())


def normalize_candles(
    payload: dict[str, Any], trade_date: date, interval_minutes: int
) -> list[NormalizedBar]:
    """Vendor candles -> close-labelled, session-clipped, integer-paise bars.

    Missing minutes stay missing. §3.4 insists a zero-volume bar is not a missing bar, and
    Breeze hands us the missing case by omitting untraded minutes -- so inventing them here
    would manufacture a price claim nobody made, in the one place it would be invisible.
    """
    kind = classify_response(payload)
    if kind is ResponseKind.RATE_LIMITED:
        raise ValueError(
            "refusing to normalize a rate-limited reply: Breeze returns the rejection in the "
            "body (Status 5), so treating it as data would record a gap that looks like a "
            "quiet market"
        )
    if not kind.carries_data:
        return []

    shift = timedelta(minutes=interval_minutes)
    bars: list[NormalizedBar] = []
    for row in payload["Success"]:
        stamp = _parse_stamp(row["datetime"])
        # OPEN-labelled -> CLOSE-labelled: the bar stamped t covers [t, t+interval).
        close_at = (stamp + shift).time()
        # Clip to the continuous session. A widened window silently returns pre-open and
        # post-close prints, and neither belongs on the continuous tape (§3.5).
        if not (SESSION_OPEN < close_at <= SESSION_CLOSE):
            continue
        bars.append(
            NormalizedBar(
                trade_date=trade_date,
                close_label=close_at,
                open_paise=rupees_to_paise(row["open"]),
                high_paise=rupees_to_paise(row["high"]),
                low_paise=rupees_to_paise(row["low"]),
                close_paise=rupees_to_paise(row["close"]),
                volume=int(row["volume"]),
            )
        )
    return sorted(bars, key=lambda b: b.close_label)
