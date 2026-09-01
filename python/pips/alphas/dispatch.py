"""One driver per alpha family, so a search can run across families  (§6 M12/M19).

Successive halving converges to a single winner, so one family can never give S5 more than one
candidate — S5 selects ACROSS families. Every alpha shares the ``compute(view, params, spec)``
signature and has its own ``Params`` type, and nothing mapped one to the other.

Three properties matter more than the mapping:

* **the register is complete.** Every spec with a compute plugin is either driven or recorded in
  :data:`NOT_RUNNABLE` with a reason. Adding a plugin and forgetting a driver would silently
  narrow the search, and the ensemble would report on a population nobody chose.
* **a driver that produces nothing is not a driver.** "Produced no forecasts" and "produced no
  edge" are different findings and the same number — an alpha yielding nothing would score zero
  and lose a search it never entered. Every driver is tested to produce forecasts on the panel.
* **nothing bounded escapes the domain check.** ``fixed`` is verified against the spec's declared
  ranges; ``unchecked`` exists only for parameters the SPEC declines to bound, and a test refuses
  anything with a real range parked there.

The exclusions are facts, not guesses — each was established by running the alpha against the
fixture panel and reading what it said.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pips.alphas.forecast import Forecast
from pips.alphas.t1 import a01, a02, a03, a04, a05, a06, a07, a08
from pips.fixtures.events import fixture_event_source

if TYPE_CHECKING:
    from pips.alphas.forecast import Forecast

__all__ = ["DRIVERS", "NOT_RUNNABLE", "AlphaDriver"]

_NS = 1_000_000_000


@dataclass(frozen=True)
class AlphaDriver:
    """How to turn a point in a spec's declared domain into that alpha's ``Params``."""

    alpha_id: str
    spec_file: str
    swept: str
    """The declared domain key the search varies."""
    fixed: Mapping[str, float]
    """Other declared parameters, in the SPEC's units, checked against their ranges."""
    compute: Callable[..., list[Forecast]]
    _build: Callable[[float, Mapping[str, float], Mapping[str, object], int], Any]
    unchecked: Mapping[str, object] = field(default_factory=dict)
    """Parameters the spec declines to bound numerically. Recorded, and their exemption tested."""

    def build(self, swept_value: float, *, bars: int) -> Any:
        """`bars` converts the spec's MINUTES into panel bars; they coincide only at one minute.

        The declared `fixed` and `unchecked` values are PASSED to the builder rather than
        repeated inside it. A hardcoded constant beside a declaration that is checked against
        the domain is a second copy of one number, and the copy that drifts is the one the
        domain check never sees — a driver could declare `hold_minutes: 15`, pass the check,
        and build a one-minute horizon.
        """
        return self._build(swept_value, self.fixed, self.unchecked, bars)


Built = Mapping[str, float]
Notes = Mapping[str, object]


