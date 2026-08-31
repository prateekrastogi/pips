"""Data quality control and quarantine (§6 M5, §3.4).

Every check here is written against a **seeded corrupt fixture** — the §6 Verify asks for
exactly that, because a QC suite that has only ever seen good data is a suite nobody knows
works.

The hardest judgement in this module is not detecting corruption. It is deciding what
"missing" means. The M3 probe established that Breeze OMITS untraded minutes rather than
zero-filling them, so absence is the normal case and a naive gap check would flag every
liquid-name session in the archive. What distinguishes a real gap is corroboration: the
manifest says the fetch succeeded, so a run of absent minutes in a name that trades every
minute is a different claim from one absent minute in a thin one.
"""

from __future__ import annotations

from datetime import date, time

from pips.data.breeze.ingest import NormalizedBar
from pips.data.pit.corporate_actions import JumpVerdict
from pips.data.qc.checks import (
    Finding,
    Severity,
    check_bar_sanity,
    check_decimal_shift,
    check_monotonic_labels,
    check_session_coverage,
    check_spikes,
    check_unexplained_ratio_jump,
)

DAY = date(2026, 8, 28)


def bar(minute: int, o: int, h: int, low: int, c: int, volume: int = 100) -> NormalizedBar:
    return NormalizedBar(
        trade_date=DAY,
        close_label=time(9, 15 + minute) if minute < 45 else time(10, minute - 45),
        open_paise=o,
        high_paise=h,
        low_paise=low,
        close_paise=c,
        volume=volume,
    )


def good(n: int = 30) -> list[NormalizedBar]:
    return [bar(i, 100_00 + i, 100_50 + i, 99_50 + i, 100_10 + i) for i in range(n)]


# ------------------------------------------------------------------ OHLC sanity ---------


def test_a_clean_session_produces_no_findings() -> None:
    # The control. Without it every other test here could pass by flagging everything.
    assert check_bar_sanity(good()) == []


def test_a_high_below_the_open_is_caught() -> None:
    bars = good()
    bars[5] = bar(5, o=100_00, h=99_00, low=98_00, c=98_50)
    findings = check_bar_sanity(bars)
    assert len(findings) == 1
    assert findings[0].severity is Severity.QUARANTINE
    assert "high" in findings[0].detail.lower()


def test_a_low_above_the_close_is_caught() -> None:
    bars = good()
    bars[7] = bar(7, o=100_00, h=101_00, low=100_90, c=100_50)
    assert check_bar_sanity(bars)[0].severity is Severity.QUARANTINE


def test_a_non_positive_price_is_caught() -> None:
    bars = good()
    bars[3] = bar(3, o=0, h=0, low=0, c=0)
    assert check_bar_sanity(bars)


def test_a_negative_volume_is_caught() -> None:
    bars = good()
    bars[2] = bar(2, 100_00, 100_50, 99_50, 100_10, volume=-1)
    assert check_bar_sanity(bars)


def test_zero_volume_is_not_an_error() -> None:
    # §3.4: "a zero-volume bar is not a missing bar". A traded-but-flat minute is legitimate
    # data, and flagging it would quarantine exactly the quiet periods worth studying.
    bars = good()
    bars[4] = bar(4, 100_00, 100_00, 100_00, 100_00, volume=0)
    assert check_bar_sanity(bars) == []


# ------------------------------------------------------------------ ordering ------------


def test_out_of_order_labels_are_caught() -> None:
    bars = good()
    bars[10], bars[11] = bars[11], bars[10]
    assert check_monotonic_labels(bars)


def test_a_duplicate_label_is_caught() -> None:
    bars = good()
    bars[12] = bars[11]
    findings = check_monotonic_labels(bars)
    assert findings and "duplicate" in findings[0].detail.lower()


# ------------------------------------------------- coverage, which is the subtle one ----


def test_a_sparse_session_is_not_flagged_by_itself() -> None:
    # The probe found untraded minutes are OMITTED. A few absent minutes is the normal case
    # for anything but the most liquid names, and flagging it would bury real findings.
    bars = [b for i, b in enumerate(good(30)) if i not in (5, 17)]
    assert check_session_coverage(bars, expected_minutes=30, fetch_succeeded=True) == []


def test_a_mostly_empty_session_is_flagged_even_though_absence_is_normal() -> None:
    # Two bars where thirty were expected is not thin trading, it is a truncated response.
    findings = check_session_coverage(good(2), expected_minutes=30, fetch_succeeded=True)
    assert findings and findings[0].severity is Severity.QUARANTINE


