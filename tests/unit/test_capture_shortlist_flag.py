"""`pips capture --shortlist <prerank artifact>`: the 500 reach the capture without retyping.

The artifact holds EXCHANGE symbols; Breeze wants its own stock codes. The flag resolves each
selected symbol through the PIT master as of the artifact's `as_of` and refuses -- exit 2, names
listed -- if any does not resolve. A silently dropped name is a name that later trades with no
captured data behind it, which is the exact failure the shortlist exists to prevent.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data.breeze import capture_session
from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore

WEEKEND = "2026-09-06T10:00:00+05:30"  # a Sunday: the plan is printed, nothing opens
AS_OF = "2026-09-03"
KNOWN_ISINS = {"RELIANCE": "INE002A01018", "ICICIBANK": "INE090A01021"}


def instrument(symbol: str, vendor: str, isin: str) -> Instrument:
    return Instrument(
        isin=isin,
        exchange_token=str(abs(hash(isin)) % 100000),
        symbol=symbol,
        name=symbol,
        series="EQ",
        lot_size=1,
        tick_size_paise=5,
        vendor_code=vendor,
    )


def archive(tmp_path: Path, selected: list[str]) -> Path:
    master = InstrumentMaster(PitStore(tmp_path / "pit"))
    master.upsert(instrument("RELIANCE", "RELIND", "INE002A01018"), known_from=date(2020, 1, 1))
    master.upsert(instrument("ICICIBANK", "ICIBAN", "INE090A01021"), known_from=date(2020, 1, 1))
    (tmp_path / "universes").mkdir()
    (tmp_path / "universes" / f"prerank-{AS_OF}.json").write_text(
        json.dumps(
            {
                "as_of": AS_OF,
                "n": 500,
                "selected": selected,
                "ranked": selected,
                # the artifact identifies names by ISIN; an unknown name gets an ISIN nobody holds
                "isins": {
                    sym: KNOWN_ISINS.get(sym, f"INE{sym[:6]:<6}0000")[:12] for sym in selected
                },
            }
        )
    )
    return tmp_path


def run(root: Path, *extra: str) -> int:
    return capture_session.main([str(root), "--now", WEEKEND, *extra])


def test_the_shortlist_is_resolved_to_vendor_codes_and_the_plan_names_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, ["RELIANCE", "ICICIBANK"])
    artifact = root / "universes" / f"prerank-{AS_OF}.json"
    assert run(root, "--shortlist", str(artifact)) == 0
    out = capsys.readouterr().out
    assert "capture: 2 symbol(s): RELIND, ICIBAN" in out
    assert f"prerank-{AS_OF}.json" in out  # the plan says where its list came from


def test_an_unresolvable_symbol_is_a_refusal_that_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, ["RELIANCE", "GHOSTCO"])
    assert run(root, "--shortlist", str(root / "universes" / f"prerank-{AS_OF}.json")) == 2
    err = capsys.readouterr().err
    assert "GHOSTCO" in err
    assert "1 of 2" in err


def test_an_empty_shortlist_is_the_existing_no_symbols_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, [])
    assert run(root, "--shortlist", str(root / "universes" / f"prerank-{AS_OF}.json")) == 2
    assert "no symbols" in capsys.readouterr().err


def test_symbols_and_shortlist_are_mutually_exclusive_and_one_is_required(tmp_path: Path) -> None:
    root = archive(tmp_path, ["RELIANCE"])
    artifact = str(root / "universes" / f"prerank-{AS_OF}.json")
    with pytest.raises(SystemExit) as both:
        run(root, "--symbols", "RELIND", "--shortlist", artifact)
    assert both.value.code == 2
    with pytest.raises(SystemExit) as neither:
        run(root)
    assert neither.value.code == 2


def test_symbols_still_works_exactly_as_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, ["RELIANCE"])
    assert run(root, "--symbols", "RELIND,ICIBAN") == 0
    assert "capture: 2 symbol(s): RELIND, ICIBAN" in capsys.readouterr().out


def test_a_missing_master_is_a_refusal_not_an_empty_subscription(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "universes").mkdir()
    artifact = tmp_path / "universes" / f"prerank-{AS_OF}.json"
    artifact.write_text(
        json.dumps({"as_of": AS_OF, "selected": ["RELIANCE"], "ranked": ["RELIANCE"]})
    )
    assert run(tmp_path, "--shortlist", str(artifact)) == 2
    assert "instrument master" in capsys.readouterr().err


def test_resolution_is_as_of_the_artifact_date_so_a_later_rename_does_not_lose_the_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # RELIANCE is renamed on 2026-09-10. The artifact is as of 2026-09-03, when the name was
    # still RELIANCE, so it must resolve. A resolver that looked at today's (or any later) state
    # would find nobody holding "RELIANCE" and refuse a perfectly good shortlist.
    root = archive(tmp_path, ["RELIANCE", "ICICIBANK"])
    InstrumentMaster(PitStore(root / "pit")).rename(
        "INE002A01018", "RELX", known_from=date(2026, 9, 10)
    )
    assert run(root, "--shortlist", str(root / "universes" / f"prerank-{AS_OF}.json")) == 0
    assert "RELIND, ICIBAN" in capsys.readouterr().out


def archive_with_isins(tmp_path: Path, selected: list[str], isins: dict[str, str]) -> Path:
    root = archive(tmp_path, selected)
    artifact = root / "universes" / f"prerank-{AS_OF}.json"
    payload = json.loads(artifact.read_text())
    payload["isins"] = isins
    artifact.write_text(json.dumps(payload))
    return root


def test_resolution_is_by_isin_so_the_equity_wins_over_a_warrant_with_the_same_symbol(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # arb-vm, 2026-09-05: HDFCBANK is held by INE040A01034 (EQ, HDFBAN) and INE040A13013
    # ("HDFC BANK WARRANT AUG 23", W3, HDFWA2). By symbol the master refuses; by ISIN it cannot.
    root = archive_with_isins(tmp_path, ["RELIANCE"], {"RELIANCE": "INE002A01018"})
    warrant = instrument("RELIANCE", "RELWA1", "INE002A13016")
    warrant = warrant.model_copy(update={"series": "W3"})
    InstrumentMaster(PitStore(root / "pit")).upsert(warrant, known_from=date(2020, 1, 1))
    assert run(root, "--shortlist", str(root / "universes" / f"prerank-{AS_OF}.json")) == 0
    assert "capture: 1 symbol(s): RELIND" in capsys.readouterr().out


def test_an_artifact_without_isins_is_refused_not_resolved_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, ["RELIANCE"])
    artifact = root / "universes" / f"prerank-{AS_OF}.json"
    payload = json.loads(artifact.read_text())
    del payload["isins"]  # the pre-ISIN artifact shape
    artifact.write_text(json.dumps(payload))
    assert run(root, "--shortlist", str(root / "universes" / f"prerank-{AS_OF}.json")) == 2
    err = capsys.readouterr().err
    assert "isins" in err and "regenerate" in err.lower()


def test_an_isin_unknown_to_the_master_as_of_the_artifact_date_is_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive_with_isins(
        tmp_path, ["RELIANCE", "GHOSTCO"], {"RELIANCE": "INE002A01018", "GHOSTCO": "INE000GHOST0"}
    )
    assert run(root, "--shortlist", str(root / "universes" / f"prerank-{AS_OF}.json")) == 2
    assert "GHOSTCO" in capsys.readouterr().err


def test_resolution_is_as_of_the_artifact_date_so_a_later_delisting_does_not_lose_the_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # By ISIN a later rename is irrelevant; a later DELISTING is not. As of the artifact's date
    # the instrument is live and must resolve; a resolver reading today's (or any later) state
    # would find it gone and refuse a shortlist that was right when it was built.
    root = archive(tmp_path, ["RELIANCE", "ICICIBANK"])
    InstrumentMaster(PitStore(root / "pit")).delist("INE002A01018", known_from=date(2026, 9, 10))
    assert run(root, "--shortlist", str(root / "universes" / f"prerank-{AS_OF}.json")) == 0
    assert "RELIND, ICIBAN" in capsys.readouterr().out
