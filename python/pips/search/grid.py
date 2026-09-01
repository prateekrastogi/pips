"""The search grid, derived from the pre-registered parameter domain  (C2, §6 M12).

C2 is explicit: *"Entry thresholds, holding periods, position sizes and rebalance bands are the
argmax of a stated objective under the cost model — never round numbers that felt right."* The
DOMAIN has to be stated too. Every :class:`AlphaSpec` declares ``parameter_domain`` as
``[min, max]`` per parameter, and that declaration is the pre-registration.

A grid hardcoded in a search driver is a sweep over a space nobody registered. Nothing stops it
drifting outside the declared domain, and a sweep outside the pre-registration looks exactly like
a sweep inside it — the results are just as plottable, and the falsifiers were written for the
space that was declared.

**Spacing is geometric.** A lookback of 3 versus 4 differs by a third; 100 versus 101 differs by
one percent. Linear spacing over ``[3, 120]`` puts most of its points where the parameter barely
changes behaviour and never separates 3 from 10. The choice is a choice, so it is stated and
tested rather than left to whichever expression got typed.

**Two units.** The spec declares ``residual_lookback_m`` in MINUTES; ``A01Params.residual_lookback``
counts BARS. They coincide on a one-minute panel and only there — on five-minute bars a declared
15-minute lookback is three bars, and passing 15 would look back 75 minutes: five times the
registered parameter, still inside the declared range as a number and outside it as a duration.
So the conversion is explicit and the interval is checked.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pips.alphas.spec import AlphaSpec

__all__ = ["assert_within_domain", "bars_per_unit", "grid_from_domain"]

_MINUTE_NS = 60 * 1_000_000_000


def grid_from_domain(spec: AlphaSpec, parameter: str, *, count: int) -> tuple[int, ...]:
    """``count`` geometrically spaced integers spanning the spec's declared range, inclusive."""
    if count < 2:
        raise ValueError(
            f"a grid needs at least 2 points, got {count}. One point is not a search; it is a "
            "hardcoded value wearing a grid's clothes."
        )
    if parameter not in spec.parameter_domain:
        raise KeyError(
            f"spec {spec.id} does not declare a domain for {parameter!r} (it declares "
            f"{sorted(spec.parameter_domain)}). Refusing to invent one: a parameter absent from "
            "the pre-registration is a parameter the spec never bounded, and sweeping it would "
            "look exactly like sweeping a registered space."
        )

    low, high = (int(v) for v in spec.parameter_domain[parameter])
    if low > high:
        raise ValueError(f"{parameter} domain [{low}, {high}] is inverted")
    if low <= 0:
        # Geometric spacing is undefined through zero, so a domain touching it is walked
        # linearly. Stated rather than silently shifted by one, which would put the grid
        # outside the declared range at the bottom end.
        step = (high - low) / (count - 1)
        values = [round(low + i * step) for i in range(count)]
    else:
        ratio = (high / low) ** (1 / (count - 1))
        values = [round(low * ratio**i) for i in range(count)]

    # Deduplicated, so a narrow integer domain yields FEWER points rather than repeats: a
    # repeated point would make the search report more trials than parameters and inflate the
    # multiplicity denominator with duplicates.
    #
    # NOT clamped to [low, high]. Both spacings land exactly on the endpoints by construction,
    # so a clamp is unreachable — and if the arithmetic ever stopped doing that, clamping would
    # quietly produce a grid that looks right. The invariant is held by the test that every
    # point lies inside the declared domain, where a violation is visible.
    return tuple(sorted(set(values)))


def bars_per_unit(bar_interval_ns: int) -> int:
    """How many bars a spec's one-minute unit spans. 1 on a minute panel, 5 on five-minute bars.

    Refuses an interval that does not divide a minute: the spec's ``_m`` parameters cannot be
    expressed in whole bars there, and rounding would move the swept parameter off the declared
    domain in duration while leaving it on it in number.
    """
    if bar_interval_ns <= 0:
        raise ValueError(f"bar interval must be positive, got {bar_interval_ns}")
    if bar_interval_ns % _MINUTE_NS and _MINUTE_NS % bar_interval_ns:
        raise ValueError(
            f"bar interval {bar_interval_ns}ns is not a whole number of minutes and does not "
            "divide one. A spec's `_m` parameters cannot be expressed in whole bars here."
        )
    return max(1, bar_interval_ns // _MINUTE_NS)


def assert_within_domain(spec: AlphaSpec, values: Mapping[str, float]) -> None:
    """Refuse any value outside the spec's pre-registered range for that parameter.

    :func:`grid_from_domain` keeps the SWEPT parameter inside the domain. The parameters held
    FIXED during a sweep are just as capable of sitting outside it, and nothing was checking
    them — which is how A01 came to be evaluated at a one-minute horizon against a declared
    ``horizon_minutes: [15, 120]``.

    The message names the declared range, because the value the reader needs is the one the
    error already knows.
    """
    for name, value in values.items():
        if name not in spec.parameter_domain:
            raise KeyError(
                f"spec {spec.id} does not declare a domain for {name!r} (it declares "
                f"{sorted(spec.parameter_domain)})"
            )
        low, high = spec.parameter_domain[name]
        if not low <= value <= high:
            raise ValueError(
                f"{spec.id}: {name}={value} is outside the pre-registered domain "
                f"[{low}, {high}]. The falsifiers attached to this spec were written for the "
                "declared space, so a run outside it cannot be rejected by them — and it looks "
                "exactly like a run inside it."
            )
