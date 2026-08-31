"""Seeded smoke fixtures and the determinism gate (constitution rule 1)."""

from __future__ import annotations

import json
from pathlib import Path

from pips.fixtures.determinism import diff_runs
from pips.fixtures.generate import SESSION_MINUTES, FixtureSpec, generate


def test_two_runs_are_bit_identical(tmp_path: Path) -> None:
    spec = FixtureSpec(symbols=("SMOKEA",), days=("2026-06-01",), second_bar_day="2026-06-01")
    first = generate(tmp_path / "a", spec)
    second = generate(tmp_path / "b", spec)
    assert first["manifest_hash"] == second["manifest_hash"]


def test_determinism_entry_point_reports_no_diffs() -> None:
    tiny = FixtureSpec(symbols=("SMOKEA",), days=("2026-06-01",), second_bar_day="2026-06-01")
    assert diff_runs(tiny) == []


def test_a_different_seed_changes_the_bytes(tmp_path: Path) -> None:
    base = FixtureSpec(symbols=("SMOKEA",), days=("2026-06-01",), second_bar_day="2026-06-01")
    other = FixtureSpec(
        symbols=("SMOKEA",), days=("2026-06-01",), second_bar_day="2026-06-01", seed=base.seed + 1
    )
    assert (
        generate(tmp_path / "a", base)["manifest_hash"]
        != generate(tmp_path / "b", other)["manifest_hash"]
    )


def test_bars_are_close_labelled_and_strictly_increasing(tmp_path: Path) -> None:
    spec = FixtureSpec(symbols=("SMOKEA",), days=("2026-06-01",), second_bar_day="2026-06-01")
    generate(tmp_path, spec)
    bars = json.loads((tmp_path / "bars/1m/SMOKEA_2026-06-01.json").read_text())
    assert len(bars) == SESSION_MINUTES
    labels = [b["close_ts_ns"] for b in bars]
    assert labels == sorted(labels) and len(set(labels)) == len(labels)


def test_prices_are_integer_paise_and_ohlc_consistent(tmp_path: Path) -> None:
    spec = FixtureSpec(symbols=("SMOKEA",), days=("2026-06-01",), second_bar_day="2026-06-01")
    generate(tmp_path, spec)
    bars = json.loads((tmp_path / "bars/1m/SMOKEA_2026-06-01.json").read_text())
    for bar in bars:
        for key in ("open_paise", "high_paise", "low_paise", "close_paise", "volume"):
            assert isinstance(bar[key], int), f"{key} must be an integer"
        assert bar["low_paise"] <= min(bar["open_paise"], bar["close_paise"])
        assert bar["high_paise"] >= max(bar["open_paise"], bar["close_paise"])
