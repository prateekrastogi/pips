"""A06 -- opening-gap reversal (T1).

The mirror claim to A05, and pre-registered separately for exactly that reason. §5 F5:
*continue/fade separate, never chosen ex post.* A06's first falsifier is "reject if
continuation and reversal rules are selected ex post by realized sign", so the two gates are
independent conditions rather than one condition and its negation — a name can fail both and be
flat in both, which a partition by sign could never produce.

**The event gate is mandatory and it is tri-state.** The spec's `no_event_flag` node:
*"missing event metadata => EXCLUDE the name, never assume no event."* A boolean cannot carry
that — with two states, an empty corporate-action master and a market with no events give the
identical answer, and the alpha fades a name through an unknown as if it were a known quiet.
So the default is ``UNKNOWN``, ``UNKNOWN`` excludes, and **with no event source wired A06
forecasts nothing at all**. That is the conservative direction the spec's deferred falsifier
names, made visible rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.alphas.t1._common import (
    EventStatus,
    EventStatusSource,
    build_forecast,
    idiosyncratic_gaps,
    opening_volume_ratio,
    peer_breadth,
    prior_day_sigma,
    range_continuation,
    session_gaps,
    sessions_by_symbol,
)
from pips.core.asof import AsOfPanelView

__all__ = ["A06Params", "compute"]


@dataclass(frozen=True)
class A06Params:
    """A point in the spec's bounded domain.

    The thresholds are SEPARATE from A05's by construction, not by convention: the spec says
    *"the weak-confirmation grid is SEPARATE from A05's confirmation grid and fixed before the
    search"*, and sharing one parameter object would make the two alphas a partition of a
    single grid.
    """

    observe_minutes: int
    hold_minutes: int
    max_volume_ratio: Decimal
    max_breadth: Decimal
    max_range_continuation: Decimal
    horizon_ns: int

    def __post_init__(self) -> None:
        if not 5 <= self.observe_minutes <= 30:
            raise ValueError(f"observe_minutes {self.observe_minutes} is outside [5, 30]")
        if not 5 <= self.hold_minutes <= 90:
            raise ValueError(
                f"hold_minutes {self.hold_minutes} is outside A06's pre-registered [5, 90] — "
                "note this is NOT A05's [5, 120]; the two domains are separate on purpose"
            )


def compute(
    view: AsOfPanelView,
    params: A06Params,
    spec: AlphaSpec,
    event_status: EventStatusSource | None = None,
) -> list[Forecast]:
    """Weak-confirmation gap fade, excluding any name whose event status is not CLEAR."""
    sessions = sessions_by_symbol(view)
    gaps = session_gaps(sessions)
    idio = idiosyncratic_gaps(gaps, sessions)

    forecasts: list[Forecast] = []
    for symbol in sorted(idio):
        status = EventStatus.UNKNOWN if event_status is None else event_status(symbol)
        if (status or EventStatus.UNKNOWN) is not EventStatus.CLEAR:
            # EXCLUDED, and excluded is not flat: a flagged or unknown name gets no forecast
            # at all, so nothing downstream can read a zero here as "measured, no position".
            continue

        volume_ratio = opening_volume_ratio(sessions[symbol])
        breadth = peer_breadth(symbol, gaps)
        if volume_ratio is None or breadth is None:
            # "any input missing => no weak-confirmation call, not a default one"
            continue

        sigma = prior_day_sigma(sessions[symbol])
        continuation = range_continuation(sessions[symbol], idio[symbol], sigma)
        weak = (
            volume_ratio <= params.max_volume_ratio
            and breadth <= params.max_breadth
            and continuation <= params.max_range_continuation
        )
        score = -idio[symbol] if weak else Decimal(0)
        forecasts.append(build_forecast(spec, symbol, score, view, params.horizon_ns))
    return forecasts
