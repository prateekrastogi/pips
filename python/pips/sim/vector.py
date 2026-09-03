"""Vectorized screening engine, F0 tier  (§6 M10, §3.8).

F0 is deliberately crude -- next-bar return minus a rough cost -- and permitted for *feature
triage only*. What is exact even here is the **accounting**: every quantity is integer paise,
and ``pnl_gross - costs == pnl_net`` holds identically rather than to a tolerance (§7 asserts
it continuously).

**THE COST HERE UNDERSTATES, and this docstring used to call it "conservative".** What is
charged is `round_trip_cost` -- the statutory stack plus brokerage -- and nothing else: no
half-spread, no impact, no latency, no adverse selection. Those are multiples of the statutory
line, and `config/costs/execution_friction.yaml` is explicit that conservatism runs the other
way: "An overstated cost kills a live edge, which costs opportunity. An understated cost makes
a DEAD edge look alive, which costs capital and is the single most expensive error this project
can make."

So F0 errs toward KEEPING features, not killing them, which is a defensible thing for a triage
tier to do and the opposite of what the old wording promised. `[C-FILL-01]` is what stops the
number travelling: every result is stamped with its tier and cross-tier comparison is refused,
so an F0 figure cannot be presented as a net return. A reader told the cost was conservative
would have believed the safe direction was already covered.

Two design choices carry weight:

* **The signal is handed an** :class:`~pips.core.asof.AsOfPanelView`, never the raw panel. A
  signal that reaches forward dies where signals actually run, not in a review. The leakage
  canary proves the guard works; this is what makes the guard unavoidable.
* **Positions are flattened every day.** pips is intraday (§3.14 has an independent flatten
  scheduler and treats broker auto-square-off as a failure path), so a day is a round trip and
  is costed as one. Carrying a position overnight in a screen would understate cost and quietly
  change the strategy being screened.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

import polars as pl

from pips.core.asof import AsOfPanelView
from pips.costs.schedule import CostSchedule
from pips.costs.statutory import Broker, round_trip_cost

__all__ = [
    "FillTier",
    "ScreenResult",
    "SignalFn",
    "forward_returns",
    "long_flat",
    "run_screen",
    "tolerance_neutral",
    "top_k",
]

Scores = Mapping[str, Decimal]
Weights = dict[str, Decimal]
SignalFn = Callable[[AsOfPanelView, list[str]], Scores]
WrapperFn = Callable[[Scores], Weights]


class FillTier(StrEnum):
    """Fill-fidelity tiers (§3.8). Each declares what it may be used for."""

    F0 = "F0"
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"

    @property
    def permits(self) -> str:
        return {
            "F0": "feature triage only (S1)",
            "F1": "T1 candidate comparison (S2+)",
            "F2": "T2 certification",
            "F3": "T3 only",
        }[self.value]


@dataclass(frozen=True)
class ScreenResult:
    """A screening run's outcome, in integer paise, stamped with its tier."""

    fill_tier: FillTier
    gross_pnl_paise: int
    net_pnl_paise: int
    cost_paise: int
    n_round_trips: int

    def compare_to(self, other: ScreenResult) -> int:
        """Order two results by net P&L. Refuses a cross-tier comparison (§3.8).

        An F0 screen number and an F2 certification number are not the same quantity, and
        comparing them silently is how a triage result becomes a claim.
        """
        if self.fill_tier is not other.fill_tier:
            raise ValueError(
                f"cross-tier comparison refused: {self.fill_tier} ({self.fill_tier.permits}) "
                f"vs {other.fill_tier} ({other.fill_tier.permits}) — these are different "
                "quantities, not different values of one quantity (§3.8)"
            )
        return (self.net_pnl_paise > other.net_pnl_paise) - (
            self.net_pnl_paise < other.net_pnl_paise
        )


# ------------------------------------------------------------------ labels --------------


def forward_returns(panel: pl.DataFrame, symbol: str) -> list[Decimal | None]:
    """Next-bar return per bar for ``symbol``; ``None`` for the final bar.

    This is the **label**, not a feature. It is legitimately a look at the future because it
    is what a signal is scored *against* -- and it is exactly why a signal must never be able
    to read it, which the as-of view enforces.
    """
    closes = panel.filter(pl.col("symbol") == symbol).sort("close_ts_ns")["close_paise"].to_list()
    out: list[Decimal | None] = []
    for i, close in enumerate(closes):
        if i + 1 >= len(closes) or close == 0:
            out.append(None)
        else:
            out.append(Decimal(closes[i + 1] - close) / Decimal(close))
    return out


