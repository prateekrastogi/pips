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
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np
import polars as pl

from pips.alphas.forecast import Forecast
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


def _check_lockbox(stamps: list[int], lockbox: SealedLockbox | None, stage: str | None) -> None:
    """Authorise a read against the holdout. ONE implementation, shared by every loader.

    The check lives at the read because that is the only place it can bite. Two loaders with two
    copies of the rule is two places for it to drift, and only one of them would be the one
    under test — so a second reader calls this rather than reimplementing it.

    ``lockbox=None`` means no holdout has been DECLARED, which is a different thing from a
    holdout that permits everything, and the default must not quietly become the latter.
    """
    if lockbox is None:
        return
    if stage is None:
        raise ValueError(
            "a lockbox was supplied without a stage. A read of unknown provenance cannot "
            "be authorised against a holdout, and defaulting the stage would authorise it."
        )
    first = datetime.fromtimestamp(min(stamps) / 1e9, IST).date()
    last = datetime.fromtimestamp(max(stamps) / 1e9, IST).date()
    lockbox.check(stage=stage, start=first, end=last + timedelta(days=1))


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
            # EVERY field the bar carries, not a subset chosen by whoever last needed one.
            # This loader already bore a note about volume -- "the fixtures always had it; this
            # loader was dropping it on the floor" -- and open, high and low were still being
            # dropped, which cost A07 its place in the search: it was recorded as not runnable
            # because "the panel has no high_paise, low_paise", true of the panel and false of
            # the fixtures. An alpha excluded for a reason that is not true is worse than one
            # excluded for a reason that is, because the reason reads as a fact about the data.
            rows.append(
                {
                    "close_ts_ns": int(bar["close_ts_ns"]),
                    "symbol": str(bar["symbol"]),
                    **{
                        key: int(value)
                        for key, value in bar.items()
                        if key not in ("close_ts_ns", "symbol")
                    },
                }
            )
    if not rows:
        raise FileNotFoundError(f"no 1m fixtures under {fixtures} — run `make fixtures`")

    _check_lockbox([int(str(r["close_ts_ns"])) for r in rows], lockbox, stage)
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


_load_panel = load_panel


_SCALE_WINDOW_M: Final = 20
_HOLD_MINUTES: Final = 15
"""The declared floor of A01's `hold_minutes: [15, 120]`.

NOT the one minute this file used from M12 until now. A parameter outside the pre-registered
domain cannot be rejected by the falsifiers attached to that spec — they were written for the
declared space — and it looks exactly like a parameter inside it.
"""


def _evaluate(
    panel: pl.DataFrame,
    closes: dict[str, dict[int, int]],
    stamps: list[int],
    params: object,
    spec: AlphaSpec,
    *,
    bar_interval_ns: int,
    compute_fn: ComputeFn = compute,
) -> tuple[list[float], list[float], int]:
    """Score every forecast against the move over the horizon it DECLARED, as-of at each decision.

    The horizon is DERIVED from ``params.horizon_ns``, never passed alongside it: two copies of
    one parameter drift, and the copy that drifts is the one nobody is looking at. A forecast
    carries ``valid_until_ns = decision_ts + horizon_ns``, so that is the window its result has
    to be read over — scoring it against the next bar measures something the forecast did not
    claim, and the number looks exactly the same.

    Shared by the smoke and the recorded search: two copies of a causality-sensitive loop is two
    places for the AsOf discipline to drift, and only one of them would be the one under test.
    """
    horizon_ns = int(params.horizon_ns)  # type: ignore[attr-defined]
    if horizon_ns <= 0:
        raise ValueError(f"horizon_ns must be positive, got {horizon_ns}")
    if horizon_ns % bar_interval_ns:
        raise ValueError(
            f"horizon_ns={horizon_ns} is not a whole number of {bar_interval_ns}ns bars. "
            "Rounding would score the forecast against a window it did not declare, and the "
            "difference would be invisible in the output."
        )
    horizon_bars = horizon_ns // bar_interval_ns

    scores: list[float] = []
    outcomes: list[float] = []
    n_forecasts = 0
    for i, ts in enumerate(stamps[:-horizon_bars]):
        view = AsOfPanelView(panel, decision_ts=ts)
        for forecast in compute_fn(view, params, spec):
            n_forecasts += 1
            series = closes[forecast.instrument_id]
            here, later = series.get(ts), series.get(stamps[i + horizon_bars])
            if here in (None, 0) or later is None:
                continue
            scores.append(float(forecast.expected_return_bps))
            outcomes.append((later - here) / here)
    return scores, outcomes, n_forecasts


