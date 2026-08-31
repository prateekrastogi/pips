"""NSE scrip-master parser  [C-DATA-01] (§6 M6, rule 13 / SAL-0026 NONE_FOUND).

The ICICI security master is the only source of ISIN, series, lot and tick for the instrument
master: `get_names` returns none of them, and the SDK's own loader keeps only code and token
(see `docs/reports/feasibility/breeze-security-master.md`). This parses the raw
`NSEScripMaster.txt` from the archive.

Three things the real file taught, each contradicting an assumption:

**`Symbol` is empty; the NSE symbol is in `ExchangeCode`.** And `ShortName` is ICICI's own code
— RELIND, not RELIANCE. Both are identifiers and they are NOT interchangeable: pips' bronze is
keyed by the ICICI code, while a future broker will use the exchange symbol. Storing one and
calling it "the symbol" is precisely the identity conflation the master exists to prevent.

**`ticksize` is `0.01` — one paise, not five.** Every fixture I have written so far assumed 5.
The value was never measured until now.

**20 of 5,873 rows have no ISIN.** The master is ISIN-keyed, so they cannot enter it — and they
must be REJECTED WITH A REASON, not silently skipped. Twenty instruments vanishing without
trace is how a universe quietly shrinks.

Columns are read by HEADER NAME, never by position. The donor SDK indexes positionally, which
breaks silently the day the vendor inserts a column — and inserts it into the wrong field
rather than failing.
"""

from __future__ import annotations

import pytest

from pips.data.pit.scrip_master import (
    REQUIRED_COLUMNS,
    RejectedRow,
    parse_nse_scrip_master,
)

HEADER = (
    "Token,ShortName,Series,CompanyName,ticksize,Lotsize,ISINCode,Symbol,"
    "DateOfDeListing,ExchangeCode"
)


def row(**over: str) -> str:
    base = {
        "Token": "2885",
        "ShortName": "RELIND",
        "Series": "EQ",
        "CompanyName": "RELIANCE INDUSTRIES",
        "ticksize": "0.01",
        "Lotsize": "1",
        "ISINCode": "INE002A01018",
        "Symbol": "",
        "DateOfDeListing": "",
        "ExchangeCode": "RELIANCE",
    }
    base.update(over)
    return ",".join(base[c] for c in HEADER.split(","))


def parse(*rows: str) -> object:
    return parse_nse_scrip_master("\n".join([HEADER, *rows]))


# ------------------------------------------------------------ the two identifiers ------


def test_the_vendor_code_and_the_exchange_symbol_are_both_kept() -> None:
    """RELIND is ICICI's code; RELIANCE is the exchange's. Neither is "the symbol".

    pips' bronze is keyed by the ICICI code, and a future broker will use the exchange symbol.
    Storing one and calling it the symbol makes every join silently wrong for the other.
    """
    result = parse(row())
    instrument = result.instruments[0]  # type: ignore[attr-defined]
    assert instrument.vendor_code == "RELIND"
    assert instrument.symbol == "RELIANCE"
    assert instrument.isin == "INE002A01018"


def test_an_empty_symbol_column_is_not_mistaken_for_the_exchange_symbol() -> None:
    # The real file leaves `Symbol` blank on every row. A parser reading it would produce a
    # master where every instrument's symbol is the empty string — and every lookup misses.
    result = parse(row(Symbol=""))
    assert result.instruments[0].symbol == "RELIANCE"  # type: ignore[attr-defined]


# ------------------------------------------------------------ measured, not assumed ----


def test_the_tick_size_is_read_as_paise_from_rupees() -> None:
    # 0.01 rupees is ONE paise. Every fixture written before this file assumed five.
    result = parse(row(ticksize="0.01"))
    assert result.instruments[0].tick_size_paise == 1  # type: ignore[attr-defined]


def test_a_larger_tick_converts_correctly() -> None:
    result = parse(row(ticksize="0.05"))
    assert result.instruments[0].tick_size_paise == 5  # type: ignore[attr-defined]


# ------------------------------------------------------------ rejected, not dropped ----


def test_a_row_without_an_isin_is_rejected_with_a_reason() -> None:
    """Twenty of 5,873 real rows have no ISIN.

    The master is ISIN-keyed so they cannot enter it — but silently skipping them is how a
    universe quietly shrinks by twenty names that nobody ever knows were dropped.
    """
    result = parse(row(), row(ShortName="NOISIN", ISINCode="", ExchangeCode="NOISIN"))
    assert len(result.instruments) == 1  # type: ignore[attr-defined]
    assert len(result.rejected) == 1  # type: ignore[attr-defined]
    rejected: RejectedRow = result.rejected[0]  # type: ignore[attr-defined]
    assert rejected.vendor_code == "NOISIN"
    assert "ISIN" in rejected.reason


def test_a_malformed_isin_is_rejected_rather_than_stored() -> None:
    result = parse(row(ISINCode="NOTANISIN"))
    assert result.instruments == []  # type: ignore[attr-defined]
    assert len(result.rejected) == 1  # type: ignore[attr-defined]


def test_every_input_row_is_accounted_for() -> None:
    # The accounting identity: parsed plus rejected equals rows in. A parser that can lose a
    # row without either counter moving is a parser whose totals mean nothing.
    rows = [
        row(),
        row(ShortName="X", ISINCode="", ExchangeCode="X"),
        row(ShortName="Y", ISINCode="INE467B01029", ExchangeCode="TCS"),
        row(ShortName="Z", ISINCode="bad", ExchangeCode="Z"),
    ]
    result = parse(*rows)
    assert len(result.instruments) + len(result.rejected) == len(rows)  # type: ignore[attr-defined]


# ------------------------------------------------------------ by name, not position ----


def test_columns_are_read_by_name_so_an_inserted_column_does_not_shift_fields() -> None:
    """The donor SDK indexes positionally. A vendor inserting a column then puts every later
    field into the wrong slot — silently, because the values are all strings.
    """
    header = (
        "Token,NewVendorColumn,ShortName,Series,CompanyName,ticksize,Lotsize,"
        "ISINCode,Symbol,DateOfDeListing,ExchangeCode"
    )
    line = "2885,junk,RELIND,EQ,RELIANCE INDUSTRIES,0.01,1,INE002A01018,,,RELIANCE"
    result = parse_nse_scrip_master("\n".join([header, line]))
    assert result.instruments[0].vendor_code == "RELIND"
    assert result.instruments[0].isin == "INE002A01018"


def test_a_missing_required_column_is_refused_loudly() -> None:
    # Not "parse what we can". A file without ISINCode produces zero instruments, and a parser
    # that returns an empty list for that reads identically to a file with no equities in it.
    with pytest.raises(ValueError, match="ISINCode"):
        parse_nse_scrip_master("Token,ShortName\n2885,RELIND")


def test_the_required_columns_are_declared() -> None:
    assert "ISINCode" in REQUIRED_COLUMNS
    assert "ExchangeCode" in REQUIRED_COLUMNS
    assert "ShortName" in REQUIRED_COLUMNS
