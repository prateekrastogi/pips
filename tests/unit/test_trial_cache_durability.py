"""A half-written cache entry costs a recompute, not every run after it (§3.1, `[C-ID-01]`).

`TrialCache.put` wrote with `path.write_text` and `entry_for` read with a bare `json.loads`. A
kill mid-write leaves a truncated file, and every subsequent lookup of that trial id raises —
permanently, until somebody deletes the file by hand. The cache poisons itself, and the failure
arrives long after the crash that caused it.

This codebase already has a settled answer for exactly this shape, and it is not this one:

* `Manifest.load` — *"An unreadable manifest means we do not know what is done. Starting from
  empty re-fetches, which costs budget; assuming everything is done would leave silent holes.
  Cost is the better failure."*
* `CaptureWriter._last_seq_on_disk` skips a truncated final line rather than refusing to start.
* `promote_bronze` quarantines a record it cannot read.

The class's own docstring says which answer applies here: *"Deliberately not the experiment
registry `[C-REG-01]`: the registry is the append-only record of every viewed trial (rule 4),
while this only avoids recomputing an identical one."* A cache that cannot read an entry has
missed, and a miss costs time. Silently missing would be the wrong answer for the REGISTRY —
undercounting trials is the direction that flatters deflation — which is exactly why the
distinction is worth stating rather than assuming.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pips.core.trial import TrialCache, TrialIdentity

# The real field set, taken from `tests/unit/core/test_trial_identity.py` rather than invented.
# My first version guessed eleven field names and pydantic rejected nineteen -- the same
# assume-the-shape mistake that has cost me four scans and two mutation specs in three days.
BASE: dict[str, Any] = {
    "code_commit": "7b8e32e0a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "data_snapshot_root": "a" * 64,
    "instrument_master_hash": "b" * 64,
    "corporate_action_hash": "c" * 64,
    "calendar_hash": "d" * 64,
    "pipeline_dag_hash": "e" * 64,
    "universe_policy_hash": "f" * 64,
    "split_definition_hash": "0" * 64,
    "cost_model_hash": "1" * 64,
    "parameters": {"lookback": 20, "k": 0.5},
    "fill_tier": "F1",
    "capital_tier": "2L",
    "seed": 7,
    "runtime_versions": {"python": "3.12.7", "polars": "1.9.0"},
}


def identity() -> TrialIdentity:
    return TrialIdentity.model_validate(BASE)


def test_a_valid_entry_round_trips(tmp_path: Path) -> None:
    cache = TrialCache(tmp_path)
    trial_id = cache.put(identity(), {"ic": 0.1})

    assert cache.get(trial_id) == {"ic": 0.1}


def test_a_truncated_entry_reads_as_a_miss_rather_than_raising(tmp_path: Path) -> None:
    """The failure this closes. A `json.JSONDecodeError` here does not surface as "the cache is
    damaged" — it surfaces as the search crashing on a trial it has run before."""
    cache = TrialCache(tmp_path)
    trial_id = cache.put(identity(), {"ic": 0.1})
    path = cache.path_for(trial_id)
    path.write_text(path.read_text()[: len(path.read_text()) // 2], encoding="utf-8")

    assert cache.get(trial_id) is None
    assert cache.entry_for(trial_id) is None


def test_a_damaged_entry_is_replaced_by_the_next_write(tmp_path: Path) -> None:
    """Self-healing is the point of reading a corrupt entry as a miss: the caller recomputes and
    stores, and the damage is gone. A cache that read it as a miss and then refused to overwrite
    would recompute forever."""
    cache = TrialCache(tmp_path)
    trial_id = cache.put(identity(), {"ic": 0.1})
    cache.path_for(trial_id).write_text("{ not json", encoding="utf-8")

    assert cache.get(trial_id) is None
    cache.put(identity(), {"ic": 0.2})

    assert cache.get(trial_id) == {"ic": 0.2}


@pytest.mark.parametrize("content", ["3", "[]", '"a string"', "null"])
def test_an_entry_that_is_valid_json_but_not_an_object_is_a_miss(
    tmp_path: Path, content: str
) -> None:
    """`json.loads` succeeds on `3`, `[]`, `"a string"` and `null`. The first three would be
    RETURNED as the entry and indexed by the caller, so the crash moves one frame outward
    instead of being handled — the same `TypeError` case `CaptureWriter` catches beside its
    `ValueError`.

    `null` is in the list and is the reason the others are: it was the only value I first
    tested, and it is the one case that gives the right answer WITHOUT the guard, because
    `json.loads("null")` is already `None`. A mutation removing the check survived on it.
    """
    cache = TrialCache(tmp_path)
    trial_id = cache.put(identity(), {"ic": 0.1})
    cache.path_for(trial_id).write_text(content, encoding="utf-8")

    assert cache.entry_for(trial_id) is None
    assert cache.get(trial_id) is None


def test_the_write_goes_through_the_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading a corrupt entry gracefully is the second line of defence; not producing one is
    the first. `core/atomic.py` exists for this and says why: "two copies of a rule are two
    places for it to drift".

    Pinned by mechanism because crash-safety cannot be observed without a crash — the same
    reasoning as the QC verdict file's test.
    """
    from pips.core.atomic import atomic_write_text

    used: list[Path] = []

    def spy(path: Path, text: str) -> None:
        used.append(path)
        atomic_write_text(path, text)

    monkeypatch.setattr("pips.core.trial.atomic_write_text", spy)
    cache = TrialCache(tmp_path)
    trial_id = cache.put(identity(), {"ic": 0.1})

    assert used == [cache.path_for(trial_id)]
