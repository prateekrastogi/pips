"""PitStore read amplification  [C-DATA-01] (§6 M6).

Found by running the real ingest: loading 5,851 instruments into the store took over ten
minutes, for a file the parser reads in under a second.

`append` calls `_latest_version` to enforce the forward-only knowledge-time rule, and
`_latest_version` calls `all_records`, which re-reads and re-validates **the entire JSONL from
disk**. Appending N records therefore performs N full parses of a file growing to N lines —
O(N²) pydantic validations, about seventeen million of them for one day's instrument master.

At six bronze records this was invisible. It became the difference between a daily snapshotter
and an overnight job at the first real dataset, which is the general shape of the thing: a data
structure that is correct at fixture scale and unusable at production scale is not finished,
and nothing about its tests would ever say so.

The test below counts actual file parses rather than measuring elapsed time. A timing
assertion would be flaky on shared hardware and would not say WHAT was slow; a read count says
exactly what the defect is and cannot pass for the wrong reason.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pips.data.pit.store import PitRecord, PitStore

D = date


def record(key: str, day: int = 1) -> PitRecord:
    return PitRecord(
        table="perf",
        key=key,
        valid_from=D(2026, 1, day),
        known_from=D(2026, 1, day),
        payload={"k": key},
    )


def test_appending_many_records_does_not_reparse_the_file_each_time(tmp_path: Path) -> None:
    """The defect, stated as a bound rather than a duration.

    200 appends must not cost 200 full parses. Without a cache each append re-reads
    everything written so far, which is what turned a 5,851-row ingest into a ten-minute job.
    """
    store = PitStore(tmp_path / "pit")
    for i in range(200):
        store.append(record(f"K{i:04d}"))

    assert store.file_parses < 20, (
        f"{store.file_parses} full file parses for 200 appends — the store is re-reading "
        "everything it has written on every write"
    )


def test_the_records_are_still_all_there_and_correct(tmp_path: Path) -> None:
    # The cache must not become a way to lose data. A fast store that drops records is worse
    # than a slow one that does not.
    store = PitStore(tmp_path / "pit")
    for i in range(200):
        store.append(record(f"K{i:04d}"))

    assert len(store.all_records("perf")) == 200
    assert len(store.as_of("perf", known_on=D(2026, 1, 2))) == 200


def test_a_reopened_store_sees_everything_the_first_one_wrote(tmp_path: Path) -> None:
    first = PitStore(tmp_path / "pit")
    for i in range(50):
        first.append(record(f"K{i:04d}"))

    reopened = PitStore(tmp_path / "pit")
    assert len(reopened.all_records("perf")) == 50


def test_a_write_by_another_process_is_picked_up(tmp_path: Path) -> None:
    """The cache must not outlive its truth.

    Two stores over one directory is exactly how a backfill and a QC pass coexist. A cache
    that trusts itself after someone else has written is a store that reports stale data with
    total confidence — worse than the slowness it was added to fix.
    """
    store = PitStore(tmp_path / "pit")
    store.append(record("A"))
    assert len(store.all_records("perf")) == 1

    other = PitStore(tmp_path / "pit")
    other.append(record("B", day=2))

    assert len(store.all_records("perf")) == 2, "the first store must notice the second's write"
