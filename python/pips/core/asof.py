"""As-of access guard -- causality is measurability (constitution rule 2).

Research code never reads a raw table. It reads a view bound to a decision timestamp,
which *physically refuses* any record whose source timestamp is later than that
decision, and records every field it hands out so that leakage is auditable after the
fact rather than argued about.

M0 provided the guard over a record sequence. M2 adds :class:`AsOfPanelView` over Polars
panels -- the object every piece of research code actually reads -- with the adversarial
battery in ``tests/unit/core/test_asof_panel.py`` and the permanent leakage canary.

Three bans are mechanical rather than advisory, because each is a leak that reviewers miss:

* **full-day fields** (``day_*``, ``*_full_day``) are unknowable intraday, so the feature API
  refuses them outright rather than trusting a caller not to use them mid-session;
* **smoothed state probabilities** (``smoothed_*``) are ``P(S_t | F_T)`` for ``T > t`` -- they
  read the future by construction and may not touch anything that trades or tunes;
* **negative shifts** are the single most common leak in research code ("tomorrow's close,
  today"), so the view exposes shifting as an operation it can check rather than letting
  callers reach for the raw frame.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import polars as pl

__all__ = [
    "BANNED_PREFIXES",
    "BANNED_SUFFIXES",
    "AsOfPanelView",
    "AsOfView",
    "CausalityViolationError",
    "Record",
    "banned_reason",
]

BANNED_PREFIXES: Final[dict[str, str]] = {
    "day_": "full-day aggregate is not knowable intraday",
    "smoothed_": "smoothed state probability P(S_t | F_T), T>t reads the future",
}
BANNED_SUFFIXES: Final[dict[str, str]] = {
    "_full_day": "full-day aggregate is not knowable intraday",
}


def banned_reason(name: str) -> str | None:
    """Why ``name`` may not be read intraday, or ``None`` if it is measurable."""
    for prefix, reason in BANNED_PREFIXES.items():
        if name.startswith(prefix):
            return reason
    for suffix, reason in BANNED_SUFFIXES.items():
        if name.endswith(suffix):
            return reason
    return None


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


@dataclass
class AsOfPanelView:
    """A decision-time-bounded view over a Polars panel -- the production read path.

    Rows later than ``decision_ts`` are not merely filtered on the way out: they are absent
    from everything the view hands back, including :meth:`visible`. Banned columns are
    dropped there too, so the obvious bypass -- take the frame instead of calling
    :meth:`column` -- yields a frame that does not contain them.
    """

    frame: pl.DataFrame
    decision_ts: int
    ts_col: str = "close_ts_ns"
    accessed_fields: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.ts_col not in self.frame.columns:
            raise ValueError(f"panel has no timestamp column {self.ts_col!r}")

    def visible(self) -> pl.DataFrame:
        """Measurable rows, with every banned column removed."""
        keep = [c for c in self.frame.columns if banned_reason(c) is None]
        return self.frame.filter(pl.col(self.ts_col) <= self.decision_ts).select(keep)

    def max_source_ts(self) -> int | None:
        """Latest source timestamp actually visible -- the invariant CI asserts on."""
        visible = self.visible()
        if visible.height == 0:
            return None
        return int(visible[self.ts_col].max())  # type: ignore[arg-type]

    def _check_readable(self, name: str) -> None:
        reason = banned_reason(name)
        if reason is not None:
            raise CausalityViolationError(f"field {name!r} is refused: {reason}")
        if name not in self.frame.columns:
            raise KeyError(f"panel has no column {name!r}")

    def column(self, name: str) -> pl.Series:
        """Visible values of ``name``, recording the access for the leakage audit."""
        self._check_readable(name)
        self.accessed_fields.add(name)
        return self.visible()[name]

    def shifted(self, name: str, periods: int) -> pl.Series:
        """Lag a column. A negative shift is a forward peek and is refused."""
        if periods < 0:
            raise CausalityViolationError(
                f"shift({periods}) on {name!r} reads forward in time; only lags are measurable"
            )
        return self.column(name).shift(periods)

    def trailing(self, name: str, window: int) -> pl.Series:
        """The last ``window`` measurable values of ``name`` (never more, never later)."""
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        return self.column(name).tail(window)

    def join_asof_safe(self, other: pl.DataFrame, on: str) -> pl.DataFrame:
        """Join another frame, refusing it if any of its rows postdate the decision.

        Filtering the joined result would be silent; a frame carrying future rows means the
        caller believes it holds information it cannot have, and that belief is the bug.
        """
        if on not in other.columns:
            raise ValueError(f"join key {on!r} missing from the right frame")
        if other.height:
            latest = int(other[on].max())  # type: ignore[arg-type]
            self.require_measurable(latest, f"joined frame on {on!r}")
        return self.visible().join(other, on=on, how="inner")

    def earliest_fill_ts(self, latency_ns: int) -> int:
        """First instant an order from this decision could execute.

        Strictly after the decision: a signal computed on completed bar ``t`` may not fill
        within bar ``t``, so equality is not permitted even at zero modelled latency.
        """
        if latency_ns < 0:
            raise ValueError(f"latency must be non-negative, got {latency_ns}")
        return self.decision_ts + max(latency_ns, 1)

    def require_measurable(self, source_ts: int, what: str) -> None:
        """Assert that ``source_ts`` was knowable at the decision. Raises if not."""
        if source_ts > self.decision_ts:
            raise CausalityViolationError(
                f"{what} has source_ts {source_ts} > decision_ts {self.decision_ts}"
            )

    def audit(self) -> dict[str, Any]:
        """What this view was asked for -- the record a leakage review reads."""
        return {
            "decision_ts": self.decision_ts,
            "max_source_ts": self.max_source_ts(),
            "accessed_fields": sorted(self.accessed_fields),
            "rows_visible": self.visible().height,
            "rows_hidden": self.frame.height - self.visible().height,
        }
