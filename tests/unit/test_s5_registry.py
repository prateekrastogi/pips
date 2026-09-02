"""S5 reading the trial registry  (§6 M19).

Every M19 capability is enforced and every one holds BY CONSTRUCTION: `run_s5` takes candidates
handed to it, so it refuses things without ever having refused anything real. This is the entry
point that reads completed runs and their preserved daily returns, so the constraints meet
actual trials.

The intake is where selection can go wrong before any of the clever parts run:

* **the stage must be named** — S5 selects from what survived earlier stages, and pooling every
  run in the registry mixes S1 exploratory trials with S4 survivors;
* **exclusions are counted, not filtered** — a run with no preserved returns cannot be
  clustered, and dropping it silently shrinks the population the selection reports on (rule 4);
* **series of different lengths are refused** — the registry's own `daily_returns_matrix`
  truncates to the common length, which aligns at index 0 and is only correct if every run
  started on the same day.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pips.search.registry import Registry, RunRecord
from pips.search.s5 import (
    RegistryIntake,
    S5Result,
    TurnoverInputs,
    run_s5_from_registry,
)
from pips.selection.netting import BlotterOrder
from pips.selection.order_budget import NSE_RETAIL_BUDGET
from pips.selection.pareto import Direction, Objective
from pips.selection.turnover import CostLine, EdgeCurve

SECOND = 1_000_000_000
OPEN = 1_772_000_000 * SECOND
TWO = [Objective("net_return", Direction.MAXIMIZE), Objective("max_drawdown", Direction.MINIMIZE)]

BASE = [((t * 37) % 101 - 50) / 1000 for t in range(101)]
OTHER = [((t * 53) % 101 - 50) / 1000 for t in range(101)]
THIRD = [((t * 61) % 101 - 50) / 1000 for t in range(101)]

TURNOVER = TurnoverInputs(
    cost_lines={("FLATTRADE", "2L"): CostLine(0.00025)},
    edge_curve=lambda tau: EdgeCurve(a=0.000274 * (1 + 0.3 * tau / 0.0005), gamma=0.5),
    trade_sigma=lambda h: 0.0005 * h,
    fitted_horizon=100_000.0,
    lam=0.5,
    density={0.0002: 40.0, 0.0006: 12.0, 0.0020: 3.0},
    ticket=50_000.0,
    capital=2_000_000.0,
)


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.db")


def record(**over: object) -> RunRecord:
    base: dict[str, object] = {
        "config_hash": "a" * 64,
        "stage": "S4",
        "stage_rank": 5,
        "family": "A01",
        "universe_id": "U100",
        "session_mask": "MID",
        "capital_tier": "2L",
        "broker": "FLATTRADE",
        "data_snapshot": "nifty100-1m-2026H1",
        "snapshot_root": "b" * 64,
        "cost_model": "c" * 64,
        "fill_tier": "F1",
        "seed": 7,
        "git_sha": "d" * 40,
        "metrics": {"net_return": 0.20, "max_drawdown": 0.10},
        "n_trades": 412,
        "daily_returns_ref": None,
        "status": "completed",
    }
    base.update(over)
    return RunRecord.model_validate(base)


def add(reg: Registry, tmp_path: Path, name: str, series: list[float], **over: object) -> int:
    ref = reg.write_daily_returns(tmp_path / f"{name}.parquet", np.array(series))
    return reg.record(record(seed=abs(hash(name)) % 10_000, daily_returns_ref=str(ref), **over))


def quiet_blotter(ids: tuple[str, ...], cost: CostLine) -> list[BlotterOrder]:
    from decimal import Decimal

    return [
        BlotterOrder(cid, f"SYM{i}", OPEN + s * SECOND, 100, Decimal("100.00"))
        for i, cid in enumerate(ids)
        for s in range(10)
    ]


def intake_of(result: S5Result) -> RegistryIntake:
    """The registry path must always populate the intake; a None here is itself a failure."""
    assert result.intake is not None, "the registry entry point must report its intake"
    return result.intake


def go(reg: Registry, **over: object) -> S5Result:
    kwargs: dict[str, object] = {
        "registry": reg,
        "stage": "S4",
        "objectives": TWO,
        "cluster_threshold": 0.2,
        "max_pairwise_correlation": 0.5,
        "blotter_for": quiet_blotter,
        "gross_cost": CostLine(0.0005),
        "bucket_ns": SECOND,
        "budget": NSE_RETAIL_BUDGET,
        "turnover": TURNOVER,
    }
    kwargs.update(over)
    return run_s5_from_registry(**kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------ the intake --------------


def test_completed_runs_at_the_stage_become_candidates(reg: Registry, tmp_path: Path) -> None:
    add(reg, tmp_path, "a", BASE, metrics={"net_return": 0.30, "max_drawdown": 0.30})
    add(reg, tmp_path, "b", OTHER, metrics={"net_return": 0.10, "max_drawdown": 0.02})
    result = go(reg)
    assert len(result.ensemble) == 2


def test_the_stage_must_be_named(reg: Registry, tmp_path: Path) -> None:
    """Pooling every run mixes S1 exploratory trials with S4 survivors.

    The result would be a frontier over a population that never existed as a cohort, and it
    would look exactly like a frontier over the right one.
    """
    import inspect

    signature = inspect.signature(run_s5_from_registry)
    assert signature.parameters["stage"].default is inspect.Parameter.empty


def test_runs_at_other_stages_are_excluded_and_counted(reg: Registry, tmp_path: Path) -> None:
    add(reg, tmp_path, "a", BASE, metrics={"net_return": 0.30, "max_drawdown": 0.30})
    add(reg, tmp_path, "b", OTHER, metrics={"net_return": 0.10, "max_drawdown": 0.02})
    add(reg, tmp_path, "early", THIRD, stage="S1", stage_rank=1)

    result = go(reg)
    intake = next(s for s in result.funnel if s.name == "registry-intake")
    assert intake.considered == 3
    assert intake.admitted == 2
    assert len(intake.dropped) == 1


def test_runs_that_did_not_complete_are_excluded_and_counted(reg: Registry, tmp_path: Path) -> None:
    """A `viewed` trial counts for multiplicity (rule 4) and is not evidence for selection.

    Two different ledgers, and the difference has to be visible rather than inferred from a
    smaller frontier.
    """
    add(reg, tmp_path, "a", BASE, metrics={"net_return": 0.30, "max_drawdown": 0.30})
    add(reg, tmp_path, "b", OTHER, metrics={"net_return": 0.10, "max_drawdown": 0.02})
    add(reg, tmp_path, "failed", THIRD, status="failed")
    add(reg, tmp_path, "seen", THIRD, status="viewed")

    result = go(reg)
    assert intake_of(result).excluded_not_completed == 1
    assert intake_of(result).excluded_viewed == 1
    assert len(result.ensemble) == 2


def test_a_run_with_no_preserved_returns_is_excluded_and_counted(
    reg: Registry, tmp_path: Path
) -> None:
    # It cannot be clustered, and that is not the same as being uncorrelated with everything.
    add(reg, tmp_path, "a", BASE, metrics={"net_return": 0.30, "max_drawdown": 0.30})
    add(reg, tmp_path, "b", OTHER, metrics={"net_return": 0.10, "max_drawdown": 0.02})
    reg.record(record(seed=99, daily_returns_ref=None))

    result = go(reg)
    assert intake_of(result).excluded_no_returns == 1
    assert len(result.ensemble) == 2


def test_the_intake_accounts_for_every_row_it_read(reg: Registry, tmp_path: Path) -> None:
    add(reg, tmp_path, "a", BASE, metrics={"net_return": 0.30, "max_drawdown": 0.30})
    add(reg, tmp_path, "b", OTHER, metrics={"net_return": 0.10, "max_drawdown": 0.02})
    add(reg, tmp_path, "failed", THIRD, status="failed")
    add(reg, tmp_path, "early", THIRD, stage="S1", stage_rank=1)
    reg.record(record(seed=99, daily_returns_ref=None))

    result = go(reg)
    i = intake_of(result)
    assert i.rows_read == 5
    assert (
        i.admitted
        + i.excluded_not_completed
        + i.excluded_viewed
        + i.excluded_no_returns
        + i.excluded_other_stage
        == i.rows_read
    )


# ------------------------------------------------------------ alignment ---------------


def test_series_of_different_lengths_are_refused_not_truncated(
    reg: Registry, tmp_path: Path
) -> None:
    """The registry's own `daily_returns_matrix` truncates to the common length.

    That aligns at index 0, which is only correct if every run started on the same day — a run
    that began a month later would be compared day-1-to-day-1 against another's day-30, and the
    correlation of that is not a number about either of them. Refusing names the runs and their
    lengths; truncating would produce a clustering nobody could question.
    """
    add(reg, tmp_path, "a", BASE, metrics={"net_return": 0.30, "max_drawdown": 0.30})
    add(reg, tmp_path, "short", OTHER[:60], metrics={"net_return": 0.10, "max_drawdown": 0.02})

    with pytest.raises(ValueError, match="length") as excinfo:
        go(reg)

    # Matching "length" alone passes WITHOUT this check at all: `correlation_distance` refuses
    # unequal series too, with its own "series length mismatch" message. That refusal names only
    # "the first series" and "the second series" — useless for finding the run at fault in a
    # population of hundreds. What this check adds is the diagnosis, so that is what is asserted.
    message = str(excinfo.value)
    assert "=101" in message and "=60" in message, "the run lengths must be named"
    assert "daily_returns_matrix" in message, "and why truncating would be wrong"


# ------------------------------------------------------------ refusals ----------------


def test_an_empty_registry_is_refused(reg: Registry) -> None:
    with pytest.raises(ValueError, match="no completed runs"):
        go(reg)


def test_a_stage_with_no_completed_runs_is_refused(reg: Registry, tmp_path: Path) -> None:
    # Distinct from an empty registry: rows exist, none of them at this stage. Returning an
    # empty ensemble would read as "nothing survived selection".
    add(reg, tmp_path, "early", BASE, stage="S1", stage_rank=1)
    with pytest.raises(ValueError, match="no completed runs"):
        go(reg)


def test_the_run_is_deterministic(reg: Registry, tmp_path: Path) -> None:
    add(reg, tmp_path, "a", BASE, metrics={"net_return": 0.30, "max_drawdown": 0.30})
    add(reg, tmp_path, "b", OTHER, metrics={"net_return": 0.10, "max_drawdown": 0.02})
    first, second = go(reg), go(reg)
    assert [c.id for c in first.ensemble] == [c.id for c in second.ensemble]


# --------------------------------------- metrics derived at selection time `[G-S4-DSR]` -----


def test_derived_metrics_reach_the_candidate(reg: Registry, tmp_path: Path) -> None:
    """The DSR is derived over the WHOLE trial ledger, so it cannot live in the row: the row was
    written before the trials that deflate it existed. It joins at selection time instead."""
    first = add(reg, tmp_path, "a", BASE)
    add(reg, tmp_path, "b", OTHER)

    result = go(reg, extra_metrics={str(first): {"dsr": 0.97}})
    by_id = {c.id: c.metrics for c in result.ensemble}
    assert by_id[str(first)]["dsr"] == 0.97
    assert by_id[str(first)]["net_return"] == 0.20


def test_a_derived_metric_may_not_overwrite_a_recorded_one(reg: Registry, tmp_path: Path) -> None:
    """Otherwise the ranking can be changed after the runs are in the append-only ledger — the
    ledger's whole point defeated by a keyword argument."""
    first = add(reg, tmp_path, "a", BASE)
    add(reg, tmp_path, "b", OTHER)

    with pytest.raises(ValueError, match="net_return"):
        go(reg, extra_metrics={str(first): {"net_return": 9.99}})


def test_a_derived_metric_for_an_unknown_run_is_refused(reg: Registry, tmp_path: Path) -> None:
    """A mapping naming a candidate that is not there is a stale mapping, and applying the rest
    of it silently means applying a mapping nobody has checked."""
    add(reg, tmp_path, "a", BASE)

    with pytest.raises(ValueError, match="9999"):
        go(reg, extra_metrics={"9999": {"dsr": 0.97}})


def test_a_candidate_with_no_derived_metrics_is_left_alone(reg: Registry, tmp_path: Path) -> None:
    """Absent, not defaulted: a missing DSR must reach the dossier as unsupplied rather than as
    a zero, which is a perfect failure dressed as a measurement."""
    first = add(reg, tmp_path, "a", BASE)
    second = add(reg, tmp_path, "b", OTHER)

    result = go(reg, extra_metrics={str(first): {"dsr": 0.97}})
    by_id = {c.id: c.metrics for c in result.ensemble}
    assert "dsr" not in by_id[str(second)]


def test_no_derived_metrics_at_all_is_the_default(reg: Registry, tmp_path: Path) -> None:
    add(reg, tmp_path, "a", BASE)
    result = go(reg)
    assert all("dsr" not in c.metrics for c in result.ensemble)
