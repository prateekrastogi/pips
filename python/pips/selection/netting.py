"""Combined-blotter netting  (§10.2, M19).

The ensemble's internal crossing — one pipeline buying what another sells — reduces REALIZED
turnover below the sum of the parts. §10.2: the combined-blotter simulation measures this
netting ratio and re-prices the ensemble's cost line, which shifts each member's optimal
threshold, and S5 iterates that to a fixed point::

    netting ratio = 1 - ensemble external turnover / sum of member turnovers

**The netting window is the whole risk.** Two pipelines cross only if they trade the same symbol
at the same TIME. A buy at 09:20 and a sell at 14:50 do not cross: both orders reach the market
and both pay the cost line. Netting them on paper books a saving that was never available, which
lowers the ensemble's cost line, which admits trades that do not clear their real costs — and
every number downstream stays perfectly plausible. So ``bucket_ns`` is required with no default.
It is the single most consequential parameter here and nothing should be able to choose it
quietly.

Buckets are fixed and EPOCH-aligned — not session-aligned, so a one-minute bucket is not each
clock minute of the trading day, and boundaries fall wherever the epoch puts them. That is
deterministic, which is what rule 1 asks for, and it means two orders a second apart can fall
either side of a boundary and fail to net. That UNDERSTATES netting, which is the conservative
direction — the ensemble is charged for a crossing it might have got. It is stated rather than
corrected: the alternative, sliding windows that chase pairs, reports a saving whenever one can
be constructed.

Members pay their own prices; the netted residual is a single order at the bucket's
volume-weighted price. Pricing it at either constituent's price instead would make the ratio
depend on which pipeline happened to be listed first.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from pips.selection.turnover import CostLine

__all__ = [
    "BlotterOrder",
    "NetOrder",
    "NettingFixedPoint",
    "NettingFixedPointError",
    "NettingReport",
    "combine_blotters",
    "solve_netting_fixed_point",
]


@dataclass(frozen=True)
class BlotterOrder:
    """One pipeline's intent. ``quantity`` is signed: positive buys, negative sells."""

    pipeline: str
    symbol: str
    ts_ns: int
    quantity: int
    price: Decimal


@dataclass(frozen=True)
class NetOrder:
    """What actually reaches the market for one symbol in one bucket."""

    symbol: str
    bucket: int
    quantity: int
    price: Decimal
    """The bucket's volume-weighted price across the orders that netted into it."""


@dataclass(frozen=True)
class NettingReport:
    combined: tuple[NetOrder, ...]
    external_turnover: Decimal
    member_turnover: Decimal
    netting_ratio: float
    bucket_ns: int
    """Reported back, because the ratio means nothing without the window that produced it."""


