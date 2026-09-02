"""Driving a certification cycle end to end  (§3.6/§12, M20, `[C-RUN-01]`).

Every piece existed before this; the thing that did not was the ORDER, and the order is the
whole design.

**The holdout confirms; it never selects.** Finalists are chosen on development evidence alone,
and only then is the lockbox opened — once, for all of them together. A candidate that was not a
finalist can never be certified here, however well the holdout would have treated it. Promoting
one afterwards is selection on the holdout, and reaching for a second look to check would void
the cycle outright (§3.6: one unlock per cycle; twice = void).

**One look, many candidates.** The sin is looking twice, not measuring several things in one
look, so the single unlock evaluates the whole finalist set and the evaluation is told exactly
whom it may measure. A finalist missing from what comes back is a broken evaluation rather than
a failing candidate — and the difference matters, because by then the unlock is spent. An id
that was *not* a finalist coming back is worse: something was measured against the sealed window
that had no business being there.

**An empty field never opens the box.** If nothing survives development there is nothing to
confirm, and an unlock recorded against no result is a look nobody can account for.

**Signing follows the holdout.** The bundle must commit to a dossier that already carries the
holdout result, or its signature covers evidence that was still to come.

The pre-holdout screen reuses `certify.gate_reasons` rather than restating it. Two definitions
of "the gates pass" drift, and the one deciding who gets the single look is the worse of the two
to have drift.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pips.certification.bundle_writer import IncompleteProvenanceError, write_bundle_for
from pips.certification.certify import (
    MAX_CERTIFIED,
    Certification,
    CertificationCandidate,
    Rejection,
    certify,
    gate_reasons,
)
from pips.certification.dossier import build_dossier, check_completeness
from pips.certification.lockbox_run import run_lockbox_once

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date

    from pips.bundle import IrNode
    from pips.certification.dossier import Dossier
    from pips.certification.lockbox_run import LockboxRun
    from pips.data.lockbox import SealedLockbox
    from pips.search.registry import Registry

__all__ = [
    "LOCKBOX_FIELD",
    "CertificationRun",
    "HoldoutResultError",
    "Nominee",
    "run_certification",
]

LOCKBOX_FIELD = "stability.lockbox_result"
"""The one required field a development run cannot fill, and the only absence the pre-holdout
screen forgives. Anything else missing means the candidate is not ready to be looked at."""


class HoldoutResultError(RuntimeError):
    """The single holdout look did not return what it was asked for. The unlock is spent."""


@dataclass(frozen=True)
class Nominee:
    """One candidate as it stands before the holdout: evidence, provenance and its IR."""

    strategy_id: str
    dossier: Dossier
    provenance: Mapping[str, Any]
    alpha_ir: tuple[IrNode, ...]
    portfolio_ir: tuple[IrNode, ...]


@dataclass(frozen=True)
class CertificationRun:
    certification: Certification
    finalists: tuple[str, ...]
    """Who was entered into the holdout, decided before it was opened."""
    not_finalists: tuple[Rejection, ...]
    """Who was not, and why. Never merely out-ranked without saying so."""
    unsignable: tuple[Rejection, ...]
    """Cleared the holdout but could not be built into a bundle. Reported, never dropped."""
    lockbox: LockboxRun | None
    """`None` when the box was never opened, which is a different outcome from opening it and
    certifying nothing."""


def _screen(nominee: Nominee) -> list[str]:
    """Why this nominee should not get the single look. Empty means it should."""
    reasons: list[str] = []
    claimed = nominee.provenance.get("strategy_id")
    if claimed != nominee.strategy_id:
        # Two names for one thing, and nothing else ties them: disagreeing means the run reports
        # finalists under one id and certifies under another, which no audit can reconcile.
        # Refused rather than overwritten -- silently correcting it hides a bundle built from
        # the wrong config.
        reasons.append(
            f"provenance names strategy {claimed!r} but the nominee is {nominee.strategy_id!r}"
        )
    reasons += gate_reasons(nominee.dossier)
    report = check_completeness(nominee.dossier)
    gaps = (set(report.missing) | set(report.hollow)) - {LOCKBOX_FIELD}
    reasons.extend(f"{path} was not recorded" for path in sorted(gaps))
    return reasons


def _rank(nominee: Nominee) -> tuple[float, str]:
    value = nominee.dossier.sections.get("economics", {}).get("net_return")
    score = float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0
    return (-score, nominee.strategy_id)


def _with_holdout(dossier: Dossier, result: object) -> Dossier:
    section, _, field = LOCKBOX_FIELD.partition(".")
    body = {**dossier.sections.get(section, {}), field: result}
    return build_dossier({**dossier.sections, section: body})


def run_certification(
    *,
    nominees: Sequence[Nominee],
    registry: Registry,
    lockbox: SealedLockbox,
    stage: str,
    evaluate_holdout: Callable[[date, date, tuple[str, ...]], Mapping[str, Any]],
    key: bytes,
) -> CertificationRun:
    """Screen, open the holdout once, then sign and certify what survives."""
    not_finalists: list[Rejection] = []
    eligible: list[Nominee] = []
    for nominee in nominees:
        reasons = _screen(nominee)
        if reasons:
            not_finalists.append(Rejection(nominee.strategy_id, tuple(reasons)))
        else:
            eligible.append(nominee)

    eligible.sort(key=_rank)
    # Capped here, before the box is opened: the look is for the field that could actually be
    # certified, not for everyone who happened to clear development.
    finalists = eligible[:MAX_CERTIFIED]
    not_finalists.extend(
        Rejection(n.strategy_id, ("ranked below the certification maximum",))
        for n in eligible[MAX_CERTIFIED:]
    )

    empty = Certification(certified=(), rejected=(), not_placed=(), considered=len(nominees))
    if not finalists:
        # Nothing to confirm. The sealed window stays sealed and the ledger records no unlock.
        return CertificationRun(
            certification=empty,
            finalists=(),
            not_finalists=tuple(sorted(not_finalists, key=lambda r: r.strategy_id)),
            unsignable=(),
            lockbox=None,
        )

    ids = tuple(n.strategy_id for n in finalists)
    run = run_lockbox_once(
        registry=registry,
        lockbox=lockbox,
        config_hash=";".join(ids),
        stage=stage,
        evaluate=lambda start, end: evaluate_holdout(start, end, ids),
    )

    measured = set(run.metrics)
    if missing := sorted(set(ids) - measured):
        raise HoldoutResultError(
            f"the holdout was opened and returned nothing for {missing}. The unlock is already "
            "spent, so this is a broken evaluation rather than a failing candidate — and it "
            "cannot be retried on this cycle."
        )
    if stowaways := sorted(measured - set(ids)):
        raise HoldoutResultError(
            f"the holdout returned results for {stowaways}, which were not finalists. Something "
            "was measured against the sealed window that had no business being there."
        )

    candidates: list[CertificationCandidate] = []
    unsignable: list[Rejection] = []
    for nominee in finalists:
        # AFTER the look, so the signature covers the holdout result rather than a promise of it.
        dossier = _with_holdout(nominee.dossier, run.metrics[nominee.strategy_id])
        try:
            bundle = write_bundle_for(
                dossier=dossier,
                provenance=nominee.provenance,
                alpha_ir=nominee.alpha_ir,
                portfolio_ir=nominee.portfolio_ir,
                key=key,
            )
        except IncompleteProvenanceError as exc:
            unsignable.append(Rejection(nominee.strategy_id, (str(exc),)))
            continue
        candidates.append(CertificationCandidate(bundle=bundle, dossier=dossier))

    certification = certify(candidates, key=key)
    return CertificationRun(
        certification=dataclasses.replace(certification, considered=len(nominees)),
        finalists=ids,
        not_finalists=tuple(sorted(not_finalists, key=lambda r: r.strategy_id)),
        unsignable=tuple(sorted(unsignable, key=lambda r: r.strategy_id)),
        lockbox=run,
    )
