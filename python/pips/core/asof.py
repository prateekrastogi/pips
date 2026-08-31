"""As-of access guard -- causality is measurability (constitution rule 2).

Research code never reads a raw table. It reads a view bound to a decision timestamp,
which *physically refuses* any record whose source timestamp is later than that
decision, and records every field it hands out so that leakage is auditable after the
fact rather than argued about.

M0 provides the guard over a record sequence and its violation type. M2 extends it to
the full ``AsOfPanelView`` over Polars panels with the adversarial test battery and the
permanent leakage canary.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["AsOfView", "CausalityViolationError", "Record"]

Record = Mapping[str, Any]


class CausalityViolationError(RuntimeError):
    """Raised when code reaches for information it could not have had at decision time."""


@dataclass
class AsOfView:
    """A decision-time-bounded view over timestamped records.

    ``ts_field`` names the record's *source* timestamp -- the instant the information
    became knowable. Records at or before ``decision_ts`` are visible; anything later
    is invisible, and asking for it by name raises rather than returning silence.
    """

    records: tuple[Record, ...]
    decision_ts: int
    ts_field: str = "ts"
    accessed_fields: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        missing = [r for r in self.records if self.ts_field not in r]
        if missing:
            raise ValueError(f"{len(missing)} record(s) lack the {self.ts_field!r} field")

    @classmethod
    def of(cls, records: Iterable[Record], decision_ts: int, ts_field: str = "ts") -> AsOfView:
        return cls(records=tuple(records), decision_ts=decision_ts, ts_field=ts_field)

    def visible(self) -> Iterator[Record]:
        """Records measurable at ``decision_ts``, in input order."""
        for record in self.records:
            if int(record[self.ts_field]) <= self.decision_ts:
                yield record

    def max_source_ts(self) -> int | None:
        """Latest source timestamp actually visible -- the invariant CI asserts on."""
        stamps = [int(r[self.ts_field]) for r in self.visible()]
        return max(stamps) if stamps else None

    def field_values(self, name: str) -> list[Any]:
        """Values of ``name`` across visible records, recording the access."""
        self.accessed_fields.add(name)
        return [r[name] for r in self.visible() if name in r]

    def require_measurable(self, source_ts: int, what: str) -> None:
        """Assert that ``source_ts`` was knowable at the decision. Raises if not."""
        if source_ts > self.decision_ts:
            raise CausalityViolationError(
                f"{what} has source_ts {source_ts} > decision_ts {self.decision_ts}"
            )
