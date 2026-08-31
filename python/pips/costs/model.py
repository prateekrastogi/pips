"""The full round-trip cost function  [C-COST-04] (§3.7).

``cost_rt_bps(broker, notional, aggression, symbol, ts, capital_tier)``
``= statutory + brokerage + spread·aggression + impact κ(q/ADV)^ψ + latency + adverse selection``

The first two terms are exact and golden-tested. The rest are estimated, and the structure is
what is pinned rather than the numbers:

* **additive by construction** (reference §10.3) -- a total that is not the sum of its named
  parts cannot be attributed, and attribution is what tells you whether to fix bands, slicing
  or infrastructure;
* **monotone in aggression** -- §10.2 is explicit that the turnover optimiser needs costs to
  *rise* with aggression to have a well-posed interior optimum. Without it S5 would happily
  choose infinite turnover.

Note what is deliberately **absent**: no Corwin-Schultz or other high-low spread estimator.
SAL-0014 is a documented negative result -- on aggregated OHLC it produced a spread an order
of magnitude above the measured anchor, and the donor built a structural scan to keep it out
of the cost path. `tests/unit/costs/test_execution_costs.py` carries that scan forward.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from pips.core.calendar import SessionState
from pips.costs.friction import load_friction
from pips.costs.schedule import CostSchedule
from pips.costs.statutory import Broker, round_trip_cost

__all__ = ["CostBreakdown", "CostContext", "cost_rt_bps"]

_BPS = Decimal("0.001")


@dataclass(frozen=True)
class CostContext:
    """Everything the cost function needs about one round trip."""

    broker: Broker
    notional_paise: int
    aggression: Decimal  # 0 = fully passive, 1 = fully aggressive (crosses the spread)
    participation: Decimal  # q / ADV_interval
    session: SessionState
    trade_date: date


@dataclass(frozen=True)
class CostBreakdown:
    """Round-trip cost in bps, decomposed. The parts sum to the total, exactly."""

    statutory_bps: Decimal
    spread_bps: Decimal
    impact_bps: Decimal
    latency_bps: Decimal
    adverse_selection_bps: Decimal

    @property
    def total_bps(self) -> Decimal:
        return (
            self.statutory_bps
            + self.spread_bps
            + self.impact_bps
            + self.latency_bps
            + self.adverse_selection_bps
        )

    def components(self) -> dict[str, Decimal]:
        return {
            "statutory": self.statutory_bps,
            "spread": self.spread_bps,
            "impact": self.impact_bps,
            "latency": self.latency_bps,
            "adverse_selection": self.adverse_selection_bps,
        }


def _q(value: Decimal) -> Decimal:
    return value.quantize(_BPS, rounding=ROUND_HALF_EVEN)


def cost_rt_bps(
    schedule: CostSchedule,
    friction_path: Path,
    context: CostContext,
    *,
    stress_multiplier: Decimal = Decimal(1),
) -> CostBreakdown:
    """Round-trip cost in basis points of one side's notional.

    ``stress_multiplier`` scales the ESTIMATED terms only (M16 stresses costs x1.5 and x2).
    The statutory stack is exact law and is never stressed -- inflating it would be inventing
    a tax rate, and it would also hide which part of the cost the stress is actually probing.
    """
    if not context.session.tradeable_as_alpha:
        raise ValueError(
            f"{context.session} is not a tradeable session — quoting a cost for it would "
            "imply it is a venue we trade (CAS is disabled by ADR-0004; FLATTEN_ONLY is "
            "exposure-reducing only)"
        )
    if not (0 <= context.aggression <= 1):
        raise ValueError(f"aggression must be in [0, 1], got {context.aggression}")
    if context.participation < 0:
        raise ValueError(f"participation must be non-negative, got {context.participation}")
    if stress_multiplier < 1:
        raise ValueError(
            f"stress multiplier must be >= 1, got {stress_multiplier} — a 'stress' that "
            "lowers the cost is not a stress"
        )

    friction = load_friction(friction_path)

    statutory = round_trip_cost(
        schedule, context.broker, context.notional_paise, context.trade_date
    ).bps

    session_key = context.session.value
    if session_key not in friction.half_spread_bps:
        raise LookupError(f"no half-spread entry for session {session_key}")

    # Two legs, each paying `aggression` of the half spread.
    spread = friction.half_spread_bps[session_key] * context.aggression * 2

    # kappa * (q/ADV)^psi. Decimal has no fractional power, so psi=0.5 is a square root and
    # anything else goes through float and comes back — acceptable because this term is an
    # estimate whose parameters are refit quarterly, and the boundary value is re-quantised.
    if context.participation == 0:
        impact = Decimal(0)
    elif friction.impact.psi == Decimal("0.5"):
        impact = friction.impact.kappa_bps * context.participation.sqrt()
    else:
        impact = friction.impact.kappa_bps * Decimal(
            str(float(context.participation) ** float(friction.impact.psi))
        )

    latency = friction.latency_bps
    adverse = friction.adverse_selection_bps

    return CostBreakdown(
        statutory_bps=_q(statutory),  # never stressed: exact law
        spread_bps=_q(spread * stress_multiplier),
        impact_bps=_q(impact * stress_multiplier),
        latency_bps=_q(latency * stress_multiplier),
        adverse_selection_bps=_q(adverse * stress_multiplier),
    )
