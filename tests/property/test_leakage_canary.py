"""The permanent leakage canary (§7, constitution rule 2).

An alpha that cheats, kept in the suite forever. It must be **spectacular** in an unsafe
harness and **refused** by every production path. Both halves matter:

* if the unsafe half stops being spectacular, the canary has stopped being a canary and this
  test is no longer evidence of anything;
* if the production half stops raising, the guard has been weakened or bypassed — and
  §7 is explicit that when the canary passes, *the infrastructure changed, not the market*.

This file is never deleted and never marked xfail. Making it green by loosening the guard is
the same offence as weakening a golden (rule 10).
"""

from __future__ import annotations

import pytest

from pips.alphas.canary import (
    CANARIES,
    LeakageCanary,
    canary_panel,
    rank_ic,
    realized_next_return,
)
from pips.core.asof import AsOfPanelView, CausalityViolationError

NS = 1_000_000_000
SPECTACULAR = 0.90  # |rank IC| a real alpha never reaches; a cheating one reaches trivially


@pytest.mark.parametrize("canary", CANARIES, ids=lambda c: c.name)
def test_the_canary_is_spectacular_in_an_unsafe_harness(canary: LeakageCanary) -> None:
    frame = canary_panel()
    forecast = canary.unsafe(frame)
    ic = rank_ic(forecast, realized_next_return(frame))
    assert abs(ic) >= SPECTACULAR, (
        f"{canary.name} scored |IC|={abs(ic):.3f} unsafely. A canary that is no longer "
        "spectacular has stopped being a canary — fix the canary, never the threshold."
    )


@pytest.mark.parametrize("canary", CANARIES, ids=lambda c: c.name)
def test_the_canary_dies_on_the_production_path(canary: LeakageCanary) -> None:
    frame = canary_panel()
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"][len(frame) // 2]))
    with pytest.raises(CausalityViolationError):
        canary.production(view)


@pytest.mark.parametrize("canary", CANARIES, ids=lambda c: c.name)
def test_the_refusal_names_the_reason(canary: LeakageCanary) -> None:
    # A guard that refuses without saying why trains people to route around it.
    frame = canary_panel()
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"][len(frame) // 2]))
    with pytest.raises(CausalityViolationError, match=canary.expected_refusal):
        canary.production(view)


def test_all_three_bans_are_exercised() -> None:
    # One canary per mechanical ban. If a ban is added without a canary, it is untested.
    assert {c.ban for c in CANARIES} == {"lookahead", "full-day", "smoothed-state"}


def test_an_honest_alpha_survives_the_same_production_path() -> None:
    # The control. Without this, a guard that refused *everything* would pass every test
    # above, and the canary suite would be proving nothing about discrimination.
    frame = canary_panel()
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"][len(frame) // 2]))
    lagged = view.shifted("close_paise", 1)
    assert lagged.len() > 0
    assert view.accessed_fields == {"close_paise"}


def test_an_honest_alpha_is_not_spectacular() -> None:
    # The other half of the control: the honest feature must score like an honest feature,
    # or SPECTACULAR is not separating cheats from real alphas.
    # Lagged volume: a field a real alpha may read, carrying no information about the next
    # return by construction. Lagged CLOSE would not serve here — on a mean-reverting path
    # the level genuinely predicts the next move, which is a property of the fixture rather
    # than a leak, and would make this control fail for the wrong reason.
    frame = canary_panel()
    honest = frame["volume"].shift(1)
    ic = rank_ic(honest, realized_next_return(frame))
    assert abs(ic) < SPECTACULAR, f"the honest control scored |IC|={abs(ic):.3f}"
