"""Binding falsifiers to the checks that evaluate them  [C-SPEC-01] (§3.2, rule 5, §6 M16).

:mod:`pips.alphas.spec` has carried this note since M12, after its text validator was twice
wrong about the reference's own falsifiers:

    The real enforcement is elsewhere and is named here so nobody mistakes this for it: human
    review at pre-registration, and M16's stress battery actually APPLYING each falsifier. When
    that battery exists, the honest strengthening is to require each falsifier to name the
    check that evaluates it — a structural binding, not a parse of English.

The battery exists now. Three rules, and the third is what makes this worth having:

**A named check must EXIST.** Not be plausible — resolve. Each id maps to a module that must
import, and every id claiming to be a stress case must be one the battery actually declares. A
falsifier naming a check that does not exist is worse than one naming nothing, because it
claims coverage.

**A named falsifier must be one that was pre-registered.** Binding a check to text that is not
in the spec's own ``falsifiers`` list annotates a rejection condition nobody registered.

**An unbound falsifier is REPORTED, not tolerated in silence.** Most falsifiers in the
catalogue cannot be bound today; the checks they need do not exist. Inventing bindings so the
report looks complete would be the exact failure this replaces — prose that reads as
enforcement. The report counts them, names them, and the count is expected to be large.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pips.alphas.spec import AlphaSpec

__all__ = [
    "CHECK_REGISTRY",
    "CoverageReport",
    "coverage_report",
    "resolve_check",
    "unbound_falsifiers",
]

# Check id -> the module that implements it. The mapping is what makes a binding structural:
# an id here is only usable because something importable stands behind it. Adding an id for a
# check that does not exist fails the registry's own test, which is the point.
CHECK_REGISTRY: dict[str, str] = {
    # Stress battery cases (§6 M16). Verified against `default_cases()` by the suite, so an
    # id here that the battery stops declaring is a failure rather than a dangling name.
    "cost-x1.5": "pips.validation.stress",
    "cost-x2": "pips.validation.stress",
    "delay-1bar": "pips.validation.stress",
    "delay-2bar": "pips.validation.stress",
    "fill-degraded": "pips.validation.stress",
    "drop-best-block": "pips.validation.stress",
    "leave-stock-out": "pips.validation.leave_out",
    "leave-day-out": "pips.validation.leave_out",
    "leave-session-out": "pips.validation.leave_out",
    # Selection and validation machinery.
    "plateau-centroid": "pips.validation.plateau",
    "shuffled-future": "pips.validation.nulls",
    "bh-fdr": "pips.validation.fdr",
    "purged-walk-forward": "pips.validation.walk_forward",
    "era-stability": "pips.validation.era_stability",
    "beats-declared-null": "pips.validation.incremental_value",
    "family-sensitivity": "pips.validation.family_sensitivity",
    "field-invariance": "pips.validation.field_invariance",
    "ex-post-selection": "pips.validation.ex_post_selection",
    "deflated-sharpe": "pips.validation.deflated_sharpe",
    "pbo-cscv": "pips.validation.pbo",
    "stationary-bootstrap": "pips.validation.bootstrap",
    "spa-test": "pips.validation.spa",
    "newey-west-hac": "pips.validation.stats",
    "monotone-in-horizon": "pips.validation.stats",
    # Execution-model properties that are enforced structurally rather than measured. A
    # falsifier about same-bar fills is answered by a simulator that cannot produce one.
    "f1-no-same-bar-fill": "pips.sim.protected_limit",
    "f0-f1-reconciliation": "pips.sim.reconcile",
}


def resolve_check(check_id: str) -> str:
    """Return the module behind ``check_id``, or raise. Importing is the proof."""
    target = CHECK_REGISTRY.get(check_id)
    if target is None:
        raise LookupError(
            f"unknown check {check_id!r}. A falsifier may only name a check that exists; "
            f"known checks are {sorted(CHECK_REGISTRY)}."
        )
    importlib.import_module(target)
    return target


@dataclass(frozen=True)
class CoverageReport:
    """How many pre-registered falsifiers actually have something evaluating them."""

    total_falsifiers: int
    bound: int
    unbound: int
    by_spec: tuple[tuple[str, tuple[str, ...]], ...]
    """``(spec_id, unbound falsifier texts)`` -- named, not just counted. A count says there
    is work; the names say what work. A report that only counts gets read as a score."""

    def describe(self) -> str:
        lines = [
            f"falsifier coverage: {self.bound} bound, {self.unbound} unbound "
            f"of {self.total_falsifiers} pre-registered",
        ]
        for spec_id, texts in self.by_spec:
            if texts:
                lines.append(f"  {spec_id}: {len(texts)} unbound")
                lines.extend(f"      - {t}" for t in texts)
        return "\n".join(lines)


def unbound_falsifiers(spec: AlphaSpec) -> tuple[str, ...]:
    """Pre-registered falsifiers with no check named against them, in declaration order."""
    bound = {binding.falsifier for binding in spec.falsifier_checks}
    return tuple(f for f in spec.falsifiers if f not in bound)


def coverage_report(specs: list[AlphaSpec]) -> CoverageReport:
    """Honest coverage across a catalogue. A large unbound count is the correct answer today."""
    by_spec = tuple((s.id, unbound_falsifiers(s)) for s in specs)
    total = sum(len(s.falsifiers) for s in specs)
    unbound = sum(len(texts) for _, texts in by_spec)
    return CoverageReport(
        total_falsifiers=total, bound=total - unbound, unbound=unbound, by_spec=by_spec
    )
