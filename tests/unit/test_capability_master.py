"""Broker-capability daily snapshotter on the PIT store  [C-DATA-01] (§6 M6, §3.4).

M3 shipped a v0: a manually maintained CSV with one `snapshot_date` per row. `capability.py`
said at the time that M6 would replace the ingest and keep the read shape — *ask as of a date,
get what was knowable then*. This is that replacement.

**What the v0 cannot say.** One date per row conflates two facts: when we learned a capability
and when it took effect. A broker announcing on 20 August that its square-off moves to 15:10
from 1 September is knowledge on the 20th and force on the 1st, and a single column has to pick
one. Picking the announcement date makes the system square off early for eleven days it should
not have; picking the effective date makes it act on information it did not have. Both are
wrong, and one of them is silently, profitably wrong.

Square-off time is not decoration here. It is what `ExchangeCalendar.session_at` uses to decide
whether an intraday position must be flat, so an error in it is an error in every position's
final minutes.

**The migration must not change any answer.** A capability table that quietly answers
differently after a refactor is worse than one that fails, so the equivalence test below asks
the v0 loader and the new master the same question for every row in the shipped CSV.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from pips.data.pit.capability import CapabilityRow, load_capability_csv
from pips.data.pit.capability_master import CapabilityMaster, migrate_v0_csv
from pips.data.pit.store import PitStore

D = date
CSV = Path("config/brokers/flattrade_capability_v0.csv")


@pytest.fixture
def master(tmp_path: Path) -> CapabilityMaster:
    return CapabilityMaster(PitStore(tmp_path / "pit"))


def row(**over: object) -> CapabilityRow:
    base: dict[str, object] = {
        "snapshot_date": D(2026, 1, 1),
        "broker": "FLATTRADE",
        "product": "MIS",
        "instrument_id": "*",
        "side": "BOTH",
        "eligible": True,
        "shortable": True,
        "max_leverage": Decimal(1),
        "square_off_time": time(15, 0),
        "square_off_verified": False,
        "order_types": ["LIMIT"],
        "rate_limit_per_second": 5,
        "rate_limit_per_minute": 200,
        "source": "test",
        "verified_on": D(2026, 1, 1),
    }
    base.update(over)
    return CapabilityRow.model_validate(base)


# ------------------------------------------------- the two clocks the v0 lacked --------


def test_a_change_announced_early_does_not_apply_before_it_takes_effect(
    master: CapabilityMaster,
) -> None:
    """The whole reason for the upgrade.

    Announced 20 August, effective 1 September. Between those dates the OLD cutoff is still
    the one in force — and squaring off at 15:10 for eleven days on the strength of an
    announcement is acting on a rule that did not yet exist.
    """
    master.snapshot(row(square_off_time=time(15, 0)), known_from=D(2026, 1, 1))
    master.snapshot(
        row(square_off_time=time(15, 10)), known_from=D(2026, 8, 20), valid_from=D(2026, 9, 1)
    )

    assert master.resolve(D(2026, 8, 25)).square_off_time == time(15, 0)
    assert master.resolve(D(2026, 9, 2)).square_off_time == time(15, 10)


def test_a_change_is_invisible_before_it_is_announced(master: CapabilityMaster) -> None:
    # The other clock. A backtest run on 1 August could not have known about the 20 August
    # announcement, whatever its effective date.
    master.snapshot(row(square_off_time=time(15, 0)), known_from=D(2026, 1, 1))
    master.snapshot(
        row(square_off_time=time(15, 10)), known_from=D(2026, 8, 20), valid_from=D(2026, 9, 1)
    )
    assert master.resolve(D(2026, 9, 2), known_on=D(2026, 8, 1)).square_off_time == time(15, 0)


def test_a_later_snapshot_cannot_change_what_an_earlier_date_saw(
    master: CapabilityMaster,
) -> None:
    master.snapshot(row(square_off_time=time(15, 0)), known_from=D(2026, 1, 1))
    before = master.resolve(D(2026, 6, 1)).square_off_time
    master.snapshot(row(square_off_time=time(14, 30)), known_from=D(2026, 7, 1))
    assert master.resolve(D(2026, 6, 1)).square_off_time == before


# ------------------------------------------------- preserved from the v0 ---------------


def test_a_date_with_no_snapshot_raises_rather_than_defaulting(
    master: CapabilityMaster,
) -> None:
    # Inventing capability for a date we have no data for is the survivorship-flavoured error
    # §3.4 exists to prevent — and here it would invent permission to trade.
    master.snapshot(row(), known_from=D(2026, 6, 1))
    with pytest.raises(LookupError, match="no capability"):
        master.resolve(D(2026, 1, 1))


def test_a_named_instrument_beats_a_wildcard(master: CapabilityMaster) -> None:
    master.snapshot(row(instrument_id="*", shortable=True), known_from=D(2026, 1, 1))
    master.snapshot(row(instrument_id="RELIND", shortable=False), known_from=D(2026, 1, 1))
    assert master.resolve(D(2026, 6, 1), instrument_id="RELIND").shortable is False
    assert master.resolve(D(2026, 6, 1), instrument_id="INFY").shortable is True


def test_an_exact_side_beats_both(master: CapabilityMaster) -> None:
    master.snapshot(row(side="BOTH", eligible=True), known_from=D(2026, 1, 1))
    master.snapshot(row(side="SELL", eligible=False), known_from=D(2026, 1, 1))
    assert master.resolve(D(2026, 6, 1), side="SELL").eligible is False
    assert master.resolve(D(2026, 6, 1), side="BUY").eligible is True


# ------------------------------------------------- the migration ------------------------


def test_the_migration_answers_every_v0_question_identically(tmp_path: Path) -> None:
    """A refactor that quietly changes an answer is worse than one that fails.

    Every row in the shipped CSV is asked of both implementations, on its own snapshot date
    and on a date well after it. Any divergence is a silent data change in the table that
    decides when positions must be flat.
    """
    v0 = load_capability_csv(CSV)
    master = CapabilityMaster(PitStore(tmp_path / "pit"))
    migrate_v0_csv(CSV, master)

    checked = 0
    for source in v0.rows:
        for as_of in (source.snapshot_date, D(2026, 12, 31)):
            expected = v0.resolve(
                as_of,
                broker=source.broker,
                product=source.product,
                instrument_id=source.instrument_id,
                side=source.side,
            )
            got = master.resolve(
                as_of,
                broker=source.broker,
                product=source.product,
                instrument_id=source.instrument_id,
                side=source.side,
            )
            assert got.model_dump() == expected.model_dump(), (
                f"{source.broker}/{source.product}/{source.instrument_id}/{source.side} "
                f"as of {as_of}: migration changed the answer"
            )
            checked += 1
    assert v0.rows, "the CSV must actually carry rows, or this test compares nothing"
    assert checked == len(v0.rows) * 2


def test_the_migrated_master_is_snapshot_rooted(tmp_path: Path) -> None:
    # [C-DATA-02]: the table a run consulted must be pinnable, like every other master.
    master = CapabilityMaster(PitStore(tmp_path / "pit"))
    migrate_v0_csv(CSV, master)
    root = master.snapshot_root(D(2026, 12, 31))
    assert len(root) == 64
    master.snapshot(row(square_off_time=time(14, 0)), known_from=D(2027, 1, 5))
    assert master.snapshot_root(D(2026, 12, 31)) == root
