"""QC's verdicts survive the process that reached them (§6 M5, `[C-QC-02]`).

`promote_bronze` consults `QcVerdicts` — but `QcReport.verdicts()` was in-memory only, so
`make qc` reached a verdict and threw it away. A promotion running in any other process (which
is every real one: QC is a separate entry point) had nothing to read, and `qc=None` is the only
thing it could pass. The gate existed and could not be reached.

The failure this guards is not a missing file. It is a **wrong** one. A verdict set written over
a different archive would mark records "examined" whose keys happen to collide — and keys are
`SYMBOL:YYYY-MM-DD`, which collide constantly between two archives of the same market. So the
file names the bronze root it was written over, and a mismatch is refused rather than trusted.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data.qc.checks import QcVerdicts, VerdictProvenanceError
from pips.data.qc.runner import run_qc, seed_two_sessions

ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "config" / "calendars" / "nse_equity.yaml"
SYMBOL = "CLEAN"
FIRST, SECOND = date(2026, 8, 27), date(2026, 8, 28)
KEYS = {f"{SYMBOL}:{FIRST.isoformat()}", f"{SYMBOL}:{SECOND.isoformat()}"}


def qc_over(tmp_path: Path, keys: set[str]) -> tuple[Path, Path]:
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)
    report = run_qc(bronze, tmp_path / "q", keys, calendar_path=CALENDAR)
    path = tmp_path / "state" / "qc-verdicts.json"
    report.write_verdicts(path, bronze_root=bronze)
    return bronze, path


def test_the_verdicts_survive_the_process_that_reached_them(tmp_path: Path) -> None:
    """The round trip, which is the whole point: QC runs, promotion runs later, elsewhere."""
    bronze, path = qc_over(tmp_path, KEYS)

    loaded = QcVerdicts.load(path, bronze_root=bronze)

    assert set(loaded.examined) == KEYS
    assert loaded.verdict_for(f"{SYMBOL}:{FIRST.isoformat()}") == "PASSED"


def test_a_quarantine_verdict_survives_too(tmp_path: Path) -> None:
    """Both halves, or the file would be a list of passes and every rejection would be lost as
    an absence — which promotion reads as `UNEXAMINED`, the weaker of the two verdicts."""
    bronze, path = qc_over(tmp_path, {f"{SYMBOL}:{FIRST.isoformat()}"})

    loaded = QcVerdicts.load(path, bronze_root=bronze)

    assert loaded.verdict_for(f"{SYMBOL}:{SECOND.isoformat()}") == "QUARANTINED"


def test_verdicts_written_over_another_archive_are_refused(tmp_path: Path) -> None:
    """The failure worth guarding, and it is not a missing file.

    Keys are `SYMBOL:YYYY-MM-DD`, which collide constantly between two archives of the same
    market — a verdict set from the staging archive would mark production's records examined
    and passed, and nothing downstream could tell. So the file names what it was written over.
    """
    _bronze, path = qc_over(tmp_path, KEYS)
    elsewhere = tmp_path / "other-bronze"
    elsewhere.mkdir()

    with pytest.raises(VerdictProvenanceError, match="other-bronze"):
        QcVerdicts.load(path, bronze_root=elsewhere)


def test_records_added_after_qc_ran_are_unexamined_not_passed(tmp_path: Path) -> None:
    """Staleness has to degrade in the safe direction.

    A verdict file is a statement about the records QC saw. Bronze grows; the file does not. A
    record added afterwards is absent from `examined`, so it reads as UNEXAMINED and promotion
    counts it — which is exactly right, and is why the file lists what it examined rather than
    only what it rejected.
    """
    bronze, path = qc_over(tmp_path, KEYS)
    seed_two_sessions(
        bronze, 10_000, 10_000, first_day=date(2026, 8, 31), second_day=date(2026, 8, 31)
    )

    loaded = QcVerdicts.load(path, bronze_root=bronze)

    assert loaded.verdict_for(f"{SYMBOL}:2026-08-31") == "UNEXAMINED"


def test_the_file_says_when_it_was_written(tmp_path: Path) -> None:
    """A verdict file with no age is one nobody can judge. Six months stale and six minutes
    stale are the same JSON otherwise, and only one of them should be trusted."""
    bronze, path = qc_over(tmp_path, KEYS)
    written = json.loads(path.read_text())

    assert isinstance(written["written_at_ns"], int)
    assert written["written_at_ns"] > 0
    assert written["bronze_root"] == str(bronze.resolve())


def test_a_missing_verdict_file_is_an_error_not_an_empty_pass(tmp_path: Path) -> None:
    """Asking for a specific file and getting silence back is the defect this whole seam is
    about. A caller with no QC passes `qc=None` deliberately; a caller naming a file that is
    not there has a broken pipeline, and must hear about it."""
    with pytest.raises(OSError):
        QcVerdicts.load(tmp_path / "nope.json", bronze_root=tmp_path)


def test_the_write_goes_through_the_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-written verdict file that parsed would be a smaller examined set — and a smaller
    examined set is a quieter one.

    The property is crash-safety, which cannot be observed without a crash, so this pins the
    MECHANISM that provides it. Implementation-coupled on purpose: my first version asserted
    only that no temp file was left behind and that the content changed, both of which a plain
    `write_text` satisfies. It could not tell the property from its absence, which a mutation
    to `path.write_text` proved by surviving it.
    """
    from pips.core.atomic import atomic_write_text

    used: list[Path] = []

    def spy(path: Path, text: str) -> None:
        used.append(path)
        atomic_write_text(path, text)

    # Patched by dotted name rather than by attribute: `runner` re-imports the helper without
    # re-exporting it, and `mypy --strict` is right that reaching through the module is not a
    # supported way to name it.
    monkeypatch.setattr("pips.data.qc.runner.atomic_write_text", spy)
    _bronze, path = qc_over(tmp_path, KEYS)

    assert used == [path], "the verdict file is written through the atomic path, not in place"
    assert json.loads(path.read_text())["examined"], "and the content still lands"


