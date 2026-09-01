"""The StrategyBundle: signed, content-hashed, registered-IR-only  (§3.9, `[C-BNDL-01]`).

The artifact the research factory hands to the Rust plant. Everything the plant needs to
reproduce a decision is in it, and nothing that could change a decision is outside it.

**Every field is covered by the content hash**, computed over the model's own fields rather than
a hand-written list — a field added later and forgotten in such a list is exactly the field the
coverage test exists to catch, and a list does not grow with the model. A bundle that is signed
but only partly hashed is worse than an unsigned one, because the signature invites trust in the
parts it does not cover.

**Verification RECOMPUTES.** A validator comparing the stored hash to the stored hash validates
nothing, passes every tamper test ever written against it, and looks exactly like one that
works. The realistic tamper is not a forger: it is someone opening the JSON and changing a
number, and an editor does not re-sign.

**Only registered IR operations cross the boundary.** §3.9: *arbitrary callables cannot be
signed.* That is "no generative AI in the trading loop" made structural — the plant cannot
execute an op nobody registered, whatever the bundle claims — and the refusal happens at BUILD,
so an unsignable bundle never exists to be shipped.

**On the signature primitive.** This is HMAC-SHA256 from the standard library, which is
SYMMETRIC: whoever can verify can also forge. For the handoff as it stands — one operator, one
VM, DRY_RUN, the threat being accident rather than an adversary — content hashing carries the
real weight and HMAC adds provenance against mistakes. It is NOT adequate for a plant running
unattended against real money, where the verifier must be unable to sign. Asymmetric signing
(Ed25519) is a stated prerequisite for that, and it is a dependency decision this milestone does
not need to make.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "REGISTERED_OPS",
    "BundleSignatureError",
    "IrNode",
    "StrategyBundle",
    "UnregisteredOpError",
    "build_bundle",
    "load_bundle",
    "verify_bundle",
    "write_bundle",
]

SCHEMA_VERSION = "1.0"

REGISTERED_OPS: frozenset[str] = frozenset(
    {
        # Alpha-side transforms. Every one is a pure function of declared inputs and params.
        "zscore",
        "rank",
        "clip",
        "ewma",
        "residualise",
        "winsorise",
        "lag",
        "diff",
        # Portfolio-side.
        "erc_weights",
        "vol_target",
        "no_trade_band",
        "net_blotter",
    }
)
"""Every op the plant can execute. Deliberately closed, and deliberately free of anything that
evaluates text: an entry like `eval` or `call_python` would satisfy every other check here while
granting exactly what §3.9 forbids."""

_UNSIGNED = frozenset({"signature", "content_hash"})
"""Excluded from the hash. `signature` because signing must not change what is signed;
`content_hash` because it IS the hash."""


class BundleSignatureError(Exception):
    """The bundle does not verify. Deliberately not a warning and not a boolean."""


class UnregisteredOpError(Exception):
    """An IR node names an op the plant cannot execute, so the bundle cannot be signed."""


@dataclass(frozen=True)
class IrNode:
    """One registered operation. Data, never a callable — a callable cannot be signed."""

    op: str
    inputs: tuple[str, ...]
    params: dict[str, Any] = field(default_factory=dict)

    def canonical(self) -> dict[str, Any]:
        return {"op": self.op, "inputs": list(self.inputs), "params": self.params}


@dataclass(frozen=True)
class StrategyBundle:
    schema_version: str
    strategy_id: str
    parent_experiment_ids: tuple[str, ...]
    code_hash: str
    build_environment_hash: str
    data_snapshot_root: str
    universe_hash: str
    calendar_hash: str
    instrument_master_hash: str
    corporate_action_hash: str
    cost_hash: str
    risk_policy_hash: str
    numeric_semantics_version: str
    bar_semantics_version: str
    alpha_ir_version: str
    portfolio_ir_version: str
    valid_from: str
    valid_until: str
    broker_context: str
    capital_range: str
    alpha_ir: tuple[IrNode, ...]
    portfolio_ir: tuple[IrNode, ...]
    validation_dossier_hash: str
    trial_registry_root: str
    golden_fixture_hashes: tuple[str, ...]
    content_hash: str
    signature: str

    def canonical_payload(self) -> dict[str, Any]:
        """Every field except the two that cannot be inside their own subject.

        Built from `dataclasses.fields`, so a field added to the model is hashed without anyone
        remembering to add it here.
        """
        payload: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            if f.name in _UNSIGNED:
                continue
            value = getattr(self, f.name)
            if isinstance(value, tuple) and value and isinstance(value[0], IrNode):
                payload[f.name] = [node.canonical() for node in value]
            elif isinstance(value, tuple):
                payload[f.name] = list(value)
            else:
                payload[f.name] = value
        return payload

    def compute_hash(self) -> str:
        blob = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _check_ops(nodes: tuple[IrNode, ...], where: str) -> None:
    for node in nodes:
        if node.op not in REGISTERED_OPS:
            raise UnregisteredOpError(
                f"{where} names op {node.op!r}, which is not registered. Arbitrary callables "
                "cannot be signed (§3.9): the plant executes only ops it knows, so a bundle "
                "carrying one it does not is refused here rather than at boot."
            )


def build_bundle(*, key: bytes, alpha_ir: tuple[IrNode, ...], **fields: Any) -> StrategyBundle:
    """Assemble, hash and sign. Refuses before signing what the plant could not execute."""
    if not alpha_ir:
        raise ValueError(
            "alpha_ir is empty: a bundle with no alpha forecasts nothing, and signing it would "
            "certify an artifact the plant can load and never act on."
        )
    portfolio_ir: tuple[IrNode, ...] = fields.get("portfolio_ir", ())
    _check_ops(alpha_ir, "alpha_ir")
    _check_ops(portfolio_ir, "portfolio_ir")

    draft = StrategyBundle(
        schema_version=SCHEMA_VERSION,
        alpha_ir=alpha_ir,
        content_hash="",
        signature="",
        **fields,
    )
    digest = draft.compute_hash()
    signed = dataclasses.replace(
        draft,
        content_hash=digest,
        signature=hmac.new(key, digest.encode("utf-8"), hashlib.sha256).hexdigest(),
    )
    return signed


def verify_bundle(bundle: StrategyBundle, *, key: bytes) -> None:
    """Raise unless the bundle is intact and signed by ``key``.

    The hash is RECOMPUTED from the fields, never read back from `content_hash` and compared to
    itself. The stored value is checked against the recomputed one first, because the realistic
    failure is an edited file whose stored hash is stale — an editor does not re-sign.
    """
    recomputed = bundle.compute_hash()
    if not hmac.compare_digest(recomputed, bundle.content_hash):
        raise BundleSignatureError(
            f"content hash mismatch: the bundle's fields hash to {recomputed[:12]} but it "
            f"carries {bundle.content_hash[:12]}. Something changed after signing."
        )
    expected = hmac.new(key, recomputed.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, bundle.signature):
        raise BundleSignatureError(
            "signature does not verify against this key. The content is intact, so either the "
            "bundle was signed by someone else or this is the wrong key."
        )


def write_bundle(bundle: StrategyBundle, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = bundle.canonical_payload()
    payload["content_hash"] = bundle.content_hash
    payload["signature"] = bundle.signature
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def load_bundle(path: Path) -> StrategyBundle:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return StrategyBundle(
        **{
            **raw,
            "parent_experiment_ids": tuple(raw["parent_experiment_ids"]),
            "golden_fixture_hashes": tuple(raw["golden_fixture_hashes"]),
            "alpha_ir": tuple(
                IrNode(op=n["op"], inputs=tuple(n["inputs"]), params=n["params"])
                for n in raw["alpha_ir"]
            ),
            "portfolio_ir": tuple(
                IrNode(op=n["op"], inputs=tuple(n["inputs"]), params=n["params"])
                for n in raw["portfolio_ir"]
            ),
        }
    )
