"""The StrategyBundle: signed, content-hashed, registered-IR-only  (§3.9, `[C-BNDL-01]`).

The bundle is the artifact the research factory hands to the Rust plant. Everything the plant
needs to reproduce a decision is in it, and nothing that could change a decision is outside it.

Three properties carry the weight.

**Every field is covered by the content hash.** A field left out is a field that can change
without the hash noticing — and a bundle that is signed but only partly hashed is worse than an
unsigned one, because the signature invites trust in the parts it does not cover.

**Verification RECOMPUTES.** A validator that compares the stored hash to the stored hash
validates nothing and passes every tamper test ever written against it.

**Only registered IR operations cross the boundary.** §3.9: *arbitrary callables cannot be
signed.* That is the structural form of "no generative AI in the trading loop" — the plant
cannot execute an op nobody registered, whatever the bundle says.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pips.bundle import (
    REGISTERED_OPS,
    BundleSignatureError,
    IrNode,
    StrategyBundle,
    UnregisteredOpError,
    build_bundle,
    verify_bundle,
)

KEY = b"test-signing-key"


def ir() -> tuple[IrNode, ...]:
    return (
        IrNode(op="zscore", inputs=("close",), params={"window": 20}),
        IrNode(op="clip", inputs=("zscore",), params={"lo": -3, "hi": 3}),
    )


def bundle(**over: object) -> StrategyBundle:
    fields: dict[str, object] = {
        "strategy_id": "A01-lb35",
        "parent_experiment_ids": ("exp-1",),
        "code_hash": "a" * 64,
        "build_environment_hash": "b" * 64,
        "data_snapshot_root": "c" * 64,
        "universe_hash": "d" * 64,
        "calendar_hash": "e" * 64,
        "instrument_master_hash": "f" * 64,
        "corporate_action_hash": "0" * 64,
        "cost_hash": "1" * 64,
        "risk_policy_hash": "2" * 64,
        "numeric_semantics_version": "1.0",
        "bar_semantics_version": "1.0",
        "alpha_ir_version": "1.0",
        "portfolio_ir_version": "1.0",
        "valid_from": "2026-09-01",
        "valid_until": "2026-12-01",
        "broker_context": "FLATTRADE",
        "capital_range": "2L",
        "alpha_ir": ir(),
        "portfolio_ir": (IrNode(op="erc_weights", inputs=("alpha",), params={}),),
        "validation_dossier_hash": "3" * 64,
        "trial_registry_root": "4" * 64,
        "golden_fixture_hashes": ("5" * 64,),
    }
    fields.update(over)
    return build_bundle(key=KEY, **fields)  # type: ignore[arg-type]


# ------------------------------------------------------------ the hash covers all -----


def test_every_signed_field_changes_the_content_hash() -> None:
    """A field outside the hash is a field that can change without anything noticing.

    Enumerated from the model rather than listed by hand: a field added later and forgotten here
    is exactly the field this is meant to catch, and a hand-written list would not grow with it.
    """
    original = bundle()
    unsigned = {"signature", "content_hash"}
    covered = [f.name for f in dataclasses.fields(original) if f.name not in unsigned]
    assert covered, "the model must have fields"

    for name in covered:
        current = getattr(original, name)
        moved = _perturb(current)
        altered = dataclasses.replace(original, **{name: moved})  # type: ignore[arg-type]
        assert altered.compute_hash() != original.content_hash, f"{name} is outside the hash"


def _perturb(value: object) -> object:
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, tuple):
        return (*value, value[0]) if value else ("x",)
    raise AssertionError(f"no perturbation for {type(value)}")


def test_the_signature_is_not_part_of_what_it_signs() -> None:
    # Otherwise signing changes the thing being signed and nothing can ever verify.
    b = bundle()
    assert b.content_hash == b.compute_hash()


# ------------------------------------------------------------ verification -----------


def test_a_valid_bundle_verifies() -> None:
    verify_bundle(bundle(), key=KEY)


def test_verification_recomputes_rather_than_trusting_the_stored_hash() -> None:
    """The validator that validates nothing.

    Comparing the stored hash to the stored hash passes every tamper test ever written against
    it, and looks exactly like a validator that works.
    """
    b = bundle()
    tampered = dataclasses.replace(b, strategy_id="A99-evil")
    assert tampered.content_hash == b.content_hash, "the stored hash is stale by construction"
    # "content hash mismatch", not merely "content": the SIGNATURE error says "The content is
    # intact", so matching the bare word passes when the content check is deleted entirely and
    # the signature check catches the tamper instead. The two errors name different causes — a
    # file that was edited versus a key that does not belong — and only one of them is this.
    with pytest.raises(BundleSignatureError, match="content hash mismatch"):
        verify_bundle(tampered, key=KEY)


def test_an_intact_bundle_with_the_wrong_key_reports_the_key_not_the_content() -> None:
    """The two failures must stay distinguishable.

    An edited file and a foreign signature are different problems with different fixes, and a
    verifier that reports one as the other sends the reader to re-derive a hash that is fine.
    """
    with pytest.raises(BundleSignatureError, match="signature does not verify"):
        verify_bundle(bundle(), key=b"not-the-key")


@pytest.mark.parametrize(
    "field,value",
    [
        ("strategy_id", "A99-evil"),
        ("cost_hash", "9" * 64),
        ("risk_policy_hash", "9" * 64),
        ("capital_range", "10L"),
        ("valid_until", "2027-12-01"),
    ],
)
def test_tampering_with_any_field_is_caught(field: str, value: str) -> None:
    with pytest.raises(BundleSignatureError):
        verify_bundle(dataclasses.replace(bundle(), **{field: value}), key=KEY)  # type: ignore[arg-type]


def test_a_wrong_key_does_not_verify() -> None:
    with pytest.raises(BundleSignatureError, match="signature"):
        verify_bundle(bundle(), key=b"not-the-key")


def test_a_forged_signature_does_not_verify() -> None:
    with pytest.raises(BundleSignatureError, match="signature"):
        verify_bundle(dataclasses.replace(bundle(), signature="0" * 64), key=KEY)


# ------------------------------------------------------------ registered IR only -----


def test_an_unregistered_alpha_op_cannot_be_signed() -> None:
    """§3.9: arbitrary callables cannot be signed.

    This is "no generative AI in the trading loop" made structural: the plant cannot execute an
    op nobody registered, whatever the bundle claims, and the refusal happens at BUILD so an
    unsignable bundle never exists to be shipped.
    """
    with pytest.raises(UnregisteredOpError, match="eval_python"):
        bundle(alpha_ir=(IrNode(op="eval_python", inputs=("close",), params={}),))


def test_an_unregistered_portfolio_op_cannot_be_signed() -> None:
    with pytest.raises(UnregisteredOpError):
        bundle(portfolio_ir=(IrNode(op="call_llm", inputs=("alpha",), params={}),))


def test_the_registry_is_not_empty_and_holds_no_escape_hatch() -> None:
    # A registry containing something like "exec" or "eval" would satisfy every other test here
    # while granting exactly what the constraint forbids.
    assert REGISTERED_OPS
    forbidden = {"eval", "exec", "python", "lambda", "call", "shell", "subprocess"}
    for op in REGISTERED_OPS:
        assert not any(bad in op.lower() for bad in forbidden), op


def test_an_empty_ir_is_refused() -> None:
    # A bundle with no alpha is a bundle that forecasts nothing, and signing it would certify
    # an artifact the plant can load and never act on.
    with pytest.raises(ValueError, match="alpha_ir"):
        bundle(alpha_ir=())


# ------------------------------------------------------------ round trip -------------


def test_a_bundle_survives_a_write_and_read(tmp_path: Path) -> None:
    from pips.bundle import load_bundle, write_bundle

    path = write_bundle(bundle(), tmp_path / "bundle.json")
    verify_bundle(load_bundle(path), key=KEY)


def test_a_bundle_edited_on_disk_does_not_verify(tmp_path: Path) -> None:
    """The realistic tamper: someone opens the JSON and changes a number.

    Content hashing is what catches it, and it is the case the signature alone would not — an
    editor does not re-sign.
    """
    from pips.bundle import load_bundle, write_bundle

    path = write_bundle(bundle(), tmp_path / "bundle.json")
    path.write_text(path.read_text().replace('"capital_range": "2L"', '"capital_range": "50L"'))
    with pytest.raises(BundleSignatureError):
        verify_bundle(load_bundle(path), key=KEY)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "strategy-bundle" in CHECK_REGISTRY
    resolve_check("strategy-bundle")
