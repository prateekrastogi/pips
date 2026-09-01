"""The loader must carry what the fixtures hold  (§6 M12).

`load_panel` built its rows from four keys — close_ts_ns, symbol, close_paise, volume — while
the fixture bars carry seven. It already bears a comment about volume: *"The fixtures always had
it; this loader was dropping it on the floor."* The same thing was happening to open, high and
low, and it cost A07 its place in the search: it was recorded as not runnable because "the panel
has no high_paise, low_paise", which was true of the panel and false of the fixtures.

An alpha excluded for a reason that is not true is worse than one excluded for a reason that is,
because the reason reads as a fact about the data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pips.search.s1 import load_panel

FIXTURES = Path("fixtures")


def fixture_keys() -> set[str]:
    first = sorted((FIXTURES / "bars" / "1m").glob("*.json"))[0]
    return set(json.loads(first.read_text(encoding="utf-8"))[0])


def test_the_panel_carries_every_field_the_fixtures_hold() -> None:
    """Not a subset chosen by whoever last needed one.

    Every column dropped here is a family that cannot run, and the family is excluded for a
    reason phrased as a property of the data rather than of the loader.
    """
    assert fixture_keys() <= set(load_panel(FIXTURES).columns)


@pytest.mark.parametrize("column", ["open_paise", "high_paise", "low_paise", "volume"])
def test_the_price_and_size_columns_are_present(column: str) -> None:
    assert column in load_panel(FIXTURES).columns


def test_high_is_never_below_low() -> None:
    # Cheap, and it would catch the two being swapped during the copy — which would give every
    # true-range calculation a negative range and A07 a silently inverted buffer.
    panel = load_panel(FIXTURES)
    assert (panel["high_paise"] >= panel["low_paise"]).all()


def test_the_close_lies_within_the_bar() -> None:
    panel = load_panel(FIXTURES)
    assert (panel["close_paise"] <= panel["high_paise"]).all()
    assert (panel["close_paise"] >= panel["low_paise"]).all()
