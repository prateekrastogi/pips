"""``make determinism`` -- run a small pipeline twice and diff the hashes.

Constitution rule 1: same ``(config, data_snapshot_id, seed)`` must give bit-identical
output. This runs the fixture pipeline into two scratch directories and compares every
file hash plus the manifest root. Any difference is a determinism bug, and a
determinism bug is a release blocker, not a flake to be retried.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pips.fixtures.generate import FixtureSpec, generate

__all__ = ["diff_runs", "main"]


def diff_runs(spec: FixtureSpec | None = None) -> list[str]:
    """Generate twice into scratch dirs; return the list of differing artifacts."""
    spec = spec or FixtureSpec()
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        first = generate(Path(a), spec)
        second = generate(Path(b), spec)

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
