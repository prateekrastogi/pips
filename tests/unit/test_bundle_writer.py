"""Building a signable bundle from real provenance  (§3.9, M20, `[C-WRIT-02]`).

`[C-WRIT-01]` may return a partial dossier, because there the gap is the finding. A bundle has
no partial form: `build_bundle` signs it, and a signed artifact with an invented `code_hash` is
worse than an unsigned one — the signature is what invites the plant to trust it. So this writer
either produces a bundle backed by real provenance or refuses, naming everything it lacks.

**The dossier hash is derived, never supplied.** A caller who can pass `validation_dossier_hash`
can bind a bundle to evidence that does not exist, which is the mirror of `[C-WRIT-01]`'s rule
that a caller cannot hand-write a gate.

**An incomplete dossier cannot be signed.** Otherwise the bundle certifies gaps.

**A hash that is not a hash is refused.** `[C-REG-01]` already makes this argument about snapshot
roots: a truncated hash, an uppercase one or a short id *records something that looks like
provenance and cannot be checked against a store*. The same is true of every hash in a bundle,
and the bundle is the artifact the plant actually executes.

**The required set is enumerated from the model**, so a field added to `StrategyBundle` later is
demanded of the provenance without anyone remembering to add it here.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from pips.bundle import IrNode, StrategyBundle, UnregisteredOpError, verify_bundle
from pips.certification.bundle_writer import (
    DERIVED_FIELDS,
    HASH_FIELDS,
    REQUIRED_PROVENANCE,
    IncompleteProvenanceError,
    write_bundle_for,
)
from pips.certification.dossier import (
    REQUIRED_FIELDS,
    Dossier,
    bind_dossier,
    build_dossier,
)

KEY = b"test-signing-key"
ALPHA = (IrNode(op="zscore", inputs=("close",), params={"window": 20}),)
PORTFOLIO = (IrNode(op="erc_weights", inputs=("alpha",), params={}),)


def complete_dossier() -> Dossier:
    return build_dossier(
        {
            name: {field: f"{name}.{field}" for field in fields}
            for name, fields in REQUIRED_FIELDS.items()
        }
    )


def provenance(**over: object) -> dict[str, object]:
    base: dict[str, object] = {}
    for index, name in enumerate(sorted(REQUIRED_PROVENANCE)):
        base[name] = f"{index:064x}" if name in HASH_FIELDS else f"value-for-{name}"
    base["golden_fixture_hashes"] = ("a" * 64,)
    base["parent_experiment_ids"] = ("exp-1",)
    base["valid_from"] = "2026-09-01"
    base["valid_until"] = "2026-12-01"
    base.update(over)
    return base


def write(**over: object) -> StrategyBundle:
    """Only the provenance varies. The one test that needs a different dossier calls
    `write_bundle_for` directly, rather than adding a parameter every other caller ignores."""
    return write_bundle_for(
        dossier=complete_dossier(),
        provenance=provenance(**over),
        alpha_ir=ALPHA,
        portfolio_ir=PORTFOLIO,
        key=KEY,
    )


# ------------------------------------------------------------------- the round trip -----


def test_the_bundle_verifies_and_binds_its_dossier() -> None:
    dossier = complete_dossier()
    bundle = write_bundle_for(
        dossier=dossier, provenance=provenance(), alpha_ir=ALPHA, portfolio_ir=PORTFOLIO, key=KEY
    )

    verify_bundle(bundle, key=KEY)
    bind_dossier(dossier, bundle)


def test_the_bundle_binds_the_dossier_it_was_given() -> None:
    """Not some other one that happened to be complete."""
    from pips.certification.dossier import DossierBindingError

    bundle = write()
    other = build_dossier(
        {
            name: {field: f"other.{name}.{field}" for field in fields}
            for name, fields in REQUIRED_FIELDS.items()
        }
    )
    with pytest.raises(DossierBindingError):
        bind_dossier(other, bundle)


# ---------------------------------------------------------- derived, never supplied -----


@pytest.mark.parametrize("derived", sorted(DERIVED_FIELDS))
def test_a_derived_field_is_not_the_callers_to_supply(derived: str) -> None:
    """A caller who can pass `validation_dossier_hash` binds a bundle to evidence that does
    not exist; one who can pass `schema_version` claims a schema the plant did not agree to."""
    with pytest.raises(IncompleteProvenanceError, match=re.escape(derived)):
        write(**{derived: "b" * 64})


def test_the_required_set_is_enumerated_from_the_model() -> None:
    """A field added to `StrategyBundle` later must be demanded without anyone remembering.

    A hand-written list does not grow with the model, and the field it would miss is exactly
    the one nobody thought about.
    """
    modelled = {f.name for f in dataclasses.fields(StrategyBundle)}
    assert set(REQUIRED_PROVENANCE) | DERIVED_FIELDS == modelled


# ---------------------------------------------------------------- refuse, don't guess -----


def test_an_incomplete_dossier_cannot_be_signed() -> None:
    sections = {
        name: {field: f"{name}.{field}" for field in fields}
        for name, fields in REQUIRED_FIELDS.items()
    }
    del sections["operations"]["kill_thresholds"]

    with pytest.raises(IncompleteProvenanceError, match=re.escape("operations.kill_thresholds")):
        write_bundle_for(
            dossier=build_dossier(sections),
            provenance=provenance(),
            alpha_ir=ALPHA,
            portfolio_ir=PORTFOLIO,
            key=KEY,
        )


def test_every_missing_field_is_named_at_once() -> None:
    """A caller who learns them one at a time rebuilds the bundle once per field."""
    partial = provenance()
    del partial["code_hash"]
    del partial["cost_hash"]

    with pytest.raises(IncompleteProvenanceError) as exc:
        write_bundle_for(
            dossier=complete_dossier(),
            provenance=partial,
            alpha_ir=ALPHA,
            portfolio_ir=PORTFOLIO,
            key=KEY,
        )
    assert "code_hash" in str(exc.value)
    assert "cost_hash" in str(exc.value)


@pytest.mark.parametrize("hollow", [None, "", "   ", "N/A", "TBD", "unknown", ()])
def test_a_hollow_provenance_value_is_refused(hollow: object) -> None:
    """Checked on a NON-hash field on purpose.

    On a hash field the shape check refuses `""` anyway, so pinning the hollow rule there
    proves nothing about the hollow rule — it only proves the hash rule twice. `broker_context`
    is where "present but says nothing" has to stand on its own.
    """
    with pytest.raises(IncompleteProvenanceError, match="broker_context"):
        write(broker_context=hollow)


@pytest.mark.parametrize("hollow", [None, "", "N/A"])
def test_a_hollow_hash_is_refused_too(hollow: object) -> None:
    with pytest.raises(IncompleteProvenanceError, match="risk_policy_hash"):
        write(risk_policy_hash=hollow)


@pytest.mark.parametrize(
    "not_a_hash",
    [
        "abc",
        "A" * 64,
        "z" * 64,
        "a" * 63,
        "a" * 65,
        "  " + "a" * 62,
        # A trailing newline is what a hash read from a file looks like, and `$` matches before
        # one — so this is the case that separates `fullmatch` from `match`.
        "a" * 64 + "\n",
    ],
)
def test_a_value_that_is_not_a_hash_is_refused(not_a_hash: str) -> None:
    """`[C-REG-01]`'s argument, applied to the artifact the plant executes: a truncated hash,
    an uppercase one or a short id records something that LOOKS like provenance."""
    with pytest.raises(IncompleteProvenanceError, match="code_hash"):
        write(code_hash=not_a_hash)


def test_a_non_hash_field_is_not_held_to_hash_shape() -> None:
    """Over-eager validation would refuse `FLATTRADE`, which is exactly right as a broker."""
    bundle = write(broker_context="FLATTRADE", capital_range="2L")
    assert bundle.broker_context == "FLATTRADE"


def test_an_undeclared_provenance_field_is_refused() -> None:
    """A typo'd name would sit unused while the field it was meant for reported missing."""
    with pytest.raises(IncompleteProvenanceError, match="code_has"):
        write(code_has="a" * 64)


