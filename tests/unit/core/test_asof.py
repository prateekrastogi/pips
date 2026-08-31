"""As-of guard: causality is measurability (constitution rule 2)."""

from __future__ import annotations

import pytest

from pips.core.asof import AsOfView, CausalityViolationError

RECORDS = [{"ts": 10, "px": 1}, {"ts": 20, "px": 2}, {"ts": 30, "px": 3}]


def test_future_rows_are_invisible() -> None:
    view = AsOfView.of(RECORDS, decision_ts=20)
    assert [r["ts"] for r in view.visible()] == [10, 20]


def test_max_source_ts_never_exceeds_the_decision() -> None:
    view = AsOfView.of(RECORDS, decision_ts=25)
    max_ts = view.max_source_ts()
    assert max_ts is not None and max_ts <= view.decision_ts


def test_field_access_is_recorded() -> None:
    view = AsOfView.of(RECORDS, decision_ts=30)
    assert view.field_values("px") == [1, 2, 3]
    assert view.accessed_fields == {"px"}


def test_empty_visible_window_has_no_max() -> None:
    assert AsOfView.of(RECORDS, decision_ts=0).max_source_ts() is None


def test_require_measurable_rejects_the_future() -> None:
    view = AsOfView.of(RECORDS, decision_ts=20)
    view.require_measurable(20, "bar close")
    with pytest.raises(CausalityViolationError, match="source_ts 21"):
        view.require_measurable(21, "bar close")


def test_records_without_a_timestamp_field_are_refused() -> None:
    with pytest.raises(ValueError, match="lack the 'ts' field"):
        AsOfView.of([{"px": 1}], decision_ts=0)
