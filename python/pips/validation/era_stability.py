"""Era-stability split  (§6 M16, A12's falsifier).

A12 pre-registered *"Require stability across calendar eras"* and nothing could evaluate it.

The question is not "does this work on average" — a strategy that made everything in one regime
and nothing since has an excellent average, and no future. It asks **did this work in each era
it was given**, and the failure it names is a single dominant regime carrying a result that no
longer holds.

Three design choices, each the same shape as one already made elsewhere:

**Worst era, not the mean.** Averaging is the one summary that cannot see a regime-dependent
edge, because the good era's contribution survives being divided. Identical reasoning to the
concentration leave-outs.

**A single era cannot be tested**, and ``NOT_TESTABLE`` is not a pass — the stress battery's
third outcome, applied here. Splitting one era into "eras" and reporting stability is worse
than declining, because the report reads the same either way.

**Eras are GIVEN, not discovered.** Choosing a boundary after seeing the returns fits the split
to the answer, which is the ex-post selection A05 and A06 are pre-registered apart to prevent.
The caller supplies them.

An era with too few observations is reported as UNMEASURED rather than scored or dropped.
Scoring it makes the verdict swing on noise; dropping it silently shrinks the test. An
unmeasured era blocks stability exactly as a failing one does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pips.validation.stress import sharpe

__all__ = ["Era", "EraVerdict", "era_stability"]


@dataclass(frozen=True)
class Era:
    """A named, half-open calendar window ``[start, end)``."""

    name: str
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"era {self.name!r} starts {self.start} and ends {self.end}")

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end


@dataclass(frozen=True)
class EraVerdict:
    """Per-era results, and what the worst of them means."""

    testable: bool
    overall_sharpe: Decimal
    by_era: dict[str, Decimal]
    unmeasured_eras: tuple[str, ...]
    worst_era: str | None
    worst_sharpe: Decimal | None
    unassigned: int
    """Returns belonging to no era. Reported because a return the test never examined makes
    the coverage smaller than it appears -- the same failure as the ratio check's invisible
    skips."""

    _stable: bool = False

    @property
    def stable(self) -> bool:
        """Testable, every era measured, and the worst one clearing the bar."""
        return self._stable


def era_stability(
    returns: list[tuple[date, Decimal]],
    eras: tuple[Era, ...],
    min_sharpe: Decimal,
    min_observations: int = 10,
) -> EraVerdict:
    """Score each era separately; the verdict is the worst of them."""
    if not eras:
        raise ValueError(
            "era_stability called with no eras. A stability test over zero eras is vacuously "
            "stable, which reads as a result."
        )
    for i, first in enumerate(eras):
        for second in eras[i + 1 :]:
            if first.start < second.end and second.start < first.end:
                raise ValueError(
                    f"eras {first.name!r} and {second.name!r} overlap. An overlapping split "
                    "double-counts the shared window and makes 'every era' ambiguous."
                )

    overall = sharpe([r for _, r in returns]) if len(returns) > 1 else Decimal(0)
    buckets: dict[str, list[Decimal]] = {era.name: [] for era in eras}
    unassigned = 0
    for day, value in returns:
        for era in eras:
            if era.contains(day):
                buckets[era.name].append(value)
                break
        else:
            unassigned += 1

    by_era: dict[str, Decimal] = {}
    unmeasured: list[str] = []
    for era in eras:
        values = buckets[era.name]
        if len(values) < min_observations:
            unmeasured.append(era.name)
            continue
        by_era[era.name] = sharpe(values)

    if len(eras) < 2:
        # One era is not a split. Reporting stability over it would read identically to a
        # genuine multi-era pass, which is the whole objection.
        return EraVerdict(
            testable=False,
            overall_sharpe=overall,
            by_era=by_era,
            unmeasured_eras=tuple(unmeasured),
            worst_era=None,
            worst_sharpe=None,
            unassigned=unassigned,
            _stable=False,
        )

    worst_era = min(by_era, key=lambda name: (by_era[name], name)) if by_era else None
    worst = by_era[worst_era] if worst_era is not None else None
    return EraVerdict(
        testable=True,
        overall_sharpe=overall,
        by_era=by_era,
        unmeasured_eras=tuple(unmeasured),
        worst_era=worst_era,
        worst_sharpe=worst,
        unassigned=unassigned,
        # Every era measured AND the worst clearing the bar. An unmeasured era blocks
        # stability exactly as a failing one does: neither has been shown to work.
        _stable=bool(by_era) and not unmeasured and worst is not None and worst >= min_sharpe,
    )
