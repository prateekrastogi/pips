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


def test_every_make_target_the_root_docs_name_exists() -> None:
    """A doc naming a target that does not exist sends the reader to a command that cannot run.

    Cheap to check and it drifts silently otherwise: targets get renamed, prose does not.
    """
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-z][a-z0-9-]*):", makefile, re.M))
    for filename in ("CLAUDE.md", "LOOP.md"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        for match in re.finditer(r"`make ([a-z][a-z0-9-]+)", text):
            assert match.group(1) in targets, f"{filename} names `make {match.group(1)}`"


@pytest.mark.parametrize("filename", ["CLAUDE.md", "LOOP.md", "IMPLEMENTATION.md"])
def test_the_docs_do_not_send_the_ladder_through_a_floating_image_tag(filename: str) -> None:
    """The gate defect, encoded so it cannot come back through the prose.

    `docker compose run research make ci` was documented as THE way to verify. The service
    resolves `image: pips/research:${PIPS_SHA:-current}` with no bind mount and no build on
    run, so with PIPS_SHA unset — every laptop invocation — it runs a tag nothing keeps
    current. It reported `ci: green` from an image built the previous day from a different
    commit, whose validation/ package predated two milestones.

    `make ci-container` builds from the working tree and passes the commit it built, so the
    in-image preflight can refuse a mismatch. The docs have to name that one.
    """
    text = (ROOT / filename).read_text(encoding="utf-8")
    assert "docker compose run research make ci" not in text, (
        f"{filename} documents running the ladder through the floating `current` tag; "
        "use `make ci-container`, which builds the image from the working tree"
    )
