"""Recording search trials in the registry  (§6 M11/M19, rule 4).

The registry has had a schema, append-only triggers and a holdout ledger since M11, and no
producer. So rule 4 — *every viewed trial counts* — has never had anything to count, and
`multiplicity()` has always read zero. This writes the rows.

**One row per (config, budget) evaluation**, which is what `HalvingResult.trials_viewed` means:
a config evaluated at three budgets was looked at three times, and each look could have been the
one that produced a flattering number. Not one row per surviving config, and not one per
distinct config.

**Eliminated candidates are recorded.** Recording only survivors is the survivorship bug at the
trial level, and it corrupts the denominator every deflation downstream divides by.

**A trial whose evaluation raises is recorded as `failed`, not dropped.** It was still viewed:
the search spent a look on it, and a look that errored is not a look that never happened.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from pips.search.halving import HalvingResult, successive_halving
from pips.search.multiplicity import multiplicity
from pips.search.registry import Registry
from pips.search.trials import TrialContext, fixture_snapshot_root, record_halving_trials

CANDIDATES = ("a01-lb5", "a01-lb8", "a01-lb13", "a01-lb21")


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.db")


@pytest.fixture
def context() -> TrialContext:
    return TrialContext(
        stage="S1",
        stage_rank=1,
        family="A01",
        data_snapshot="fixtures-2026H1",
        snapshot_root="b" * 64,
        cost_model="c" * 64,
        fill_tier="F1",
        git_sha="d" * 40,
        universe_id="U100",
        session_mask="MID",
        capital_tier="2L",
        broker="FLATTRADE",
    )


def score(config: str, budget: int) -> Decimal:
    return Decimal(len(config) * budget % 7) / Decimal(10)


def metrics_for(config: str, budget: int) -> dict[str, float]:
    return {"net_return": (len(config) % 5) / 100, "max_drawdown": (budget % 4) / 100}


def halving() -> HalvingResult:
    return successive_halving(CANDIDATES, score, initial_budget=8, eta=2)


# ------------------------------------------------------------ the count ---------------


def test_one_row_per_config_budget_evaluation(reg: Registry, context: TrialContext) -> None:
    """The ledger and the search must agree on how many looks were taken."""
    result = halving()
    recorded = record_halving_trials(reg, result, metrics_for=metrics_for, context=context)

    assert recorded.rows == result.trials_viewed
    assert len(reg.all_runs()) == result.trials_viewed


def test_the_multiplicity_ledger_now_counts_something(reg: Registry, context: TrialContext) -> None:
    """`multiplicity()` reads `len(all_runs())`, and until now that was always zero.

    The whole §3.6 apparatus — the DSR bracket, the effective rank — divides by this. A
    denominator of zero is not a small error; it is the absence of any correction at all.
    """
    result = halving()
    record_halving_trials(reg, result, metrics_for=metrics_for, context=context)
    assert multiplicity(reg).literal_count == result.trials_viewed
    assert multiplicity(reg).literal_count > len(CANDIDATES), "more looks than candidates"


def test_a_config_seen_at_three_budgets_gets_three_rows(
    reg: Registry, context: TrialContext
) -> None:
    result = halving()
    record_halving_trials(reg, result, metrics_for=metrics_for, context=context)

    winner_rows = [r for r in reg.all_runs() if r["config_hash"] and result.winner]
    appearances = sum(rung.configs.count(result.winner) for rung in result.rounds)
    assert appearances > 1, "the winner survives several rungs"
    hashes = [r["config_hash"] for r in reg.all_runs()]
    assert len(winner_rows) == len(hashes)
    # The winner's hash appears once per rung it ran in.
    winner_hash = next(r["config_hash"] for r in reg.all_runs() if r["status"] == "completed")
    assert hashes.count(winner_hash) == appearances


def test_eliminated_candidates_are_recorded_not_dropped(
    reg: Registry, context: TrialContext
) -> None:
    result = halving()
    record_halving_trials(reg, result, metrics_for=metrics_for, context=context)

    recorded_configs = {r["config_hash"] for r in reg.all_runs()}
    assert len(recorded_configs) == result.configs_viewed == len(CANDIDATES)


# ------------------------------------------------------------ status -------------------


def test_only_the_final_rung_completes(reg: Registry, context: TrialContext) -> None:
    """An early rung is a look at REDUCED fidelity, not a finished run.

    `viewed` is the status for it: it counts for multiplicity and is not evidence about the
    config's performance, which is exactly how `pooled_family_means` and S5 already treat it.
    """
    result = halving()
    record_halving_trials(reg, result, metrics_for=metrics_for, context=context)

    rows = reg.all_runs()
    completed = [r for r in rows if r["status"] == "completed"]
    viewed = [r for r in rows if r["status"] == "viewed"]
    assert len(completed) == len(result.rounds[-1].configs)
    assert len(viewed) == result.trials_viewed - len(completed)


def test_an_evaluation_that_raises_is_recorded_as_failed(
    reg: Registry, context: TrialContext
) -> None:
    """A look that errored is not a look that never happened.

    Dropping it would make the search report fewer trials than it took, in the direction that
    weakens every deflation downstream.
    """

    def exploding(config: str, budget: int) -> dict[str, float]:
        if config == "a01-lb13":
            raise RuntimeError("simulated evaluation failure")
        return metrics_for(config, budget)

    result = halving()
    recorded = record_halving_trials(reg, result, metrics_for=exploding, context=context)

    assert recorded.rows == result.trials_viewed, "still one row per look"
    failed = [r for r in reg.all_runs() if r["status"] == "failed"]
    assert failed, "the failing config was recorded"
    assert recorded.failures == len(failed)


# ------------------------------------------------------------ provenance ---------------


def test_the_snapshot_root_is_the_merkle_root_of_the_bytes_read(tmp_path: Path) -> None:
    (tmp_path / "a.parquet").write_bytes(b"one")
    (tmp_path / "b.parquet").write_bytes(b"two")
    first = fixture_snapshot_root(tmp_path)

    assert len(first) == 64
    assert first == fixture_snapshot_root(tmp_path), "stable across reads"


def test_changing_a_fixture_changes_the_root(tmp_path: Path) -> None:
    (tmp_path / "a.parquet").write_bytes(b"one")
    before = fixture_snapshot_root(tmp_path)
    (tmp_path / "a.parquet").write_bytes(b"one-modified")
    assert fixture_snapshot_root(tmp_path) != before


def test_the_root_does_not_depend_on_directory_listing_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling it twice proves nothing: `rglob` yields the same order both times.

    Filesystem listing order is not guaranteed ACROSS machines, and a root that moves with it
    is not an identity — the same bytes would pin differently on the laptop and on arb-vm, and
    the pin would silently stop meaning anything. So the order is varied deliberately.
    """
    for name in ("z.parquet", "a.parquet", "m.parquet"):
        (tmp_path / name).write_bytes(name.encode())
    forward = fixture_snapshot_root(tmp_path)

    original = Path.rglob
    monkeypatch.setattr(
        Path, "rglob", lambda self, pattern: reversed(list(original(self, pattern)))
    )
    assert fixture_snapshot_root(tmp_path) == forward
    assert len(forward) == 64


