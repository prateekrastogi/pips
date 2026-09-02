"""A search per alpha family, and S5 across the winners  (§6 M12/M19).

The last gap between the M19 modules and anything real. Successive halving converges to one
winner, so a single family can never give S5 more than one candidate — S5 selects ACROSS
families. :data:`pips.alphas.dispatch.DRIVERS` provides six that run on the fixture panel; this
runs a search for each, PROMOTES each winner to a later stage, and hands the promoted rows to
:func:`run_s5_from_registry`.

**A promotion is another look, not a copy.** The S1 rows stay and the promoted row is added, so
``multiplicity()`` counts both. That is the established meaning here — M counts evaluations, and
a config re-evaluated at higher fidelity was looked at again (``HalvingResult.trials_viewed``
says the same thing about rungs). Moving the row instead would erase the evidence that the config
was viewed at S1 at all.

**A family that fails is named, not dropped.** A search that raises leaves its family out of the
ensemble, and an ensemble quietly assembled from five of six families is a different claim from
one assembled from six.

**Every family's returns cover the same window**, so the preserved series are correlatable and
S5 can cluster them. The recorder refuses unequal lengths, which is what makes that a checked
property rather than an intention.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
import polars as pl

from pips.alphas.dispatch import DRIVERS
from pips.alphas.spec import load_alpha_spec
from pips.search.funnel import gate_s4
from pips.search.grid import assert_within_domain, bars_per_unit, grid_from_domain
from pips.search.halving import successive_halving
from pips.search.multiplicity import multiplicity
from pips.search.registry import Registry, RunRecord
from pips.search.s1 import _evaluate, _pnl_series, load_panel
from pips.search.s5 import TurnoverInputs, run_s5_from_registry
from pips.search.silver_panel import load_silver_panel
from pips.search.trials import (
    TrialContext,
    file_snapshot_root,
    fixture_snapshot_root,
    record_halving_trials,
)
from pips.selection.netting import BlotterOrder
from pips.selection.order_budget import NSE_RETAIL_BUDGET
from pips.selection.pareto import Direction, Objective
from pips.selection.turnover import CostLine, EdgeCurve
from pips.validation.nulls import rank_ic

if TYPE_CHECKING:
    from pips.alphas.dispatch import AlphaDriver
    from pips.search.s5 import StageStep
    from pips.selection.pareto import Candidate

__all__ = ["PROMOTED_STAGE", "run_family_searches"]

_NS = 1_000_000_000
_SPECS = Path("config/search_spaces")
COST_MODEL = "0" * 64
"""Placeholder cost model for the fixture run. Named once so the RunRecords and the report that
summarises them cannot disagree about which one was used."""
BROKER = "FLATTRADE"
CAPITAL_TIER = "2L"

PROMOTED_STAGE = "S4"
_PROMOTED_RANK = 5
_SECOND = _NS
_OPEN = 1_772_000_000 * _NS
_IST = timezone(timedelta(hours=5, minutes=30))

_OBJECTIVES = [
    Objective("net_return", Direction.MAXIMIZE),
    Objective("max_drawdown", Direction.MINIMIZE),
]


@dataclass(frozen=True)
class _Family:
    driver: AlphaDriver
    winner: str
    series: list[float]
    metrics: dict[str, float]


def _drawdown(series: Sequence[float]) -> float:
    """Worst peak-to-trough of the cumulative PnL. Reported as a POSITIVE magnitude.

    S5 minimises it, so the sign convention has to be stated: a negative drawdown would be
    maximised by the sort and the worst candidate would win.
    """
    peak = running = 0.0
    worst = 0.0
    for value in series:
        running += value
        peak = max(peak, running)
        worst = max(worst, peak - running)
    return worst


def _blotter_for(ids: tuple[str, ...], cost: CostLine) -> list[BlotterOrder]:
    """One order per member per second in its own symbol — inside every governor limit.

    A stand-in: the fixture panel has no execution simulation behind it, so this exercises the
    netting and budget path without pretending to model fills.
    """
    del cost
    return [
        BlotterOrder(cid, f"SYM{i}", _OPEN + s * _SECOND, 100, Decimal("100.00"))
        for i, cid in enumerate(ids)
        for s in range(10)
    ]


def _turnover_inputs() -> TurnoverInputs:
    return TurnoverInputs(
        cost_lines={("FLATTRADE", "2L"): CostLine(0.00025)},
        edge_curve=lambda tau: EdgeCurve(a=0.000274 * (1 + 0.3 * tau / 0.0005), gamma=0.5),
        trade_sigma=lambda h: 0.0005 * h,
        fitted_horizon=100_000.0,
        lam=0.5,
        density={0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0},
        ticket=50_000.0,
        capital=2_000_000.0,
    )


def _search_one(
    driver: AlphaDriver,
    panel: pl.DataFrame,
    closes: dict[str, dict[int, int]],
    stamps: list[int],
    interval: int,
    registry: Registry,
    returns_dir: Path,
    context: TrialContext,
    grid_points: int,
    initial_budget: int,
    returns_bars: int,
) -> _Family:
    spec = load_alpha_spec(_SPECS / driver.spec_file)
    assert_within_domain(spec, driver.fixed)
    bars = bars_per_unit(interval)
    grid = grid_from_domain(spec, driver.swept, count=grid_points)
    candidates = tuple(f"{driver.alpha_id}-{driver.swept}={v}" for v in grid)
    by_config = dict(zip(candidates, grid, strict=True))

    scored: dict[tuple[str, int], Decimal] = {}

    def score(config: str, budget: int) -> Decimal:
        key = (config, budget)
        if key not in scored:
            params = driver.build(by_config[config], bars=bars)
            values, outcomes, _ = _evaluate(
                panel,
                closes,
                stamps[:budget],
                params,
                spec,
                bar_interval_ns=interval,
                compute_fn=driver.compute,
            )
            scored[key] = (
                Decimal(str(rank_ic(np.array(values), np.array(outcomes))))
                if len(values) >= 2
                else Decimal(0)
            )
        return scored[key]

    pnl: dict[str, list[float]] = {}

    def series_for(config: str) -> list[float]:
        if config not in pnl:
            # The FULL window for every config, so preserved series are equal-length and
            # correlatable -- a config's return stream is a property of the config, not of how
            # long the search looked at it.
            pnl[config] = _pnl_series(
                panel,
                closes,
                stamps[:returns_bars],
                driver.build(by_config[config], bars=bars),
                spec,
                driver.compute,
            )
        return pnl[config]

    result = successive_halving(candidates, score, initial_budget=initial_budget, eta=2)

    def metrics_for(config: str, budget: int) -> dict[str, float]:
        return {"rank_ic": float(score(config, budget)), "budget_bars": float(budget)}

    record_halving_trials(
        registry,
        result,
        metrics_for=metrics_for,
        context=context,
        returns_for=lambda config, budget: np.array(series_for(config)),
        returns_dir=returns_dir,
    )

    winner = result.winner
    assert winner is not None
    series = series_for(winner)
    return _Family(
        driver=driver,
        winner=winner,
        series=series,
        metrics={
            "net_return": float(sum(series)),
            "max_drawdown": _drawdown(series),
            "rank_ic": float(score(winner, result.rounds[-1].budget)),
        },
    )


def flat_series_reason(alpha_id: str, winner: str, *, window: int, total: int) -> str:
    """Why a winner's PnL never moved — and the two cases wear the same symptom.

    If the preserved window is a TRUNCATION of the panel, the window may simply be too short to
    hold what the alpha needs: A05 and A06 measure a gap against the prior session's close, A07
    breaks out of an opening range, and a window inside one session offers none of that.

    If the window IS the panel, the window cannot be the limitation. The alpha looked at
    everything there is and found nothing it trades on — a statement about the DATA. On three
    real trading days of ICICIBANK and RELIANCE, A06 found no qualifying idiosyncratic gap in
    all 1,108 bars; saying "this is a statement about the window" there would be plainly false
    and would send the reader to a knob already at its limit.

    The message also used to explain A05's gap requirement whatever family had gone flat. An
    explanation of the wrong alpha reads as a diagnosis.
    """
    head = (
        f"winner {winner!r} produced no trades, so its PnL series is flat and cannot be "
        f"correlated. {alpha_id} is not promoted. "
    )
    if window < total:
        return head + (
            f"The preserved window is {window} of {total} bars, so it may simply be too short "
            f"to contain what {alpha_id} needs — the gap and opening-range families require a "
            "session boundary inside the window."
        )
    return head + (
        f"The window is the whole panel, all {total} bars, so this is not about the window: "
        f"{alpha_id} found nothing it trades on in every bar available."
    )


def run_family_searches(
    *,
    fixtures: Path,
    registry: Registry,
    returns_dir: Path,
    grid_points: int = 4,
    initial_budget: int = 400,
    returns_bars: int | None = None,
    silver: Path | None = None,
) -> dict[str, object]:
    """Search every family, promote each winner, and run S5 across the promoted rows."""
    # Real promoted bars when `silver` is given, generated fixtures otherwise. Both pin what
    # they read: [C-DATA-02] does not care which shape the data arrived in, and a run on real
    # bars that recorded no snapshot root would be the one run nobody could reproduce.
    if silver is not None:
        panel = load_silver_panel(silver)
        snapshot_name = f"silver@{silver.name}"
        root = file_snapshot_root(silver)
    else:
        panel = load_panel(fixtures)
        snapshot_name = f"fixtures@{fixtures.name}"
        root = fixture_snapshot_root(fixtures)

    stamps = sorted(set(panel["close_ts_ns"].to_list()))
    interval = stamps[1] - stamps[0]
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
    # The window preserved returns cover. It must be the SAME for every config -- the recorder
    # refuses unequal lengths and S5 cannot correlate them -- but it need not be the whole panel.
    window = len(stamps) if returns_bars is None else min(returns_bars, len(stamps))

    families: list[_Family] = []
    failures: dict[str, str] = {}
    # Session boundaries the first rung's window actually contains. A05 and A06 measure a gap
    # against the prior session's close and A07 breaks out of an opening range, so each needs
    # something from a session it did not start in -- and a budget that crosses no boundary
    # gives them nothing. Checked BEFORE the search: otherwise every rung scores zero, halving
    # eliminates their configs on noise, and the emptiness surfaces at promotion as a flat
    # series, which reads as a fact about the alpha rather than about the schedule.
    budget_sessions = len(
        {datetime.fromtimestamp(ts / 1e9, _IST).date() for ts in stamps[:initial_budget]}
    )
    boundaries = budget_sessions - 1

    for alpha_id, driver in sorted(DRIVERS.items()):
        if boundaries < driver.minimum_sessions:
            failures[alpha_id] = (
                f"declares minimum_sessions={driver.minimum_sessions} and the first rung's "
                f"budget of {initial_budget} bars spans {budget_sessions} session(s), crossing "
                f"{boundaries}. Not searched: every rung would score zero and halving would "
                "eliminate its configs on noise."
            )
            continue
        context = TrialContext(
            stage="S1",
            stage_rank=1,
            family=alpha_id,
            data_snapshot=snapshot_name,
            snapshot_root=root,
            cost_model=COST_MODEL,
            fill_tier="F1",
            git_sha="0" * 40,
            universe_id="FIXTURES",
            session_mask="ALL",
            capital_tier=CAPITAL_TIER,
            broker=BROKER,
        )
        try:
            families.append(
                _search_one(
                    driver,
                    panel,
                    closes,
                    stamps,
                    interval,
                    registry,
                    returns_dir / alpha_id,
                    context,
                    grid_points,
                    initial_budget,
                    window,
                )
            )
        except Exception as error:
            failures[alpha_id] = repr(error)

    # A winner whose PnL series never moves did not trade in the preserved window. That is a
    # finding about the family and the window -- A05 needs a session boundary, because a gap
    # requires a prior close, so a window inside one session gives it nothing to trade -- and it
    # is NOT "no edge". Promoting it would hand S5 a flat series, which the clustering correctly
    # refuses; the refusal would arrive from three modules away and name nothing.
    tradeable: list[_Family] = []
    for family in families:
        if len(set(family.series)) <= 1:
            failures[family.driver.alpha_id] = flat_series_reason(
                family.driver.alpha_id, family.winner, window=window, total=len(stamps)
            )
        else:
            tradeable.append(family)

    # Promote each winner: a NEW row at the later stage, not a moved one. The registry is
    # append-only, and erasing the S1 row would erase the evidence that the config was viewed
    # there -- a count rule 4 asks for.
    for family in tradeable:
        registry.record(
            RunRecord(
                config_hash=__import__("hashlib").sha256(family.winner.encode()).hexdigest(),
                stage=PROMOTED_STAGE,
                stage_rank=_PROMOTED_RANK,
                family=family.driver.alpha_id,
                universe_id="FIXTURES",
                session_mask="ALL",
                capital_tier=CAPITAL_TIER,
                broker=BROKER,
                data_snapshot=snapshot_name,
                snapshot_root=root,
                cost_model=COST_MODEL,
                fill_tier="F1",
                seed=0,
                git_sha="0" * 40,
                metrics=family.metrics,
                daily_returns_ref=str(
                    registry.write_daily_returns(
                        returns_dir / "promoted" / f"{family.driver.alpha_id}.parquet",
                        np.array(family.series),
                    )
                ),
                status="completed",
            )
        )

    # `[G-S4-DSR]` AFTER every promotion is recorded, so the deflation counts every trial the
    # cycle viewed -- including the promotions themselves. Computing it earlier would deflate
    # against a smaller N, and a smaller N raises the DSR.
    s4 = gate_s4(registry, stage=PROMOTED_STAGE)
    selection = run_s5_from_registry(
        registry=registry,
        stage=PROMOTED_STAGE,
        # Derived here rather than recorded on the row: the row was written before the trials
        # that deflate it existed.
        extra_metrics={b.run_id: {"dsr": b.dsr_at_literal} for b in s4.admitted + s4.rejected},
        objectives=_OBJECTIVES,
        cluster_threshold=0.2,
        max_pairwise_correlation=0.5,
        blotter_for=_blotter_for,
        gross_cost=CostLine(0.0005),
        bucket_ns=_SECOND,
        budget=NSE_RETAIL_BUDGET,
        turnover=_turnover_inputs(),
    )

    counts = multiplicity(registry)
    return {
        "families_run": len(families),
        "families_promoted": len(tradeable),
        "families_failed": len(failures),
        "failures": failures,
        "winners": {f.driver.alpha_id: f.winner for f in families},
        "promoted": sorted(f.driver.alpha_id for f in tradeable),
        "promoted_stage": PROMOTED_STAGE,
        "trials_viewed": len(registry.all_runs()),
        "multiplicity_literal": counts.literal_count,
        "multiplicity_effective": (
            f"{counts.effective_count:.3f}" if counts.effective_count is not None else None
        ),
        "ensemble": selection.ensemble,
        "s4_admitted": len(s4.admitted),
        "s4_rejected": len(s4.rejected),
        "s4_excluded": s4.excluded,
        # The whole result, not only the projection above: `[C-NOM-01]` needs the CLUSTERS, and
        # a report that flattens them forces the caller to re-derive what S5 already computed.
        "s5": selection,
        "s5_funnel": selection.funnel,
        # What this run READ and ran UNDER. Recorded here because a dossier that cannot name its
        # snapshot, cost model or venue is describing some other run (`[C-SMOKE-01]`).
        "snapshot_name": snapshot_name,
        "snapshot_root": root,
        "cost_model": COST_MODEL,
        "broker": BROKER,
        "capital_tier": CAPITAL_TIER,
        "netting_ratio": selection.netting.netting_ratio,
        "s5_admissible": selection.admissible,
        "_is_an_edge": False,
    }


def main(argv: list[str] | None = None) -> int:
    """``pips s5-smoke <fixtures> <registry.db>`` — search every family, then select across them."""
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    fixtures = Path(args[0]) if args else Path("fixtures")
    db = Path(args[1]) if len(args) > 1 else Path("build/s5-smoke/registry.db")
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        report = run_family_searches(
            fixtures=fixtures, registry=Registry(db), returns_dir=db.parent / "returns"
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"s5-smoke FAILED: {exc}")
        return 1

    print("s5-smoke: a search per family, then S5 across the winners")
    for key in (
        "families_run",
        "families_promoted",
        "failures",
        "winners",
        "promoted",
        "trials_viewed",
        "multiplicity_literal",
        "multiplicity_effective",
        "netting_ratio",
        "s5_admissible",
    ):
        print(f"  {key}: {report[key]}")
    ensemble = cast("tuple[Candidate, ...]", report["ensemble"])
    funnel = cast("tuple[StageStep, ...]", report["s5_funnel"])
    print(f"  ensemble: {[c.id for c in ensemble]}")
    print("  funnel:")
    for step in funnel:
        print(f"    {step.name:26} {step.considered} -> {step.admitted}")

    print(
        "\n  WHAT THIS IS NOT: an edge. Two synthetic symbols from a seeded random walk, so\n"
        "  every rank IC above is noise and the ensemble is a selection among noises. What it\n"
        "  demonstrates is that the M19 chain runs on rows a search actually produced: trials\n"
        "  recorded, winners promoted, frontier taken, near-variants clustered, correlated\n"
        "  survivors gated, netting priced, order budget measured — and the multiplicity\n"
        "  bracket computed from the same ledger."
    )
    return 0
