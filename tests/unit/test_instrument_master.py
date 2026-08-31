"""Point-in-time instrument master  [C-DATA-01] (§6 M6, §3.4, rule 13 / SAL-0026 NONE_FOUND).

The master answers one question in both directions: *which security was this, then?*

A symbol is a label the exchange lends out, not an identity. NSE frees a symbol when a name
delists and can lend the same letters to a different company later. A join on symbol across
that boundary splices two companies' price histories into one series — and the result looks
like a stock that changed character, not like a bug. Nothing downstream can detect it, because
by then the two are one column.

So the master is keyed on ISIN, the durable identity, and symbol and exchange token are
attributes with histories. Resolution is always as-of, and an ambiguous resolution is REFUSED
rather than guessed: picking the first match would be right most of the time, which is exactly
what makes it dangerous.

Written from scratch per SAL-0026 (NONE_FOUND across all three donor repos, every ref), and
bitemporal from the first line rather than retrofitted.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.instruments import AmbiguousSymbolError, Instrument, InstrumentMaster
from pips.data.pit.store import PitStore

D = date


def resolved(found: Instrument | None) -> Instrument:
    """Assert a resolution succeeded and narrow the type.

    `resolve_*` returns None deliberately — an unclaimed symbol has no answer, and that case
    carries real weight in this file. mypy --strict is right to insist the tests say which
    outcome they expect rather than reaching through the Optional.
    """
    assert found is not None, "expected the symbol/token to resolve"
    return found


@pytest.fixture
def master(tmp_path: Path) -> InstrumentMaster:
    return InstrumentMaster(PitStore(tmp_path / "pit"))


def instrument(isin: str, symbol: str, token: str = "1", name: str = "Some Ltd") -> Instrument:
    return Instrument(
        isin=isin,
        exchange_token=token,
        symbol=symbol,
        name=name,
        series="EQ",
        lot_size=1,
        tick_size_paise=5,
    )


# ------------------------------------------------------- the reused symbol -------------


def test_a_reused_symbol_resolves_to_the_right_company_on_each_date(
    master: InstrumentMaster,
) -> None:
    """The failure the master exists to prevent.

    ACME delists in June and the exchange lends "ACME" to a different company in August. A
    symbol-keyed join across that boundary produces one price series out of two companies —
    and it looks like a stock that changed character, not like a bug.
    """
    master.upsert(instrument("INE001A01036", "ACME", token="100"), known_from=D(2026, 1, 1))
    master.delist("INE001A01036", known_from=D(2026, 6, 1))
    master.upsert(instrument("INE999A01018", "ACME", token="900"), known_from=D(2026, 8, 1))

    assert resolved(master.resolve_symbol("ACME", on=D(2026, 3, 1))).isin == "INE001A01036"
    assert resolved(master.resolve_symbol("ACME", on=D(2026, 9, 1))).isin == "INE999A01018"


def test_a_symbol_resolves_to_nothing_in_the_gap(master: InstrumentMaster) -> None:
    # Between the delisting and the reassignment the symbol belongs to nobody. Returning the
    # old holder "because it was most recent" is how the splice happens.
    master.upsert(instrument("INE001A01036", "ACME"), known_from=D(2026, 1, 1))
    master.delist("INE001A01036", known_from=D(2026, 6, 1))
    master.upsert(instrument("INE999A01018", "ACME"), known_from=D(2026, 8, 1))
    assert master.resolve_symbol("ACME", on=D(2026, 7, 1)) is None


def test_two_live_claims_on_one_symbol_are_refused_not_guessed(master: InstrumentMaster) -> None:
    """Refusing beats guessing, precisely because guessing would usually be right.

    A duplicate symbol means the master is wrong — a missed delisting, a bad ingest, a series
    collision. Picking one silently buries the evidence under a plausible answer.
    """
    master.upsert(instrument("INE001A01036", "ACME", token="100"), known_from=D(2026, 1, 1))
    master.upsert(instrument("INE999A01018", "ACME", token="900"), known_from=D(2026, 2, 1))
    with pytest.raises(AmbiguousSymbolError) as excinfo:
        master.resolve_symbol("ACME", on=D(2026, 3, 1))
    # BOTH claimants named. An ambiguity error that does not say who is ambiguous leaves the
    # reader to go and find them, which is the work the error was in a position to do.
    assert "INE001A01036" in str(excinfo.value)
    assert "INE999A01018" in str(excinfo.value)


# ------------------------------------------------------- change history ----------------


def test_a_rename_keeps_the_isin_so_a_join_survives_it(master: InstrumentMaster) -> None:
    master.upsert(instrument("INE002A01018", "RELIANCE"), known_from=D(2026, 1, 1))
    master.rename("INE002A01018", symbol="RELIND", known_from=D(2026, 5, 1))

    assert resolved(master.resolve_symbol("RELIANCE", on=D(2026, 3, 1))).isin == "INE002A01018"
    assert resolved(master.resolve_symbol("RELIND", on=D(2026, 6, 1))).isin == "INE002A01018"
    assert master.resolve_symbol("RELIANCE", on=D(2026, 6, 1)) is None


def test_the_symbol_history_is_readable_with_its_dates(master: InstrumentMaster) -> None:
    master.upsert(instrument("INE002A01018", "RELIANCE"), known_from=D(2026, 1, 1))
    master.rename("INE002A01018", symbol="RELIND", known_from=D(2026, 5, 1))
    assert master.symbol_history("INE002A01018") == [
        (D(2026, 1, 1), "RELIANCE"),
        (D(2026, 5, 1), "RELIND"),
    ]


def test_an_exchange_token_change_is_tracked_too(master: InstrumentMaster) -> None:
    # Tokens are the broker's handle and they get reassigned. A cached token->symbol map built
    # once and reused is the same splice in a different field.
    master.upsert(instrument("INE467B01029", "TCS", token="11536"), known_from=D(2026, 1, 1))
    master.retoken("INE467B01029", exchange_token="22222", known_from=D(2026, 5, 1))

    assert resolved(master.resolve_token("11536", on=D(2026, 3, 1))).isin == "INE467B01029"
    assert resolved(master.resolve_token("22222", on=D(2026, 6, 1))).isin == "INE467B01029"
    assert master.resolve_token("11536", on=D(2026, 6, 1)) is None


def test_a_reassigned_token_resolves_to_the_new_holder(master: InstrumentMaster) -> None:
    master.upsert(instrument("INE467B01029", "TCS", token="11536"), known_from=D(2026, 1, 1))
    master.retoken("INE467B01029", exchange_token="22222", known_from=D(2026, 5, 1))
    master.upsert(instrument("INE075A01022", "WIPRO", token="11536"), known_from=D(2026, 6, 1))
    assert resolved(master.resolve_token("11536", on=D(2026, 7, 1))).isin == "INE075A01022"


def test_amending_an_unknown_isin_is_refused(master: InstrumentMaster) -> None:
    with pytest.raises(KeyError, match="INE404Z01011"):
        master.rename("INE404Z01011", symbol="X", known_from=D(2026, 5, 1))
    with pytest.raises(KeyError, match="INE404Z01011"):
        master.retoken("INE404Z01011", exchange_token="9", known_from=D(2026, 5, 1))
    with pytest.raises(KeyError, match="INE404Z01011"):
        master.delist("INE404Z01011", known_from=D(2026, 5, 1))


# ------------------------------------------------------- as-of reads -------------------


def test_the_master_reads_as_of_a_past_date(master: InstrumentMaster) -> None:
    master.upsert(instrument("INE002A01018", "RELIANCE"), known_from=D(2026, 1, 1))
    master.upsert(instrument("INE009A01021", "LATER"), known_from=D(2026, 7, 1))
    assert [i.isin for i in master.as_of(D(2026, 3, 1))] == ["INE002A01018"]
    assert [i.isin for i in master.as_of(D(2026, 8, 1))] == ["INE002A01018", "INE009A01021"]


def test_a_past_read_does_not_move_when_the_master_grows(master: InstrumentMaster) -> None:
    # Inherited from PitStore, asserted here because the master is what callers touch and an
    # inherited guarantee that nothing re-checks at this level is a guarantee by assumption.
    master.upsert(instrument("INE002A01018", "RELIANCE"), known_from=D(2026, 1, 1))
    before = master.snapshot_root(D(2026, 3, 1))
    master.upsert(instrument("INE009A01021", "LATER"), known_from=D(2026, 7, 1))
    master.rename("INE002A01018", symbol="RELIND", known_from=D(2026, 8, 1))
    assert master.snapshot_root(D(2026, 3, 1)) == before


def test_a_delisted_name_is_still_readable_before_its_delisting(master: InstrumentMaster) -> None:
    master.upsert(instrument("INE001A01036", "ACME"), known_from=D(2026, 1, 1))
    master.delist("INE001A01036", known_from=D(2026, 6, 1))
    assert [i.isin for i in master.as_of(D(2026, 3, 1))] == ["INE001A01036"]
    assert master.as_of(D(2026, 7, 1)) == []


# ------------------------------------------------------- shape -------------------------


def test_an_isin_that_is_not_an_isin_is_refused() -> None:
    for bad in ("", "INE", "US0378331005X", "ine002a01018"):
        with pytest.raises(ValueError, match="ISIN"):
            instrument(bad, "ACME")


def test_a_token_change_does_not_appear_as_a_symbol_change(master: InstrumentMaster) -> None:
    """Every amendment writes a new version, so a naive history reports them all.

    `symbol_history` deduplicates on the symbol for that reason — and a mutation run proved
    the claim was untested: removing the dedup killed nothing, because the existing history
    test only ever changed the symbol. A docstring is not a test.
    """
    master.upsert(instrument("INE002A01018", "RELIANCE", token="2885"), known_from=D(2026, 1, 1))
    master.retoken("INE002A01018", exchange_token="99999", known_from=D(2026, 3, 1))
    master.rename("INE002A01018", symbol="RELIND", known_from=D(2026, 5, 1))

    assert master.symbol_history("INE002A01018") == [
        (D(2026, 1, 1), "RELIANCE"),
        (D(2026, 5, 1), "RELIND"),
    ], "the token change must not appear as a renaming that never happened"
    assert master.token_history("INE002A01018") == [
        (D(2026, 1, 1), "2885"),
        (D(2026, 3, 1), "99999"),
    ]


def test_amending_a_delisted_instrument_is_refused_comprehensibly(
    master: InstrumentMaster,
) -> None:
    """A delisting is a tombstone with no payload, and the first version walked straight into
    it: `rename` after `delist` raised a seven-error pydantic ValidationError about missing
    fields on `{}`. That is a real mistake — amending a security that no longer exists —
    reported as if the master were corrupt.
    """
    master.upsert(instrument("INE001A01036", "ACME"), known_from=D(2026, 1, 1))
    master.delist("INE001A01036", known_from=D(2026, 6, 1))

    for call in ("rename", "retoken", "delist"):
        with pytest.raises(LookupError, match="delisted"):
            {
                "rename": lambda: master.rename(
                    "INE001A01036", symbol="NEW", known_from=D(2026, 7, 1)
                ),
                "retoken": lambda: master.retoken(
                    "INE001A01036", exchange_token="9", known_from=D(2026, 7, 1)
                ),
                "delist": lambda: master.delist("INE001A01036", known_from=D(2026, 7, 1)),
            }[call]()


def test_a_delisted_instrument_can_be_relisted_by_upsert(master: InstrumentMaster) -> None:
    # Refusing to AMEND a delisted instrument must not mean refusing to bring it back. A
    # relisting is a new fact about an existing ISIN, which is exactly what upsert records.
    master.upsert(instrument("INE001A01036", "ACME"), known_from=D(2026, 1, 1))
    master.delist("INE001A01036", known_from=D(2026, 6, 1))
    master.upsert(instrument("INE001A01036", "ACME2"), known_from=D(2026, 9, 1))
    assert resolved(master.resolve_symbol("ACME2", on=D(2026, 10, 1))).isin == "INE001A01036"
