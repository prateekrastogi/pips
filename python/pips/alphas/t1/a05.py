"""A05 -- opening-gap continuation (T1).

The claim: a large IDIOSYNCRATIC overnight gap, confirmed at the open by volume and by peer
breadth, is incorporated gradually rather than instantly.

Three things in the spec do real work here and are implemented as written rather than as
convenient:

**Unconfirmed is flat, not reversed.** The spec's `continuation_score` node says
*"unconfirmed => flat, not a reversed position"*. Flat and reversed are opposite trades, and
defaulting to the second would silently turn A05 into A06.

**Flat is reported; uncomputable is not.** A name with no prior session yields NO forecast,
while a name that was measured and found unconfirmed yields a forecast scoring zero. Collapsing
those two into "emit nothing" would lose the difference between *we looked and the answer is no
position* and *we could not look* — a distinction this project keeps having to re-establish.

**The gap is measured to the first bar's close.** A05's own falsifier is *"reject if the result
depends on the first untradeable print"*, so building the alpha on the opening auction price
would be constructing exactly what the falsifier distrusts. See ``session_gaps``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.alphas.t1._common import (
    build_forecast,
    idiosyncratic_gaps,
    opening_volume_ratio,
    peer_breadth,
    session_gaps,
    sessions_by_symbol,
)
from pips.core.asof import AsOfPanelView

__all__ = ["A05Params", "compute"]


@dataclass(frozen=True)
class A05Params:
    """A point in the spec's bounded domain."""

    observe_minutes: int
    hold_minutes: int
    min_volume_ratio: Decimal
    min_breadth: Decimal
    horizon_ns: int

    def __post_init__(self) -> None:
        if not 5 <= self.observe_minutes <= 30:
            raise ValueError(
                f"observe_minutes {self.observe_minutes} is outside the pre-registered "
                "domain [5, 30] (§3.2) — widening the domain during a search is the search"
            )
        if not 5 <= self.hold_minutes <= 120:
            raise ValueError(f"hold_minutes {self.hold_minutes} is outside [5, 120]")


def compute(view: AsOfPanelView, params: A05Params, spec: AlphaSpec) -> list[Forecast]:
    """Confirmation-gated idiosyncratic gap continuation. Pure and deterministic."""
    sessions = sessions_by_symbol(view)
    gaps = session_gaps(sessions)
    idio = idiosyncratic_gaps(gaps, sessions)

    forecasts: list[Forecast] = []
    for symbol in sorted(idio):
        volume_ratio = opening_volume_ratio(sessions[symbol])
        breadth = peer_breadth(symbol, gaps)
        if volume_ratio is None or breadth is None:
            # An input the spec requires is missing. The `opening_confirmation` node says
            # "insufficient observation window => no forecast" — not an unconfirmed one,
            # which would be a measured claim we did not measure.
            continue
        confirmed = volume_ratio >= params.min_volume_ratio and breadth >= params.min_breadth
        score = idio[symbol] if confirmed else Decimal(0)
        forecasts.append(build_forecast(spec, symbol, score, view, params.horizon_ns))
    return forecasts
