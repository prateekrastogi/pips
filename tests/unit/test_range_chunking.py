"""Splitting a range into calls that cannot be truncated (§6 M4).

The 2026-09-03 probe measured the limit: Breeze caps a reply at 1,000 candles and drops the
**oldest** bars to fit, under Status 200 with no Error. `[C-M4-02]` refuses a reply that comes
back at the cap, which is correct and leaves the ranged shape unusable for anything finer than
daily. Chunking is what makes it usable: split the range so no single call can reach the cap.

The counting is deliberately an OVER-estimate. Weekends are free, holidays are not subtracted
(the list is unverified, and `holidays_verified` is an open M6 item), and Breeze omits untraded
bars -- so a chunk is planned for more candles than it can possibly return. Every one of those
errs toward a smaller chunk, which costs an extra call and never loses a bar. The opposite
error is silent: a chunk that reaches the cap loses the beginning of the period it asked for
and reports success.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

import pytest

from pips.data.breeze.campaign import (
    CANDLES_PER_CALL,
    CampaignPlan,
    RangeTooFineError,
    chunk_range,
)

MINUTE_SESSION = 375  # candles one session yields at 1m


def weekdays(first: date, last: date) -> int:
    """Counted here rather than taken from the chunker, so the invariant is checked against an
    independent count rather than a restatement of the implementation."""
    total, day = 0, first
    while day <= last:
        total += day.weekday() < 5
        day += timedelta(days=1)
    return total


def test_a_range_that_fits_one_call_is_not_split() -> None:
    """Splitting a range that already fits doubles its cost for nothing, and the seeding plan
    is priced per call."""
    chunks = chunk_range(date(2026, 9, 1), date(2026, 9, 2), "1minute")

    assert chunks == [(date(2026, 9, 1), date(2026, 9, 2))]


def test_three_years_of_daily_bars_is_still_one_call() -> None:
    """What the probe measured: 742 candles for three years, in one call.

    The chunker counts 782 weekdays rather than 742 sessions, because the holiday list is
    unverified -- an over-count, and still under the cap. If this ever splits, the daily seed
    silently doubles in price.
    """
    start, end = date(2023, 9, 4), date(2026, 9, 3)
    chunks = chunk_range(start, end, "1day")

    assert chunks == [(start, end)]


def test_no_chunk_can_reach_the_cap() -> None:
    """The invariant the whole function exists for, checked against an independent weekday
    count over a three-year range at 1-minute."""
    start, end = date(2023, 9, 4), date(2026, 9, 3)

    for first, last in chunk_range(start, end, "1minute"):
        assert weekdays(first, last) * MINUTE_SESSION <= CANDLES_PER_CALL


def test_the_chunks_cover_the_range_exactly() -> None:
    """No gap and no overlap.

    A gap loses days that nothing would report missing -- the manifest would mark every chunk
    fetched and the archive would be short. An overlap fetches the same days twice and pays
    for them twice, on a budget measured in quota-days.
    """
    start, end = date(2023, 9, 4), date(2026, 9, 3)
    chunks = chunk_range(start, end, "1minute")

    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    for (_, previous_end), (next_start, _) in pairwise(chunks):
        assert next_start == previous_end + timedelta(days=1)
    for first, last in chunks:
        assert first <= last


def test_a_weekend_inside_a_chunk_costs_nothing() -> None:
    """The property that separates counting weekdays from counting calendar days.

    Sep 3-6 2026 is Thu, Fri, Sat, Sun: four days but two sessions, which is why it fits beside
    a neighbour where a calendar-day count would have split it. Over three years, counting
    calendar days would buy about 40% more calls than the data needs.
    """
    chunks = chunk_range(date(2026, 9, 1), date(2026, 9, 14), "1minute")

    assert chunks == [
        (date(2026, 9, 1), date(2026, 9, 2)),
        (date(2026, 9, 3), date(2026, 9, 6)),  # Thu, Fri + a free weekend
        (date(2026, 9, 7), date(2026, 9, 8)),
        (date(2026, 9, 9), date(2026, 9, 10)),
        (date(2026, 9, 11), date(2026, 9, 14)),  # Fri + weekend + Mon
    ]


def test_an_interval_whose_single_session_exceeds_a_call_is_refused() -> None:
    """One second yields 22,500 candles a session, so no arrangement of whole days fits.

    Refused rather than chunked to one day, because a one-day chunk at 1s would come back at
    the cap and lose the morning -- the exact failure `[C-M4-02]` refuses. The ranged shape
    does not exist at this interval; the per-symbol-day campaign is what serves it, and saying
    so is the honest answer.
    """
    with pytest.raises(ValueError, match="1second") as caught:
        chunk_range(date(2026, 9, 1), date(2026, 9, 30), "1second")

    assert "22500" in str(caught.value), "the message names the number that does not fit"


def test_a_single_day_is_one_chunk() -> None:
    assert chunk_range(date(2026, 9, 1), date(2026, 9, 1), "1minute") == [
        (date(2026, 9, 1), date(2026, 9, 1))
    ]


def test_a_backwards_range_is_refused() -> None:
    """Two dates are one typo apart, and a silently empty chunk list would fetch nothing while
    the manifest recorded a completed range."""
    with pytest.raises(ValueError, match="before"):
        chunk_range(date(2026, 9, 30), date(2026, 9, 1), "1minute")


def test_an_unsupported_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="2minute"):
        chunk_range(date(2026, 9, 1), date(2026, 9, 30), "2minute")


def test_a_range_of_pure_weekend_is_one_chunk() -> None:
    """No sessions at all is not an error -- it is a range with nothing in it, and the fetcher
    will report EMPTY. Splitting it, or refusing it, would both be inventing a problem."""
    assert chunk_range(date(2026, 9, 5), date(2026, 9, 6), "1minute") == [
        (date(2026, 9, 5), date(2026, 9, 6))
    ]


def plan(interval: str) -> CampaignPlan:
    """U300 over three years, the seeding campaign as planned."""
    start, end = date(2023, 9, 4), date(2026, 9, 3)
    days = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]
    return CampaignPlan(symbols=[f"SYM{i:04d}" for i in range(300)], days=days, interval=interval)


def test_the_chunked_cost_is_what_the_code_will_actually_spend() -> None:
    """Three figures, and they are three different questions.

    `estimated_calls` is the per-symbol-day toll this code pays today. `estimated_calls_if_
    ranged` is what the VENDOR would allow, packing 1,000 candles into every call -- which needs
    windows that end mid-session, and the bronze layout is keyed per day. Between them sits what
    day-aligned chunking actually costs, and that is the number a seeding decision needs.

    The gap matters: the ranged figure understates the real chunked cost by a third, and this
    same estimate has been written down wrong twice already.
    """
    minute = plan("1minute")

    assert minute.estimated_calls == 235_200, "per symbol-day"
    assert minute.estimated_calls_if_chunked == 117_600, "day-aligned ranges"
    assert minute.estimated_calls_if_ranged == 88_200, "the vendor's allowance, candle-packed"
    assert (
        minute.estimated_calls_if_ranged
        < minute.estimated_calls_if_chunked
        < minute.estimated_calls
    ), "day boundaries cost something, and chunking still halves the bill"


def test_chunking_the_daily_seed_costs_one_call_per_symbol() -> None:
    """What the probe measured, priced: 300 symbols, three years of daily bars, 300 calls."""
    assert plan("1day").estimated_calls_if_chunked == 300


def test_an_interval_with_no_ranged_shape_reports_none_rather_than_a_number() -> None:
    """One second has no arrangement of whole days that fits a call.

    None rather than a number, because every number here would be a claim that some ranged
    fetch is possible -- and a plan that quotes a price for a shape that does not exist is how
    the seeding estimate went wrong the first time.
    """
    assert plan("1second").estimated_calls_if_chunked is None


def test_a_bad_interval_still_raises_rather_than_reporting_no_ranged_shape() -> None:
    """ "No arrangement of whole days fits" and "that is not an interval" are different facts.

    Catching every `ValueError` to mean the first would report a typo'd interval as a costed
    decision -- the plan would say the ranged shape does not exist, the campaign would fall
    back to per-symbol-day, and the typo would never surface. So the too-fine refusal has its
    own type and everything else propagates.
    """
    days = [date(2026, 9, 1), date(2026, 9, 2)]
    bad = CampaignPlan(symbols=["RELIND"], days=days, interval="2minute")

    with pytest.raises(ValueError, match="2minute"):
        _ = bad.estimated_calls_if_chunked


def test_the_too_fine_refusal_is_its_own_type() -> None:
    """So a caller can tell the one recoverable case from every other bad argument."""
    with pytest.raises(RangeTooFineError):
        chunk_range(date(2026, 9, 1), date(2026, 9, 2), "1second")

    assert issubclass(RangeTooFineError, ValueError), "still a ValueError for existing callers"


def test_a_chunk_is_planned_strictly_below_the_cap_because_the_cap_itself_is_refused() -> None:
    """The two halves must agree on what "too big" means.

    `run_range_backfill` treats a reply of exactly `candles_per_call` rows as probably
    truncated and refuses it -- there is no way to tell a full call from a clipped one. A
    chunker that planned up to and including the cap would therefore build ranges the fetcher
    rejects: the campaign would price a seed it cannot run, and the failure would arrive one
    call into a three-year backfill.

    Two 1-minute sessions are 750 candles, so with a 750-candle cap they must be split.
    """
    chunks = chunk_range(date(2026, 9, 1), date(2026, 9, 4), "1minute", candles_per_call=750)

    assert chunks == [
        (date(2026, 9, 1), date(2026, 9, 1)),
        (date(2026, 9, 2), date(2026, 9, 2)),
        (date(2026, 9, 3), date(2026, 9, 3)),
        (date(2026, 9, 4), date(2026, 9, 4)),
    ]


def test_an_interval_whose_session_exactly_fills_a_call_has_no_ranged_shape() -> None:
    """Same rule at the other end: a single day at exactly the cap comes back at the cap, and
    a reply at the cap is refused. One day is the smallest range, so there is nothing left to
    split and the ranged shape does not exist."""
    with pytest.raises(RangeTooFineError, match="375"):
        chunk_range(date(2026, 9, 1), date(2026, 9, 30), "1minute", candles_per_call=375)


def test_a_campaign_with_no_days_costs_no_calls() -> None:
    """Zero, not one per symbol. A plan that quotes 300 calls for an empty range is a plan
    somebody budgets for."""
    empty = CampaignPlan(symbols=[f"SYM{i}" for i in range(300)], days=[], interval="1minute")

    assert empty.estimated_calls_if_chunked == 0
    assert empty.estimated_calls == 0
