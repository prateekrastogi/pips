"""The determinism gate itself  (constitution rule 1).

Rule 1 says the same `(config, data_snapshot_id, seed)` must give **bit-identical output** —
across runs, which means across processes. The check generated twice inside one interpreter,
so it shared a `PYTHONHASHSEED` with itself and could not see the most common source of
cross-run non-determinism in Python: a `set` or `dict` iterated without sorting produces one
order for the whole life of a process and a different one in the next.

That is not hypothetical here. The PIT store's `as_of` key list is `sorted()` for exactly this
reason, and the sweep that found it noted the same thing: set iteration order is neither
insertion order nor stable across processes. A gate that runs twice in one process would have
passed a version without that `sorted()`.
"""

from __future__ import annotations

from pathlib import Path

from pips.fixtures.determinism import HASH_SEEDS, diff_runs, generate_under_seed


def test_the_two_runs_use_different_hash_seeds() -> None:
    """Otherwise the gate compares a process against itself.

    Two seeds, and they must differ — a pair of identical seeds is the in-process check wearing
    a subprocess costume, and it would look exactly as green.
    """
    assert len(HASH_SEEDS) == 2
    assert HASH_SEEDS[0] != HASH_SEEDS[1]


def test_the_fixture_pipeline_is_seed_independent(tmp_path: Path) -> None:
    """The property the gate exists to assert, stated directly.

    Generating under two hash seeds must produce identical file hashes and an identical
    manifest root. This is what a `sorted()` missing from an iteration order would break, and
    what the in-process comparison could never have detected.
    """
    first = generate_under_seed(tmp_path / "a", HASH_SEEDS[0])
    second = generate_under_seed(tmp_path / "b", HASH_SEEDS[1])

    assert first["manifest_hash"] == second["manifest_hash"]
    assert first["files"] == second["files"]


def test_the_gate_reports_no_differences() -> None:
    """End to end, which is what `make ci` runs."""
    assert diff_runs() == []
