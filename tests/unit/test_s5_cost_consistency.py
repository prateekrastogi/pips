"""The S5 smoke prices selection and netting on two different cost lines (§6 M15, `[C-S5-01]`).

`families.py` warns about this at one of the two sites:

    # The SAME line the PnL is netted with. Two literals would drift, and S5 would then
    # price a trade differently from the series it is selecting on.
    gross_cost=CostLine(ROUND_TRIP_COST),

and then `_turnover_inputs()` supplies `CostLine(0.00025)` — half of `ROUND_TRIP_COST`, with no
comment — for the line that decides τ* and h*. `turnover.CostLine` documents itself as "the
all-in cost per round trip", the same quantity `gross_cost` carries, so these are two prices for
one thing.

**The smoke's headline verdict depended on the gap.** Equalising them makes `s5_admissible`
false: the synthetic edge clears 2.5 bps and does not clear 5. So the demonstration that the S5
chain composes end to end rested on selection being priced at half what the returns are netted
at, and nothing said so.

**Resolved 2026-09-04 (owner): equalise.** `SELECTION_COST_FACTOR` is 1.0 and the verdict on
fixture noise is false, which is the honest answer — the smoke's job is to prove the chain is
wired, not to produce an admissible strategy from a seeded random walk. These tests now pin that
the two lines are ONE line, so splitting them again would have to be argued for.
"""

from __future__ import annotations

import pytest

from pips.search import families


def test_the_two_cost_lines_are_related_by_a_stated_factor() -> None:
    """One number, one factor, both visible.

    Before this, the relationship was two unexplained literals two hundred lines apart. A
    reader comparing them had no way to tell a deliberate ratio from a typo, and the file's own
    comment says why that matters: S5 would price a trade differently from the series it is
    selecting on.
    """
    assert (
        pytest.approx(families.SELECTION_COST)
        == families.SELECTION_COST_FACTOR * families.ROUND_TRIP_COST
    )
    assert 0 < families.SELECTION_COST_FACTOR <= 1


def test_the_turnover_inputs_use_the_named_selection_cost() -> None:
    """Not a third literal. The whole point is that there is one place to change."""
    line = families._turnover_inputs().cost_lines[("FLATTRADE", "2L")]

    assert line.total == pytest.approx(families.SELECTION_COST)


def test_the_two_lines_are_now_one_line() -> None:
    """The guard that used to sit here asserted `SELECTION_COST_FACTOR != 1.0`, so that
    equalising could not happen quietly: *"that should be a deliberate act with its reasoning
    written down, not something noticed later."*

    It did its job — this is the deliberate act. Resolved by the owner on 2026-09-04: equalise,
    and let the verdict be false. The smoke proves the chain is WIRED, and its own output says
    "WHAT THIS IS NOT: an edge — the fixtures are two synthetic symbols from a seeded random
    walk". An admissible verdict on noise was never meaningful, and buying one by pricing
    selection at half the netting cost made the single number that looks like a result the one
    that was arranged.

    The assertion is inverted rather than deleted: a future change back to a split line would be
    a modelling decision too, and should meet the same bar.
    """
    assert families.SELECTION_COST_FACTOR == 1.0, (
        "the selection line has been split from the netting line again — S5 would price a "
        "trade differently from the series it selects on, which is what `families.py`'s own "
        "comment warns against. If a venue genuinely differs, say which and why."
    )
    assert families.SELECTION_COST == families.ROUND_TRIP_COST
