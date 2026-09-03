"""S1 can search real promoted bars, not only generated fixtures (§6 M12, `[C-SILVER-01]`).

S5 has read silver since `run_family_searches` gained a `silver` argument. S1 — the FIRST stage
of the funnel — could not: `run_s1_search` calls `load_panel(fixtures)` and nothing else, so the
one loader built for this (`load_silver_panel`, which carries the lockbox check) was unreachable
from the stage that runs first.

The property that matters is not "it reads the file". It is what the trial ledger says
afterwards. `run_s1_search` recorded `snapshot_root=fixture_snapshot_root(fixtures)`
unconditionally, so a run over real bars would have written a fixture root onto every trial —
`[C-DATA-02]`'s pin pointing at data the run never touched, and rule 4's ledger describing the
wrong experiment. Reproducing it would silently reproduce something else.
"""

from __future__ import annotations

import contextlib
import io
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from pips.search.registry import Registry
from pips.search.s1 import run_s1_search, search_main
from pips.search.trials import file_snapshot_root, fixture_snapshot_root

MINUTE = 60 * 1_000_000_000
OPEN = 1787715960 * 1_000_000_000  # 2026-08-26 09:16 IST
FIXTURES = Path("fixtures")


def silver_file(tmp_path: Path, rows: int = 400, drift: int = 0) -> Path:
    """Enough bars for the halving budget, two symbols, deliberately unsorted on disk.

    ``drift`` changes the PRICES, not just the row count. Two files differing only in length
    produce identical searches, because the halving budget is fixed and both runs read the same
    leading stamps with the same closes -- a fixture too tidy to show that the panel is being
    read at all, which is what my first version of this was.
    """
    frame = pl.DataFrame(
        [
            {
                "close_ts_ns": OPEN + i * MINUTE,
                "symbol": s,
                "isin": f"INE{s[:3]}01011",
                "open_paise": 130000 + i + j,
                "high_paise": 130100 + i + j,
                "low_paise": 129900 + i + j,
                "close_paise": 130050 + i + (j * 7) + (drift * (i % 11)),
                "volume": 1000 + i,
                "received_at_ns": OPEN,
            }
            for i in range(rows)
            for j, s in enumerate(("ICICIBANK", "RELIANCE"))
        ]
    )
    path = tmp_path / "bars_1m.parquet"
    frame.reverse().write_parquet(path)
    return path


def run(tmp_path: Path, *, silver: Path | None) -> dict[str, object]:
    return run_s1_search(
        fixtures=FIXTURES,
        registry=Registry(tmp_path / "r.db"),
        returns_dir=tmp_path / "returns",
        silver=silver,
    )


def test_a_silver_run_pins_the_file_it_read_not_the_fixtures(tmp_path: Path) -> None:
    """The defect this unit exists for.

    An unconditional `fixture_snapshot_root` would stamp every trial of a real-bar run with the
    root of data it never touched. `[C-DATA-02]`'s pin would point at the wrong bytes, rule 4's
    ledger would describe the wrong experiment, and re-running from the record would reproduce
    something else while looking exact.
    """
    silver = silver_file(tmp_path)
    report = run(tmp_path, silver=silver)

    assert report["snapshot_root"] == file_snapshot_root(silver)
    assert report["snapshot_root"] != fixture_snapshot_root(FIXTURES)


def test_a_fixture_run_still_pins_the_fixtures(tmp_path: Path) -> None:
    """The other half, or the first test passes by pinning nothing correctly."""
    report = run(tmp_path, silver=None)

    assert report["snapshot_root"] == fixture_snapshot_root(FIXTURES)


