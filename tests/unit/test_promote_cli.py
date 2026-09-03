"""`pips promote` — bronze becomes silver, and the QC gate is reachable from a shell (§6 M5/M6).

`promote_bronze` had no caller outside tests. Every reference to it in the tree is a docstring
pointing at it, including `silver_panel.py`'s error message, which tells the reader to *write
Python*: "Promote bronze first: `pips.data.silver.promote_bronze(bronze_root, silver_root,
master, known_on=...)`".

That left the gate built two ticks ago unreachable. `pips qc` writes its verdicts to
`<root>/state/qc-verdicts.json` and prints "pass them to promote_bronze(qc=...)" — and nothing
could. The seam existed at both ends with no command in between.

The default is loud rather than strict, deliberately, and unlike `pips capture`: promotion
spends nothing and touches no live path, so refusing without QC would make the fixture workflow
unusable to prevent a harm that only exists downstream. It follows
`require_verified_holidays` instead — usable without the evidence, never silent without it, and
`--require-qc` is the hard refusal for anything on the path to real capital.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data import silver as silver_module
from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore
from pips.data.qc.runner import seed_two_sessions

SYMBOL = "CLEAN"
FIRST, SECOND = date(2026, 8, 27), date(2026, 8, 28)
KEYS = [f"{SYMBOL}:{FIRST.isoformat()}", f"{SYMBOL}:{SECOND.isoformat()}"]


def archive(tmp_path: Path, *, with_master: bool = True) -> Path:
    seed_two_sessions(tmp_path / "bronze", 10_000, 10_000, first_day=FIRST, second_day=SECOND)
    if with_master:
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
    return tmp_path


def write_verdicts(tmp_path: Path, *, quarantined: list[str]) -> Path:
    path = tmp_path / "state" / "qc-verdicts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "written_at_ns": 1,
                "bronze_root": str((tmp_path / "bronze").resolve()),
                "examined": KEYS,
                "quarantined": quarantined,
            }
        )
    )
    return path


def test_it_promotes_bronze_and_reports_what_it_did(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive(tmp_path)
    write_verdicts(tmp_path, quarantined=[])

    assert silver_module.main([str(tmp_path), "--known-on", "2026-09-04"]) == 0

    out = capsys.readouterr().out
    assert "promoted 2" in out
    assert (tmp_path / "silver" / "bars_1m.parquet").exists()


def test_it_finds_the_verdicts_where_qc_writes_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`pips qc` writes `<root>/state/qc-verdicts.json` and says "pass them to promote_bronze".
    If this looked anywhere else, the two commands would still not meet."""
    archive(tmp_path)
    write_verdicts(tmp_path, quarantined=[KEYS[0]])

    assert silver_module.main([str(tmp_path), "--known-on", "2026-09-04"]) == 0

    out = capsys.readouterr().out
    assert "promoted 1" in out
    # `PromotionReport.describe()`'s actual wording, read from the source rather than
    # remembered: "N quarantined (M by QC)".
    assert "1 quarantined (1 by QC)" in out


def test_no_verdict_file_promotes_but_says_every_record_is_unchecked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Usable without the evidence, never silent without it.

    Refusing outright would make the fixture workflow unusable to prevent a harm that only
    exists downstream. Promoting quietly would put unchecked bars in the panel with a clean
    line above them, which is the defect the verdict seam exists to close.
    """
    archive(tmp_path)

    assert silver_module.main([str(tmp_path), "--known-on", "2026-09-04"]) == 0

    out = capsys.readouterr().out
    assert "2 promoted without QC" in out
    assert "make qc" in out, "it names the command that would fix this"


def test_require_qc_refuses_a_panel_built_on_unchecked_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The hard refusal, for anything on the path to real capital."""
    archive(tmp_path)

    assert silver_module.main([str(tmp_path), "--known-on", "2026-09-04", "--require-qc"]) == 1
    assert "no QC verdict" in capsys.readouterr().err


def test_require_qc_passes_when_every_record_was_examined(tmp_path: Path) -> None:
    archive(tmp_path)
    write_verdicts(tmp_path, quarantined=[])

    assert silver_module.main([str(tmp_path), "--known-on", "2026-09-04", "--require-qc"]) == 0


def test_an_absent_instrument_master_is_refused_before_anything_is_promoted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a master every vendor code resolves to nothing, so every record quarantines
    under a reason about identity.

    That is a true statement about each record and a useless one about the run: the operator
    reads 5,000 identity failures and goes looking for a data problem, when the answer is that
    the PIT store was never built. Refused up front, naming it.
    """
    archive(tmp_path, with_master=False)

    assert silver_module.main([str(tmp_path), "--known-on", "2026-09-04"]) == 2

    err = capsys.readouterr().err
    assert "no instrument master" in err.lower()
    assert not (tmp_path / "silver").exists()


def test_no_bronze_is_not_a_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The same shape `pips qc` uses: nothing to do is reported as nothing to do, not as a
    clean run over an archive that does not exist."""
    assert silver_module.main([str(tmp_path), "--known-on", "2026-09-04"]) == 0

    out = capsys.readouterr().out
    assert "no bronze" in out
    assert "not a pass" in out


def test_known_on_is_required_and_not_defaulted_to_today(tmp_path: Path) -> None:
    """`known_on` decides which version of the instrument master is read, so defaulting it to
    today would silently re-resolve a historical promotion under whatever the master says now
    — a bitemporal read that moves is the one thing §3.4 forbids."""
    archive(tmp_path)

    with pytest.raises(SystemExit):
        silver_module.main([str(tmp_path)])
