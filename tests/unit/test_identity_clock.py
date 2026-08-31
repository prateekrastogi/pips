"""Which clock an identity lookup uses  [C-DATA-01] (§3.4, §6 M6).

`InstrumentMaster.as_of(on)` passed one date as BOTH clocks, and that collapse hid two
genuinely different questions behind one call:

**"Which security was RELIND on 28 August?"** — a question about the world. Valid time answers
it: whoever held that code then, whenever we happened to learn it. Asking this today, with a
master downloaded on the 31st, is not lookahead. It is reference data about the past.

**"Which security did we BELIEVE RELIND was, on 28 August?"** — a question about us. Knowledge
time answers it, and reproducing a historical run needs exactly this: if the master was wrong
that day, the run that used it saw the wrong answer.

Both are legitimate. Collapsing them made the second the silent default, so a QC pass over
August bronze resolved *nothing* — the master's knowledge began on the 31st — and reported it
as an unidentified security.

**So there is no default.** `known_on` is required, and `None` is a thing the caller must type.
Neither failure is visible on its own: forgetting to ask for current knowledge resolves nothing
(which I demonstrated is invisible through QC), and forgetting to pin a historical run's
knowledge silently uses today's. When both mistakes are silent, the decision belongs at the
call site.

**The action clock does NOT move.** Identity is reference data; a corporate action recorded
after the fact must still never explain an earlier jump. The last test here exists to prove the
identity fix did not leak into the causality rule.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.corporate_actions import ActionKind, CorporateAction, CorporateActionMaster
from pips.data.pit.explain import jump_explainer
from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore

D = date
ISIN = "INE002A01018"


def listed(**over: object) -> Instrument:
    base: dict[str, object] = {
        "isin": ISIN,
        "exchange_token": "2885",
        "symbol": "RELIANCE",
        "name": "RELIANCE INDUSTRIES",
        "series": "EQ",
        "lot_size": 1,
        "tick_size_paise": 1,
        "vendor_code": "RELIND",
    }
    base.update(over)
    return Instrument.model_validate(base)


@pytest.fixture
def master(tmp_path: Path) -> InstrumentMaster:
    return InstrumentMaster(PitStore(tmp_path / "pit"))


# ------------------------------------------- the question about the world ---------------


def test_current_knowledge_resolves_a_bar_that_predates_the_ingest(
    master: InstrumentMaster,
) -> None:
    """The failure that started this: the master is ingested after the data it describes.

    A scrip master downloaded on the 31st knows nothing on the 28th, so every historical QC
    pass resolved nothing — for every instrument, forever, since every instrument is ingested
    after some of its own bars.
    """
    master.upsert(listed(), known_from=D(2026, 8, 31), valid_from=D(2020, 1, 1))
    found = master.resolve_vendor_code("RELIND", on=D(2026, 8, 28), known_on=None)
    assert found is not None
    assert found.isin == ISIN


def test_valid_time_still_decides_who_held_the_code(master: InstrumentMaster) -> None:
    """Current knowledge must not become "today's holder".

    The splice this whole master exists to prevent: a code reassigned between companies. Using
    what we know NOW is fine; using WHO HOLDS IT NOW is the error. Valid time still separates
    them, and that is why current knowledge is safe here.
    """
    master.upsert(listed(vendor_code="SHARED"), known_from=D(2026, 8, 31), valid_from=D(2020, 1, 1))
    master.delist(ISIN, known_from=D(2026, 8, 31))
    master.upsert(
        listed(isin="INE467B01029", vendor_code="SHARED", symbol="TCS"),
        known_from=D(2026, 9, 15),
        valid_from=D(2026, 9, 1),
    )

    earlier = master.resolve_vendor_code("SHARED", on=D(2026, 8, 28), known_on=None)
    later = master.resolve_vendor_code("SHARED", on=D(2026, 9, 20), known_on=None)
    assert earlier is not None and earlier.isin == ISIN
    assert later is not None and later.isin == "INE467B01029"


# ------------------------------------------- the question about us ----------------------


def test_pinning_knowledge_reproduces_what_the_master_said_then(
    master: InstrumentMaster,
) -> None:
    """Reproducing a historical run needs the belief of the day, errors included.

    A CORRECTION, not a rename — and the distinction is the test. A rename says the symbol
    changed on a date, so it does not apply to earlier dates and full knowledge still returns
    the old name. A correction says we recorded it wrongly all along, so it applies to every
    date and only knowledge time separates the two answers.

    My first version used `rename` here and was right to fail: it was asking the correction
    question through the change operation.
    """
    master.upsert(listed(symbol="WRONGNAME"), known_from=D(2026, 8, 1), valid_from=D(2020, 1, 1))
    master.correct(ISIN, known_from=D(2026, 8, 20), symbol="RELIANCE")

    as_believed = master.resolve_vendor_code("RELIND", on=D(2026, 8, 10), known_on=D(2026, 8, 10))
    as_known_now = master.resolve_vendor_code("RELIND", on=D(2026, 8, 10), known_on=None)
    assert as_believed is not None and as_believed.symbol == "WRONGNAME"
    assert as_known_now is not None and as_known_now.symbol == "RELIANCE"


def test_the_two_clocks_give_different_answers_and_both_are_available(
    master: InstrumentMaster,
) -> None:
    # The control for the pair above: if these ever agree, one of the clocks has stopped.
    master.upsert(listed(), known_from=D(2026, 8, 31), valid_from=D(2020, 1, 1))
    assert master.as_of(D(2026, 8, 28), known_on=D(2026, 8, 28)) == []
    assert len(master.as_of(D(2026, 8, 28), known_on=None)) == 1


def test_known_on_must_be_stated(master: InstrumentMaster) -> None:
    """No default, because neither mistake is visible.

    Forgetting to ask for current knowledge resolves nothing — invisible through QC, as this
    project found out. Forgetting to pin a run's knowledge silently uses today's. When both
    failures are silent the decision belongs at the call site, typed out.
    """
    master.upsert(listed(), known_from=D(2026, 8, 31), valid_from=D(2020, 1, 1))
    with pytest.raises(TypeError):
        master.as_of(D(2026, 8, 28))  # type: ignore[call-arg]


# ------------------------------------------- the action clock does NOT move -------------


def test_an_action_recorded_later_still_cannot_explain_an_earlier_jump(
    tmp_path: Path,
) -> None:
    """The leak this fix must not have.

    Identity now resolves with current knowledge. Corporate actions must NOT: an action
    recorded a week after a jump did not explain anything at the time, and letting it do so
    would quietly un-quarantine historical records — using the identity fix as the vehicle.
    """
    store = PitStore(tmp_path / "pit")
    InstrumentMaster(store).upsert(listed(), known_from=D(2026, 8, 31), valid_from=D(2020, 1, 1))
    CorporateActionMaster(store).announce(
        CorporateAction(
            action_id=f"{ISIN}-2026-08-28-SPLIT",
            isin=ISIN,
            kind=ActionKind.SPLIT,
            ex_date=D(2026, 8, 28),
            shares_before=1,
            shares_after=2,
        ),
        known_from=D(2026, 9, 10),
    )

    explain = jump_explainer(tmp_path / "pit")
    assert explain is not None
    verdict = explain("RELIND", D(2026, 8, 28), 128_540, 64_270)

    assert verdict is not None
    assert "not in the instrument master" not in verdict.reason, (
        "identity must resolve — that is the fix"
    )
    assert not verdict.explained, (
        "but the action was recorded on 10 September and cannot explain a 28 August jump"
    )


def test_an_action_known_at_the_time_does_explain_it(tmp_path: Path) -> None:
    # The control. Without it, "not explained" could be what the seam always says.
    store = PitStore(tmp_path / "pit")
    InstrumentMaster(store).upsert(listed(), known_from=D(2026, 8, 31), valid_from=D(2020, 1, 1))
    CorporateActionMaster(store).announce(
        CorporateAction(
            action_id=f"{ISIN}-2026-08-28-SPLIT",
            isin=ISIN,
            kind=ActionKind.SPLIT,
            ex_date=D(2026, 8, 28),
            shares_before=1,
            shares_after=2,
        ),
        known_from=D(2026, 8, 1),
    )
    explain = jump_explainer(tmp_path / "pit")
    assert explain is not None
    verdict = explain("RELIND", D(2026, 8, 28), 128_540, 64_270)
    assert verdict is not None
    assert verdict.explained, verdict.reason
