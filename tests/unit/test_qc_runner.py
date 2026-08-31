"""QC runner over bronze, and the seeded-corruption verify (§6 M5).

§6 M5's Verify is "seeded corrupt fixtures caught". Not "the checks pass in isolation" —
end to end, from a bronze record on disk to a quarantine entry with a reason. A check suite
that has only been exercised through its own unit tests has never met the parsing, the
normalization or the file layout it will actually run against.

The other property here is that quarantine **retains**. A record that fails QC is moved with
its reason attached, never dropped: the corrupt record is the evidence for the corruption, and
deleting it makes the finding unverifiable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pips.data.qc.runner import CORRUPTIONS, run_qc, seed_corrupt_bronze


@pytest.fixture
def clean(tmp_path: Path) -> Path:
    seed_corrupt_bronze(tmp_path / "bronze", corruption=None)
    return tmp_path


def test_a_clean_session_passes(clean: Path) -> None:
    # The control. Without it, a runner that quarantined everything would "catch" every
    # seeded corruption and look perfect.
    report = run_qc(clean / "bronze", clean / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    assert report.findings == []
    assert report.quarantined == 0
    assert report.checked == 1


@pytest.mark.parametrize("corruption", sorted(CORRUPTIONS))
def test_every_seeded_corruption_is_caught(tmp_path: Path, corruption: str) -> None:
    seed_corrupt_bronze(tmp_path / "bronze", corruption=corruption)
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    assert report.findings, f"seeded corruption {corruption!r} was not caught"
    # Which check should catch which corruption, stated explicitly. Requiring the names to
    # coincide would have forced a check per corruption, and an empty session is genuinely
    # a coverage problem rather than a category of its own.
    expected = {"empty": "session_coverage"}.get(corruption, corruption)
    assert expected in {f.check for f in report.findings}, (
        f"{corruption!r} was caught, but by {sorted({f.check for f in report.findings})} "
        f"rather than {expected!r}"
    )


def test_a_quarantined_record_is_moved_with_its_reason(tmp_path: Path) -> None:
    seed_corrupt_bronze(tmp_path / "bronze", corruption="bar_sanity")
    run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    entries = list((tmp_path / "quarantine").rglob("*.json"))
    assert entries, "a quarantined record must be written, not dropped"
    entry = json.loads(entries[0].read_text())
    assert entry["findings"], "the reason must travel with the record"
    assert entry["source"].endswith(".json")


def test_quarantine_retains_the_original_record(tmp_path: Path) -> None:
    # The corrupt record is the evidence for the corruption. Deleting it makes the finding
    # unverifiable, and a QC report nobody can check is a QC report nobody should trust.
    seed_corrupt_bronze(tmp_path / "bronze", corruption="bar_sanity")
    run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    entry = json.loads(next((tmp_path / "quarantine").rglob("*.json")).read_text())
    assert entry["payload"], "the original payload must be retained"


def test_bronze_is_never_modified_by_qc(tmp_path: Path) -> None:
    # Bronze is append-only and raw (§3.4). QC reads it and writes elsewhere; a QC pass that
    # edited bronze would destroy the only unmodified copy of what the vendor actually sent.
    seed_corrupt_bronze(tmp_path / "bronze", corruption="bar_sanity")
    before = {p: p.read_bytes() for p in (tmp_path / "bronze").rglob("*.json")}
    run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    after = {p: p.read_bytes() for p in (tmp_path / "bronze").rglob("*.json")}
    assert before == after


def test_a_key_absent_from_the_manifest_is_reported_as_unfetched(tmp_path: Path) -> None:
    # The cross-check that only exists because M4 kept the manifest: bronze alone cannot tell
    # "nothing traded" from "we never got an answer".
    seed_corrupt_bronze(tmp_path / "bronze", corruption="empty")
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys=set())
    assert any("not fetched" in f.detail.lower() for f in report.findings)


def test_the_report_is_reportable(tmp_path: Path) -> None:
    seed_corrupt_bronze(tmp_path / "bronze", corruption="spike")
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"CLEAN:2026-08-28"})
    summary = report.describe()
    assert "checked" in summary and "quarantined" in summary


def test_coverage_is_measured_against_the_real_session_not_the_fixture(tmp_path: Path) -> None:
    """A truncated REAL session must be caught.

    This was vacuous on real data. `run_qc` passed `expected_minutes=len(_rows())` — the seed
    fixture's 30 minutes — so a genuine 375-minute session arriving with 50 bars scored 50/30
    and sailed through. QC ran against the first six real records, reported zero findings, and
    the number was meaningless for this check.

    Caught by asking why a pass was a pass, not by a failure. The expectation now comes from
    the exchange calendar, so it describes the session rather than the test data.
    """
    import json
    import time

    rows = [
        {
            "datetime": f"2026-08-28 {9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00",
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.1,
            "volume": 10,
        }
        for i in range(50)  # 50 of ~375: badly truncated
    ]
    directory = tmp_path / "bronze" / "REAL" / "2026-08-28"
    directory.mkdir(parents=True)
    (directory / f"{time.time_ns()}.json").write_text(
        json.dumps(
            {
                "request": {"symbol": "REAL", "trade_date": "2026-08-28", "interval": "1minute"},
                "received_at_ns": time.time_ns(),
                "payload": {"Status": 200, "Success": rows},
            }
        )
    )
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"REAL:2026-08-28"})
    assert any(f.check == "session_coverage" for f in report.findings), (
        "50 bars of a 375-minute session must be flagged as truncated"
    )


def test_a_full_real_session_is_not_flagged(tmp_path: Path) -> None:
    # The control for the above. The M3 probe measured a real session at 370 of 375 minutes,
    # because untraded minutes are omitted — so the floor must sit well below that.
    import json
    import time

    rows = [
        {
            "datetime": f"2026-08-28 {9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00",
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.1,
            "volume": 10,
        }
        for i in range(370)
    ]
    directory = tmp_path / "bronze" / "REAL" / "2026-08-28"
    directory.mkdir(parents=True)
    (directory / f"{time.time_ns()}.json").write_text(
        json.dumps(
            {
                "request": {"symbol": "REAL", "trade_date": "2026-08-28", "interval": "1minute"},
                "received_at_ns": time.time_ns(),
                "payload": {"Status": 200, "Success": rows},
            }
        )
    )
    report = run_qc(tmp_path / "bronze", tmp_path / "quarantine", fetched_keys={"REAL:2026-08-28"})
    assert not [f for f in report.findings if f.check == "session_coverage"]
