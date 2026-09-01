"""Turnover calculus: the Faustmann hold h* and the selectivity threshold tau*  (§6 M19).

From Quantitative Foundations §6.1-§6.2. Both are C2 rules — "every rule is an optimum", the
argmax of a stated objective under the MEASURED cost line, never a round number that felt right.

**§6.1 — how long to hold.** Rotating capital repeatedly, value accrues at rate
``rho(h) = (alpha(h) - c) / h``. Setting ``rho'(h) = 0``::

    rho'(h) = [alpha'(h)*h - (alpha(h) - c)] / h^2 = 0
    =>  alpha'(h*) = (alpha(h*) - c) / h* = rho(h*)

Extend the hold until the marginal rate of edge accrual falls to the average net rate — the
Faustmann rotation condition from renewable-resource economics, transplanted intact. For the
empirically typical concave family ``alpha(h) = a*h^gamma``, ``0 < gamma < 1``::

    h* = [c / (a(1-gamma))]^(1/gamma)   alpha(h*) = c/(1-gamma)   net edge = c*gamma/(1-gamma)

At ``gamma = 1/2`` gross edge at the optimum is exactly ``2c`` — the screening heuristic.

**§6.2 — what to enter.** With opportunities at conditional edge ``g`` and density ``n(g)``,
``dPi/dtau = -(tau - c)*n(tau)``, so ``tau* = c`` risk-neutral and ``tau* = c + lambda*sigma``
risk-adjusted: the marginal admitted trade breaks even against the all-in cost line. ``lambda``
is the Lagrange multiplier on the vol-target constraint (§5.1), NOT a free mood parameter, so a
negative one — which would admit trades below cost — is refused.

**Turnover is an OUTPUT.** ``T* = integral_{tau*}^inf n(g) dg * ticket / capital`` falls out of
the threshold. There is deliberately no ``threshold_for_turnover``: that inversion is "pick the
selectivity that hits the turnover we wanted", which is the reasoning §6.2 exists to refuse. A
test asserts no such function exists for a caller to find.

**Why per broker x tier.** ``c`` differs by both, and ``h*`` scales as ``(c/a)^(1/gamma)`` — so
using one broker's cost line for another is not a small error, it is a superlinear one.

The two conditions interact through ``alpha(h)`` and are solved jointly by coordinate descent in
§6.3; that fixed point is not implemented here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

__all__ = [
    "CostLine",
    "TurnoverPlan",
    "optimal_hold",
    "optimal_hold_power_law",
    "optimal_threshold",
    "optimal_turnover",
    "plan_per_broker_tier",
    "rotation_residual",
]

_INV_PHI = (math.sqrt(5.0) - 1.0) / 2.0
_MAX_ITER = 500
_EDGE_FRACTION = 1e-6
"""How close to a bracket endpoint counts as being AT it."""


@dataclass(frozen=True)
class CostLine:
    """The all-in cost per round trip, and optionally what it is made of.

    The breakdown is validated against the headline because a breakdown that DISAGREES with the
    total is worse than none at all: it is checkable and wrong, so it gets checked once,
    believed, and reused. Cost is the single input that decides both rules (§4: costs are
    effective-dated data, not assumptions).
    """

    total: float
    components: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.components:
            summed = sum(self.components.values())
            if not math.isclose(summed, self.total, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(
                    f"cost components sum to {summed!r} but the total is {self.total!r}. A "
                    "breakdown that disagrees with its headline is checkable and wrong."
                )


def _require_cost(cost: float) -> None:
    if not math.isfinite(cost) or cost <= 0:
        raise ValueError(
            f"the cost line must be positive and finite, got {cost!r}. Zero drives h* to zero — "
            "trade infinitely fast, infinitely often. Costs are effective-dated DATA (§4), and "
            "a zero cost line is a missing measurement wearing the shape of a favourable one."
        )


def optimal_hold_power_law(*, a: float, gamma: float, cost: float) -> float:
    """``h* = [c / (a(1-gamma))]^(1/gamma)`` for ``alpha(h) = a*h^gamma``."""
    _require_cost(cost)
    if not 0.0 < gamma < 1.0:
        raise ValueError(
            f"gamma={gamma!r} is outside (0, 1), where alpha(h) is concave and an optimum "
            "exists. At gamma >= 1 edge accrues at least linearly forever and the right answer "
            "is 'hold forever'; the closed form still evaluates — dividing by zero at gamma=1 "
            "and returning a positive-looking number above it — so it would recommend a finite "
            "hold that is the argmax of nothing."
        )
    if not math.isfinite(a) or a <= 0:
        raise ValueError(f"the edge scale `a` must be positive and finite, got {a!r}")
    return float((cost / (a * (1.0 - gamma))) ** (1.0 / gamma))


def rotation_residual(alpha: Callable[[float], float], h: float, cost: float) -> float:
    """``alpha'(h) - (alpha(h) - c)/h``. Zero exactly at the Faustmann optimum."""
    step = h * 1e-6
    derivative = (alpha(h + step) - alpha(h - step)) / (2.0 * step)
    return derivative - (alpha(h) - cost) / h


