#!/usr/bin/env python3
"""Mutation runner. Replaces a shell loop that failed in three separate ways.

1. `str.replace(old, new, 1)` silently mutated the FIRST of several identical anchors, so two
   mutations were scored against code the tests never exercised. -> the anchor must be UNIQUE.
2. `case $OUT in *failed*)` never matched pytest's uppercase `FAILED`, so six kills were
   reported as survivals. -> classify on the EXIT CODE, never on output text.
3. A backgrounded pytest plus a `sleep` watchdog could outlive an interrupted tick, and the
   `trap 'kill 0'` meant to fix that killed its own process group. -> subprocess timeout, which
   kills the child and leaves nothing behind however this process ends.

Usage: mutate.py <spec.json>
  {"source": "path.py", "tests": ["tests/..."], "timeout": 90,
   "mutations": [{"name": "...", "old": "...", "new": "..."}]}
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys


def _canary_dies(source: pathlib.Path, original: str, tests: list[str], timeout: int) -> bool:
    """Do the listed tests actually EXERCISE this source?

    Twice now a sweep has run against the wrong test file -- a glob that matched
    `test_universe_snapshot.py` but not `test_liquidity.py`, and one that matched
    `test_bundle_writer.py` but not `test_strategy_bundle.py` -- and reported every mutant as
    surviving. That looks exactly like a discovery: "the weights can be flipped with no test
    noticing", "the content hash is not checked". Both were false, and both were alarming
    enough to be believed.

    Being careful did not fix it, so the harness checks instead. A module-level `raise` is the
    most fatal mutation there is: any test that imports this source, directly or through
    anything else, must fail. If the suite still passes, the tests do not touch this file and
    every result below would be noise.
    """
    source.write_text(original + '\n\nraise RuntimeError("mutation harness canary")\n')
    try:
        probe = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "--no-header", *tests],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return probe.returncode != 0
    except subprocess.TimeoutExpired:
        return True
    finally:
        source.write_text(original)


def _stray_repo_data(root: pathlib.Path) -> list[str]:
    """Files a mutant wrote into the repo's data zones.

    A mutation that disables a SAFETY GUARD makes the unsafe thing happen for real. Deleting
    `_refuse_repo_paths` (rule 14) let the backfill CLI write a bronze record into ./data --
    the source was restored, the side effect was not, and `make ci` went red in a test that had
    nothing to do with the sweep. The harness restores files; it cannot restore the filesystem.
    """
    zones = [root / "data" / z for z in ("bronze", "silver", "gold", "quarantine")]
    return [
        str(f)
        for z in zones
        if z.exists()
        for f in z.rglob("*")
        if f.is_file() and f.name != ".gitkeep"
    ]


def main() -> int:
    spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
    source = pathlib.Path(spec["source"])

    # CRASH RECOVERY. `finally` does not survive SIGKILL, and the harness kills a command at ten
    # minutes -- which once left a mutation in the working tree, passed the suite that had run
    # BEFORE it in the same command, and got committed. Jenkins caught it; nothing local did.
    #
    # So the pristine text is written to disk before anything is mutated, and a leftover copy is
    # restored on the next run rather than assumed absent.
    backup = source.with_suffix(source.suffix + ".mutorig")
    if backup.exists():
        source.write_text(backup.read_text())
        print(f"  RECOVERED {source} from a previous run that was killed before restoring")
    original = source.read_text()
    backup.write_text(original)
    timeout = spec.get("timeout", 90)
    killed = survived = broken = 0

    try:
        if not _canary_dies(source, original, spec["tests"], spec.get("timeout", 90)):
            print("  !! THE LISTED TESTS DO NOT EXERCISE THIS SOURCE.")
            print(f"     A module-level raise in {source} left them passing, so every")
            print("     'SURVIVED' below would be noise. Check the test paths in the spec.")
            backup.unlink(missing_ok=True)
            return 1

        for mutation in spec["mutations"]:
            name, old, new = mutation["name"], mutation["old"], mutation["new"]
            occurrences = original.count(old)
            if occurrences != 1:
                print(f"  [{name}] ANCHOR NOT UNIQUE ({occurrences} occurrences) -- not run")
                broken += 1
                continue

            source.write_text(original.replace(old, new))
            subprocess.run(
                [
                    "find",
                    ".",
                    "-name",
                    "__pycache__",
                    "-path",
                    "*/pips/*",
                    "-exec",
                    "rm",
                    "-rf",
                    "{}",
                    "+",
                ],
                capture_output=True,
                check=False,
            )
            try:
                completed = subprocess.run(
                    ["uv", "run", "pytest", *spec["tests"]],
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
                verdict = "KILLED" if completed.returncode else "*** SURVIVED ***"
            except subprocess.TimeoutExpired:
                verdict = "HUNG (timed out -- a stall, not a clean failure)"
            finally:
                source.write_text(original)

            print(f"  [{name}] {verdict}")
            if verdict.startswith("KILLED") or verdict.startswith("HUNG"):
                killed += 1
            else:
                survived += 1
    finally:
        source.write_text(original)
        backup.unlink(missing_ok=True)
        subprocess.run(
            [
                "find",
                ".",
                "-name",
                "__pycache__",
                "-path",
                "*/pips/*",
                "-exec",
                "rm",
                "-rf",
                "{}",
                "+",
            ],
            capture_output=True,
            check=False,
        )

    print(
        f"\n  {killed} killed, {survived} survived"
        + (f", {broken} not run (bad anchor)" if broken else "")
    )

    stray = _stray_repo_data(pathlib.Path.cwd())
    if stray:
        print(f"\n  !! {len(stray)} file(s) written into the repo's data zones by a mutant:")
        for f in stray:
            print(f"       {f}")
        print("     Rule 14. Delete them before committing -- `make ci` will go red on a test")
        print("     that has nothing to do with the sweep.")
        return 1
    return 1 if survived or broken else 0


if __name__ == "__main__":
    sys.exit(main())
