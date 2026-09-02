"""Turning an S5 result into nominees  (§12, M20, `[C-NOM-01]`).

The mechanical join between the search and the certification chain, and the reason it is not
left to a human is that S5 already *knows* things `[C-DOSS-01]` requires. Re-typing them is how
a dossier comes to describe a slightly different run than the one that happened — the
correlation cluster in particular, which §12.2 asks for by name and which nothing outside S5 can
reconstruct.

**Only the ensemble is nominated.** S5's funnel already dropped candidates for stated reasons;
readmitting one here would undo the narrowing without recording that it happened.

**An inadmissible S5 result nominates nobody.** `admissible` is false when there is no ensemble,
no solved venue, or the order budget is breached — and a strategy with no rule to run it under
is not a certification candidate, whatever its metrics say.

**A nominee with no provenance is reported, not skipped.** A silent skip shrinks the field and
reads as "S5 found fewer", which is a claim about the search rather than about the paperwork.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from pips.bundle import IrNode
from pips.certification.dossier import REQUIRED_FIELDS, Measurement
from pips.certification.nominate import S5_OWNED, NoProvenanceError, nominate
from pips.certification.writer import GATE_SOURCES, METRIC_SOURCES
from pips.selection.cluster import Cluster
from pips.selection.pareto import Candidate

if TYPE_CHECKING:
    from collections.abc import Mapping

ALPHA = (IrNode(op="zscore", inputs=("close",), params={"window": 20}),)
PORTFOLIO = (IrNode(op="erc_weights", inputs=("alpha",), params={}),)
DERIVED_PATHS = {spec.path for spec in METRIC_SOURCES}


def metrics() -> dict[str, float]:
    values = {spec.metric: (0.0 if spec.direction == "at_most" else 1.0) for spec in GATE_SOURCES}
    values["net_return"] = 0.04
    values["max_drawdown"] = 0.02
    return values


def evidence_for(strategy_id: str) -> dict[str, Any]:
    """Everything the caller owns: policy, operations, identity.

    Never a gate, and never `decision.correlation_cluster` — that one is S5's, and the adapter
    refuses a caller who offers it.
    """
    return {
        f"{s}.{f}": f"{strategy_id}:{s}.{f}"
        for s, fields in REQUIRED_FIELDS.items()
        for f in fields
        if f"{s}.{f}" not in DERIVED_PATHS and f"{s}.{f}" not in S5_OWNED
    }


def provenance_for(strategy_id: str) -> dict[str, Any]:
    from pips.certification.bundle_writer import HASH_FIELDS, REQUIRED_PROVENANCE

    base: dict[str, Any] = {}
    for index, name in enumerate(sorted(REQUIRED_PROVENANCE)):
        base[name] = f"{index:064x}" if name in HASH_FIELDS else f"{strategy_id}-{name}"
    base["strategy_id"] = strategy_id
    base["golden_fixture_hashes"] = ("a" * 64,)
    base["parent_experiment_ids"] = ("exp-1",)
    base["valid_from"] = "2026-09-01"
    base["valid_until"] = "2026-12-01"
    return base


class FakeS5:
    """Only what the adapter is allowed to read."""

    def __init__(
        self,
        ensemble: tuple[Candidate, ...],
        *,
        clusters: tuple[Cluster, ...] = (),
        admissible: bool = True,
    ) -> None:
        self.ensemble = ensemble
        self.clusters = clusters
        self.admissible = admissible


def candidate(strategy_id: str, **over: float) -> Candidate:
    return Candidate(id=strategy_id, metrics={**metrics(), **over})


def call(s5: FakeS5, **over: Any) -> Any:
    kwargs: dict[str, Any] = {
        "s5": s5,
        "evidence_for": evidence_for,
        "provenance_for": provenance_for,
        "alpha_ir_for": lambda _: ALPHA,
        "portfolio_ir_for": lambda _: PORTFOLIO,
    }
    kwargs.update(over)
    return nominate(**kwargs)


# ---------------------------------------------------------------- only the ensemble -----


def test_one_nominee_per_ensemble_member() -> None:
    result = call(FakeS5((candidate("A01"), candidate("A02"))))
    assert [n.strategy_id for n in result.nominees] == ["A01", "A02"]


def test_an_inadmissible_result_nominates_nobody() -> None:
    """No ensemble, no solved venue, or a breached order budget — there is no rule to run it
    under, and "no breaches" would otherwise read as approval."""
    result = call(FakeS5((candidate("A01"),), admissible=False))

    assert result.nominees == ()
    assert "admissible" in " | ".join(result.refused)


def test_an_empty_ensemble_nominates_nobody() -> None:
    result = call(FakeS5(()))
    assert result.nominees == ()


# ---------------------------------------------- what S5 knows and nobody should re-type -----


def test_the_correlation_cluster_comes_from_s5() -> None:
    """§12.2 asks for it by name, and nothing outside S5 can reconstruct which near-variants
    collapsed together or which one spoke for them."""
    clusters = (Cluster(members=("A01", "A02"), representative="A01"),)
    result = call(FakeS5((candidate("A01"),), clusters=clusters))

    recorded = result.nominees[0].dossier.sections["decision"]["correlation_cluster"]
    assert "A01" in recorded
    assert "A02" in recorded


def test_a_candidate_in_no_cluster_says_so_rather_than_inheriting_one() -> None:
    """Borrowing a neighbour's cluster would misreport what it was compared against."""
    clusters = (Cluster(members=("A02", "A03"), representative="A02"),)
    result = call(FakeS5((candidate("A01"),), clusters=clusters))

    recorded = result.nominees[0].dossier.sections["decision"]["correlation_cluster"]
    assert "A02" not in recorded
    assert "A03" not in recorded


