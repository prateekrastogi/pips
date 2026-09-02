"""Resumable call budgeter for the Breeze fetcher  (§6 M4, ADR-0012).

**Ported from SAL-0003**, keeping its two best ideas and replacing its constants with data:

* injectable ``sleep`` and ``clock``, so pacing is testable without waiting;
* pace **under** the published cap, because "real enforcement is stricter/buggier than
  published (a user hit the daily error at ~170 calls)".

The numbers come from ``config/breeze.yaml`` rather than from constants here. ADR-0012 records
100,000 calls/day and 32 parallel fetches, owner-confirmed, and keeps the per-minute rate at a
conservative unverified 75 until it is measured. An entitlement that changed once will change
again, and a constant in code is the wrong place to notice.

**Resumable, which the milestone asks for explicitly.** A campaign interrupted at call 60,000
must resume there. A budgeter that forgets is worse than none: it will spend the day's quota
twice and the failure will look like the vendor's.
"""

from __future__ import annotations

import json
import time as _time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from pips.core.atomic import atomic_write_text

__all__ = ["CallBudget", "DailyBudgetExceededError"]

# 10% under the confirmed cap. Not a superstition -- SAL-0003 records real enforcement biting
# earlier than the published number, and a campaign that stops early can resume tomorrow while
# one that trips the vendor's limiter has to work out what it half-wrote.
_HEADROOM = 0.90


class DailyBudgetExceededError(RuntimeError):
    """The day's call budget is spent. Checkpoint and resume tomorrow."""


class CallBudget:
    """Min-interval pacing plus a persisted per-day call budget."""

    def __init__(
        self,
        daily_cap: int,
        per_minute: int,
        max_parallel: int,
        state_path: Path,
        today: str,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], float] = _time.monotonic,
    ) -> None:
        self.daily_cap = daily_cap
        self.per_minute = per_minute
        self.max_parallel = max_parallel
        self.state_path = state_path
        self.today = today
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self._calls_made = self._load()

    @classmethod
    def from_config(
        cls,
        config_path: Path,
        state_path: Path,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], float] = _time.monotonic,
        today: str | None = None,
    ) -> CallBudget:
        """Build from ``config/breeze.yaml`` -- the quota is data, not code (rule 6)."""
        config: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        quota = config["quota"]
        return cls(
            daily_cap=int(quota["max_calls_per_day"]),
            per_minute=int(quota["max_calls_per_minute"]),
            max_parallel=int(quota["max_parallel_fetches"]),
            state_path=state_path,
            today=today or datetime.now(UTC).date().isoformat(),
            sleep=sleep,
            clock=clock,
        )

    # -- budget ------------------------------------------------------------------------
    @property
    def effective_budget(self) -> int:
        """The cap with headroom applied -- what we actually spend against."""
        return int(self.daily_cap * _HEADROOM)

    @property
    def min_interval(self) -> float:
        """Seconds between calls, derived from the per-minute limit.

        Derived rather than fixed, so measuring the real rate later changes pacing by editing
        `config/breeze.yaml` instead of by editing code.
        """
        return 60.0 / self.per_minute

    @property
    def calls_made(self) -> int:
        return self._calls_made

    @property
    def remaining(self) -> int:
        return max(0, self.effective_budget - self._calls_made)

    # -- persistence -------------------------------------------------------------------
    def _load(self) -> int:
        """Spend so far *today*. A different date starts at zero."""
        if not self.state_path.exists():
            return 0
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Unreadable state means we do not know what we have spent. Assuming zero would
            # risk spending the quota twice, so assume the worst and force a fresh day.
            return self.effective_budget
        if state.get("date") != self.today:
            return 0
        try:
            return int(state["calls_made"])
        except (KeyError, TypeError, ValueError):
            # Valid JSON that does not say what we spent. The guard above covers an unreadable
            # file; this covers a readable one missing the only field that matters -- an older
            # format, a hand edit, a half-written file that happened to stay parseable. Same
            # answer for the same reason: not knowing what we spent must not read as zero.
            return self.effective_budget

    def _save(self) -> None:
        # ATOMIC: rewritten once per call -- 90,000 times a day at the effective budget --
        # and a truncated file reads as "the whole day is spent", which is safe and costs the
        # rest of the day's quota.
        atomic_write_text(
            self.state_path,
            json.dumps({"date": self.today, "calls_made": self._calls_made}, sort_keys=True) + "\n",
        )

    # -- the gate ----------------------------------------------------------------------
    def acquire(self) -> None:
        """Pace one call, or raise once the day's budget is spent.

        Raises rather than throttling to a crawl: a campaign that quietly slows down looks
        like a slow vendor, while one that stops can checkpoint and resume tomorrow.
        """
        if self._calls_made >= self.effective_budget:
            raise DailyBudgetExceededError(
                f"spent {self._calls_made} of {self.effective_budget} calls "
                f"(cap {self.daily_cap}, headroom applied) on {self.today} — checkpoint and "
                "resume tomorrow rather than pushing into the vendor's limiter"
            )
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self._calls_made += 1
        self._save()