def test_the_search_actually_reads_the_silver_bars(tmp_path: Path) -> None:
    """Two different files must give two different searches, or `silver` is decoration.

    The panel decides every score, so a run that loaded fixtures while claiming silver would
    still produce a plausible report — which is why this compares two silver files against each
    other rather than checking that a report came back.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    one = run(tmp_path / "a", silver=silver_file(tmp_path / "a"))
    two = run(tmp_path / "b", silver=silver_file(tmp_path / "b", drift=37))

    assert one["snapshot_root"] != two["snapshot_root"]
    assert one["winner_score"] != two["winner_score"], "different bars, different search"


def test_the_sealed_lockbox_closes_the_silver_door_too(tmp_path: Path) -> None:
    """A second reader is a second door into the holdout.

    `load_silver_panel` consults the lockbox because the read is the only place the seal can
    bite. Wiring S1 to it must not route around that check -- a new entry point that skipped it
    would reopen exactly the hole the lockbox exists to close, while looking like plumbing.
    """
    from pips.data.lockbox import LockboxSealedError, SealedLockbox

    sealed = SealedLockbox(
        start=date(2026, 8, 1), end=date(2026, 9, 1), release_stage="S6", cycle_id="c1"
    )

    with pytest.raises(LockboxSealedError):
        run_s1_search(
            fixtures=FIXTURES,
            registry=Registry(tmp_path / "r.db"),
            returns_dir=tmp_path / "returns",
            silver=silver_file(tmp_path),
            lockbox=sealed,
            stage="S1",
        )


def test_the_report_does_not_call_real_bars_a_synthetic_random_walk(tmp_path: Path) -> None:
    """`search_main` prints "the fixtures are two synthetic symbols from a seeded random walk".

    That is true of a fixture run and FALSE of a silver run, and printing it anyway would put a
    false statement about the data beside the result -- the same class of error as a snapshot
    root pointing at the wrong bytes, except this one is aimed at a person rather than a
    ledger, and a person is likelier to act on it.
    """
    silver = silver_file(tmp_path)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        search_main([str(FIXTURES), str(tmp_path / "r.db"), str(tmp_path / "returns"), str(silver)])
    printed = out.getvalue()

    # The CLAIM, not the words. Forbidding "random walk" outright was too blunt: the silver
    # message legitimately says these bars are NOT one, and a test that cannot tell an
    # assertion from its negation would have forced the message to be vaguer to pass.
    assert "The fixtures are two synthetic symbols" not in printed
    assert str(silver.name) in printed, "it says which bars it actually read"


def test_a_fixture_run_still_says_what_it_is(tmp_path: Path) -> None:
    """The disclaimer earns its place on the run it describes: a search over noise returns a
    flattering winner every time, and the report has to say so."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        search_main([str(FIXTURES), str(tmp_path / "r.db"), str(tmp_path / "returns")])

    assert "The fixtures are two synthetic symbols" in out.getvalue()


def recorded_rows(tmp_path: Path, *, silver: Path | None) -> list[dict[str, object]]:
    registry = Registry(tmp_path / "r.db")
    run_s1_search(
        fixtures=FIXTURES, registry=registry, returns_dir=tmp_path / "returns", silver=silver
    )
    return [dict(row) for row in registry.all_runs()]


def test_the_ledger_records_which_universe_the_trials_actually_ran_on(tmp_path: Path) -> None:
    """`universe_id` and `data_snapshot` travel into every recorded trial, and both were
    hardcoded to the fixtures.

    Rule 4 counts every look, and the count is only meaningful if the rows say what was looked
    AT. A ledger of real-bar trials labelled `FIXTURES` is not a slightly-wrong label: it makes
    the deflation bracket describe a different experiment, and it merges two populations of
    trials that must never be pooled.

    Asserted against the REGISTRY rather than the returned report, because the ledger is where
    the claim persists and where anything downstream will read it.
    """
    silver = silver_file(tmp_path)
    rows = recorded_rows(tmp_path, silver=silver)

    assert rows, "the search recorded nothing, so this asserts nothing"
    assert {r["universe_id"] for r in rows} == {"SILVER"}
    assert {r["data_snapshot"] for r in rows} == {f"silver@{silver.name}"}


def test_a_fixture_run_is_recorded_as_a_fixture_run(tmp_path: Path) -> None:
    """The other half. Without it the test above passes on a build that labels everything
    SILVER, which is the same defect pointing the other way."""
    rows = recorded_rows(tmp_path, silver=None)

    assert {r["universe_id"] for r in rows} == {"FIXTURES"}
    assert {r["data_snapshot"] for r in rows} == {f"fixtures@{FIXTURES.name}"}


def test_the_sealed_lockbox_closes_the_fixture_door_too(tmp_path: Path) -> None:
    """I tested the new door and not the old one.

    `run_s1_search` now forwards `lockbox`/`stage` to both loaders, and a mutation dropping
    them from the FIXTURES branch survived — because every lockbox test here went through
    silver. The holdout would have stayed readable by the path that has always existed, which
    is the one every current caller uses.
    """
    from pips.data.lockbox import LockboxSealedError, SealedLockbox

    sealed = SealedLockbox(
        start=date(2020, 1, 1), end=date(2030, 1, 1), release_stage="S6", cycle_id="c1"
    )

    with pytest.raises(LockboxSealedError):
        run_s1_search(
            fixtures=FIXTURES,
            registry=Registry(tmp_path / "r.db"),
            returns_dir=tmp_path / "returns",
            lockbox=sealed,
            stage="S1",
        )