# ----------------------------------------------------- portfolio wrappers ---------------


def top_k(scores: Scores, k: int) -> Weights:
    """Equal weight across the ``k`` highest scores. Ties break by symbol (§3.11)."""
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    if k > len(scores):
        raise ValueError(f"k={k} exceeds the universe of {len(scores)} names")
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    chosen = {name for name, _ in ranked[:k]}
    weight = Decimal(1) / Decimal(k)
    return {name: (weight if name in chosen else Decimal(0)) for name in scores}


def long_flat(scores: Scores, threshold: Decimal) -> Weights:
    """Equal weight across names above ``threshold``; flat otherwise. Never short."""
    selected = [name for name, score in scores.items() if score > threshold]
    if not selected:
        return dict.fromkeys(scores, Decimal(0))
    weight = Decimal(1) / Decimal(len(selected))
    return {name: (weight if name in selected else Decimal(0)) for name in scores}


def tolerance_neutral(scores: Scores, tolerance: Decimal) -> Weights:
    """Long the top half, short the bottom half, net exposure within ``tolerance``.

    Deliberately a *band*, not exact neutrality: §7's rejection list names "exact neutrality
    regardless of ticket economics", because trading to remove an imbalance that costs more
    than it is worth is a cost with no corresponding benefit.
    """
    if tolerance < 0:
        raise ValueError(f"tolerance must be non-negative, got {tolerance}")
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    half = len(ranked) // 2
    if half == 0:
        return dict.fromkeys(scores, Decimal(0))
    longs = {name for name, _ in ranked[:half]}
    shorts = {name for name, _ in ranked[-half:]}
    weight = Decimal(1) / Decimal(2 * half)
    weights = {
        name: (weight if name in longs else (-weight if name in shorts else Decimal(0)))
        for name in scores
    }
    net = sum(weights.values(), Decimal(0))
    if abs(net) > tolerance:
        # Shave the imbalance off the largest leg rather than rescaling everything, so the
        # relative sizing the signal asked for survives.
        adjust = net - (tolerance if net > 0 else -tolerance)
        target = max(weights, key=lambda n: abs(weights[n]))
        weights[target] -= adjust
    return weights


# ------------------------------------------------------------------ the engine ----------


def _to_paise(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def run_screen(
    panel: pl.DataFrame,
    signal: SignalFn,
    wrapper: WrapperFn,
    capital_paise: int,
    schedule: CostSchedule,
    broker: Broker,
) -> ScreenResult:
    """Run an F0 screen over ``panel``.

    For each bar except the last: build an as-of view at that bar, ask the signal for scores,
    turn them into weights, earn the next-bar return on the weighted notional, and pay one
    round trip on every notional actually held (intraday flatten, §3.14).
    """
    if capital_paise <= 0:
        raise ValueError(f"capital must be positive, got {capital_paise}")

    bars = sorted(set(panel["close_ts_ns"].to_list()))
    symbols = sorted(set(panel["symbol"].to_list()))
    returns = {s: forward_returns(panel, s) for s in symbols}

    gross = Decimal(0)
    cost = Decimal(0)
    round_trips = 0

    for i, bar_ts in enumerate(bars[:-1]):
        view = AsOfPanelView(panel, decision_ts=bar_ts)
        weights = wrapper(signal(view, symbols))

        for symbol, weight in weights.items():
            if weight == 0:
                continue
            forward = returns[symbol][i]
            if forward is None:
                continue
            notional = Decimal(capital_paise) * abs(weight)
            gross += Decimal(capital_paise) * weight * forward
            # One round trip per name per day: entered and flattened the same session.
            cost += Decimal(
                round_trip_cost(
                    schedule, broker, _to_paise(notional), _bar_date(panel, bar_ts)
                ).total_paise
            )
            round_trips += 1

    gross_paise = _to_paise(gross)
    cost_paise = _to_paise(cost)
    return ScreenResult(
        fill_tier=FillTier.F0,
        gross_pnl_paise=gross_paise,
        cost_paise=cost_paise,
        # Subtracted, never recomputed: the identity pnl_gross - costs == pnl_net holds by
        # construction rather than to a tolerance (§7).
        net_pnl_paise=gross_paise - cost_paise,
        n_round_trips=round_trips,
    )


def _bar_date(panel: pl.DataFrame, bar_ts: int) -> date:
    """The trading date of a bar, for the effective-dated cost schedule."""
    value = panel.filter(pl.col("close_ts_ns") == bar_ts)["day"][0]
    return value if isinstance(value, date) else date.fromisoformat(str(value))
