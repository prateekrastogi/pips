"""Recording search trials in the registry  (§6 M11/M19, rule 4).

The registry has had a schema, append-only triggers and a holdout ledger since M11, and no
producer. So rule 4 — *every viewed trial counts* — has never had anything to count, and
:func:`pips.search.multiplicity.multiplicity` has always read zero. Every deflation in §3.6
divides by that number: a denominator of zero is not a small error, it is the absence of any
correction at all.

**One row per (config, budget) evaluation**, which is exactly what ``HalvingResult.trials_viewed``
counts — a config evaluated at three budgets was looked at three times, and each look could have
been the one that produced a flattering number. Not one row per surviving config, and not one per
distinct config.

**Eliminated candidates are recorded.** Recording only survivors is the survivorship bug at the
trial level, and it corrupts the denominator every deflation divides by.

**A trial whose evaluation raises is recorded as `failed`, not dropped.** It was still viewed:
the search spent a look on it, and a look that errored is not a look that never happened.

**Only the final rung completes.** An early rung is a look at REDUCED fidelity, so its status is
``viewed`` — it counts for multiplicity and is not evidence about the config's performance,
which is how :func:`pooled_family_means` and S5 already treat that status.

**Every non-failed trial keeps its returns, and they must all be the same length.** The recorder
does not decide which trials are worth preserving — restricting to completed ones would leave
M_erank computed over a strict subset, and an effective rank of 1 over 1 of 7 trials reads
exactly like an effective rank of 1 over all 7. It is the LENGTHS that have to match, so that is
what is enforced here: correlating unequal series needs a truncation aligning at index 0, which
is only correct if every trial covers the same window. Supplying equal-length series is the
caller's job and is checked rather than assumed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pips.core.config import config_hash
from pips.data.pit.store import MerkleTree
from pips.search.registry import Registry, RunRecord

if TYPE_CHECKING:
    import numpy as np

    from pips.search.halving import HalvingResult

__all__ = ["RecordedTrials", "TrialContext", "fixture_snapshot_root", "record_halving_trials"]


@dataclass(frozen=True)
class TrialContext:
    """Everything about a trial that is not the candidate itself.

    Passed rather than inferred: the snapshot root, the cost model and the git SHA are what make
    a row reproducible, and a recorder that guessed any of them would produce rows that look
    provenanced and are not.
    """

    stage: str
    stage_rank: int
    family: str
    data_snapshot: str
    snapshot_root: str
    cost_model: str
    fill_tier: str
    git_sha: str
    universe_id: str | None = None
    session_mask: str | None = None
    capital_tier: str | None = None
    broker: str | None = None


@dataclass(frozen=True)
class RecordedTrials:
    rows: int
    completed: int
    viewed: int
    failures: int


def fixture_snapshot_root(directory: Path) -> str:
    """A 64-hex Merkle root over the bytes of every file under ``directory``.

    Leaves are ``<relative path>:<sha256>`` and are SORTED. Filesystem listing order is not
    guaranteed and a root that moves with it is not an identity — the same bytes would produce
    two different roots on two machines, and the pin would silently stop meaning anything.
    """
    leaves = sorted(
        f"{path.relative_to(directory).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in directory.rglob("*")
        if path.is_file()
    )
    return MerkleTree.root(leaves)


def record_halving_trials(
    registry: Registry,
    result: HalvingResult,
    *,
    metrics_for: Callable[[str, int], Mapping[str, float]],
    context: TrialContext,
    returns_for: Callable[[str, int], np.ndarray] | None = None,
    returns_dir: Path | None = None,
) -> RecordedTrials:
    """Write one row per (config, budget) look the search took."""
    final_round = result.rounds[-1].round_index if result.rounds else -1
    rows = completed = viewed = failures = 0
    length: int | None = None

    for rung in result.rounds:
        for config in rung.configs:
            status = "completed" if rung.round_index == final_round else "viewed"
            try:
                metrics: dict[str, Any] = dict(metrics_for(config, rung.budget))
            except Exception as error:
                # Recorded, not skipped -- dropping it would make the search report fewer
                # trials than it took, weakening every deflation downstream. The reason is kept
                # too: a registry that says a trial failed without saying why is evidence of
                # less than it could be.
                metrics = {"error": repr(error)}
                status = "failed"
                failures += 1

            ref: str | None = None
            if returns_for is not None and returns_dir is not None and status != "failed":
                digest = hashlib.sha256(f"{config}:{rung.budget}".encode()).hexdigest()[:16]
                preserved = returns_for(config, rung.budget)
                if length is None:
                    length = len(preserved)
                elif len(preserved) != length:
                    raise ValueError(
                        f"trial {config!r} at budget {rung.budget} preserved "
                        f"{len(preserved)} returns where earlier trials preserved {length}. "
                        "Refusing: correlating unequal series needs a truncation that aligns "
                        "at index 0, and M_erank computed over incomparable series is not a "
                        "measurement of anything."
                    )
                ref = str(
                    registry.write_daily_returns(returns_dir / f"{digest}.parquet", preserved)
                )

            registry.record(
                RunRecord(
                    config_hash=config_hash({"candidate": config, "family": context.family}),
                    stage=context.stage,
                    stage_rank=context.stage_rank,
                    family=context.family,
                    universe_id=context.universe_id,
                    session_mask=context.session_mask,
                    capital_tier=context.capital_tier,
                    broker=context.broker,
                    data_snapshot=context.data_snapshot,
                    snapshot_root=context.snapshot_root,
                    cost_model=context.cost_model,
                    fill_tier=context.fill_tier,
                    seed=rung.budget,
                    git_sha=context.git_sha,
                    metrics=metrics,
                    daily_returns_ref=ref,
                    status=status,
                )
            )
            rows += 1
            if status == "completed":
                completed += 1
            elif status == "viewed":
                viewed += 1

    return RecordedTrials(rows=rows, completed=completed, viewed=viewed, failures=failures)
