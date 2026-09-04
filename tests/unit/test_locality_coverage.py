"""Rule 14 guards every zone that writes market data, not two of four (`[C-DATA-01]`).

`core/locality.py` exists because *"the consequence — market data in git — is one of the few
mistakes here that cannot be fully undone"*, and it warns that the guard **fails silently when
it fails**: it allows a path by concluding the path is outside the repository, so anything that
makes the repository un-findable reads as permission.

The module put the rule in one place. What nothing checked is whether every writer uses it.
`run_backfill` guards bronze and `CaptureWriter` guards tick capture — and `promote_bronze`
wrote `silver_root/bars_1m.parquet`, and `run_qc` wrote quarantined records, with no check at
all. Two of the four zones rule 14 names.

That gap became more reachable when `pips promote` gained a `data_root` argument: before, silver
was written by whatever Python somebody wrote; now there is a command that takes the path from
the command line.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.core.locality import repo_root
from pips.data.pit.instruments import InstrumentMaster
from pips.data.pit.store import PitStore
from pips.data.qc.runner import run_qc, seed_two_sessions
from pips.data.silver import promote_bronze


def inside_the_repo(name: str) -> Path:
    """A path inside the working tree that is NOT a tracked data zone.

    The obvious choice is `data/silver` and `data/quarantine`, and my first version used them.
    That is a trap: to test "it refuses to write here" the test has to try, so on the RED run —
    before the guard exists — the test PERFORMS the thing it exists to prevent. It did, and it
    left real quarantine records in `data/quarantine` that turned `make ci` red on
    `test_repo_data_zones_hold_no_market_data`, a test with nothing to do with this one.

    `build/` is inside the repository, so the guard still fires, and is not a data zone, so a
    build without the guard leaves nothing anybody has to notice and clean up.
    """
    root = repo_root()
    assert root is not None, "these tests are meaningless outside a working tree"
    return root / "build" / "locality-probe" / name


def empty_master(tmp_path: Path) -> InstrumentMaster:
    """A real master holding nothing.

    The guard has to fire on the ROOT ALONE, before any instrument is resolved -- so a master
    that could resolve nothing is the honest fixture: if the refusal ever moved to the write
    site, these tests would fail with a quarantine report instead of a rule-14 error.
    """
    return InstrumentMaster(PitStore(tmp_path / "pit"))


def test_promotion_refuses_to_write_silver_into_the_repository(tmp_path: Path) -> None:
    """Silver is the panel. It is market data by any reading of rule 14, and it was the one
    zone with a CLI that takes its destination from an argument."""
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=date(2026, 8, 27))

    with pytest.raises(ValueError, match="rule 14"):
        promote_bronze(
            bronze,
            inside_the_repo("silver"),  # inside the working tree
            empty_master(tmp_path),
            known_on=date(2026, 9, 4),
        )


def test_qc_refuses_to_write_quarantine_into_the_repository(tmp_path: Path) -> None:
    """A quarantined record is the bronze payload plus its reasons — the same data, moved
    aside. Rule 14 names `quarantine` beside `bronze` for that reason."""
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=date(2026, 8, 27))

    with pytest.raises(ValueError, match="rule 14"):
        run_qc(bronze, inside_the_repo("quarantine"), set())


def test_the_guard_names_which_write_it_stopped(tmp_path: Path) -> None:
    """`refuse_repo_paths` takes `what` so the message says which write was stopped rather than
    leaving the reader to work it out from a traceback. A guard added without it would raise a
    message about "bronze" while refusing a silver write."""
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=date(2026, 8, 27))

    # "write silver bars", not "silver": the message is `refusing to write {what} inside ...
    # ({root})`, and the ROOT here ends in `/silver`. Matching the bare word passed even when
    # the label said "bronze" -- a mutation proved it -- because the path supplied the match.
    with pytest.raises(ValueError, match="write silver bars"):
        promote_bronze(
            bronze, inside_the_repo("silver"), empty_master(tmp_path), known_on=date(2026, 9, 4)
        )

    with pytest.raises(ValueError, match="write quarantined records"):
        run_qc(bronze, inside_the_repo("quarantine"), set())


def test_a_path_outside_the_tree_is_still_allowed(tmp_path: Path) -> None:
    """The guard must not become a refusal of everything: `tmp_path` is outside the repo and
    both writers have to work there, which is where every other test in the suite runs them."""
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=date(2026, 8, 27))

    report = run_qc(bronze, tmp_path / "quarantine", set())
    assert report.checked > 0
