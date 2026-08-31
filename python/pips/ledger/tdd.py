"""``pips tdd check`` -- test-first enforcement  [G-TDD-01] (constitution rule 16).

Walks the branch's commits oldest-first and refuses any commit that introduces
production code without a test having landed in that commit or an earlier one on the
branch. Docs, ops and config changes are not production code and are not forced to
carry tests.

The escape hatch is deliberately loud, never silent: a commit may carry a
``TDD-Exempt: <reason>`` trailer (pure renames, mechanical refactors whose behaviour is
already pinned). An empty reason is not an exemption, and every exemption is printed by
the check so it shows up in the Jenkins log and in review.

This checks *ordering*, which is what a machine can see. The other half of the rule --
that the test was observed to FAIL before the code made it pass -- is evidence a human
or agent records: the red output goes in the session log and the PR body (§7.1).
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Commit", "classify", "evaluate", "git_commits", "main"]

_PRODUCTION_PREFIXES = ("python/pips/", "rust/crates/", "schemas/", "apps/")
_TEST_PREFIXES = ("tests/",)
_TEST_MARKERS = ("/tests/", "/test_", "_test.")
_EXEMPT_TRAILER = "TDD-Exempt:"


@dataclass(frozen=True)
class Commit:
    """One commit on the branch: what it touched and whether it claims an exemption."""

    sha: str
    subject: str
    files: tuple[str, ...]
    exempt_reason: str | None = None

    @property
    def short(self) -> str:
        return self.sha[:12]


def _is_test(path: str) -> bool:
    return path.startswith(_TEST_PREFIXES) or any(m in path for m in _TEST_MARKERS)


def classify(paths: list[str] | tuple[str, ...]) -> tuple[bool, bool]:
    """Return ``(touches_production, touches_tests)`` for a set of changed paths."""
    production = any(p.startswith(_PRODUCTION_PREFIXES) and not _is_test(p) for p in paths)
    tests = any(_is_test(p) for p in paths)
    return production, tests


def evaluate(commits: list[Commit]) -> list[str]:
    """Return a list of test-first violations (empty == green)."""
    failures: list[str] = []
    tests_seen = False
    for commit in commits:
        production, tests = classify(commit.files)
        if production and not tests and not tests_seen:
            reason = (commit.exempt_reason or "").strip()
            if not reason:
                failures.append(
                    f"{commit.short} {commit.subject!r}: production code with no test "
                    f"in this or any earlier commit on the branch "
                    f"(write the failing test first, or add a 'TDD-Exempt: <reason>' trailer)"
                )
        tests_seen = tests_seen or tests
    return failures


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def git_commits(root: Path, base: str = "main") -> list[Commit]:
    """Commits on ``HEAD`` that are not on ``base``, oldest first."""
    try:
        merge_base = _git(root, "merge-base", base, "HEAD").strip()
    except RuntimeError:
        return []
    shas = _git(root, "rev-list", "--reverse", f"{merge_base}..HEAD").split()
    commits: list[Commit] = []
    for sha in shas:
        subject = _git(root, "log", "-1", "--pretty=%s", sha).strip()
        body = _git(root, "log", "-1", "--pretty=%B", sha)
        exempt = next(
            (
                line.split(_EXEMPT_TRAILER, 1)[1].strip()
                for line in body.splitlines()
                if line.strip().startswith(_EXEMPT_TRAILER)
            ),
            None,
        )
        files = tuple(
            f for f in _git(root, "show", "--name-only", "--pretty=format:", sha).split() if f
        )
        commits.append(Commit(sha=sha, subject=subject, files=files, exempt_reason=exempt))
    return commits


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``pips tdd check [base] [root]``."""
    args = list(argv if argv is not None else sys.argv[1:])
    base = args[0] if args else "main"
    root = Path(args[1]) if len(args) > 1 else Path.cwd()

    commits = git_commits(root, base)
    if not commits:
        print(f"tdd-check OK: no commits ahead of {base}")
        return 0

    for commit in commits:
        if (commit.exempt_reason or "").strip():
            print(f"tdd-check EXEMPTION {commit.short}: {commit.exempt_reason}")

    failures = evaluate(commits)
    if failures:
        print(f"tdd-check FAILED ({len(failures)} commit(s) added code before a test):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"tdd-check OK: {len(commits)} commit(s) on this branch are test-first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
