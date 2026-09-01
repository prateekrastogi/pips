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
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np
import polars as pl

from pips.alphas.spec import AlphaSpec, load_alpha_spec
from pips.alphas.t1._common import IST
from pips.alphas.t1.a01 import A01Params, compute
from pips.core.asof import AsOfPanelView
from pips.search.grid import assert_within_domain, bars_per_unit, grid_from_domain
from pips.search.halving import successive_halving
from pips.search.multiplicity import multiplicity
from pips.search.registry import Registry
from pips.search.trials import TrialContext, fixture_snapshot_root, record_halving_trials
from pips.validation.fdr import benjamini_hochberg
from pips.validation.nulls import rank_ic, shuffled_future_control

if TYPE_CHECKING:
    from pips.data.lockbox import SealedLockbox

__all__ = [
    "apply_family_fdr",
    "enumerate_specs",
    "main",
    "run_s1_smoke",
    "specs_with_plugins",
]

NS = 1_000_000_000
_SPEC = Path("config/search_spaces/A01_residual_momentum.yaml")


def specs_with_plugins() -> set[str]:
    """Spec ids that have a compute plugin, DERIVED from the package rather than listed.

    This was a hardcoded ``{"A01", "A02", "A03", "A04"}``. A hand-maintained list beside the
    thing it describes is the drift that has already been caught twice in this repository —
    once between the registry's DDL and its model, once between the deploy rail's service list
    and compose. The smoke report's headline claim is *which alphas can actually run*, and a
    stale list makes that claim wrong in the more flattering direction.
    """
    import pkgutil

    import pips.alphas.t1 as t1_package

    return {
        module.name.upper()
        for module in pkgutil.iter_modules(t1_package.__path__)
        if not module.name.startswith("_")
    }


def enumerate_specs(spec_dir: Path) -> list[AlphaSpec]:
    """Every pre-registered AlphaSpec, in id order.

    Loading is validation, so a spec that has lost its falsifiers cannot be swept — it fails
    here rather than producing a result nobody could reject.
    """
    return sorted((load_alpha_spec(path) for path in spec_dir.glob("A*.yaml")), key=lambda s: s.id)


def apply_family_fdr(candidates: list[dict[str, object]], q: float) -> list[dict[str, object]]:
    """BH-FDR **within family x universe** (§6 M13).

    The grouping is the design, not a detail. Pooling every family into one correction would
    penalise a family for tests another family ran; correcting nothing would promote the best
    of N. Each candidate keeps its group key so a report can show which bar it cleared.
    """
    groups: dict[tuple[object, object], list[int]] = {}
    for i, candidate in enumerate(candidates):
        groups.setdefault((candidate["family"], candidate["universe"]), []).append(i)

    out = [dict(c) for c in candidates]
    for indices in groups.values():
        rejected = benjamini_hochberg([float(candidates[i]["p_value"]) for i in indices], q=q)  # type: ignore[arg-type]
        for i, survives in zip(indices, rejected, strict=True):
            out[i]["survives"] = survives
            out[i]["n_tests_in_group"] = len(indices)
    return out


def load_panel(
    fixtures: Path, lockbox: SealedLockbox | None = None, stage: str | None = None
) -> pl.DataFrame:
    """Load the fixture panel, consulted against the sealed lockbox when one is configured.

    The lockbox is checked HERE, at the read, because that is the only place it can bite. A
    holdout enforced anywhere else is a convention, and `check_unexplained_ratio_jump` already
    demonstrated what happens to a check nothing calls: written at M5, unit-tested, and never
    invoked by the runner for an entire milestone.

    ``lockbox=None`` means no holdout has been DECLARED, which is a different thing from a
    holdout that permits everything — and the default must not quietly become the latter.
    """
    rows: list[dict[str, object]] = []
    for path in sorted((fixtures / "bars" / "1m").glob("*.json")):
        for bar in json.loads(path.read_text(encoding="utf-8")):
            rows.append(
                {
                    "close_ts_ns": int(bar["close_ts_ns"]),
                    "symbol": str(bar["symbol"]),
                    "close_paise": int(bar["close_paise"]),
                    # Carried because the session-structure family (A05-A08) needs it. The
                    # fixtures always had it; this loader was dropping it on the floor.
                    "volume": int(bar["volume"]),
                }
            )
    if not rows:
        raise FileNotFoundError(f"no 1m fixtures under {fixtures} — run `make fixtures`")

    if lockbox is not None:
        if stage is None:
            raise ValueError(
                "a lockbox was supplied without a stage. A read of unknown provenance cannot "
                "be authorised against a holdout, and defaulting the stage would authorise it."
            )
        stamps = [int(r["close_ts_ns"]) for r in rows]  # type: ignore[call-overload]
        first = datetime.fromtimestamp(min(stamps) / 1e9, IST).date()
        last = datetime.fromtimestamp(max(stamps) / 1e9, IST).date()
        lockbox.check(stage=stage, start=first, end=last + timedelta(days=1))

    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


