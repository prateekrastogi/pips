"""No image writes the shared volume as root  (§2.2, rule 14).

Promoting bronze to silver produced a parquet owned by `root` that the VM's `ubuntu` user could
not rewrite. A second promotion would have failed on permissions — in exactly the case the
design promises is safe, since promotion is idempotent.

The cause was asymmetry nobody had noticed: `reader` runs as uid 10002 and `engine` as uid
10001, both declared in their Dockerfiles, and `research` declared nothing and therefore ran as
root. Three images write one bind-mounted tree under three identities.

The uids stay DIFFERENT on purpose — the data plane and the order plane are separate processes
(rule 7), and collapsing them to one identity would undo that. What they share is a GROUP, so
one service can rewrite what another wrote without any of them being root.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ["research", "reader", "engine"]
SHARED_GID = 10000


def dockerfile(name: str) -> str:
    return (ROOT / "docker" / f"{name}.Dockerfile").read_text(encoding="utf-8")


@pytest.mark.parametrize("image", IMAGES)
def test_the_image_runs_as_a_named_user(image: str) -> None:
    """An image with no USER runs as root, and root writes files nobody else can replace."""
    assert re.search(r"^USER\s+pips\s*$", dockerfile(image), re.M), f"{image} has no USER"


@pytest.mark.parametrize("image", IMAGES)
def test_the_user_is_in_the_shared_group(image: str) -> None:
    """The group is what lets one service rewrite another's files.

    Without it, three images writing one volume leave three sets of files none of the others can
    touch — and the failure appears as a permission error in whichever job runs second, which
    reads as a broken job rather than as a broken convention.
    """
    text = dockerfile(image)
    assert f"--gid {SHARED_GID}" in text, f"{image}'s user is not in the shared group"
    assert f"groupadd --system --gid {SHARED_GID} pips" in text


@pytest.mark.parametrize("image", IMAGES)
def test_the_uid_is_not_root(image: str) -> None:
    match = re.search(r"useradd[^\n]*--uid (\d+)", dockerfile(image))
    assert match, f"{image} declares no uid"
    assert int(match.group(1)) > 1000, "a system uid, not root and not a host user's"


def test_the_planes_keep_separate_identities() -> None:
    """Rule 7: two planes, two credentials, two processes.

    Sharing a group is not sharing an identity. Collapsing reader and engine onto one uid would
    make the shared volume convenient and the process separation nominal.
    """
    uids = {
        image: int(re.search(r"useradd[^\n]*--uid (\d+)", dockerfile(image)).group(1))  # type: ignore[union-attr]
        for image in IMAGES
    }
    assert len(set(uids.values())) == len(uids), uids
