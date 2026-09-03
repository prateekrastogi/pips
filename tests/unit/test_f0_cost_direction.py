"""What F0 charges, and which way it errs (§6 M10, §3.8, `[C-FILL-01]`).

`run_screen` charges `round_trip_cost` — statutory plus brokerage — and nothing else. No
half-spread, no impact, no latency, no adverse selection. Its docstring called that a
"conservative rough cost", and in this project's vocabulary that word means the opposite of what
is happening. `config/costs/execution_friction.yaml` states the rule:

    THE DIRECTION OF CONSERVATISM IS NOT SYMMETRIC. An overstated cost kills a live edge, which
    costs opportunity. An understated cost makes a DEAD edge look alive, which costs capital and
    is the single most expensive error this project can make. So placeholders overstate.

F0 understates. The statutory line is ~3.5 bps round trip; the friction placeholders add at
least 7.5 more before impact (half-spread 4 at MID, latency 1.5, adverse selection 2.0). A
reader told the cost is conservative believes the screen errs toward killing features, when it
errs toward keeping them.

**The behaviour is not the problem.** F0 is declared crude and `[C-FILL-01]` stamps every result
with its tier and refuses cross-tier comparison, so an F0 number cannot be presented as a net
return. The description was the problem, and these tests pin what is actually charged so the
description and the code cannot drift apart again.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import yaml

from pips.costs.schedule import CostSchedule
from pips.costs.statutory import Broker, round_trip_cost

ROOT = Path(__file__).resolve().parents[2]


def test_f0_charges_the_statutory_line_and_nothing_else() -> None:
    """The omission, pinned. Adding a friction term here changes what F0 IS, and the account of
    it in the module docstring would have to change with it."""
    source = (ROOT / "python" / "pips" / "sim" / "vector.py").read_text(encoding="utf-8")
    charged = re.findall(r"cost \+= Decimal\(\s*(\w+)\(", source)

    assert charged == ["round_trip_cost"], (
        f"F0 now charges {charged}; it charged statutory-plus-brokerage only, and the module "
        "docstring describes it on that basis"
    )


def test_the_statutory_line_is_smaller_than_the_frictions_f0_omits() -> None:
    """The direction, measured rather than asserted.

    If the omitted terms were negligible the wording would be a quibble. They are not: the
    placeholders alone are multiples of the statutory line, and they are the ones the config
    says to overstate.
    """
    friction = yaml.safe_load(
        (ROOT / "config" / "costs" / "execution_friction.yaml").read_text(encoding="utf-8")
    )
    omitted_bps = (
        Decimal(friction["half_spread_bps"]["MID"]) * 2  # both sides of a round trip
        + Decimal(friction["latency_bps"])
        + Decimal(friction["adverse_selection_bps"])
    )

    schedule = CostSchedule.model_validate(
        yaml.safe_load(
            (ROOT / "config" / "costs" / "nse_equity_intraday.yaml").read_text(encoding="utf-8")
        )
    )
    from datetime import date

    statutory = round_trip_cost(schedule, Broker.FLATTRADE, 10_000_000, date(2026, 9, 1))
    statutory_bps = Decimal(statutory.total_paise) / Decimal(10_000_000) * 10_000

    assert omitted_bps > statutory_bps, (
        f"F0 omits {omitted_bps} bps and charges {statutory_bps} — if that ever inverts, the "
        "understatement is no longer the dominant term and the wording can be revisited"
    )


def test_the_module_does_not_call_its_understatement_conservative() -> None:
    """A word that means "errs toward killing edges" describing a cost that errs toward keeping
    them is worse than no word: it tells the reader the safe direction is covered."""
    source = (ROOT / "python" / "pips" / "sim" / "vector.py").read_text(encoding="utf-8")
    docstring = source.split('"""')[1]

    assert "conservative rough cost" not in docstring
    assert "understate" in docstring, "it says which way it errs"
