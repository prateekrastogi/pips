"""Parameter-family sensitivity  (§6 M16, A02's falsifier).

A02 pre-registered *"Reject if only one lookback works"* and nothing could evaluate it.

The claim behind it is that a real effect shows up across a predeclared family of parameter
values, not at one of them. A02's plugin already refuses a single-lookback configuration at
construction and averages the declared lookbacks rather than picking the best — but that is a
guard against SEARCHING, and it says nothing about whether the result survives when each value
is looked at on its own. Averaging is in fact what hides the failure: one spectacular lookback
and three dead ones produce a mean that looks fine.

**Contiguity is REPORTED, not required.** If 5 and 40 clear the bar while 10 and 20 do not,
that is a suspicious shape — a real effect is usually smooth in its own parameter, which is the
argument plateau-centroid makes for two-dimensional surfaces. But A02 registered *"only one
works"*, not *"the working set must be contiguous"*, and holding an alpha to a stricter bar
than it registered is changing the test after the fact. The gap is surfaced; it does not fail.

**Values must come from the declared family**, and every declared value must have a score. A
family evaluated in part is a smaller family reported as the whole one, and "three of four
work" is then not a fact about the family that was registered.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["FamilyVerdict", "family_sensitivity"]


@dataclass(frozen=True)
class FamilyVerdict:
    """Which values of a predeclared family cleared the bar."""

    testable: bool
    declared: tuple[int, ...]
    working: tuple[int, ...]
    contiguous: bool
    _survives: bool = False

    @property
    def survives(self) -> bool:
        """Testable, and more than one declared value works. Exactly what A02 registered."""
        return self._survives

    def describe(self) -> str:
        if not self.testable:
            return (
                f"family {self.declared}: NOT TESTABLE — a single declared value cannot show "
                "whether an effect spans its family"
            )
        head = (
            f"family {self.declared}: {len(self.working)} of {len(self.declared)} work "
            f"{self.working}"
        )
        if not self.working:
            return f"{head} — nothing works; the effect is absent, not concentrated"
        if len(self.working) == 1:
            return f"{head} — ONLY ONE works; a single-parameter artefact (A02's falsifier)"
        if not self.contiguous:
            return (
                f"{head} — the working set is not contiguous, which is a suspicious shape "
                "for an effect that should be smooth in its own parameter. REPORTED ONLY: "
                "A02 registered 'only one works' as the rejection, not contiguity."
            )
        return f"{head} — contiguous"


def family_sensitivity(
    declared: tuple[int, ...], scores: dict[int, Decimal], min_score: Decimal
) -> FamilyVerdict:
    """Score each declared value on its own; more than one must clear ``min_score``."""
    if not declared:
        raise ValueError(
            "family_sensitivity called with no declared values. A family of nothing survives "
            "every test it is given, which reads as a result."
        )
    stray = sorted(set(scores) - set(declared))
    if stray:
        raise ValueError(
            f"{stray} is not in the declared family {declared}. Scoring a value nobody "
            "pre-registered evaluates against something chosen afterwards."
        )
    missing = sorted(set(declared) - set(scores))
    if missing:
        raise ValueError(
            f"declared value(s) {missing} have no score. A family evaluated in part is a "
            "smaller family reported as the whole one."
        )

    ordered = tuple(sorted(declared))
    working = tuple(v for v in ordered if scores[v] >= min_score)
    positions = [ordered.index(v) for v in working]
    contiguous = bool(working) and positions == list(range(positions[0], positions[-1] + 1))

    if len(declared) < 2:
        # One value is not a family. Reporting sensitivity over it reads identically to a
        # genuine multi-value pass, which is the objection.
        return FamilyVerdict(False, ordered, working, contiguous, False)
    return FamilyVerdict(True, ordered, working, contiguous, len(working) > 1)
