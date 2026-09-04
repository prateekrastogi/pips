"""M7's liquidity score and the universe it ranks  (§6 M7, `[C-UNIV-01]`).

`U300` is not a list somebody supplies. It is **computed**: M7 specifies

    z(log median ₹vol) - 0.75·z(spread) - 0.50·z(Amihud) - 0.25·z(gap-rate)

with weights that are *fixed, stress-tested, never P&L-tuned*, and N ∈ {50, 100, 150, 300}.

That phrase is the design. **A weight the caller can pass is a weight somebody will tune** until
the universe contains the names their strategy already liked — and a universe tuned on P&L is a
selection effect wearing the costume of an eligibility rule, applied before every measurement
downstream. So the weights are constants and the scorer takes none.

**The z-scores are cross-sectional**, across symbols on one day: a name is liquid relative to
the others it competes with for the same capital. A time-series z would ask "is this name liquid
for itself lately", which every illiquid name passes.

**Volume enters as a log.** Rupee volume spans orders of magnitude, and without it one mega-cap
dominates the z and flattens every other name's contribution into noise.

**A symbol missing any component cannot be scored**, and is excluded rather than defaulted:
a missing spread read as zero makes an illiquid name look tight, which is the flattering
direction.

The signs are stated because a single flip ranks the worst names first and nothing downstream
would notice: volume helps; spread, Amihud and gap-rate hurt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Any

__all__ = [
    "SUPPORTED_N",
    "WEIGHTS",
    "SymbolStats",
    "amihud_ratio",
    "gap_rate",
    "liquidity_scores",
    "stable_core",
    "top_n",
]

WEIGHTS: dict[str, float] = {
    "median_rupee_volume": 1.0,
    "relative_spread": -0.75,
    "amihud": -0.50,
    "gap_rate": -0.25,
}
"""M7's coefficients, verbatim and closed. Not a default, not a parameter: *fixed,
stress-tested, never P&L-tuned* is the property that makes the universe an eligibility rule
rather than a second selection stage."""


def amihud_ratio(returns: Sequence[float], rupee_volume: Sequence[float]) -> float:
    """Amihud (2002) illiquidity for ONE symbol over a causal trailing window.

        Amihud_i = (1/D) * sum_d |r_i,d| / Vol_i,d

    PORTED under rule 13 from `../past` convexity `c13fccaf3dfa`,
    `src/convexity/cost/friction/spread_impact.py::amihud_ratio` (`SAL-0015`). The donor's
    surrounding friction model is SKIPped (`SAL-0013`) because its impact anchor was calibrated
    on a crypto book; this measure is venue-neutral and is the part that was kept.

    Per-symbol rather than the donor's ``(D, n_sym)`` matrix, because `SymbolStats` is
    per-symbol and a matrix here would exist only to be sliced apart again.

    The caller slices the trailing window ending at day ``t`` INCLUSIVE, so the estimate stays
    F_t-measurable (rule 2). This function does no windowing of its own: a window length chosen
    in here would be a second, hidden parameter.

    A day whose volume is not strictly positive and finite is DROPPED from the mean -- never
    divided into, and never counted as a zero contribution. The two are easy to confuse and
    they differ: counting an untraded day as zero shrinks the average and makes an illiquid
    name look tighter, which is the flattering direction.

    A name with no usable day is NaN rather than 0.0, because a zero Amihud is the most liquid
    reading there is. `_usable` already refuses non-finite components, so the NaN leaves the
    name out of the ranking instead of putting it at the top of it.
    """
    if len(returns) != len(rupee_volume):
        raise ValueError(
            f"returns ({len(returns)}) and rupee_volume ({len(rupee_volume)}) must be aligned; "
            "zipping to the shorter one would silently drop the tail of the window"
        )
    per_day = [
        abs(r) / v
        for r, v in zip(returns, rupee_volume, strict=True)
        if math.isfinite(r) and math.isfinite(v) and v > 0.0
    ]
    if not per_day:
        return math.nan
    return sum(per_day) / len(per_day)


def gap_rate(
    bars: Sequence[tuple[date, int, int]],
    *,
    threshold: float,
    explain: Callable[[str, date, int, int], Any] | None = None,
    symbol: str = "",
) -> float:
    """How OFTEN a name gaps overnight: the fourth term of §4.1's score.

        move_d   = |open_d / close_{d-1} - 1|
        gap_rate = #{d : move_d > threshold} / #{d : usable}

    ``bars`` is ``(trade_date, open_paise, close_paise)`` in session order, and the caller slices
    the lookback -- a window length chosen in here would be a second, hidden parameter.

    DEFINED 2026-09-05 by owner decision. §4.1 names `gap_rate` and its -0.25 weight and defines
    no component, so until then this existed as a field name and nothing else. It is a FREQUENCY
    rather than a mean magnitude: one crash day would dominate an average, and "rate" means how
    often rather than how far. ``threshold`` is effective-dated configuration, never a constant
    here -- it is a judgement and should look like one.

    CORPORATE ACTIONS ARE EXCLUDED FROM BOTH SIDES. A 1:2 split is a 50% "gap" that says nothing
    about liquidity: counted, the name looks like the gappiest on the exchange; counted as a
    non-gap, unusually smooth. Neither is true, so the pair leaves the sample. ``explain`` is the
    same `jump_explainer` QC uses, so this reuses that judgement rather than growing a second
    notion of an unexplained jump.

    The threshold comparison is exact rather than floating point: `10300 / 10000 - 1` is
    0.030000000000000027, so an exactly-3% move would test as above a 3% threshold and the
    boundary would quietly sit somewhere other than where it was configured.

    A name with no usable pair is NaN, not 0.0 -- zero is the smoothest reading there is, and
    `_usable` already refuses non-finite components, so the name leaves the ranking rather than
    topping it. The same rule `amihud_ratio` follows for a day with no usable volume.
    """
    gapped = usable = 0
    for (_, _, prev_close), (day, open_paise, _) in pairwise(bars):
        if prev_close <= 0 or open_paise < 0:
            continue
        if explain is not None:
            verdict = explain(symbol, day, prev_close, open_paise)
            if getattr(verdict, "explained", False):
                continue
        usable += 1
        # EXACT, not float. `10300 / 10000 - 1` is 0.030000000000000027, so a move of exactly
        # 3% tests as ABOVE a 3% threshold and the boundary silently moves. Prices are integer
        # paise for this reason; the comparison is cross-multiplied into the same arithmetic:
        #     |open/prev - 1| > t   <=>   |open - prev| > t * prev
        if Decimal(abs(open_paise - prev_close)) > Decimal(str(threshold)) * prev_close:
            gapped += 1
    if usable == 0:
        return math.nan
    return gapped / usable


SUPPORTED_N: frozenset[int] = frozenset({50, 100, 150, 300})
"""The universe sizes M7 registers. An arbitrary N is a universe nobody pre-registered, and
choosing it after seeing scores is the multiplicity problem moved one layer down."""


@dataclass(frozen=True)
class SymbolStats:
    """One symbol's liquidity inputs for one day. All four are required."""

    symbol: str
    median_rupee_volume: float
    relative_spread: float
    amihud: float
    gap_rate: float


