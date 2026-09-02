"""Decision delay in the PnL series — `[G-P4-DELAY1]`'s input  (§6 M18/M20).

The blueprint's certification row reads *"Positive after 1.5x cost and **survives +1-bar
delay**"*. Two gates, and only one of them is computable here.

**`stress.cost_1_5x` is NOT.** `_pnl_series` is gross: it takes every forecast's sign and holds
one bar, with no cost line anywhere. Multiplying a cost of zero by 1.5 leaves it zero, so the
"stressed" result would equal the unstressed one and the case would PASS — a perturbation that
cannot be evaluated certifying itself, which is the exact defect `CaseOutcome.NOT_RUN` was added
to prevent. It needs the event engine's cost model (M14), and until then the field stays
unsupplied.

**`stress.delay_1_bar` IS.** Deciding on bar *i* and entering at *i+1* instead of *i* is exactly
the perturbation the gate names, and it is a property of the same data.

A delayed series that never trades must NOT be recorded as a net return of zero: `at_least 0.0`
would pass it, and a strategy that stops trading under a one-bar delay has not survived the
delay — it has stopped.
"""

from __future__ import annotations

import polars as pl
import pytest

from pips.search.s1 import _pnl_series

BAR = 60_000_000_000
STAMPS = [1_772_000_000_000_000_000 + i * BAR for i in range(5)]


class _Spec:
    id = "A00"


def panel_of(prices: list[int]) -> tuple[pl.DataFrame, dict[str, dict[int, int]]]:
    rows = [
        {"instrument_id": "SYM", "close_ts_ns": ts, "close_paise": price}
        for ts, price in zip(STAMPS, prices, strict=True)
    ]
    closes = {"SYM": dict(zip(STAMPS, prices, strict=True))}
    return pl.DataFrame(rows), closes


def always_long(_view: object, _params: object, _spec: object) -> list[object]:
    class F:
        instrument_id = "SYM"
        expected_return_bps = 1.0

    return [F()]


def series(prices: list[int], delay_bars: int = 0) -> list[float]:
    panel, closes = panel_of(prices)
    return _pnl_series(
        panel,
        closes,
        STAMPS,
        object(),
        _Spec(),  # type: ignore[arg-type]
        compute_fn=always_long,  # type: ignore[arg-type]
        delay_bars=delay_bars,
    )


# ------------------------------------------------------------------ the shift itself -----


def test_no_delay_is_the_existing_behaviour() -> None:
    """A rising ladder: each bar's return is the next close over this one."""
    out = series([100, 110, 120, 130, 140])
    assert out == pytest.approx([0.10, 10 / 110, 10 / 120, 10 / 130])


def test_one_bar_delay_enters_a_bar_later() -> None:
    """The decision is still made on bar i; the position is taken at i+1 and closed at i+2.

    On a ladder that means each entry pays the NEXT rung's return, which is smaller — exactly
    the kind of erosion the gate is looking for.
    """
    out = series([100, 110, 120, 130, 140], delay_bars=1)
    assert out[0] == pytest.approx(10 / 110)
    assert out[1] == pytest.approx(10 / 120)


def test_a_decision_with_no_room_left_is_dropped_not_carried() -> None:
    """Under a delay the last decisions have no exit bar. They contribute nothing rather than
    reusing an earlier price, which would fabricate a return out of the shift."""
    undelayed = series([100, 110, 120, 130, 140])
    delayed = series([100, 110, 120, 130, 140], delay_bars=1)

    assert len(delayed) == len(undelayed), "the series must stay comparable"
    assert delayed[-1] == 0.0


def test_a_delay_longer_than_the_window_trades_nothing() -> None:
    out = series([100, 110, 120, 130, 140], delay_bars=10)
    assert out == [0.0] * (len(STAMPS) - 1)


def test_a_negative_delay_is_refused() -> None:
    """A negative delay enters BEFORE the decision, which is the lookahead this project exists
    to prevent — and it would improve every result."""
    with pytest.raises(ValueError, match="delay_bars"):
        series([100, 110, 120, 130, 140], delay_bars=-1)


def test_the_delay_erodes_a_trending_series() -> None:
    """Direction check: on a decelerating uptrend, entering later earns less."""
    prices = [100, 200, 250, 275, 280]
    assert sum(series(prices, delay_bars=1)) < sum(series(prices))


# ------------------------------------------------- costs, so that "net" means net -----


def costed(prices: list[int], cost: float, delay_bars: int = 0) -> list[float]:
    panel, closes = panel_of(prices)
    return _pnl_series(
        panel,
        closes,
        STAMPS,
        object(),
        _Spec(),  # type: ignore[arg-type]
        compute_fn=always_long,  # type: ignore[arg-type]
        delay_bars=delay_bars,
        cost_per_round_trip=cost,
    )


