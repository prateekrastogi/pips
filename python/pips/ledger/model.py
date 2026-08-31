"""Ledger row schemas -- the machine-readable normative layer (§8.2)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ContractRow", "GateRow", "Ledger", "Status", "load_ledger"]


class Status(StrEnum):
    """Lifecycle of a normative row. ``enforced`` means code *and* tests exist."""

    PLANNED = "planned"
    BUILDING = "building"
    ENFORCED = "enforced"

    @property
    def rank(self) -> int:
        return {"planned": 0, "building": 1, "enforced": 2}[self.value]


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    spec: str
    status: Status
    owner_milestone: str
    source_refs: list[str] = Field(default_factory=list)
    code: str | None = None
    tests: list[str] = Field(default_factory=list)


class ContractRow(_Row):
    """A ``C-*`` row: a pinned contract bound to code and tests."""


class GateRow(_Row):
    """A ``G-*`` row: a promotion/release gate with a threshold and evidence."""

    threshold: dict[str, Any] = Field(default_factory=dict)
    enforced_by: str | None = None
    evidence: str | None = None


class Ledger(BaseModel):
    """The whole ledger, loaded from ``docs/ledger/``."""

    model_config = ConfigDict(frozen=True)

    contracts: list[ContractRow]
    gates: list[GateRow]

    @property
    def all_ids(self) -> list[str]:
        return [r.id for r in self.contracts] + [g.id for g in self.gates]


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"ledger file missing: {path}")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return list(loaded or [])


def load_ledger(ledger_dir: Path) -> Ledger:
    """Load ``contracts.yaml`` and ``gates.yaml`` from ``ledger_dir``."""
    return Ledger(
        contracts=[
            ContractRow.model_validate(r) for r in _load_rows(ledger_dir / "contracts.yaml")
        ],
        gates=[GateRow.model_validate(r) for r in _load_rows(ledger_dir / "gates.yaml")],
    )