def _usable(stat: SymbolStats) -> bool:
    """Every component present, finite, and loggable where a log is taken."""
    values = (stat.relative_spread, stat.amihud, stat.gap_rate)
    if not all(math.isfinite(v) for v in values):
        return False
    # A name that traded nothing has no log-volume, and clamping it to a floor invents one.
    return math.isfinite(stat.median_rupee_volume) and stat.median_rupee_volume > 0


def _z(values: Mapping[str, float]) -> dict[str, float]:
    """Cross-sectional z-scores. Zero everywhere when the cross-section is degenerate.

    `min == max` rather than `std == 0.0`: the standard deviation of identical values is exactly
    zero only at some lengths, and dividing by 1e-19 of float noise gives a z around 1e15 —
    one name would take the whole universe. The same trap `gate_s4` had.
    """
    # Kept although `liquidity_scores` never reaches it with fewer than two, and although the
    # `min == max` guard below already answers the one-value case identically. What it uniquely
    # protects is the EMPTY mapping, where `min(())` raises -- so this is the guard for a second
    # caller, the same reason `_TERMINAL` is kept in the backfill. Unreachable today, and a
    # mutation of it is correspondingly equivalent.
    if len(values) < 2:
        return dict.fromkeys(values, 0.0)
    ordered = list(values.values())
    if min(ordered) == max(ordered):
        return dict.fromkeys(values, 0.0)
    mean = sum(ordered) / len(ordered)
    spread = math.sqrt(sum((v - mean) ** 2 for v in ordered) / len(ordered))
    return {name: (value - mean) / spread for name, value in values.items()}


