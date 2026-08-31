"""Stress battery  (§6 M16).

§6 M16 lists the perturbations — costs x1.5/x2, delay +1/+2 bars, fill degradation, universe
N±buffer and leave-sector-out, drop-best-month, concentration leave-outs — and its Verify is
*"known-fragile toy fails, known-robust toy passes"*.

The design question that matters is not which perturbations to apply. It is **what happens to a
case that cannot be run.**

pips has no sector map. ``leave-sector-out`` is in the battery's own definition and cannot be
evaluated today, and both tempting behaviours are wrong: skipping it silently reports a battery
that passed everything it *tried*, and passing it by default reports a robustness the strategy
has never demonstrated. Either way a certification says "cleared the stress battery" when the
battery was smaller than its name — and nobody reading the certificate can tell.

So: a case that cannot run is ``NOT_RUN``, ``NOT_RUN`` is not ``PASSED``, and a battery
containing any ``NOT_RUN`` case cannot certify. That is the same shape as A06's tri-state event
flag and QC's fail-closed verdict, arriving at the last gate before capital.

A failure also names WHICH perturbation broke the strategy. "Something failed" carries no
information about what to fix, and a stress report that cannot be acted on gets skimmed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

__all__ = [
    "CaseOutcome",
    "StressBattery",
    "StressCase",
    "StressConfig",
    "StressReport",
    "StressVerdict",
    "sharpe",
]


@dataclass(frozen=True)
class StressConfig:
    """The knobs a perturbation turns. Defaults are the unstressed baseline."""

    cost_multiplier: Decimal = Decimal(1)
    decision_delay_bars: int = 0
    fill_degradation: Decimal = Decimal(0)
    universe_delta: int = 0


Evaluate = Callable[[StressConfig], list[Decimal]]
"""``config -> per-period net returns``. Injected, so the battery is pure."""


class CaseOutcome(StrEnum):
    """Three outcomes, and the third is the reason this enum exists."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"
    """The perturbation could not be evaluated. NOT a pass, and not a failure of the strategy
    -- an operator builds the missing input rather than abandoning the alpha."""


def sharpe(returns: Sequence[Decimal]) -> Decimal:
    """Mean over standard deviation. Zero when there is no deviation, never a division.

    A perfectly flat series has no risk to divide by. Returning zero is the conservative
    reading — it certifies nothing — where returning infinity would let a constant series
    clear every threshold in the battery.
    """
    if len(returns) < 2:
        raise ValueError(
            f"sharpe needs at least 2 observations to have a deviation, got {len(returns)}"
        )
    mean = sum(returns, Decimal(0)) / Decimal(len(returns))
    variance = sum((r - mean) ** 2 for r in returns) / Decimal(len(returns))
    if variance <= 0:
        return Decimal(0)
    return mean / variance.sqrt()


@dataclass(frozen=True)
class StressCase:
    """One perturbation: how to configure it, and how to judge what comes back."""

    name: str
    description: str
    config: StressConfig = field(default_factory=StressConfig)
    drop_best_block: bool = False
    requires: str | None = None
    """An input this case cannot run without, named on the CASE rather than inferred.

    Two defects made this necessary, both of the same kind. The concentration cases first ran
    as no-op perturbations against a bare return series and PASSED — a case that cannot be
    evaluated certifying itself, which is precisely what NOT_RUN exists to prevent. And
    `leave-sector-out`, the battery's own flagship example of an unrunnable case, had the same
    hole from the day it was written: it only ever appeared as NOT_RUN because every test
    remembered to pass it in `unavailable`. A caller who forgot got a PASS.

    A dependency the caller has to remember is a dependency that will be forgotten."""


@dataclass(frozen=True)
class StressVerdict:
    case: str
    outcome: CaseOutcome
    baseline_sharpe: Decimal | None = None
    stressed_sharpe: Decimal | None = None
    note: str = ""


@dataclass(frozen=True)
class StressReport:
    verdicts: tuple[StressVerdict, ...]

    @property
    def all_run_cases_passed(self) -> bool:
        """Nothing that RAN failed. §6 M16's Verify is about this, not about certification.

        Kept separate from :attr:`certifies` deliberately. The battery cannot certify anything
        today — leave-sector-out needs a sector map, the concentration cases need attribution
        — so collapsing the two would make the Verify unsatisfiable and tempt someone to
        weaken `certifies` until it passed.
        """
        ran = [v for v in self.verdicts if v.outcome is not CaseOutcome.NOT_RUN]
        return bool(ran) and all(v.outcome is CaseOutcome.PASSED for v in ran)

    @property
    def certifies(self) -> bool:
        """Every case ran, and every case passed. Both halves are required."""
        return bool(self.verdicts) and all(v.outcome is CaseOutcome.PASSED for v in self.verdicts)

    def describe(self) -> str:
        lines = []
        for v in self.verdicts:
            sr = "" if v.stressed_sharpe is None else f"SR {v.stressed_sharpe:.3f}"
            lines.append(f"  {v.case:<20} {v.outcome:<8} {sr} {v.note}".rstrip())
        head = "stress: CERTIFIES" if self.certifies else "stress: DOES NOT CERTIFY"
        not_run = [v.case for v in self.verdicts if v.outcome is CaseOutcome.NOT_RUN]
        if not_run:
            head += f" — {len(not_run)} case(s) could not run: {', '.join(not_run)}"
        return "\n".join([head, *lines])


