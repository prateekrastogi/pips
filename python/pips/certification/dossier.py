"""The certification dossier: the evidence a bundle is certified ON  (§12.2, `[C-BNDL-01]`).

The bundle says what will run. The dossier says why anyone believed it should — and it is the
half a reader can actually argue with six months later, when the strategy is losing money and
the question is whether it was ever measured or merely built.

The blueprint fixes eight sections (§12.2) and fixes their content as *all gate values,
DSR/PBO/SPA numbers, N at certification, holdout result*. **Values, not verdicts.** A dossier
recording `dsr_passed: true` has thrown away the only thing that can be re-checked; a dossier
recording `0.97 against a 0.95 floor` can be re-derived, disputed, and falsified. So
`Measurement` has no field to store a conclusion in — `passed()` is computed, and a dossier
cannot claim a pass on a failing number because nothing in it says "pass".

**Absence must not read as a value.** A completeness check written as `name in section` returns
true for `None`, for `""`, and for `"N/A"` — and a dossier full of `"TBD"` then certifies a
strategy nobody measured. It is the same shape as a rate-limited HTTP 200 or a NOT_RUN gate read
as PASSED: the dangerous absence is the one wearing the costume of data. There is deliberately no
way to write "genuinely unavailable" here. A strategy whose kill thresholds are unknown is not
certifiable-with-a-caveat; it is incomplete.

**But zero is a value.** `0.0` and `False` are results, and `if not value` erases precisely the
ones that matter — a zero cost share, a `False` on an outage test.

**Completeness is not passing.** `complete` asks whether everything was recorded, never whether
it was good. Conflating the two makes a failing strategy look unmeasured, an unmeasured one look
failed, and the rejection dossier — the artifact rule 4 counts, and the one that makes "top-5 is
a maximum, fewer is a valid output" writable — impossible to produce.

**The bundle's signature does not protect the dossier.** `StrategyBundle.validation_dossier_hash`
covers the dossier's *hash*, not its bytes, so an edited dossier leaves the bundle verifying
perfectly. Only `bind_dossier` notices. Certifying a strategy therefore means running both:
`verify_bundle` alone will accept any dossier at all. The direction is forced and cannot be made
symmetric — the bundle names the dossier because the dossier is finished first, and a dossier
naming the bundle back would need a hash that does not exist until the dossier is sealed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pips.bundle import StrategyBundle

__all__ = [
    "REQUIRED_FIELDS",
    "SECTIONS",
    "CompletenessReport",
    "Dossier",
    "DossierBindingError",
    "IncompleteDossierError",
    "Measurement",
    "bind_dossier",
    "build_dossier",
    "check_completeness",
    "is_hollow",
    "require_complete",
]

SECTIONS: tuple[str, ...] = (
    "identity",
    "trade_context",
    "economics",
    "stability",
    "stress",
    "capacity",
    "operations",
    "decision",
)
"""The eight sections of §12.2, in the blueprint's order. Declared separately from
`REQUIRED_FIELDS` so that the two must agree rather than one being derived from the other."""

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "identity": (
        "strategy_id",
        "family_graph",
        "parent_experiment_ids",
        "code_version",
        "data_version",
        "cost_version",
    ),
    "trade_context": (
        "universe_policy",
        "session_regime",
        "horizon",
        "broker",
        "capital_range",
        "side_product",
    ),
    "economics": (
        "net_return",
        "dsr",
        "max_drawdown",
        "cvar",
        "gross_to_net",
        "cost_share",
        "breakeven_edge",
        "rotation",
        "orders_per_day",
    ),
    "stability": (
        "outer_folds",
        "bootstrap_ci",
        "parameter_plateau",
        "universe_sensitivity",
        "concentration",
        # §12.2's Stability row predates the P4 gate list, which adds these two by name. A
        # dossier that omits them cannot be checked against the gate it was certified under.
        "pbo",
        "spa_p",
        # The blueprint's "holdout result". In this project the holdout is the sealed lockbox,
        # so it is named for the artifact that actually produced it.
        "lockbox_result",
        # A DSR without the N it was computed at cannot be re-derived, and understating N raises
        # it (§3.6). Both ends of the bracket, because the honest report is a range.
        "trials_viewed",
        "m_erank",
    ),
    "stress": (
        "cost_1_5x",
        "cost_2x",
        "delay_1_bar",
        "delay_2_bar",
        "fill_degradation",
        "outage_restart",
    ),
    "capacity": (
        "minimum_economic_ticket",
        "positions",
        "participation",
        "capital_time_use",
    ),
    "operations": (
        "entry_cutoff",
        "flatten_deadline",
        "broker_limits",
        "failure_modes",
        "kill_thresholds",
    ),
    "decision": (
        "rationale",
        "correlation_cluster",
        # §12.2 names only the rationale, which is prose. `outcome` is added because "fewer is a
        # valid output" needs rejections to be countable, and counting prose is guesswork.
        "outcome",
    ),
}

_PLACEHOLDERS = frozenset(
    {"n/a", "na", "tbd", "todo", "unknown", "none", "null", "nil", "-", "--", "?", "pending"}
)
"""Strings that mean "nobody filled this in". Refusing them is deliberate: a field whose honest
content is "unknown" makes the dossier incomplete, and incomplete is the correct verdict."""

_DIRECTIONS = frozenset({"at_least", "at_most"})


class DossierBindingError(Exception):
    """The dossier is not the one the bundle was signed over."""


class IncompleteDossierError(Exception):
    """A required field was never written, or was written as a placeholder."""


@dataclass(frozen=True)
class Measurement:
    """One gate value and the bar it was held to. No field records the outcome.

    A stored verdict can disagree with the number printed beside it, and a reader trusts the
    verdict — so there is nowhere to put one.
    """

    value: float
    threshold: float
    direction: str

    def __post_init__(self) -> None:
        if self.direction not in _DIRECTIONS:
            raise ValueError(
                f"direction {self.direction!r} is not one of {sorted(_DIRECTIONS)}. Refused "
                "rather than defaulted: a silent default would read every ≤ gate as a ≥ gate, "
                "turning the worst PBO in the run into a pass."
            )

    def passed(self) -> bool:
        if self.direction == "at_least":
            return self.value >= self.threshold
        return self.value <= self.threshold

    def canonical(self) -> dict[str, Any]:
        # Tagged so a plain dict carrying the same three keys cannot hash to the same dossier.
        return {
            "__measurement__": {
                "value": self.value,
                "threshold": self.threshold,
                "direction": self.direction,
            }
        }


@dataclass(frozen=True)
class CompletenessReport:
    complete: bool
    missing: tuple[str, ...]
    """Required and never written. The pipeline did not produce it."""
    hollow: tuple[str, ...]
    """Written as a placeholder. Something ran and had nothing to say — a different fix."""
    failing: tuple[str, ...]
    """Measurements that did not clear their threshold. Recorded, not a defect in the dossier."""


@dataclass(frozen=True)
class Dossier:
    sections: dict[str, dict[str, Any]]

    def dossier_hash(self) -> str:
        blob = json.dumps(
            {
                section: {name: _canonical(value) for name, value in body.items()}
                for section, body in self.sections.items()
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Measurement):
        return value.canonical()
    if isinstance(value, tuple | set | frozenset):
        return sorted(value) if isinstance(value, set | frozenset) else list(value)
    return value


def is_hollow(value: Any) -> bool:
    """True when something is present but says nothing.

    Numbers are never hollow: `0`, `0.0` and `False` are results, and treating them as absences
    erases exactly the measurements worth arguing about.
    """
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return not stripped or stripped.casefold() in _PLACEHOLDERS
    if isinstance(value, list | tuple | dict | set | frozenset):
        return len(value) == 0
    return False


def build_dossier(sections: Mapping[str, Mapping[str, Any]]) -> Dossier:
    """Copy and validate the shape. Undeclared names are refused, not ignored.

    A typo'd section leaves the real one reporting eight missing fields while the typo sits
    beside it looking filled; refusing it turns a puzzle into a sentence. And an undeclared field
    is unreviewed evidence inside a hashed artifact — adding one means declaring it.
    """
    for section, body in sections.items():
        if section not in REQUIRED_FIELDS:
            raise ValueError(
                f"{section!r} is not a dossier section. §12.2 fixes exactly {list(SECTIONS)}."
            )
        undeclared = sorted(set(body) - set(REQUIRED_FIELDS[section]))
        if undeclared:
            raise ValueError(
                f"{section} carries undeclared field(s) {undeclared}. A field nobody declared is "
                "evidence nobody reviewed; declare it in REQUIRED_FIELDS or drop it."
            )
    return Dossier(sections={name: dict(body) for name, body in sections.items()})


def check_completeness(dossier: Dossier) -> CompletenessReport:
    """Ask whether everything was recorded. Never whether it was good."""
    missing: list[str] = []
    hollow: list[str] = []
    failing: list[str] = []

    for section, required in REQUIRED_FIELDS.items():
        body = dossier.sections.get(section, {})
        for name in required:
            path = f"{section}.{name}"
            if name not in body:
                missing.append(path)
            elif is_hollow(body[name]):
                hollow.append(path)

    for section, body in dossier.sections.items():
        for name, value in body.items():
            if isinstance(value, Measurement) and not value.passed():
                failing.append(f"{section}.{name}")

    return CompletenessReport(
        complete=not missing and not hollow,
        missing=tuple(sorted(missing)),
        hollow=tuple(sorted(hollow)),
        failing=tuple(sorted(failing)),
    )


def require_complete(dossier: Dossier) -> None:
    """Raise unless every required field was recorded, naming every gap in one message.

    One raise per run rather than one per gap: a caller who learns about the gaps one at a time
    runs the whole certification eight times to find eight of them.
    """
    report = check_completeness(dossier)
    if report.complete:
        return
    parts = []
    if report.missing:
        parts.append(f"never written: {list(report.missing)}")
    if report.hollow:
        parts.append(f"written as a placeholder: {list(report.hollow)}")
    raise IncompleteDossierError(
        "The dossier cannot certify anything — " + "; ".join(parts) + ". Completeness is not "
        "the same question as passing: a recorded failure is fine here, an unrecorded result "
        "is not."
    )


def bind_dossier(dossier: Dossier, bundle: StrategyBundle) -> None:
    """Raise unless this dossier is the one the bundle was signed over.

    Necessary because the bundle's own signature cannot detect a swapped dossier: the bundle
    hashes the dossier's HASH, so editing the dossier changes nothing inside the bundle and
    `verify_bundle` keeps saying yes.
    """
    actual = dossier.dossier_hash()
    if actual != bundle.validation_dossier_hash:
        raise DossierBindingError(
            f"The dossier hashes to {actual} but the bundle was signed over "
            f"{bundle.validation_dossier_hash} — it does not match. The bundle's signature "
            "cannot see this: it covers the hash, not the evidence behind it."
        )
