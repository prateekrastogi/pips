"""`PitStore.as_of` answers in ONE pass over the records -- same answers as the per-key scan.

The method's own docstring priced itself: O(keys x records), ~0.4 s on the real master, "fine
for a daily read and not for a per-bar one ... the fix is an index by key". The daily panel
build asks it once per trading day (~745 times) and the prerank's explainer asks the corporate
actions table once per overnight pair. Semantics pinned here: both filters before choosing, last
write wins on a tie, sorted by key, CLOSE dropped.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.store import PitOp, PitRecord, PitStore

T = "things"


def rec(
    key: str, valid: date, known: date, op: PitOp = PitOp.UPSERT, **payload: object
) -> PitRecord:
    return PitRecord(
        table=T, key=key, valid_from=valid, known_from=known, payload=dict(payload), op=op
    )


@pytest.fixture
def store(tmp_path: Path) -> PitStore:
    s = PitStore(tmp_path / "pit")
    # A: two versions, the later known one valid from later
    s.append(rec("A", date(2020, 1, 1), date(2020, 1, 1), name="a0"))
    s.append(rec("A", date(2026, 10, 1), date(2026, 9, 1), name="a-future"))
    # B: same known_from twice (a same-day amendment): last write wins
    s.append(rec("B", date(2020, 1, 1), date(2020, 1, 1), name="b0"))
    s.append(rec("B", date(2020, 1, 1), date(2020, 1, 1), name="b1"))
    # C: closed
    s.append(rec("C", date(2020, 1, 1), date(2020, 1, 1), name="c0"))
    s.append(rec("C", date(2021, 1, 1), date(2021, 1, 1), PitOp.CLOSE))
    # D: known only later than the query
    s.append(rec("D", date(2020, 1, 1), date(2026, 12, 1), name="d-late-knowledge"))
    return s


def reference(store: PitStore, known_on: date, valid_on: date | None) -> list[PitRecord]:
    """The per-key scan, kept as the oracle."""
    effective = known_on if valid_on is None else valid_on
    out = []
    for key in sorted({r.key for r in store.all_records(T)}):
        v = store._latest_version(T, key, known_on=known_on, valid_on=effective)
        if v is None or v.op is PitOp.CLOSE:
            continue
        out.append(v)
    return out


@pytest.mark.parametrize(
    ("known_on", "valid_on"),
    [
        (date(2026, 9, 3), None),
        (date(2026, 9, 3), date(2026, 10, 15)),  # a-future valid but is it known? yes (2026-09-01)
        (date(2020, 6, 1), None),  # before C closed, before A's second version
        (date(2027, 1, 1), None),  # everything known; D appears
        (date(2019, 1, 1), None),  # nothing known yet
    ],
)
def test_single_pass_gives_the_per_key_scans_answer(
    store: PitStore, known_on: date, valid_on: date | None
) -> None:
    assert store.as_of(T, known_on=known_on, valid_on=valid_on) == reference(
        store, known_on, valid_on
    )


def test_a_same_day_amendment_is_won_by_the_last_write(store: PitStore) -> None:
    (b,) = [r for r in store.as_of(T, known_on=date(2026, 9, 3)) if r.key == "B"]
    assert b.payload["name"] == "b1"


def test_as_of_reads_the_records_once(store: PitStore, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = [0]
    real = store.all_records

    def counting(table: str) -> list[PitRecord]:
        calls[0] += 1
        return real(table)

    monkeypatch.setattr(store, "all_records", counting)
    store.as_of(T, known_on=date(2026, 9, 3))
    assert calls[0] == 1  # not 1 + one scan per key
