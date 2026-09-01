"""Order-budget constraints  (§6 M19, blueprint §3.3-§3.4 and §12).

The blueprint states the purpose exactly: *"order budget respected as an optimizer constraint,
so research never certifies a strategy the engine may not legally run."* The constraint belongs
in SELECTION, not only in the engine — a strategy that clears every statistical gate and then
cannot be run is a strategy that wasted the gates.

Three limits, and they are not interchangeable:

* **5 orders/second globally** — the engine's governor, deliberately half of SEBI's ~10/s
  threshold for the registration-free route.
* **2 orders/second per symbol** — a separate throttle. Satisfying the global does not imply it.
* **a daily cap** — the broker's, separate from any rate.

**The binding constraint is the governor (5/s), not the legal threshold (10/s).** A strategy at
7/s is legal and still inadmissible, because the governor will throttle it — and the throttled
strategy is not the one that was validated. Certifying it means certifying a backtest of
something the plant will never run.
"""

from __future__ import annotations

import pytest

from pips.selection.order_budget import (
    NSE_RETAIL_BUDGET,
    OrderBudget,
    OrderEvent,
    OrderKind,
    check_order_budget,
)

SECOND = 1_000_000_000
OPEN = 1_772_000_000 * SECOND


def ev(offset_ns: int, symbol: str = "RELIANCE", kind: OrderKind = OrderKind.NEW) -> OrderEvent:
    return OrderEvent(ts_ns=OPEN + offset_ns, symbol=symbol, kind=kind)


def spread(
    n: int, symbol: str = "RELIANCE", start: int = 0, gap_ns: int = SECOND
) -> list[OrderEvent]:
    return [ev(start + i * gap_ns, symbol) for i in range(n)]


# ------------------------------------------------------------ the rate ----------------


def test_a_strategy_within_every_limit_is_admissible() -> None:
    verdict = check_order_budget(spread(20), NSE_RETAIL_BUDGET)
    assert verdict.admissible
    assert verdict.breaches == ()
    assert verdict.peak_global_per_second == 1


