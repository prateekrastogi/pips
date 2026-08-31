"""A12 -- intraday seasonal residual (T1).

The most seductive of the nine, and its own fit protocol says why: *"Slot means are never
reported unshrunk — an unshrunk slot mean over few sessions is the artefact this alpha must not
become."* Its declared null model IS that artefact.

Slice any return series by clock slot and some slot will have a large mean. That is what finite
samples do, and it happens in data with no schedule in it at all. Report it raw and the alpha
is a machine for finding noise and calling it an institutional cycle. The hypothesis is equally
careful: *"an isolated slot spike is the NULL this must be distinguished from, not evidence for
it."*

So the shrinkage is not a refinement applied to the estimate — it IS the estimate. What is
reported is an empirical-Bayes posterior: the slot's own mean pulled toward the name's overall
mean by an amount fitted from the data, so a slot with few or noisy sessions barely moves off
its parent while one with many consistent sessions earns most of its own signal.

**The hierarchy is two levels, not three.** The spec asks for stock -> sector -> slot; pips has
no sector map until M6's masters carry one, so the middle level is absent and this says so
rather than implying the fuller model — the same disclosure ``cross_sectional_residuals`` makes
about residualizing on the market leg alone.

A degenerate slot whose observations are all identical reports **zero within-slot variance**,
which would mathematically earn a weight of exactly 1 and be reported raw. It is shrunk fully
to its parent instead: claiming zero noise from a finite sample is precisely the overconfidence
the shrinkage exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from pips.alphas.forecast import Forecast
from pips.alphas.spec import AlphaSpec
from pips.alphas.t1._common import (
    IST,
    build_forecast,
    cross_sectional_residuals,
    sessions_by_symbol,
)
from pips.core.asof import AsOfPanelView

__all__ = ["A12Params", "SlotEstimate", "compute", "slot_estimates", "slot_of"]

SESSION_OPEN_MINUTE: Final = 9 * 60 + 15
SESSION_CLOSE_MINUTE: Final = 15 * 60 + 30
CLOCK_BIN_CHOICES: Final = (5, 10, 15)


def slot_of(hour: int, minute: int, bin_minutes: int) -> int | None:
    """Clock-slot index for a CLOSE-LABELLED bar, or ``None`` outside the continuous session.

    The label is the END of the bar, so 09:16 is the first bar of the session and 09:15 labels
    nothing tradeable — it is the pre-open boundary. Returning a slot for it would attach the
    opening auction to an intraday pattern that has nothing to do with it, and the M3 probe
    found Breeze does return pre-open and post-close prints when the window allows.
    """
    label = hour * 60 + minute
    if not SESSION_OPEN_MINUTE < label <= SESSION_CLOSE_MINUTE:
        return None
    return (label - SESSION_OPEN_MINUTE - 1) // bin_minutes


@dataclass(frozen=True)
class A12Params:
    """A point in the spec's bounded domain."""

    clock_bin_minutes: int
    history_sessions: int
    hold_minutes: int
    horizon_ns: int

    def __post_init__(self) -> None:
        if self.clock_bin_minutes not in CLOCK_BIN_CHOICES:
            raise ValueError(
                f"clock_bin_minutes {self.clock_bin_minutes} is not one of the predeclared "
                f"{CLOCK_BIN_CHOICES} (§3.2)"
            )
        if not 60 <= self.history_sessions <= 250:
            raise ValueError(f"history_sessions {self.history_sessions} is outside [60, 250]")
        if not 5 <= self.hold_minutes <= 60:
            raise ValueError(f"hold_minutes {self.hold_minutes} is outside [5, 60]")


@dataclass(frozen=True)
class SlotEstimate:
    """What the alpha reports, and what it declined to report.

    ``raw_mean`` is kept alongside ``shrunk_mean`` on purpose: the raw value is the declared
    null model, and a reader comparing them can see how much of it survived. Hiding it would
    make the shrinkage unauditable.
    """

    slot: int
    sessions: int
    raw_mean: Decimal
    parent_mean: Decimal
    shrunk_mean: Decimal
    weight: Decimal


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else Decimal(0)


