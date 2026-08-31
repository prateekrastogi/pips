"""S1 smoke run -- the whole funnel end to end on fixtures (§6 M12 Verify, §4).

Proves the *pipeline* runs: load fixtures, build a panel, walk decision bars behind the as-of
view, compute a pre-registered alpha, score it against realised next-bar returns, and put the
result through its shuffled-future control.

**It does not claim an edge, and says so in its own output.** The smoke fixtures are two
synthetic symbols from a seeded random walk; a cross-section of two is degenerate and there is
no market structure to find. A smoke run that reported an encouraging IC would be the most
misleading artefact in the repository, so the number is printed with what it is worth attached.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl

from pips.alphas.spec import load_alpha_spec
from pips.alphas.t1.a01 import A01Params, compute
from pips.core.asof import AsOfPanelView
from pips.validation.nulls import rank_ic, shuffled_future_control

__all__ = ["main", "run_s1_smoke"]

NS = 1_000_000_000
_SPEC = Path("config/search_spaces/A01_residual_momentum.yaml")


def _load_panel(fixtures: Path) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for path in sorted((fixtures / "bars" / "1m").glob("*.json")):
        for bar in json.loads(path.read_text(encoding="utf-8")):
            rows.append(
                {
                    "close_ts_ns": int(bar["close_ts_ns"]),
                    "symbol": str(bar["symbol"]),
                    "close_paise": int(bar["close_paise"]),
                }
            )
    if not rows:
        raise FileNotFoundError(f"no 1m fixtures under {fixtures} — run `make fixtures`")
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


def run_s1_smoke(fixtures: Path, spec_path: Path = _SPEC) -> dict[str, object]:
    """Run A01 across the fixture panel and return the smoke report."""
    spec = load_alpha_spec(spec_path)
    params = A01Params(residual_lookback=5, scale_window=20, horizon_ns=60 * NS)
    panel = _load_panel(fixtures)

    stamps = sorted(set(panel["close_ts_ns"].to_list()))
    closes = {
        s: dict(
            zip(
                panel.filter(pl.col("symbol") == s)["close_ts_ns"].to_list(),
                panel.filter(pl.col("symbol") == s)["close_paise"].to_list(),
                strict=True,
            )
        )
        for s in sorted(set(panel["symbol"].to_list()))
    }

    scores: list[float] = []
    outcomes: list[float] = []
    n_forecasts = 0

    for i, ts in enumerate(stamps[:-1]):
        view = AsOfPanelView(panel, decision_ts=ts)
        for forecast in compute(view, params, spec):
            n_forecasts += 1
            series = closes[forecast.instrument_id]
            here, nxt = series.get(ts), series.get(stamps[i + 1])
            if here in (None, 0) or nxt is None:
                continue
            scores.append(float(forecast.expected_return_bps))
            outcomes.append((nxt - here) / here)

    report: dict[str, object] = {
        "spec": spec.strategy_id,
        "spec_hash": spec.short_id(),
        "bars": len(stamps),
        "symbols": sorted(closes),
        "forecasts": n_forecasts,
        "scored_pairs": len(scores),
    }
    if len(scores) >= 20:
        control = shuffled_future_control(
            np.array(scores), np.array(outcomes), n_permutations=200, seed=1407
        )
        report["rank_ic"] = str(control.observed_ic)
        report["p_value"] = str(control.p_value)
        shuffled_mean = abs(
            sum(control.shuffled_ics, Decimal(0)) / Decimal(len(control.shuffled_ics))
        )
        report["shuffled_mean"] = str(shuffled_mean)
        # A principled bound, not a round number. Under a destroyed relationship the mean
        # |rank IC| is O(1/sqrt(n)); 5x that is generous and still catches a harness that is
        # misaligning scores with outcomes. A threshold of "< 1" would have passed anything,
        # which is the vacuous-check failure this project keeps finding in its own work.
        bound = Decimal(5) / Decimal(len(scores)).sqrt()
        report["harness_self_test"] = (
            f"OK (shuffled mean |IC| {shuffled_mean:.4f} < bound {bound:.4f})"
            if shuffled_mean < bound
            else f"SUSPECT: shuffled mean |IC| {shuffled_mean:.4f} exceeds {bound:.4f} — the "
            "harness may be misaligning scores and outcomes"
        )
        report["_self_test_passed"] = shuffled_mean < bound
        report["observed_ic_raw"] = f"{rank_ic(np.array(scores), np.array(outcomes)):.4f}"
    return report


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    fixtures = Path(args[0]) if args else Path("fixtures")
    try:
        report = run_s1_smoke(fixtures)
    except (FileNotFoundError, ValueError) as exc:
        print(f"s1-smoke FAILED: {exc}")
        return 1

    print("s1-smoke: the S1 pipeline ran end to end on fixtures")
    for key, value in report.items():
        if not key.startswith("_"):
            print(f"  {key}: {value}")

    if report.get("_self_test_passed") is False:
        print("\ns1-smoke FAILED: the null control's own self-test did not hold.")
        return 1
    print(
        "\n  WHAT THIS IS NOT: an edge. The fixtures are two synthetic symbols from a seeded\n"
        "  random walk, so there is no market structure to find and a cross-section of two is\n"
        "  degenerate. Any IC above is noise. This target proves the funnel is WIRED —\n"
        "  as-of view -> pre-registered spec -> compute -> forecast -> scoring -> null control\n"
        "  — which is what §6 M12 asks it to prove."
    )
    return 0
