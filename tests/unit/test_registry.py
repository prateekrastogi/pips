"""Experiment registry and multiplicity ledger [C-REG-01] (§3.6, constitution rule 4).

Rule 4 is the reason this exists: *every viewed trial counts*. Completed, failed, abandoned,
hand-tuned, alternative-seed and notebook-glanced variants all land here, and **deletion does
not un-count a trial**. A registry you can quietly edit is a leaderboard, and a leaderboard is
what this project is explicitly not building.

So append-only is enforced by the DATABASE, not by the application remembering not to. §3.6
says "application code has no UPDATE/DELETE"; a trigger is strictly stronger — it also refuses
a `sqlite3` shell, a stray migration and a helpful future contributor.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from pips.search.multiplicity import effective_rank, multiplicity
from pips.search.registry import Registry, RunRecord

STAGES = {"S1": 1, "S2V": 2, "S2E": 3, "S3": 4, "S4": 5, "S5": 6, "S6": 7}


def record(**over: object) -> RunRecord:
    base: dict[str, object] = {
        "config_hash": "a" * 64,
        "stage": "S1",
        "stage_rank": 1,
        "family": "A01",
        "universe_id": "U100",
        "session_mask": "MID",
        "capital_tier": "2L",
        "broker": "FLATTRADE",
        # A NAME and a ROOT, deliberately unlike each other. This helper used to set
        # data_snapshot to "b" * 64, which reads as a hash and is not one — the very
        # conflation `snapshot_root` was added to end [C-DATA-02].
        "data_snapshot": "nifty100-1m-2026H1",
        "snapshot_root": "b" * 64,
        "cost_model": "c" * 64,
        "fill_tier": "F1",
        "seed": 7,
        "git_sha": "d" * 40,
        "metrics": {"rank_ic": 0.03},
        "n_trades": 412,
        "daily_returns_ref": None,
        "status": "completed",
    }
    base.update(over)
    return RunRecord.model_validate(base)


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.db")


# ------------------------------------------------------------- append-only -------------


def test_a_run_can_be_recorded_and_read_back(reg: Registry) -> None:
    run_id = reg.record(record())
    got = reg.get(run_id)
    assert got is not None and got.config_hash == "a" * 64


def test_update_is_refused_by_the_database(reg: Registry) -> None:
    reg.record(record())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        reg.connection.execute("UPDATE runs SET status = 'completed' WHERE run_id = 1")


def test_delete_is_refused_by_the_database(reg: Registry) -> None:
    reg.record(record())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        reg.connection.execute("DELETE FROM runs WHERE run_id = 1")


def test_deletion_does_not_un_count_a_trial(reg: Registry) -> None:
    # Rule 4, stated literally. The attempt fails and the count is unchanged.
    for seed in range(3):
        reg.record(record(seed=seed))
    with pytest.raises(sqlite3.IntegrityError):
        reg.connection.execute("DELETE FROM runs")
    assert multiplicity(reg).literal_count == 3


# ----------------------------------------------------- every viewed trial counts --------


@pytest.mark.parametrize("status", ["completed", "failed", "abandoned", "viewed"])
def test_every_status_counts_toward_multiplicity(reg: Registry, status: str) -> None:
    # "Completed, failed, abandoned, hand-tuned, alternative-seed and notebook-glanced
    # variants all land in the registry and enter the multiplicity ledger."
    reg.record(record(status=status))
    assert multiplicity(reg).literal_count == 1


def test_an_unknown_status_is_refused(reg: Registry) -> None:
    with pytest.raises(ValueError, match="status"):
        reg.record(record(status="probably_fine"))


def test_a_stage_rank_that_contradicts_its_stage_is_refused(reg: Registry) -> None:
    # stage_rank orders the funnel; a mismatch would silently reorder it.
    with pytest.raises(ValueError, match="stage_rank"):
        reg.record(record(stage="S4", stage_rank=1))


@pytest.mark.parametrize(("stage", "rank"), sorted(STAGES.items()))
def test_every_declared_stage_rank_is_accepted(reg: Registry, stage: str, rank: int) -> None:
    assert reg.record(record(stage=stage, stage_rank=rank)) > 0


# -------------------------------------------------------- the holdout lockbox -----------


def test_a_cycle_can_be_unlocked_once(reg: Registry) -> None:
    reg.unlock_holdout("cycle-1", "a" * 64)
    assert reg.holdout_unlock_count("cycle-1") == 1


def test_a_second_unlock_of_the_same_cycle_voids_it(reg: Registry) -> None:
    # §3.6: "one unlock per cycle; twice = void". The second attempt must be loud — a silent
    # second look at the holdout is the most valuable lie a research process can tell itself.
    reg.unlock_holdout("cycle-1", "a" * 64)
    with pytest.raises(RuntimeError, match="void"):
        reg.unlock_holdout("cycle-1", "b" * 64)


def test_the_void_attempt_is_still_recorded(reg: Registry) -> None:
    # The attempt itself is evidence. Refusing it and forgetting it would hide that someone
    # tried, which is exactly what a lockbox is for.
    reg.unlock_holdout("cycle-1", "a" * 64)
    with pytest.raises(RuntimeError):
        reg.unlock_holdout("cycle-1", "b" * 64)
    assert reg.holdout_unlock_count("cycle-1") == 2


def test_different_cycles_unlock_independently(reg: Registry) -> None:
    reg.unlock_holdout("cycle-1", "a" * 64)
    reg.unlock_holdout("cycle-2", "b" * 64)
    assert reg.holdout_unlock_count("cycle-2") == 1


# -------------------------------------------------- M_erank on synthetic trials ---------


def test_erank_of_independent_trials_is_the_trial_count() -> None:
    # The Verify case (§6 M11): erank on synthetic correlated trials.
    rng = np.random.default_rng(20260831)
    returns = rng.normal(size=(2000, 8))
    assert 7.0 < effective_rank(returns) <= 8.0


def test_erank_of_identical_trials_collapses_to_one() -> None:
    # Eight clones of one strategy are ONE trial's worth of multiplicity, not eight. This is
    # the whole reason M_erank is reported beside M.
    base = np.random.default_rng(7).normal(size=(2000, 1))
    returns = np.repeat(base, 8, axis=1)
    assert effective_rank(returns) == pytest.approx(1.0, abs=1e-6)


def test_erank_of_partially_correlated_trials_lies_between() -> None:
    rng = np.random.default_rng(11)
    common = rng.normal(size=(2000, 1))
    idiosyncratic = rng.normal(size=(2000, 8))
    returns = 0.7 * common + 0.3 * idiosyncratic
    erank = effective_rank(returns)
    assert 1.0 < erank < 8.0


def test_erank_is_undefined_for_a_single_trial() -> None:
    assert effective_rank(np.random.default_rng(3).normal(size=(100, 1))) == 1.0


def test_a_constant_return_series_does_not_produce_a_nan(reg: Registry) -> None:
    # A trial that never traded has zero variance, and a correlation matrix built naively
    # from it is full of NaN — which would silently poison M_erank for every OTHER trial.
    rng = np.random.default_rng(5)
    returns = np.column_stack([rng.normal(size=500), np.zeros(500)])
    erank = effective_rank(returns)
    assert np.isfinite(erank)


# --------------------------------------------- M and M_erank reported together ----------


def test_multiplicity_reports_both_counts(reg: Registry, tmp_path: Path) -> None:
    # §3.6: report BOTH. DSR is evaluated at N=M and N=M_erank as bracketing cases, so a
    # report carrying only one of them cannot produce the bracket.
    rng = np.random.default_rng(2)
    for i in range(4):
        path = tmp_path / f"returns_{i}.parquet"
        reg.write_daily_returns(path, rng.normal(size=300))
        reg.record(record(seed=i, daily_returns_ref=str(path)))
    m = multiplicity(reg)
    assert m.literal_count == 4
    assert m.effective_count is not None
    assert 1.0 <= m.effective_count <= 4.0
    # The DSR bracket (§3.6): N=M_erank and N=M, with the effective count never above the
    # literal one — more trials cannot be less correlated than themselves.
    assert m.bracket() == (4, m.effective_count)


def test_multiplicity_without_preserved_returns_reports_m_only(reg: Registry) -> None:
    # Honest degradation: if returns were not preserved, M_erank cannot be computed and must
    # be absent rather than defaulted to M (which would understate the correction).
    reg.record(record(daily_returns_ref=None))
    m = multiplicity(reg)
    assert m.literal_count == 1
    assert m.effective_count is None
