"""Bar-labelling inference for the Breeze probe [C-BAR-01] (§3.5, §6 M3, ADR-0001).

§3.5: "Empirically verify Breeze's own labeling convention in M4 and normalize on ingest."
The *decision* — is a returned candle labelled by its open or its close? — is pure logic over
what the vendor returned, so it is tested here. Only the fetch is I/O.

This matters more than it looks. pips labels bars by CLOSE and treats them as usable at or
after the label. If Breeze labels by OPEN and we ingest without normalizing, every bar is
usable one interval too early — a one-bar lookahead applied uniformly to every backtest, and
the most flattering bug available.
"""

from __future__ import annotations

from datetime import time

import pytest

from pips.data.breeze.probe import BarLabelling, infer_bar_labelling

OPEN = time(9, 15)
CLOSE = time(15, 30)


def test_first_candle_at_the_session_open_means_open_labelled() -> None:
    # 09:15 .. 15:29, 375 candles: each bar carries the timestamp it STARTED at.
    assert (
        infer_bar_labelling(time(9, 15), time(15, 29), 375, OPEN, CLOSE)
        is BarLabelling.OPEN_LABELLED
    )


def test_first_candle_one_interval_after_the_open_means_close_labelled() -> None:
    # 09:16 .. 15:30, 375 candles: each bar carries the timestamp it ENDED at.
    assert (
        infer_bar_labelling(time(9, 16), time(15, 30), 375, OPEN, CLOSE)
        is BarLabelling.CLOSE_LABELLED
    )


def test_an_ambiguous_shape_is_reported_as_ambiguous_not_guessed() -> None:
    # A partial session, a halt, or an unexpected count must not be resolved by picking the
    # likelier answer. Guessing here produces a silent one-bar lookahead in every backtest.
    assert (
        infer_bar_labelling(time(9, 20), time(15, 10), 200, OPEN, CLOSE) is BarLabelling.AMBIGUOUS
    )


def test_a_count_that_contradicts_the_endpoints_is_ambiguous() -> None:
    # Endpoints say open-labelled but the count says otherwise: the two disagree, so neither
    # is trusted.
    assert (
        infer_bar_labelling(time(9, 15), time(15, 29), 300, OPEN, CLOSE) is BarLabelling.AMBIGUOUS
    )


def test_an_empty_response_is_ambiguous_rather_than_a_default() -> None:
    assert infer_bar_labelling(None, None, 0, OPEN, CLOSE) is BarLabelling.AMBIGUOUS


@pytest.mark.parametrize(
    ("labelling", "shift"),
    [(BarLabelling.OPEN_LABELLED, 1), (BarLabelling.CLOSE_LABELLED, 0)],
)
def test_the_normalization_shift_follows_from_the_labelling(
    labelling: BarLabelling, shift: int
) -> None:
    # An open-labelled vendor bar must be shifted forward one interval to become a
    # close-labelled pips bar. A close-labelled one is already correct.
    assert labelling.intervals_to_add == shift


def test_ambiguous_has_no_shift_and_says_so() -> None:
    # Asking for a shift we cannot justify must raise, not return zero — zero is a decision.
    with pytest.raises(ValueError, match="ambiguous"):
        _ = BarLabelling.AMBIGUOUS.intervals_to_add
