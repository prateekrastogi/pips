"""Broker-capability daily snapshotter on the PIT store  [C-DATA-01] [C-DATA-02] (§6 M6, §3.4).

M3 shipped a v0 — a manually maintained CSV with one ``snapshot_date`` per row — and said M6
would replace the ingest while keeping the read shape: *ask as of a date, get what was knowable
then*. This is that replacement.

**What one date cannot say.** ``snapshot_date`` conflates when we LEARNED a capability with
when it TOOK EFFECT. A broker announcing on 20 August that its square-off moves to 15:10 from 1
September is knowledge on the 20th and force on the 1st; a single column must pick one. Pick
the announcement and the system squares off early for eleven days it should not have; pick the
effective date and it acts on information it did not have. Both are wrong, and one of them is
silently, profitably wrong.

Square-off time is not a detail here. :meth:`pips.core.calendar.ExchangeCalendar.session_at`
reads it to decide whether an intraday position must be flat, so an error in this table is an
error in the last minutes of every position.

The v0 loader in :mod:`pips.data.pit.capability` stays, and is not dead code: it is what
:func:`migrate_v0_csv` reads, and it is the reference the migration's equivalence test compares
against. A capability table that quietly answers differently after a refactor is worse than one
that fails outright.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pips.data.pit.capability import CapabilityRow, load_capability_csv
from pips.data.pit.store import PitRecord, PitStore, from_payload

__all__ = ["CapabilityMaster", "capability_key", "migrate_v0_csv"]

TABLE = "broker_capability"
_WILDCARD = "*"
_BOTH = "BOTH"


def capability_key(broker: str, product: str, instrument_id: str, side: str) -> str:
    """The PIT key for one capability lane.

    A composite of all four dimensions, because they are independent: a change to Flattrade's
    MIS shortability for one instrument must not disturb the wildcard row it overrides, and
    keying on anything coarser would make one an amendment of the other.
    """
    return f"{broker}|{product}|{instrument_id}|{side}"


class CapabilityMaster:
    """Broker capability, bitemporal, read as of a date."""

    def __init__(self, store: PitStore) -> None:
        self.store = store

    def snapshot(
        self, row: CapabilityRow, known_from: date, valid_from: date | None = None
    ) -> None:
        """Record a capability as known from a date, in force from another.

        ``valid_from`` defaults to ``known_from``: the overwhelmingly common case is a daily
        snapshotter recording what is true today. The split exists for the announcement case,
        and making the caller spell it out every time would invite the two drifting apart by
        accident.
        """
        # A plain append, never `correct`. A correction inherits the version it amends —
        # right for "this value was always wrong", wrong here: each snapshot carries its OWN
        # effective date, and inheriting the previous one silently discards the announcement
        # split this class exists to record.
        self.store.append(
            PitRecord(
                table=TABLE,
                key=capability_key(row.broker, row.product, row.instrument_id, row.side),
                valid_from=known_from if valid_from is None else valid_from,
                known_from=known_from,
                payload=row.model_dump(mode="json"),
            )
        )

    def _visible(self, as_of: date, known_on: date | None) -> list[CapabilityRow]:
        return [
            from_payload(CapabilityRow, r.payload)
            for r in self.store.as_of(
                TABLE, known_on=as_of if known_on is None else known_on, valid_on=as_of
            )
        ]

    @staticmethod
    def _specificity(row: CapabilityRow) -> tuple[int, int, date]:
        """Higher sorts first: a named instrument beats ``*``, an exact side beats ``BOTH``."""
        return (
            0 if row.instrument_id == _WILDCARD else 1,
            0 if row.side == _BOTH else 1,
            row.snapshot_date,
        )

    def resolve(
        self,
        as_of: date,
        broker: str = "FLATTRADE",
        product: str = "MIS",
        instrument_id: str = "*",
        side: str = "BOTH",
        known_on: date | None = None,
    ) -> CapabilityRow:
        """The capability in force on ``as_of``, as understood on ``known_on``.

        A date with no snapshot RAISES rather than falling back to a default. Inventing
        capability for a date we have no data for is the survivorship-flavoured error §3.4
        exists to prevent — and here it would invent permission to trade.
        """
        candidates = [
            row
            for row in self._visible(as_of, known_on)
            if row.broker == broker
            and row.product == product
            and row.instrument_id in (instrument_id, _WILDCARD)
            and row.side in (side, _BOTH)
        ]
        if not candidates:
            raise LookupError(
                f"no capability snapshot for {broker}/{product}/{instrument_id}/{side} "
                f"as of {as_of}"
            )
        return max(candidates, key=self._specificity)

    def snapshot_root(self, as_of: date, known_on: date | None = None) -> str:
        """Merkle root of the capability table as of a date [C-DATA-02]."""
        return self.store.snapshot_root(
            TABLE, known_on=as_of if known_on is None else known_on, valid_on=as_of
        )


def migrate_v0_csv(path: Path, master: CapabilityMaster) -> int:
    """Load the M3 v0 CSV into the master. Returns the number of rows recorded.

    ``snapshot_date`` becomes BOTH clocks: the v0 could not distinguish them, so claiming a
    split it never recorded would be inventing provenance. What the migration buys is the
    ability to record the distinction from now on, not a retroactive one.
    """
    recorded = 0
    for row in load_capability_csv(path).rows:
        master.snapshot(row, known_from=row.snapshot_date)
        recorded += 1
    return recorded
