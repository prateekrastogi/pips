"""Certification: top-5 is a MAXIMUM, and zero is a valid output  (§12, M20, `[C-CERT-01]`).

The P4 gate reads *0-5 bundles; every certified one passes hard gates*. The dangerous
implementation is `sorted(candidates)[:5]`, which returns five whenever five exist — a number
that looks like a result and is really just the size of the input.

**The gates are re-derived, never read.** This is what `Measurement` having no verdict field was
for (`[C-DOSS-01]`): the selector recomputes every pass from the value and its threshold, so a
dossier cannot assert one. A gate field that holds a bare number instead of a `Measurement` is
therefore *ungated* — it has no threshold, nothing can be derived from it, and accepting it
would let "recorded" read as "passed".

**Not placing is not failing.** A candidate that cleared every gate and ranked sixth is reported
apart from one that failed PBO. Merging them into a single "rejected" list would say the sixth
was unsound, which is a different and much stronger claim than "there were five better ones".

**An empty certification carries its reasons.** Zero certified is the expected output of a bad
cycle, and it has to be distinguishable from a selector that never ran — an empty list is not.
"""

from __future__ import annotations

import inspect

import pytest

from pips.bundle import IrNode, build_bundle
from pips.certification.certify import (
    DISCLOSED,
    HARD_GATES,
    MAX_CERTIFIED,
    Certification,
    CertificationCandidate,
    DuplicateStrategyError,
    certify,
)
from pips.certification.dossier import REQUIRED_FIELDS, Dossier, Measurement, build_dossier

KEY = b"test-signing-key"

PASSING: dict[str, Measurement] = {
    "economics.dsr": Measurement(0.97, 0.95, "at_least"),
    "stability.pbo": Measurement(0.18, 0.25, "at_most"),
    "stability.spa_p": Measurement(0.04, 0.10, "at_most"),
    "stability.parameter_plateau": Measurement(0.80, 0.50, "at_least"),
    "stability.concentration": Measurement(0.30, 0.40, "at_most"),
    "stress.cost_1_5x": Measurement(0.60, 0.00, "at_least"),
    "stress.delay_1_bar": Measurement(0.55, 0.00, "at_least"),
    # ADR-0015: twelve outer folds post-seal. Three years less a holdout yields 20-24.
    "stability.outer_folds": Measurement(24, 12, "at_least"),
}

DISCLOSURES: dict[str, float] = {
    # Reported, never gated (ADR-0014). A Measurement here would be refused, which is what
    # `test_a_measurement_in_a_disclosed_field_is_refused` holds.
    "stress.cost_2x": 0.20,
    "stress.delay_2_bar": 0.10,
}


def dossier_for(**over: object) -> Dossier:
    """Every gate passing, then `over` applied last so a test can break exactly one thing.

    `net_return` is popped rather than left in `over` because the other keys are dotted paths
    and it is not one; a dotted `economics.net_return` still overrides it, which is the order
    the boolean test depends on.
    """
    net_return = over.pop("net_return", 0.04)
    sections: dict[str, dict[str, object]] = {
        name: {field: f"{name}.{field}" for field in fields}
        for name, fields in REQUIRED_FIELDS.items()
    }
    for path, value in {**PASSING, **DISCLOSURES}.items():
        section, _, field = path.partition(".")
        sections[section][field] = value
    sections["economics"]["net_return"] = net_return
    for path, value in over.items():
        section, _, field = path.partition(".")
        sections[section][field] = value
    return build_dossier(sections)


def candidate(strategy_id: str, **over: object) -> CertificationCandidate:
    dossier = dossier_for(**over)
    bundle = build_bundle(
        key=KEY,
        strategy_id=strategy_id,
        parent_experiment_ids=("exp-1",),
        code_hash="a" * 64,
        build_environment_hash="b" * 64,
        data_snapshot_root="c" * 64,
        universe_hash="d" * 64,
        calendar_hash="e" * 64,
        instrument_master_hash="f" * 64,
        corporate_action_hash="0" * 64,
        cost_hash="1" * 64,
        risk_policy_hash="2" * 64,
        numeric_semantics_version="1.0",
        bar_semantics_version="1.0",
        alpha_ir_version="1.0",
        portfolio_ir_version="1.0",
        valid_from="2026-09-01",
        valid_until="2026-12-01",
        broker_context="FLATTRADE",
        capital_range="2L",
        alpha_ir=(IrNode(op="zscore", inputs=("close",), params={"window": 20}),),
        portfolio_ir=(IrNode(op="erc_weights", inputs=("alpha",), params={}),),
        validation_dossier_hash=dossier.dossier_hash(),
        trial_registry_root="4" * 64,
        golden_fixture_hashes=("5" * 64,),
    )
    return CertificationCandidate(bundle=bundle, dossier=dossier)


