"""`InstrumentMaster` resolves through a cached per-day VIEW, not a fresh scan per call.

Found on arb-vm: `pips daily promote` over 6,202 range records is ~4.6 million vendor-code
resolutions, and each one filtered every record and re-validated every instrument -- days of
CPU for a panel that is one parquet file. The view is built once per `(on, known_on)` and is
invalidated by any append to the store. The ANSWERS do not change; only how often they are
computed. Duplicates on a day still raise.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from pips.data.pit import instruments as instruments_module
from pips.data.pit.instruments import AmbiguousSymbolError, Instrument, InstrumentMaster
from pips.data.pit.store import PitStore, from_payload

DAY = date(2026, 9, 3)


def instrument(symbol: str, vendor: str, isin: str, token: str) -> Instrument:
    return Instrument(
        isin=isin,
        exchange_token=token,
        symbol=symbol,
        name=symbol,
        series="EQ",
        lot_size=1,
        tick_size_paise=5,
        vendor_code=vendor,
    )


def master_with(tmp_path: Path, n: int = 50) -> InstrumentMaster:
    master = InstrumentMaster(PitStore(tmp_path / "pit"))
    for k in range(n):
        master.upsert(
            instrument(f"SYM{k:03d}", f"VC{k:03d}", f"INE{k:09d}", str(1000 + k)),
            known_from=date(2020, 1, 1),
        )
    return master


def count_constructions(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]

    def counting(cls: object, payload: object) -> object:
        calls[0] += 1
        return from_payload(cls, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(instruments_module, "from_payload", counting)
    return calls


def test_a_thousand_resolutions_on_one_day_build_the_instruments_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = master_with(tmp_path, n=50)
    calls = count_constructions(monkeypatch)
    for _ in range(1000):
        found = master.resolve_vendor_code("VC007", DAY, known_on=DAY)
        assert found is not None and found.symbol == "SYM007"
    assert calls[0] == 50  # one construction per instrument, not per call


def test_symbol_and_token_resolution_share_the_same_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = master_with(tmp_path, n=20)
    calls = count_constructions(monkeypatch)
    assert master.resolve_vendor_code("VC001", DAY, known_on=DAY) is not None
    assert master.resolve_symbol("SYM002", DAY, known_on=DAY) is not None
    assert master.resolve_token("1003", DAY, known_on=DAY) is not None
    assert calls[0] == 20


def test_a_different_day_or_knowledge_date_is_a_different_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = master_with(tmp_path, n=10)
    master.rename("INE000000001", "RENAMED", known_from=date(2026, 9, 10))
    calls = count_constructions(monkeypatch)
    # each asked twice: today that is sixty constructions, with the view it is thirty
    for _ in range(2):
        before = master.resolve_symbol("SYM001", DAY, known_on=DAY)
        after = master.resolve_symbol("RENAMED", date(2026, 9, 12), known_on=date(2026, 9, 12))
        stale_knowledge = master.resolve_symbol("SYM001", date(2026, 9, 12), known_on=DAY)
    assert before is not None and after is not None and stale_knowledge is not None
    assert before.isin == after.isin == stale_knowledge.isin
    # Three distinct (on, known_on) views -- asserted directly. Constructions are one per PIT
    # record VERSION: ten originals plus the rename, shared by every view that includes them.
    assert len(master._views) == 3
    assert calls[0] == 11


def test_an_append_invalidates_the_view(tmp_path: Path) -> None:
    master = master_with(tmp_path, n=5)
    assert master.resolve_vendor_code("VCNEW", DAY, known_on=None) is None
    master.upsert(instrument("NEWCO", "VCNEW", "INE999999999", "9999"), known_from=date(2020, 1, 1))
    found = master.resolve_vendor_code("VCNEW", DAY, known_on=None)
    assert found is not None and found.symbol == "NEWCO"


def test_another_process_appending_to_the_same_file_invalidates_the_view(tmp_path: Path) -> None:
    master = master_with(tmp_path, n=5)
    assert master.resolve_vendor_code("VCNEW", DAY, known_on=None) is None
    other = InstrumentMaster(PitStore(tmp_path / "pit"))  # a second store over one directory
    other.upsert(instrument("NEWCO", "VCNEW", "INE999999999", "9999"), known_from=date(2020, 1, 1))
    found = master.resolve_vendor_code("VCNEW", DAY, known_on=None)
    assert found is not None and found.symbol == "NEWCO"


def test_a_duplicate_vendor_code_on_a_day_still_raises_through_the_view(tmp_path: Path) -> None:
    master = master_with(tmp_path, n=3)
    master.upsert(instrument("OTHER", "VC001", "INE888888888", "8888"), known_from=date(2020, 1, 1))
    with pytest.raises(AmbiguousSymbolError, match="2 live instruments"):
        master.resolve_vendor_code("VC001", DAY, known_on=None)
    # and the cached view gives the same refusal the second time, not a memoised first match
    with pytest.raises(AmbiguousSymbolError, match="2 live instruments"):
        master.resolve_vendor_code("VC001", DAY, known_on=None)


def test_as_of_still_returns_a_fresh_list_the_caller_may_mutate(tmp_path: Path) -> None:
    master = master_with(tmp_path, n=4)
    first = master.as_of(DAY, known_on=None)
    first.clear()
    assert len(master.as_of(DAY, known_on=None)) == 4


def test_the_view_cache_is_bounded_and_eviction_does_not_change_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = master_with(tmp_path, n=3)
    monkeypatch.setattr(instruments_module, "_MAX_VIEWS", 3)
    for k in range(6):
        day = date(2026, 9, 1 + k)
        found = master.resolve_vendor_code("VC001", day, known_on=day)
        assert found is not None and found.symbol == "SYM001"
    assert len(master._views) == 3


def test_instruments_are_shared_across_views_not_rebuilt_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # arb-vm, second panel run: ~745 daily views x ~2,500 instruments, each view its own
    # pydantic objects -- gigabytes, and the run was stopped before it could OOM the plant.
    # One Instrument per PIT record, referenced by every view that includes it.
    master = master_with(tmp_path, n=10)
    calls = count_constructions(monkeypatch)
    for k in range(30):
        day = date(2026, 6, 1) + timedelta(days=k)
        assert master.resolve_vendor_code("VC003", day, known_on=day) is not None
    assert calls[0] == 10  # ten records, ten constructions, thirty views
    a = master.resolve_vendor_code("VC003", date(2026, 6, 1), known_on=date(2026, 6, 1))
    b = master.resolve_vendor_code("VC003", date(2026, 6, 30), known_on=date(2026, 6, 30))
    assert a is b  # the same object, not an equal copy


def test_a_same_day_amendment_is_not_served_from_the_old_object(tmp_path: Path) -> None:
    # An upsert and a rename on the SAME known_from share (key, valid_from, known_from). The
    # shared-object cache must be dropped when the store re-parses, or the view keeps handing
    # out the pre-rename Instrument for the post-rename record. Found by the honest sweep.
    master = master_with(tmp_path, n=3)
    assert master.resolve_symbol("SYM001", DAY, known_on=None) is not None
    master.rename("INE000000001", "RENAMED", known_from=date(2020, 1, 1))
    assert master.resolve_symbol("RENAMED", DAY, known_on=None) is not None
    assert master.resolve_symbol("SYM001", DAY, known_on=None) is None
