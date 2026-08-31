"""Adversarial battery against the as-of panel view (constitution rule 2).

Causality is measurability. These tests do not check that the view *usually* behaves; they
attack it the way a leaky research idea would — by shifting, joining, resampling, reindexing
and asking for fields that only exist once the day is over. Every one of them must be
refused by the view itself, not by a reviewer noticing.
"""

from __future__ import annotations

import polars as pl
import pytest

from pips.core.asof import AsOfPanelView, CausalityViolationError

NS = 1_000_000_000


def panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "close_ts_ns": [10 * NS, 20 * NS, 30 * NS, 40 * NS],
            "symbol": ["A", "A", "A", "A"],
            "close_paise": [100, 110, 120, 130],
            "volume": [10, 20, 30, 40],
            "day_vwap_paise": [115, 115, 115, 115],  # full-day: unknowable intraday
            "smoothed_regime_p": [0.1, 0.2, 0.3, 0.4],  # P(S_t | F_T), T>t
        }
    )


def view(decision_s: int = 30) -> AsOfPanelView:
    return AsOfPanelView(panel(), decision_ts=decision_s * NS)


def test_rows_after_the_decision_are_not_present() -> None:
    assert view(20).visible().height == 2


def test_the_bar_labelled_exactly_at_the_decision_is_visible() -> None:
    # Bars are close-labelled and usable AT or after their label [C-BAR-01].
    latest = view(20).max_source_ts()
    assert latest is not None
    assert latest == 20 * NS


def test_max_source_ts_never_exceeds_the_decision() -> None:
    v = view(30)
    latest = v.max_source_ts()
    assert latest is not None
    assert latest <= v.decision_ts


def test_column_access_is_recorded_for_audit() -> None:
    v = view()
    v.column("close_paise")
    v.column("volume")
    assert v.accessed_fields == {"close_paise", "volume"}


def test_full_day_fields_are_refused_by_the_feature_api() -> None:
    # "Full-day VWAP/volume used intraday is banned by the feature API" (rule 2).
    with pytest.raises(CausalityViolationError, match="full-day"):
        view().column("day_vwap_paise")


def test_smoothed_state_probabilities_are_refused() -> None:
    # "Smoothed state probabilities P(S_t | F_T), T>t are banned from anything that trades
    # or tunes" (rule 2).
    with pytest.raises(CausalityViolationError, match="smoothed"):
        view().column("smoothed_regime_p")


def test_a_banned_field_is_refused_even_when_the_whole_frame_is_requested() -> None:
    # The obvious bypass: skip .column() and take the frame. visible() must already be clean.
    assert "day_vwap_paise" not in view().visible().columns
    assert "smoothed_regime_p" not in view().visible().columns


def test_negative_shift_lookahead_is_refused() -> None:
    # shift(-1) is the single most common leak: "tomorrow's close, today".
    with pytest.raises(CausalityViolationError, match="forward"):
        view().shifted("close_paise", -1)


def test_positive_shift_is_allowed_and_is_the_lagged_value() -> None:
    lagged = view().shifted("close_paise", 1)
    assert lagged.to_list() == [None, 100, 110]


def test_a_trailing_window_never_reaches_past_the_decision() -> None:
    w = view(20).trailing("close_paise", 5)
    assert w.to_list() == [100, 110]


def test_joining_a_future_labelled_frame_is_refused() -> None:
    future = pl.DataFrame({"close_ts_ns": [50 * NS], "extra": [1]})
    with pytest.raises(CausalityViolationError, match="source_ts"):
        view().join_asof_safe(future, on="close_ts_ns")


def test_joining_a_past_labelled_frame_is_allowed() -> None:
    past = pl.DataFrame({"close_ts_ns": [10 * NS, 20 * NS], "extra": [1, 2]})
    assert view().join_asof_safe(past, on="close_ts_ns").height == 2


def test_a_frame_whose_own_rows_postdate_the_decision_cannot_be_wrapped_unchecked() -> None:
    v = AsOfPanelView(panel(), decision_ts=25 * NS)
    assert v.visible()["close_ts_ns"].to_list() == [10 * NS, 20 * NS]


def test_earliest_fill_is_strictly_after_the_decision_plus_latency() -> None:
    # "A signal computed on completed bar t may not fill within bar t; earliest fill is the
    # next executable event after decision + modeled latency."
    v = view(30)
    fill = v.earliest_fill_ts(latency_ns=2 * NS)
    assert fill > v.decision_ts
    assert fill >= v.decision_ts + 2 * NS


def test_requiring_measurability_rejects_a_future_stamp() -> None:
    with pytest.raises(CausalityViolationError, match="source_ts"):
        view(20).require_measurable(21 * NS, "some feature")


def test_an_empty_visible_window_is_not_an_error_but_has_no_max() -> None:
    v = AsOfPanelView(panel(), decision_ts=0)
    assert v.visible().height == 0
    assert v.max_source_ts() is None


def test_a_missing_timestamp_column_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="close_ts_ns"):
        AsOfPanelView(pl.DataFrame({"x": [1]}), decision_ts=NS)


def test_the_audit_reports_every_field_touched_and_the_latest_source() -> None:
    v = view()
    v.column("close_paise")
    audit = v.audit()
    assert audit["accessed_fields"] == ["close_paise"]
    assert audit["max_source_ts"] == 30 * NS
    assert audit["decision_ts"] == 30 * NS
