"""Drafting a dossier from what the factory actually measured  (§12.2, M20, `[C-WRIT-01]`).

`[C-DOSS-01]` checks a dossier; this writes one, and the two halves fail in opposite directions.
A checker that is too lax certifies unmeasured strategies. A writer that is too *helpful* does
the same thing one step earlier and leaves no trace: a default of `0.0` for a missing PBO, or a
`"none"` for kill thresholds nobody set, produces a dossier that is complete, hashes cleanly,
binds to its bundle, and is entirely invented.

So the contract here is subtractive. **It fills only what it can derive and names everything it
could not.** There is no default anywhere in this module, and no path by which one could be
added without deleting a test.

**The caller cannot hand-write a gate.** Gate measurements come from the candidate's metrics
held against thresholds declared *here*; evidence offered for a gate path is refused outright.
Otherwise the writer is a way to inject a passing `Measurement`, which is the one thing the
`[C-DOSS-01]` / `[C-CERT-01]` chain exists to prevent.

**A metric that did not compute is not a metric.** NaN and infinity are unsupplied.

**The draft's account of the gap agrees with the checker's**, and a test holds them together: a
writer that believes it filled what `check_completeness` calls hollow is a writer whose report
nobody can act on.

**On the thresholds that are missing.** P4 states numbers for DSR (0.95), PBO (0.25) and SPA
(0.10) — only `dsr_min` also appears in `gates.yaml`. Plateau stability, concentration and the
four cost/delay stress gates are named in P4 *without a bar anywhere*, so they cannot be drafted
and no drafted dossier can pass `[C-CERT-01]` yet. That is a real gap in the specification, and
inventing six thresholds to close it here is precisely the failure this module refuses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pips.certification.dossier import REQUIRED_FIELDS, Measurement, build_dossier

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pips.certification.dossier import Dossier
    from pips.selection.pareto import Candidate

__all__ = [
    "GATE_SOURCES",
    "METRIC_SOURCES",
    "DossierDraft",
    "MetricSource",
    "UndeclaredEvidenceError",
    "draft_dossier",
]


class UndeclaredEvidenceError(ValueError):
    """The caller offered a value for a path it does not own, or for no path at all."""


@dataclass(frozen=True)
class MetricSource:
    """Which measured metric becomes which dossier field, and the bar it is held to.

    `threshold is None` means the field is a plain recorded value rather than a gate.
    """

    metric: str
    path: str
    threshold: float | None = None
    direction: str | None = None


METRIC_SOURCES: tuple[MetricSource, ...] = (
    # Gates. Only the three P4 puts a number on -- see the module docstring: the other six hard
    # gates have no declared threshold, and drafting them would mean inventing one.
    MetricSource("dsr", "economics.dsr", 0.95, "at_least"),
    MetricSource("pbo", "stability.pbo", 0.25, "at_most"),
    MetricSource("spa_p", "stability.spa_p", 0.10, "at_most"),
    # Plain values that the factory produces today. `net_return` is DERIVED rather than supplied
    # because `[C-CERT-01]` ranks on it: a caller-supplied one is a caller-chosen ranking, which
    # is the same objection as a caller-supplied gate one step further along.
    MetricSource("net_return", "economics.net_return"),
    MetricSource("max_drawdown", "economics.max_drawdown"),
)

GATE_SOURCES: tuple[MetricSource, ...] = tuple(
    spec for spec in METRIC_SOURCES if spec.threshold is not None
)

_GATE_PATHS = frozenset(spec.path for spec in GATE_SOURCES)
_DERIVED_PATHS = frozenset(spec.path for spec in METRIC_SOURCES)
_ALL_PATHS = frozenset(
    f"{section}.{field}" for section, fields in REQUIRED_FIELDS.items() for field in fields
)


@dataclass(frozen=True)
class DossierDraft:
    dossier: Dossier
    supplied: tuple[str, ...]
    """``path <- metric:name`` or ``path <- evidence``. The provenance of every filled field."""
    unsupplied: tuple[str, ...]
    """Required paths this draft could not derive. The finding, not an error."""


def _usable(value: object) -> bool:
    """A number that computed. NaN and infinity are what a failed calculation looks like."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value)


def draft_dossier(*, candidate: Candidate, evidence: Mapping[str, Any]) -> DossierDraft:
    """Fill what the metrics and the caller's evidence support; name the rest.

    ``evidence`` is keyed by dotted ``section.field`` path and may not name a gate path — those
    are derived from ``candidate.metrics`` alone.
    """
    for path in evidence:
        if path in _GATE_PATHS:
            raise UndeclaredEvidenceError(
                f"{path} is a gate and is derived from the measured metric, not supplied. "
                "Accepting it here would let a caller hand the certifier a passing Measurement."
            )
        if path in _DERIVED_PATHS:
            raise UndeclaredEvidenceError(
                f"{path} is derived from the measured metric, not supplied. Certification ranks "
                "on it, so a caller-supplied value is a caller-chosen ranking."
            )
        if path not in _ALL_PATHS:
            raise UndeclaredEvidenceError(
                f"{path} is not a dossier field. A typo'd path would sit in the dossier while "
                "the field it was meant for went on reporting missing."
            )

    sections: dict[str, dict[str, Any]] = {}
    supplied: list[str] = []

    def place(path: str, value: Any, source: str) -> None:
        section, _, field = path.partition(".")
        sections.setdefault(section, {})[field] = value
        supplied.append(f"{path} <- {source}")

    for spec in METRIC_SOURCES:
        measured = candidate.metrics.get(spec.metric)
        if not _usable(measured):
            continue
        value: Any = float(measured)  # type: ignore[arg-type]
        if spec.threshold is not None and spec.direction is not None:
            value = Measurement(value, spec.threshold, spec.direction)
        place(spec.path, value, f"metric:{spec.metric}")

    for path, value in evidence.items():
        place(path, value, "evidence")

    dossier = build_dossier(sections)
    filled = {part.split(" <- ")[0] for part in supplied}
    return DossierDraft(
        dossier=dossier,
        supplied=tuple(sorted(supplied)),
        unsupplied=tuple(sorted(_ALL_PATHS - filled)),
    )
