"""``make determinism`` -- run a small pipeline twice and diff the hashes.

Constitution rule 1: same ``(config, data_snapshot_id, seed)`` must give bit-identical
output. This runs the fixture pipeline into two scratch directories and compares every
file hash plus the manifest root. Any difference is a determinism bug, and a
determinism bug is a release blocker, not a flake to be retried.

**In two processes, under two different hash seeds.** A run is a process, and generating twice
inside one interpreter shares a ``PYTHONHASHSEED`` with itself -- so an unsorted ``set``
iteration gives the same order both times and the gate sees nothing, while the next run orders
it differently. See :data:`HASH_SEEDS`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pips.fixtures.generate import FixtureSpec

__all__ = ["HASH_SEEDS", "diff_runs", "generate_under_seed", "main"]

HASH_SEEDS: tuple[str, str] = ("0", "524287")
"""Two DIFFERENT interpreter hash seeds, which is the whole point of running out of process.

Rule 1 asks for bit-identical output across runs, and a run is a process. Generating twice
inside one interpreter shares a `PYTHONHASHSEED` with itself, so a `set` or `dict` iterated
without sorting yields the same order both times and the gate sees nothing -- while the next
run, on another machine or after a restart, orders it differently. That is not a hypothetical
failure mode here: `PitStore.as_of` sorts its key list for exactly this reason, and a version
missing that `sorted()` would have passed an in-process comparison.
"""


def generate_under_seed(
    target: Path, hash_seed: str, spec: FixtureSpec | None = None
) -> dict[str, Any]:
    """Generate the fixtures in a FRESH interpreter pinned to ``hash_seed``.

    A subprocess rather than a thread or a re-import: `PYTHONHASHSEED` is read once at
    interpreter start and cannot be changed from inside a running one, so nothing short of a
    new process can vary it.

    The spec crosses as JSON rather than being pickled, so what the child builds is exactly
    what a reader of the command can see.
    """
    fields = json.dumps(dataclasses.asdict(spec or FixtureSpec()))
    child = (
        "import json, sys; from pathlib import Path; "
        "from pips.fixtures.generate import FixtureSpec, generate; "
        "print(json.dumps(generate(Path(sys.argv[1]), FixtureSpec(**json.loads(sys.argv[2])))))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", child, str(target), fields],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
    )
    return dict(json.loads(completed.stdout))


def diff_runs(spec: FixtureSpec | None = None) -> list[str]:
    """Generate twice, in two processes under two hash seeds; return differing artifacts."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        first = generate_under_seed(Path(a), HASH_SEEDS[0], spec)
        second = generate_under_seed(Path(b), HASH_SEEDS[1], spec)

    diffs: list[str] = []
    files_a = first["files"]
    files_b = second["files"]
    for name in sorted(set(files_a) | set(files_b)):
        if files_a.get(name) != files_b.get(name):
            diffs.append(f"{name}: {files_a.get(name)} != {files_b.get(name)}")
    if first["manifest_hash"] != second["manifest_hash"]:
        diffs.append(f"manifest_hash: {first['manifest_hash']} != {second['manifest_hash']}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    _ = argv
    diffs = diff_runs()
    if diffs:
        print(f"determinism FAILED ({len(diffs)} differing artifact(s)):")
        for diff in diffs:
            print(f"  - {diff}")
        return 1
    print("determinism OK: two independent runs are bit-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
