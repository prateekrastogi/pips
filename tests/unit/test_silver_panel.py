"""Reading silver as a panel  (§6 M6/M12).

2,216 real bars sit in `/srv/pips/silver` — ICICIBANK and RELIANCE over three trading days — and
the search still runs on generated fixtures. This is the loader that lets a search read them.

**A second reader is a second door into the holdout.** `load_panel` consults the sealed lockbox
because that is the only place it can bite; a loader that skipped the check would reopen exactly
the hole the lockbox exists to close, and it would look like a convenience. The check is shared,
not re-implemented, and the tests below hold both doors to the same rule.

**The columns the search needs are named, not assumed.** A silver file missing `close_paise` is
not a panel with one fewer column — it is a panel every alpha reads zero prices from.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from pips.data.lockbox import LockboxSealedError, SealedLockbox
from pips.search.silver_panel import REQUIRED_COLUMNS, load_silver_panel

MINUTE = 60 * 1_000_000_000
# 2026-08-26 09:16 IST, the first close-labelled bar of the real silver file.
#
# Was 1787967960, which is 2026-08-29 07:16 IST -- a SATURDAY, outside any session. The comment
# said one date and the constant meant another, and nothing noticed because every test here
# either ignores the date or uses a window wide enough to contain both. A fixture that does not
# mean what it says is one nobody can reason about when a test finally depends on it.
OPEN = 1787715960 * 1_000_000_000


def silver(
    tmp_path: Path, rows: int = 40, symbols: tuple[str, ...] = ("ICICIBANK", "RELIANCE")
) -> Path:
    frame = pl.DataFrame(
        [
            {
                "close_ts_ns": OPEN + i * MINUTE,
                "symbol": s,
                "isin": f"INE{s[:3]}01011",
                "open_paise": 130000 + i,
                "high_paise": 130100 + i,
                "low_paise": 129900 + i,
                "close_paise": 130050 + i,
                "volume": 1000 + i,
                "received_at_ns": OPEN,
            }
            for i in range(rows)
            for s in symbols
        ]
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "bars_1m.parquet"
    # Written REVERSED on purpose. Built in natural order the file is already sorted, so the
    # loader's sort has nothing to do and a test over it cannot tell whether the sort happened.
    frame.reverse().write_parquet(path)
    return path


def test_the_panel_carries_the_columns_the_search_reads(tmp_path: Path) -> None:
    panel = load_silver_panel(silver(tmp_path))
    assert set(panel.columns) >= REQUIRED_COLUMNS


def test_rows_are_ordered_by_time_then_symbol(tmp_path: Path) -> None:
    # An as-of view over an unordered panel is an as-of view over whatever the file happened to
    # hold, and the search's determinism (rule 1) rests on this.
    panel = load_silver_panel(silver(tmp_path))
    keys = list(zip(panel["close_ts_ns"].to_list(), panel["symbol"].to_list(), strict=True))
    assert keys == sorted(keys)


def test_a_missing_price_column_is_refused_by_name(tmp_path: Path) -> None:
    """Not "one fewer column" — a panel every alpha reads zero prices from.

    The refusal names what is absent, because a KeyError three modules deep inside an alpha's
    compute says only that something went wrong somewhere.
    """
    path = silver(tmp_path)
    pl.read_parquet(path).drop("close_paise").write_parquet(path)
    with pytest.raises(ValueError, match="close_paise"):
        load_silver_panel(path)


def test_an_empty_silver_file_is_refused(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "bars_1m.parquet"
    pl.DataFrame({c: [] for c in sorted(REQUIRED_COLUMNS)}).write_parquet(path)
    with pytest.raises(ValueError, match="no bars"):
        load_silver_panel(path)


def test_a_missing_file_names_the_promotion_that_would_make_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="promote_bronze"):
        load_silver_panel(tmp_path / "absent.parquet")


# ------------------------------------------------------------ the same holdout --------


def test_the_lockbox_is_consulted(tmp_path: Path) -> None:
    """A second reader must not be a second door.

    `load_panel` checks the lockbox because the read is the only place it can bite. A loader
    that skipped it would reopen the hole the lockbox exists to close, and would look like a
    convenience while doing it.
    """
    sealed = SealedLockbox(
        start=date(2026, 8, 1), end=date(2026, 9, 1), release_stage="S6", cycle_id="c1"
    )
    with pytest.raises(LockboxSealedError):
        load_silver_panel(silver(tmp_path), lockbox=sealed, stage="S1")


def test_a_lockbox_without_a_stage_is_refused(tmp_path: Path) -> None:
    # Same rule as the fixture loader: a read of unknown provenance cannot be authorised, and
    # defaulting the stage would authorise it.
    sealed = SealedLockbox(
        start=date(2026, 8, 1), end=date(2026, 9, 1), release_stage="S6", cycle_id="c1"
    )
    with pytest.raises(ValueError, match="stage"):
        load_silver_panel(silver(tmp_path), lockbox=sealed)


def test_a_released_stage_may_read_the_same_bars(tmp_path: Path) -> None:
    sealed = SealedLockbox(
        start=date(2026, 8, 1), end=date(2026, 9, 1), release_stage="S6", cycle_id="c1"
    )
    panel = load_silver_panel(silver(tmp_path), lockbox=sealed, stage="S6")
    assert panel.height > 0


def test_both_loaders_share_one_lockbox_check() -> None:
    """Not two copies of the rule.

    Two implementations of one holdout is two places for it to drift, and only one of them would
    be the one under test.
    """
    import inspect

    from pips.search import s1, silver_panel

    assert "_check_lockbox" in inspect.getsource(s1.load_panel)
    assert "_check_lockbox" in inspect.getsource(silver_panel.load_silver_panel)


# ------------------------------------------------------------ the search reads it -----


def test_a_family_search_can_run_on_silver(tmp_path: Path) -> None:
    """The loader has a caller. A reader nothing calls is the pattern this session keeps finding.

    Small on purpose: what is checked is that the search reads promoted bars at all and pins
    what it read, not what it selects — two names over a handful of bars select noise.
    """
    from pips.search.families import run_family_searches
    from pips.search.registry import Registry

    parquet = silver(tmp_path, rows=500)
    report = run_family_searches(
        fixtures=Path("fixtures"),
        registry=Registry(tmp_path / "r.db"),
        returns_dir=tmp_path / "ret",
        grid_points=2,
        initial_budget=120,
        returns_bars=300,
        silver=parquet,
    )
    assert int(str(report["trials_viewed"])) > 0


def test_a_silver_run_pins_the_file_it_read(tmp_path: Path) -> None:
    """[C-DATA-02] does not care which shape the data arrived in.

    A run on real bars that recorded no snapshot root would be the one run nobody could
    reproduce — and it would look exactly like a fixture run, which records one.
    """
    from pips.search.families import run_family_searches
    from pips.search.registry import Registry
    from pips.search.trials import file_snapshot_root

    parquet = silver(tmp_path, rows=500)
    registry = Registry(tmp_path / "r.db")
    run_family_searches(
        fixtures=Path("fixtures"),
        registry=registry,
        returns_dir=tmp_path / "ret",
        grid_points=2,
        initial_budget=120,
        returns_bars=300,
        silver=parquet,
    )
    rows = registry.all_runs()
    assert rows
    assert {r["snapshot_root"] for r in rows} == {file_snapshot_root(parquet)}
    assert all(str(r["data_snapshot"]).startswith("silver@") for r in rows)


def test_changing_the_silver_file_changes_the_pin(tmp_path: Path) -> None:
    from pips.search.trials import file_snapshot_root

    first = file_snapshot_root(silver(tmp_path / "a", rows=10))
    second = file_snapshot_root(silver(tmp_path / "b", rows=11))
    assert first != second


# --------------------------------------------------------- found by mutation sweep ---


def test_a_panel_spanning_days_is_checked_from_its_earliest_bar(tmp_path: Path) -> None:
    """The range is [first, last+1), and `first` is the one the existing fixture could not test.

    Every panel in this file spans forty minutes of one morning, so `min(stamps)` and
    `max(stamps)` fall on the same date and taking either gives the same answer. A real panel
    spans months. Checking from the LAST bar means a holdout sitting at the START of the panel
    is never seen: the read is authorised, the sealed window is read, and the one place the
    lockbox can bite did not.
    """
    day_two = OPEN + 24 * 60 * MINUTE
    frame = pl.read_parquet(silver(tmp_path))
    later = frame.with_columns(pl.col("close_ts_ns") + (day_two - OPEN))
    path = tmp_path / "two_days.parquet"
    pl.concat([frame, later]).write_parquet(path)

    # sealed over the FIRST day only
    # sealed over the FIRST day only, so only a check that starts there can see it
    sealed = SealedLockbox(
        start=date(2026, 8, 26), end=date(2026, 8, 27), release_stage="S6", cycle_id="c1"
    )
    with pytest.raises(LockboxSealedError):
        load_silver_panel(path, lockbox=sealed, stage="S1")


def test_the_lockbox_dates_do_not_depend_on_the_machines_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bars are stamped in IST because the exchange is, not because the machine might be.

    `datetime.fromtimestamp(ns)` without a zone uses the MACHINE's, and 09:15 IST is 23:45 the
    previous day in New York — so the same panel would be checked against different dates
    depending on where the process runs, and a sealed window could be read from one continent
    and refused from another. On this laptop the two agree because the laptop is in IST, which
    is exactly why the mutation survived; the second time this session that an environment
    stood in for a property.
    """
    # ONE day wide, and it has to be. A month-wide window contains both the IST date and the
    # date a New York clock would produce, so it raises either way and cannot tell them apart --
    # which is how the first version of this test passed under the mutation it was written for.
    sealed = SealedLockbox(
        start=date(2026, 8, 26), end=date(2026, 8, 27), release_stage="S6", cycle_id="c1"
    )
    panel = silver(tmp_path)

    # Los Angeles, not New York. The panel runs 09:16-09:56 IST, which in New York straddles
    # midnight -- the earliest bar lands on the 25th and the latest on the 26th, so the range
    # still touches the sealed day and raises whatever the zone. Seven hours further west puts
    # the whole window on the 25th, which is the only arrangement that can tell the two apart.
    for zone in ("Asia/Kolkata", "America/Los_Angeles", "UTC"):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
        with pytest.raises(LockboxSealedError):
            load_silver_panel(panel, lockbox=sealed, stage="S1")

    monkeypatch.delenv("TZ", raising=False)
    time.tzset()
