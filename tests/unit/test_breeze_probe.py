"""Bar-labelling inference for the Breeze probe [C-BAR-01] (§3.5, §6 M3, ADR-0001).

§3.5: "Empirically verify Breeze's own labeling convention in M4 and normalize on ingest."

**Counting candles cannot answer this, and the first version of these tests assumed it could.**
Live data settled it: a full NSE session returned 370 candles, not 375, because minutes with no
trades are OMITTED rather than zero-filled; other days returned 376. Endpoints were no better —
15:30 is present on some days and absent on others, so it is a traded minute, not a structural
boundary.

The discriminator that works is a price identity: the day's OPEN belongs to exactly one
one-minute bar, and that bar's LABEL tells you the convention. If it is stamped with the
session open, labels mark a bar's start; if stamped one interval later, they mark its end.

It matters because pips labels by CLOSE and treats a bar as usable at or after its label. Get
this wrong and every bar is usable one interval too early — a one-bar lookahead applied
uniformly to every backtest, leaving no trace in any result.
"""

from __future__ import annotations

from datetime import time

import pytest

from pips.data.breeze.probe import BarLabelling, infer_bar_labelling

OPEN = time(9, 15)


def test_a_first_bar_stamped_with_the_session_open_is_open_labelled() -> None:
    # The observed Breeze case: the bar carrying the day's opening price is stamped 09:15.
    assert (
        infer_bar_labelling(first_bar_label=time(9, 15), session_open=OPEN, carries_day_open=True)
        is BarLabelling.OPEN_LABELLED
    )


def test_a_first_bar_stamped_one_interval_later_is_close_labelled() -> None:
    assert (
        infer_bar_labelling(first_bar_label=time(9, 16), session_open=OPEN, carries_day_open=True)
        is BarLabelling.CLOSE_LABELLED
    )


def test_without_the_price_identity_the_answer_is_ambiguous() -> None:
    # If we cannot confirm which bar carries the day's open, its label proves nothing — the
    # bar might be a pre-open print, and a widened window does return those.
    assert (
        infer_bar_labelling(first_bar_label=time(9, 15), session_open=OPEN, carries_day_open=False)
        is BarLabelling.AMBIGUOUS
    )


def test_an_unexpected_label_is_ambiguous_rather_than_rounded_to_the_nearer_answer() -> None:
    assert (
        infer_bar_labelling(first_bar_label=time(9, 20), session_open=OPEN, carries_day_open=True)
        is BarLabelling.AMBIGUOUS
    )


@pytest.mark.parametrize(
    ("labelling", "shift"),
    [(BarLabelling.OPEN_LABELLED, 1), (BarLabelling.CLOSE_LABELLED, 0)],
)
def test_the_normalization_shift_follows_from_the_labelling(
    labelling: BarLabelling, shift: int
) -> None:
    assert labelling.intervals_to_add == shift


def test_ambiguous_refuses_to_supply_a_shift() -> None:
    # Zero is a decision — that the vendor is already close-labelled — and making it by
    # default is how an unverified convention becomes a silent lookahead.
    with pytest.raises(ValueError, match="ambiguous"):
        _ = BarLabelling.AMBIGUOUS.intervals_to_add


def test_the_probed_breeze_convention_is_pinned() -> None:
    """What the live probe found on 2026-08-28, pinned so a later change is visible.

    Day open 1285.4 == the 09:15 bar's open; day close 1287.0 == the 15:29 bar's close. So
    Breeze stamps a bar with the minute it STARTS, and ingest must add one interval to make it
    close-labelled. If this ever changes, the normalizer is wrong and every bar shifts.
    """
    from pips.data.breeze.probe import BREEZE_BAR_LABELLING

    assert BREEZE_BAR_LABELLING is BarLabelling.OPEN_LABELLED
    assert BREEZE_BAR_LABELLING.intervals_to_add == 1
