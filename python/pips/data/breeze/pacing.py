"""Pace a vendor campaign on what the API actually says, not on a number somebody guessed.

OWNER INSTRUCTION, 2026-09-05, asked what this account's real limits are: *"run it to maximum and
without any limits, basis real time responding conditions of api."*

Read literally, "no limits" would mean hammering the endpoint until it locks the account, which
is the opposite of running at maximum. What it means operationally is that no FIXED ceiling
governs the run -- the vendor's own replies set the pace, and the limit is DISCOVERED rather than
declared. That is a control loop, and the classic shape is additive-increase / multiplicative-
decrease: probe for more throughput a little at a time, and back off hard the moment a reply is a
rejection.

WHAT THIS REPLACES was never measured. `config/breeze.yaml` carries 75 calls/min marked in as
many words a "CONSERVATIVE PLACEHOLDER", and 100,000/day on owner confirmation, while SAL-0003's
donor measured 100/min and 5,000/day against this same vendor -- a 20x disagreement that nothing
in this repository has ever settled, and which decides whether the 1-minute campaign takes two
days or twenty-four. A loop that learns beats a constant that argues.

THE REJECTION IS IN THE BODY. Breeze answers a rate limit with `Status 5` / "Limit exceed" and an
HTTP 200, never a 429 -- which is why this is driven by `ResponseKind` from `classify_response`
rather than by an exception, and why a caller that does not look for it records a throttled reply
as a quiet market.

THE ONE FIXED BOUND is `floor_interval`, and it is not a rate limit: it stops the loop reaching
zero delay and spinning. Everything above it is the vendor's to decide.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable

from pips.data.breeze.ingest import ResponseKind

__all__ = ["AdaptivePacer"]


class AdaptivePacer:
    """Additive-increase / multiplicative-decrease pacing, driven by vendor replies."""

    def __init__(
        self,
        *,
        start_interval: float = 0.8,
        floor_interval: float = 0.1,
        step: float = 0.02,
        backoff: float = 2.0,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], float] = _time.monotonic,
    ) -> None:
        self.interval = float(start_interval)
        self.floor_interval = float(floor_interval)
        self.step = float(step)
        self.backoff = float(backoff)
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.calls = 0
        self.rejections = 0
        self._started = clock()

    def acquire(self) -> None:
        """Wait out the current interval. It never refuses -- pacing IS the mechanism.

        There is deliberately no call counter to exceed here. A preset budget is exactly the
        guessed number this class exists to stop relying on.
        """
        if self._last is not None:
            wait = self.interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.calls += 1

    def observe(self, kind: ResponseKind) -> None:
        """Feed one reply back into the pace.

        RATE_LIMITED is the only signal that means we are already over the line, so it is the
        only one that slows us -- and it slows us multiplicatively, with no ceiling, because
        whatever the vendor is enforcing the loop has to be able to get under it.

        OK and EMPTY are both healthy: EMPTY is a legitimate answer for a non-trading day, not a
        symptom of pacing, and reading it as one would throttle a campaign on every holiday.

        ERROR moves nothing. It says nothing about our rate: speeding up on it would treat a
        failure as permission, and slowing down would throttle the run for an unrelated fault.
        """
        if kind is ResponseKind.RATE_LIMITED:
            self.rejections += 1
            self.interval *= self.backoff
        elif kind in (ResponseKind.OK, ResponseKind.EMPTY):
            self.interval = max(self.floor_interval, self.interval - self.step)

    def observed_rate_per_minute(self) -> float:
        """Calls per minute actually achieved so far, measured rather than configured."""
        elapsed = self._clock() - self._started
        if elapsed <= 0:
            return 0.0
        return self.calls * 60.0 / elapsed

    def describe(self) -> str:
        return (
            f"pacing: {self.calls} call(s), {self.rejections} rejection(s), "
            f"interval now {self.interval:.3f}s "
            f"({self.observed_rate_per_minute():.1f} calls/min observed)"
        )