def combine_blotters(orders: Sequence[BlotterOrder], *, bucket_ns: int) -> NettingReport:
    """Net the members' blotters into one and measure how much of the turnover crossed."""
    if bucket_ns <= 0:
        raise ValueError(
            f"bucket_ns must be positive, got {bucket_ns!r}. It is the window within which two "
            "pipelines are treated as crossing, and there is no safe default: too wide and the "
            "ratio books savings that were never available."
        )

    groups: dict[tuple[str, int], list[BlotterOrder]] = {}
    member_turnover = Decimal(0)
    for entry in orders:
        if not isinstance(entry.quantity, int) or isinstance(entry.quantity, bool):
            raise TypeError(
                f"quantity {entry.quantity!r} is not an integer. NSE cash equity trades whole "
                "shares; a fractional quantity is a units error upstream, and rounding it here "
                "would hide that at the point it turns into money."
            )
        member_turnover += abs(entry.quantity) * entry.price
        groups.setdefault((entry.symbol, entry.ts_ns // bucket_ns), []).append(entry)

    if member_turnover == 0:
        raise ValueError(
            "no turnover to net: the blotter is empty or every quantity is zero. Refusing "
            "rather than reporting a ratio of 0 — nothing traded is not the same as nothing "
            "crossed, and a zero would feed the cost re-pricing as though it were evidence."
        )

    combined: list[NetOrder] = []
    external_turnover = Decimal(0)
    # Sorted, so the combined blotter does not depend on the order the members were listed in
    # (rule 1).
    for (symbol, bucket), entries in sorted(groups.items()):
        net = sum(e.quantity for e in entries)
        if net == 0:
            # A perfect cross reaches the market as nothing at all, not as a zero-quantity
            # order that later code would have to remember to skip.
            continue
        shares = sum(abs(e.quantity) for e in entries)
        vwap = sum((abs(e.quantity) * e.price for e in entries), Decimal(0)) / Decimal(shares)
        combined.append(NetOrder(symbol=symbol, bucket=bucket, quantity=net, price=vwap))
        external_turnover += abs(net) * vwap

    return NettingReport(
        combined=tuple(combined),
        external_turnover=external_turnover,
        member_turnover=member_turnover,
        # |sum(x)| <= sum(|x|) bucket by bucket, so this is in [0, 1] by construction. A value
        # outside that range is not a surprising measurement, it is a bug.
        netting_ratio=float(1 - external_turnover / member_turnover),
        bucket_ns=bucket_ns,
    )


# ============================================================ the fixed point ==========
#
# §10.2: the combined-blotter simulation measures the netting ratio and RE-PRICES the ensemble's
# cost line, which in turn shifts each member's optimal threshold -- and S5 iterates that to a
# fixed point.
#
# The loop closes because the pieces feed each other. If external turnover is (1 - ratio) of the
# members' summed turnover, then the costs actually paid, attributed per unit of INTENDED
# turnover, are c * (1 - ratio). Each member prices at that lower line, so tau* falls, so more
# trades are admitted, so the blotter changes -- and the ratio must be measured again.
#
# THE FEEDBACK RUNS THE FLATTERING WAY. Every pass can only lower the cost line, and a lower
# line can only admit more trades. A generator whose crossing improves with volume drives c
# toward zero, and a zero cost line admits every opportunity regardless of edge. So the
# degenerate answers are refused rather than reported.
#
# Note the units: the cost line is a RATE (a fraction of notional) and is a float, while blotter
# turnover is money and is Decimal. They are kept apart deliberately -- paise accounting applies
# to cash amounts, not to rates, and mixing the two in one expression is its own class of bug.


class NettingFixedPointError(RuntimeError):
    """The re-pricing loop did not settle, or settled on a degenerate answer."""


@dataclass(frozen=True)
class NettingFixedPoint:
    effective_cost: CostLine
    netting_ratio: float
    report: NettingReport
    iterations: int
    history: tuple[float, ...]
    """Every ratio measured, so the path can be audited and not just its endpoint."""


def solve_netting_fixed_point(
    *,
    blotter_for: Callable[[CostLine], Sequence[BlotterOrder]],
    gross_cost: CostLine,
    bucket_ns: int,
    rel_tol: float = 1e-10,
    max_passes: int = 50,
) -> NettingFixedPoint:
    """Alternate (blotter | cost line) and (cost line | ratio) until the ratio settles.

    The first pass prices at the GROSS line -- assume nothing crossed until a blotter says it
    did. Starting from an optimistic ratio would admit trades on a saving that has not been
    measured yet, and the fixed point inherits that.
    """
    if rel_tol <= 0:
        raise ValueError(f"rel_tol must be positive, got {rel_tol!r}")
    if max_passes < 1:
        raise ValueError(f"max_passes must be at least 1, got {max_passes!r}")

    ratio = 0.0
    history: list[float] = []
    for _ in range(max_passes):
        effective = CostLine(gross_cost.total * (1.0 - ratio))
        report = combine_blotters(blotter_for(effective), bucket_ns=bucket_ns)
        if report.netting_ratio >= 1.0:
            raise NettingFixedPointError(
                "the combined blotter is entirely internal: every share crossed, so the "
                "ensemble sends nothing to the market. Its cost per unit of intended turnover "
                "is not zero but UNDEFINED -- there is no external trade to attribute a cost "
                "to. Reporting zero would set tau* to zero and admit every opportunity "
                "regardless of edge, which would look like the best result the search ever "
                "found."
            )
        history.append(report.netting_ratio)

        if abs(report.netting_ratio - ratio) <= rel_tol * max(abs(report.netting_ratio), 1.0):
            return NettingFixedPoint(
                effective_cost=CostLine(gross_cost.total * (1.0 - report.netting_ratio)),
                netting_ratio=report.netting_ratio,
                report=report,
                iterations=len(history),
                history=tuple(history),
            )

        # Convergence is tested first, so a match against an EARLIER ratio without matching the
        # previous one is a genuine cycle rather than a settling sequence.
        #
        # start=1, NOT start=2 as in `solve_joint`, and the difference is real rather than
        # sloppy: there the candidate value is compared BEFORE being appended, so the first
        # element scanned is two steps back. Here it is appended first, so the first element
        # scanned is one step back. Same construct, histories offset by one -- harmonising them
        # without checking would relabel every cycle.
        for back, seen in enumerate(reversed(history[:-1]), start=1):
            if abs(report.netting_ratio - seen) <= rel_tol * max(abs(seen), 1.0):
                raise NettingFixedPointError(
                    f"the re-pricing entered a cycle of period {back}: a cheaper line admits "
                    "trades that change the crossing, which restores the line, which drops "
                    "them again. Raising max_passes cannot help, which is why this does not "
                    "report as running out of passes."
                )
        ratio = report.netting_ratio

    raise NettingFixedPointError(
        f"the re-pricing did not settle within max_passes={max_passes}. Refusing to return the "
        "last pass: it is an ordinary-looking cost line that is not a fixed point, and every "
        "threshold derived from it would be wrong in the flattering direction."
    )
