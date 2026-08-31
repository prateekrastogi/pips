"""Concentration leave-outs  (§6 M16).

§6 M16 names them: *concentration (leave stock/day/session out)*. They answer the question a
headline Sharpe cannot — **was this an edge, or was it one name?**

Three pre-registered falsifiers wait on exactly this and nothing else can evaluate them: A01's
*"reject if the edge concentrates in few names"*, A02's *"reject if results are dominated by
open gaps"*, and A12's *"reject if it depends on a handful of expiry days"*.

Two design choices carry the weight:

**Leave-one-out is WORST CASE over buckets, never the average.** Averaging is the one summary
that cannot see concentration: a strategy whose entire edge is a single stock has an excellent
average leave-one-out, because every removal but one changes nothing. The removal that matters
is the one that destroys it, and a mean over buckets is precisely the statistic that drowns it.

**Attribution must reconcile.** Leaving a bucket out of an incomplete attribution removes less
than it appears to, and the test then passes because the thing it meant to remove was never in
the sum. That is checked structurally against supplied period returns rather than through a
residual — the F0/F1 reconciliation taught that a residual defined as a remainder closes by
construction and cannot detect the error it was written for.

**A dimension with one bucket is NOT TESTABLE, and not testable is not a pass.** Removing the
only session leaves no strategy at all. Reporting that as a failure blames the alpha for the
shape of the data; reporting it as a pass certifies a test that never ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pips.validation.stress import sharpe

__all__ = ["Contribution", "LeaveOutDimension", "LeaveOutVerdict", "leave_one_out"]


class LeaveOutDimension(StrEnum):
    """Which axis to remove one value of."""

    INSTRUMENT = "INSTRUMENT"
    DAY = "DAY"
    SESSION = "SESSION"


@dataclass(frozen=True)
class Contribution:
    """One bucket's contribution to one period's return."""

    period: int
    instrument_id: str
    session: str
    day: int
    net_return: Decimal

    def bucket(self, dimension: LeaveOutDimension) -> str:
        return {
            LeaveOutDimension.INSTRUMENT: self.instrument_id,
            LeaveOutDimension.DAY: str(self.day),
            LeaveOutDimension.SESSION: self.session,
        }[dimension]


@dataclass(frozen=True)
class LeaveOutVerdict:
    """What happened when each bucket was removed in turn."""

    dimension: LeaveOutDimension
    testable: bool
    full_sharpe: Decimal
    worst_bucket: str | None
    worst_sharpe: Decimal | None
    by_bucket: dict[str, Decimal]

    @property
    def survives(self) -> bool:
        """Requires BOTH that the test could run and that the worst removal cleared the bar."""
        return self._survives

    _survives: bool = False


def _periods(
    contributions: list[Contribution], exclude: str | None, dimension: LeaveOutDimension
) -> list[Decimal]:
    """Per-period totals, optionally with one bucket removed."""
    totals: dict[int, Decimal] = {}
    for c in contributions:
        if exclude is not None and c.bucket(dimension) == exclude:
            continue
        totals[c.period] = totals.get(c.period, Decimal(0)) + c.net_return
    return [totals[p] for p in sorted(totals)]


def leave_one_out(
    contributions: list[Contribution],
    dimension: LeaveOutDimension,
    min_sharpe: Decimal,
    period_returns: dict[int, Decimal] | None = None,
) -> LeaveOutVerdict:
    """Remove each bucket of ``dimension`` in turn; the verdict is the WORST outcome."""
    if not contributions:
        raise ValueError(
            "leave_one_out called with no contributions. An empty attribution survives every "
            "removal trivially, which reads as robustness and is the absence of a test."
        )

    if period_returns is not None:
        attributed: dict[int, Decimal] = {}
        for c in contributions:
            attributed[c.period] = attributed.get(c.period, Decimal(0)) + c.net_return
        mismatched = {p for p, total in attributed.items() if period_returns.get(p) != total}
        if mismatched or set(period_returns) != set(attributed):
            raise ValueError(
                "the attribution does not reconcile to the supplied period returns "
                f"({len(mismatched)} period(s) differ). Leaving a bucket out of an incomplete "
                "attribution removes less than it appears to, and the test then passes "
                "because what it meant to remove was never in the sum."
            )

    full = sharpe(_periods(contributions, None, dimension))
    buckets = sorted({c.bucket(dimension) for c in contributions})
    if len(buckets) < 2:
        # Removing the only bucket removes the strategy. Not a failure of the alpha, and not
        # a pass either -- the test did not run.
        return LeaveOutVerdict(
            dimension=dimension,
            testable=False,
            full_sharpe=full,
            worst_bucket=None,
            worst_sharpe=None,
            by_bucket={},
            _survives=False,
        )

    by_bucket = {b: sharpe(_periods(contributions, b, dimension)) for b in buckets}
    # WORST, not mean. The mean over buckets is the statistic that cannot see concentration.
    worst_bucket = min(by_bucket, key=lambda b: (by_bucket[b], b))
    worst = by_bucket[worst_bucket]
    return LeaveOutVerdict(
        dimension=dimension,
        testable=True,
        full_sharpe=full,
        worst_bucket=worst_bucket,
        worst_sharpe=worst,
        by_bucket=by_bucket,
        _survives=worst >= min_sharpe,
    )
