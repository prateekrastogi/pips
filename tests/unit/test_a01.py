"""A01 residual momentum compute plugin (§3.2, reference A01 card).

The plugin contract: ``compute(view, params) -> forecasts`` is **pure, deterministic and
warm-up-declared** (§3.2). The semantic test that matters is the neutralization claim: A01
asserts *idiosyncratic* continuation, so a name that moves exactly with the cross-section must
produce no signal. An implementation that scored raw returns would pass a smoke test and fail
this one.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from pips.alphas.spec import load_alpha_spec
from pips.alphas.t1.a01 import A01Params, compute
from pips.core.asof import AsOfPanelView

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_alpha_spec(ROOT / "config" / "search_spaces" / "A01_residual_momentum.yaml")
NS = 1_000_000_000
PARAMS = A01Params(residual_lookback=3, scale_window=5, horizon_ns=60 * NS)


def panel(paths: dict[str, list[int]]) -> pl.DataFrame:
    rows = []
    n = len(next(iter(paths.values())))
    for i in range(n):
        for symbol, closes in paths.items():
            rows.append(
                {"close_ts_ns": (i + 1) * 60 * NS, "symbol": symbol, "close_paise": closes[i]}
            )
    return pl.DataFrame(rows)


def rising_and_falling(n: int = 20) -> pl.DataFrame:
    return panel(
        {
            "A": [10_000 + 50 * i for i in range(n)],
            "B": [10_000 - 50 * i for i in range(n)],
            "C": [10_000 for _ in range(n)],
        }
    )


def view_at(frame: pl.DataFrame, bar: int) -> AsOfPanelView:
    stamps = sorted(set(frame["close_ts_ns"].to_list()))
    return AsOfPanelView(frame, decision_ts=stamps[bar])


# ------------------------------------------------------------- the contract -------------


def test_compute_is_deterministic() -> None:
    frame = rising_and_falling()
    a = compute(view_at(frame, 15), PARAMS, SPEC)
    b = compute(view_at(frame, 15), PARAMS, SPEC)
    assert [f.model_dump() for f in a] == [f.model_dump() for f in b]


def test_insufficient_warmup_yields_no_forecast_not_a_zero() -> None:
    # §3.2's missingness policy: "insufficient warmup => no forecast, not a zero". A zero is
    # a claim that the expected return is zero; silence is the honest output.
    assert compute(view_at(rising_and_falling(), 1), PARAMS, SPEC) == []


def test_forecasts_carry_the_strategy_and_family_id() -> None:
    forecasts = compute(view_at(rising_and_falling(), 15), PARAMS, SPEC)
    assert forecasts
    for f in forecasts:
        assert f.family_id == "A01"
        assert f.strategy_id == "A01@1.0.0"


def test_the_decision_timestamp_is_the_view_not_the_wall_clock() -> None:
    frame = rising_and_falling()
    v = view_at(frame, 15)
    for f in compute(v, PARAMS, SPEC):
        assert f.decision_ts == v.decision_ts
        assert f.valid_until_ns > f.decision_ts


def test_it_reads_only_through_the_view() -> None:
    v = view_at(rising_and_falling(), 15)
    compute(v, PARAMS, SPEC)
    assert v.accessed_fields, "the plugin must read through the view, so accesses are audited"


# ------------------------------------------------- the neutralization claim -------------


def test_a_name_moving_with_the_cross_section_produces_no_signal() -> None:
    # A01 claims IDIOSYNCRATIC continuation. If every name moves identically, the residual is
    # zero and there is nothing to forecast. An implementation scoring raw returns would
    # produce a strong signal here — which is exactly the mechanism the card denies.
    frame = panel({s: [10_000 + 50 * i for i in range(20)] for s in ("A", "B", "C")})
    forecasts = compute(view_at(frame, 15), PARAMS, SPEC)
    assert all(abs(f.expected_return_bps) < 1 for f in forecasts), (
        "a common move must leave no residual momentum"
    )


def test_a_divergent_name_is_ranked_against_its_peers() -> None:
    forecasts = {
        f.instrument_id: f for f in compute(view_at(rising_and_falling(), 15), PARAMS, SPEC)
    }
    assert forecasts["A"].expected_return_bps > forecasts["B"].expected_return_bps


def test_a_universe_too_small_for_a_cross_section_is_refused() -> None:
    # A cross-sectional score over one name is not a cross-section. Returning something
    # anyway would put a meaningless number into the funnel.
    frame = panel({"A": [10_000 + 50 * i for i in range(20)]})
    with pytest.raises(ValueError, match="cross-section"):
        compute(view_at(frame, 15), PARAMS, SPEC)
