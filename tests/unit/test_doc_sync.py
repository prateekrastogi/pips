"""CLAUDE.md and LOOP.md are copies of IMPLEMENTATION.md §10.3 / §10.6 -- keep them equal.

Drift here is how a constitution quietly forks: the loop reads LOOP.md, a human reads
IMPLEMENTATION.md, and they stop saying the same thing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("filename", "section"), [("CLAUDE.md", "### 10.3"), ("LOOP.md", "### 10.6")]
)
def test_root_file_matches_its_in_document_copy(filename: str, section: str) -> None:
    impl = (ROOT / "IMPLEMENTATION.md").read_text(encoding="utf-8")
    block = impl.split(section, 1)[1]
    match = re.search(r"```md\n(.*?)\n```", block, re.S)
    assert match is not None, f"no fenced md block after {section}"
    assert match.group(1).strip() == (ROOT / filename).read_text(encoding="utf-8").strip()


def test_the_constitution_states_the_test_first_rule() -> None:
    impl = (ROOT / "IMPLEMENTATION.md").read_text(encoding="utf-8")
    assert "16. **Test-first (TDD), always.**" in impl
    assert "### 7.1 Test-first protocol (TDD)" in impl
    for filename in ("CLAUDE.md", "LOOP.md"):
        assert "tdd-check" in (ROOT / filename).read_text(encoding="utf-8")