def test_no_cost_is_the_default_and_the_existing_behaviour() -> None:
    """S1's own search calls this too; a default that charged would move its results."""
    assert costed([100, 110, 120, 130, 140], 0.0) == series([100, 110, 120, 130, 140])


def test_a_cost_is_charged_per_round_trip() -> None:
    """Every forecast here opens and closes within the bar, so each one is a round trip."""
    gross = series([100, 110, 120, 130, 140])
    net = costed([100, 110, 120, 130, 140], 0.001)
    assert net == pytest.approx([g - 0.001 for g in gross])


def test_nothing_is_charged_where_no_position_was_taken() -> None:
    """A forecast skipped for a missing price cost nothing, because nothing was traded.

    Charging per BAR, or per forecast EMITTED, would bill for trades that never happened — and
    on the last bars under a delay it would bill for every one of them.
    """
    net = costed([100, 110, 120, 130, 140], 0.001, delay_bars=1)
    assert net[-1] == 0.0, "the final decision has no exit bar, so it is not a trade"


def test_a_negative_cost_is_refused() -> None:
    """A negative cost pays the strategy to trade, and would make turnover a source of alpha."""
    with pytest.raises(ValueError, match="cost_per_round_trip"):
        costed([100, 110, 120, 130, 140], -0.001)


def test_net_never_exceeds_gross() -> None:
    prices = [100, 90, 130, 95, 140]
    assert sum(costed(prices, 0.002)) <= sum(series(prices))


def test_more_cost_is_never_better() -> None:
    """The 1.5x stress leans on this: raising the cost line must not raise the result."""
    prices = [100, 90, 130, 95, 140]
    assert sum(costed(prices, 0.003)) <= sum(costed(prices, 0.002))


# ------------------------------------------- one pass, every delay `[G-P4-DELAY1]` + 2x -----


def by_delay(prices: list[int], delays: tuple[int, ...]) -> dict[int, list[float]]:
    from pips.search.s1 import _pnl_by_delay

    panel, closes = panel_of(prices)
    out = _pnl_by_delay(
        panel,
        closes,
        STAMPS,
        object(),
        _Spec(),  # type: ignore[arg-type]
        compute_fn=always_long,  # type: ignore[arg-type]
        delays=delays,
    )
    return {d: gross for d, (gross, _turns, _per_name) in out.items()}


def test_one_pass_matches_a_pass_per_delay() -> None:
    """The justification for sharing the pass, stated as an equality.

    The decision is made from the as-of view at bar i whatever the delay; only which prices the
    position is opened and closed at moves. So the expensive half — building the view and
    calling the alpha — is identical across delays, and computing them separately repeats it.
    """
    prices = [100, 90, 130, 95, 140]
    shared = by_delay(prices, (0, 1, 2))

    assert shared[0] == pytest.approx(series(prices))
    assert shared[1] == pytest.approx(series(prices, delay_bars=1))
    assert shared[2] == pytest.approx(series(prices, delay_bars=2))


def test_the_alpha_is_called_once_per_bar_not_once_per_delay() -> None:
    """The point of the shared pass. Three delays must not mean three evaluations."""
    from pips.search.s1 import _pnl_by_delay

    calls: list[int] = []

    def counting(view: object, params: object, spec: object) -> list[object]:
        calls.append(1)
        return always_long(view, params, spec)

    panel, closes = panel_of([100, 110, 120, 130, 140])
    _pnl_by_delay(
        panel,
        closes,
        STAMPS,
        object(),
        _Spec(),  # type: ignore[arg-type]
        compute_fn=counting,  # type: ignore[arg-type]
        delays=(0, 1, 2),
    )
    assert len(calls) == len(STAMPS) - 1, "the alpha ran more than once per decision bar"


def test_a_repeated_delay_is_refused() -> None:
    """Silently deduping would return fewer entries than asked for, and a caller indexing the
    result by position would read the wrong delay's series."""
    with pytest.raises(ValueError, match="delays"):
        by_delay([100, 110, 120, 130, 140], (1, 1))


def test_no_delays_at_all_is_refused() -> None:
    with pytest.raises(ValueError, match="delays"):
        by_delay([100, 110, 120, 130, 140], ())


def test_the_attribution_rides_the_same_pass() -> None:
    """Whether one name dominates the P&L is a certification question (§12.2), and answering it
    in a second pass would re-run the alpha for a number the first pass already had."""
    from pips.search.s1 import _pnl_by_delay

    panel, closes = panel_of([100, 110, 120, 130, 140])
    out = _pnl_by_delay(
        panel,
        closes,
        STAMPS,
        object(),
        _Spec(),  # type: ignore[arg-type]
        compute_fn=always_long,  # type: ignore[arg-type]
        delays=(0,),
    )
    gross, turns, per_name = out[0]

    assert set(per_name) == {"SYM"}
    attributed, counted = per_name["SYM"]
    assert attributed == pytest.approx(sum(gross)), "attribution must sum to the total"
    assert counted == sum(turns), "and account for every round trip"
