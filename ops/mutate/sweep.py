"""``make sweep`` -- every production module changed against BASE is swept by a committed spec.

Manual sweeps found the day's best defects (2026-09-05) and nothing enforced them. This runs in
the ladder: the production modules changed against ``BASE`` (default ``origin/main``, like
``tdd-check``) each need a spec under ``ops/mutate/specs/`` naming them as ``source``; a changed
module WITHOUT a spec is red -- the ratchet ``ledger-check`` applies to rows -- and a spec that
fails (a survivor not declared ``expect: survive`` with a ``why``, a red baseline, a stale anchor)
is red and named.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

PRODUCTION = "python/pips/"
SPECS = pathlib.Path("ops/mutate/specs")


@dataclass
class Plan:
    to_run: list[pathlib.Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def _is_production(path: str) -> bool:
    return path.startswith(PRODUCTION) and path.endswith(".py") and not path.endswith("__init__.py")


def plan(*, changed: Sequence[str], specs_dir: pathlib.Path) -> Plan:
    """Match changed production modules to specs; name the ones nobody covers."""
    by_source: dict[str, pathlib.Path] = {}
    if specs_dir.exists():
        for spec in sorted(specs_dir.glob("*.json")):
            by_source[str(json.loads(spec.read_text(encoding="utf-8"))["source"])] = spec
    out = Plan()
    for path in sorted(set(changed)):
        if not _is_production(path):
            out.ignored.append(path)
        elif path in by_source:
            out.to_run.append(by_source[path])
        else:
            out.missing.append(path)
    return out


def run(
    *,
    changed: Sequence[str],
    specs_dir: pathlib.Path,
    runner: Callable[[pathlib.Path], int],
) -> int:
    p = plan(changed=changed, specs_dir=specs_dir)
    if not p.to_run and not p.missing:
        print("sweep: no production module changed against BASE -- nothing to sweep.")
        return 0
    rc = 0
    for spec in p.to_run:
        print(f"sweep: {spec}")
        result = runner(spec)
        print(f"sweep: {spec.name} {'ok' if result == 0 else 'FAILED'}")
        rc = rc or (1 if result != 0 else 0)
    if p.missing:
        print(f"sweep: {len(p.missing)} changed production module(s) have NO mutation spec:")
        for path in p.missing:
            print(f"    {path}")
        print('    Add ops/mutate/specs/<name>.json with "source": "<path>" -- a changed module')
        print("    nobody swept is the shape every survivor today had.")
        rc = 1
    return rc


def _changed_against(base: str) -> list[str]:
    committed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True, check=True
    ).stdout.split()
    working = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return committed + [line[3:] for line in working if line.strip()]


def _run_tool(spec: pathlib.Path) -> int:
    tool = pathlib.Path(__file__).with_name("mutate.py")
    return subprocess.run([sys.executable, str(tool), str(spec)], check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sweep")
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    return run(changed=_changed_against(args.base), specs_dir=SPECS, runner=_run_tool)


if __name__ == "__main__":
    sys.exit(main())