def test_an_unpinned_root_is_refused_by_the_registry(reg: Registry, context: TrialContext) -> None:
    """[C-DATA-02] holds by OBSERVATION now, not just by construction.

    Until something wrote runs, "a run cannot be recorded without a validated root" was a claim
    no code path had ever tested against a real writer.
    """
    from dataclasses import replace

    bad = replace(context, snapshot_root="not-a-root")
    with pytest.raises(ValueError):
        record_halving_trials(reg, halving(), metrics_for=metrics_for, context=bad)


def test_the_config_hash_distinguishes_the_candidates(reg: Registry, context: TrialContext) -> None:
    result = halving()
    record_halving_trials(reg, result, metrics_for=metrics_for, context=context)
    hashes = {r["config_hash"] for r in reg.all_runs()}
    assert len(hashes) == len(CANDIDATES)
    assert all(len(h) == 64 for h in hashes)


def test_daily_returns_are_preserved_when_supplied(
    reg: Registry, context: TrialContext, tmp_path: Path
) -> None:
    # Without them S5 cannot cluster, and §3.6's effective rank cannot be computed at all.
    def returns_for(config: str, budget: int) -> np.ndarray:
        return np.array([0.001 * (i + len(config)) for i in range(20)])

    result = halving()
    record_halving_trials(
        reg,
        result,
        metrics_for=metrics_for,
        context=context,
        returns_for=returns_for,
        returns_dir=tmp_path / "returns",
    )
    rows = reg.all_runs()
    refs = [r["daily_returns_ref"] for r in rows]

    # EVERY non-failed trial, not just the completed ones. Restricting to completed would leave
    # M_erank computed over a strict subset, and an effective rank of 1 over 1 of 7 trials reads
    # exactly like an effective rank of 1 over all 7.
    assert all(refs), "every trial carries a returns reference"

    # DISTINCT paths, not just non-empty ones. Writing every trial to one file leaves each row
    # pointing at the last trial's returns: M_erank would see identical series and report an
    # effective rank of 1, and S5's clustering would collapse the whole population into one
    # idea. Both look like findings.
    assert len(set(refs)) == len(refs), "each trial keeps its own returns"
    matrix = reg.daily_returns_matrix()
    assert matrix is not None
    assert matrix.shape[1] == len(refs), "one column per preserved trial"


