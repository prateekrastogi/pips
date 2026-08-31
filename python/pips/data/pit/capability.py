"""Broker capability snapshots  [C-DATA-01] (§3.4, M3 v0).

Square-off times, order types, rate limits, shortability and leverage are **data, not
constants** (§3.4). This is the table they live in, and it is where
:meth:`pips.core.calendar.ExchangeCalendar.session_at` gets its broker cutoff -- so there is
no path from a hard-coded time to a session state.

v0 is a manually maintained CSV, which M3 explicitly permits. **M6 has now replaced the
ingest**: :mod:`pips.data.pit.capability_master` puts these rows on the bitemporal PIT store,
where ``known_from`` and ``valid_from`` are separate — a change announced weeks before it takes
effect is finally expressible, which one ``snapshot_date`` column never could.

This module is not dead. :class:`CapabilityRow` is still the schema, ``load_capability_csv`` is
what the migration reads, and :class:`CapabilitySnapshot` is the reference the migration's
equivalence test compares against row by row. A capability table that quietly answers
differently after a refactor is worse than one that fails outright, and that test is what says
it does not. The read shape is unchanged either way: ask as of a date, get what was knowable
then.
"""

from __future__ import annotations

import csv
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from pydantic import Field, field_validator

from pips.core.config import PipsConfig
from pips.core.time import TimestampNs, ts_from_iso

__all__ = [
    "CapabilityRow",
    "CapabilitySnapshot",
    "launch_leverage",
    "load_capability_csv",
]

_WILDCARD = "*"
_BOTH = "BOTH"


def launch_leverage() -> Decimal:
    """The leverage pips actually uses at launch: 1.0, unlevered (ADR-0003).

    Separate from :attr:`CapabilityRow.max_leverage`, which records what the broker *offers*.
    Keeping them apart is the point: a broker-permitted multiple must not leak into sizing
    just because it exists in a snapshot.
    """
    return Decimal(1)


class CapabilityRow(PipsConfig):
    """One broker x product x instrument x side capability record."""

    snapshot_date: date
    broker: str
    product: str
    instrument_id: str
    side: str
    eligible: bool
    shortable: bool
    max_leverage: Decimal
    square_off_time: time | None
    square_off_verified: bool
    order_types: list[str] = Field(min_length=1)
    rate_limit_per_second: int
    rate_limit_per_minute: int
    source: str
    verified_on: date

    @field_validator("square_off_time", mode="before")
    @classmethod
    def _parse_square_off(cls, value: object) -> object:
        if value in (None, "", "null"):
            return None
        return time.fromisoformat(value) if isinstance(value, str) else value

    def require_verified_square_off(self) -> None:
        """Refuse an unverified cutoff on any path to real capital.

        Research on fixtures may use the placeholder -- it is conservative by construction --
        but nothing that can place an order may rely on a time nobody confirmed.
        """
        if not self.square_off_verified:
            raise RuntimeError(
                f"{self.broker} {self.product} square-off time {self.square_off_time} is "
                "not verified — it is a conservative placeholder pending the M3 probe"
            )

    def square_off_ns(self, day: date) -> TimestampNs:
        """The cutoff as a nanosecond timestamp on ``day``, for the calendar to consume."""
        if self.square_off_time is None:
            raise ValueError(f"{self.broker} {self.product} has no intraday square-off")
        return ts_from_iso(f"{day.isoformat()}T{self.square_off_time.isoformat()}")


class CapabilitySnapshot:
    """A set of capability rows, read as of a date."""

    def __init__(self, rows: list[CapabilityRow]) -> None:
        self.rows = sorted(rows, key=lambda r: r.snapshot_date)

    def _specificity(self, row: CapabilityRow) -> tuple[int, int, date]:
        """Higher sorts first: a named instrument beats ``*``, an exact side beats ``BOTH``."""
        return (
            0 if row.instrument_id == _WILDCARD else 1,
            0 if row.side == _BOTH else 1,
            row.snapshot_date,
        )

    def resolve(
        self, as_of: date, broker: str, product: str, instrument_id: str, side: str
    ) -> CapabilityRow:
        """The capability in force on ``as_of``.

        Point-in-time by construction: rows dated after ``as_of`` are invisible, so a snapshot
        taken later cannot change what an earlier date saw. A date with no snapshot raises
        rather than falling back to a default -- inventing capability for a date we have no
        data for is exactly the survivorship-flavoured error §3.4 exists to prevent.
        """
        candidates = [
            row
            for row in self.rows
            if row.snapshot_date <= as_of
            and row.broker == broker
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


def load_capability_csv(path: Path) -> CapabilitySnapshot:
    """Load a v0 capability CSV. Lines beginning ``#`` are commentary, not data."""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    rows: list[CapabilityRow] = []
    for record in csv.DictReader(lines):
        # dict[str, object]: a CSV gives strings, and the model wants dates, Decimals, bools
        # and a list. Widening the value type here is honest about that conversion rather
        # than silencing it field by field.
        payload: dict[str, object] = dict(record)
        payload["order_types"] = [t.strip() for t in str(record["order_types"]).split("|")]
        for flag in ("eligible", "shortable", "square_off_verified"):
            payload[flag] = str(record[flag]).strip().lower() == "true"
        payload["max_leverage"] = Decimal(str(record["max_leverage"]))
        payload["rate_limit_per_second"] = int(str(record["rate_limit_per_second"]))
        payload["rate_limit_per_minute"] = int(str(record["rate_limit_per_minute"]))
        payload["snapshot_date"] = date.fromisoformat(str(record["snapshot_date"]))
        payload["verified_on"] = date.fromisoformat(str(record["verified_on"]))
        rows.append(CapabilityRow.model_validate(payload))
    return CapabilitySnapshot(rows)