def default_cases() -> tuple[StressCase, ...]:
    """The perturbations §6 M16 names. Every one of them, including the ones pips cannot run.

    Declaring a case it cannot evaluate is deliberate: the battery's definition is fixed by the
    spec, not by what happens to be implementable, and a missing case must be VISIBLE as
    NOT_RUN rather than absent from the list entirely. A battery that quietly omits what it
    cannot do reports a clean sweep of a smaller battery.
    """
    return (
        StressCase("cost-x1.5", "costs at 1.5x", StressConfig(cost_multiplier=Decimal("1.5"))),
        StressCase("cost-x2", "costs at 2x", StressConfig(cost_multiplier=Decimal(2))),
        StressCase("delay-1bar", "decision delayed one bar", StressConfig(decision_delay_bars=1)),
        StressCase("delay-2bar", "decision delayed two bars", StressConfig(decision_delay_bars=2)),
        StressCase(
            "fill-degraded",
            "worse fills",
            StressConfig(fill_degradation=Decimal("0.25")),
        ),
        StressCase("universe-minus", "universe shrunk", StressConfig(universe_delta=-10)),
        StressCase("universe-plus", "universe widened", StressConfig(universe_delta=10)),
        StressCase("drop-best-block", "best block removed", drop_best_block=True),
        StressCase(
            "leave-stock-out",
            "worst single-instrument removal — NEEDS PER-BUCKET ATTRIBUTION, which a bare "
            "return series cannot supply",
            requires="attribution",
        ),
        StressCase(
            "leave-day-out",
            "worst single-day removal — NEEDS PER-BUCKET ATTRIBUTION",
            requires="attribution",
        ),
        StressCase(
            "leave-session-out",
            "worst single-session removal — NEEDS PER-BUCKET ATTRIBUTION",
            requires="attribution",
        ),
        StressCase(
            "leave-sector-out",
            "one sector removed — NEEDS A SECTOR MAP, which pips does not have until M6's "
            "masters carry one",
            requires="sector-map",
        ),
    )


@dataclass(frozen=True)
class StressBattery:
    """Runs every declared case and refuses to certify unless every one of them passed."""

    min_sharpe: Decimal
    block_size: int
    cases: tuple[StressCase, ...] = field(default_factory=default_cases)

    def run(
        self,
        evaluate: Evaluate,
        unavailable: set[str] | None = None,
        provides: set[str] | None = None,
    ) -> StressReport:
        """Evaluate every case.

        ``provides`` names inputs the caller HAS — "attribution", "sector-map". A case
        declaring a requirement the caller has not provided is NOT_RUN, without the caller
        having to know which cases those are. ``unavailable`` remains for cases a caller
        cannot run for reasons the case itself cannot predict.
        """
        if not self.cases:
            raise ValueError(
                "a battery with no cases certifies everything it is given. If the intent is "
                "to run nothing, say so somewhere a certificate cannot be issued."
            )
        cannot = set(unavailable or set())
        have = provides or set()
        # One code path for "could not be evaluated", and the case decides — not the caller.
        cannot |= {c.name for c in self.cases if c.requires and c.requires not in have}
        baseline = sharpe(evaluate(StressConfig()))

        verdicts: list[StressVerdict] = []
        for case in self.cases:
            if case.name in cannot:
                verdicts.append(
                    StressVerdict(
                        case=case.name,
                        outcome=CaseOutcome.NOT_RUN,
                        baseline_sharpe=baseline,
                        note=f"could not be evaluated: {case.description}",
                    )
                )
                continue

            returns = evaluate(case.config)
            if case.drop_best_block:
                returns = self.without_best_block(returns)
            stressed = sharpe(returns)
            verdicts.append(
                StressVerdict(
                    case=case.name,
                    outcome=(
                        CaseOutcome.PASSED if stressed >= self.min_sharpe else CaseOutcome.FAILED
                    ),
                    baseline_sharpe=baseline,
                    stressed_sharpe=stressed,
                )
            )
        return StressReport(verdicts=tuple(verdicts))

    def without_best_block(self, returns: list[Decimal]) -> list[Decimal]:
        """Remove the single best contiguous block. The BEST one, not an arbitrary one.

        Dropping a random block asks whether the strategy survives losing some data; dropping
        the best asks whether its edge was ever more than one lucky stretch. Only the second
        is a stress test.
        """
        blocks = [
            (sum(returns[i : i + self.block_size], Decimal(0)), i)
            for i in range(0, len(returns), self.block_size)
        ]
        if len(blocks) < 2:
            return returns
        _, start = max(blocks)
        return returns[:start] + returns[start + self.block_size :]
