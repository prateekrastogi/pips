"""Point-in-time corporate-action master  [C-DATA-01] (§6 M6, §3.4, rule 12 causality).

Ported in SHAPE ONLY from SAL-0016 (`convexity 790d7235b202:
src/convexity/breakout/data/corporate_actions.py`, deleted from HEAD, 2268 bytes). What that
donor contributes is the idea: back-adjust a multiplicative factor onto the bars before an
ex-date so the action bar is not a fabricated breakout. What it cannot contribute is anything
this milestone is actually for — it is US equities in float arithmetic, with no knowledge time
and, more seriously, no causality rule: it applies every supplied action to every pre-ex-date
bar regardless of when the action was known or whether its ex-date has arrived.

**The causality rule is the whole thing.** Adjusting a bar at time `s`, as of decision time
`t`, uses actions with `s < ex_date <= t` and `known_from <= t`. Both bounds carry weight:

- `ex_date <= t`: a split announced in June and effective in July must NOT adjust May bars
  when the decision is made in June. The June price has not split yet, so adjusting the
  trailing window puts the history on a different scale from the price being traded — a
  20-day return that is wrong by the split factor, in the flattering direction.
- `known_from <= t`: a revision or cancellation that arrived later cannot reach back. That is
  ordinary F_t-measurability, and it is why the master is bitemporal rather than a table.

Ratios are exact integer pairs, never floats. A 5:4 bonus is `4 -> 9` shares, and the price
factor is 4/9 — a number that has no float representation and every reason to be exact in a
system whose prices are integer paise.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pips.data.pit.corporate_actions import (
    ActionKind,
    CorporateAction,
    CorporateActionMaster,
    UnadjustableActionError,
)
from pips.data.pit.store import PitStore

D = date
ISIN = "INE002A01018"


@pytest.fixture
def master(tmp_path: Path) -> CorporateActionMaster:
    return CorporateActionMaster(PitStore(tmp_path / "pit"))


def split(ex_date: date, before: int = 1, after: int = 2, **over: object) -> CorporateAction:
    base: dict[str, object] = {
        "action_id": f"{ISIN}-{ex_date.isoformat()}-SPLIT",
        "isin": ISIN,
        "kind": ActionKind.SPLIT,
        "ex_date": ex_date,
        "shares_before": before,
        "shares_after": after,
    }
    base.update(over)
    return CorporateAction.model_validate(base)


# ----------------------------------------------------------------- causality -----------


def test_an_action_whose_ex_date_has_not_arrived_does_not_adjust_anything(
    master: CorporateActionMaster,
) -> None:
    """Announced in June, effective in July, decision made in June.

    The donor gets this wrong: it scales every bar before the ex-date, so a May bar would be
    halved on 15 June while the 15 June price is still unsplit. The trailing window and the
    tradeable price end up on different scales, and a 20-day return is wrong by exactly the
    split factor — in the flattering direction, because the series looks like it rose.
    """
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 6, 1))
    assert master.adjustment_factor(ISIN, bar_on=D(2026, 5, 1), as_of=D(2026, 6, 15)) == 1


def test_an_action_whose_ex_date_has_passed_adjusts_earlier_bars(
    master: CorporateActionMaster,
) -> None:
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 6, 1))
    factor = master.adjustment_factor(ISIN, bar_on=D(2026, 5, 1), as_of=D(2026, 7, 15))
    assert factor == Decimal(1) / Decimal(2)


def test_a_bar_on_or_after_the_ex_date_is_not_adjusted(master: CorporateActionMaster) -> None:
    # The ex-date bar is already quoted on the new scale. Adjusting it applies the split twice.
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 6, 1))
    for day in (D(2026, 7, 1), D(2026, 7, 2)):
        assert master.adjustment_factor(ISIN, bar_on=day, as_of=D(2026, 7, 15)) == 1


def test_an_action_not_yet_known_does_not_adjust_anything(
    master: CorporateActionMaster,
) -> None:
    # F_t-measurability. The strategy running on 15 July had not heard of this yet.
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 8, 1))
    assert master.adjustment_factor(ISIN, bar_on=D(2026, 5, 1), as_of=D(2026, 7, 15)) == 1


def test_factors_compose_across_several_actions(master: CorporateActionMaster) -> None:
    master.announce(split(D(2026, 3, 1)), known_from=D(2026, 2, 1))
    master.announce(split(D(2026, 7, 1), before=4, after=9), known_from=D(2026, 6, 1))
    factor = master.adjustment_factor(ISIN, bar_on=D(2026, 1, 1), as_of=D(2026, 8, 1))
    assert factor == Decimal(1) / Decimal(2) * (Decimal(4) / Decimal(9))


def test_the_factor_is_exact_not_floating(master: CorporateActionMaster) -> None:
    # 4/9 has no float representation. Prices are integer paise; an adjustment that drifts in
    # the 15th decimal produces off-by-one-paise reconciliation failures that look like data.
    master.announce(split(D(2026, 7, 1), before=4, after=9), known_from=D(2026, 6, 1))
    factor = master.adjustment_factor(ISIN, bar_on=D(2026, 1, 1), as_of=D(2026, 8, 1))
    assert factor * 9 == 4


# ------------------------------------------------- revisions and cancellations ---------


def test_a_revision_creates_a_new_knowledge_version(master: CorporateActionMaster) -> None:
    master.announce(split(D(2026, 7, 1), after=2), known_from=D(2026, 6, 1))
    master.revise(
        f"{ISIN}-2026-07-01-SPLIT", split(D(2026, 7, 1), after=5), known_from=D(2026, 6, 20)
    )
    # As understood on 10 June, it was 1:2; as understood on 25 June, 1:5. Both are readable.
    assert master.adjustment_factor(ISIN, bar_on=D(2026, 1, 1), as_of=D(2026, 7, 10)) == Decimal(
        1
    ) / Decimal(5)
    early = master.as_of(D(2026, 6, 10))
    assert early[0].shares_after == 2


def test_a_cancelled_action_stops_adjusting_from_its_cancellation(
    master: CorporateActionMaster,
) -> None:
    """Cancellations happen, and they are the reason knowledge time is not optional.

    A run made before the cancellation used the split; a run made after does not. Both are
    correct for their own decision times, and a flat table can represent only one of them.
    """
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 6, 1))
    master.cancel(f"{ISIN}-2026-07-01-SPLIT", known_from=D(2026, 6, 25))

    assert master.adjustment_factor(ISIN, bar_on=D(2026, 1, 1), as_of=D(2026, 6, 20)) == 1
    assert master.adjustment_factor(ISIN, bar_on=D(2026, 1, 1), as_of=D(2026, 8, 1)) == 1
    # ...and after the ex-date, a run that still believed in it would have adjusted:
    assert master.adjustment_factor(ISIN, bar_on=D(2026, 1, 1), as_of=D(2026, 7, 15)) == 1, (
        "a cancelled action must not adjust, at any later decision time"
    )


# ------------------------------------------------------------- the QC hook -------------


def test_a_split_explains_the_ratio_jump_it_causes(master: CorporateActionMaster) -> None:
    """§6 M5's QC quarantines every unexplained ratio jump because nothing could explain one.

    A 1:2 split halves the price. Given the observed jump, the master says whether a known
    action accounts for it — which turns a blanket quarantine into a check that fires only on
    jumps nobody can explain.
    """
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 6, 1))
    verdict = master.explains_jump(
        ISIN, on=D(2026, 7, 1), previous_close_paise=100_000, open_paise=50_000
    )
    assert verdict.explained
    assert "SPLIT" in verdict.reason


def test_an_unexplained_jump_stays_unexplained(master: CorporateActionMaster) -> None:
    # The check must not become a rubber stamp. A halving with no action behind it is exactly
    # what QC exists to catch, and "there is a master now" must not make it disappear.
    verdict = master.explains_jump(
        ISIN, on=D(2026, 7, 1), previous_close_paise=100_000, open_paise=50_000
    )
    assert not verdict.explained
    assert "no known action" in verdict.reason


def test_a_jump_that_does_not_match_its_action_is_not_explained(
    master: CorporateActionMaster,
) -> None:
    """The subtle one. An action on the day is not a licence to accept any jump.

    A 1:2 split predicts a halving. If the price fell 90%, something else happened too, and
    accepting it because *an* action exists that day is how a real corruption gets waved
    through by the very table that was supposed to catch it.
    """
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 6, 1))
    verdict = master.explains_jump(
        ISIN, on=D(2026, 7, 1), previous_close_paise=100_000, open_paise=10_000
    )
    assert not verdict.explained
    assert "0.5" in verdict.reason and "0.1" in verdict.reason


def test_an_action_known_only_later_cannot_explain_a_jump_retroactively(
    master: CorporateActionMaster,
) -> None:
    # QC runs on the day. An action recorded a week later did not explain anything at the time,
    # and letting it do so retroactively would quietly un-quarantine historical records.
    master.announce(split(D(2026, 7, 1)), known_from=D(2026, 7, 10))
    verdict = master.explains_jump(
        ISIN,
        on=D(2026, 7, 1),
        previous_close_paise=100_000,
        open_paise=50_000,
        as_of=D(2026, 7, 1),
    )
    assert not verdict.explained


# ------------------------------------------------------------- shape ------------------


def test_a_ratio_that_destroys_shares_is_refused() -> None:
    for before, after in ((0, 2), (1, 0), (-1, 2)):
        with pytest.raises(ValueError, match="shares"):
            split(D(2026, 7, 1), before=before, after=after)


def test_an_action_must_belong_to_a_real_isin() -> None:
    with pytest.raises(ValueError, match="ISIN"):
        split(D(2026, 7, 1), isin="NOTANISIN")


def test_an_action_kind_that_cannot_be_adjusted_refuses_loudly(
    master: CorporateActionMaster,
) -> None:
    """A cash dividend has no share ratio, so it has no exact price factor.

    Returning 1 for it would be the donor's mistake in a new place: the series silently keeps
    a discontinuity at the ex-date, and every feature computed across it is wrong with nothing
    to show for it. Whether to adjust for dividends at all is a PRICE-RETURN vs TOTAL-RETURN
    decision this project has not made, and defaulting it by accident is how such decisions
    get made. So it raises, and says which decision is missing.
    """
    master.announce(
        CorporateAction.model_validate(
            {
                "action_id": f"{ISIN}-2026-07-01-DIV",
                "isin": ISIN,
                "kind": ActionKind.DIVIDEND,
                "ex_date": D(2026, 7, 1),
                "dividend_paise": 1_200,
            }
        ),
        known_from=D(2026, 6, 1),
    )
    with pytest.raises(UnadjustableActionError, match="TOTAL-RETURN"):
        master.adjustment_factor(ISIN, bar_on=D(2026, 1, 1), as_of=D(2026, 8, 1))


def test_an_unadjustable_action_still_records_and_still_reads(
    master: CorporateActionMaster,
) -> None:
    # Refusing to ADJUST for it must not mean refusing to KNOW about it. The record is
    # evidence; the adjustment is a calculation we decline to guess at.
    master.announce(
        CorporateAction.model_validate(
            {
                "action_id": f"{ISIN}-2026-07-01-DIV",
                "isin": ISIN,
                "kind": ActionKind.DIVIDEND,
                "ex_date": D(2026, 7, 1),
                "dividend_paise": 1_200,
            }
        ),
        known_from=D(2026, 6, 1),
    )
    recorded = master.as_of(D(2026, 6, 15))
    assert [a.kind for a in recorded] == [ActionKind.DIVIDEND]
    assert recorded[0].dividend_paise == 1_200
