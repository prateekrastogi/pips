"""The search grid comes from the pre-registered domain  (C2, §6 M12).

C2: *"Entry thresholds, holding periods, position sizes and rebalance bands are the argmax of a
stated objective under the cost model — never round numbers that felt right."* The domain has to
be stated too. Every AlphaSpec declares `parameter_domain` as `[min, max]` per parameter, and
that is the pre-registration; a grid hardcoded in the search driver is a sweep over a space
nobody registered, and nothing stops it drifting outside the declared one.

Two units live here, and they are not the same unit. The spec declares `residual_lookback_m` in
MINUTES; `A01Params.residual_lookback` counts BARS. They coincide on a one-minute panel and only
there, so the conversion is explicit and the bar interval is checked rather than assumed.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from pips.alphas.spec import load_alpha_spec
from pips.search.grid import assert_within_domain, bars_per_unit, grid_from_domain

SPEC = load_alpha_spec(Path("config/search_spaces/A01_residual_momentum.yaml"))
MINUTE_NS = 60 * 1_000_000_000


# ------------------------------------------------------------ the grid ----------------


def test_every_grid_point_lies_inside_the_declared_domain() -> None:
    low, high = SPEC.parameter_domain["residual_lookback_m"]
    for value in grid_from_domain(SPEC, "residual_lookback_m", count=4):
        assert low <= value <= high


def test_the_endpoints_of_the_domain_are_included() -> None:
    """A sweep that never tries the declared extremes has not swept the declared domain."""
    low, high = SPEC.parameter_domain["residual_lookback_m"]
    grid = grid_from_domain(SPEC, "residual_lookback_m", count=4)
    assert grid[0] == low
    assert grid[-1] == high


def test_the_spacing_is_geometric_not_linear() -> None:
    """A lookback of 3 vs 4 differs by 33%; 100 vs 101 differs by 1%.

    Linear spacing over [3, 120] puts three of its four points above 40, where the parameter
    barely changes behaviour, and never distinguishes 3 from 10. The choice is stated here so it
    cannot quietly become linear.
    """
    grid = grid_from_domain(SPEC, "residual_lookback_m", count=4)
    ratios = [b / a for a, b in itertools.pairwise(grid)]
    assert max(ratios) / min(ratios) < 1.6, f"roughly constant ratio, got {ratios}"

    linear = [3 + i * (120 - 3) / 3 for i in range(4)]
    assert [float(v) for v in grid] != linear


def test_the_grid_is_ascending_and_free_of_duplicates() -> None:
    grid = grid_from_domain(SPEC, "residual_lookback_m", count=6)
    assert list(grid) == sorted(grid)
    assert len(set(grid)) == len(grid)


def test_a_narrow_integer_domain_yields_fewer_points_than_asked_for() -> None:
    """`skip_bars` is [0, 3]: four integers exist, so a grid of eight cannot.

    Returning eight by repeating values would make the search report more trials than
    parameters, inflating the multiplicity denominator with duplicates.
    """
    grid = grid_from_domain(SPEC, "skip_bars", count=8)
    assert len(grid) <= 4
    assert len(set(grid)) == len(grid)


def test_the_grid_is_deterministic() -> None:
    assert grid_from_domain(SPEC, "residual_lookback_m", count=5) == grid_from_domain(
        SPEC, "residual_lookback_m", count=5
    )


# ------------------------------------------------------------ refusals -----------------


def test_a_parameter_the_spec_does_not_declare_is_refused() -> None:
    """Not defaulted to some range the code picked.

    A parameter absent from the pre-registration is one the spec never bounded, and sweeping it
    would be sweeping an unregistered space while looking exactly like sweeping a registered one.
    """
    with pytest.raises(KeyError, match="does not declare"):
        grid_from_domain(SPEC, "residual_lookback", count=4)


def test_a_count_below_two_is_refused() -> None:
    # One point is not a search; it is a hardcoded value wearing a grid's clothes.
    with pytest.raises(ValueError, match="at least 2"):
        grid_from_domain(SPEC, "residual_lookback_m", count=1)


# ------------------------------------------------------------ units --------------------


def test_minutes_convert_to_bars_only_when_the_bars_are_minutes() -> None:
    """The spec says `_m` and the params count bars. They coincide on a one-minute panel.

    On five-minute bars a declared lookback of 15 minutes is three bars, and passing 15 would
    silently look back 75 minutes — a parameter five times the registered one, still inside the
    declared range as a number, and outside it as a duration.
    """
    assert bars_per_unit(MINUTE_NS) == 1
    assert bars_per_unit(5 * MINUTE_NS) == 5


def test_a_bar_interval_that_does_not_divide_a_minute_is_refused() -> None:
    with pytest.raises(ValueError, match="minute"):
        bars_per_unit(7 * 1_000_000_000)


def test_the_conversion_refuses_a_non_positive_interval() -> None:
    with pytest.raises(ValueError, match="positive"):
        bars_per_unit(0)


# ------------------------------------------------------------ conformance --------------
#
# The grid keeps the SWEPT parameter inside the domain. The parameters held FIXED during a sweep
# are just as capable of sitting outside it, and nothing was checking them.


def test_fixed_parameters_inside_the_domain_are_accepted() -> None:
    assert_within_domain(SPEC, {"residual_lookback_m": 10, "scale_window_m": 20})


def test_a_fixed_parameter_below_its_declared_minimum_is_refused() -> None:
    """The real case this was written for.

    `config/search_spaces/A01` declares `hold_minutes: [15, 120]`, and the S1 smoke has run
    A01 with `horizon_ns = 60 * NS` — one minute, fifteen times below the registered floor —
    since M12. The number is plausible, the run completes, and the falsifiers attached to the
    spec ("monotone rank-IC across the horizon grid") were written for a space that run is not
    in.
    """
    with pytest.raises(ValueError, match="hold_minutes"):
        assert_within_domain(SPEC, {"hold_minutes": 1})


def test_a_fixed_parameter_above_its_declared_maximum_is_refused() -> None:
    with pytest.raises(ValueError, match="240"):
        assert_within_domain(SPEC, {"hold_minutes": 240})


def test_the_message_names_the_declared_range() -> None:
    # Refusing without saying what the domain IS makes the reader go and look, and the value
    # they are checking against is the one thing the error already knows.
    with pytest.raises(ValueError, match=r"\[15, 120\]"):
        assert_within_domain(SPEC, {"hold_minutes": 1})


def test_a_parameter_the_spec_does_not_declare_is_refused_here_too() -> None:
    with pytest.raises(KeyError, match="does not declare"):
        assert_within_domain(SPEC, {"invented_knob": 5})


def test_the_endpoints_are_inside() -> None:
    assert_within_domain(SPEC, {"hold_minutes": 15})
    assert_within_domain(SPEC, {"hold_minutes": 120})