# ------------------------------------------------------------------ validity window -----


def test_an_inverted_validity_window_is_refused() -> None:
    with pytest.raises(IncompleteProvenanceError, match="valid_until"):
        write(valid_from="2026-12-01", valid_until="2026-09-01")


def test_an_empty_validity_window_is_refused() -> None:
    """Equal dates make a bundle that is never valid while looking bounded."""
    with pytest.raises(IncompleteProvenanceError, match="valid_until"):
        write(valid_from="2026-09-01", valid_until="2026-09-01")


# ----------------------------------------------------------------------------- the IR -----


def test_an_unregistered_op_is_still_refused() -> None:
    """Delegated to `build_bundle`, and pinned here so a future refactor cannot lose it."""
    with pytest.raises(UnregisteredOpError):
        write_bundle_for(
            dossier=complete_dossier(),
            provenance=provenance(),
            alpha_ir=(IrNode(op="eval", inputs=("close",), params={}),),
            portfolio_ir=PORTFOLIO,
            key=KEY,
        )


def test_an_empty_alpha_ir_is_refused() -> None:
    with pytest.raises(ValueError, match="alpha_ir"):
        write_bundle_for(
            dossier=complete_dossier(),
            provenance=provenance(),
            alpha_ir=(),
            portfolio_ir=PORTFOLIO,
            key=KEY,
        )


def test_a_bad_golden_fixture_hash_is_refused() -> None:
    """The tuple is checked element-wise. A bundle whose boot fixtures cannot be located is one
    the plant cannot replay, which is the whole point of carrying them."""
    with pytest.raises(IncompleteProvenanceError, match="golden_fixture_hashes"):
        write(golden_fixture_hashes=("a" * 64, "not-a-hash"))


def test_a_derived_field_and_a_typo_are_refused_for_different_reasons() -> None:
    """Both are "you may not put that there", but the fixes differ: one means stop supplying a
    value the writer computes, the other means correct a name. A single message would send
    half the readers looking for the wrong mistake.
    """
    with pytest.raises(IncompleteProvenanceError, match="derived, not supplied"):
        write(validation_dossier_hash="b" * 64)

    with pytest.raises(IncompleteProvenanceError, match="not a bundle field"):
        write(code_has="b" * 64)