def liquidity_scores(population: Sequence[SymbolStats]) -> dict[str, float]:
    """M7's score for every scorable symbol in one day's cross-section.

    A single symbol scores nothing: there is no cross-section to be liquid *relative to*, and
    returning a score anyway would let a one-name population pass an eligibility rule that
    exists to compare.
    """
    usable = [s for s in population if _usable(s)]
    if len(usable) < 2:
        return {}

    components = {
        "median_rupee_volume": _z({s.symbol: math.log(s.median_rupee_volume) for s in usable}),
        "relative_spread": _z({s.symbol: s.relative_spread for s in usable}),
        "amihud": _z({s.symbol: s.amihud for s in usable}),
        "gap_rate": _z({s.symbol: s.gap_rate for s in usable}),
    }
    return {
        s.symbol: sum(weight * components[name][s.symbol] for name, weight in WEIGHTS.items())
        for s in usable
    }


def top_n(scores: Mapping[str, float], n: int) -> tuple[str, ...]:
    """The ``n`` highest-scoring symbols, ties broken on the symbol.

    ``n`` is a MAXIMUM: fewer qualify when fewer were scored, and padding would name a universe
    member that was never measured — the same rule as the top-5 report.
    """
    if n not in SUPPORTED_N:
        raise ValueError(
            f"n={n} is not one of M7's registered universe sizes {sorted(SUPPORTED_N)}. An "
            "arbitrary N is a universe nobody pre-registered, and picking one after seeing the "
            "scores is the multiplicity problem moved down a layer."
        )
    ranked = sorted(scores, key=lambda symbol: (-scores[symbol], symbol))
    return tuple(ranked[:n])


def stable_core(
    *, previous: Sequence[str], scores: Mapping[str, float], n: int, k: int
) -> tuple[str, ...]:
    """The blueprint's stable-core buffer: *enter above N-k; exit below N+k*.

    **The asymmetry is the whole mechanism.** A newcomer must beat the tighter bar to get in; an
    incumbent survives until it falls past the looser one. Symmetric bars would just be a wider
    universe and would stabilise nothing — a name oscillating around rank N would enter and
    leave every refresh, and each round trip costs the panel a warm-up and the strategy a
    turnover it never asked for.

    **An unscored incumbent cannot be kept.** A name with no score today was not measured today
    — suspended, delisted, or simply absent from the cross-section — and carrying it forward
    would put a universe member in the panel with no bars behind it.

    ``k`` is a POLICY parameter, not a tuned one, and unlike :data:`WEIGHTS` it is meant to be
    searched: the blueprint lists the stable-core buffer among the policy dimensions whose
    guardrail is *"stress-tested for liquidity, not tuned to maximize strategy P&L"*. Its
    starter values are the one column of that table the blueprint leaves empty, so there is no
    registered set to validate against here — only that it cannot be negative, which would
    invert the bars and require a name to get WORSE to stay.

    Membership drifts inside the buffer by construction and is bounded by ``n + k``: hysteresis
    that let a U50 grow to 200 would not be the policy anybody registered.
    """
    if n not in SUPPORTED_N:
        raise ValueError(
            f"n={n} is not one of M7's registered universe sizes {sorted(SUPPORTED_N)}."
        )
    if k < 0:
        raise ValueError(
            f"k={k} is negative, which inverts the bars: a name would have to get WORSE to stay "
            "in the universe."
        )

    ranking = sorted(scores, key=lambda symbol: (-scores[symbol], symbol))
    rank = {symbol: position + 1 for position, symbol in enumerate(ranking)}
    incumbents = set(previous)

    kept = [
        symbol
        for symbol in ranking
        # Enter above n-k; incumbents survive until they fall past n+k.
        if rank[symbol] <= (n + k if symbol in incumbents else max(0, n - k))
    ]
    # No trailing slice. An incumbent is kept only at rank <= n+k and a newcomer only at
    # rank <= n-k, so the membership is already a subset of ranks <= n+k and a cap on top of
    # that is a bound nothing can reach. The fifth guard this project has removed for being
    # indistinguishable; the bound is a consequence of the rule, and a test asserts it.
    return tuple(kept)
