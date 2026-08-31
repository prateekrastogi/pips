"""Connecting QC's verdict seam to the M6 masters  [C-DATA-01] (§6 M5/M6).

`check_unexplained_ratio_jump` takes a verdict; the corporate-action master produces one. The
join between them is not trivial, and it is the reason the seam was left as a callable rather
than a master object: **bronze carries a SYMBOL and the action master is keyed on ISIN.**
Resolving one to the other is the instrument master's job, and it has to be done as-of, or a
reused symbol resolves to whichever company holds it today.

Three outcomes, and keeping them apart is the point:

- resolved, and an action accounts for the move  -> explained, no finding
- resolved, and nothing accounts for it          -> unexplained, quarantined
- NOT resolved                                   -> unexplained, quarantined, and the reason
                                                    says the symbol is unknown

The third is the one worth being careful about. "I could not identify this security" is a
different fact from "this security had no corporate action", and reporting the first as the
second is the failure this project keeps meeting: a lookup that could not answer, recorded as
an answer.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.corporate_actions import ActionKind, CorporateAction, CorporateActionMaster
from pips.data.pit.explain import jump_explainer
from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore
from pips.data.qc.runner import main, seed_two_sessions

D = date
ISIN = "INE002A01018"
SEED_SYMBOL = "CLEAN"
FIRST_DAY = D(2026, 8, 27)
SECOND_DAY = D(2026, 8, 28)
DEFAULT_ANNOUNCE = D(2026, 8, 1)


def seed_archive(root: Path) -> None:
    """A halving between two adjacent sessions -- split-shaped, and quarantined by default."""
    seed_two_sessions(root / "bronze", first_close_paise=100_000, second_open_paise=50_000)
    (root / "state").mkdir(exist_ok=True)
    (root / "state" / "backfill-manifest.json").write_text(
        json.dumps(
            {"outcomes": {f"{SEED_SYMBOL}:{d.isoformat()}": "OK" for d in (FIRST_DAY, SECOND_DAY)}}
        ),
        encoding="utf-8",
    )


def seed_instrument(root: Path, symbol: str = SEED_SYMBOL) -> None:
    master = InstrumentMaster(PitStore(root / "pit"))
    master.upsert(
        Instrument(
            isin=ISIN,
            exchange_token="2885",
            symbol=symbol,
            name="Clean Ltd",
            series="EQ",
            lot_size=1,
            tick_size_paise=5,
        ),
        known_from=D(2026, 1, 1),
    )


def seed_split(root: Path, known_from: date = DEFAULT_ANNOUNCE) -> None:
    CorporateActionMaster(PitStore(root / "pit")).announce(
        CorporateAction(
            action_id=f"{ISIN}-2026-08-28-SPLIT",
            isin=ISIN,
            kind=ActionKind.SPLIT,
            ex_date=SECOND_DAY,
            shares_before=1,
            shares_after=2,
        ),
        known_from=known_from,
    )


# ------------------------------------------------------------- the three outcomes -------


def test_a_matching_split_explains_the_jump_and_nothing_is_quarantined(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_archive(tmp_path)
    seed_instrument(tmp_path)
    seed_split(tmp_path)
    assert main([str(tmp_path)]) == 0
    assert "ratio_jump" not in capsys.readouterr().out


def test_without_an_action_the_same_jump_is_quarantined(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The control for the test above. If both passed, the explainer would be proving nothing —
    # a seeded master that silently explains everything looks exactly like one that works.
    seed_archive(tmp_path)
    seed_instrument(tmp_path)
    assert main([str(tmp_path)]) == 1
    assert "ratio_jump" in capsys.readouterr().out


def test_an_unresolvable_symbol_is_reported_as_unknown_not_as_no_action(
    tmp_path: Path,
) -> None:
    """ "I could not identify this security" is not "this security had no action".

    Both quarantine, so the exit code cannot tell them apart — but the operator reading the
    reason has to act differently: one means fix the instrument master, the other means
    investigate the data.
    """
    seed_archive(tmp_path)
    seed_instrument(tmp_path, symbol="SOMETHINGELSE")
    seed_split(tmp_path)
    assert main([str(tmp_path)]) == 1

    reasons = [
        json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "quarantine").rglob("*.json")
    ]
    detail = " ".join(
        f["detail"] for r in reasons for f in r.get("qc_findings", r.get("findings", []))
    )
    assert "not in the instrument master" in detail, detail


def test_an_action_known_only_later_does_not_explain_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # QC runs on the day. An action recorded a week later did not explain anything then, and
    # letting it do so would quietly un-quarantine historical records.
    seed_archive(tmp_path)
    seed_instrument(tmp_path)
    seed_split(tmp_path, known_from=D(2026, 9, 5))
    assert main([str(tmp_path)]) == 1
    assert "ratio_jump" in capsys.readouterr().out


# ------------------------------------------------------------- fail closed --------------


def test_no_pit_store_at_all_yields_no_explainer(tmp_path: Path) -> None:
    # Fails closed: with nothing to consult there is no verdict, and no verdict quarantines.
    assert jump_explainer(tmp_path / "absent") is None


def test_the_symbol_is_resolved_as_of_the_qc_date_not_today(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The splice, reintroduced at the join — caught by mutation, not by design.

    The instrument master refuses to resolve a reused symbol by today's holder. The EXPLAINER
    has to ask it as-of the QC date to get that protection, and nothing here proved it did:
    replacing `on=day` with `on=date.max` killed no test.

    Here the symbol belonged to one company on the QC date and was lent to another afterwards.
    Resolving as-of finds the first, and its split explains the move. Resolving by today finds
    the second, which has no action, and a perfectly good record is quarantined.

    The reverse case is worse and is the same bug: the later holder's actions used to explain
    the earlier holder's prices, so a genuine corruption gets waved through by an action that
    belongs to a different security entirely.
    """
    seed_archive(tmp_path)
    store = PitStore(tmp_path / "pit")
    instruments = InstrumentMaster(store)

    def listing(isin: str, token: str) -> Instrument:
        return Instrument(
            isin=isin,
            exchange_token=token,
            symbol=SEED_SYMBOL,
            name="Clean Ltd",
            series="EQ",
            lot_size=1,
            tick_size_paise=5,
        )

    instruments.upsert(listing(ISIN, "2885"), known_from=D(2026, 1, 1))
    instruments.delist(ISIN, known_from=D(2026, 9, 1))
    instruments.upsert(listing("INE467B01029", "9999"), known_from=D(2026, 9, 15))
    seed_split(tmp_path)  # belongs to the FIRST holder

    assert main([str(tmp_path)]) == 0, "the split of the holder ON THE DAY must explain it"
    assert "ratio_jump" not in capsys.readouterr().out


