"""Resumable call budgeter for the Breeze fetcher (§6 M4, ADR-0012).

Two requirements the milestone states plainly and one the donor adds:

* the budget comes from `config/breeze.yaml`, not from constants — ADR-0012 records
  100,000/day and 32 parallel fetches, and an entitlement that changed once will change again;
* it is **resumable**: a campaign interrupted at call 60,000 must resume there, not restart.
  A budgeter that forgets is worse than none, because it will cheerfully spend the day's quota
  twice and blame the vendor;
* it paces **under** the published cap. SAL-0003: "real enforcement is stricter/buggier than
  published (a user hit the daily error at ~170 calls)".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pips.data.breeze.budget import CallBudget, DailyBudgetExceededError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "breeze.yaml"


class FakeClock:
    """Injectable clock and sleep, so pacing is tested without waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def budget(tmp_path: Path, clock: FakeClock) -> CallBudget:
    return CallBudget.from_config(
        CONFIG, state_path=tmp_path / "budget.json", sleep=clock.sleep, clock=clock.monotonic
    )


# ------------------------------------------------------------ configuration -------------


def test_the_budget_comes_from_config_not_constants(tmp_path: Path) -> None:
    b = budget(tmp_path, FakeClock())
    assert b.daily_cap == 100_000  # ADR-0012
    assert b.max_parallel == 32


def test_the_effective_budget_leaves_headroom_under_the_cap(tmp_path: Path) -> None:
    # SAL-0003's warning, kept: real enforcement is stricter than published.
    b = budget(tmp_path, FakeClock())
    assert b.effective_budget < b.daily_cap
    assert b.effective_budget >= b.daily_cap * 0.8, "headroom should be modest, not crippling"


def test_pacing_is_derived_from_the_per_minute_limit(tmp_path: Path) -> None:
    # config/breeze.yaml carries a conservative 75/min marked unverified, so the interval is
    # 60/75 = 0.8s. Deriving it means a measured limit later changes pacing by editing data.
    b = budget(tmp_path, FakeClock())
    assert b.min_interval == pytest.approx(0.8)


# ------------------------------------------------------------------ pacing --------------


def test_it_waits_between_calls(tmp_path: Path) -> None:
    clock = FakeClock()
    b = budget(tmp_path, clock)
    b.acquire()
    b.acquire()
    assert clock.slept and clock.slept[0] == pytest.approx(0.8)


def test_it_does_not_wait_when_enough_time_has_already_passed(tmp_path: Path) -> None:
    clock = FakeClock()
    b = budget(tmp_path, clock)
    b.acquire()
    clock.now += 5.0
    b.acquire()
    assert clock.slept == []


# --------------------------------------------------------------- resumability -----------


def test_the_count_survives_a_restart(tmp_path: Path) -> None:
    # The requirement in one test: interrupt, reconstruct, and the spend is remembered.
    clock = FakeClock()
    first = budget(tmp_path, clock)
    for _ in range(5):
        first.acquire()
    assert first.calls_made == 5

    resumed = budget(tmp_path, FakeClock())
    assert resumed.calls_made == 5, "a budgeter that forgets will spend the day's quota twice"


def test_a_new_day_resets_the_count(tmp_path: Path) -> None:
    clock = FakeClock()
    b = CallBudget.from_config(
        CONFIG,
        state_path=tmp_path / "b.json",
        sleep=clock.sleep,
        clock=clock.monotonic,
        today="2026-08-31",
    )
    b.acquire()
    b.acquire()
    tomorrow = CallBudget.from_config(
        CONFIG,
        state_path=tmp_path / "b.json",
        sleep=clock.sleep,
        clock=clock.monotonic,
        today="2026-09-01",
    )
    assert tomorrow.calls_made == 0


def test_exhausting_the_budget_raises_rather_than_slowing_down(tmp_path: Path) -> None:
    # Silently throttling to a crawl would look like a slow vendor. The campaign must stop and
    # checkpoint so it can resume tomorrow.
    clock = FakeClock()
    b = budget(tmp_path, clock)
    b._calls_made = b.effective_budget
    with pytest.raises(DailyBudgetExceededError, match="resume"):
        b.acquire()


def test_the_remaining_count_is_reported(tmp_path: Path) -> None:
    b = budget(tmp_path, FakeClock())
    before = b.remaining
    b.acquire()
    assert b.remaining == before - 1
