"""`[C-NUM-01]`'s Python half, gathered in one place (§3.11).

The row said `status: planned` with `tests: []` — the ledger's way of saying nothing is
started. Six production modules cite it as a rule they already satisfy:

* `costs/statutory.py` — "Every charge is computed in **integer paise** [C-NUM-01]"
* `core/money.py` — the boundary API itself
* `core/ids.py` — "NaN and infinities cannot cross a schema boundary"
* `core/trial.py` — relies on that refusal to keep two trials from sharing an id
* `data/breeze/ingest.py` — "Exact rupees -> integer paise [C-NUM-01]"

and two test files assert it in passing. What was missing was a row that admitted any of it,
and tests bound to that row so the claims cannot rot unnoticed.

**The Rust half is genuinely unstarted.** "f64 confined to the kernel" needs a kernel, and all
21 crates are M0 scaffolds. That is why this row moves to `building` and not to `enforced`.
"""

from __future__ import annotations

import ast
import math
import pathlib
from decimal import Decimal

import pytest

from pips.core.ids import canonicalize
from pips.core.money import (
    notional_paise,
    paise_to_rupees_str,
    round_half_even,
    round_to_tick,
    rupees_to_paise,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_float_cannot_cross_the_boundary(bad: float) -> None:
    """The half of the rule that has teeth. `trial.py` depends on it: pydantic's JSON
    serialiser turns a non-finite float into `null`, so `inf` and `None` would hash
    identically and two different trials would share one id and one cached result."""
    with pytest.raises(ValueError):
        canonicalize({"p": bad})


def test_rupees_become_paise_exactly() -> None:
    """A string or Decimal in, integer paise out. `1285.4` rupees is `128540` paise and no
    float ever holds it."""
    assert rupees_to_paise("1285.4") == 128_540
    assert rupees_to_paise(Decimal("0.05")) == 5
    assert paise_to_rupees_str(128_540) == "1285.40"


def test_rounding_is_half_to_even() -> None:
    """Half-UP would bias every cost estimate upward by a fraction of a paise per component,
    consistently in one direction, which is what a contract note does not do."""
    assert round_half_even(Decimal("0.5")) == 0
    assert round_half_even(Decimal("1.5")) == 2
    assert round_half_even(Decimal("2.5")) == 2


def test_a_price_is_snapped_to_the_tick() -> None:
    assert round_to_tick(10_003) == 10_005
    assert round_to_tick(10_002) == 10_000


def test_notional_stays_integer() -> None:
    assert notional_paise(10_005, 37) == 10_005 * 37


def test_the_boundary_api_takes_no_float_arguments() -> None:
    """The rule is about the BOUNDARY, so the boundary's own signatures are where it is
    cheapest to check. A `float` parameter here is an invitation to pass one.
    """
    source = (ROOT / "python" / "pips" / "core" / "money.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = [
        f"{node.name}({arg.arg})"
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        for arg in node.args.args
        if arg.annotation is not None and "float" in ast.unparse(arg.annotation)
    ]
    assert offenders == [], f"float crosses the money boundary at {offenders}"
