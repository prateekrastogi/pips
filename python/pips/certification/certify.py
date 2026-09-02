"""Certification: top-5 is a MAXIMUM, and zero is a valid output  (§12, M20, `[C-CERT-01]`).

The P4 gate reads *0-5 bundles; every certified one passes hard gates*. The dangerous
implementation is `sorted(candidates)[:5]`: it returns five whenever five exist, so the count
reports the size of the input while looking like a finding. Here the gates run first and the
ceiling only ever removes.

**The gates are re-derived, never read.** This is what `Measurement` having no verdict field was
for (`[C-DOSS-01]`): every pass is recomputed from the value and the threshold it was held to,
so a dossier cannot assert one. A gate field holding a bare number is *ungated* — a float has no
threshold, nothing can be derived from it, and accepting it would let "recorded" read as
"passed", which is the stored-verdict problem wearing a different hat.

**Not placing is not failing.** A candidate that cleared every gate and ranked sixth is reported
in `not_placed`, apart from one that failed PBO. Merging the two would say the sixth was
unsound — a different and much stronger claim than "there were five better ones".

**An empty certification carries its reasons.** Zero certified is the expected output of a bad
cycle, and it must be distinguishable from a selector that never ran. An empty list is not.

**On the DSR gate.** `economics.dsr` is the value at N = M, the conservative end of the §3.6
bracket; `stability.trials_viewed` and `stability.m_erank` are recorded beside it so the bracket
can be reconstructed. Nothing here can yet CHECK that the recorded DSR was computed at N = M
rather than at the smaller N = M_erank, which would raise it — that needs the raw Sharpe in the
dossier, and it is a stated gap rather than a solved one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pips.bundle import BundleSignatureError, verify_bundle
from pips.certification.dossier import (
    DossierBindingError,
    IncompleteDossierError,
    Measurement,
    bind_dossier,
    require_complete,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pips.bundle import StrategyBundle
    from pips.certification.dossier import Dossier

__all__ = [
    "DISCLOSED",
    "HARD_GATES",
    "MAX_CERTIFIED",
    "Certification",
    "CertificationCandidate",
    "CertifiedStrategy",
    "DuplicateStrategyError",
    "Rejection",
    "certify",
    "gate_reasons",
]

MAX_CERTIFIED = 5
"""A ceiling, not a target, and deliberately not a parameter — a maximum the caller can raise is
a default. The blueprint's top-3-5 report is at most five; fewer is the normal result."""

HARD_GATES: tuple[str, ...] = (
    "economics.dsr",
    "stability.pbo",
    "stability.spa_p",
    "stability.parameter_plateau",
    "stability.concentration",
    "stress.cost_1_5x",
    "stress.delay_1_bar",
    "stability.outer_folds",
)
"""The P4 hard gates that live as numbers in the dossier. Each must be a `Measurement`, because
a gate is a value AND the bar it was held to; a path dropped from this tuple is a gate nothing
enforces, so a test pins the list."""

DISCLOSED: tuple[str, ...] = (
    "stress.cost_2x",
    "stress.delay_2_bar",
)
"""Required to be present, never held to a bar (ADR-0014). The blueprint's certification row
reads *positive after 1.5x cost and survives +1-bar delay; 2x result DISCLOSED* — gating these
would reject strategies the specification certifies, which is a defect even though it errs
strict. A `Measurement` here is refused: the threshold would be one somebody invented."""

_RANK_FIELD = ("economics", "net_return")


class DuplicateStrategyError(ValueError):
    """Two bundles claim one strategy id, so the top five could be five copies of one."""


@dataclass(frozen=True)
class CertificationCandidate:
    bundle: StrategyBundle
    dossier: Dossier


@dataclass(frozen=True)
class CertifiedStrategy:
    strategy_id: str
    net_return: float
    bundle: StrategyBundle
    dossier: Dossier


@dataclass(frozen=True)
class Rejection:
    strategy_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Certification:
    certified: tuple[CertifiedStrategy, ...]
    rejected: tuple[Rejection, ...]
    """Failed a gate, or could not be trusted at all. Never merely out-ranked."""
    not_placed: tuple[str, ...]
    """Cleared everything and ranked below the ceiling. Sound; there were better ones."""
    considered: int


def _integrity_reasons(candidate: CertificationCandidate, key: bytes) -> list[str]:
    """Whether this bundle and this dossier can be trusted at all.

    Reported alone when it fails: if the dossier is not the one the bundle was signed over, its
    gate values describe some other strategy, and listing them as reasons would mislead.
    """
    reasons: list[str] = []
    try:
        verify_bundle(candidate.bundle, key=key)
    except BundleSignatureError as exc:
        reasons.append(f"bundle signature/content: {exc}")
    try:
        bind_dossier(candidate.dossier, candidate.bundle)
    except DossierBindingError as exc:
        reasons.append(f"dossier binding: {exc}")
    return reasons


