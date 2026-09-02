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


# --------------------------------------------------------- found by mutation sweep ---


def test_the_headroom_truncates_rather_than_rounding_up(tmp_path: Path) -> None:
    """90,000 of 100,000, and the direction of the rounding is the point.

    The headroom exists because SAL-0003 saw real enforcement bite before the published
    number. Rounding up spends one call more than the margin allows, which is a rounding
    error in the direction the margin was put there to avoid.
    """
    budget = CallBudget(100_000, 75, 32, tmp_path / "s.json", "2026-09-02")
    assert budget.effective_budget == 90_000
    assert budget.remaining == 90_000
    odd = CallBudget(1_001, 75, 32, tmp_path / "t.json", "2026-09-02")
    assert odd.effective_budget == 900, "900.9 truncates to 900, never 901"


def test_unreadable_state_assumes_the_day_is_spent(tmp_path: Path) -> None:
    """Not that nothing was spent. The docstring's own words: a budgeter that forgets is worse
    than none, because it will spend the day's quota twice and the failure will look like the
    vendor's. Stopping early is recoverable tomorrow; double-spending is not recoverable at all.
    """
    state = tmp_path / "s.json"
    state.write_text('{"date": "2026-09-02", "calls_made": 4', encoding="utf-8")
    budget = CallBudget(100_000, 75, 32, state, "2026-09-02")
    assert budget.calls_made == budget.effective_budget
    assert budget.remaining == 0
    with pytest.raises(DailyBudgetExceededError):
        budget.acquire()


def test_readable_state_that_does_not_say_what_we_spent_also_assumes_spent(
    tmp_path: Path,
) -> None:
    """The half the guard missed.

    `state.get("date")` was tolerant and `state["calls_made"]` was not, so a *parseable* file
    without that field raised KeyError out of the constructor instead of failing safe — an
    older format, a hand edit, or a half-written file that happened to stay valid JSON.
    Not knowing what we spent must not read as zero, however the not-knowing arrives.
    """
    for content in ('{"date": "2026-09-02"}', '{"date": "2026-09-02", "calls_made": "many"}'):
        state = tmp_path / f"s{hash(content)}.json"
        state.write_text(content, encoding="utf-8")
        budget = CallBudget(100_000, 75, 32, state, "2026-09-02")
        assert budget.calls_made == budget.effective_budget, content


def test_remaining_never_goes_negative(tmp_path: Path) -> None:
    """Lowering the cap between runs must not report a negative allowance.

    `remaining` is what a campaign driver reads to size the next slice of work; a negative
    reads as "less than nothing to do" only if someone thought to check for it.
    """
    state = tmp_path / "s.json"
    state.write_text('{"date": "2026-09-02", "calls_made": 5000}', encoding="utf-8")
    tightened = CallBudget(1_000, 75, 32, state, "2026-09-02")
    assert tightened.calls_made == 5000
    assert tightened.remaining == 0


def test_the_quota_comes_from_the_config_file_not_from_constants(tmp_path: Path) -> None:
    """Rule 6, and the module's stated reason for existing.

    An entitlement that changed once will change again, and a constant in code is the wrong
    place to notice. Values here are deliberately unlike the real ones: a test that used
    100000/75 would pass against a hardcoded 100000/75.
    """
    config = tmp_path / "breeze.yaml"
    config.write_text(
        "quota:\n"
        "  max_calls_per_day: 12345\n"
        "  max_calls_per_minute: 7\n"
        "  max_parallel_fetches: 3\n",
        encoding="utf-8",
    )
    budget = CallBudget.from_config(config, tmp_path / "s.json", today="2026-09-02")
    assert budget.daily_cap == 12_345
    assert budget.per_minute == 7
    assert budget.max_parallel == 3
    assert budget.effective_budget == 11_110
    assert budget.min_interval == pytest.approx(60.0 / 7)


def test_the_shipped_config_is_the_one_the_budgeter_reads(tmp_path: Path) -> None:
    """And it agrees with ADR-0012: 100,000/day, 32 parallel, 75/min still unverified."""
    budget = CallBudget.from_config(CONFIG, tmp_path / "s.json", today="2026-09-02")
    assert budget.daily_cap == 100_000
    assert budget.max_parallel == 32
    assert budget.effective_budget == 90_000


def test_a_crash_mid_save_does_not_destroy_the_days_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The state file is rewritten once per call — 90,000 windows a day.

    A truncated file is read as "the whole day is spent", which is the safe direction and
    costs the rest of the day's quota. Cheap to avoid: the write has to land whole or not at
    all, the same rule the backfill manifest follows.
    """
    state = tmp_path / "s.json"
    clock = FakeClock()
    budget = CallBudget(100_000, 75, 32, state, "2026-09-02", clock.sleep, clock.monotonic)
    budget.acquire()
    budget.acquire()

    real_write = Path.write_text

    def killed_halfway(self: Path, data: str, **kwargs: object) -> int:
        real_write(self, data[: len(data) // 2], **kwargs)  # type: ignore[arg-type]
        raise OSError("process killed mid-write")

    monkeypatch.setattr(Path, "write_text", killed_halfway)
    with pytest.raises(OSError, match="killed mid-write"):
        budget.acquire()
    monkeypatch.undo()

    resumed = CallBudget(100_000, 75, 32, state, "2026-09-02", clock.sleep, clock.monotonic)
    assert resumed.calls_made == 2, "the two calls already paid for must survive"
