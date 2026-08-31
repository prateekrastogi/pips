"""Breeze ingest: response classification and normalization (§6 M4).

Tested entirely against **recorded cassettes** — CI makes no live calls (§6 M4). The recorded
ones came off arb-vm on 2026-08-28; the rate-limited one is synthesized from SAL-0003's
documentation and its filename says so.

The two properties that carry the most weight:

* **a rate rejection must never be read as "no data".** SAL-0003 records that Breeze returns
  it in the JSON body as `Status: 5`, not as HTTP 429. A client checking HTTP status sees a
  200 with an empty payload and writes a gap that looks like a quiet market — corrupt data
  that no later QC can distinguish from the real thing;
* **normalization adds one interval.** The M3 probe established Breeze is open-labelled and
  pips is close-labelled. Skipping the shift is a uniform one-bar lookahead.
"""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path
from typing import Any

import pytest

from pips.data.breeze.ingest import (
    ResponseKind,
    classify_response,
    normalize_candles,
)

ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ROOT / "fixtures" / "cassettes" / "breeze"
DAY = date(2026, 8, 28)


def cassette(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((CASSETTES / f"{name}.json").read_text(encoding="utf-8"))
    return loaded


# ------------------------------------------------- response classification --------------


def test_a_recorded_success_classifies_as_ok() -> None:
    assert classify_response(cassette("session_open_slice")) is ResponseKind.OK


def test_a_rate_rejection_is_not_mistaken_for_empty() -> None:
    # The failure this prevents: Breeze answers HTTP 200 with Status 5 in the body. Read as
    # "empty", it becomes a recorded gap indistinguishable from a genuinely quiet window.
    assert classify_response(cassette("SYNTHESIZED_rate_limited")) is ResponseKind.RATE_LIMITED


def test_a_genuinely_empty_reply_is_empty_not_an_error() -> None:
    # A non-trading day legitimately returns nothing; treating that as an error would halt a
    # backfill on every holiday.
    assert classify_response({"Status": 200, "Success": []}) is ResponseKind.EMPTY


def test_an_unrecognised_reply_is_an_error_not_a_success() -> None:
    assert classify_response({"Status": 500, "Error": "boom"}) is ResponseKind.ERROR


def test_rate_limited_is_never_usable_data() -> None:
    for kind in ResponseKind:
        assert kind.carries_data == (kind is ResponseKind.OK)


# ------------------------------------------------------ normalization -------------------


def test_timestamps_are_shifted_one_interval_to_close_labels() -> None:
    # Breeze's 09:15 bar covers [09:15, 09:16) and becomes the pips bar labelled 09:16.
    bars = normalize_candles(cassette("session_open_slice"), DAY, interval_minutes=1)
    assert bars[0].close_label == time(9, 16)
    assert bars[-1].close_label == time(9, 26)


def test_prices_become_integer_paise_exactly() -> None:
    # [C-NUM-01]: no float crosses a schema boundary. 1285.4 rupees is 128540 paise, exactly.
    bars = normalize_candles(cassette("session_open_slice"), DAY, interval_minutes=1)
    first = bars[0]
    assert first.open_paise == 128_540
    for value in (first.open_paise, first.high_paise, first.low_paise, first.close_paise):
        assert isinstance(value, int)


def test_pre_open_and_post_close_bars_are_dropped() -> None:
    # The probe found a widened window silently returns 09:07 (pre-open) and 15:31
    # (post-close) prints. §3.5 excludes pre-open from continuous bars, and a post-close print
    # is not part of the continuous tape either.
    bars = normalize_candles(cassette("widened_window_edges"), DAY, interval_minutes=1)
    labels = [b.close_label for b in bars]
    assert time(9, 8) not in labels, "the 09:07 pre-open bar must not survive"
    assert time(15, 32) not in labels, "the 15:31 post-close bar must not survive"
    assert time(9, 16) in labels and time(15, 30) in labels


def test_the_last_session_bar_is_kept() -> None:
    # Breeze's 15:29 bar closes at 15:30 — the session close — and must survive the clip.
    bars = normalize_candles(cassette("widened_window_edges"), DAY, interval_minutes=1)
    assert bars[-1].close_label == time(15, 30)


def test_missing_minutes_are_left_missing_not_filled() -> None:
    # §3.4: "a zero-volume bar is not a missing bar". Breeze omits untraded minutes, so the
    # normalizer must not invent them — a filled bar is a price claim nobody made.
    bars = normalize_candles(cassette("widened_window_edges"), DAY, interval_minutes=1)
    labels = [b.close_label for b in bars]
    assert time(9, 20) not in labels, "the gap between the edge rows must not be filled"
    assert len(bars) == len(set(labels))


def test_a_rate_limited_payload_normalizes_to_nothing_and_says_why() -> None:
    with pytest.raises(ValueError, match="rate"):
        normalize_candles(cassette("SYNTHESIZED_rate_limited"), DAY, interval_minutes=1)


def test_bars_come_out_sorted_by_label() -> None:
    bars = normalize_candles(cassette("widened_window_edges"), DAY, interval_minutes=1)
    assert [b.close_label for b in bars] == sorted(b.close_label for b in bars)
