"""Order-budget constraints  (§6 M19; blueprint §3.3-§3.4 and §12).

The blueprint states the purpose exactly: *"order budget respected as an optimizer constraint,
so research never certifies a strategy the engine may not legally run."* The constraint belongs
in SELECTION and not only in the engine — a strategy that clears every statistical gate and then
cannot be run is a strategy that wasted the gates.

Three limits, and they are not interchangeable:

* **5 orders/second globally** — the engine's governor, deliberately half of SEBI's ~10/s
  threshold for the registration-free retail route (Feb 2025 circular, enforced from
  2026-04-01).
* **2 orders/second per symbol** — a separate throttle. Satisfying the global does not imply it,
  and three symbols each sitting exactly at 2/s already breach the global 5.
* **a daily cap** — the broker's, and a different dimension from any rate: one order per second
  all day never approaches 5/s and still blows through ~3000.

**The binding constraint is the governor, not the legal threshold.** A strategy at 7 orders/s is
legal and still inadmissible, because the governor throttles it — and the throttled strategy is
not the one that was validated. Certifying it certifies a backtest of something the plant will
never run.

**The window slides.** Fixed one-second buckets hide exactly the bursts this exists to catch:
five orders at 0.9s and five at 1.1s bucket as 5 and 5, both inside the cap, and are ten orders
in 200ms. Note this is the OPPOSITE choice from :mod:`pips.selection.netting`, deliberately —
there, fixed buckets understate crossing, which charges the ensemble for a saving it might have
had, the conservative direction. Here, fixed buckets understate the peak, which hides a
violation. The same-looking question has different safe answers depending on which way the
error flatters.

**Every order event counts, not every fill.** The protected-limit machine (M14) reprices, so one
intent becomes several events. Counting fills, or counting intents, understates the rate by
whatever the reprice multiplier happens to be — and understates it in the direction that admits
the strategy.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "NSE_RETAIL_BUDGET",
    "Breach",
    "BudgetVerdict",
    "OrderBudget",
    "OrderEvent",
    "OrderKind",
    "check_order_budget",
]

_ONE_SECOND_NS = 1_000_000_000


class OrderKind(enum.Enum):
    NEW = "new"
    MODIFY = "modify"
    CANCEL = "cancel"


@dataclass(frozen=True)
class OrderEvent:
    """One message to the broker. A modify and a cancel are orders, the same as a new one."""

    ts_ns: int
    symbol: str
    kind: OrderKind = OrderKind.NEW


@dataclass(frozen=True)
class OrderBudget:
    global_per_second: int
    per_symbol_per_second: int
    daily_cap: int
    legal_per_second: int
    """SEBI's registration-free threshold. Reported for context; never the binding constraint."""

    def __post_init__(self) -> None:
        if self.global_per_second > self.legal_per_second:
            raise ValueError(
                f"global_per_second={self.global_per_second} exceeds the legal threshold "
                f"{self.legal_per_second}. The governor exists to sit UNDER that threshold; a "
                "budget above it would let selection certify a strategy whose order rate "
                "requires exchange registration this project does not have."
            )
        if self.per_symbol_per_second > self.global_per_second:
            raise ValueError(
                f"per-symbol throttle {self.per_symbol_per_second} exceeds the global "
                f"{self.global_per_second}, so it could never bind — declaring it suggests a "
                "protection that does not exist."
            )
        if min(self.global_per_second, self.per_symbol_per_second, self.daily_cap) <= 0:
            raise ValueError("every limit must be positive")


NSE_RETAIL_BUDGET = OrderBudget(
    # §12: "Global order-rate governor capped at 5 orders/second (half the threshold),
    # per-symbol throttle 2/s." The daily cap is the broker's (~3k) and is flagged in the
    # blueprint as "verify current" -- it is a number to confirm at onboarding, not a constant
    # to trust.
    global_per_second=5,
    per_symbol_per_second=2,
    daily_cap=3000,
    legal_per_second=10,
)


@dataclass(frozen=True)
class Breach:
    limit: str
    allowed: int
    observed: int
    at_ns: int
    symbol: str | None = None


@dataclass(frozen=True)
class BudgetVerdict:
    breaches: tuple[Breach, ...]
    peak_global_per_second: int
    peak_per_symbol: dict[str, int]
    total_orders: int

    @property
    def admissible(self) -> bool:
        """Derived from the breach list, never set independently.

        A field that can be assigned separately is a field that can say "fine" when nothing was
        evaluated, which is how NOT_RUN becomes PASSED.
        """
        return not self.breaches


def _peak_in_window(timestamps: Sequence[int]) -> tuple[int, int]:
    """Largest count in any 1-second SLIDING window, and where it starts.

    Two pointers over sorted stamps: the window anchored at each event, since a maximum can
    always be shifted left to start on one.
    """
    if not timestamps:
        return 0, 0
    best = 0
    best_at = timestamps[0]
    left = 0
    for right, stamp in enumerate(timestamps):
        while stamp - timestamps[left] >= _ONE_SECOND_NS:
            left += 1
        count = right - left + 1
        if count > best:
            best, best_at = count, timestamps[left]
    return best, best_at


def check_order_budget(events: Sequence[OrderEvent], budget: OrderBudget) -> BudgetVerdict:
    """Measure a candidate's order traffic against the governor, the throttle and the cap."""
    ordered = sorted(events, key=lambda e: (e.ts_ns, e.symbol, e.kind.value))
    stamps = [e.ts_ns for e in ordered]
    by_symbol: dict[str, list[int]] = {}
    for event in ordered:
        by_symbol.setdefault(event.symbol, []).append(event.ts_ns)

    breaches: list[Breach] = []
    peak_global, at_global = _peak_in_window(stamps)
    if peak_global > budget.global_per_second:
        breaches.append(
            Breach("global orders/second", budget.global_per_second, peak_global, at_global)
        )

    peak_per_symbol: dict[str, int] = {}
    for symbol, symbol_stamps in sorted(by_symbol.items()):
        peak, at = _peak_in_window(symbol_stamps)
        peak_per_symbol[symbol] = peak
        if peak > budget.per_symbol_per_second:
            breaches.append(
                Breach("per-symbol orders/second", budget.per_symbol_per_second, peak, at, symbol)
            )

    if len(ordered) > budget.daily_cap:
        breaches.append(
            Breach("daily order cap", budget.daily_cap, len(ordered), stamps[0] if stamps else 0)
        )

    return BudgetVerdict(
        breaches=tuple(breaches),
        peak_global_per_second=peak_global,
        peak_per_symbol=peak_per_symbol,
        total_orders=len(ordered),
    )