def test_preserved_returns_make_the_dsr_bracket_formable(
    reg: Registry, context: TrialContext, tmp_path: Path
) -> None:
    """`Multiplicity.bracket()` raises without them, naming this exact gap.

    Its message asks the caller to "preserve daily_returns_ref per trial (§3.6)" — which nothing
    did, so the DSR bracket has never been formable on a real registry. With the returns written
    the bracket exists, which is the end-to-end statement that this recorder unblocks §3.6.
    """

    def returns_for(config: str, budget: int) -> np.ndarray:
        return np.array([0.001 * ((i * 7 + len(config)) % 11 - 5) for i in range(30)])

    record_halving_trials(
        reg,
        halving(),
        metrics_for=metrics_for,
        context=context,
        returns_for=returns_for,
        returns_dir=tmp_path / "returns",
    )
    literal, effective = multiplicity(reg).bracket()
    assert literal > 0
    assert 0 < effective <= literal


def test_the_bracket_is_unavailable_without_preserved_returns(
    reg: Registry, context: TrialContext
) -> None:
    # The honest failure: no M_erank rather than M_erank defaulted to M, which would understate
    # the correction exactly when it matters.
    record_halving_trials(reg, halving(), metrics_for=metrics_for, context=context)
    with pytest.raises(RuntimeError, match="M_erank"):
        multiplicity(reg).bracket()


def test_series_of_unequal_length_are_refused_by_the_recorder(
    reg: Registry, context: TrialContext, tmp_path: Path
) -> None:
    """The invariant lives here rather than in a rule about which trials count.

    Correlating unequal series needs a truncation that aligns at index 0, and M_erank over
    incomparable series is not a measurement of anything. Supplying equal-length series is the
    caller's job, so it is checked rather than assumed.
    """

    def ragged(config: str, budget: int) -> np.ndarray:
        return np.zeros(20 if config == "a01-lb5" else 30)

    with pytest.raises(ValueError, match="Refusing"):
        record_halving_trials(
            reg,
            halving(),
            metrics_for=metrics_for,
            context=context,
            returns_for=ragged,
            returns_dir=tmp_path / "returns",
        )


def test_recording_twice_appends_because_the_ledger_is_append_only(
    reg: Registry, context: TrialContext
) -> None:
    """Two runs of the same search are two searches' worth of looks.

    Deduping would be a deletion by another name, and rule 4's whole point is that a trial you
    took cannot be un-taken.
    """
    result = halving()
    record_halving_trials(reg, result, metrics_for=metrics_for, context=context)
    record_halving_trials(reg, result, metrics_for=metrics_for, context=context)
    assert len(reg.all_runs()) == 2 * result.trials_viewed