def gate_reasons(dossier: Dossier) -> list[str]:
    """Every gate that did not clear, in one pass. Says nothing about completeness.

    Public and separate from the completeness check because the pre-holdout selection in
    `[C-RUN-01]` needs exactly this: a dossier missing only `stability.lockbox_result` has not
    failed anything, and must still be judged on the gates it does carry. Two definitions of
    "the gates pass" would drift, and the one deciding who gets the single holdout look is the
    worse one to have drift.
    """
    reasons: list[str] = []
    for path in DISCLOSED:
        section, _, field = path.partition(".")
        if isinstance(dossier.sections.get(section, {}).get(field), Measurement):
            reasons.append(
                f"{path} carries a Measurement, but the blueprint DISCLOSES it rather than "
                "gating it (ADR-0014) — the threshold is one somebody invented"
            )

    for path in HARD_GATES:
        section, _, field = path.partition(".")
        value = dossier.sections.get(section, {}).get(field)
        if not isinstance(value, Measurement):
            reasons.append(
                f"{path} is not a Measurement ({type(value).__name__}), so it is ungated: a "
                "bare number carries no threshold and nothing can be derived from it"
            )
        elif not value.passed():
            reasons.append(f"{path} = {value.value} fails {value.direction} {value.threshold}")
    return reasons


def _gate_reasons(dossier: Dossier) -> list[str]:
    """Completeness and gates together — what certification itself requires."""
    reasons: list[str] = []
    try:
        require_complete(dossier)
    except IncompleteDossierError as exc:
        reasons.append(str(exc))
    return reasons + gate_reasons(dossier)


def _rank_score(dossier: Dossier) -> float | None:
    section, field = _RANK_FIELD
    value = dossier.sections.get(section, {}).get(field)
    if isinstance(value, Measurement):
        return float(value.value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def certify(candidates: Sequence[CertificationCandidate], *, key: bytes) -> Certification:
    """Apply the hard gates, rank the survivors, and keep at most `MAX_CERTIFIED`."""
    seen: set[str] = set()
    for candidate in candidates:
        strategy_id = candidate.bundle.strategy_id
        if strategy_id in seen:
            raise DuplicateStrategyError(
                f"two bundles claim strategy id {strategy_id!r}. Certifying both would let the "
                "top five be five copies of one strategy, which is the concentration the "
                "report exists to rule out."
            )
        seen.add(strategy_id)

    survivors: list[CertifiedStrategy] = []
    rejected: list[Rejection] = []

    for candidate in candidates:
        strategy_id = candidate.bundle.strategy_id
        score = _rank_score(candidate.dossier)
        reasons = _integrity_reasons(candidate, key)
        if not reasons:
            # Only once the artifact can be trusted: a dossier that is not this bundle's
            # describes some other strategy, and listing its gate values would mislead.
            reasons = _gate_reasons(candidate.dossier)
            if score is None:
                reasons.append(
                    f"{'.'.join(_RANK_FIELD)} is not a number, so the candidate cannot be ranked"
                )

        # `or score is None` is redundant at RUNTIME -- an unrankable score has already had
        # its reason appended above, so `reasons` is non-empty whenever it is None -- and a
        # mutation dropping it is correspondingly equivalent. It stays because it is what
        # narrows `float | None` to `float` for the constructor below; without it `make ci`'s
        # typecheck fails, which is the check that would otherwise catch the same mistake.
        if reasons or score is None:
            rejected.append(Rejection(strategy_id=strategy_id, reasons=tuple(reasons)))
            continue
        survivors.append(
            CertifiedStrategy(
                strategy_id=strategy_id,
                net_return=score,
                bundle=candidate.bundle,
                dossier=candidate.dossier,
            )
        )

    # Descending by score; ties on the id, so two runs of one cycle certify the same bundles in
    # the same order. Input order is never the tie-break -- it is not a property of the cycle.
    survivors.sort(key=lambda s: (-s.net_return, s.strategy_id))

    return Certification(
        certified=tuple(survivors[:MAX_CERTIFIED]),
        rejected=tuple(sorted(rejected, key=lambda r: r.strategy_id)),
        not_placed=tuple(sorted(s.strategy_id for s in survivors[MAX_CERTIFIED:])),
        considered=len(candidates),
    )
