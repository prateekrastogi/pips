"""``pips ledger check`` -- close the loop between prose, ledger, code and tests (§8.2).

Verifies, over ``IMPLEMENTATION.md`` + ``docs/ledger/``:

1. every ledger id is unique;
2. every ``C-``/``G-`` id cited in the prose exists in the ledger, and every ledger row
   is cited by the prose (no orphans in either direction);
3. every row's ``spec:`` anchor resolves to a real heading;
4. status >= ``building`` implies its ``code:`` path exists;
5. status == ``enforced`` implies its ``tests:`` exist and are collectable.

Exit code 0 = green. Any failure prints the exact rows and exits 1 -- and the fix is
never to soften the check (constitution rule 10).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from pips.ledger.model import Ledger, Status, load_ledger

__all__ = ["check_ledger", "cited_ids", "heading_slugs", "main"]

_RANGE_RE = re.compile(r"\b([CG]-[A-Z0-9]+)-(\d+)…(\d+)\b")
_GLOB_RE = re.compile(r"\b([CG]-[A-Z0-9]+)-\*")
_PLAIN_RE = re.compile(r"\b([CG]-[A-Z0-9]+-[A-Z0-9]+)\b")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)


def _slugify(heading: str) -> str:
    text = heading.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"-+", "-", re.sub(r"\s+", "-", text)).strip("-")


def heading_slugs(markdown: str) -> set[str]:
    """GitHub-ish anchor slugs for every heading in a markdown document."""
    return {_slugify(h) for h in _HEADING_RE.findall(markdown)}


def cited_ids(prose: str, known_ids: list[str]) -> set[str]:
    """Ids cited by the prose, expanding ``A…B`` ranges and ``PREFIX-*`` globs."""
    cited: set[str] = set(_PLAIN_RE.findall(prose))
    for prefix, lo, hi in _RANGE_RE.findall(prose):
        width = len(lo)
        cited.update(f"{prefix}-{n:0{width}d}" for n in range(int(lo), int(hi) + 1))
    for prefix in _GLOB_RE.findall(prose):
        cited.update(i for i in known_ids if i.startswith(f"{prefix}-"))
    return cited


def _collectable_pytest(root: Path, node_ids: list[str]) -> list[str]:
    """Return the node ids pytest does *not* collect."""
    if not node_ids:
        return []
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    collected = result.stdout
    return [n for n in node_ids if n not in collected]


def _rust_test_present(root: Path, ref: str) -> bool:
    """``rust/crates/<c>/src/x.rs::test_name`` -- the file exists and declares that test."""
    path_part, _, test_name = ref.partition("::")
    target = root / path_part
    if not target.exists():
        return False
    return not test_name or f"fn {test_name}" in target.read_text(encoding="utf-8")


def check_ledger(root: Path) -> list[str]:
    """Run every check; return a list of human-readable failures (empty == green)."""
    failures: list[str] = []
    prose_path = root / "IMPLEMENTATION.md"
    ledger: Ledger = load_ledger(root / "docs" / "ledger")
    prose = prose_path.read_text(encoding="utf-8")

    duplicates = [i for i, n in Counter(ledger.all_ids).items() if n > 1]
    failures += [f"duplicate ledger id: {i}" for i in sorted(duplicates)]

    ledger_ids = set(ledger.all_ids)
    cited = cited_ids(prose, ledger.all_ids)
    failures += [f"cited in prose but absent from ledger: {i}" for i in sorted(cited - ledger_ids)]
    failures += [f"in ledger but never cited in prose: {i}" for i in sorted(ledger_ids - cited)]

    slugs = heading_slugs(prose)
    pytest_nodes: list[str] = []
    for row in [*ledger.contracts, *ledger.gates]:
        doc, _, anchor = row.spec.partition("#")
        if doc != "IMPLEMENTATION.md":
            failures.append(f"{row.id}: spec must point at IMPLEMENTATION.md, got {row.spec!r}")
        elif not anchor or not any(s.startswith(anchor) for s in slugs):
            failures.append(f"{row.id}: spec anchor #{anchor} matches no heading")

        if row.status.rank >= Status.BUILDING.rank:
            if not row.code:
                failures.append(f"{row.id}: status {row.status} requires a code: path")
            elif not (root / row.code).exists():
                failures.append(f"{row.id}: code path does not exist: {row.code}")

        if row.status is Status.ENFORCED:
            if not row.tests:
                failures.append(f"{row.id}: status enforced requires at least one test")
            for ref in row.tests:
                if ref.startswith("rust/"):
                    if not _rust_test_present(root, ref):
                        failures.append(f"{row.id}: rust test not found: {ref}")
                else:
                    pytest_nodes.append(ref)

    failures += [f"pytest does not collect: {n}" for n in _collectable_pytest(root, pytest_nodes)]
    return failures


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``pips ledger check``."""
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(args[0]) if args else Path.cwd()
    failures = check_ledger(root)
    ledger = load_ledger(root / "docs" / "ledger")
    if failures:
        print(f"ledger-check FAILED ({len(failures)} problem(s)):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    by_status = Counter(r.status.value for r in [*ledger.contracts, *ledger.gates])
    summary = " ".join(f"{k}={by_status[k]}" for k in ("planned", "building", "enforced"))
    print(f"ledger-check OK: {len(ledger.all_ids)} rows ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