def reason_for(result: Certification, strategy_id: str) -> str:
    for rejection in result.rejected:
        if rejection.strategy_id == strategy_id:
            return " | ".join(rejection.reasons)
    raise AssertionError(f"{strategy_id} was not rejected")


# ------------------------------------------------------------- five is a ceiling -----


def test_eight_sound_candidates_certify_five() -> None:
    result = certify([candidate(f"A{i:02d}", net_return=0.01 * i) for i in range(1, 9)], key=KEY)
    assert len(result.certified) == MAX_CERTIFIED == 5


def test_two_sound_candidates_certify_two() -> None:
    """The count is a property of the candidates, not of the ceiling."""
    result = certify([candidate("A01"), candidate("A02", net_return=0.03)], key=KEY)
    assert [c.strategy_id for c in result.certified] == ["A01", "A02"]


def test_the_ceiling_cannot_be_raised_by_the_caller() -> None:
    """Structural: a maximum that takes an argument is a default."""
    taken = set(inspect.signature(certify).parameters)
    assert not (taken & {"maximum", "max_certified", "k", "top_n", "limit", "n"}), taken


def test_not_placing_is_reported_apart_from_failing() -> None:
    """Sixth place is not a defect, and saying so would be a much stronger claim."""
    result = certify([candidate(f"A{i:02d}", net_return=0.01 * i) for i in range(1, 9)], key=KEY)

    assert set(result.not_placed) == {"A01", "A02", "A03"}
    assert result.rejected == ()


# --------------------------------------------------------------- zero is a result -----


def test_zero_certified_is_a_valid_output() -> None:
    result = certify(
        [candidate("A01", **{"stability.pbo": Measurement(0.40, 0.25, "at_most")})], key=KEY
    )
    assert result.certified == ()
    assert result.considered == 1


def test_an_empty_certification_still_says_why() -> None:
    """Otherwise it is indistinguishable from a selector that never ran."""
    result = certify(
        [candidate("A01", **{"stability.pbo": Measurement(0.40, 0.25, "at_most")})], key=KEY
    )
    assert "stability.pbo" in reason_for(result, "A01")


def test_no_candidates_at_all_is_not_an_error() -> None:
    result = certify([], key=KEY)
    assert result.certified == ()
    assert result.considered == 0


# ------------------------------------------------------- the gates are re-derived -----


@pytest.mark.parametrize("gate", HARD_GATES)
def test_every_hard_gate_can_reject_on_its_own(gate: str) -> None:
    failing = {
        "at_least": Measurement(0.0, 0.95, "at_least"),
        "at_most": Measurement(9.99, 0.25, "at_most"),
    }[PASSING[gate].direction]
    result = certify([candidate("A01", **{gate: failing})], key=KEY)

    assert result.certified == ()
    assert gate in reason_for(result, "A01")


@pytest.mark.parametrize("gate", HARD_GATES)
def test_a_bare_number_where_a_gate_belongs_is_ungated_not_passed(gate: str) -> None:
    """A float has no threshold, so nothing can be derived from it.

    Accepting it would let a dossier clear a gate by recording a number and no bar — which is
    the stored-verdict problem wearing a different hat.
    """
    result = certify([candidate("A01", **{gate: 0.0001})], key=KEY)

    assert result.certified == ()
    assert gate in reason_for(result, "A01")


def test_a_failing_candidate_hears_every_reason_at_once() -> None:
    """A caller who learns them one at a time runs certification once per gate."""
    result = certify(
        [
            candidate(
                "A01",
                **{
                    "stability.pbo": Measurement(0.40, 0.25, "at_most"),
                    "stability.spa_p": Measurement(0.50, 0.10, "at_most"),
                },
            )
        ],
        key=KEY,
    )
    reasons = reason_for(result, "A01")
    assert "stability.pbo" in reasons
    assert "stability.spa_p" in reasons


