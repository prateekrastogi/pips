"""Turning an S5 result into nominees  (§12, M20, `[C-NOM-01]`).

The mechanical join between the search and the certification chain. The reason it is not left to
a human is that S5 already *knows* things `[C-DOSS-01]` requires, and re-typing them is how a
dossier comes to describe a slightly different run than the one that happened — the correlation
cluster above all, which §12.2 asks for by name and which nothing outside S5 can reconstruct.

**Only the ensemble is nominated.** S5's funnel already dropped candidates for stated reasons;
readmitting one here would undo the narrowing without recording that it happened.

**An inadmissible S5 result nominates nobody.** `admissible` is false when there is no ensemble,
no solved venue, or the order budget is breached. A strategy with no rule to run it under is not
a certification candidate whatever its metrics say, and "no breaches" must not read as approval.

**Paperwork gaps are loud.** A nominee whose provenance cannot be found is *reported*, never
skipped: a silent skip shrinks the field and reads as "S5 found fewer", which is a claim about
the search rather than about the records.

The drafting goes through `[C-WRIT-01]`, so every refusal there still applies — this is a join,
not a way around it. In particular the caller may not supply `decision.correlation_cluster`: it
is S5's to state, and a caller-supplied one describes a comparison that did not happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pips.certification.run import Nominee
from pips.certification.writer import draft_dossier

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from pips.bundle import IrNode
    from pips.selection.cluster import Cluster
    from pips.selection.pareto import Candidate

__all__ = [
    "CLUSTER_FIELD",
    "NoProvenanceError",
    "NominationResult",
    "nominate",
]

CLUSTER_FIELD = "decision.correlation_cluster"


class NoProvenanceError(LookupError):
    """Raised BY THE CALLER's `provenance_for` when a strategy has no build record.

    A named exception rather than a `None` return, so the reason travels with the refusal — the
    reader wants to know *why* there is no record, not merely that there is none.
    """


class _S5Like(Protocol):
    ensemble: Sequence[Candidate]
    clusters: Sequence[Cluster]

    @property
    def admissible(self) -> bool: ...


@dataclass(frozen=True)
class NominationResult:
    nominees: tuple[Nominee, ...]
    unsupplied: Mapping[str, tuple[str, ...]]
    """Per strategy, the dossier paths the draft could not fill. Carried rather than dropped:
    the gap is the finding, and losing it here hides it until certification."""
    refused: tuple[str, ...]
    """Ensemble members that could not be nominated, and why."""


def _cluster_note(strategy_id: str, clusters: Sequence[Cluster]) -> str:
    if not clusters:
        return f"{strategy_id}: correlation clustering was not run for this result"
    for cluster in clusters:
        if strategy_id in cluster.members:
            members = ", ".join(cluster.members)
            return f"{strategy_id}: cluster [{members}], represented by {cluster.representative}"
    # Deliberately not the nearest cluster: borrowing a neighbour's would misreport what this
    # candidate was compared against.
    return f"{strategy_id}: in no reported cluster"


def nominate(
    *,
    s5: _S5Like,
    evidence_for: Callable[[str], Mapping[str, Any]],
    provenance_for: Callable[[str], Mapping[str, Any]],
    alpha_ir_for: Callable[[str], tuple[IrNode, ...]],
    portfolio_ir_for: Callable[[str], tuple[IrNode, ...]],
) -> NominationResult:
    """Draft a dossier and gather provenance for every admissible ensemble member."""
    if not s5.admissible:
        return NominationResult(
            nominees=(),
            unsupplied={},
            refused=(
                "the S5 result is not admissible — no ensemble, no solved venue, or the order "
                "budget is breached. There is no rule to run these under, and certifying them "
                "would let 'no breaches' read as approval.",
            ),
        )

    nominees: list[Nominee] = []
    unsupplied: dict[str, tuple[str, ...]] = {}
    refused: list[str] = []

    for candidate in s5.ensemble:
        evidence = dict(evidence_for(candidate.id))
        if CLUSTER_FIELD in evidence:
            raise ValueError(
                f"{CLUSTER_FIELD} is S5's to state, not the caller's. A supplied one describes "
                "a comparison that did not happen, and nothing outside S5 can reconstruct which "
                "near-variants collapsed together."
            )
        evidence[CLUSTER_FIELD] = _cluster_note(candidate.id, s5.clusters)

        try:
            provenance = provenance_for(candidate.id)
        except NoProvenanceError as exc:
            refused.append(f"{candidate.id}: {exc}")
            continue

        draft = draft_dossier(candidate=candidate, evidence=evidence)
        unsupplied[candidate.id] = draft.unsupplied
        nominees.append(
            Nominee(
                strategy_id=candidate.id,
                dossier=draft.dossier,
                provenance=provenance,
                alpha_ir=alpha_ir_for(candidate.id),
                portfolio_ir=portfolio_ir_for(candidate.id),
            )
        )

    return NominationResult(nominees=tuple(nominees), unsupplied=unsupplied, refused=tuple(refused))