def test_a_rewrite_replaces_the_file_rather_than_appending(tmp_path: Path) -> None:
    """Re-running QC after fixing something must leave the NEW verdict, not both."""
    bronze, path = qc_over(tmp_path, KEYS)
    first = path.read_text()

    report = run_qc(
        bronze, tmp_path / "q", {f"{SYMBOL}:{FIRST.isoformat()}"}, calendar_path=CALENDAR
    )
    report.write_verdicts(path, bronze_root=bronze)

    assert path.read_text() != first
    assert json.loads(path.read_text())["quarantined"], "the rewrite is complete, not partial"


def test_the_keys_are_written_in_a_stable_order(tmp_path: Path) -> None:
    """Rule 1. Re-running QC over an unchanged archive must produce an identical file, or every
    diff of it is noise and nobody reads the next one.

    A set has no order. Emitting one would make the file depend on the interpreter's hash seed
    — precisely what the determinism gate runs two subprocesses to catch, and what this file
    would smuggle past it, since nothing else compares two QC runs.
    """
    bronze = tmp_path / "bronze"
    days = [date(2026, 8, d) for d in (17, 18, 19, 20, 21, 24, 25, 26, 27, 28)]
    for day in days:
        seed_two_sessions(bronze, 10_000, 10_000, first_day=day, second_day=day)
    keys = {f"{SYMBOL}:{d.isoformat()}" for d in days}

    report = run_qc(bronze, tmp_path / "q", keys, calendar_path=CALENDAR)
    path = tmp_path / "state" / "qc-verdicts.json"
    report.write_verdicts(path, bronze_root=bronze)

    assert json.loads(path.read_text())["examined"] == sorted(keys)


def test_a_path_that_resolves_to_the_same_archive_is_accepted(tmp_path: Path) -> None:
    """Provenance is about the DIRECTORY, not the spelling of it.

    `/srv/pips/bronze`, `./bronze` and a path through `..` all name one archive. Comparing the
    strings unresolved would refuse legitimate verdicts — and would accept the dangerous case:
    two different archives, each called `bronze` from its own working directory, compare EQUAL,
    which is the exact collision the provenance check exists to prevent.
    """
    bronze, path = qc_over(tmp_path, KEYS)
    same_place_spelt_differently = bronze / ".." / bronze.name

    loaded = QcVerdicts.load(path, bronze_root=same_place_spelt_differently)

    assert set(loaded.examined) == KEYS


def test_the_cli_writes_the_verdicts_where_promotion_looks(tmp_path: Path) -> None:
    """`make qc` is the only thing that runs QC today, so if it does not write the verdict
    file, the seam is unreachable in every real pipeline — which is what it was.

    The path is derived from the data root, beside the backfill manifest, because a verdict
    file whose location each caller chooses is one promotion cannot find.
    """
    from pips.data.qc.runner import main

    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)

    main([str(tmp_path)])

    path = tmp_path / "state" / "qc-verdicts.json"
    assert path.exists(), "a QC pass that reaches a verdict and discards it gates nothing"
    loaded = QcVerdicts.load(path, bronze_root=bronze)
    assert set(loaded.examined) == KEYS


def test_the_cli_says_where_it_wrote_them(tmp_path: Path) -> None:
    """A file nobody is told about is a file nobody passes to promotion."""
    from pips.data.qc.runner import main

    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)

    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main([str(tmp_path)])

    assert "qc-verdicts.json" in out.getvalue()