def _variance(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal(0)
    centre = _mean(values)
    return sum((v - centre) ** 2 for v in values) / Decimal(len(values))


def slot_estimates(view: AsOfPanelView, params: A12Params) -> dict[str, SlotEstimate]:
    """Shrunk estimate for the CURRENT slot of each symbol with enough history."""
    sessions = sessions_by_symbol(view)
    if len(sessions) < 2:
        return {}

    # Residualize on the market leg first, so a slot pattern shared by the whole cross-section
    # is not reported as each name's own seasonal.
    closes: dict[str, list[int]] = {}
    labels: dict[str, list[int]] = {}
    for symbol, days in sessions.items():
        if len(days) < params.history_sessions:
            continue  # "insufficient session history => no slot estimate, not a zero"
        flat_closes: list[int] = []
        for day in days:
            flat_closes += day.closes
        closes[symbol] = flat_closes
    if len(closes) < 2:
        return {}

    # Bar labels, in the same order as the flattened closes, so a residual can be slotted.
    visible = view.visible().sort(["symbol", "close_ts_ns"])
    for symbol in closes:
        labels[symbol] = visible.filter(visible["symbol"] == symbol)["close_ts_ns"].to_list()

    returns = {
        s: [
            Decimal(closes[s][i] - closes[s][i - 1]) / Decimal(closes[s][i - 1])
            for i in range(1, len(closes[s]))
            if closes[s][i - 1] != 0
        ]
        for s in closes
    }
    residuals = cross_sectional_residuals(returns)

    out: dict[str, SlotEstimate] = {}
    for symbol, series in residuals.items():
        # Residual i corresponds to the bar at index i+1; slot it by that bar's label.
        by_slot: dict[int, list[Decimal]] = {}
        for i, residual in enumerate(series):
            stamp = datetime.fromtimestamp(labels[symbol][i + 1] / 1e9, IST)
            slot = slot_of(stamp.hour, stamp.minute, params.clock_bin_minutes)
            if slot is None:
                continue  # "a bar outside the continuous session has no slot"
            by_slot.setdefault(slot, []).append(residual)
        if not by_slot:
            continue

        current = slot_of(
            *datetime.fromtimestamp(labels[symbol][-1] / 1e9, IST).timetuple()[3:5],
            bin_minutes=params.clock_bin_minutes,
        )
        if current is None or current not in by_slot:
            continue

        observations = by_slot[current]
        raw = _mean(observations)
        parent = _mean([v for values in by_slot.values() for v in values])
        slot_means = [_mean(v) for v in by_slot.values()]

        between = _variance(slot_means)  # tau^2 -- how much slots really differ
        within = _variance(observations)  # sigma^2 -- noise inside this slot
        n = Decimal(len(observations))
        if within <= 0 or between <= 0 or n == 0:
            # Zero within-slot variance would mathematically earn a weight of exactly 1 and
            # report the raw mean — the declared null. Claiming zero noise from a finite
            # sample is the overconfidence the shrinkage exists to prevent, so shrink fully.
            weight = Decimal(0)
        else:
            weight = between / (between + within / n)

        out[symbol] = SlotEstimate(
            slot=current,
            sessions=len(observations),
            raw_mean=raw,
            parent_mean=parent,
            shrunk_mean=weight * raw + (Decimal(1) - weight) * parent,
            weight=weight,
        )
    return out


def compute(view: AsOfPanelView, params: A12Params, spec: AlphaSpec) -> list[Forecast]:
    """Hierarchically shrunk intraday slot residual. Pure and deterministic."""
    return [
        build_forecast(spec, symbol, estimate.shrunk_mean, view, params.horizon_ns)
        for symbol, estimate in sorted(slot_estimates(view, params).items())
    ]