def test_the_hard_gates_match_the_blueprints_gate_table() -> None:
    """Structural: a gate dropped from this tuple is a gate nothing enforces.

    `stress.cost_2x` and `stress.delay_2_bar` are deliberately absent. The blueprint's own
    certification row reads *positive after 1.5x cost and survives +1-bar delay; 2x result
    DISCLOSED* — gating the 2x cases would reject strategies the specification certifies, which
    is a defect even though it errs strict.
    """
    assert set(HARD_GATES) == {
        "economics.dsr",
        "stability.pbo",
        "stability.spa_p",
        "stability.parameter_plateau",
        "stability.concentration",
        "stress.cost_1_5x",
        "stress.delay_1_bar",
        "stability.outer_folds",
    }


def test_gated_and_disclosed_are_disjoint() -> None:
    """A field cannot be both held to a bar and merely reported."""
    assert not set(HARD_GATES) & set(DISCLOSED)


def test_a_disclosed_field_is_reported_not_gated() -> None:
    """A bare number in `cost_2x` is the CORRECT shape: it has no bar to be held to."""
    result = certify([candidate("A01", **{"stress.cost_2x": -0.20})], key=KEY)
    assert [c.strategy_id for c in result.certified] == ["A01"]


def test_a_disclosed_field_must_still_be_present() -> None:
    """Disclosure is an obligation. An absent 2x result is an undisclosed one."""
    result = certify([candidate("A01", **{"stress.cost_2x": None})], key=KEY)
    assert result.certified == ()
    assert "stress.cost_2x" in reason_for(result, "A01")


# ---------------------------------------------------------------------- integrity -----


def test_a_dossier_that_is_not_the_bundles_is_refused() -> None:
    """`verify_bundle` cannot see this: the bundle signs the dossier's hash, not its bytes."""
    sound = candidate("A01")
    swapped = CertificationCandidate(bundle=sound.bundle, dossier=dossier_for(net_return=0.09))

    result = certify([swapped], key=KEY)
    assert result.certified == ()
    assert "dossier" in reason_for(result, "A01").lower()


def test_a_bundle_signed_by_another_key_is_refused() -> None:
    result = certify([candidate("A01")], key=b"a-different-key")
    assert result.certified == ()
    assert "signature" in reason_for(result, "A01").lower()


def test_an_incomplete_dossier_cannot_be_certified() -> None:
    """A gate nobody recorded is not a gate that passed."""
    result = certify([candidate("A01", **{"operations.kill_thresholds": "TBD"})], key=KEY)
    assert result.certified == ()
    assert "operations.kill_thresholds" in reason_for(result, "A01")


def test_two_bundles_claiming_one_strategy_id_are_refused() -> None:
    """Otherwise the top five can be five copies of one strategy."""
    with pytest.raises(DuplicateStrategyError, match="A01"):
        certify([candidate("A01"), candidate("A01", net_return=0.09)], key=KEY)


# ---------------------------------------------------------------------- ordering -----


def test_the_ranking_is_by_net_return_descending() -> None:
    result = certify(
        [candidate("A01", net_return=0.02), candidate("A02", net_return=0.07)], key=KEY
    )
    assert [c.strategy_id for c in result.certified] == ["A02", "A01"]


def test_ties_break_on_the_strategy_id_not_on_input_order() -> None:
    """Two runs of the same cycle must certify the same bundles in the same order."""
    forward = certify([candidate("A01"), candidate("A02")], key=KEY)
    backward = certify([candidate("A02"), candidate("A01")], key=KEY)
    assert [c.strategy_id for c in forward.certified] == ["A01", "A02"]
    assert forward.certified == backward.certified


def test_rejections_are_ordered_too() -> None:
    bad = {"stability.pbo": Measurement(0.40, 0.25, "at_most")}
    result = certify([candidate("A02", **bad), candidate("A01", **bad)], key=KEY)
    assert [r.strategy_id for r in result.rejected] == ["A01", "A02"]


@pytest.mark.parametrize("boolean", [True, False])
def test_a_boolean_net_return_is_not_a_rankable_number(boolean: bool) -> None:
    """`True` is an `int` in Python, so a boolean landing in `net_return` ranks as a 100%
    return and sorts first. The dossier deliberately counts `False` as a recorded value, so
    completeness will not catch it either — this is the only place that can.
    """
    result = certify([candidate("A01", **{"economics.net_return": boolean})], key=KEY)

    assert result.certified == ()
    assert "net_return" in reason_for(result, "A01")


def test_a_measurement_in_a_disclosed_field_is_refused() -> None:
    """A bar on a disclosure is a bar somebody invented (ADR-0014)."""
    result = certify(
        [candidate("A01", **{"stress.cost_2x": Measurement(0.2, 0.0, "at_least")})], key=KEY
    )
    assert result.certified == ()
    assert "stress.cost_2x" in reason_for(result, "A01")
