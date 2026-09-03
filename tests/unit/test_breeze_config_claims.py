"""`config/breeze.yaml` says what it is, and the code agrees (§6 M4, `[C-DATA-01]`).

The file opens with a claim about itself:

    Effective-dated data, like a fee schedule (rule 6): every number carries where it came from
    and when it was verified. The fetcher reads these; it does not hard-code them.

Both halves are checkable, and one of them was false. `budget.py` genuinely reads the `quota`
block — day cap, per-minute rate, parallelism — which is what makes a reader assume
`fetch.candles_per_call` is read too. It is not. The code carries its own `CANDLES_PER_CALL`,
and the config's copy is inert: measure a different cap, update the config, and **nothing
changes**. The number that decides every chunk boundary would still be the old one.

Two constants at one value were deduplicated inside the code earlier; this is the third copy,
one level out, and the one nobody would think to check because the file promises it is read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pips.data.breeze.campaign import CANDLES_PER_CALL

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "breeze.yaml"


def config() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return loaded


def test_the_declared_candle_cap_is_the_one_the_code_uses() -> None:
    """The drift this closes is silent and expensive.

    `chunk_range` splits ranges so no reply can reach the cap and `run_range_backfill` refuses
    one that does — both against the code constant. A config saying something else would be
    read by a person planning a campaign and by nothing else, so the plan and the fetcher would
    disagree about the only number that decides how a three-year range is cut.
    """
    assert config()["fetch"]["candles_per_call"] == CANDLES_PER_CALL


def test_the_candle_cap_is_recorded_as_measured_not_as_a_planning_figure() -> None:
    """The 2026-09-03 probe settled it: 1,125 minutes requested, exactly 1,000 returned, the
    oldest 125 absent under Status 200.

    Leaving `verified: false` beside a measured number is the same defect as a check that did
    not run reading as one that passed, pointed the other way: a fact that WAS established
    reading as one that was not. The next person to plan a campaign would go and measure it
    again, or worse, discount it.
    """
    fetch = config()["fetch"]

    assert fetch["candles_per_call_verified"] is True
    assert "2026-09-03" in str(fetch["candles_per_call_source"])
    assert fetch["candles_per_call_verified_on"].isoformat() == "2026-09-03"


def test_what_is_still_unverified_does_not_name_the_cap() -> None:
    """The file keeps a list of what the probe must still measure. A number can be in that list
    or marked verified, never both — two statements in one file disagreeing is worse than
    either being wrong, because a reader cannot tell which to act on."""
    listed = " ".join(config()["unverified"]).lower()

    assert "candles_per_call" not in listed
    assert "candle" not in listed


def test_everything_still_unverified_says_so_in_both_places() -> None:
    """The other direction, so the test above cannot be satisfied by emptying the list.

    The per-minute rate is a deliberate conservative placeholder and must stay marked
    unverified while it is one — being throttled costs minutes, being rate-limited mid-campaign
    costs a resumable-state bug hunt.
    """
    quota = config()["quota"]
    listed = " ".join(config()["unverified"]).lower()

    assert quota["max_calls_per_minute_verified"] is False
    assert "per-minute rate" in listed


def test_every_verified_number_carries_a_source_and_a_date() -> None:
    """Rule 6's shape, checked over the file rather than trusted.

    A number marked verified with no source is an assertion; the whole point of an
    effective-dated file is that a reader can go and check it, and later tell whether the world
    has moved since.
    """
    loaded = config()
    for block in ("quota", "fetch"):
        for key, value in loaded[block].items():
            if not key.endswith("_verified") or value is not True:
                continue
            stem = key.removesuffix("_verified")
            assert loaded[block].get(f"{stem}_source"), f"{stem} is verified with no source"
            assert loaded[block].get(f"{stem}_verified_on"), f"{stem} is verified with no date"
