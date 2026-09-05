"""A+ (`BLK-0005`): a three-component pre-rank picks the 500 for capture, with two safeguards.

WHY. `build_shortlist` scores with `liquidity_scores`, whose `_unmeasurable` refuses a missing
spread. Spread comes from 1-second capture, which is budgeted for the 500 names the shortlist
selects -- so with no spread anywhere the shortlist admits nobody. `shortlist.py` forbids a second
score, because using M7's own score is what made the 500 a superset of every registered universe
BY CONSTRUCTION. Both were deliberate. The owner chose A+ on 2026-09-05: break the circle with a
pre-rank, and replace the by-construction guarantee with something CHECKED and something that
CORRECTS.

WHAT THIS IS NOT. Not a liquidity score. It has no spread term and carries a different type and
name so nothing downstream can mistake it for one. It picks names for CAPTURE -- which data will
exist -- never for trading. It invents no weights: the three it uses are §4.1's own, with the
spread term omitted, because a new weighting would be a free parameter fitted after seeing the
data, which is exactly what `top_n` refuses an unregistered N to prevent.

THE COST, plainly. The 500 are chosen by an ordering that omits the term with the second-largest
weight (spread, -0.75). A heavily traded but persistently wide name can enter the 500 and then fail
the real score -- cheap, it just wastes capture. A tight but modest-volume name can MISS the 500 and
never get the data that would have shown it -- expensive, because a name missing from the archive
is missing for as long as the archive runs. `superset_breaches` measures the first kind of error
each refresh; `exploration_picks` is the only thing that ever corrects the second.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

# One z-score implementation in this package, not two. `_z` is private to `liquidity` because
# nothing else needed it; this is the second caller, and copying it would give the pre-rank a
# subtly different notion of "cross-sectional" than the score it feeds into.
from pips.universe.liquidity import WEIGHTS, _z

__all__ = [
    "PRERANK_WEIGHTS",
    "DailyStats",
    "PreRank",
    "exploration_picks",
    "prerank_for_capture",
    "superset_breaches",
]

PRERANK_WEIGHTS: Mapping[str, float] = {k: v for k, v in WEIGHTS.items() if k != "relative_spread"}
"""§4.1's weights with the spread term removed -- derived from `WEIGHTS`, never restated, so the
two cannot drift apart."""


@dataclass(frozen=True)
class DailyStats:
    """One symbol's DAILY-derivable liquidity inputs. Deliberately has no spread field."""

    symbol: str
    median_rupee_volume: float
    amihud: float
    gap_rate: float


@dataclass(frozen=True)
class PreRank:
    """Names picked for CAPTURE by the three-component pre-rank. NOT a liquidity score.

    This decides which names get 1-second data acquired. It decides nothing about trading: the
    universe is chosen later, by `liquidity_scores`, over the four components -- including the
    spread this pre-rank could not see. Treating `selected` as a universe would trade on a score
    with its second-largest term missing.
    """

    selected: tuple[str, ...]
    ranked: tuple[str, ...]
    """Every admissible name in pre-rank order, best first. `exploration_picks` reads the tail."""
    excluded: Mapping[str, str]
    n_admissible: int
    as_of: date | None = None


def _unmeasurable(s: DailyStats) -> str:
    """Why a name cannot be pre-ranked, or ``""``.

    Mirrors `shortlist._unmeasurable` and, like it, names the field rather than returning a bool.
    """
    if not math.isfinite(s.median_rupee_volume) or s.median_rupee_volume <= 0:
        return f"median_rupee_volume is not a positive finite number ({s.median_rupee_volume})"
    for field in ("amihud", "gap_rate"):
        value = getattr(s, field)
        if not math.isfinite(value):
            # Not defaulted: a missing component read as average is the flattering direction.
            return f"{field} is not finite ({value})"
    return ""


def prerank_for_capture(
    population: Sequence[DailyStats], *, n: int, as_of: date | None = None
) -> PreRank:
    """The ``n`` names the three daily components rank highest, for capture. ``n`` is a maximum."""
    excluded: dict[str, str] = {}
    usable: list[DailyStats] = []
    for s in population:
        reason = _unmeasurable(s)
        if reason:
            excluded[s.symbol] = reason
        else:
            usable.append(s)
    if not usable:
        return PreRank((), (), excluded, 0, as_of)

    z = {
        "median_rupee_volume": _z({s.symbol: math.log(s.median_rupee_volume) for s in usable}),
        "amihud": _z({s.symbol: s.amihud for s in usable}),
        "gap_rate": _z({s.symbol: s.gap_rate for s in usable}),
    }
    score = {
        s.symbol: sum(PRERANK_WEIGHTS[c] * z[c][s.symbol] for c in PRERANK_WEIGHTS) for s in usable
    }
    # Ties break on the symbol -- the same rule `top_n` uses -- so the cut falls the same way
    # every run (rule 1).
    ranked = tuple(sorted(score, key=lambda sym: (-score[sym], sym)))
    return PreRank(ranked[: max(n, 0)], ranked, excluded, len(usable), as_of)


def superset_breaches(*, universe: Sequence[str], shortlist: Sequence[str]) -> tuple[str, ...]:
    """Universe names that were NOT in the shortlist that acquired their data. Empty is the pass.

    What `shortlist.py` used to guarantee by construction -- "a name cannot enter U300 without
    already being inside the 500" -- is now OBSERVED each refresh. A breach means a name is being
    traded on a spread nobody captured for it, and the reader gets the name, not a boolean.
    """
    return tuple(sorted(set(universe) - set(shortlist)))


def exploration_picks(
    ranked: Sequence[str], *, cut: int, budget: int, refresh: date
) -> tuple[str, ...]:
    """``budget`` names just OUTSIDE the cut, rotating deterministically by refresh date.

    The pre-rank's expensive error is the false negative: a tight, modest-volume name that never
    makes the 500 and so never gets the spread data that would have promoted it. Nothing about the
    three components can find that name -- only capturing it can. So each refresh spends a small
    budget on the tail, and the window ADVANCES by ``budget`` per week, which covers the whole tail
    in ``ceil(len(tail) / budget)`` refreshes rather than orbiting the same few names.

    Deterministic in ``refresh`` (rule 1): rotating is not the same as random. A budget that covers
    the whole tail returns the tail once.
    """
    tail = tuple(ranked[cut:])
    if budget <= 0 or not tail:
        return ()
    if budget >= len(tail):
        return tail
    offset = ((refresh.toordinal() // 7) * budget) % len(tail)
    return tuple(tail[(offset + i) % len(tail)] for i in range(budget))