def run_s1_smoke(fixtures: Path, spec_path: Path = _SPEC) -> dict[str, object]:
    """Run A01 across the fixture panel and return the smoke report."""
    spec = load_alpha_spec(spec_path)
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

    # The parameters are checked against the spec's PRE-REGISTERED domain before anything runs.
    # This target ran A01 at a one-minute horizon from M12 until now, against a declared
    # `hold_minutes: [15, 120]` — fifteen times below the floor. The falsifiers attached to the
    # spec were written for the declared space, so they could not reject it, and it looked
    # exactly like a conforming run.
    interval = stamps[1] - stamps[0]
    bars = bars_per_unit(interval)
    declared = {"residual_lookback_m": 5, "scale_window_m": 20, "hold_minutes": _HOLD_MINUTES}
    assert_within_domain(spec, declared)
    params = A01Params(
        residual_lookback=declared["residual_lookback_m"] * bars,
        scale_window=declared["scale_window_m"] * bars,
        horizon_ns=_HOLD_MINUTES * 60 * NS,
    )
    scores, outcomes, n_forecasts = _evaluate(
        panel, closes, stamps, params, spec, bar_interval_ns=interval
    )

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
        "hold_minutes": _HOLD_MINUTES,
        # Overlap. Fifteen-minute forecasts made every minute share fourteen-fifteenths of their
        # window, so the pair count overstates the evidence by roughly the horizon. Reported
        # beside it, because a rank IC over 1,800 heavily-overlapping pairs is not 1,800
        # observations' worth of anything and the raw count invites reading it as though it were.
        "independent_windows": len(scores) // (_HOLD_MINUTES * bars) if scores else 0,
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


ComputeFn = Callable[..., list[Forecast]]

_GRID_POINTS: Final = 4
_INITIAL_BUDGET: Final = 400
"""Bars in the first rung. With eta=2 and four candidates the ladder is 4@400, 2@800, 1@1600 —
inside the 1875-bar fixture panel, so the final rung is never silently truncated."""


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
    params: object,
    spec: AlphaSpec,
    compute_fn: ComputeFn = compute,
    delay_bars: int = 0,
    cost_per_round_trip: float = 0.0,
) -> list[float]:
    """Per-bar realised PnL of taking every forecast's sign, zero where there was no forecast.

    Zero-filled rather than compacted, so every config's series has the same length at the same
    budget whatever its warm-up costs it. Compacting would make the series lengths depend on the
    parameter, and correlating those would need a truncation that aligns at index 0.

    ``cost_per_round_trip`` is charged for every forecast ACTED ON — each opens and closes
    within its holding bar, so each is one round trip. Charged per position taken rather than
    per bar or per forecast emitted: a forecast skipped for a missing price traded nothing, and
    billing it would invent turnover. Defaults to zero so the series is gross unless a caller
    names a line; the caller that certifies must name one, because a gross return recorded in a
    field called `net_return` is a claim the number does not support — and `[C-CERT-01]` RANKS
    on that field.

    ``delay_bars`` shifts ENTRY, never the decision: the forecast is still computed from the
    as-of view at ``ts``, and the position is taken ``delay_bars`` bars later. That is
    `[G-P4-DELAY1]`'s perturbation — *survives +1-bar delay* — and it is the honest one, because
    delaying the decision instead would hand the strategy a later view of the market.

    Decisions with no exit bar left contribute **zero** rather than reusing an earlier price,
    which would fabricate a return out of the shift. The series length is unchanged so a
    stressed run stays comparable with its baseline.
    """
    if cost_per_round_trip < 0:
        raise ValueError(
            f"cost_per_round_trip must not be negative, got {cost_per_round_trip}. A negative "
            "cost pays the strategy to trade, which would make turnover a source of alpha."
        )
    if delay_bars < 0:
        raise ValueError(
            f"delay_bars must not be negative, got {delay_bars}. A negative delay enters BEFORE "
            "the decision — the lookahead this project exists to prevent, and it would improve "
            "every result it touched."
        )
    gross, turns = _pnl_and_turns(
        panel, closes, stamps, params, spec, compute_fn=compute_fn, delay_bars=delay_bars
    )
    return [g - t * cost_per_round_trip for g, t in zip(gross, turns, strict=True)]


def _pnl_and_turns(
    panel: pl.DataFrame,
    closes: dict[str, dict[int, int]],
    stamps: list[int],
    params: object,
    spec: AlphaSpec,
    compute_fn: ComputeFn = compute,
    delay_bars: int = 0,
) -> tuple[list[float], list[int]]:
    """Gross PnL per bar and the number of round trips that produced it.

    Separated so a caller pricing the SAME series at several cost lines pays for one evaluation
    rather than one per line: a cost shifts each traded bar by a constant, so every other line
    is arithmetic. `certify-smoke` needs the gross, the net and the 1.5x stress together, and
    re-running the panel three times for two subtractions made the milestone's own Verify four
    times slower than the thing it verifies.
    """
    gross = [0.0] * (len(stamps) - 1)
    turns = [0] * (len(stamps) - 1)
    for i, ts in enumerate(stamps[:-1]):
        entry_index, exit_index = i + delay_bars, i + delay_bars + 1
        if exit_index >= len(stamps):
            continue
        view = AsOfPanelView(panel, decision_ts=ts)
        for forecast in compute_fn(view, params, spec):
            prices = closes[forecast.instrument_id]
            here, nxt = prices.get(stamps[entry_index]), prices.get(stamps[exit_index])
            if here in (None, 0) or nxt is None:
                continue
            direction = 1.0 if float(forecast.expected_return_bps) >= 0 else -1.0
            gross[i] += direction * (nxt - here) / here
            turns[i] += 1
    return gross, turns


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
                panel,
                closes,
                stamps[:budget],
                _params_for(config, bars),
                spec,
                bar_interval_ns=interval,
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
