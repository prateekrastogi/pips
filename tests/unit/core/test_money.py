"""Integer money and half-to-even rounding [C-NUM-01]."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.core.money import (
    notional_paise,
    paise_to_rupees_str,
    round_half_even,
    round_to_tick,
    rupees_to_paise,
)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("2500", 250_000), ("2500.05", 250_005), ("0.01", 1), ("-1.5", -150)],
)
def test_rupees_to_paise_is_exact(amount: str, expected: int) -> None:
    assert rupees_to_paise(amount) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.5", 0), ("1.5", 2), ("2.5", 2), ("3.5", 4), ("-0.5", 0), ("-1.5", -2)],
)
def test_ties_go_to_even(value: str, expected: int) -> None:
    assert round_half_even(Decimal(value)) == expected


def test_float_rupees_are_refused_as_lossy() -> None:
    with pytest.raises(TypeError):
        rupees_to_paise(2500.05)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("price", "expected"), [(102, 100), (103, 105), (107, 105), (250, 250), (255, 255)]
)
def test_round_to_tick_uses_even_ticks(price: int, expected: int) -> None:
    assert round_to_tick(price, 5) == expected


def test_zero_tick_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        round_to_tick(100, 0)


def test_notional_is_integer_only() -> None:
    assert notional_paise(250_005, 40) == 10_000_200


@pytest.mark.parametrize(("paise", "text"), [(250_005, "2500.05"), (1, "0.01"), (-150, "-1.50")])
def test_rupee_rendering_is_exact(paise: int, text: str) -> None:
    assert paise_to_rupees_str(paise) == text
