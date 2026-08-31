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

__all__ = ["IngestSummary", "ingest_instruments"]


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
    rejected: list[RejectedRow] | None = None,
) -> IngestSummary:
    """Record only what actually changed, and report everything."""
    if not instruments:
        raise ValueError(
            "ingest_instruments called with no instruments. An empty ingest reports a clean "
            "run over no data, which reads exactly like a successful one."
        )

    current = {i.isin: i for i in master.as_of(known_from)}
    added = changed = unchanged = 0
    changed_isins: list[str] = []
    for instrument in instruments:
        existing = current.get(instrument.isin)
        if existing is None:
            master.upsert(instrument, known_from=known_from)
            added += 1
        elif existing == instrument:
            # The common case by far, and the one that must cost nothing. See the module
            # docstring: re-recording it is how a snapshotter buries its own signal.
            unchanged += 1
        else:
            master.upsert(instrument, known_from=known_from)
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
