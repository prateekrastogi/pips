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

__all__ = ["AlphaSpec", "DataTier", "load_alpha_spec"]

# A falsifier must name a perturbation and an outcome. These are the perturbation vocabulary
# §6's stress battery (M16) actually applies, so a falsifier written in these terms can be
# mechanically evaluated rather than argued about.
_CONDITION_WORDS = (
    "reject if",
    "require",
    "must",
    "fails if",
    "disappears",
    "below",
    "above",
    "monotone",
    "delay",
    "neutral",
    "perturb",
    "remove",
    "drop",
    "stable",
)


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
            if not any(word in lowered for word in _CONDITION_WORDS):
                raise ValueError(
                    f"{self.id}: falsifier {falsifier!r} states no evaluable condition. Name "
                    "the perturbation and the outcome (e.g. 'reject if rank-IC is not "
                    "monotone in horizon'), not a sentiment."
                )
        return self

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
