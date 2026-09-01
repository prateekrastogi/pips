"""Building a signable bundle from real provenance  (§3.9, M20, `[C-WRIT-02]`).

`[C-WRIT-01]` may return a partial dossier, because there the gap *is* the finding. A bundle has
no partial form: `build_bundle` signs it, and a signed artifact carrying an invented `code_hash`
is worse than an unsigned one — the signature is precisely what invites the plant to trust it.
So this writer either produces a bundle backed by real provenance or refuses, naming everything
it lacks in one message rather than one per rebuild.

**The dossier hash is derived, never supplied.** A caller who can pass
`validation_dossier_hash` can bind a bundle to evidence that does not exist — the mirror of
`[C-WRIT-01]`'s rule that a caller cannot hand-write a gate.

**An incomplete dossier cannot be signed**, or the bundle certifies gaps.

**A hash that is not a hash is refused.** `[C-REG-01]` makes this argument about snapshot roots:
a truncated hash, an uppercase one or a short id *records something that looks like provenance
and cannot be checked against a store*. It holds for every hash in a bundle, and the bundle is
the artifact the plant actually executes.

**The required set is enumerated from the model**, so a field added to `StrategyBundle` later is
demanded of the provenance without anyone remembering to add it here — a hand-written list does
not grow with the model, and the field it would miss is the one nobody thought about.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any

from pips.bundle import StrategyBundle, build_bundle
from pips.certification.dossier import (
    IncompleteDossierError,
    is_hollow,
    require_complete,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pips.bundle import IrNode
    from pips.certification.dossier import Dossier

__all__ = [
    "DERIVED_FIELDS",
    "HASH_FIELDS",
    "REQUIRED_PROVENANCE",
    "IncompleteProvenanceError",
    "write_bundle_for",
]

DERIVED_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",  # the writer's, not the caller's: a claimed schema is not agreement
        "alpha_ir",  # passed explicitly, so the op check cannot be routed around
        "portfolio_ir",
        "validation_dossier_hash",  # computed from the dossier that is actually being signed
        "content_hash",  # produced by signing
        "signature",
    }
)

REQUIRED_PROVENANCE: tuple[str, ...] = tuple(
    sorted(f.name for f in dataclasses.fields(StrategyBundle) if f.name not in DERIVED_FIELDS)
)
"""Every remaining bundle field. Enumerated from the model, never listed by hand."""

HASH_FIELDS: frozenset[str] = frozenset(
    {
        "code_hash",
        "build_environment_hash",
        "data_snapshot_root",
        "universe_hash",
        "calendar_hash",
        "instrument_master_hash",
        "corporate_action_hash",
        "cost_hash",
        "risk_policy_hash",
        "trial_registry_root",
    }
)
"""Fields whose value must be a lowercase 64-hex digest. `golden_fixture_hashes` is a tuple of
them and is checked element-wise; `broker_context` and the versions are deliberately not here."""

_HASH = re.compile(r"^[0-9a-f]{64}$")


class IncompleteProvenanceError(ValueError):
    """The bundle cannot be signed from what was offered, and is not signed from a guess."""


def _hash_complaint(name: str, value: Any) -> str | None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        return (
            f"{name}={value!r} is not a lowercase 64-hex digest. A truncated hash, an uppercase "
            "one or a short id records something that LOOKS like provenance and cannot be "
            "checked against a store (`[C-REG-01]`)."
        )
    return None


def write_bundle_for(
    *,
    dossier: Dossier,
    provenance: Mapping[str, Any],
    alpha_ir: tuple[IrNode, ...],
    portfolio_ir: tuple[IrNode, ...],
    key: bytes,
) -> StrategyBundle:
    """Sign a bundle for ``dossier``, or refuse and say why."""
    problems: list[str] = []

    # The evidence first: a bundle signed over an incomplete dossier certifies the gaps in it.
    try:
        require_complete(dossier)
    except IncompleteDossierError as exc:
        # Narrow deliberately: a broad `except` would report a TypeError from a bug in the
        # checker as a missing provenance field, and send the caller hunting for one.
        problems.append(str(exc))

    for name in provenance:
        if name in DERIVED_FIELDS:
            problems.append(
                f"{name} is derived, not supplied. A caller who sets it can bind this bundle to "
                "something other than the dossier being signed."
            )
        elif name not in REQUIRED_PROVENANCE:
            problems.append(
                f"{name} is not a bundle field. A typo'd name sits unused while the field it "
                "was meant for goes on reporting missing."
            )

    for name in REQUIRED_PROVENANCE:
        if name not in provenance:
            problems.append(f"{name} was not supplied, and there is no default for provenance.")
            continue
        value = provenance[name]
        if is_hollow(value):
            problems.append(f"{name} is present but says nothing ({value!r}).")
        elif name in HASH_FIELDS:
            complaint = _hash_complaint(name, value)
            if complaint:
                problems.append(complaint)
        elif name == "golden_fixture_hashes":
            problems.extend(
                complaint
                for complaint in (_hash_complaint(name, item) for item in value)
                if complaint
            )

    start, end = provenance.get("valid_from"), provenance.get("valid_until")
    if isinstance(start, str) and isinstance(end, str) and end <= start:
        problems.append(
            f"valid_until {end!r} does not follow valid_from {start!r}. An empty or inverted "
            "window is a bundle that is never valid while looking bounded."
        )

    if problems:
        raise IncompleteProvenanceError(
            "The bundle cannot be signed from what was offered:\n  - " + "\n  - ".join(problems)
        )

    return build_bundle(
        key=key,
        alpha_ir=alpha_ir,
        portfolio_ir=portfolio_ir,
        validation_dossier_hash=dossier.dossier_hash(),
        **{name: provenance[name] for name in REQUIRED_PROVENANCE},
    )
