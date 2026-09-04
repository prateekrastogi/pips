"""Pace on what the API actually says, not on a number somebody guessed.

OWNER INSTRUCTION, 2026-09-05, when asked what this account's real limits are: *"run it to
maximum and without any limits, basis real time responding conditions of api."*

Taken literally, "no limits" would mean hammering the endpoint until it locks the account, which
is the opposite of running at maximum. What it means in practice is that no FIXED ceiling should
govern the run: the vendor's own responses set the pace, and the limit is discovered rather than
declared. That is a control loop, and the classic shape for one is additive-increase /
multiplicative-decrease — speed up gently while replies are healthy, back off hard the moment one
is a rejection.

The numbers this replaces were never measured. `config/breeze.yaml` carries 75/min as an
explicit "CONSERVATIVE PLACEHOLDER" and 100,000/day on owner confirmation, while SAL-0003's donor
measured 100/min and 5,000/day against the same vendor — a 20x disagreement nothing in this
repository has ever settled. A pacer that learns beats a constant that argues.

A rate rejection arrives in the BODY (`Status 5`, "Limit exceed"), never as HTTP 429, which is
why `classify_response` exists and why this loop is driven by `ResponseKind` rather than by an
exception.
"""

from __future__ import annotations

import pytest

from pips.data.breeze.ingest import ResponseKind
from pips.data.breeze.pacing import AdaptivePacer


def pacer(**kw: float) -> AdaptivePacer:
    slept: list[float] = []
    clock = {"t": 0.0}

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["t"] += seconds

    p = AdaptivePacer(sleep=sleep, clock=lambda: clock["t"], **kw)
    p.slept = slept  # type: ignore[attr-defined]
    return p


def test_it_starts_at_the_configured_interval() -> None:
    assert pacer(start_interval=0.8).interval == pytest.approx(0.8)


def test_a_rate_rejection_slows_it_down_hard() -> None:
    """Multiplicative decrease: the one signal that means we are already over the line."""
    p = pacer(start_interval=0.5)
    p.observe(ResponseKind.RATE_LIMITED)
    assert p.interval > 0.5
    assert p.interval == pytest.approx(1.0), "doubling by default"


def test_healthy_replies_speed_it_up_gently() -> None:
    """Additive increase: probing for more throughput, a little at a time."""
    p = pacer(start_interval=1.0, step=0.05)
    before = p.interval
    p.observe(ResponseKind.OK)
    assert p.interval < before
    assert p.interval == pytest.approx(0.95)


def test_an_empty_reply_is_healthy_too() -> None:
    """EMPTY is a legitimate answer -- a non-trading day -- not a symptom of pacing."""
    p = pacer(start_interval=1.0, step=0.05)
    p.observe(ResponseKind.EMPTY)
    assert p.interval == pytest.approx(0.95)


def test_an_error_neither_speeds_up_nor_slows_down() -> None:
    """A vendor error says nothing about our rate, so it must not be read as either signal.

    Speeding up on it would treat a failure as permission; slowing down would throttle the run
    for a fault that has nothing to do with pacing.
    """
    p = pacer(start_interval=1.0, step=0.05)
    p.observe(ResponseKind.ERROR)
    assert p.interval == pytest.approx(1.0)


def test_it_never_speeds_past_the_floor() -> None:
    """The floor is the only fixed bound, and it exists so the loop cannot reach zero delay."""
    p = pacer(start_interval=0.2, step=0.05, floor_interval=0.1)
    for _ in range(20):
        p.observe(ResponseKind.OK)
    assert p.interval == pytest.approx(0.1)


def test_backing_off_has_no_ceiling_of_its_own() -> None:
    """Whatever the vendor is enforcing, the loop must be able to get under it."""
    p = pacer(start_interval=0.5)
    for _ in range(6):
        p.observe(ResponseKind.RATE_LIMITED)
    assert p.interval > 20


def test_it_records_what_it_learned() -> None:
    """The point of discovering a limit is being able to report it.

    `config/breeze.yaml` has carried an unverified 75/min and a disputed 100,000/day since
    August; a run that measures the truth and does not say so leaves them unverified forever.
    """
    p = pacer(start_interval=0.5)
    # The real loop is acquire -> call -> observe, and `calls` counts calls actually made.
    for kind in (ResponseKind.OK, ResponseKind.OK, ResponseKind.RATE_LIMITED, ResponseKind.OK):
        p.acquire()
        p.observe(kind)
    assert p.calls == 4
    assert p.rejections == 1
    assert "1 rejection" in p.describe()
    assert "calls/min" in p.describe()


def test_no_fixed_ceiling_refuses_a_call() -> None:
    """The instruction was 'without any limits' -- so nothing here counts calls and stops.

    Pacing is the whole mechanism. A preset budget is exactly the guessed number this replaces,
    and `DailyBudgetExceededError` was raised on one.
    """
    p = pacer(start_interval=0.0, floor_interval=0.0)
    for _ in range(10_000):
        p.acquire()
        p.observe(ResponseKind.OK)
    assert p.calls == 10_000, "it paces, it does not refuse"


def test_acquire_waits_the_current_interval() -> None:
    p = pacer(start_interval=0.5, floor_interval=0.5)
    p.acquire()  # first call has nothing to wait for
    p.acquire()
    assert p.slept and p.slept[-1] == pytest.approx(0.5)  # type: ignore[attr-defined]
