"""Point-in-time instrument master  [C-DATA-01] (§6 M6, §3.4).

Answers one question in both directions: *which security was this, then?*

**A symbol is a label the exchange lends out, not an identity.** NSE frees a symbol when a
name delists and can lend the same letters to a different company later. A join on symbol
across that boundary splices two companies' price histories into one series, and the result
looks like a stock that changed character rather than like a bug — by the time anything
downstream sees it, the two are a single column and no check can separate them.

So the master is keyed on ISIN, and symbol and exchange token are attributes with histories.
Every read is as-of. An ambiguous resolution is REFUSED rather than guessed: a duplicate live
symbol means the master is wrong — a missed delisting, a bad ingest, a series collision — and
picking one silently buries that evidence under a plausible answer.

Written from scratch per SAL-0026 (NONE_FOUND across all three donor repos, every ref;
``intraday``'s ``conf/instruments.py`` is a 237-byte stub), bitemporal from the first line
rather than retrofitted onto a flat table.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Final

from pydantic import field_validator

from pips.core.config import PipsConfig
from pips.data.pit.store import PitOp, PitRecord, PitStore, from_payload

__all__ = ["AmbiguousSymbolError", "Instrument", "InstrumentMaster", "validate_isin"]

TABLE: Final = "instruments"

# Country code + 9 alphanumeric + check digit. Uppercase only: an ISIN is a printed
# identifier, and accepting mixed case would let "ine002a01018" and "INE002A01018" become two
# instruments with two price histories and no complaint from anything.
_ISIN_RE: Final = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def validate_isin(value: str) -> str:
    """Return ``value`` if it is a well-formed ISIN, else raise.

    Public and shared, because the corporate-action master needs the identical rule and two
    copies of a validation rule drift — which is precisely the defect the registry's
    schema/model guard was added to catch a few commits ago.
    """
    if not _ISIN_RE.match(value):
        raise ValueError(
            f"{value!r} is not an ISIN (2-letter country code, 9 alphanumeric, check digit, "
            "uppercase). The ISIN is the master's key — a malformed one creates a second "
            "identity for a security that already has one."
        )
    return value


class AmbiguousSymbolError(LookupError):
    """More than one live instrument claims a symbol on a date."""


class Instrument(PipsConfig):
    """One security as the master knew it at a point in time."""

    isin: str
    exchange_token: str
    symbol: str
    name: str
    series: str
    lot_size: int
    tick_size_paise: int

    @field_validator("isin")
    @classmethod
    def _looks_like_an_isin(cls, value: str) -> str:
        return validate_isin(value)


class InstrumentMaster:
    """The instrument table, over a :class:`PitStore`.

    A thin layer on purpose: the bitemporal guarantees belong to the store, and re-deriving
    them here would give two implementations of one promise. What this adds is identity —
    which ISIN a symbol or token pointed at on a date, and the refusal to guess.
    """

    def __init__(self, store: PitStore) -> None:
        self.store = store

    # ------------------------------------------------------------- writing ----------

    def upsert(
        self, instrument: Instrument, known_from: date, valid_from: date | None = None
    ) -> None:
        """Record an instrument as known from a date (valid from the same date by default)."""
        self.store.append(
            PitRecord(
                table=TABLE,
                key=instrument.isin,
                valid_from=known_from if valid_from is None else valid_from,
                known_from=known_from,
                payload=instrument.model_dump(mode="json"),
            )
        )

    def rename(self, isin: str, symbol: str, known_from: date) -> None:
        """Record a symbol change. The ISIN does not move, so joins on it survive."""
        self._amend(isin, known_from, symbol=symbol)

    def retoken(self, isin: str, exchange_token: str, known_from: date) -> None:
        """Record an exchange-token change.

        Tokens are the broker's handle and get reassigned. A token->symbol map built once and
        cached is the same splice as the symbol case, in a different field.
        """
        self._amend(isin, known_from, exchange_token=exchange_token)

    def delist(self, isin: str, known_from: date) -> None:
        """Record that the instrument left the master. Its symbol is now free."""
        self._require(isin)
        self.store.close(TABLE, isin, known_from=known_from)

    def _amend(self, isin: str, known_from: date, **changes: str) -> None:
        current = self._require(isin)
        self.store.correct(
            TABLE,
            isin,
            known_from=known_from,
            payload=current.model_copy(update=changes).model_dump(mode="json"),
        )

    def _require(self, isin: str) -> Instrument:
        """The instrument's current version, or a comprehensible refusal.

        A delisting is a tombstone with an empty payload. The first version of this method
        validated whatever the latest record held, so amending a delisted instrument — a real
        and ordinary mistake — surfaced as a seven-error pydantic complaint about missing
        fields on ``{}``, which reads like a corrupt master rather than like the mistake it is.
        """
        records = [r for r in self.store.all_records(TABLE) if r.key == isin]
        if not records:
            raise KeyError(f"{isin} is not in the instrument master — upsert it first")
        if records[-1].op is PitOp.CLOSE:
            raise LookupError(
                f"{isin} was delisted on {records[-1].known_from.isoformat()} and cannot be "
                "amended. If it has come back, record that as an upsert — a relisting is a "
                "new fact about the ISIN, not an edit to a security that no longer exists."
            )
        return from_payload(Instrument, records[-1].payload)

    # ------------------------------------------------------------- reading ----------

    def as_of(self, on: date) -> list[Instrument]:
        """Every live instrument as the master knew it on that date, in ISIN order."""
        return [
            from_payload(Instrument, r.payload)
            for r in self.store.as_of(TABLE, known_on=on, valid_on=on)
        ]

    def resolve_symbol(self, symbol: str, on: date) -> Instrument | None:
        """The instrument holding ``symbol`` on ``on``. ``None`` if nobody held it.

        ``None`` in the gap between a delisting and a reassignment is the load-bearing case:
        falling back to "the most recent holder" is exactly how one price series ends up
        containing two companies.
        """
        matches = [i for i in self.as_of(on) if i.symbol == symbol]
        return self._exactly_one(matches, f"symbol {symbol!r}", on)

    def resolve_token(self, exchange_token: str, on: date) -> Instrument | None:
        """The instrument holding ``exchange_token`` on ``on``."""
        matches = [i for i in self.as_of(on) if i.exchange_token == exchange_token]
        return self._exactly_one(matches, f"token {exchange_token!r}", on)

    @staticmethod
    def _exactly_one(matches: list[Instrument], what: str, on: date) -> Instrument | None:
        if not matches:
            return None
        if len(matches) > 1:
            raise AmbiguousSymbolError(
                f"{what} resolves to {len(matches)} live instruments on {on.isoformat()}: "
                f"{', '.join(sorted(i.isin for i in matches))}. The master is wrong — a "
                "missed delisting, a bad ingest or a series collision. Refusing to pick one, "
                "because picking would usually be right and would bury the evidence."
            )
        return matches[0]

    def symbol_history(self, isin: str) -> list[tuple[date, str]]:
        """``(known_from, symbol)`` for every version, in knowledge order.

        Deduplicated on the symbol, so a token change does not appear as a symbol change —
        every version is a new row, and reporting all of them would make a renaming history
        that never happened.
        """
        return self._history(isin, lambda i: i.symbol)

    def token_history(self, isin: str) -> list[tuple[date, str]]:
        """``(known_from, exchange_token)`` for every version, in knowledge order."""
        return self._history(isin, lambda i: i.exchange_token)

    def _history(self, isin: str, field: Callable[[Instrument], str]) -> list[tuple[date, str]]:
        out: list[tuple[date, str]] = []
        for record in self.store.all_records(TABLE):
            if record.key != isin or not record.payload:
                continue
            value = field(from_payload(Instrument, record.payload))
            if not out or out[-1][1] != value:
                out.append((record.known_from, value))
        return out

    def snapshot_root(self, on: date) -> str:
        """Merkle root of the master as of a date [C-DATA-02] — what a run pins."""
        return self.store.snapshot_root(TABLE, known_on=on, valid_on=on)