def test_an_empty_session_whose_fetch_did_not_succeed_is_a_different_finding() -> None:
    # The manifest knows whether we ever got an answer. "No data because we never fetched"
    # and "no data because nothing traded" look identical in the archive and are not the
    # same claim — the second is evidence, the first is a hole.
    findings = check_session_coverage([], expected_minutes=30, fetch_succeeded=False)
    assert findings and "not fetched" in findings[0].detail.lower()


# ------------------------------------------------------------------ spikes --------------


def test_an_implausible_jump_is_flagged() -> None:
    bars = good()
    bars[15] = bar(15, 100_00, 500_00, 99_00, 480_00)
    assert check_spikes(bars, max_move_bps=500)


def test_ordinary_movement_is_not_flagged() -> None:
    assert check_spikes(good(), max_move_bps=500) == []


# --------------------------------------------- decimal shifts, the classic vendor bug ---


def test_a_decimal_shift_is_caught_and_named_as_one() -> None:
    # A price 10x off that returns to trend is the classic vendor decimal error. Flagged as a
    # spike it looks like a market event; naming it lets the fix be a correction rather than a
    # deletion.
    bars = good()
    bars[20] = bar(20, 1000_00, 1005_00, 995_00, 1001_00)
    findings = check_decimal_shift(bars)
    assert findings and "decimal" in findings[0].detail.lower()
    assert findings[0].severity is Severity.QUARANTINE


def test_a_genuine_sustained_move_is_not_called_a_decimal_shift() -> None:
    # The discriminator is the RETURN. A price that steps up and stays there is a market
    # event, however large; only a jump that reverts looks like a misplaced decimal point.
    bars = good(20) + [
        bar(i, 1000_00 + i, 1005_00 + i, 995_00 + i, 1001_00 + i) for i in range(20, 30)
    ]
    assert check_decimal_shift(bars) == []


# ------------------------------------- corporate actions, now that the M6 master exists ---


def test_an_unexplained_overnight_ratio_jump_is_quarantined_not_adjusted() -> None:
    # A 1:2 split halves the price overnight. If nothing can explain it we cannot tell a split
    # from bad data — so it is quarantined rather than silently adjusted or silently accepted.
    # Adjusting on a guess would corrupt every return that crosses the date.
    findings = check_unexplained_ratio_jump(
        previous_close_paise=200_00,
        first_open_paise=100_00,
        verdict=JumpVerdict(False, "no known action"),
    )
    assert findings and findings[0].severity is Severity.QUARANTINE
    assert "corporate action" in findings[0].detail.lower()


def test_a_matching_corporate_action_explains_the_jump() -> None:
    findings = check_unexplained_ratio_jump(
        previous_close_paise=200_00,
        first_open_paise=100_00,
        verdict=JumpVerdict(True, "SPLIT on 2026-07-01 predicts 0.5000; observed 0.5000"),
    )
    assert findings == []


def test_an_action_on_the_day_is_not_a_licence_to_accept_any_jump() -> None:
    """The defect this rewiring fixes.

    The check used to take a list of declared actions and return `[]` if the list was
    non-empty — so ANY action on the day cleared ANY jump. A 1:2 split sat next to a 90%
    collapse and the collapse was waved through by the very table meant to catch it. The
    master now answers whether the action accounts for THIS jump, and a mismatch quarantines.
    """
    findings = check_unexplained_ratio_jump(
        previous_close_paise=200_00,
        first_open_paise=20_00,
        verdict=JumpVerdict(False, "SPLIT predicts 0.5000 but observed 0.1000"),
    )
    assert findings and findings[0].severity is Severity.QUARANTINE
    assert "0.5000" in findings[0].detail, "the finding must carry the master's reasoning"


def test_no_verdict_at_all_fails_closed() -> None:
    # A caller that never consulted the master must not thereby pass. Absence of an answer is
    # not an answer — the same rule the WS gap record follows with `messages_missed: null`.
    findings = check_unexplained_ratio_jump(
        previous_close_paise=200_00, first_open_paise=100_00, verdict=None
    )
    assert findings and findings[0].severity is Severity.QUARANTINE
    assert "not consulted" in findings[0].detail


def test_an_ordinary_overnight_gap_is_not_a_ratio_jump() -> None:
    assert check_unexplained_ratio_jump(200_00, 196_00, verdict=None) == []


def test_a_finding_carries_enough_to_act_on() -> None:
    finding = check_bar_sanity([bar(0, 100_00, 99_00, 98_00, 98_50)])[0]
    assert isinstance(finding, Finding)
    assert finding.check and finding.detail and finding.severity
