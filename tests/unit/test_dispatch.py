"""One driver per alpha family, so a search can run across families  (§6 M12/M19).

Successive halving converges to a single winner, so one family can never give S5 more than one
candidate — S5 selects ACROSS families. Every alpha shares the `compute(view, params, spec)`
signature and has its own `Params` type, and nothing mapped one to the other.

Three properties matter more than the mapping itself:

* **the register is complete** — every spec with a compute plugin is either driven or recorded
  as not runnable WITH A REASON, so an alpha cannot go missing by being forgotten;
* **a driver that produces nothing is not a driver** — "produced no forecasts" is not "produced
  no edge", and an alpha silently scoring zero would lose a search it never entered;
* **nothing bounded escapes the domain check** — a parameter may be left unchecked only where
  the spec itself declines to bound it, and that exemption is visible.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from pips.alphas.dispatch import DRIVERS, NOT_RUNNABLE, AlphaDriver
from pips.alphas.spec import load_alpha_spec
from pips.core.asof import AsOfPanelView
from pips.search.grid import assert_within_domain, grid_from_domain
from pips.search.s1 import load_panel, specs_with_plugins

SPECS = Path("config/search_spaces")
PANEL = load_panel(Path("fixtures"))
STAMPS = sorted(set(PANEL["close_ts_ns"].to_list()))
IDS = sorted(DRIVERS)


# ------------------------------------------------------------ completeness ------------


def test_every_alpha_with_a_plugin_is_either_driven_or_explained() -> None:
    """An alpha cannot go missing by being forgotten.

    Without this, adding a tenth plugin and no driver silently narrows the search to nine
    families, and the ensemble reports on a population nobody chose.
    """
    accounted = set(DRIVERS) | set(NOT_RUNNABLE)
    assert specs_with_plugins() == accounted


def test_no_alpha_is_both_driven_and_excluded() -> None:
    assert not set(DRIVERS) & set(NOT_RUNNABLE)


@pytest.mark.parametrize("alpha_id", sorted(NOT_RUNNABLE))
def test_each_exclusion_states_a_reason(alpha_id: str) -> None:
    # "Not runnable" without a reason is indistinguishable from "not got round to".
    assert len(NOT_RUNNABLE[alpha_id]) > 30


@pytest.mark.parametrize("alpha_id", IDS)
def test_the_driver_key_matches_its_alpha_and_its_spec(alpha_id: str) -> None:
    driver = DRIVERS[alpha_id]
    assert driver.alpha_id == alpha_id
    assert load_alpha_spec(SPECS / driver.spec_file).id == alpha_id


# ------------------------------------------------------------ the domain --------------


@pytest.mark.parametrize("alpha_id", IDS)
def test_the_swept_parameter_yields_an_in_domain_grid(alpha_id: str) -> None:
    driver = DRIVERS[alpha_id]
    spec = load_alpha_spec(SPECS / driver.spec_file)
    low, high = spec.parameter_domain[driver.swept]
    for value in grid_from_domain(spec, driver.swept, count=4):
        assert low <= value <= high


@pytest.mark.parametrize("alpha_id", IDS)
def test_the_fixed_parameters_are_inside_their_declared_ranges(alpha_id: str) -> None:
    driver = DRIVERS[alpha_id]
    assert_within_domain(load_alpha_spec(SPECS / driver.spec_file), driver.fixed)


@pytest.mark.parametrize("alpha_id", IDS)
def test_nothing_bounded_hides_in_the_unchecked_bucket(alpha_id: str) -> None:
    """`unchecked` is for parameters the SPEC declines to bound, not for inconvenient ones.

    A05 declares `confirmation_thresholds: 'coarse grid, preregistered'` — prose, not a range —
    so its volume and breadth thresholds cannot be checked against anything. That is a gap in
    the pre-registration and is recorded as one. What must not happen is a parameter with a
    perfectly good declared range being parked here to avoid the check.
    """
    driver = DRIVERS[alpha_id]
    spec = load_alpha_spec(SPECS / driver.spec_file)
    for name in driver.unchecked:
        domain = spec.parameter_domain.get(name)
        is_range = (
            isinstance(domain, list | tuple)
            and len(domain) == 2
            and all(isinstance(v, int | float) and not isinstance(v, bool) for v in domain)
        )
        assert not is_range, f"{alpha_id}.{name} has a declared range and must be checked"


# ------------------------------------------------------------ it actually runs --------


@pytest.mark.parametrize("alpha_id", IDS)
def test_every_driver_produces_forecasts_on_the_fixture_panel(alpha_id: str) -> None:
    """A driver that yields nothing would score zero and lose a search it never entered.

    "Produced no forecasts" and "produced no edge" are different findings and the same number.
    """
    driver = DRIVERS[alpha_id]
    spec = load_alpha_spec(SPECS / driver.spec_file)
    swept = grid_from_domain(spec, driver.swept, count=4)[0]
    params = driver.build(swept, bars=1)

    produced = sum(
        len(driver.compute(AsOfPanelView(PANEL, decision_ts=ts), params, spec))
        for ts in STAMPS[600:700]
    )
    assert produced > 0, f"{alpha_id} produced no forecasts and must not be registered as runnable"


@pytest.mark.parametrize("alpha_id", IDS)
def test_the_built_params_carry_the_swept_value(alpha_id: str) -> None:
    # Otherwise the sweep varies a number the alpha never sees, and every rung scores the same.
    driver = DRIVERS[alpha_id]
    spec = load_alpha_spec(SPECS / driver.spec_file)
    grid = grid_from_domain(spec, driver.swept, count=4)
    built = [driver.build(v, bars=1) for v in grid]
    assert len(set(map(repr, built))) == len(grid)


def test_the_register_is_not_empty() -> None:
    assert len(DRIVERS) >= 4, "S5 needs several families to have an ensemble at all"
    assert isinstance(next(iter(DRIVERS.values())), AlphaDriver)


# ------------------------------------------------------------ declarations bind -------


@pytest.mark.parametrize("alpha_id", IDS)
def test_the_build_reads_the_declared_fixed_values(alpha_id: str) -> None:
    """A hardcoded constant beside a checked declaration is a second copy of one number.

    `fixed` is verified against the spec's declared ranges, and for a while the builders simply
    repeated those numbers as literals — so a driver could declare `hold_minutes: 15`, pass the
    domain check, and construct a one-minute horizon. The check saw the declaration; the run used
    the literal. Changing the declaration must change what gets built, or the check is decorative.
    """
    driver = DRIVERS[alpha_id]
    spec = load_alpha_spec(SPECS / driver.spec_file)
    swept = grid_from_domain(spec, driver.swept, count=4)[0]
    baseline = driver.build(swept, bars=1)

    for name, value in driver.fixed.items():
        moved = replace(driver, fixed={**driver.fixed, name: value + 1})
        assert repr(moved.build(swept, bars=1)) != repr(baseline), (
            f"{alpha_id}: changing declared {name} changed nothing in the built params"
        )


def test_the_build_reads_the_unchecked_values_too() -> None:
    """A05's thresholds are recorded as unchecked; they must still be what it runs with.

    An `unchecked` mapping the builder ignores is documentation of something that is not
    happening, which is worse than no documentation.
    """
    driver = DRIVERS["A05"]
    spec = load_alpha_spec(SPECS / driver.spec_file)
    swept = grid_from_domain(spec, driver.swept, count=4)[0]
    baseline = driver.build(swept, bars=1)

    for name, value in driver.unchecked.items():
        moved = replace(driver, unchecked={**driver.unchecked, name: Decimal(str(value)) + 1})
        assert repr(moved.build(swept, bars=1)) != repr(baseline), f"unchecked {name} is ignored"