def _a01(lookback_m: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del notes
    return a01.A01Params(
        residual_lookback=int(lookback_m) * bars,
        scale_window=int(fixed["scale_window_m"]) * bars,
        horizon_ns=int(fixed["hold_minutes"]) * 60 * _NS,
    )


def _a02(vol_half_life_m: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del notes
    # `lookbacks` needs at least two horizons; both sit inside own_lookbacks_m [5, 240].
    base = int(fixed["own_lookbacks_m"])
    return a02.A02Params(
        lookbacks=(base * bars, 2 * base * bars),
        vol_window=int(vol_half_life_m) * bars,
        horizon_ns=int(fixed["hold_minutes"]) * 60 * _NS,
    )


def _a03(shock_window_m: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del notes
    return a03.A03Params(
        shock_window=int(shock_window_m) * bars,
        tail=fixed["robust_tail"],
        horizon_ns=int(fixed["hold_minutes"]) * 60 * _NS,
    )


def _a04(spread_z_window_m: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del notes
    return a04.A04Params(
        z_window=int(spread_z_window_m) * bars,
        entry_z=fixed["entry_z"],
        exit_z=fixed["exit_z"],
        horizon_ns=int(fixed["hold_minutes"]) * 60 * _NS,
    )


def _a05(observe_minutes: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del bars  # A05 takes its observation window in minutes directly.
    return a05.A05Params(
        observe_minutes=int(observe_minutes),
        hold_minutes=int(fixed["hold_minutes"]),
        # Cast at the use site, explicitly. `unchecked` is typed `object` because the spec
        # declines to bound these and so says nothing about their type either; converting
        # through `str` is exact for Decimal and loud for anything that is not a number.
        min_volume_ratio=Decimal(str(notes["min_volume_ratio"])),
        min_breadth=Decimal(str(notes["min_breadth"])),
        horizon_ns=int(fixed["hold_minutes"]) * 60 * _NS,
    )


def _a06(hold_minutes: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del bars, fixed  # A06 works in minutes; every other parameter is the unbounded grid.
    return a06.A06Params(
        observe_minutes=int(str(notes["observe_minutes"])),
        hold_minutes=int(hold_minutes),
        max_volume_ratio=Decimal(str(notes["max_volume_ratio"])),
        max_breadth=Decimal(str(notes["max_breadth"])),
        max_range_continuation=Decimal(str(notes["max_range_continuation"])),
        horizon_ns=int(hold_minutes) * 60 * _NS,
    )


def _a06_compute(view: Any, params: Any, spec: Any) -> list[Forecast]:
    """A06 alone takes a fourth argument, so the dispatch binds it here.

    The source is the FIXTURE allowlist: CLEAR for generated names, UNKNOWN for anything else.
    A06 keeps its refusal intact against real symbols -- the wrapper widens the dispatch, not
    the rule.
    """
    return a06.compute(view, params, spec, fixture_event_source())


def _a07(buffer_atr: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del bars  # A07 works in minutes directly.
    return a07.A07Params(
        range_end_minutes=int(fixed["range_end_minutes"]),
        buffer_atr=Decimal(str(buffer_atr)),
        hold_minutes=int(fixed["hold_minutes"]),
        min_participation=Decimal(str(notes["min_participation"])),
        horizon_ns=int(fixed["hold_minutes"]) * 60 * _NS,
    )


def _a08(compression_window_m: float, fixed: Built, notes: Notes, bars: int) -> Any:
    del notes
    return a08.A08Params(
        compression_window_m=int(compression_window_m) * bars,
        compression_percentile_c0=int(fixed["compression_percentile_c0"]),
        expansion_threshold_e0_mad=Decimal(int(fixed["expansion_threshold_e0_mad"])),
        hold_minutes=int(fixed["hold_minutes"]),
        horizon_ns=int(fixed["hold_minutes"]) * 60 * _NS,
    )


DRIVERS: dict[str, AlphaDriver] = {
    "A01": AlphaDriver(
        "A01",
        "A01_residual_momentum.yaml",
        "residual_lookback_m",
        {"scale_window_m": 20, "hold_minutes": 15},
        a01.compute,
        _a01,
    ),
    "A02": AlphaDriver(
        "A02",
        "A02_ts_momentum.yaml",
        "vol_half_life_m",
        {"own_lookbacks_m": 5, "hold_minutes": 30},
        a02.compute,
        _a02,
    ),
    "A03": AlphaDriver(
        "A03",
        "A03_cs_reversal.yaml",
        "shock_window_m",
        {"robust_tail": 1.5, "hold_minutes": 15},
        a03.compute,
        _a03,
    ),
    "A04": AlphaDriver(
        "A04",
        "A04_residual_reversion.yaml",
        "spread_z_window_m",
        {"entry_z": 1.5, "exit_z": 0.0, "hold_minutes": 15},
        a04.compute,
        _a04,
    ),
    "A05": AlphaDriver(
        "A05",
        "A05_gap_continuation.yaml",
        "observe_minutes",
        {"hold_minutes": 30},
        a05.compute,
        _a05,
        # A05 declares `confirmation_thresholds: 'coarse grid, preregistered'` -- prose, not a
        # range -- so its volume and breadth thresholds cannot be checked against anything. That
        # is a gap in the pre-registration, recorded here rather than papered over.
        unchecked={"min_volume_ratio": Decimal("1.2"), "min_breadth": Decimal("0.5")},
    ),
    "A06": AlphaDriver(
        "A06",
        "A06_gap_reversal.yaml",
        # `hold_minutes` [5, 90] is the only declared range that maps to a parameter. The rest
        # are the weak-confirmation grid, which the spec declares as prose -- "separate from
        # A05's, preregistered" -- so they cannot be checked against anything and say so.
        "hold_minutes",
        {},
        _a06_compute,
        _a06,
        unchecked={
            "observe_minutes": 15,
            "max_volume_ratio": Decimal("3"),
            "max_breadth": Decimal("0.9"),
            "max_range_continuation": Decimal("0.9"),
        },
    ),
    "A07": AlphaDriver(
        "A07",
        "A07_opening_range_breakout.yaml",
        # Swept on the ATR buffer, a real [0.0, 1.0] range. `range_end_minutes` is an
        # ENUMERATION [5, 10, 15, 30] and is held fixed at one of its declared choices --
        # membership-checked, not range-checked.
        "volatility_buffer_atr",
        {"range_end_minutes": 15, "hold_minutes": 30},
        a07.compute,
        _a07,
        # A07 declares no domain for min_participation, so it cannot be checked against one.
        unchecked={"min_participation": Decimal("0.1")},
    ),
    "A08": AlphaDriver(
        "A08",
        "A08_compression_expansion.yaml",
        "compression_window_m",
        {"compression_percentile_c0": 20, "expansion_threshold_e0_mad": 2, "hold_minutes": 30},
        a08.compute,
        _a08,
    ),
}

NOT_RUNNABLE: dict[str, str] = {
    # Each reason was established by running the alpha against the fixture panel and reading
    # what it said -- not by inspecting imports and guessing.
    "A12": (
        "declares history_sessions [60, 250] and the fixture panel spans five sessions "
        "(2026-06-01 to 06-05). The seasonal profile needs a year of history to estimate; a "
        "run here would be sweeping a parameter no value of which the data can satisfy."
    ),
}
