"""A+ (`BLK-0005`, owner decision 2026-09-05): a three-component pre-rank picks the 500, and the
risk that creates is made MEASURABLE and CORRECTABLE rather than merely accepted.

WHY THIS EXISTS. `build_shortlist` scores with `liquidity_scores`, whose `_unmeasurable` refuses
a missing spread. Spread comes from 1-second capture, which is budgeted for the 500 names the
shortlist selects. With no spread anywhere, the shortlist admits nobody. `shortlist.py` forbids a
second score because using M7's own score is what made the 500 a superset of every universe BY
CONSTRUCTION. Both were deliberate; the owner chose A+: break the circle with a pre-rank, and
replace the by-construction guarantee with two safeguards.

THREE PIECES, and the second and third are the difference between A and A+:

1. `prerank_for_capture` — three components (median rupee volume, Amihud, gap-rate), the same
   three weights §4.1 gives them, spread omitted. It is NOT a liquidity score: it is a distinct
   type with a distinct name so nothing downstream can mistake it for one, and it picks names for
   CAPTURE, never for trading.
2. `superset_breaches` — every refresh, every name in the universe must have been inside the
   shortlist that acquired its data. What used to be guaranteed is now CHECKED, and a breach is
   reported by name rather than assumed away.
3. `exploration_picks` — a small budget of names just OUTSIDE the cut, rotating deterministically
   by refresh date, so a tight-but-modest-volume name the three-component rank misses eventually
   gets the spread data that would have shown it. "A name missing from the archive is missing for
   as long as the archive runs" — rotation is the only thing that ever answers that.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from pips.universe.prerank import (
    DailyStats,
    PreRank,
    exploration_picks,
    prerank_for_capture,
    superset_breaches,
)


def stats(symbol: str, vol: float = 1e7, amihud: float = 1e-4, gap: float = 0.05) -> DailyStats:
    return DailyStats(symbol=symbol, median_rupee_volume=vol, amihud=amihud, gap_rate=gap)


# ------------------------------------------------------------------- 1. the pre-rank -----


def test_it_is_a_distinct_type_that_cannot_be_mistaken_for_a_liquidity_score() -> None:
    """The load-bearing property. `shortlist.py`'s objection was to a second score being
    confused with the first; the answer is a type that has no spread and says so."""
    result = prerank_for_capture([stats("A"), stats("B")], n=1)
    assert isinstance(result, PreRank)
    assert not hasattr(DailyStats, "relative_spread"), "spread has no place in the pre-rank input"
    doc = PreRank.__doc__
    assert doc is not None, "the docstring IS the guard against misuse; it must exist"
    assert "capture" in doc.lower() and "not" in doc.lower()


def test_higher_volume_ranks_higher_all_else_equal() -> None:
    result = prerank_for_capture([stats("LOW", vol=1e6), stats("HIGH", vol=1e8)], n=1)
    assert result.selected == ("HIGH",)


def test_higher_amihud_and_higher_gap_rate_rank_lower() -> None:
    """Both carry NEGATIVE weight in §4.1 (-0.50 and -0.25); the pre-rank keeps the signs."""
    illiquid = stats("ILLIQ", amihud=1e-2)
    gappy = stats("GAPPY", gap=0.40)
    clean = stats("CLEAN")
    result = prerank_for_capture([illiquid, gappy, clean], n=1)
    assert result.selected == ("CLEAN",)


def test_the_weights_are_section_4_1s_not_new_ones() -> None:
    """A+ omits spread; it does not invent weights. Anything else is a free parameter fitted
    after seeing the data, which is exactly what `top_n` refuses an unregistered N to prevent."""
    from pips.universe.liquidity import WEIGHTS
    from pips.universe.prerank import PRERANK_WEIGHTS

    assert {k: v for k, v in WEIGHTS.items() if k != "relative_spread"} == PRERANK_WEIGHTS


def test_an_unmeasurable_name_is_excluded_and_named_not_ranked_last() -> None:
    """Same rule as `_unmeasurable`: NaN is not a bad score, it is no score."""
    result = prerank_for_capture([stats("A"), stats("NOVOL", vol=math.nan), stats("C")], n=5)
    assert "NOVOL" not in result.selected
    assert "NOVOL" in result.excluded and "median_rupee_volume" in result.excluded["NOVOL"]


def test_n_is_a_maximum_and_it_never_pads() -> None:
    result = prerank_for_capture([stats("A"), stats("B")], n=500)
    assert result.selected == ("A", "B") or set(result.selected) == {"A", "B"}
    assert len(result.selected) == 2


def test_ties_break_on_the_symbol_so_the_cut_is_deterministic() -> None:
    """Rule 1. Two identical names either side of the cut must fall the same way every run."""
    pop = [stats(s) for s in ("ZED", "ALPHA", "MID")]
    assert (
        prerank_for_capture(pop, n=1).selected
        == prerank_for_capture(list(reversed(pop)), n=1).selected
    )


# ------------------------------------------------------------- 2. the superset check -----


def test_a_universe_inside_the_shortlist_has_no_breaches() -> None:
    assert superset_breaches(universe=("A", "B"), shortlist=("A", "B", "C")) == ()


def test_a_universe_name_outside_the_shortlist_is_named() -> None:
    """The guarantee that used to hold by construction now has to be OBSERVED to hold — and when
    it does not, the reader gets the name, not a boolean."""
    assert superset_breaches(universe=("A", "X"), shortlist=("A", "B")) == ("X",)


def test_breaches_are_sorted_so_the_report_is_stable() -> None:
    assert superset_breaches(universe=("Z", "M", "A"), shortlist=()) == ("A", "M", "Z")


# ------------------------------------------------------------ 3. the exploration budget -----


def test_exploration_takes_names_just_outside_the_cut_not_random_ones() -> None:
    ranked = tuple(f"S{i:03d}" for i in range(20))  # S000 best ... S019 worst
    picks = exploration_picks(ranked, cut=10, budget=3, refresh=date(2026, 9, 7))
    assert set(picks) <= set(ranked[10:]), "exploration lives OUTSIDE the cut"
    assert len(picks) == 3


def test_exploration_rotates_across_refreshes() -> None:
    """The whole point: a name at rank 505 must not be the name at rank 505 forever."""
    ranked = tuple(f"S{i:03d}" for i in range(20))
    a = exploration_picks(ranked, cut=10, budget=3, refresh=date(2026, 9, 7))
    b = exploration_picks(ranked, cut=10, budget=3, refresh=date(2026, 9, 14))
    assert a != b


def test_exploration_is_deterministic_for_a_given_refresh() -> None:
    """Rotating is not the same as random (rule 1): the same refresh date picks the same names."""
    ranked = tuple(f"S{i:03d}" for i in range(20))
    assert exploration_picks(
        ranked, cut=10, budget=3, refresh=date(2026, 9, 7)
    ) == exploration_picks(ranked, cut=10, budget=3, refresh=date(2026, 9, 7))


def test_exploration_covers_the_whole_tail_over_enough_refreshes() -> None:
    """Rotation must actually rotate through everyone outside the cut, not orbit a few."""
    ranked = tuple(f"S{i:03d}" for i in range(16))
    seen: set[str] = set()
    for week in range(12):
        refresh = date(2026, 9, 7) + timedelta(weeks=week)
        seen |= set(exploration_picks(ranked, cut=10, budget=2, refresh=refresh))
    assert seen == set(ranked[10:]), f"never explored: {set(ranked[10:]) - seen}"


def test_a_budget_larger_than_the_tail_returns_the_whole_tail_once() -> None:
    ranked = ("A", "B", "C", "D")
    picks = exploration_picks(ranked, cut=2, budget=10, refresh=date(2026, 9, 7))
    assert sorted(picks) == ["C", "D"]


@pytest.mark.parametrize("budget", [0, -1])
def test_a_non_positive_budget_explores_nothing(budget: int) -> None:
    assert exploration_picks(("A", "B", "C"), cut=1, budget=budget, refresh=date(2026, 9, 7)) == ()


def test_exploration_covers_the_tail_in_ceil_len_over_budget_refreshes_not_more() -> None:
    """The docstring promises coverage in ``ceil(len(tail) / budget)`` refreshes. The looser test
    above (coverage *eventually*) let a mutant survive that advanced the window by ONE name per
    week instead of by ``budget`` -- still covering everyone, but in ``len(tail)`` weeks, and
    re-capturing half of last week's names each time. Wasted capture budget is the whole cost
    A+ is trying to control, so the RATE is the property, not merely the destination.
    """
    ranked = tuple(f"S{i:03d}" for i in range(16))  # tail of 6 outside a cut of 10
    budget, tail = 2, set(ranked[10:])
    needed = -(-len(tail) // budget)  # ceil -> 3
    seen: set[str] = set()
    for week in range(needed):
        seen |= set(
            exploration_picks(
                ranked, cut=10, budget=budget, refresh=date(2026, 9, 7) + timedelta(weeks=week)
            )
        )
    assert seen == tail, f"after {needed} refreshes still unexplored: {tail - seen}"


def test_exploration_can_be_bounded_to_a_band_below_the_cut() -> None:
    # OWNER DECISION 2026-09-06: explore ranks 501-1,000 only. Names at rank 2,400 will never
    # qualify on four components; spending the budget there measures nothing useful.
    ranked = tuple(f"S{i:04d}" for i in range(1, 2001))
    picks = exploration_picks(ranked, cut=500, budget=25, refresh=date(2026, 9, 7), band_end=1000)
    assert len(picks) == 25
    assert all(500 < int(p[1:]) <= 1000 for p in picks)


def test_the_band_is_walked_completely_in_ceil_band_over_budget_refreshes() -> None:
    ranked = tuple(f"S{i:04d}" for i in range(1, 2001))
    seen: set[str] = set()
    for week in range(20):  # 500 names / 25 per week
        seen |= set(
            exploration_picks(
                ranked,
                cut=500,
                budget=25,
                refresh=date(2026, 9, 7) + timedelta(weeks=week),
                band_end=1000,
            )
        )
    assert seen == set(ranked[500:1000])


def test_a_band_that_ends_at_or_before_the_cut_explores_nothing() -> None:
    ranked = tuple(f"S{i:04d}" for i in range(1, 2001))
    assert (
        exploration_picks(ranked, cut=500, budget=25, refresh=date(2026, 9, 7), band_end=500) == ()
    )
    assert (
        exploration_picks(ranked, cut=500, budget=25, refresh=date(2026, 9, 7), band_end=300) == ()
    )


def test_without_a_band_the_whole_tail_is_the_pool_as_before() -> None:
    ranked = tuple(f"S{i:04d}" for i in range(1, 2001))
    picks = exploration_picks(ranked, cut=500, budget=25, refresh=date(2026, 9, 7))
    assert len(picks) == 25 and all(int(p[1:]) > 500 for p in picks)
