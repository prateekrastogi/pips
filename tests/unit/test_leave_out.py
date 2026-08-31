"""Concentration leave-outs  (§6 M16).

§6 M16 names them: *concentration (leave stock/day/session out)*. They answer the question a
headline Sharpe cannot — **was this an edge, or was it one name?**

Three pre-registered falsifiers wait on exactly this and nothing else can evaluate them:

- A01: *"Require stable cross-sectional breadth; reject if the edge concentrates in few names"*
- A02: *"Reject if results are dominated by open gaps"*
- A12: *"Reject if it depends on a handful of expiry days"*

Two design choices carry the weight:

**Leave-one-out is WORST CASE over buckets, never the average.** Averaging is the one summary
that cannot see concentration: a strategy whose entire edge is one stock has an excellent
average leave-one-out, because 99 of 100 removals change nothing. The one that matters is the
one that destroys it.

**Attribution must reconcile.** Leaving a bucket out of an incomplete attribution removes less
than it appears to, and the test passes because the thing it meant to remove was never there.
So the contributions must sum to the aggregate return, exactly, in the same integer arithmetic
— and that is checked structurally rather than through a residual, which the F0/F1
reconciliation taught is a check that closes by construction.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.leave_out import (
    Contribution,
    LeaveOutDimension,
    leave_one_out,
)

MIN_SHARPE = Decimal("0.5")


def noise(period: int, name: int) -> Decimal:
    """Deterministic but IRREGULAR per-name noise.

    The first version used `(p + i) % 3 - 1`, which is too tidy: for several choices of
    removed name the remaining noise summed to a constant across every period, so the series
    had zero variance, `sharpe` returned 0 by its own guard, and four perfectly healthy
    removals were counted as failures. Coprime multipliers keep the sums from cancelling.

    This is the third time this session a neat modular fixture has produced degenerate
    statistics and the code has been right to balk at them.
    """
    return (Decimal((period * 7 + name * 13) % 11) - 5) * Decimal("0.0002")


def spread(n_periods: int = 40, n_names: int = 8) -> list[Contribution]:
    """An edge shared across many names: no single removal should matter much."""
    return [
        Contribution(
            period=p,
            instrument_id=f"NAME{i}",
            session="MID",
            day=p // 5,
            net_return=Decimal("0.001") + noise(p, i),
        )
        for p in range(n_periods)
        for i in range(n_names)
    ]


def one_name_carries_it(n_periods: int = 40, n_names: int = 8) -> list[Contribution]:
    """NAME0 is the entire edge; the rest are noise around zero."""
    return [
        Contribution(
            period=p,
            instrument_id=f"NAME{i}",
            session="MID",
            day=p // 5,
            net_return=Decimal("0.008") if i == 0 else noise(p, i),
        )
        for p in range(n_periods)
        for i in range(n_names)
    ]


# ------------------------------------------------------------ concentration ------------


def test_an_edge_carried_by_one_name_fails_leave_stock_out() -> None:
    verdict = leave_one_out(
        one_name_carries_it(), LeaveOutDimension.INSTRUMENT, min_sharpe=MIN_SHARPE
    )
    assert not verdict.survives
    assert verdict.worst_bucket == "NAME0", "the report must name which removal broke it"


def test_an_edge_spread_across_names_survives_leave_stock_out() -> None:
    # The control. Without it, "fails" could be what this function always returns.
    verdict = leave_one_out(spread(), LeaveOutDimension.INSTRUMENT, min_sharpe=MIN_SHARPE)
    assert verdict.survives


def test_the_verdict_is_the_worst_removal_not_the_average() -> None:
    """The one summary that cannot see concentration is the average.

    A strategy whose entire edge is one stock has an EXCELLENT average leave-one-out: 7 of 8
    removals change nothing at all. Only the worst case sees it, and an implementation that
    averages passes this fixture comfortably.
    """
    verdict = leave_one_out(
        one_name_carries_it(), LeaveOutDimension.INSTRUMENT, min_sharpe=MIN_SHARPE
    )
    # `worst_sharpe` is Optional because an untestable dimension has none; assert it is
    # present rather than reaching through the Optional, which is what mypy is objecting to
    # and is also the assertion this test actually wants to make.
    assert verdict.worst_sharpe is not None
    assert verdict.worst_sharpe < verdict.full_sharpe
    assert verdict.worst_sharpe < MIN_SHARPE
    # Most removals leave it healthy; the mean over buckets would clear the bar easily.
    healthy = [s for s in verdict.by_bucket.values() if s >= MIN_SHARPE]
    assert len(healthy) >= 6, "the average is fine — which is exactly why it is not the test"


def test_leaving_a_day_out_and_leaving_a_session_out_are_separate_dimensions() -> None:
    contributions = one_name_carries_it()
    by_day = leave_one_out(contributions, LeaveOutDimension.DAY, min_sharpe=MIN_SHARPE)
    by_session = leave_one_out(contributions, LeaveOutDimension.SESSION, min_sharpe=MIN_SHARPE)
    assert by_day.dimension is LeaveOutDimension.DAY
    assert by_session.dimension is LeaveOutDimension.SESSION
    assert set(by_day.by_bucket) != set(by_session.by_bucket)


# ------------------------------------------------------------ the refusals -------------


def test_a_dimension_with_a_single_bucket_cannot_be_tested() -> None:
    """Removing the only bucket removes everything, which measures nothing.

    Every contribution here is in session MID. "Leave one session out" leaves no strategy at
    all — and reporting that as a failure would blame the alpha for the shape of the data,
    while reporting it as a pass would certify a test that never ran.
    """
    verdict = leave_one_out(spread(), LeaveOutDimension.SESSION, min_sharpe=MIN_SHARPE)
    assert verdict.testable is False
    assert verdict.survives is False, "not testable is not a pass"


def test_an_attribution_that_does_not_reconcile_is_refused() -> None:
    """Leaving a bucket out of an incomplete attribution removes less than it appears to.

    The test then passes because the thing it meant to remove was never in the sum. Checked
    structurally — the F0/F1 reconciliation taught that a residual defined as a remainder
    closes by construction and cannot detect this.
    """
    contributions = spread()
    with pytest.raises(ValueError, match="does not reconcile"):
        leave_one_out(
            contributions,
            LeaveOutDimension.INSTRUMENT,
            min_sharpe=MIN_SHARPE,
            period_returns={p: Decimal("99") for p in range(40)},
        )


def test_a_matching_attribution_is_accepted() -> None:
    contributions = spread()
    totals: dict[int, Decimal] = {}
    for c in contributions:
        totals[c.period] = totals.get(c.period, Decimal(0)) + c.net_return
    verdict = leave_one_out(
        contributions,
        LeaveOutDimension.INSTRUMENT,
        min_sharpe=MIN_SHARPE,
        period_returns=totals,
    )
    assert verdict.testable


def test_no_contributions_at_all_is_refused() -> None:
    with pytest.raises(ValueError, match="no contributions"):
        leave_one_out([], LeaveOutDimension.INSTRUMENT, min_sharpe=MIN_SHARPE)
