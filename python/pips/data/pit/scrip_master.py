"""NSE scrip-master parser  [C-DATA-01] (§6 M6, rule 13 / SAL-0026 NONE_FOUND).

The ICICI security master is the only source of ISIN, series, lot and tick for the instrument
master: ``get_names`` returns none of them, and the SDK's own loader keeps only code and token
(``docs/reports/feasibility/breeze-security-master.md``). This parses the raw
``NSEScripMaster.txt`` from that archive.

Three things the real file taught, each contradicting an assumption held until it was read:

**``Symbol`` is empty on every row; the exchange symbol lives in ``ExchangeCode``.** And
``ShortName`` is ICICI's own code — RELIND, not RELIANCE. Both are identifiers and they are not
interchangeable: pips' bronze is keyed by the vendor code, while a broker order carries the
exchange symbol. A master storing one of them and calling it "the symbol" makes every join
silently wrong for the other.

**``ticksize`` is ``0.01`` — one paise.** Every fixture written before this file assumed five.
The value had simply never been measured.

**20 of 5,873 rows carry no ISIN.** The master is ISIN-keyed so they cannot enter it, and they
are REJECTED WITH A REASON rather than skipped. Twenty instruments vanishing without trace is
how a universe quietly shrinks.

Columns are read by HEADER NAME, never by position. The donor SDK indexes positionally, which
breaks the day the vendor inserts a column — and breaks silently, putting every later value
into the wrong field, because they are all strings.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from pydantic import ValidationError

from pips.core.money import rupees_to_paise
from pips.data.pit.instruments import Instrument

__all__ = ["REQUIRED_COLUMNS", "ParseResult", "RejectedRow", "parse_nse_scrip_master"]

REQUIRED_COLUMNS: Final = (
    "Token",
    "ShortName",
    "Series",
    "CompanyName",
    "ticksize",
    "Lotsize",
    "ISINCode",
    "ExchangeCode",
)


@dataclass(frozen=True)
class RejectedRow:
    """A row that could not become an instrument, and why.

    The reason is not decoration. A count of rejects tells you the universe shrank; the reason
    tells you whether that is a vendor quirk to accept or an ingest bug to fix.
    """

    vendor_code: str
    isin: str
    reason: str


@dataclass(frozen=True)
class ParseResult:
    """Everything parsed and everything refused. The two together are the input."""

    instruments: list[Instrument] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)

    @property
    def rows_in(self) -> int:
        """Parsed plus rejected. A parser that can lose a row without either counter moving
        is a parser whose totals mean nothing."""
        return len(self.instruments) + len(self.rejected)


def parse_nse_scrip_master(text: str) -> ParseResult:
    """Parse ``NSEScripMaster.txt`` into instruments and explicit rejections."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().strip('"') for h in next(reader)]
    except StopIteration:
        raise ValueError("scrip master is empty — no header row") from None

    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        # Not "parse what we can". A file without ISINCode yields zero instruments, and an
        # empty list reads identically to a file that genuinely contains no equities.
        raise ValueError(
            f"scrip master is missing required column(s): {', '.join(missing)}. Parsing what "
            "remains would produce an empty or partial master indistinguishable from a real one."
        )
    index = {name: i for i, name in enumerate(header)}

    instruments: list[Instrument] = []
    rejected: list[RejectedRow] = []
    for row in reader:
        if not row or len(row) <= max(index[c] for c in REQUIRED_COLUMNS):
            continue

        def value(column: str, row: list[str] = row) -> str:
            return row[index[column]].strip().strip('"').strip()

        vendor_code, isin = value("ShortName"), value("ISINCode")
        if not isin:
            rejected.append(
                RejectedRow(vendor_code, isin, "no ISINCode — the master is ISIN-keyed")
            )
            continue
        try:
            instruments.append(
                Instrument(
                    isin=isin,
                    exchange_token=value("Token"),
                    symbol=value("ExchangeCode"),
                    name=value("CompanyName"),
                    series=value("Series"),
                    lot_size=int(value("Lotsize") or 1),
                    tick_size_paise=int(rupees_to_paise(Decimal(value("ticksize") or "0.01"))),
                    vendor_code=vendor_code,
                )
            )
        except ValidationError as exc:
            # The FIELD and the message, not pydantic's "1 validation error for Instrument".
            # The reason exists so a reader can tell a vendor quirk from an ingest bug, and
            # a bare count supports neither decision.
            detail = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            rejected.append(RejectedRow(vendor_code, isin, detail))
        except (ValueError, ArithmeticError) as exc:
            rejected.append(RejectedRow(vendor_code, isin, str(exc).splitlines()[0]))
    return ParseResult(instruments=instruments, rejected=rejected)
