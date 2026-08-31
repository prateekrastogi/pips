"""Loading a parsed scrip master into the PIT instrument master  [C-DATA-01] (§6 M6).

The last step from a downloaded archive to a live master. Three properties:

**A re-ingest of the same file records nothing new.** The master is bitemporal and append-only,
so a daily snapshotter that rewrites every instrument every day turns 5,851 rows into 5,851
rows PER DAY, and a year of unchanged data becomes two million versions of nothing happening.
Only actual changes are versions.

**A changed field IS a new version, on the ingest date.** That is the whole point of the daily
snapshot: a symbol or token that moves becomes visible as a change with a date, rather than
overwriting the past.

**Rejected rows are carried through, not dropped at the boundary.** The parser refuses them
with reasons; an ingest that returns only a success count throws that away one layer up.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.scrip_ingest import UNKNOWN_LISTING_DATE, ingest_instruments
from pips.data.pit.store import PitStore

D = date


def instrument(**over: object) -> Instrument:
    base: dict[str, object] = {
        "isin": "INE002A01018",
        "exchange_token": "2885",
        "symbol": "RELIANCE",
        "name": "RELIANCE INDUSTRIES",
        "series": "EQ",
        "lot_size": 1,
        "tick_size_paise": 1,
        "vendor_code": "RELIND",
    }
    base.update(over)
    return Instrument.model_validate(base)


@pytest.fixture
def master(tmp_path: Path) -> InstrumentMaster:
    return InstrumentMaster(PitStore(tmp_path / "pit"))


def test_a_first_ingest_records_every_instrument(master: InstrumentMaster) -> None:
    result = ingest_instruments(
        master, [instrument()], known_from=D(2026, 8, 31), valid_from=UNKNOWN_LISTING_DATE
    )
    assert result.added == 1
    assert result.unchanged == 0
    assert len(master.as_of(D(2026, 8, 31), known_on=D(2026, 8, 31))) == 1


def test_re_ingesting_the_same_file_records_nothing_new(master: InstrumentMaster) -> None:
    """The property that keeps a daily snapshotter from becoming a daily rewrite.

    5,851 instruments re-recorded every day is two million versions a year of nothing
    happening — and it makes every genuine change impossible to find among them.
    """
    ingest_instruments(
        master, [instrument()], known_from=D(2026, 8, 31), valid_from=UNKNOWN_LISTING_DATE
    )
    again = ingest_instruments(
        master, [instrument()], known_from=D(2026, 9, 1), valid_from=UNKNOWN_LISTING_DATE
    )

    assert again.added == 0
    assert again.changed == 0
    assert again.unchanged == 1
    assert len(master.store.all_records("instruments")) == 1, "no second version was written"


def test_a_changed_field_becomes_a_new_version_dated_by_the_ingest(
    master: InstrumentMaster,
) -> None:
    ingest_instruments(
        master,
        [instrument(symbol="RELIANCE")],
        known_from=D(2026, 8, 31),
        valid_from=UNKNOWN_LISTING_DATE,
    )
    result = ingest_instruments(
        master,
        [instrument(symbol="RELIND")],
        known_from=D(2026, 9, 1),
        valid_from=UNKNOWN_LISTING_DATE,
    )

    assert result.changed == 1

    # KNOWLEDGE-pinned, not full knowledge, and that is a consequence worth naming: with an
    # unknown listing date both versions are valid from 1990, so valid time cannot separate
    # them and a full-knowledge read sees only the latest. Until a listing-date source exists,
    # the symbol history of these instruments is a KNOWLEDGE history, not a validity one.
    assert master.resolve_symbol("RELIANCE", on=D(2026, 8, 31), known_on=D(2026, 8, 31)) is not None
    assert master.resolve_symbol("RELIND", on=D(2026, 9, 1), known_on=D(2026, 9, 1)) is not None
    assert master.resolve_symbol("RELIND", on=D(2026, 9, 1), known_on=None) is not None
    assert master.symbol_history("INE002A01018") == [
        (D(2026, 8, 31), "RELIANCE"),
        (D(2026, 9, 1), "RELIND"),
    ]


def test_rejected_rows_are_carried_through_not_dropped(master: InstrumentMaster) -> None:
    from pips.data.pit.scrip_master import RejectedRow

    rejected = [RejectedRow("NOISIN", "", "no ISINCode — the master is ISIN-keyed")]
    result = ingest_instruments(
        master,
        [instrument()],
        known_from=D(2026, 8, 31),
        valid_from=UNKNOWN_LISTING_DATE,
        rejected=rejected,
    )
    assert result.rejected == 1
    assert "NOISIN" in result.describe()


def test_the_summary_accounts_for_every_input(master: InstrumentMaster) -> None:
    batch = [instrument(), instrument(isin="INE467B01029", vendor_code="TCS")]
    first = ingest_instruments(
        master, batch, known_from=D(2026, 8, 31), valid_from=UNKNOWN_LISTING_DATE
    )
    assert first.added + first.changed + first.unchanged == len(batch)

    second = ingest_instruments(
        master, batch, known_from=D(2026, 9, 1), valid_from=UNKNOWN_LISTING_DATE
    )
    assert second.added + second.changed + second.unchanged == len(batch)


def test_ingesting_nothing_is_refused(master: InstrumentMaster) -> None:
    # An empty ingest reports a clean run over no data, which reads like a successful one.
    with pytest.raises(ValueError, match="no instruments"):
        ingest_instruments(master, [], known_from=D(2026, 8, 31), valid_from=UNKNOWN_LISTING_DATE)


# ------------------------------------------- when the listing date is unknowable --------


def test_the_ingest_requires_an_explicit_validity_start(master: InstrumentMaster) -> None:
    """The ingest date is NOT when the instrument came into existence.

    Defaulting `valid_from` to the ingest date said RELIANCE began on 31 August, so every
    historical read excluded it and QC over August bronze resolved nothing. And the file
    cannot supply the truth: **all 5,873 rows have a blank `DateOfListing`** — measured, not
    assumed. So the caller states what it is asserting, because there is no correct default
    and the wrong one is silent.
    """
    with pytest.raises(TypeError):
        ingest_instruments(master, [instrument()], known_from=D(2026, 8, 31))  # type: ignore[call-arg]


def test_an_unknown_listing_date_resolves_for_earlier_bars(master: InstrumentMaster) -> None:
    from pips.data.pit.scrip_ingest import UNKNOWN_LISTING_DATE

    ingest_instruments(
        master, [instrument()], known_from=D(2026, 8, 31), valid_from=UNKNOWN_LISTING_DATE
    )
    found = master.resolve_vendor_code("RELIND", on=D(2026, 8, 28), known_on=None)
    assert found is not None


def test_the_sentinel_could_not_be_mistaken_for_a_measured_listing_date() -> None:
    """Obviously not real, on purpose.

    A plausible date gets mistaken for a measurement. NSE began trading in 1994, so a
    1990 date cannot be one — it reads as the assertion it is: *at or before anything we
    could have data for*, not *this is when the security listed*.
    """
    from pips.data.pit.scrip_ingest import UNKNOWN_LISTING_DATE

    assert D(1994, 1, 1) > UNKNOWN_LISTING_DATE


def test_two_names_sharing_a_code_with_unknown_listing_dates_are_refused_not_guessed(
    master: InstrumentMaster,
) -> None:
    """What the sentinel costs, and why it is acceptable.

    Unknown listing dates mean a reused code has two claimants overlapping in valid time, and
    valid time can no longer separate them. That is a real loss — but it degrades to the
    master's existing REFUSAL to guess, which is loud, rather than to a silent splice of two
    companies into one price series. A wrong answer would be undetectable; this is not.
    """
    from pips.data.pit.instruments import AmbiguousSymbolError
    from pips.data.pit.scrip_ingest import UNKNOWN_LISTING_DATE

    ingest_instruments(
        master,
        [instrument(), instrument(isin="INE467B01029", symbol="TCS", vendor_code="RELIND")],
        known_from=D(2026, 8, 31),
        valid_from=UNKNOWN_LISTING_DATE,
    )
    with pytest.raises(AmbiguousSymbolError):
        master.resolve_vendor_code("RELIND", on=D(2026, 8, 28), known_on=None)
