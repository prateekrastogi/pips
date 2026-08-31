"""Experiments pin snapshot_root  [C-DATA-02] (§6 M6, §3.4, constitution rule 3).

The half of `[C-DATA-02]` that the Merkle tree alone does not deliver. A root that nothing
records is a root that proves nothing.

`RunRecord` already carried `data_snapshot` — but that is a NAME. A trial recorded against
`"daily-v3"` cannot be re-derived, because "daily-v3" can be rebuilt, extended or corrected
and still answer to the same name. The name says which shelf the data was on; the root says
which bytes were on it. Rule 3 wants evidence, and a pointer that can silently change its
referent is not evidence.

So the run row pins the root, the root is verified against the store that produced it, and a
run whose root does not match what the store says for that as-of date is refused — because the
failure being guarded is not a missing snapshot, it is a snapshot that has quietly moved while
keeping its name.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.store import PitRecord, PitStore
from pips.search.registry import Registry, RunRecord, missing_run_columns

D = date
ROOT_A = "a" * 64
ROOT_B = "b" * 64


def record(**over: object) -> RunRecord:
    base: dict[str, object] = {
        "config_hash": "a" * 64,
        "stage": "S1",
        "stage_rank": 1,
        "data_snapshot": "nifty100-1m-2026H1",
        "snapshot_root": ROOT_A,
        "cost_model": "c" * 64,
        "fill_tier": "F1",
        "seed": 7,
        "git_sha": "d" * 40,
        "metrics": {"rank_ic": 0.03},
        "status": "completed",
    }
    base.update(over)
    return RunRecord.model_validate(base)


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.db")


@pytest.fixture
def store(tmp_path: Path) -> PitStore:
    store = PitStore(tmp_path / "pit")
    for key, symbol in (("1", "RELIANCE"), ("2", "INFY")):
        store.append(
            PitRecord(
                table="instruments",
                key=key,
                valid_from=D(2026, 1, 1),
                known_from=D(2026, 6, 1),
                payload={"symbol": symbol},
            )
        )
    return store


# ------------------------------------------------------------ the pin ------------------


def test_a_run_pins_its_snapshot_root(reg: Registry) -> None:
    run_id = reg.record(record())
    stored = reg.get(run_id)
    assert stored is not None
    assert stored.snapshot_root == ROOT_A


def test_a_run_without_a_snapshot_root_is_refused() -> None:
    with pytest.raises(ValueError, match="snapshot_root"):
        RunRecord.model_validate(
            {k: v for k, v in record().model_dump().items() if k != "snapshot_root"}
        )


def test_a_snapshot_root_that_is_not_a_root_is_refused() -> None:
    # A truncated hash, an uppercase one, a short-id: each is a plausible paste, and each
    # would record something that looks like provenance and cannot be checked against a store.
    for bad in ("", "not-a-hash", "ABCD" * 16, "a" * 63, "a" * 16, "g" * 64):
        with pytest.raises(ValueError, match="64"):
            record(snapshot_root=bad)


def test_the_name_and_the_root_are_kept_apart(reg: Registry) -> None:
    """Two runs on the same NAMED snapshot whose bytes differ are distinguishable.

    This is the whole point of adding the column: before it, these two rows were identical in
    every provenance field, and the second would have inherited the first's credibility.
    """
    reg.record(record(snapshot_root=ROOT_A))
    reg.record(record(snapshot_root=ROOT_B))
    rows = reg.all_runs()
    assert {r["data_snapshot"] for r in rows} == {"nifty100-1m-2026H1"}
    assert {r["snapshot_root"] for r in rows} == {ROOT_A, ROOT_B}


# ------------------------------------------------- the pin is checked, not trusted -----


def test_a_root_matching_the_store_verifies(store: PitStore) -> None:
    root = store.snapshot_root("instruments", known_on=D(2026, 6, 30))
    assert store.verify_pinned_root("instruments", known_on=D(2026, 6, 30), pinned=root)


def test_a_root_that_no_longer_matches_the_store_is_caught(store: PitStore) -> None:
    """The failure this exists for: the snapshot moved while keeping its name.

    A run pinned a root in June. In July someone re-ingests and the master gains a name. The
    NAME is unchanged, so nothing in `data_snapshot` moves — only the root does, and only
    because the root is over bytes.
    """
    pinned = store.snapshot_root("instruments", known_on=D(2026, 6, 30))
    store.append(
        PitRecord(
            table="instruments",
            key="3",
            valid_from=D(2026, 1, 1),
            known_from=D(2026, 6, 2),  # backfilled INTO the already-pinned window
            payload={"symbol": "TCS"},
        )
    )
    assert not store.verify_pinned_root("instruments", known_on=D(2026, 6, 30), pinned=pinned)


def test_a_later_snapshot_does_not_invalidate_an_earlier_pin(store: PitStore) -> None:
    # The complement, and the reason the check is worth having rather than merely alarming:
    # ordinary forward progress must NOT trip it, or it will be switched off.
    pinned = store.snapshot_root("instruments", known_on=D(2026, 6, 30))
    store.append(
        PitRecord(
            table="instruments",
            key="3",
            valid_from=D(2026, 7, 1),
            known_from=D(2026, 7, 1),
            payload={"symbol": "TCS"},
        )
    )
    assert store.verify_pinned_root("instruments", known_on=D(2026, 6, 30), pinned=pinned)


# --------------------------------------------------- schema/model drift ----------------


def test_the_runs_table_has_a_column_for_every_recorded_field(reg: Registry) -> None:
    """The DDL and the model are two hand-maintained lists of the same thing.

    They drifted the moment `snapshot_root` was added to one of them, and the symptom would
    have been `sqlite3.OperationalError: no such column` from deep inside an INSERT. Naming the
    drift directly is worth more than the traceback.
    """
    assert missing_run_columns(reg.connection) == []


def test_drift_is_reported_by_name(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "stale.db")
    connection.execute("CREATE TABLE runs (config_hash TEXT, stage TEXT)")
    assert "snapshot_root" in missing_run_columns(connection)
    assert "seed" in missing_run_columns(connection)


def test_a_registry_opened_on_a_stale_schema_refuses(tmp_path: Path) -> None:
    # Fail at OPEN, not at the first insert. A registry that accepts the connection and
    # rejects the write loses whatever the caller was midway through recording — and rule 4
    # says a trial that was viewed must be counted, so losing the write loses evidence.
    path = tmp_path / "stale.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE runs (config_hash TEXT, stage TEXT)")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match="snapshot_root"):
        Registry(path)