def optimal_hold(
    alpha: Callable[[float], float],
    cost: float,
    *,
    bracket: tuple[float, float],
    tol: float = 1e-10,
) -> float:
    """Maximise ``rho(h) = (alpha(h) - c)/h`` on ``bracket`` by golden-section search.

    Golden section rather than a root-find on ``rho'``: real ``alpha(h)`` is read off a measured
    IC-decay curve, so its derivative is a finite difference of noisy data. The doc states each
    subproblem is unimodal on the estimated curves, which is exactly what golden section needs,
    and it is deterministic to the last bit on every machine (rule 1).
    """
    _require_cost(cost)
    lo, hi = bracket
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo <= 0 or hi <= lo:
        raise ValueError(f"bracket must be 0 < lo < hi, got {bracket!r}")

    def rho(h: float) -> float:
        return (alpha(h) - cost) / h

    span = hi - lo
    a, b = lo, hi
    c = b - _INV_PHI * (b - a)
    d = a + _INV_PHI * (b - a)
    fc, fd = rho(c), rho(d)
    # Bounded, not `while abs(b - a) > tol`: an alpha that returns NaN would make every
    # comparison false and spin forever, and a stall reports nothing at all.
    for _ in range(_MAX_ITER):
        if abs(b - a) <= tol * span:
            break
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - _INV_PHI * (b - a)
            fc = rho(c)
        else:
            a, c, fc = c, d, fd
            d = a + _INV_PHI * (b - a)
            fd = rho(d)
    best = (a + b) / 2.0

    if rho(best) <= 0:
        raise ValueError(
            "this edge curve never clears costs on the bracket: every holding period loses "
            "money. Refusing rather than returning the least-bad one — the argmax of a "
            "negative accrual rate is a real number and it is not an answer to how long to hold."
        )
    if best - lo <= span * _EDGE_FRACTION or hi - best <= span * _EDGE_FRACTION:
        raise ValueError(
            f"the optimum sits at a bracket endpoint ({best!r} in {bracket!r}), so the bracket "
            "does not contain it. Returning the endpoint would report a boundary as an optimum."
        )
    return best


def optimal_threshold(cost: CostLine, *, lam: float, sigma_trade: float) -> float:
    """``tau* = c + lambda*sigma_trade``; ``lambda = 0`` gives the risk-neutral ``tau* = c``."""
    _require_cost(cost.total)
    if not math.isfinite(lam) or lam < 0:
        raise ValueError(
            f"lambda={lam!r} must be non-negative. It is the Lagrange multiplier on the "
            "vol-target constraint (§5.1), not a free mood parameter; a negative one admits "
            "trades BELOW the cost line, which is being paid to take variance."
        )
    if not math.isfinite(sigma_trade) or sigma_trade < 0:
        raise ValueError(f"sigma_trade={sigma_trade!r} must be non-negative")
    return cost.total + lam * sigma_trade


def optimal_turnover(
    density: Mapping[float, float], threshold: float, *, ticket: float, capital: float
) -> float:
    """``T* = (opportunities per day at edge >= tau) * ticket / capital``. An output.

    Note what is NOT here: no way to name a turnover and be handed the threshold that produces
    it. Turnover is what the selectivity implies, and the inversion is the error the section
    was written to prevent.
    """
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError(f"capital must be positive, got {capital!r}")
    if not math.isfinite(ticket) or ticket <= 0:
        raise ValueError(f"the average ticket must be positive, got {ticket!r}")
    admitted = sum(n for edge, n in density.items() if edge >= threshold)
    return admitted * ticket / capital


@dataclass(frozen=True)
class TurnoverPlan:
    """One broker x tier's rule: how selective, how long, and the turnover that implies."""

    broker: str
    tier: str
    cost: CostLine
    hold: float
    threshold: float
    turnover: float

    @property
    def admits_nothing(self) -> bool:
        """True when no opportunity in the density clears this broker's threshold.

        Reported rather than filtered out: a broker whose economics admit nothing is a finding
        about that broker, and dropping it leaves a caller comparing two where three were
        priced — missing exactly the one that failed.
        """
        return self.turnover == 0.0


def plan_per_broker_tier(
    cost_lines: Mapping[tuple[str, str], CostLine],
    *,
    a: float,
    gamma: float,
    fitted_horizon: float,
    lam: float,
    sigma_trade: float,
    density: Mapping[float, float],
    ticket: float,
    capital: float,
) -> tuple[TurnoverPlan, ...]:
    """tau* and h* for each (broker, tier). The cost line differs, so the whole rule differs.

    ``fitted_horizon`` is REQUIRED and has no default. ``alpha(h) = a*h^gamma`` grows without
    bound, so the closed form always finds a profitable-looking optimum — including at holding
    periods far past anything the curve was measured over. Real IC-decay curves saturate; a
    power law fitted to the first 60 minutes says nothing about 400. An optimum outside the
    fitted range is refused rather than reported, because nothing distinguishes it in the
    output from one the data supports.
    """
    if not cost_lines:
        raise ValueError(
            "no cost line supplied: tau* and h* are per broker x tier, and both "
            "are functions of c, so there is nothing to solve without one"
        )
    if not math.isfinite(fitted_horizon) or fitted_horizon <= 0:
        raise ValueError(f"fitted_horizon must be positive and finite, got {fitted_horizon!r}")

    plans: list[TurnoverPlan] = []
    # Sorted, not input order: a plan set is compared across runs and across brokers, so its
    # order must not depend on how the caller happened to build the mapping (rule 1).
    for (broker, tier), cost in sorted(cost_lines.items()):
        hold = optimal_hold_power_law(a=a, gamma=gamma, cost=cost.total)
        if hold > fitted_horizon:
            raise ValueError(
                f"{broker}/{tier}: h* = {hold:.1f} lies beyond the fitted horizon "
                f"{fitted_horizon:.1f}. alpha(h) was never measured there, so this optimum is "
                "an extrapolation of the power law rather than a reading of the curve — and "
                "nothing in the number says so."
            )
        threshold = optimal_threshold(cost, lam=lam, sigma_trade=sigma_trade)
        plans.append(
            TurnoverPlan(
                broker=broker,
                tier=tier,
                cost=cost,
                hold=hold,
                threshold=threshold,
                turnover=optimal_turnover(density, threshold, ticket=ticket, capital=capital),
            )
        )
    return tuple(plans)
