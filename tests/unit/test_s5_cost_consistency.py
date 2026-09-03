"""The S5 smoke prices selection and netting on two different cost lines (§6 M15, `[C-S5-01]`).

`families.py` warns about this at one of the two sites:

    # The SAME line the PnL is netted with. Two literals would drift, and S5 would then
    # price a trade differently from the series it is selecting on.
    gross_cost=CostLine(ROUND_TRIP_COST),

and then `_turnover_inputs()` supplies `CostLine(0.00025)` — half of `ROUND_TRIP_COST`, with no
comment — for the line that decides τ* and h*. `turnover.CostLine` documents itself as "the
all-in cost per round trip", the same quantity `gross_cost` carries, so these are two prices for
one thing.

**The smoke's headline verdict depends on the gap.** Setting them equal makes `s5_admissible`
false: the synthetic edge clears 2.5 bps and does not clear 5. So the demonstration that the S5
chain composes end to end rests on selection being priced at half what the returns are netted
at, and nothing said so.

This test does not decide which number is right — that is a modelling question about a fixture,
not something to settle from the outside. It pins the RELATIONSHIP, so the two cannot drift
further in silence, and it fails loudly if anyone changes one without the other.
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


def test_the_smokes_admissibility_is_recorded_as_depending_on_the_gap() -> None:
    """A regression guard on the finding itself.

    If `SELECTION_COST_FACTOR` ever becomes 1, the two lines agree — and the S5 smoke stops
    reporting admissible, which is a real change in what the fixture demonstrates. That should
    be a deliberate act with its reasoning written down, not something noticed later.
    """
    assert families.SELECTION_COST_FACTOR != 1.0, (
        "the two cost lines now agree — S5 will report inadmissible on the fixture edge, so "
        "the smoke no longer demonstrates the chain composing. If that is intended, say so "
        "here and in the module; if not, the edge curve needs to clear the honest cost."
    )
