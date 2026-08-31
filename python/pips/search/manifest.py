"""Experiment manifest -- the pre-registration object  [C-REG-01] (§6 M11, reference App. B).

A manifest declares what will be searched, on what data, under which protocol, with which
seed, **before** the search runs. Its content hash is what ties a declared experiment to the
trials it produced, so a result can be checked against what was proposed rather than against
whatever turned out well.

``status: PROPOSED`` is a claim about the future; every other status is a claim about the
past. Conflating them after the fact -- quietly re-describing an exploratory sweep as a
pre-registered one -- is the failure this object exists to prevent, and it is the same family
as "hidden notebook trials or deleted failures" on the anti-voodoo list (§7).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from pips.core.calendar import SessionState
from pips.core.config import DecimalFromNumber, PipsConfig, load_yaml
from pips.core.ids import ShortId, content_hash, short_id

__all__ = [
    "AlphaRef",
    "CostContextRef",
    "DataRef",
    "Experiment",
    "ExperimentManifest",
    "ManifestStatus",
    "UniverseRef",
    "ValidationRef",
    "load_manifest",
]


class ManifestStatus(StrEnum):
    """PROPOSED is a claim about the future; the rest are claims about the past."""

    PROPOSED = "PROPOSED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class AlphaRef(PipsConfig):
    id: str
    version: str
    params: dict[str, Any] = Field(default_factory=dict)


class DataRef(PipsConfig):
    snapshot: str
    tier: str
    asof_policy: str


class UniverseRef(PipsConfig):
    policy: str
    n: int
    lookback_days: int
    refresh: str


class CostContextRef(PipsConfig):
    version: str
    # Unquoted in the reference's Appendix B, so accepted unquoted here.
    stress: list[DecimalFromNumber]

    def validate_grid(self) -> CostContextRef:
        """The stress grid must contain the unstressed case and something above it.

        Reporting only stressed numbers hides the baseline; reporting only the baseline is
        the error M16 exists to prevent. A grid missing either end cannot show the gap.
        """
        if Decimal(1) not in self.stress:
            raise ValueError(
                f"stress grid {self.stress} omits the unstressed case 1.0 — without it the "
                "stressed numbers have no baseline to be compared against"
            )
        if not any(s > 1 for s in self.stress):
            raise ValueError(f"stress grid {self.stress} has no value above 1.0")
        return self


class ValidationRef(PipsConfig):
    outer: str
    inner: str
    train: str
    purge: str
    embargo: str


class Experiment(PipsConfig):
    protocol: str
    alpha: AlphaRef
    data: DataRef
    universe: UniverseRef
    session: str
    broker_context: str
    capital_inr: int
    costs: CostContextRef
    validation: ValidationRef
    seed: int
    status: ManifestStatus

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, value: object) -> object:
        return ManifestStatus(value) if isinstance(value, str) else value

    def validate_session(self) -> Experiment:
        """The declared session must exist and must be one we may actually trade."""
        try:
            state = SessionState(self.session)
        except ValueError as exc:
            raise ValueError(
                f"session {self.session!r} is not a known session state; expected one of "
                f"{[s.value for s in SessionState]}"
            ) from exc
        if not state.tradeable_as_alpha:
            raise ValueError(
                f"{state} is not a tradeable session — pre-registering a search on it would "
                "propose an experiment we are not permitted to run (ADR-0004)"
            )
        return self


class ExperimentManifest(PipsConfig):
    """The whole pre-registration document."""

    experiment: Experiment

    def content_hash(self) -> str:
        """Full SHA-256 -- the tie between a pre-registration and its trials."""
        return content_hash(self.model_dump(mode="json"))

    def short_id(self) -> ShortId:
        return short_id(self.content_hash())


def load_manifest(path: Path) -> ExperimentManifest:
    """Load, validate and check a manifest, including its session and stress grid."""
    manifest = ExperimentManifest.model_validate(load_yaml(path))
    manifest.experiment.validate_session()
    manifest.experiment.costs.validate_grid()
    return manifest
