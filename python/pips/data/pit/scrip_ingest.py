"""Loading a parsed scrip master into the PIT instrument master  [C-DATA-01] (§6 M6).

The last step from a downloaded archive to a live master, and the one place a daily
snapshotter can quietly ruin the store it is filling.

**A re-ingest of an unchanged file must record nothing.** The master is bitemporal and
append-only: rewriting every instrument every day turns 5,851 rows into 5,851 rows PER DAY, and
a year of unchanged data becomes two million versions of nothing happening. Worse than the
storage, it makes every genuine change impossible to find among them — a symbol rename becomes
one row in three hundred and sixty-five identical ones. Only actual changes become versions.

**A changed field IS a new version, dated by the ingest.** That is the point of a daily
snapshot: a symbol or token that moves becomes visible as a change with a date attached, rather
than overwriting what came before.

**Rejected rows travel with the summary.** The parser refuses them with reasons; an ingest that
returns only a success count throws that away one layer up, and the count of instruments loaded
then reads as the count of instruments there were.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.scrip_master import RejectedRow

__all__ = ["UNKNOWN_LISTING_DATE", "IngestSummary", "ingest_instruments"]

UNKNOWN_LISTING_DATE = date(1990, 1, 1)
"""Validity start for an instrument whose listing date the vendor does not supply.

**All 5,873 rows of the real NSE scrip master have a blank ``DateOfListing``** — measured, not
assumed. So the master cannot say when a security listed, and the ingest date is emphatically
not the answer: defaulting to it said RELIANCE began on 31 August and made every historical
read exclude it.

This asserts *at or before anything we could have data for*, and nothing more. It is
deliberately absurd as a listing date — NSE began trading in 1994 — because a plausible one
gets mistaken for a measurement.

WHAT IT COSTS, stated rather than discovered: a reused code now has two claimants overlapping
in valid time, and valid time can no longer separate them. That is a real loss of resolution.
It degrades to the master's existing refusal to guess, which is loud, rather than to a silent
splice of two companies into one price series — and a wrong answer there would be
undetectable.

It also makes VALID TIME DEGENERATE for these instruments: every version is valid from 1990, so
temporal resolution falls back entirely to knowledge time, and their symbol history is a
knowledge history rather than a validity one. That is the honest description of a master built
from a file with no listing dates in it. When a listing-date source appears, this sentinel is
what to replace, and valid time starts doing its job again.
"""


@dataclass(frozen=True)
class IngestSummary:
    """What one ingest actually did. ``added + changed + unchanged`` is the input count."""

    known_from: date
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    rejected: int = 0
    changed_isins: tuple[str, ...] = field(default_factory=tuple)
    rejected_rows: tuple[RejectedRow, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        lines = [
            f"scrip ingest {self.known_from.isoformat()}: {self.added} added, "
            f"{self.changed} changed, {self.unchanged} unchanged, {self.rejected} rejected",
        ]
        lines.extend(f"    changed: {isin}" for isin in self.changed_isins[:20])
        if len(self.changed_isins) > 20:
            lines.append(f"    ... and {len(self.changed_isins) - 20} more")
        lines.extend(
            f"    rejected: {r.vendor_code or '(no code)'} {r.isin!r} — {r.reason}"
            for r in self.rejected_rows[:20]
        )
        if len(self.rejected_rows) > 20:
            lines.append(f"    ... and {len(self.rejected_rows) - 20} more rejections")
        return "\n".join(lines)


def ingest_instruments(
    master: InstrumentMaster,
    instruments: list[Instrument],
    known_from: date,
    *,
    valid_from: date,
    rejected: list[RejectedRow] | None = None,
) -> IngestSummary:
    """Record only what actually changed, and report everything.

    ``valid_from`` is REQUIRED and has no default. The ingest date is not when an instrument
    came into existence, and using it made every historical read exclude every instrument —
    silently. The vendor does not supply listing dates, so the caller states what it is
    asserting; :data:`UNKNOWN_LISTING_DATE` is the honest answer when nothing better exists.
    """
    if not instruments:
        raise ValueError(
            "ingest_instruments called with no instruments. An empty ingest reports a clean "
            "run over no data, which reads exactly like a successful one."
        )

    # Both clocks at the ingest date: an ingest compares against what the master holds NOW,
    # and "now" for a snapshotter is the date it is snapshotting.
    # Compare against everything we hold, on both clocks wide open: an instrument recorded
    # with an UNKNOWN_LISTING_DATE validity start is still the instrument we have, and a
    # narrow read here would report it as new every single day.
    current = {i.isin: i for i in master.as_of(known_from, known_on=None)}
    added = changed = unchanged = 0
    changed_isins: list[str] = []
    for instrument in instruments:
        existing = current.get(instrument.isin)
        if existing is None:
            master.upsert(instrument, known_from=known_from, valid_from=valid_from)
            added += 1
        elif existing == instrument:
            # The common case by far, and the one that must cost nothing. See the module
            # docstring: re-recording it is how a snapshotter buries its own signal.
            unchanged += 1
        else:
            master.upsert(instrument, known_from=known_from, valid_from=valid_from)
            changed += 1
            changed_isins.append(instrument.isin)

    return IngestSummary(
        known_from=known_from,
        added=added,
        changed=changed,
        unchanged=unchanged,
        rejected=len(rejected or []),
        changed_isins=tuple(changed_isins),
        rejected_rows=tuple(rejected or []),
    )