# ------------------------------------------- which identifier bronze actually carries ----


def seed_real_shaped_instrument(root: Path) -> None:
    """As the real scrip master records it: vendor code RELIND, exchange symbol RELIANCE."""
    InstrumentMaster(PitStore(root / "pit")).upsert(
        Instrument(
            isin=ISIN,
            exchange_token="2885",
            symbol="RELIANCE",
            name="RELIANCE INDUSTRIES",
            series="EQ",
            lot_size=1,
            tick_size_paise=1,
            vendor_code="RELIND",
        ),
        known_from=D(2026, 1, 1),
    )


def test_a_bronze_vendor_code_resolves_against_the_real_master() -> None:
    """The bug the live master exposed, and QC could not have shown.

    pips' bronze is keyed by the DATA VENDOR's code — RELIND — while the master's `symbol` is
    the exchange's, RELIANCE. The explainer asked `resolve_symbol`, so with 5,851 real
    instruments loaded it still reported *"RELIND is not in the instrument master"*.

    QC never showed it: the run had no ratio jumps, so the explainer was never called and the
    report said 0 findings either way. Only asking the explainer directly surfaced it.

    The message was at least honest — "an unidentified security, NOT a security with no
    actions" — which is the distinction that made the bug legible instead of looking like an
    absence of corporate actions.
    """
    import tempfile

    root = Path(tempfile.mkdtemp())
    seed_real_shaped_instrument(root)
    explain = jump_explainer(root / "pit")
    assert explain is not None

    verdict = explain("RELIND", D(2026, 8, 28), 128_540, 64_270)
    assert verdict is not None
    assert "not in the instrument master" not in verdict.reason, verdict.reason
    assert "no known action" in verdict.reason


def test_an_exchange_symbol_also_resolves() -> None:
    # Bronze carries the vendor code today; a broker fill will carry the exchange symbol.
    # Both must work, or the seam breaks the first time it is used from the other side.
    import tempfile

    root = Path(tempfile.mkdtemp())
    seed_real_shaped_instrument(root)
    explain = jump_explainer(root / "pit")
    assert explain is not None
    by_symbol = explain("RELIANCE", D(2026, 8, 28), 128_540, 64_270)
    assert by_symbol is not None
    assert "not in the instrument master" not in by_symbol.reason


def test_an_identifier_that_resolves_to_two_different_securities_is_refused() -> None:
    """One string, two instruments, by different routes.

    If a name's vendor code is some other name's exchange symbol, trying both and taking the
    first is how one company's actions get used to explain another's prices. It is the same
    refusal `resolve_symbol` already makes for two live claims on one symbol, carried across
    the two identifier spaces.
    """
    import tempfile

    root = Path(tempfile.mkdtemp())
    master = InstrumentMaster(PitStore(root / "pit"))
    master.upsert(
        Instrument(
            isin=ISIN,
            exchange_token="1",
            symbol="ACME",
            name="A",
            series="EQ",
            lot_size=1,
            tick_size_paise=1,
            vendor_code="ZZZ",
        ),
        known_from=D(2026, 1, 1),
    )
    master.upsert(
        Instrument(
            isin="INE467B01029",
            exchange_token="2",
            symbol="OTHER",
            name="B",
            series="EQ",
            lot_size=1,
            tick_size_paise=1,
            vendor_code="ACME",
        ),
        known_from=D(2026, 1, 1),
    )
    explain = jump_explainer(root / "pit")
    assert explain is not None
    verdict = explain("ACME", D(2026, 8, 28), 128_540, 64_270)
    assert verdict is not None
    assert not verdict.explained
    assert "ambiguous" in verdict.reason
