"""`gap_rate`, the fourth term of M7's liquidity score — defined at last (`BLK-0003`).

§4.1 gives `L = z(log median ₹-volume) - 0.75z(spread) - 0.50z(Amihud) - 0.25z(gap_rate)` and
defines **no component**. Until 2026-09-05 `gap_rate` existed in this repository as a field name
and a weight and nothing else: no threshold, no lookback, no statement of what it measures. That
made it the one part of the screen that could not be implemented without inventing the semantics
of what counts as tradeable, which is why it went to the owner.

DECIDED, 2026-09-05: the FRACTION of session-pairs whose overnight move exceeds a configured
threshold, excluding jumps a corporate action explains.

    move_d = |open_d / close_{d-1} - 1|
    gap_rate = #{d : move_d > threshold} / #{d : usable}

Three things make it the shape it is:

* **A frequency, not a mean magnitude.** One crash day would dominate an average; and "rate"
  means how often, not how far.
* **Corporate actions are EXCLUDED, not counted.** A 1:2 split is a 50% "gap" that says nothing
  about liquidity. pips already discriminates these for QC via `jump_explainer`, so this reuses
  that judgement rather than growing a second notion of "unexplained jump".
* **An excluded pair leaves the denominator too.** It is not evidence of gappiness OR of
  smoothness, so counting it either way would be a claim the data does not make — the same rule
  `amihud_ratio` follows for a day with no usable volume.
"""

from __future__ import annotations

from datetime import date

import pytest

from pips.universe.liquidity import gap_rate

# close_{d-1} = 10000 paise throughout, so an open of 10400 is a 4% gap.
FLAT = [
    (date(2026, 8, 24), 10000, 10000),
    (date(2026, 8, 25), 10000, 10000),
    (date(2026, 8, 26), 10000, 10000),
    (date(2026, 8, 27), 10000, 10000),
]


def bars(*opens: int) -> list[tuple[date, int, int]]:
    """(day, open_paise, close_paise) with every close at 10000, so opens drive the gaps."""
    return [(date(2026, 8, 24 + i), o, 10000) for i, o in enumerate(opens)]


def test_no_gaps_is_zero_not_nan() -> None:
    assert gap_rate(FLAT, threshold=0.03) == 0.0


def test_it_is_a_fraction_of_the_pairs_that_gapped() -> None:
    # opens: 10000 (no prior), 10400 (+4%), 10000 (0%), 10000 (0%) -> 1 of 3 pairs
    assert gap_rate(bars(10000, 10400, 10000, 10000), threshold=0.03) == pytest.approx(1 / 3)


def test_the_direction_of_the_gap_does_not_matter() -> None:
    """A 4% gap down is as much a gap as a 4% gap up."""
    up = gap_rate(bars(10000, 10400, 10000, 10000), threshold=0.03)
    down = gap_rate(bars(10000, 9600, 10000, 10000), threshold=0.03)
    assert up == down == pytest.approx(1 / 3)


def test_the_threshold_is_strict_and_actually_bites() -> None:
    """A fixture where the two readings differ, or the parameter proves nothing."""
    exactly_three = bars(10000, 10300, 10000, 10000)
    assert gap_rate(exactly_three, threshold=0.03) == 0.0, "3% is not ABOVE a 3% threshold"
    assert gap_rate(exactly_three, threshold=0.02) == pytest.approx(1 / 3)


def test_the_first_session_makes_no_pair() -> None:
    """There is no previous close to gap from, so it is not a denominator entry."""
    assert gap_rate(bars(10000, 10000), threshold=0.03) == 0.0
    # one pair only; if the lone session counted, a 4% open would read as 1/2 rather than 1/1
    assert gap_rate(bars(10000, 10400), threshold=0.03) == pytest.approx(1.0)


def test_a_corporate_action_jump_is_excluded_from_both_sides() -> None:
    """The property the whole design turns on.

    A 1:2 split halves the price overnight. Counted, this name looks like the gappiest stock on
    the exchange; counted as a NON-gap it looks unusually smooth. Neither is true, so the pair
    leaves the sample entirely.
    """
    split = bars(10000, 5000, 10000, 10000)  # -50% on the second day

    def explains_the_split(symbol: str, day: date, prev_close: int, open_: int) -> object:
        class V:
            explained = day == date(2026, 8, 25)
            reason = "1:2 split"

        return V()

    assert gap_rate(split, threshold=0.03) == pytest.approx(1 / 3), "unexplained, it is a gap"
    # Excluded from the numerator AND the denominator: 0 gaps out of the 2 remaining pairs.
    assert gap_rate(split, threshold=0.03, explain=explains_the_split, symbol="X") == 0.0


def test_an_unexplained_jump_still_counts() -> None:
    """The exclusion must be earned by an actual verdict, not by an explainer being present."""

    def explains_nothing(symbol: str, day: date, prev_close: int, open_: int) -> object:
        class V:
            explained = False
            reason = "no action found"

        return V()

    moved = bars(10000, 10400, 10000, 10000)
    assert gap_rate(moved, threshold=0.03, explain=explains_nothing, symbol="X") == pytest.approx(
        1 / 3
    )


def test_no_usable_pair_is_nan_rather_than_zero() -> None:
    """Zero is the SMOOTHEST reading there is; absence of evidence must not earn it.

    Same rule `amihud_ratio` follows, and `_usable` already refuses non-finite components, so
    the name leaves the ranking instead of topping it.
    """
    import math

    assert math.isnan(gap_rate([], threshold=0.03))
    assert math.isnan(gap_rate(bars(10000), threshold=0.03))


def test_a_non_positive_previous_close_is_dropped_not_divided_by() -> None:
    weird = [(date(2026, 8, 24), 10000, 0), (date(2026, 8, 25), 10400, 10000)]
    import math

    assert math.isnan(gap_rate(weird, threshold=0.03)), "the only pair had no usable base"


def test_an_explained_pair_leaves_the_denominator_too() -> None:
    """The earlier exclusion test could not tell this apart, and a mutation proved it.

    With the split as the ONLY move, dropping it from the denominator gives 0/3 and keeping it
    gives 0/4 — both zero, so the fixture passed either way. This one has a REAL gap beside the
    split, so the two readings separate:

        excluded from both sides : 1 gap / 3 usable pairs = 0.333...
        left in the denominator  : 1 gap / 4 usable pairs = 0.25

    Both are plausible numbers. Only one is right, and a corporate action is not evidence that a
    name trades smoothly.
    """
    # pairs: -50% (a split, explained), +4% (a real gap), 0%, 0%
    series = bars(10000, 5000, 10400, 10000, 10000)

    def explains_the_split(symbol: str, day: date, prev_close: int, open_: int) -> object:
        class V:
            explained = day == date(2026, 8, 25)
            reason = "1:2 split"

        return V()

    got = gap_rate(series, threshold=0.03, explain=explains_the_split, symbol="X")
    assert got == pytest.approx(1 / 3)
    assert got != pytest.approx(1 / 4), "the explained pair must not pad the denominator"
