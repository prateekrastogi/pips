"""Rule 14's guard, in one place  (§2 rule 14).

Market data lives on arb-vm; the laptop holds code and fixtures. Two modules enforced that
with two copies of the same function, differing only in wording — and both located the
repository as `Path(__file__).resolve().parents[4]`, a constant that is only correct while
the file stays exactly four directories deep.

**This guard fails silently when it fails.** A wrong repository root makes `relative_to` raise,
which the guard reads as "the path is outside the repo" and allows. So a module moved one
directory would keep passing its own tests while quietly permitting exactly what rule 14
forbids — and the mutation sweep has already shown what that costs: deleting the guard put a
bronze record in `./data` for real, and `make ci` reported it three tests away from the cause.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pips.core.locality import refuse_repo_paths, repo_root


def test_the_repository_is_found_by_its_marker_not_by_counting_directories() -> None:
    root = repo_root()
    assert root is not None
    assert (root / ".git").exists()
    assert (root / "IMPLEMENTATION.md").exists(), "this is the pips working tree, not a parent"


def test_a_path_inside_the_working_tree_is_refused() -> None:
    root = repo_root()
    assert root is not None
    with pytest.raises(ValueError, match="rule 14"):
        refuse_repo_paths(root / "data" / "bronze", what="bronze")


def test_the_refusal_names_what_was_being_written(tmp_path: Path) -> None:
    root = repo_root()
    assert root is not None
    with pytest.raises(ValueError, match="tick capture"):
        refuse_repo_paths(root / "data" / "ws", what="tick capture")


def test_a_path_outside_the_working_tree_is_allowed(tmp_path: Path) -> None:
    refuse_repo_paths(tmp_path / "srv" / "pips" / "bronze", what="bronze")


def test_both_writers_use_the_shared_guard_rather_than_their_own() -> None:
    """One rule, one implementation.

    Two copies are two places for it to drift and only one of them is the one under test —
    `silver_panel.py`'s own argument, applied to the guard that keeps a live tick stream out
    of a git tree.
    """
    for module in ("backfill", "capture"):
        source = (
            Path(__file__).resolve().parents[2]
            / "python"
            / "pips"
            / "data"
            / "breeze"
            / f"{module}.py"
        ).read_text(encoding="utf-8")
        assert "refuse_repo_paths" in source, f"{module} must still enforce rule 14"
        assert "parents[4]" not in source, (
            f"{module} still locates the repository by counting directories"
        )
        assert "def _refuse_repo_paths" not in source, f"{module} keeps its own copy of the guard"


def test_with_no_working_tree_nothing_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deployed case, and the one that would be discovered in production.

    The service on arb-vm runs from an image built out of the tree, not from the tree — no
    `.git`, so no repository to protect. Refusing every path there would leave the container
    unable to write bronze anywhere at all, and the guard meant to keep market data off the
    laptop would have stopped the only machine that is supposed to hold it.
    """
    monkeypatch.setattr("pips.core.locality.repo_root", lambda: None)
    refuse_repo_paths(tmp_path / "anywhere", what="bronze")
    refuse_repo_paths(Path("/srv/pips/bronze"), what="bronze")
