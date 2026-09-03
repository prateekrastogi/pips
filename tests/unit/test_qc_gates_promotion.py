"""Promotion consults QC, and a QC pass that never ran does not read as one that passed.

`[C-QC-01]`/`[C-QC-02]` have had one blocker left: *nothing makes QC a precondition of
anything*. `promote_bronze` already runs the checks it can run ITSELF — bar sanity and label
order — and the comment beside them is right that the others do not belong there: session
coverage needs the backfill manifest, the ratio jump needs the previous session and the
corporate-action master. Promotion knows neither, and quarantining on a guess would be worse
than not checking.

So the missing thing is not more checks inline. It is that promotion had **no way to know
whether QC had run at all**. An empty quarantine directory and a QC pass that never happened
are the same evidence, which is this codebase's recurring defect one level up: a check that did
not run, reading as a check that passed.

The answer here follows `require_verified_holidays`, which the calendar already establishes:
usable without the evidence, never SILENT without it, and a hard refusal available for anything
on the path to real capital. Research on fixtures needs the first; the panel needs the last.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore
from pips.data.qc.checks import QcVerdicts
from pips.data.qc.runner import run_qc, seed_two_sessions
from pips.data.silver import promote_bronze

ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "config" / "calendars" / "nse_equity.yaml"
FIRST, SECOND = date(2026, 8, 27), date(2026, 8, 28)
SYMBOL = "CLEAN"  # what `seed_two_sessions` writes; a wrong symbol here misses every key
KEYS = {f"{SYMBOL}:{FIRST.isoformat()}", f"{SYMBOL}:{SECOND.isoformat()}"}
KNOWN_ON = date(2026, 9, 3)


def one_instrument_master(tmp_path: Path) -> InstrumentMaster:
    """A real master holding the one instrument the seeder's records name.

    Real rather than a stub: `InstrumentMaster` is a concrete class over a `PitStore`, and a
    duck-typed stand-in does not satisfy it under `mypy --strict`. Using the real one also
    means these tests exercise the vendor-code resolution promotion actually performs —
    notably that a record is refused when the code resolves to nothing, which is the failure
    a stub returning a synthetic instrument would paper over.
    """
    master = InstrumentMaster(PitStore(tmp_path / "pit"))
    master.upsert(
        Instrument(
            isin="INE002A01018",
            exchange_token="2885",
            symbol="RELIANCE",
            name="Reliance Industries Ltd",
            series="EQ",
            lot_size=1,
            tick_size_paise=5,
            vendor_code=SYMBOL,
        ),
        known_from=date(2020, 1, 1),
    )
    return master


def seeded(tmp_path: Path) -> Path:
    bronze = tmp_path / "bronze"
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)
    return bronze


def promote(bronze: Path, tmp_path: Path, qc: QcVerdicts | None) -> Any:
    return promote_bronze(
        bronze,
        tmp_path / "silver",
        one_instrument_master(tmp_path),
        known_on=KNOWN_ON,
        qc=qc,
    )


def test_a_record_qc_quarantined_is_not_promoted(tmp_path: Path) -> None:
    """The whole point. QC finds a problem promotion cannot see for itself -- a truncated
    session, an unexplained overnight jump -- and the bars must not reach the panel anyway."""
    bronze = seeded(tmp_path)
    rejected = f"{SYMBOL}:{FIRST.isoformat()}"
    report = promote(bronze, tmp_path, QcVerdicts(examined=KEYS, quarantined={rejected}))

    assert report.files_promoted == 1
    assert report.refused_by_qc == 1
    assert any("QC" in q.reason for q in report.quarantined)
    assert all(r["symbol"] == "RELIANCE" for r in report.rows), "the EXCHANGE symbol"
    promoted_days = {r["close_ts_ns"] for r in report.rows}
    assert promoted_days, "the surviving session was still promoted"


def test_the_refused_records_bars_are_absent_from_silver_not_merely_uncounted(
    tmp_path: Path,
) -> None:
    """A count is not the property. If the bars are written and only the tally is adjusted, the
    panel still holds data QC rejected and every number computed from it is wrong."""
    bronze = seeded(tmp_path)
    both = promote(bronze, tmp_path, QcVerdicts(examined=KEYS, quarantined=set()))
    one = promote(
        bronze, tmp_path, QcVerdicts(examined=KEYS, quarantined={f"{SYMBOL}:{FIRST.isoformat()}"})
    )

    assert len(one.rows) * 2 == len(both.rows), "exactly one session's bars are missing"


def test_a_record_qc_examined_and_passed_is_promoted(tmp_path: Path) -> None:
    bronze = seeded(tmp_path)
    report = promote(bronze, tmp_path, QcVerdicts(examined=KEYS, quarantined=set()))

    assert report.files_promoted == 2
    assert report.refused_by_qc == 0
    assert report.promoted_without_qc == 0


def test_a_record_qc_never_looked_at_is_counted_not_assumed_clean(tmp_path: Path) -> None:
    """The defect this unit exists for. QC examined one session; the other it never saw.

    Promoted, because refusing outright would make every fixture-based test unusable and QC is
    not always available. Counted, because "0 quarantined" over a record nobody checked is not
    a clean bill -- it is no bill at all.
    """
    bronze = seeded(tmp_path)
    report = promote(
        bronze, tmp_path, QcVerdicts(examined={f"{SYMBOL}:{FIRST.isoformat()}"}, quarantined=set())
    )

    assert report.files_promoted == 2
    assert report.promoted_without_qc == 1


def test_promotion_with_no_qc_at_all_says_so_for_every_record(tmp_path: Path) -> None:
    """`qc=None` is the old behaviour, and it must not be the quiet one. Every record promoted
    without a verdict is counted, so a run that never consulted QC cannot print the same line
    as one that consulted it for everything."""
    report = promote(seeded(tmp_path), tmp_path, None)

    assert report.files_promoted == 2
    assert report.promoted_without_qc == 2
    assert report.refused_by_qc == 0


def test_requiring_qc_coverage_refuses_a_panel_built_on_unchecked_records(
    tmp_path: Path,
) -> None:
    """The hard refusal, for anything on the path to real capital.

    Modelled on `require_verified_holidays`: the archive stays usable without the evidence so
    research on fixtures works, and the thing that trades has to ask. A report that merely
    counted would leave the decision to whoever remembered to read the number.
    """
    report = promote(seeded(tmp_path), tmp_path, None)

    with pytest.raises(RuntimeError, match="2 record"):
        report.require_qc_coverage()


def test_requiring_qc_coverage_passes_when_every_record_was_examined(tmp_path: Path) -> None:
    report = promote(seeded(tmp_path), tmp_path, QcVerdicts(examined=KEYS, quarantined=set()))

    report.require_qc_coverage()


def test_a_qc_run_hands_promotion_the_verdicts_it_reached(tmp_path: Path) -> None:
    """End to end, because the two halves being individually right is not the property.

    QC keys its records `SYMBOL:YYYY-MM-DD` and so does the backfill manifest; promotion has to
    key them the same way or every verdict silently misses and every record reads as unchecked.
    A mismatch would show up as a suspiciously clean `promoted_without_qc`, which is exactly the
    number nobody would question.
    """
    bronze = seeded(tmp_path)
    qc_report = run_qc(bronze, tmp_path / "q", KEYS, calendar_path=CALENDAR)
    verdicts = qc_report.verdicts()

    assert verdicts.examined == KEYS, "the keys QC used are the keys promotion looks up"

    report = promote(bronze, tmp_path, verdicts)
    assert report.promoted_without_qc == 0
    report.require_qc_coverage()


def test_a_quarantined_record_reaches_promotion_as_a_refusal(tmp_path: Path) -> None:
    """The connected version of the first test: QC actually rejects something, and promotion
    actually declines it, with no set assembled by hand in between."""
    bronze = tmp_path / "bronze"
    # A record whose fetch never succeeded: QC calls that a hole, not a quiet market.
    seed_two_sessions(bronze, 10_000, 10_000, first_day=FIRST, second_day=SECOND)
    partial_keys = {f"{SYMBOL}:{FIRST.isoformat()}"}

    qc_report = run_qc(bronze, tmp_path / "q", partial_keys, calendar_path=CALENDAR)
    verdicts = qc_report.verdicts()

    assert f"{SYMBOL}:{SECOND.isoformat()}" in verdicts.quarantined

    report = promote(bronze, tmp_path, verdicts)
    assert report.refused_by_qc == 1
    assert report.files_promoted == 1


def test_the_report_prints_the_unchecked_count(tmp_path: Path) -> None:
    """A number in a dataclass nobody prints is a number nobody reads."""
    report = promote(seeded(tmp_path), tmp_path, None)

    assert "2" in report.describe()
    assert "without QC" in report.describe()
