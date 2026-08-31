"""Test-first enforcement [G-TDD-01] (constitution rule 16, §7.1).

Written before ``python/pips/ledger/tdd.py`` existed -- this file is the rule's own
first application.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pips.ledger.tdd import Commit, classify, evaluate, git_commits


def _c(sha: str, files: list[str], exempt: str | None = None) -> Commit:
    return Commit(sha=sha, subject=f"subject {sha}", files=tuple(files), exempt_reason=exempt)


@pytest.mark.parametrize(
    "path",
    ["python/pips/costs/statutory.py", "rust/crates/oms/src/lib.rs", "schemas/forecast/v1.json"],
)
def test_production_paths_are_recognised(path: str) -> None:
    production, tests = classify([path])
    assert production and not tests


@pytest.mark.parametrize(
    "path", ["tests/unit/core/test_ids.py", "rust/crates/oms/tests/state.rs", "tests/property/x.py"]
)
def test_test_paths_are_recognised(path: str) -> None:
    production, tests = classify([path])
    assert tests and not production


@pytest.mark.parametrize("path", ["docs/state/CURRENT.md", "Makefile", "ops/deploy/sync.sh"])
def test_neither_docs_nor_ops_count_as_production(path: str) -> None:
    assert classify([path]) == (False, False)


def test_code_with_tests_in_the_same_commit_passes() -> None:
    assert (
        evaluate([_c("a1", ["python/pips/costs/statutory.py", "tests/unit/costs/test_x.py"])]) == []
    )


def test_code_with_no_test_anywhere_on_the_branch_is_a_violation() -> None:
    failures = evaluate([_c("a1", ["python/pips/costs/statutory.py"])])
    assert len(failures) == 1 and "a1" in failures[0]


def test_a_prior_test_commit_authorises_later_code_commits() -> None:
    commits = [
        _c("a1", ["tests/unit/costs/test_x.py"]),
        _c("a2", ["python/pips/costs/statutory.py"]),
    ]
    assert evaluate(commits) == []


def test_code_before_its_test_is_a_violation_even_if_the_test_arrives_later() -> None:
    commits = [
        _c("a1", ["python/pips/costs/statutory.py"]),
        _c("a2", ["tests/unit/costs/test_x.py"]),
    ]
    failures = evaluate(commits)
    assert len(failures) == 1 and "a1" in failures[0]


def test_an_exemption_must_carry_a_reason() -> None:
    assert (
        evaluate([_c("a1", ["python/pips/x.py"], exempt="pure rename, behaviour pinned by test_x")])
        == []
    )
    assert evaluate([_c("a1", ["python/pips/x.py"], exempt="   ")]) != []


def test_docs_only_branches_are_not_forced_to_add_tests() -> None:
    assert evaluate([_c("a1", ["docs/state/CURRENT.md", "IMPLEMENTATION.md"])]) == []


def test_git_walk_reads_real_history(tmp_path: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (tmp_path / "README.md").write_text("x\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    run("checkout", "-q", "-b", "feature")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a() -> None: ...\n")
    run("add", "-A")
    run("commit", "-qm", "test: red first")
    commits = git_commits(tmp_path, "main")
    assert [c.subject for c in commits] == ["test: red first"]
    assert commits[0].files == ("tests/test_a.py",)
