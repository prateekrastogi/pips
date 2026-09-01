"""A wider cross-section, so selection has something to select between  (§6 M12/M19).

`make s5-smoke` runs seven families over TWO synthetic symbols. Every alpha therefore trades the
same two names, their PnL streams overlap by construction, and the pairwise gate collapses them
almost regardless of merit — the funnel reads 7 -> 3 -> 2 on pure noise. That is the machinery
working on a panel too narrow for the answer to mean anything.

**Symbols are nearly free; sessions are not.** The as-of loop iterates TIMESTAMPS, so widening
the cross-section leaves the number of decision points unchanged — eight symbols over five
sessions costs what two symbols over five sessions cost, in stamps. Adding sessions multiplies
the stamps and the runtime with them.

The wide panel is generated on demand rather than committed: it is four times the bars, and the
spec hash makes it reproducible from the seed (rule 1), so storing the bytes buys nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pips.fixtures.generate import WIDE_SPEC, FixtureSpec, generate
from pips.search.s1 import load_panel


@pytest.fixture(scope="module")
def wide(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("wide")
    generate(out, WIDE_SPEC)
    return out


def test_the_wide_spec_broadens_the_cross_section(wide: Path) -> None:
    panel = load_panel(wide)
    symbols = set(panel["symbol"].to_list())
    assert len(symbols) >= 8, "two names is a degenerate cross-section for A03 and A04"


def test_the_wide_spec_keeps_the_session_count(wide: Path) -> None:
    """Sessions are the expensive axis, and five already give A05 and A07 what they need.

    A gap needs a prior close and an opening range needs a session start; five sessions supply
    four of each. Multiplying sessions would multiply the decision points and the runtime, for
    no property the selection is currently missing.
    """
    assert len(WIDE_SPEC.days) == len(FixtureSpec().days)


def test_the_stamp_count_is_unchanged_so_the_search_costs_the_same(wide: Path) -> None:
    """The reason this is cheap. More names per bar, not more bars."""
    narrow_stamps = len(set(load_panel(Path("fixtures"))["close_ts_ns"].to_list()))
    wide_stamps = len(set(load_panel(wide)["close_ts_ns"].to_list()))
    assert wide_stamps == narrow_stamps


def test_the_symbols_are_not_copies_of_each_other(wide: Path) -> None:
    """Eight identical walks would be two symbols wearing eight names.

    The cross-sectional alphas would rank a tie, and the ensemble would be exactly as degenerate
    as before while looking broader.
    """
    panel = load_panel(wide)
    closes = {
        symbol: tuple(panel.filter(panel["symbol"] == symbol)["close_paise"].to_list())
        for symbol in sorted(set(panel["symbol"].to_list()))
    }
    assert len(set(closes.values())) == len(closes)


def test_generation_is_deterministic(tmp_path: Path) -> None:
    # Rule 1, and the reason the bytes need not be committed.
    first = generate(tmp_path / "a", WIDE_SPEC)
    second = generate(tmp_path / "b", WIDE_SPEC)
    assert first["manifest_hash"] == second["manifest_hash"]


def test_the_wide_spec_has_its_own_hash(tmp_path: Path) -> None:
    # Otherwise the two panels would be indistinguishable in any manifest that recorded them.
    narrow = generate(tmp_path / "n", FixtureSpec())
    wide = generate(tmp_path / "w", WIDE_SPEC)
    assert narrow["spec_hash"] != wide["spec_hash"]


def test_the_cli_flag_selects_the_wide_spec(tmp_path: Path) -> None:
    """A flag rather than a second target, so the spec is visible in the command that made it."""
    from pips.fixtures.generate import main

    assert main([str(tmp_path / "narrow")]) == 0
    assert main(["--wide", str(tmp_path / "wide")]) == 0

    narrow_symbols = set(load_panel(tmp_path / "narrow")["symbol"].to_list())
    wide_symbols = set(load_panel(tmp_path / "wide")["symbol"].to_list())
    assert len(wide_symbols) > len(narrow_symbols)


def test_the_cross_sectional_alphas_have_a_real_cross_section_to_rank(tmp_path: Path) -> None:
    """The structural reason for the wide panel, and the one that does not depend on a window.

    A03 is cross-sectional reversal and A04 residual reversion: both RANK names against each
    other at a decision point. Ranking two names is a tie dressed as a ranking — whichever moved
    more is first, always, and there is no cross-section to speak of.

    I first wrote this test as "the wider panel decorrelates the families", asserting M_erank
    rises. It does at a 900-bar window (3.13 -> 4.22) and REVERSES at 400 and 500 (5.42 -> 4.70,
    4.98 -> 4.32): shorter series make the correlation estimates noisier and noise decorrelates.
    That is a measurement at one window, not a property, and asserting it would have pinned a
    fixture-dependent number as a law.
    """
    from pips.alphas.dispatch import DRIVERS
    from pips.alphas.spec import load_alpha_spec
    from pips.core.asof import AsOfPanelView
    from pips.search.grid import bars_per_unit, grid_from_domain

    generate(tmp_path / "wide", WIDE_SPEC)
    panel = load_panel(tmp_path / "wide")
    stamps = sorted(set(panel["close_ts_ns"].to_list()))
    bars = bars_per_unit(stamps[1] - stamps[0])

    for alpha_id in ("A03", "A04"):
        driver = DRIVERS[alpha_id]
        spec = load_alpha_spec(Path("config/search_spaces") / driver.spec_file)
        params = driver.build(grid_from_domain(spec, driver.swept, count=2)[0], bars=bars)
        ranked = {
            f.instrument_id
            for ts in stamps[700:760]
            for f in driver.compute(AsOfPanelView(panel, decision_ts=ts), params, spec)
        }
        assert len(ranked) >= 8, f"{alpha_id} ranked {len(ranked)} names"
