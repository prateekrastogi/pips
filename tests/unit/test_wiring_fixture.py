"""Session length is part of a panel's identity — and A06 is gap-conditional  (§6 M12).

`test_families.py` is 1:35 of a 3:15 suite and Jenkins runs it every push. The cost is the
SESSION FLOOR: A05, A06 and A07 need the evaluation window to cross a session boundary, a real
session is 375 bars, so `initial_budget` cannot go below ~376 whatever else is tuned. A shorter
session would make the floor cheap.

**That compression was attempted and abandoned, and the reason is worth keeping.** A06 fades an
UNCONFIRMED idiosyncratic gap, and qualifying gaps are rare in a seeded random walk — the walk
depends on the symbol name, so whether A06 participates at all depends on which names a panel
uses. Of ten name sets tried it fired on two: the shipped `SMOKE*` and the wide `WIDE*`. `WIRE`,
`WA`, `TEST`, `PANEL`, `FIX`, `GAP`, `TICK` and `CHAIN` all produced nothing, at every session
length from 120 to 375 bars.

A panel whose viability turns on that is not a safe substitute for the shipped one, so the
compression is not worth the ~75 seconds. What survives is `session_minutes` as a real part of
`FixtureSpec` — and the knowledge that A06's presence in the search is conditional on the data,
which nothing recorded before.
"""

from __future__ import annotations

from pathlib import Path

from pips.alphas.dispatch import DRIVERS
from pips.alphas.spec import load_alpha_spec
from pips.core.asof import AsOfPanelView
from pips.fixtures.generate import FixtureSpec, generate
from pips.search.grid import bars_per_unit, grid_from_domain
from pips.search.s1 import load_panel

SPECS = Path("config/search_spaces")


def test_the_session_length_is_part_of_the_identity(tmp_path: Path) -> None:
    """Two panels differing only in session length are different data.

    A hash that ignored it would let a compressed panel be mistaken for a real one in any
    manifest that recorded the spec — and a manifest is how a result is traced back to its bars.
    """
    normal = generate(tmp_path / "n", FixtureSpec())
    compressed = generate(tmp_path / "c", FixtureSpec(session_minutes=60))
    assert normal["spec_hash"] != compressed["spec_hash"]


def test_a_shorter_session_really_produces_shorter_sessions(tmp_path: Path) -> None:
    generate(tmp_path / "c", FixtureSpec(session_minutes=60))
    panel = load_panel(tmp_path / "c")
    stamps = sorted(set(panel["close_ts_ns"].to_list()))
    assert len(stamps) == 60 * len(FixtureSpec().days)


def test_the_default_session_is_the_real_one() -> None:
    # 09:15 -> 15:30 continuous. A default that drifted would quietly change every fixture.
    assert FixtureSpec().session_minutes == 375


def test_a06_participates_only_because_the_shipped_walks_produce_gaps() -> None:
    """The finding, pinned so it cannot go quiet.

    A06 is in the driver register because it produces forecasts on the shipped panel. That is a
    fact about these bars, not about A06: regenerate the fixtures under a different seed or
    different symbol names and it may produce nothing, be dropped at promotion as a flat series,
    and vanish from the ensemble without anything saying why.

    This asserts the condition holds NOW. When it stops holding, the failure names the cause
    instead of leaving a family silently absent.
    """
    panel = load_panel(Path("fixtures"))
    stamps = sorted(set(panel["close_ts_ns"].to_list()))
    driver = DRIVERS["A06"]
    spec = load_alpha_spec(SPECS / driver.spec_file)
    params = driver.build(
        grid_from_domain(spec, driver.swept, count=2)[0],
        bars=bars_per_unit(stamps[1] - stamps[0]),
    )
    produced = sum(
        len(driver.compute(AsOfPanelView(panel, decision_ts=ts), params, spec))
        for ts in stamps[375:]
    )
    assert produced > 0, (
        "A06 found no qualifying gap in the shipped fixtures. It is registered as a runnable "
        "driver on the strength of these particular seeded walks; if they no longer produce "
        "gaps it will be dropped at promotion as a flat series, which reads as a fact about "
        "the alpha rather than about the data."
    )
