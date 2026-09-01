"""The certification dossier: the evidence a bundle is certified ON  (§12.2, `[C-BNDL-01]`).

The bundle says what will run. The dossier says why anyone believed it should. §12.2 fixes eight
sections; the blueprint's §12.6 fixes the content — *all gate values, DSR/PBO/SPA numbers, N at
certification, holdout result*. Values, not verdicts.

Four properties carry the weight here.

**Absence must not read as a value.** A completeness check that asks `key in section` passes on
`None`, on `""`, and on `"N/A"` — and a dossier full of `"TBD"` then certifies a strategy nobody
measured. This is the same failure as a rate-limited HTTP 200 or a NOT_RUN gate read as PASSED:
the dangerous absence is the one wearing the costume of data.

**But zero is a value.** `0.0` cost share and `False` are measurements, and a check written as
`if not value` erases exactly the results that matter most.

**Completeness is not passing.** `complete` asks whether everything was recorded, never whether
it was good. Conflating them makes a failing strategy look unmeasured and an unmeasured one look
failed — and it makes the rejection dossier, which is what rule 4 counts, impossible to write.

**The bundle's signature does not protect the dossier.** The bundle names the dossier by hash;
the hash is one of the bundle's signed fields. So an edited dossier leaves the bundle verifying
perfectly, and only the binding check catches it. Anyone who runs `verify_bundle` alone can be
handed any dossier at all.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from pips.bundle import IrNode, build_bundle
from pips.certification.dossier import (
    REQUIRED_FIELDS,
    SECTIONS,
    DossierBindingError,
    IncompleteDossierError,
    Measurement,
    bind_dossier,
    build_dossier,
    check_completeness,
    require_complete,
)

KEY = b"test-signing-key"


def _filled() -> dict[str, dict[str, Any]]:
    """Every required field present with a plausible value. Tests remove from this, never add."""
    filled: dict[str, dict[str, Any]] = {}
    for section, fields in REQUIRED_FIELDS.items():
        filled[section] = {name: f"{section}.{name}" for name in fields}
    # A few carry real types, so the checks below exercise more than strings.
    filled["economics"]["net_return"] = 0.041
    filled["economics"]["dsr"] = Measurement(value=0.97, threshold=0.95, direction="at_least")
    filled["stability"]["pbo"] = Measurement(value=0.18, threshold=0.25, direction="at_most")
    filled["stability"]["trials_viewed"] = 812
    filled["decision"]["outcome"] = "promoted"
    return filled


def dossier(**over: dict[str, Any]) -> Any:
    sections = _filled()
    for name, patch in over.items():
        sections[name] = {**sections.get(name, {}), **patch}
    return build_dossier(sections)


def _bundle(dossier_hash: str) -> Any:
    return build_bundle(
        key=KEY,
        strategy_id="A01-lb35",
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
        validation_dossier_hash=dossier_hash,
        trial_registry_root="4" * 64,
        golden_fixture_hashes=("5" * 64,),
    )


# ------------------------------------------------------- absence is not a value -----


def test_a_complete_dossier_reports_complete() -> None:
    report = check_completeness(dossier())
    assert report.complete
    assert report.missing == ()
    assert report.hollow == ()


def test_a_missing_field_is_named_not_merely_counted() -> None:
    """`complete: False` sends the reader hunting through eight sections."""
    sections = _filled()
    del sections["capacity"]["participation"]
    report = check_completeness(build_dossier(sections))

    assert not report.complete
    assert report.missing == ("capacity.participation",)


def test_a_missing_section_names_all_of_its_fields() -> None:
    sections = _filled()
    del sections["stress"]
    report = check_completeness(build_dossier(sections))

    assert not report.complete
    assert set(report.missing) == {f"stress.{name}" for name in REQUIRED_FIELDS["stress"]}


@pytest.mark.parametrize("placeholder", ["", "   ", "N/A", "n/a", "TBD", "unknown", "-", "?"])
def test_a_placeholder_is_not_a_value(placeholder: str) -> None:
    """The dangerous absence is the one that looks deliberate.

    Something wrote `"TBD"`; a check that only asks whether the key exists says the field was
    measured. There is no way to express "genuinely unavailable" here, and that is the point: a
    strategy whose kill thresholds are unknown is not certifiable, it is incomplete.
    """
    report = check_completeness(dossier(operations={"kill_thresholds": placeholder}))

    assert not report.complete
    assert report.hollow == ("operations.kill_thresholds",)
    assert report.missing == (), "present-but-hollow is a different fix from never-written"


@pytest.mark.parametrize("empty", [None, [], {}, ()])
def test_an_empty_container_is_hollow(empty: object) -> None:
    report = check_completeness(dossier(stability={"outer_folds": empty}))
    assert not report.complete
    assert report.hollow == ("stability.outer_folds",)


@pytest.mark.parametrize("value", [0, 0.0, False, 0.0000, -0.0])
def test_zero_and_false_are_values(value: object) -> None:
    """`if not value` erases a zero cost share and a `False` — the results that matter most."""
    report = check_completeness(dossier(economics={"cost_share": value}))
    assert report.complete, f"{value!r} is a measurement, not an absence"


# ---------------------------------------------------- completeness is not passing -----


def test_a_failing_measurement_leaves_the_dossier_complete() -> None:
    """Everything was recorded. It recorded a failure. Those are different questions.

    Conflating them makes the rejection dossier — the one rule 4 counts — unwritable.
    """
    report = check_completeness(dossier(stability={"pbo": Measurement(0.40, 0.25, "at_most")}))

    assert report.complete
    assert report.missing == ()
    assert report.failing == ("stability.pbo",)


def test_a_rejection_dossier_is_as_complete_as_a_promotion() -> None:
    """Top-5 is a maximum and fewer is a valid output, so zero must be documentable."""
    rejected = dossier(
        decision={"outcome": "rejected", "rationale": "PBO 0.40 over the 0.25 ceiling"},
        stability={"pbo": Measurement(0.40, 0.25, "at_most")},
    )
    report = check_completeness(rejected)

    assert report.complete
    assert report.failing == ("stability.pbo",)


def test_require_complete_names_every_gap_at_once() -> None:
    """One raise per run, not one per re-run: a caller fixing gaps one at a time is a caller
    who runs the whole certification eight times."""
    sections = _filled()
    del sections["capacity"]["positions"]
    sections["operations"]["entry_cutoff"] = "TBD"

    with pytest.raises(IncompleteDossierError) as exc:
        require_complete(build_dossier(sections))

    assert "capacity.positions" in str(exc.value)
    assert "operations.entry_cutoff" in str(exc.value)


def test_require_complete_passes_a_dossier_whose_measurements_failed() -> None:
    require_complete(dossier(stability={"pbo": Measurement(0.40, 0.25, "at_most")}))


# ------------------------------------------------------- values, never verdicts -----


def test_a_measurement_has_nowhere_to_store_a_verdict() -> None:
    """A stored verdict can disagree with the number beside it, and the reader trusts the verdict.

    Structural rather than behavioural: there must be no field to lie in.
    """
    names = {f.name for f in dataclasses.fields(Measurement)}
    for verdict in ("passed", "pass", "ok", "result", "verdict", "status", "certified"):
        assert verdict not in names, f"Measurement.{verdict} could contradict .value"


@pytest.mark.parametrize(
    ("value", "threshold", "direction", "expected"),
    [
        (0.95, 0.95, "at_least", True),
        (0.95, 0.95, "at_most", True),
        (0.9499, 0.95, "at_least", False),
        (0.9501, 0.95, "at_most", False),
    ],
)
def test_a_measurement_passes_at_the_boundary(
    value: float, threshold: float, direction: str, expected: bool
) -> None:
    assert Measurement(value, threshold, direction).passed() is expected


def test_at_most_is_not_at_least() -> None:
    """PBO ≤ 0.25 read as ≥ turns the worst overfitting score in the run into a pass."""
    pbo = Measurement(value=0.40, threshold=0.25, direction="at_most")
    assert not pbo.passed()
    assert Measurement(value=0.40, threshold=0.25, direction="at_least").passed()


def test_an_unknown_direction_is_refused() -> None:
    """A silent default would read every ≤ gate as a ≥ gate."""
    with pytest.raises(ValueError, match="direction"):
        Measurement(value=1.0, threshold=0.5, direction="greater")


# ----------------------------------------------------------------- the binding -----


def test_the_dossier_hash_covers_every_section() -> None:
    """A section outside the hash is a section that can be rewritten after certification."""
    original = dossier()
    for section, fields in REQUIRED_FIELDS.items():
        name = fields[0]
        body = {**original.sections[section], name: "moved"}
        moved = build_dossier({**original.sections, section: body})
        assert moved.dossier_hash() != original.dossier_hash(), f"{section}.{name} is not hashed"


def test_the_dossier_hash_ignores_key_order() -> None:
    a = build_dossier(_filled())
    reversed_sections = {
        name: dict(reversed(list(fields.items())))
        for name, fields in reversed(list(_filled().items()))
    }
    assert build_dossier(reversed_sections).dossier_hash() == a.dossier_hash()


def test_the_bundle_binds_the_dossier_by_hash() -> None:
    d = dossier()
    bind_dossier(d, _bundle(d.dossier_hash()))


def test_an_edited_dossier_breaks_the_binding_while_the_bundle_still_verifies() -> None:
    """The bundle's signature is no protection at all here.

    The bundle hashes the dossier's hash, not its contents, so editing the dossier changes
    nothing inside the bundle. `verify_bundle` passes on a strategy whose entire evidence base
    has been swapped; only this check notices.
    """
    from pips.bundle import verify_bundle

    honest = dossier()
    signed = _bundle(honest.dossier_hash())
    edited = build_dossier(
        {**honest.sections, "economics": {**honest.sections["economics"], "net_return": 9.99}}
    )

    verify_bundle(signed, key=KEY)  # unchanged, and it says so

    with pytest.raises(DossierBindingError, match="does not match"):
        bind_dossier(edited, signed)


def test_binding_refuses_a_dossier_for_a_different_strategy() -> None:
    mine = dossier()
    theirs = dossier(identity={"strategy_id": "A03-mom"})
    with pytest.raises(DossierBindingError):
        bind_dossier(theirs, _bundle(mine.dossier_hash()))


# -------------------------------------------------------------------- structure -----


def test_every_section_declares_its_required_fields() -> None:
    """A section with no required fields is a section that is always complete."""
    assert tuple(REQUIRED_FIELDS) == SECTIONS
    for section in SECTIONS:
        assert REQUIRED_FIELDS[section], f"{section} requires nothing, so it proves nothing"


def test_an_unknown_section_is_refused() -> None:
    """Otherwise the real section reports missing while the typo sits there looking filled."""
    with pytest.raises(ValueError, match="econmics"):
        build_dossier({**_filled(), "econmics": {"net_return": 1.0}})


def test_an_unknown_field_within_a_section_is_refused() -> None:
    with pytest.raises(ValueError, match="net_retrun"):
        build_dossier({**_filled(), "economics": {**_filled()["economics"], "net_retrun": 1.0}})


def test_a_measurement_does_not_hash_like_a_plain_dict() -> None:
    """The sealed hash must tell a recorded gate from three keys that merely look like one.

    A plain dict is never scanned for failures, so two dossiers whose `failing` reports differ
    would otherwise seal to the same hash and bind to the same bundle.
    """
    as_measurement = dossier(economics={"dsr": Measurement(0.97, 0.95, "at_least")})
    as_dict = dossier(
        economics={"dsr": {"value": 0.97, "threshold": 0.95, "direction": "at_least"}}
    )
    assert as_measurement.dossier_hash() != as_dict.dossier_hash()
