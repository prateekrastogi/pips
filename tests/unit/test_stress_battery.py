"""Stress battery  (§6 M16).

§6 M16 lists the perturbations — costs x1.5/x2, delay +1/+2 bars, fill degradation, universe
N±buffer and leave-sector-out, drop-best-month, concentration leave-outs — and its Verify is
*"known-fragile toy fails, known-robust toy passes"*.

The design question that matters is not which perturbations to apply. It is **what happens to a
case that cannot be run.**

pips has no sector map. `leave-sector-out` is in the battery's own definition and cannot be
evaluated today, and the tempting behaviours are both wrong: skipping it silently reports a
battery that passed everything it tried, and passing it by default reports a robustness the
strategy has never demonstrated. Either way a certification says "cleared the stress battery"
when the battery was smaller than its name.

So a case that cannot run is `NOT_RUN`, `NOT_RUN` is not `PASSED`, and a battery containing any
`NOT_RUN` case cannot certify. That is the same shape as A06's tri-state event flag and QC's
fail-closed verdict, arriving at the last gate before capital.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.stress import (
    CaseOutcome,
    StressBattery,
    StressConfig,
    sharpe,
)

BASE = StressConfig()


def robust(config: StressConfig) -> list[Decimal]:
    """A toy with real edge: survives 2x costs and two bars of delay."""
    gross = [Decimal("0.010")] * 60
    penalty = (config.cost_multiplier - 1) * Decimal("0.001") + (
        Decimal(config.decision_delay_bars) * Decimal("0.0005")
    )
    return [g - penalty + (Decimal(i % 5) - 2) * Decimal("0.0004") for i, g in enumerate(gross)]


def fragile(config: StressConfig) -> list[Decimal]:
    """A toy whose edge is a rounding error away from nothing: 1.5x costs kill it."""
    gross = [Decimal("0.0012")] * 60
    penalty = (config.cost_multiplier - 1) * Decimal("0.004") + (
        Decimal(config.decision_delay_bars) * Decimal("0.003")
    )
    return [g - penalty + (Decimal(i % 5) - 2) * Decimal("0.0004") for i, g in enumerate(gross)]


def one_lucky_month(config: StressConfig) -> list[Decimal]:
    """Flat all year except one spectacular block, placed in the MIDDLE.

    The position is the test. With the lucky block at index 0, "drop the best block" and "drop
    the first block" remove the same data, so an implementation that just drops the first
    passes — and a mutation proved it did. At index 25 the two disagree, and only removing the
    best one destroys the edge.
    """
    out = [Decimal("0.0001")] * 60
    for i in range(25, 30):
        out[i] = Decimal("0.05")
    return out


def battery(**over: object) -> StressBattery:
    base: dict[str, object] = {"min_sharpe": Decimal("0.5"), "block_size": 5}
    base.update(over)
    return StressBattery(**base)  # type: ignore[arg-type]


# ------------------------------------------------------- the Verify --------------------


def test_a_known_robust_toy_passes() -> None:
    report = battery().run(robust)
    assert report.certifies, report.describe()
    assert all(v.outcome is CaseOutcome.PASSED for v in report.verdicts)


def test_a_known_fragile_toy_fails() -> None:
    report = battery().run(fragile)
    assert not report.certifies
    assert any(v.outcome is CaseOutcome.FAILED for v in report.verdicts)


def test_the_fragile_toy_fails_on_cost_specifically() -> None:
    # Not merely "something failed": the battery must name WHICH perturbation broke it, or a
    # failing result carries no information about what to fix.
    report = battery().run(fragile)
    failed = {v.case for v in report.verdicts if v.outcome is CaseOutcome.FAILED}
    assert any("cost" in name for name in failed), failed


def test_drop_best_month_destroys_a_one_lucky_month_toy() -> None:
    report = battery().run(one_lucky_month)
    dropped = next(v for v in report.verdicts if v.case == "drop-best-block")
    assert dropped.outcome is CaseOutcome.FAILED


def test_drop_best_block_removes_the_highest_sum_block_not_the_first() -> None:
    """The mechanism, tested directly rather than through a threshold.

    The end-to-end test above cannot distinguish "drop the best" from "drop the first": a
    fixture spiky enough for the best block to matter is spiky enough that its own volatility
    keeps the Sharpe under the bar either way, so both implementations FAIL the case and the
    test passes for the wrong one. A mutation proved it, twice — once with the lucky block at
    index 0, and again after moving it to the middle.

    Tuning the fixture until it straddles the threshold would make the test depend on a
    balance I had chosen. Asserting the operation instead is exact.
    """
    returns = (
        [Decimal("0.001")] * 5
        + [Decimal("0.002")] * 5
        + [Decimal("0.05")] * 5
        + [Decimal("0.003")] * 5
    )
    kept = battery().without_best_block(returns)

    assert Decimal("0.05") not in kept, "the best block must be the one removed"
    assert Decimal("0.001") in kept, "the FIRST block must survive; it is not the best"
    assert len(kept) == 15


# ------------------------------------------- a case that cannot run is not a pass -------


def test_a_case_that_cannot_be_evaluated_is_not_run_and_blocks_certification() -> None:
    """The load-bearing behaviour.

    `leave-sector-out` needs a sector map pips does not have. Skipping it silently would
    report a battery that passed everything it TRIED; passing it by default would report a
    robustness never demonstrated. Both let a certification claim a battery larger than the
    one that ran.
    """
    report = battery().run(robust, unavailable={"leave-sector-out"})
    sector = next(v for v in report.verdicts if v.case == "leave-sector-out")
    assert sector.outcome is CaseOutcome.NOT_RUN
    assert not report.certifies
    assert "leave-sector-out" in report.describe()


def test_not_run_is_distinguishable_from_failed_in_the_report() -> None:
    # An operator acts differently on the two: one means build the sector map, the other means
    # the strategy is fragile. A report that merges them tells neither story.
    report = battery().run(robust, unavailable={"leave-sector-out"})
    assert not any(v.outcome is CaseOutcome.FAILED for v in report.verdicts)
    assert sum(v.outcome is CaseOutcome.NOT_RUN for v in report.verdicts) == 1


def test_an_empty_battery_certifies_nothing() -> None:
    with pytest.raises(ValueError, match="no cases"):
        StressBattery(min_sharpe=Decimal("0.5"), block_size=5, cases=()).run(robust)


def test_marking_every_case_unavailable_does_not_certify() -> None:
    # The degenerate version of the same error: a battery that ran nothing at all must not be
    # the easiest one to pass.
    names = {c.name for c in battery().cases}
    report = battery().run(robust, unavailable=names)
    assert not report.certifies
    assert all(v.outcome is CaseOutcome.NOT_RUN for v in report.verdicts)


# ------------------------------------------------------- shape --------------------------


def test_every_declared_perturbation_in_the_spec_has_a_case() -> None:
    names = {c.name for c in battery().cases}
    for required in ("cost-x1.5", "cost-x2", "delay-1bar", "delay-2bar", "drop-best-block"):
        assert required in names, f"§6 M16 names {required} and the battery does not run it"


def test_sharpe_of_a_flat_series_is_zero_not_undefined() -> None:
    assert sharpe([Decimal("0.01")] * 20) == 0


def test_sharpe_refuses_a_series_too_short_to_have_a_deviation() -> None:
    with pytest.raises(ValueError, match="at least"):
        sharpe([Decimal("0.01")])
