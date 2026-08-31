"""Compute plugins for the momentum/reversal core: A02, A03, A04 (§6 M12).

Each test here targets the *mechanism the card claims*, not that the code runs. A plugin that
computes something plausible but does not implement its own hypothesis would pass a smoke test
and fail these — which is the only kind of test worth writing for an alpha.

The sharpest is `test_a03_contradicts_a01_on_the_same_data`: A01 claims residual CONTINUATION
and A03 claims residual REVERSAL. Two alphas making opposite claims about the same mechanism
must be visibly opposite. If they agree, at least one is not implementing its card.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any

import polars as pl
import pytest

from pips.alphas.spec import load_alpha_spec
from pips.alphas.t1 import a01, a02, a03, a04
from pips.core.asof import AsOfPanelView

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "config" / "search_spaces"
NS = 1_000_000_000


def panel(paths: dict[str, list[int]]) -> pl.DataFrame:
    rows = []
    n = len(next(iter(paths.values())))
    for i in range(n):
        for symbol, closes in paths.items():
            rows.append(
                {"close_ts_ns": (i + 1) * 60 * NS, "symbol": symbol, "close_paise": closes[i]}
            )
    return pl.DataFrame(rows)


def view_at(frame: pl.DataFrame, bar: int) -> AsOfPanelView:
    stamps = sorted(set(frame["close_ts_ns"].to_list()))
    return AsOfPanelView(frame, decision_ts=stamps[bar])


def diverging(n: int = 40) -> pl.DataFrame:
    """A rises, B falls, C flat — a clean residual dispersion."""
    return panel(
        {
            "A": [10_000 + 40 * i for i in range(n)],
            "B": [10_000 - 40 * i for i in range(n)],
            "C": [10_000 + (10 if i % 2 else -10) for i in range(n)],
        }
    )


def one_name_in_the_tail(n: int = 40) -> pl.DataFrame:
    """Five names, four alike and one genuinely extreme.

    A03 is gated on a cross-sectional TAIL, and `robust_z` scales by the MAD — so with only
    three names nothing can reach 1.5 and A03 is structurally silent. Testing it would then
    require a tail below its own pre-registered domain of 1.5-3.5, which would be testing a
    configuration the spec forbids. Five names give the cross-section room to have a tail.
    """
    quiet = {
        f"Q{k}": [10_000 + (3 * k) * i + (i * (7 * k + 11) % 40) for i in range(n)]
        for k in range(4)
    }
    return panel({**quiet, "SHOCK": [10_000 + 260 * i for i in range(n)]})


# ------------------------------------------------------------------ A02 ----------------


def test_a02_works_on_a_single_symbol() -> None:
    # A02 is TIME-SERIES momentum: "continuation in each instrument's OWN return process".
    # Unlike A01 it needs no cross-section, and requiring one would mean it had been built
    # as a cross-sectional alpha wearing A02's name.
    spec = load_alpha_spec(SPECS / "A02_ts_momentum.yaml")
    frame = panel({"A": [10_000 + 40 * i for i in range(40)]})
    forecasts = a02.compute(
        view_at(frame, 35),
        a02.A02Params(lookbacks=(5, 10), vol_window=20, horizon_ns=60 * NS),
        spec,
    )
    assert len(forecasts) == 1
    assert forecasts[0].instrument_id == "A"


def test_a02_scales_by_volatility_so_a_noisy_name_does_not_dominate() -> None:
    # The card: "scaled so high-volatility names do not mechanically dominate". Two names
    # with the same drift but very different volatility must not be ranked by volatility.
    spec = load_alpha_spec(SPECS / "A02_ts_momentum.yaml")
    quiet = [10_000 + 40 * i for i in range(40)]
    loud = [10_000 + 40 * i + (600 if i % 2 else -600) for i in range(40)]
    frame = panel({"QUIET": quiet, "LOUD": loud})
    params = a02.A02Params(lookbacks=(5, 10), vol_window=20, horizon_ns=60 * NS)
    scores = {
        f.instrument_id: f.expected_return_bps
        for f in a02.compute(view_at(frame, 35), params, spec)
    }
    # Same drift: the vol-scaled scores must be far closer than the raw drifts' vol ratio.
    assert scores["QUIET"] > 0 and scores["LOUD"] > 0
    assert abs(scores["QUIET"] - scores["LOUD"]) < abs(scores["QUIET"]) * 2


def test_a02_requires_at_least_two_predeclared_horizons() -> None:
    # The card's falsifier: "reject if only one lookback works". A single-lookback A02 cannot
    # even be evaluated against that condition.
    with pytest.raises(ValueError, match="lookback"):
        a02.A02Params(lookbacks=(5,), vol_window=20, horizon_ns=60 * NS)


# ------------------------------------------------------------------ A03 ----------------


def test_a03_contradicts_a01_on_the_same_data() -> None:
    """A01 claims residual continuation; A03 claims residual reversal.

    Two alphas making opposite claims about the same mechanism must be visibly opposite on
    the same input. If they agreed, at least one would not be implementing its own card —
    and both would still pass every smoke test.
    """
    a01_spec = load_alpha_spec(SPECS / "A01_residual_momentum.yaml")
    a03_spec = load_alpha_spec(SPECS / "A03_cs_reversal.yaml")
    frame = one_name_in_the_tail()
    v = view_at(frame, 35)

    cont = {
        f.instrument_id: f.expected_return_bps
        for f in a01.compute(v, a01.A01Params(5, 20, 60 * NS), a01_spec)
    }
    rev = {
        f.instrument_id: f.expected_return_bps
        for f in a03.compute(
            v, a03.A03Params(shock_window=5, tail=1.5, horizon_ns=60 * NS), a03_spec
        )
    }

    # Compare only where BOTH spoke: A03 is gated on a tail and stays silent otherwise, and
    # silence is not agreement.
    compared = 0
    for symbol in cont:
        if cont[symbol] != 0 and rev[symbol] != 0:
            compared += 1
            assert (cont[symbol] > 0) != (rev[symbol] > 0), (
                f"{symbol}: continuation {cont[symbol]} and reversal {rev[symbol]} agree in "
                "sign — one of these alphas is not implementing its card"
            )
    assert compared >= 2, "the fixture must make both alphas speak, or this proves nothing"


def test_a03_only_fires_on_a_tail_shock() -> None:
    # The card gates on an EXTREME recent residual move. A name drifting gently is not a
    # liquidity shock, and treating it as one would make A03 an always-on contrarian.
    spec = load_alpha_spec(SPECS / "A03_cs_reversal.yaml")
    gentle = panel(
        {s: [10_000 + (3 if s == "A" else -3) * i for i in range(40)] for s in ("A", "B", "C")}
    )
    params = a03.A03Params(shock_window=5, tail=3.5, horizon_ns=60 * NS)
    forecasts = a03.compute(view_at(gentle, 35), params, spec)
    assert all(f.expected_return_bps == 0 for f in forecasts), "no tail shock, no reversal claim"


# ------------------------------------------------------------------ A04 ----------------


def test_a04_points_back_toward_the_factor_manifold() -> None:
    # The card: the conditional error-correction response of a factor-relative state. A name
    # pushed ABOVE the manifold must forecast a move back DOWN, and vice versa.
    spec = load_alpha_spec(SPECS / "A04_residual_reversion.yaml")
    n = 40
    base = [10_000 for _ in range(n)]
    # The jump lands at bar 30, INSIDE the view at bar 35. An earlier draft put it at bar 37
    # and the view could not see it — the as-of guard doing its job on my own test.
    dislocated = [10_000 + (900 if i >= 30 else 0) for i in range(n)]
    frame = panel({"HIGH": dislocated, "B": base, "C": base})
    params = a04.A04Params(z_window=20, entry_z=1.0, exit_z=0.0, horizon_ns=60 * NS)
    scores = {
        f.instrument_id: f.expected_return_bps
        for f in a04.compute(view_at(frame, 35), params, spec)
    }
    assert scores["HIGH"] < 0, "a name above the manifold must forecast reversion downward"


def test_a04_is_not_unconditional_moving_average_reversion() -> None:
    """The card is explicit: the estimand is the CONDITIONAL error-correction response, "not
    the unconditional tendency of a return or price to revisit a moving average".

    A steadily trending name is always above its own moving average, so an MA-reversion
    implementation would short it forever. Under a factor-relative state it is not dislocated
    at all when its peers trend with it — and must produce no signal.
    """
    spec = load_alpha_spec(SPECS / "A04_residual_reversion.yaml")
    trending = panel({s: [10_000 + 40 * i for i in range(40)] for s in ("A", "B", "C")})
    params = a04.A04Params(z_window=20, entry_z=1.0, exit_z=0.0, horizon_ns=60 * NS)
    scores = [f.expected_return_bps for f in a04.compute(view_at(trending, 35), params, spec)]
    assert all(s == 0 for s in scores), (
        "every name trending together is dislocated from nothing — an MA-reversion "
        "implementation would short them all"
    )


def test_a04_stays_flat_inside_the_band() -> None:
    # A fixture with real dispersion. `diverging()` is a perfectly linear divergence, so its
    # per-bar residual is near-constant, its sigma near-zero and its z enormous — a
    # pathological synthetic, not a wide band. Deterministic wiggle keeps z single-digit.
    spec = load_alpha_spec(SPECS / "A04_residual_reversion.yaml")
    frame = panel(
        {
            "A": [10_000 + 40 * i + (i * 37 % 300) for i in range(40)],
            "B": [10_000 - 40 * i + (i * 53 % 300) for i in range(40)],
            "C": [10_000 + (i * 71 % 300) for i in range(40)],
        }
    )
    wide = a04.A04Params(z_window=20, entry_z=99.0, exit_z=0.0, horizon_ns=60 * NS)
    scores = [f.expected_return_bps for f in a04.compute(view_at(frame, 35), wide, spec)]
    assert scores, "the fixture must produce forecasts, or this proves nothing"
    assert all(s == 0 for s in scores)


# ------------------------------------------------------- shared contract ----------------


@pytest.mark.parametrize(
    ("module", "params", "spec_file"),
    [
        (
            a02,
            a02.A02Params(lookbacks=(5, 10), vol_window=20, horizon_ns=60 * NS),
            "A02_ts_momentum.yaml",
        ),
        (a03, a03.A03Params(shock_window=5, tail=1.5, horizon_ns=60 * NS), "A03_cs_reversal.yaml"),
        (
            a04,
            a04.A04Params(z_window=20, entry_z=1.0, exit_z=0.0, horizon_ns=60 * NS),
            "A04_residual_reversion.yaml",
        ),
    ],
    ids=["A02", "A03", "A04"],
)
def test_every_plugin_is_deterministic_and_reads_through_the_view(
    module: ModuleType, params: Any, spec_file: str
) -> None:
    spec = load_alpha_spec(SPECS / spec_file)
    frame = diverging()
    v1, v2 = view_at(frame, 35), view_at(frame, 35)
    assert [f.model_dump() for f in module.compute(v1, params, spec)] == [
        f.model_dump() for f in module.compute(v2, params, spec)
    ]
    assert v1.accessed_fields, "the plugin must read through the view"


@pytest.mark.parametrize(
    ("module", "params", "spec_file"),
    [
        (
            a02,
            a02.A02Params(lookbacks=(5, 10), vol_window=20, horizon_ns=60 * NS),
            "A02_ts_momentum.yaml",
        ),
        (a03, a03.A03Params(shock_window=5, tail=1.5, horizon_ns=60 * NS), "A03_cs_reversal.yaml"),
        (
            a04,
            a04.A04Params(z_window=20, entry_z=1.0, exit_z=0.0, horizon_ns=60 * NS),
            "A04_residual_reversion.yaml",
        ),
    ],
    ids=["A02", "A03", "A04"],
)
def test_insufficient_warmup_yields_silence(
    module: ModuleType, params: Any, spec_file: str
) -> None:
    spec = load_alpha_spec(SPECS / spec_file)
    assert module.compute(view_at(diverging(), 2), params, spec) == []
