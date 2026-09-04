"""The deploy rail reclaims the images it builds (`[C-DEPLOY-01]`, `[G-DEPLOY-01]`).

On 2026-09-04 the rail stopped: `fatal: write error: No space left on device`, failing every
two minutes and alerting each time. arb-vm's disk was 96G/96G with **zero** bytes free, and
Docker held 476 tagged `pips/*` images totalling 83.7 GB, 92% of it reclaimable. Exactly one was
dangling — so a routine `docker image prune` would have freed nothing. The garbage was *tagged*:
one `research`/`engine`/`reader` trio per deployed SHA, roughly 3 GB each, never removed.

**An age filter would not have saved it.** 220 of those images were two days old and 175 three
days old, but the day it filled, fourteen commits reached main — every one of them under any
plausible `until=24h` cutoff. The bound has to be on the number of SHAs retained, not on their
age.

The reclaim runs at the END, after `last-good-sha` is written. A deploy that dies half-way must
not take the rollback target with it, and that ordering is the only thing keeping the two apart.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "ops" / "deploy" / "sync.sh"


def script() -> str:
    return SYNC.read_text(encoding="utf-8")


def test_the_rail_reclaims_images_after_a_build() -> None:
    """Without this the disk fills at roughly 9 GB per day of active development, and the
    symptom is a git fetch failing rather than anything that names Docker."""
    assert "docker rmi" in script() or "image prune" in script()


def test_the_reclaim_runs_after_last_good_is_written() -> None:
    """Ordering is the safety property.

    `last-good-sha` is the rollback pointer. Reclaiming before it is written means a deploy that
    fails between the two has already deleted images it might need to roll back to — turning a
    failed deploy into an unrecoverable one.
    """
    text = script()
    last_good = text.index('> "$LAST_GOOD"')
    reclaim = min(
        (m.start() for m in re.finditer(r"docker rmi|image prune|builder prune", text)),
        default=-1,
    )

    assert reclaim > last_good, "the reclaim must come after the rollback pointer is written"


def test_the_deployed_sha_and_the_floating_tag_are_protected() -> None:
    """`:current` is what a manual `docker compose run` on the VM resolves to, and the script
    republishes it deliberately -- "without this a manual run silently executes whatever stale
    image last carried the tag". Reclaiming it would recreate that bug."""
    text = script()

    assert "current" in text.split('> "$LAST_GOOD"')[1], "the reclaim does not mention :current"
    assert "$TARGET" in text.split('> "$LAST_GOOD"')[1], "the reclaim does not protect the SHA"


def test_the_retention_is_a_count_of_shas_not_an_age() -> None:
    """The incident's actual lesson. Fourteen SHAs reached main in one day; every one of them
    would survive an `until=24h` filter, and their trios alone are ~40 GB of a 96 GB disk."""
    reclaim = script().split('> "$LAST_GOOD"')[1]

    assert re.search(r"KEEP_SHAS|keep_shas", reclaim), "no SHA-count retention bound"
