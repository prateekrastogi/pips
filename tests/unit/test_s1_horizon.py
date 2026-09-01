"""Scoring at the horizon the forecast declared  (§6 M12, C2).

A01 emits a forecast with `valid_until_ns = decision_ts + horizon_ns`. `_evaluate` scored every
one of them against the NEXT BAR, whatever horizon it declared. While the smoke ran at a
one-minute horizon on a one-minute panel that was self-consistent by accident; the moment the
horizon moves into A01's pre-registered `hold_minutes: [15, 120]` it becomes a measurement of
something the forecast did not claim.

**The horizon is derived, not passed.** A separate `horizon_bars` argument beside `horizon_ns`
is two copies of one parameter, and the copy that drifts is the one nobody is looking at.

**Overlap is reported.** Fifteen-minute forecasts made every minute overlap fourteen-fifteenths
of the time, so the count of scored pairs overstates the evidence by roughly the horizon. A rank
IC computed over 1,800 heavily-overlapping pairs is not 1,800 observations' worth of anything.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from pips.alphas.spec import load_alpha_spec
from pips.alphas.t1.a01 import A01Params
from pips.search.s1 import _evaluate

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_alpha_spec(ROOT / "config" / "search_spaces" / "A01_residual_momentum.yaml")
NS = 1_000_000_000
MINUTE = 60 * NS


def panel(paths: dict[str, list[int]]) -> pl.DataFrame:
    rows = []
    n = len(next(iter(paths.values())))
    for i in range(n):
        for symbol, closes in paths.items():
            rows.append(
                {"close_ts_ns": (i + 1) * MINUTE, "symbol": symbol, "close_paise": closes[i]}
            )
    return pl.DataFrame(rows)


def fixture_panel(n: int = 80) -> tuple[pl.DataFrame, dict[str, dict[int, int]], list[int]]:
    a = [100_000 + ((i * 37) % 101 - 50) * 40 + i * 25 for i in range(n)]
    b = [100_000 + ((i * 53) % 101 - 50) * 40 - i * 15 for i in range(n)]
    frame = panel({"AAA": a, "BBB": b})
    stamps = sorted(set(frame["close_ts_ns"].to_list()))
    closes = {
        s: dict(
            zip(
                frame.filter(pl.col("symbol") == s)["close_ts_ns"].to_list(),
                frame.filter(pl.col("symbol") == s)["close_paise"].to_list(),
                strict=True,
            )
        )
        for s in ("AAA", "BBB")
    }
    return frame, closes, stamps


def params(horizon_minutes: int) -> A01Params:
    return A01Params(residual_lookback=3, scale_window=20, horizon_ns=horizon_minutes * MINUTE)


# ------------------------------------------------------------ the horizon -------------


def test_the_outcome_is_measured_at_the_declared_horizon() -> None:
    """Every outcome must be a move over exactly `horizon_ns`, not over one bar."""
    frame, closes, stamps = fixture_panel()
    _, outcomes, _ = _evaluate(frame, closes, stamps, params(5), SPEC, bar_interval_ns=MINUTE)

    assert outcomes
    five_bar_moves = {
        round((prices[stamps[i + 5]] - prices[stamps[i]]) / prices[stamps[i]], 12)
        for prices in closes.values()
        for i in range(len(stamps) - 5)
    }
    assert all(round(o, 12) in five_bar_moves for o in outcomes)


def test_changing_the_horizon_changes_the_outcomes() -> None:
    """Otherwise the declared horizon is decoration and the score means one bar, always."""
    frame, closes, stamps = fixture_panel()
    _, one, _ = _evaluate(frame, closes, stamps, params(1), SPEC, bar_interval_ns=MINUTE)
    _, five, _ = _evaluate(frame, closes, stamps, params(5), SPEC, bar_interval_ns=MINUTE)
    assert one != five


def test_bars_without_a_full_horizon_ahead_are_skipped() -> None:
    """Not measured against a truncated one, which would report a 5-minute forecast's result
    from a 2-minute move and quietly mix horizons inside one IC."""
    frame, closes, stamps = fixture_panel()
    _, long_h, _ = _evaluate(frame, closes, stamps, params(20), SPEC, bar_interval_ns=MINUTE)
    _, short_h, _ = _evaluate(frame, closes, stamps, params(5), SPEC, bar_interval_ns=MINUTE)
    assert len(long_h) < len(short_h), "a longer horizon leaves fewer scorable bars"


def test_a_horizon_that_is_not_a_whole_number_of_bars_is_refused() -> None:
    # Rounding would score a forecast against a window it did not declare, and the difference
    # would be invisible in the output.
    frame, closes, stamps = fixture_panel()
    with pytest.raises(ValueError, match="whole"):
        _evaluate(
            frame,
            closes,
            stamps,
            A01Params(residual_lookback=3, scale_window=20, horizon_ns=90 * NS),
            SPEC,
            bar_interval_ns=MINUTE,
        )


def test_a_zero_horizon_is_refused() -> None:
    frame, closes, stamps = fixture_panel()
    with pytest.raises(ValueError, match="positive"):
        _evaluate(
            frame,
            closes,
            stamps,
            A01Params(residual_lookback=3, scale_window=20, horizon_ns=0),
            SPEC,
            bar_interval_ns=MINUTE,
        )


# ------------------------------------------------------------ the smoke ---------------
#
# `run_s1_smoke` is a documented M12 Verify target and had NO test at all — which is how it ran
# outside its own spec's declared domain from M12 until now without anything noticing.


def test_the_smoke_conforms_to_the_pre_registered_domain() -> None:
    """It did not, from M12 until now: `hold_minutes: [15, 120]` declared, one minute run."""
    from pips.search.grid import assert_within_domain
    from pips.search.s1 import _HOLD_MINUTES

    assert_within_domain(SPEC, {"hold_minutes": _HOLD_MINUTES})
    low, _ = SPEC.parameter_domain["hold_minutes"]
    assert low <= _HOLD_MINUTES


def test_the_smoke_reports_overlap_beside_the_pair_count() -> None:
    """The pair count alone turns this run into a three-sigma result on a random walk.

    At a 15-minute horizon sampled every minute the smoke scores ~3,680 pairs and gets a rank IC
    of ~0.048. Read against 3,680 that is 2.9 standard errors — on two synthetic symbols from a
    seeded random walk, where the true IC is zero. Read against the ~245 non-overlapping windows
    those pairs actually represent, it is 0.76. Same number, same data, and only one of the two
    readings is available unless the report carries both.
    """
    from pips.search.s1 import run_s1_smoke

    report = run_s1_smoke(Path("fixtures"))
    pairs = int(str(report["scored_pairs"]))
    independent = int(str(report["independent_windows"]))

    assert independent > 0
    assert independent < pairs // 10, "a 15-minute horizon overlaps heavily by construction"
    assert pairs // independent >= int(str(report["hold_minutes"])) - 1


def test_the_smoke_itself_refuses_an_out_of_domain_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checking that the CONSTANT is in range does not check that the smoke checks it.

    `test_the_smoke_conforms_to_the_pre_registered_domain` calls `assert_within_domain` itself,
    so it passes with the guard deleted from `run_s1_smoke` entirely — it verifies today's value,
    not the thing that would catch tomorrow's. Deleting that guard is exactly how the horizon
    drifted out of domain for a whole milestone, so the guard is what gets tested here.
    """
    import pips.search.s1 as module
    from pips.search.s1 import run_s1_smoke

    monkeypatch.setattr(module, "_HOLD_MINUTES", 1)
    with pytest.raises(ValueError, match="hold_minutes"):
        run_s1_smoke(Path("fixtures"))