def test_a_burst_over_the_global_governor_is_caught() -> None:
    events = [ev(i * SECOND // 100) for i in range(9)]  # 9 orders inside 90ms
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert not verdict.admissible
    assert verdict.peak_global_per_second == 9
    assert any("global" in b.limit for b in verdict.breaches)


def test_a_tiny_daily_total_does_not_excuse_a_burst() -> None:
    """The failure an average would hide.

    Forty orders in one second and nothing else all day is about 0.002 orders/second averaged
    over the session — comfortably inside any cap you like — and it is forty orders in a second.
    The engine governs on the instant, so the check has to as well.
    """
    burst = [ev(i * SECOND // 1000) for i in range(40)]
    verdict = check_order_budget(burst, NSE_RETAIL_BUDGET)
    assert not verdict.admissible
    assert verdict.peak_global_per_second == 40
    assert verdict.total_orders == 40, "the daily total is unremarkable; the peak is not"


def test_the_window_slides_rather_than_snapping_to_fixed_seconds() -> None:
    """Fixed one-second buckets hide exactly the bursts this exists to catch.

    Five orders at t=0.9s and five at t=1.1s: bucketed by whole second that reads as 5 and 5,
    both inside the cap. Slid, it is ten orders in 200ms.

    Note this is the OPPOSITE choice from the netting bucket, and deliberately. There, fixed
    buckets understate crossing, which charges the ensemble for a saving it might have had —
    the conservative direction. Here, fixed buckets understate the peak, which hides a
    violation. The same-looking question has different safe answers depending on which way the
    error flatters.
    """
    events = [ev(900 * SECOND // 1000 + i) for i in range(5)]
    events += [ev(1100 * SECOND // 1000 + i) for i in range(5)]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert verdict.peak_global_per_second == 10
    assert not verdict.admissible


def test_the_governor_binds_before_the_legal_threshold() -> None:
    """7 orders/second is legal under SEBI and still inadmissible.

    The engine caps at 5. At 7 the governor throttles, so what runs is a delayed version of the
    strategy — and the delayed version is not the one that was validated. Certifying it
    certifies a backtest of something that will never execute.
    """
    events = [ev(i * SECOND // 10) for i in range(7)]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert not verdict.admissible
    assert verdict.peak_global_per_second == 7
    assert NSE_RETAIL_BUDGET.global_per_second < NSE_RETAIL_BUDGET.legal_per_second


# ------------------------------------------------------------ per symbol --------------


def test_the_per_symbol_throttle_binds_independently_of_the_global_one() -> None:
    # Four orders in one symbol inside a second: 4 < 5 globally, but 4 > 2 for that symbol.
    events = [ev(i * SECOND // 10, "RELIANCE") for i in range(4)]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert not verdict.admissible
    assert any("per-symbol" in b.limit and b.symbol == "RELIANCE" for b in verdict.breaches)


def test_the_global_limit_binds_even_when_every_symbol_is_fine() -> None:
    # Three symbols at 2/s each: every symbol is exactly at its throttle, the total is 6 > 5.
    events = []
    for symbol in ("RELIANCE", "TCS", "SBIN"):
        events += [ev(i * SECOND // 10, symbol) for i in range(2)]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert not verdict.admissible
    assert any("global" in b.limit for b in verdict.breaches)
    assert not any("per-symbol" in b.limit for b in verdict.breaches)


def test_orders_in_different_symbols_do_not_pool_into_one_throttle() -> None:
    events = [ev(0, "RELIANCE"), ev(1, "TCS"), ev(2, "SBIN"), ev(3, "INFY")]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert not any("per-symbol" in b.limit for b in verdict.breaches)


# ------------------------------------------------------------ what counts -------------


def test_cancels_and_modifies_count_as_orders() -> None:
    """The protected-limit machine (M14) reprices: one intent becomes several order events.

    Counting fills, or counting intents, understates the rate by whatever the reprice
    multiplier happens to be — and understates it in the direction that admits the strategy.
    """
    events = [
        ev(0, kind=OrderKind.NEW),
        ev(SECOND // 10, kind=OrderKind.MODIFY),
        ev(2 * SECOND // 10, kind=OrderKind.MODIFY),
        ev(3 * SECOND // 10, kind=OrderKind.CANCEL),
        ev(4 * SECOND // 10, kind=OrderKind.NEW),
        ev(5 * SECOND // 10, kind=OrderKind.NEW),
    ]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert verdict.peak_global_per_second == 6
    assert not verdict.admissible


def test_the_daily_cap_is_a_separate_dimension_from_the_rate() -> None:
    # One order per second all day: never near 5/s, and far past the daily cap.
    events = spread(NSE_RETAIL_BUDGET.daily_cap + 1)
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert verdict.peak_global_per_second == 1
    assert not verdict.admissible
    assert any("daily" in b.limit for b in verdict.breaches)


# ------------------------------------------------------------ the verdict -------------


def test_the_verdict_names_when_and_where_so_it_can_be_diagnosed() -> None:
    """The burst must NOT be the first thing in the day, or `at_ns` proves nothing.

    Reporting the first event's timestamp is right by accident whenever the breach happens to
    start there. Quiet traffic first, then the burst, so a hardcoded `timestamps[0]` points at
    the wrong moment — which is the difference between a diagnosable breach and a note that
    something, somewhere, was too fast.
    """
    quiet = [ev(i * SECOND, "SBIN") for i in range(10)]
    burst = [ev(600 * SECOND + i * SECOND // 100, "TCS") for i in range(9)]
    verdict = check_order_budget(quiet + burst, NSE_RETAIL_BUDGET)

    breach = next(b for b in verdict.breaches if "global" in b.limit)
    assert breach.observed == 9
    assert breach.allowed == NSE_RETAIL_BUDGET.global_per_second
    assert breach.at_ns == burst[0].ts_ns
    assert breach.at_ns != quiet[0].ts_ns


def test_unsorted_input_gives_the_same_verdict() -> None:
    """The events must be SPREAD OUT, or the test passes without any sorting at all.

    The two-pointer never advances on descending stamps, so it counts everything as one window.
    On a fixture where every event really is in one window that wrong behaviour produces the
    right number, and the test proves nothing. Here the events are a second apart, so failing
    to sort turns a peak of 1 into a peak of 9.
    """
    events = spread(9)
    assert check_order_budget(events, NSE_RETAIL_BUDGET).peak_global_per_second == 1
    assert check_order_budget(list(reversed(events)), NSE_RETAIL_BUDGET).peak_global_per_second == 1


def test_a_strategy_that_sends_nothing_breaches_nothing() -> None:
    verdict = check_order_budget([], NSE_RETAIL_BUDGET)
    assert verdict.admissible
    assert verdict.peak_global_per_second == 0


def test_there_is_no_verdict_that_means_unknown() -> None:
    """Fail-closed: `admissible` is computed from the breach list, never set independently.

    A tri-state where 'not evaluated' can be read as 'fine' is how NOT_RUN becomes PASSED.
    """
    events = [ev(i * SECOND // 100) for i in range(9)]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert verdict.admissible == (verdict.breaches == ())


# ------------------------------------------------------------ the budget --------------


def test_a_budget_that_exceeds_the_legal_threshold_is_refused() -> None:
    """The governor exists to sit UNDER the threshold; a budget above it is not a budget.

    Constructing one would let selection certify a strategy whose order rate requires exchange
    registration the project does not have.
    """
    with pytest.raises(ValueError, match="legal"):
        OrderBudget(
            global_per_second=12, per_symbol_per_second=2, daily_cap=3000, legal_per_second=10
        )


def test_a_per_symbol_throttle_above_the_global_one_is_refused() -> None:
    # It could never bind, so declaring it would suggest a protection that does not exist.
    with pytest.raises(ValueError, match="per-symbol"):
        OrderBudget(
            global_per_second=5, per_symbol_per_second=8, daily_cap=3000, legal_per_second=10
        )


def test_the_shipped_budget_matches_the_blueprint() -> None:
    # §12: "Global order-rate governor capped at 5 orders/second (half the threshold),
    # per-symbol throttle 2/s."
    assert NSE_RETAIL_BUDGET.global_per_second == 5
    assert NSE_RETAIL_BUDGET.per_symbol_per_second == 2
    assert NSE_RETAIL_BUDGET.legal_per_second == 10


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "order-budget" in CHECK_REGISTRY
    resolve_check("order-budget")


# ------------------------------------------------------------ the window convention ---
#
# "N per second" means: no 1-second window contains more than N. The window is HALF-OPEN,
# [t, t+1s), and both tests below exist because the alternative is tempting and wrong.


def test_traffic_sustained_exactly_at_the_cap_is_admissible() -> None:
    """The argument against an inclusive window, which is otherwise the 'safe' choice.

    Under a closed [t, t+1s] window, five orders per second sustained reads as SIX — the
    boundary order is counted in both neighbouring windows — so every strategy running at
    exactly the governor's rate would be refused. That is not conservatism, it is an off-by-one
    applied systematically.
    """
    # Spread across three symbols so the PER-SYMBOL throttle is not what bites: sustaining 5/s
    # globally requires at least three symbols, since each is capped at 2/s. A fixture that put
    # all five in one name would fail for the wrong reason and prove nothing about the window.
    symbols = ["RELIANCE", "RELIANCE", "TCS", "TCS", "SBIN"]
    events = [
        ev(second * SECOND + i * SECOND // 5, symbols[i]) for second in range(10) for i in range(5)
    ]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert max(verdict.peak_per_symbol.values()) == 2
    assert verdict.peak_global_per_second == 5
    assert verdict.admissible


def test_orders_spanning_exactly_one_second_are_not_all_one_second_apart() -> None:
    """Three orders at 0.0s, 0.5s and 1.0s against a 2/s throttle: admissible.

    The closed interval [0, 1.0] does hold three of them, which looks like a breach and is not:
    no window of DURATION one second holds three, because the first and last are a full second
    apart. Pinned rather than left to whichever comparison operator got typed — this is the
    same boundary question as §6.2's `g >= tau`, and it deserves the same treatment.

    Nothing is hidden by this. Any burst spanning less than a second sits entirely inside some
    window, so the only thing the half-open convention excludes is the boundary instant itself.
    """
    events = [ev(0, "RELIANCE"), ev(SECOND // 2, "RELIANCE"), ev(SECOND, "RELIANCE")]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert verdict.peak_per_symbol["RELIANCE"] == 2
    assert verdict.admissible


def test_one_nanosecond_inside_the_window_does_breach() -> None:
    # The other side of the same boundary: shift the last order a nanosecond earlier and all
    # three fit in one window.
    events = [ev(0, "RELIANCE"), ev(SECOND // 2, "RELIANCE"), ev(SECOND - 1, "RELIANCE")]
    verdict = check_order_budget(events, NSE_RETAIL_BUDGET)
    assert verdict.peak_per_symbol["RELIANCE"] == 3
    assert not verdict.admissible
