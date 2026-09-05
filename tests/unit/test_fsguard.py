"""`writable_directory`: a real write, not a permission-bit guess, and no directory left behind."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pips.core.fsguard import writable_directory


def test_an_absent_directory_is_probed_and_not_left_behind(tmp_path: Path) -> None:
    target = tmp_path / "new" / "deeper"
    assert writable_directory(target) is None
    assert not target.exists()
    assert not (tmp_path / "new").exists() or (tmp_path / "new").is_dir()


def test_an_existing_writable_directory_is_kept_and_left_clean(tmp_path: Path) -> None:
    target = tmp_path / "out"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    assert writable_directory(target) is None
    assert target.is_dir() and sorted(p.name for p in target.iterdir()) == ["keep.txt"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere; the probe cannot fail")
def test_a_read_only_directory_is_refused_by_the_probe_not_by_mkdir(tmp_path: Path) -> None:
    target = tmp_path / "ro"
    target.mkdir()
    target.chmod(0o500)
    try:
        refusal = writable_directory(target)
    finally:
        target.chmod(0o700)
    assert refusal is not None
    assert "cannot write" in refusal and str(target) in refusal
    assert "re-run" in refusal


def test_a_file_where_the_directory_should_be_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "out"
    target.write_text("not a directory")
    refusal = writable_directory(target)
    assert refusal is not None and str(target) in refusal


def test_an_existing_empty_directory_is_kept(tmp_path: Path) -> None:
    # /srv/pips/universes on arb-vm: created by the plant, empty until the first artifact.
    # The probe must not mistake it for one it created and remove it.
    target = tmp_path / "universes"
    target.mkdir()
    assert writable_directory(target) is None
    assert target.is_dir()
