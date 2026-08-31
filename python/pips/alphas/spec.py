"""AlphaSpec -- the pre-registration object  [C-SPEC-01] (§3.2, constitution rule 5).

"No alpha enters as an indicator recipe" (§3.2). It enters as the tuple
``A = (H, I_t, T_h, phi_theta, C, E, N, F)``: hypothesis, information set, target, feature
DAG, parameter domain, fit protocol, null models, falsifiers.

The falsifiers are the part that does the work, and they are enforced at entry rather than
reviewed later. Rule 5: *every alpha ships with named null models and a written rejection
condition before it is searched.* A discipline that is optional at the point of entry is not a
discipline, so a spec without either is refused, and a "falsifier" that names no perturbation
and no threshold is refused too -- "reject if it stops working" cannot be evaluated after the
fact, which is the only time it would matter.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from pips.core.config import PipsConfig, load_yaml
from pips.core.ids import ShortId, content_hash, short_id

__all__ = ["AlphaSpec", "DataTier", "FalsifierBinding", "load_alpha_spec"]

# WHAT THIS CHECK IS, AND WHAT IT GAVE UP ON. A falsifier must state an ACTION (reject /
# require / must / fail) and be a clause rather than a fragment. That is all it verifies.
#
# It was twice stronger than this and twice wrong. First it demanded the literal phrase
# "reject if" and rejected the reference's own A12 falsifier ("Reject isolated day-of-week or
# slot spikes after family-wise correction"). Then it demanded a word from a "referent"
# vocabulary and rejected A07's ("Reject if small changes to range_end or buffer reverse the
# result"). Each failure would have been fixed by widening the list — and a list widened until
# it stops rejecting anything checks nothing. A check that refuses the source document is
# broken; a check that accepts everything is theatre. So it was narrowed to the part that is
# actually mechanical.
#
# The real enforcement is elsewhere and is named here so nobody mistakes this for it: human
# review at pre-registration, and M16's stress battery actually APPLYING each falsifier.
#
# THAT BINDING NOW EXISTS. `falsifier_checks` below names, per falsifier, the check that
# evaluates it — and the check must RESOLVE (see `pips.validation.falsifier_binding`), not
# merely appear in a list. It is deliberately incomplete: 12 of 32 falsifiers across the
# catalogue are bound today, and `coverage_report` counts and NAMES the rest. Inventing
# bindings so that number looked finished would be this same prose-as-enforcement failure,
# relocated.
_ACTION_WORDS = ("reject", "require", "must", "fail")
_MIN_FALSIFIER_WORDS = 4


class FalsifierBinding(PipsConfig):
    """One pre-registered falsifier and the check that evaluates it.

    The structural binding this module's comment above has been asking for since M12. The
    falsifier TEXT is repeated rather than referenced by index: a spec's falsifier list is
    pre-registration, and an index would silently re-point if the list were ever reordered.
    """

    falsifier: str
    check: str


class DataTier(StrEnum):
    """§5: T1 is the launch surface; T2/T3 claims are quarantined until their data exists."""

    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class AlphaSpec(PipsConfig):
    """A pre-registered alpha. Every field is part of the trial's identity."""

    id: str
    version: str
    hypothesis: str
    information_set: list[str] = Field(min_length=1)
    target: dict[str, Any]
    feature_dag: list[dict[str, Any]] = Field(min_length=1)
    parameter_domain: dict[str, Any]
    fit_protocol: str
    null_models: list[str] = Field(default_factory=list)
    falsifiers: list[str] = Field(default_factory=list)
    data_tier: DataTier
    cost_context: dict[str, Any]
    execution_policy: dict[str, Any]
    heuristic: bool = False
    references: list[str] = Field(default_factory=list)
    # Falsifiers that are PRE-REGISTERED but cannot yet be evaluated, because the data they
    # need does not exist. Declaring them here keeps the gap machine-visible instead of a
    # footnote: a spec whose strongest rejection condition is unrunnable is weaker evidence
    # than one whose conditions can all be applied, and a reader should not have to work
    # that out. Each entry must name a falsifier that was actually declared.
    falsifiers_deferred: list[str] = Field(default_factory=list)
    # Which check evaluates which falsifier. OPTIONAL, and expected to be incomplete: the
    # checks most falsifiers need do not exist yet, and inventing bindings to look complete
    # would be the prose-as-enforcement failure this field exists to end. What is NOT optional
    # is that a binding present here be real — see the validator below.
    falsifier_checks: list[FalsifierBinding] = Field(default_factory=list)

    @field_validator("data_tier", mode="before")
    @classmethod
    def _coerce_tier(cls, value: object) -> object:
        return DataTier(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _rule_five(self) -> AlphaSpec:
        if not self.null_models:
            raise ValueError(
                f"{self.id}: null_models must be named before the search (rule 5). An alpha "
                "with nothing to beat has not stated what beating it would mean."
            )
        if not self.falsifiers:
            raise ValueError(
                f"{self.id}: at least one written falsifier is required before the search "
                "(rule 5). A rejection condition declared afterwards is a rationalisation."
            )
        for falsifier in self.falsifiers:
            lowered = falsifier.lower()
            if not any(word in lowered for word in _ACTION_WORDS):
                raise ValueError(
                    f"{self.id}: falsifier {falsifier!r} states no action. A rejection "
                    "condition must say what happens — reject, require, must, fail — not "
                    "describe a feeling about the result."
                )
            if len(falsifier.split()) < _MIN_FALSIFIER_WORDS:
                raise ValueError(
                    f"{self.id}: falsifier {falsifier!r} is a fragment, not a condition. "
                    "Name the perturbation and the outcome."
                )
        for binding in self.falsifier_checks:
            if binding.falsifier not in self.falsifiers:
                raise ValueError(
                    f"{self.id}: falsifier_checks names {binding.falsifier!r}, which is not "
                    "one of the declared falsifiers — a check cannot evaluate a rejection "
                    "condition nobody pre-registered"
                )
            # Imported here rather than at module scope: validation depends on the check
            # registry, and the registry's modules import alpha machinery.
            from pips.validation.falsifier_binding import resolve_check

            try:
                resolve_check(binding.check)
            except LookupError as exc:
                # Re-raised as ValueError so pydantic reports it as a validation failure
                # rather than letting a LookupError escape the model boundary raw.
                raise ValueError(f"{self.id}: {exc}") from exc

        for deferred in self.falsifiers_deferred:
            if not any(deferred.split(" — needs ")[0].strip() in f for f in self.falsifiers):
                raise ValueError(
                    f"{self.id}: falsifiers_deferred names {deferred!r}, which is not one of "
                    "the declared falsifiers — a condition cannot be deferred if it was "
                    "never pre-registered"
                )
        return self

    @property
    def runnable_falsifiers(self) -> list[str]:
        """Falsifiers that can be evaluated with the data we actually have."""
        deferred_heads = [d.split(" — needs ")[0].strip() for d in self.falsifiers_deferred]
        return [f for f in self.falsifiers if not any(h in f for h in deferred_heads)]

    @model_validator(mode="after")
    def _tier_matches_the_information_set(self) -> AlphaSpec:
        """A T2/T3 claim needs T2/T3 inputs. Declaring the tier does not supply the data."""
        microstructure = ("quote", "depth", "tick", "book", "trade_sign")
        has_micro = any(
            any(term in field.lower() for term in microstructure) for field in self.information_set
        )
        if self.data_tier is not DataTier.T1 and not has_micro:
            raise ValueError(
                f"{self.id}: declares {self.data_tier} but its information set is "
                f"{self.information_set} — no quote/depth/tick field. §5 quarantines "
                "microstructure claims until the archive exists; declaring the tier does not "
                "create the data."
            )
        return self

    @property
    def strategy_id(self) -> str:
        """``id@version`` -- a material change bumps the version and is a new trial (§3.2)."""
        return f"{self.id}@{self.version}"

    @property
    def quarantined(self) -> bool:
        """Heuristic alphas are quarantined and subject to the ensemble cap (rule 5)."""
        return self.heuristic

    def content_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def short_id(self) -> ShortId:
        return short_id(self.content_hash())


def load_alpha_spec(path: Path) -> AlphaSpec:
    """Load and validate an AlphaSpec from YAML."""
    return AlphaSpec.model_validate(load_yaml(path))
