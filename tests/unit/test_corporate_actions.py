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


# --------------------------------------------------------- found by mutation sweep ---

OTHER_ISIN = "INE467B01029"


def test_one_names_split_does_not_adjust_another_names_bars(
    master: CorporateActionMaster,
) -> None:
    """The `isin` filter, which nothing exercised because nothing put two names in the store.

    A single-name fixture cannot tell a filter from its absence. On a real master — 5,851
    names, actions most days — dropping it would apply every split in the market to every
    symbol's history, silently and multiplicatively.
    """
    master.announce(split(date(2026, 2, 1)), known_from=date(2026, 1, 1))
    assert master.adjustment_factor(ISIN, date(2026, 1, 15), date(2026, 3, 1)) == Decimal("0.5")
    assert master.adjustment_factor(OTHER_ISIN, date(2026, 1, 15), date(2026, 3, 1)) == Decimal(1)


def test_a_jump_is_explained_only_by_that_names_own_action(
    master: CorporateActionMaster,
) -> None:
    """Same gap, on the QC hook — and here it un-quarantines rather than corrupts.

    A verdict of "explained" clears a record from quarantine. Explaining one name's jump with
    another name's split is how a real corruption gets waved through by the very table that
    exists to catch it.
    """
    master.announce(
        split(date(2026, 2, 2), isin=OTHER_ISIN, action_id="OTHER-SPLIT"),
        known_from=date(2026, 1, 1),
    )
    verdict = master.explains_jump(ISIN, date(2026, 2, 2), 100_00, 50_00)
    assert not verdict.explained
    assert "no known action" in verdict.reason


def test_a_jump_is_explained_only_by_an_action_on_that_day(
    master: CorporateActionMaster,
) -> None:
    """`ex_date == on`, not merely "this name has actions".

    A split effective next month is known now and explains nothing now. Without the date
    filter it would clear today's unrelated 50% collapse.
    """
    master.announce(split(date(2026, 3, 10)), known_from=date(2026, 1, 1))
    verdict = master.explains_jump(ISIN, date(2026, 2, 2), 100_00, 50_00, as_of=date(2026, 2, 2))
    assert not verdict.explained
    assert "no known action" in verdict.reason


def test_the_jump_tolerance_scales_with_the_ratio_it_is_checking(
    master: CorporateActionMaster,
) -> None:
    """10% OF THE PREDICTED FACTOR, not 10 percentage points of raw ratio.

    At a 1:10 split the factor is 0.1 and the window is +/-0.01; unscaled it would be +/-0.10,
    which spans the entire distance from the predicted ratio to no split at all. The action
    would then explain a name that simply collapsed 90% on its ex-date, which is precisely the
    coincidence this check exists to refuse.
    """
    master.announce(split(date(2026, 2, 2), before=1, after=10), known_from=date(2026, 1, 1))
    near = master.explains_jump(ISIN, date(2026, 2, 2), 100_00, 10_50)
    assert near.explained, f"0.105 is within 10% of 0.1: {near.reason}"
    far = master.explains_jump(ISIN, date(2026, 2, 2), 100_00, 15_00)
    assert not far.explained, f"0.15 is not: {far.reason}"


def test_two_actions_on_one_ex_date_compose_in_the_verdict(
    master: CorporateActionMaster,
) -> None:
    """A split and a bonus on the same day are one combined factor, not the last one seen.

    `adjustment_factor` composes and is tested; the QC hook computes its own `expected` and
    was not. Taking only one of the two predicts the wrong ratio, so a correctly-behaving
    price gets quarantined and the operator learns to distrust the check.
    """
    master.announce(split(date(2026, 2, 2), before=1, after=2), known_from=date(2026, 1, 1))
    master.announce(
        split(date(2026, 2, 2), before=1, after=5, action_id=f"{ISIN}-second"),
        known_from=date(2026, 1, 1),
    )
    verdict = master.explains_jump(ISIN, date(2026, 2, 2), 100_00, 10_00)
    assert verdict.explained, f"1/2 x 1/5 = 0.1, and 10.00/100.00 is 0.1: {verdict.reason}"
    assert "0.1000" in verdict.reason


def test_a_non_positive_previous_close_has_no_ratio_to_explain(
    master: CorporateActionMaster,
) -> None:
    """The guard is load-bearing: without it this is a DivisionByZero out of a QC hook.

    Same shape as `check_decimal_shift`'s missing `current` guard — a zero price, which is the
    most basic corruption there is, taking down the machinery meant to report it.
    """
    master.announce(split(date(2026, 2, 2)), known_from=date(2026, 1, 1))
    verdict = master.explains_jump(ISIN, date(2026, 2, 2), 0, 50_00)
    assert not verdict.explained
    assert "not positive" in verdict.reason


def test_a_dividend_on_the_day_does_not_explain_the_jump(master: CorporateActionMaster) -> None:
    """It says so, rather than raising out of the QC hook.

    A DIVIDEND has no exact price factor from a share ratio, and whether to adjust for it is a
    price-return vs total-return decision this project has deliberately not made. So
    `price_factor` refuses — correctly — and the guard here is what turns that refusal into a
    verdict instead of an `UnadjustableActionError` thrown from inside a QC pass, which would
    take the run down and lose every finding collected before it.

    The verdict is "not explained", which quarantines the record: the honest answer while the
    decision is unmade, and a quarantined bar is recoverable where a wrongly-cleared one is not.
    """
    master.announce(
        split(
            date(2026, 2, 2),
            kind=ActionKind.DIVIDEND,
            action_id=f"{ISIN}-DIV",
            shares_after=1,
        ),
        known_from=date(2026, 1, 1),
    )
    verdict = master.explains_jump(ISIN, date(2026, 2, 2), 100_00, 98_00)
    assert not verdict.explained
    assert "no exact price factor" in verdict.reason
