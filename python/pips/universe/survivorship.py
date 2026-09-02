"""§4.2's survivorship audit, which is a promotion blocker  (`[C-UNIV-04]`).

The blueprint states it in a box:

    If the available history contains only currently listed names or current broker
    eligibility, label every result survivorship-biased. **No candidate may be promoted** until
    listings, delistings, token changes, corporate actions and daily eligibility have adequate
    archival coverage.

Two claims, and the second is the one with teeth. A survivorship-biased backtest is not a caveat
to note in a dossier — it is a bar on promotion, because the bias is not a wide error band. It
is a systematic lift in one direction: the names that failed are simply absent, so every
strategy looks better than it was, and no downstream statistic recovers what was never in the
panel. A DSR computed over survivors is a confident number about the wrong population.

**Biased and may-promote are derived, never stored.** Two facts that must agree will eventually
not, and a reader shown *"survivorship-biased, promotable"* believes the half that lets the work
proceed. Same argument as `Measurement` having no verdict field.

**Unknown coverage blocks.** *"We did not check whether delistings are covered"* is not
*"delistings are covered"*, and treating them alike is how a survivorship-biased panel gets
promoted by a missing file. The two are reported apart because the fixes differ: one is an
archive to obtain, the other a check to run.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

__all__ = [
    "REQUIRED_COVERAGE",
    "ArchivalCoverage",
    "SurvivorshipVerdict",
    "survivorship_audit",
]


@dataclass(frozen=True)
class ArchivalCoverage:
    """Whether the history covers each thing §4.2 names. ``None`` means nobody checked."""

    listings: bool | None
    delistings: bool | None
    token_changes: bool | None
    corporate_actions: bool | None
    daily_eligibility: bool | None


REQUIRED_COVERAGE: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(ArchivalCoverage))
"""Enumerated from the model, so a sixth requirement added later is audited without anyone
remembering to add it here. A test pins the set against the blueprint's own wording, so the two
must agree rather than one being derived from the other."""


@dataclass(frozen=True)
class SurvivorshipVerdict:
    missing: tuple[str, ...]
    """Named in §4.2 and known NOT to be covered. An archive to obtain."""
    undetermined: tuple[str, ...]
    """Coverage nobody has established. A check to run — and not a pass."""

    @property
    def biased(self) -> bool:
        """Any gap at all. Derived, so it cannot contradict :attr:`may_promote`."""
        return bool(self.missing or self.undetermined)

    @property
    def may_promote(self) -> bool:
        """§4.2's bar. Not a separate judgement: the blueprint ties them together, and so does
        this — *no candidate may be promoted until* the coverage is adequate."""
        return not self.biased


def survivorship_audit(coverage: ArchivalCoverage) -> SurvivorshipVerdict:
    """Whether a panel built on ``coverage`` may promote a candidate.

    Every gap is reported, not the first: a caller closing them one at a time re-runs the audit
    once per archive.
    """
    missing: list[str] = []
    undetermined: list[str] = []
    for name in REQUIRED_COVERAGE:
        value = getattr(coverage, name)
        if value is None:
            undetermined.append(f"{name}: coverage has not been established")
        elif not value:
            missing.append(f"{name}: not covered by the available history")
    return SurvivorshipVerdict(missing=tuple(missing), undetermined=tuple(undetermined))