_load_panel = load_panel


def _evaluate(
    panel: pl.DataFrame,
    closes: dict[str, dict[int, int]],
    stamps: list[int],
    params: A01Params,
    spec: AlphaSpec,
) -> tuple[list[float], list[float], int]:
    """Score every forecast against the NEXT bar's realised move, as-of at each decision.

    Shared by the smoke and the recorded search: two copies of a causality-sensitive loop is two
    places for the AsOf discipline to drift, and only one of them would be the one under test.
    """
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
    return scores, outcomes, n_forecasts


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

    scores, outcomes, n_forecasts = _evaluate(panel, closes, stamps, params, spec)

    registered = enumerate_specs(spec_path.parent)
    with_plugin = specs_with_plugins()
    report: dict[str, object] = {
        "specs_registered": len(registered),
        "specs_with_a_compute_plugin": sorted(with_plugin),
        "specs_awaiting_a_plugin": sorted({s.id for s in registered} - with_plugin),
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


_GRID_POINTS: Final = 4
_INITIAL_BUDGET: Final = 400
"""Bars in the first rung. With eta=2 and four candidates the ladder is 4@400, 2@800, 1@1600 —
inside the 1875-bar fixture panel, so the final rung is never silently truncated."""

_SCALE_WINDOW_M: Final = 20
_HOLD_MINUTES: Final = 15
"""The declared floor of A01's `hold_minutes: [15, 120]`.

NOT the one minute the smoke uses. A parameter outside the pre-registered domain cannot be
rejected by the falsifiers attached to that spec, because they were written for the declared
space — and it looks exactly like a parameter inside it. `assert_within_domain` now refuses it.
"""


def _params_for(config: str, bars: int) -> A01Params:
    """`bars` converts the spec's MINUTES into panel bars; they coincide only at one-minute."""
    return A01Params(
        residual_lookback=int(config.rsplit("-lb", 1)[1]) * bars,
        scale_window=_SCALE_WINDOW_M * bars,
        horizon_ns=_HOLD_MINUTES * 60 * NS,
    )


def _pnl_series(
    panel: pl.DataFrame,
    closes: dict[str, dict[int, int]],
    stamps: list[int],
    params: A01Params,
    spec: AlphaSpec,
) -> list[float]:
    """Per-bar realised PnL of taking every forecast's sign, zero where there was no forecast.

    Zero-filled rather than compacted, so every config's series has the same length at the same
    budget whatever its warm-up costs it. Compacting would make the series lengths depend on the
    parameter, and correlating those would need a truncation that aligns at index 0.
    """
    series = [0.0] * (len(stamps) - 1)
    for i, ts in enumerate(stamps[:-1]):
        view = AsOfPanelView(panel, decision_ts=ts)
        for forecast in compute(view, params, spec):
            prices = closes[forecast.instrument_id]
            here, nxt = prices.get(ts), prices.get(stamps[i + 1])
            if here in (None, 0) or nxt is None:
                continue
            direction = 1.0 if float(forecast.expected_return_bps) >= 0 else -1.0
            series[i] += direction * (nxt - here) / here
    return series


def run_s1_search(
    *,
    fixtures: Path,
    registry: Registry,
    returns_dir: Path,
    spec_path: Path = _SPEC,
) -> dict[str, object]:
    """Run successive halving over A01 variants on the fixtures and RECORD every look.

    The point is not the winner. The fixtures are two synthetic symbols from a seeded random
    walk, so any IC is noise — and a search over noise returns a winner with a flattering score
    every time. That is precisely what §3.6 deflates, so the report carries the multiplicity
    bracket beside the winner's raw score and never the raw score alone.
    """
    spec = load_alpha_spec(spec_path)
    panel = load_panel(fixtures)
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
    # The grid comes from the spec's pre-registered `parameter_domain`, not from a tuple in
    # this file. A hardcoded grid is a sweep over a space nobody registered: the one this
    # replaced was (3, 5, 8, 13), the bottom eleven percent of a domain declared as [3, 120].
    interval = stamps[1] - stamps[0]
    bars = bars_per_unit(interval)
    lookbacks = grid_from_domain(spec, "residual_lookback_m", count=_GRID_POINTS)
    assert_within_domain(spec, {"scale_window_m": _SCALE_WINDOW_M, "hold_minutes": _HOLD_MINUTES})
    candidates = tuple(f"a01-lb{n}" for n in lookbacks)

    # Memoised so `metrics_for` reports the score that actually DECIDED the elimination rather
    # than a recomputation of it — and so the search does not evaluate every rung twice.
    seen: dict[tuple[str, int], Decimal] = {}

    def score(config: str, budget: int) -> Decimal:
        key = (config, budget)
        if key not in seen:
            scores, outcomes, _ = _evaluate(
                panel, closes, stamps[:budget], _params_for(config, bars), spec
            )
            seen[key] = (
                Decimal(str(rank_ic(np.array(scores), np.array(outcomes))))
                if len(scores) >= 2
                else Decimal(0)
            )
        return seen[key]

    result = successive_halving(candidates, score, initial_budget=_INITIAL_BUDGET, eta=2)

    def metrics_for(config: str, budget: int) -> dict[str, float]:
        return {"rank_ic": float(score(config, budget)), "budget_bars": float(budget)}

    pnl: dict[str, list[float]] = {}

    def returns_for(config: str, budget: int) -> np.ndarray:
        # The FULL window, not `stamps[:budget]`. A config's return stream is a property of the
        # config, not of how long the search looked at it -- and equal lengths are what make the
        # series correlatable at all. Two rungs of one config then preserve identical series,
        # which is correct: M_erank counts them as one effective trial while M counts both
        # looks, and that gap is exactly what the bracket is for.
        del budget
        if config not in pnl:
            pnl[config] = _pnl_series(panel, closes, stamps, _params_for(config, bars), spec)
        return np.array(pnl[config])

    recorded = record_halving_trials(
        registry,
        result,
        metrics_for=metrics_for,
        context=TrialContext(
            stage="S1",
            stage_rank=1,
            family="A01",
            data_snapshot=f"fixtures@{fixtures.name}",
            snapshot_root=fixture_snapshot_root(fixtures),
            cost_model="0" * 64,
            fill_tier="F1",
            git_sha="0" * 40,
            universe_id="FIXTURES",
            session_mask="ALL",
            capital_tier="2L",
            broker="NONE",
        ),
        returns_for=returns_for,
        returns_dir=returns_dir,
    )

    counts = multiplicity(registry)
    return {
        "candidates": len(candidates),
        "rounds": len(result.rounds),
        "trials_viewed": result.trials_viewed,
        "rows_recorded": recorded.rows,
        "completed": recorded.completed,
        "viewed": recorded.viewed,
        "winner": result.winner,
        "winner_score": str(score(result.winner, result.rounds[-1].budget))
        if result.winner
        else None,
        "multiplicity_literal": counts.literal_count,
        "multiplicity_effective": (
            f"{counts.effective_count:.3f}" if counts.effective_count is not None else None
        ),
        "_is_an_edge": False,
    }


def search_main(argv: list[str] | None = None) -> int:
    """``pips s1-search <fixtures> <registry.db> <returns-dir>`` — run and record a search."""
    args = list(argv if argv is not None else sys.argv[1:])
    fixtures = Path(args[0]) if args else Path("fixtures")
    db = Path(args[1]) if len(args) > 1 else Path("build/s1-search/registry.db")
    returns = Path(args[2]) if len(args) > 2 else db.parent / "returns"
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        report = run_s1_search(fixtures=fixtures, registry=Registry(db), returns_dir=returns)
    except (FileNotFoundError, ValueError) as exc:
        print(f"s1-search FAILED: {exc}")
        return 1

    print("s1-search: successive halving over A01 variants, every look recorded")
    for key, value in report.items():
        if not key.startswith("_"):
            print(f"  {key}: {value}")
    print(
        "\n  WHAT THIS IS NOT: an edge. The fixtures are two synthetic symbols from a seeded\n"
        "  random walk, so the winner's rank IC is noise — and a search over noise returns a\n"
        "  flattering winner every time. That is the point: the multiplicity bracket above is\n"
        "  computed from trials this run actually recorded, so §3.6's deflation is operating on\n"
        "  a real ledger for the first time rather than on an empty one."
    )
    return 0