def test_the_caller_may_not_supply_the_correlation_cluster() -> None:
    """It is S5's to state. A caller-supplied one describes a comparison that did not happen."""

    def evidence(strategy_id: str) -> Mapping[str, Any]:
        return {**evidence_for(strategy_id), "decision.correlation_cluster": "whatever I like"}

    with pytest.raises(ValueError, match="correlation_cluster"):
        call(FakeS5((candidate("A01"),)), evidence_for=evidence)


# ------------------------------------------------------------- paperwork gaps are loud -----


def test_a_nominee_with_no_provenance_is_reported_not_skipped() -> None:
    """A silent skip shrinks the field and reads as "S5 found fewer"."""

    def provenance(strategy_id: str) -> Mapping[str, Any]:
        if strategy_id == "A02":
            raise NoProvenanceError("no build record for A02")
        return provenance_for(strategy_id)

    result = call(FakeS5((candidate("A01"), candidate("A02"))), provenance_for=provenance)

    assert [n.strategy_id for n in result.nominees] == ["A01"]
    assert "A02" in " | ".join(result.refused)


def test_the_writers_refusals_still_apply() -> None:
    """The adapter routes through `[C-WRIT-01]`; it does not become a way around it."""

    def evidence(strategy_id: str) -> Mapping[str, Any]:
        return {
            **evidence_for(strategy_id),
            "stability.concentration": Measurement(0.1, 9.9, "at_most"),
        }

    with pytest.raises(ValueError, match="no declared threshold"):
        call(FakeS5((candidate("A01"),)), evidence_for=evidence)


def test_the_unsupplied_paths_are_carried_for_the_reader() -> None:
    """The gap the draft found is the finding; losing it here hides it until certification.

    A caller who fills everything leaves no gap — including `stability.concentration`, which may
    be supplied as a plain number and is then honestly *ungated* rather than absent. The gap
    this carries is the one a caller actually leaves.
    """

    def thin(strategy_id: str) -> Mapping[str, Any]:
        return {
            path: value
            for path, value in evidence_for(strategy_id).items()
            if path != "capacity.participation"
        }

    result = call(FakeS5((candidate("A01"),)), evidence_for=thin)
    assert result.unsupplied["A01"] == ("capacity.participation",)


def test_a_full_caller_leaves_no_gap() -> None:
    result = call(FakeS5((candidate("A01"),)))
    assert result.unsupplied["A01"] == ()


def test_metrics_reach_the_dossier_as_gates() -> None:
    result = call(FakeS5((candidate("A01"),)))
    dsr = result.nominees[0].dossier.sections["economics"]["dsr"]
    assert isinstance(dsr, Measurement)
    assert dsr.threshold == 0.95


def test_the_strategy_id_comes_from_s5() -> None:
    """Found by running `make certify-smoke`: the report listed `identity.strategy_id` as a
    field the factory cannot supply, while the adapter was holding it the whole time.

    Same argument as the correlation cluster — it is S5's to state, so the caller is refused.
    """
    result = call(FakeS5((candidate("A01"),)))
    assert result.nominees[0].dossier.sections["identity"]["strategy_id"] == "A01"


def test_the_caller_may_not_supply_the_strategy_id() -> None:
    def evidence(strategy_id: str) -> Mapping[str, Any]:
        return {**evidence_for(strategy_id), "identity.strategy_id": "something-else"}

    with pytest.raises(ValueError, match=re.escape("identity.strategy_id")):
        call(FakeS5((candidate("A01"),)), evidence_for=evidence)
