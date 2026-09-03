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


# --------------------------------------------------------- found by mutation sweep ---


@pytest.mark.parametrize(
    ("rupees", "paise"),
    [
        ("1285.407", 128541),  # rounds up
        ("1285.995", 128600),  # carries into the rupee
        ("0.015", 2),  # ties to even at the smallest scale
        ("1285.405", 128540),  # and ties down, to the even paise
    ],
)
def test_a_sub_paise_amount_rounds_rather_than_truncating(rupees: str, paise: int) -> None:
    """Every existing case is exact to the paise, so truncation looks identical to rounding.

    `1285.4` converts the same either way, and so does every price in the fixtures — which is
    why `int(amount * 100)` in place of `round_half_even` changed no test. It differs only on
    amounts carrying sub-paise precision, and there it **always rounds toward zero**: a
    systematic downward bias on every price the vendor sends with a third decimal. On a long
    book that is a free basis point per fill, in the flattering direction, applied uniformly so
    nothing downstream looks anomalous.

    Half-to-EVEN, not half-up: `1285.405` goes down to the even paise and `0.015` goes up to
    it, so the bias cancels across many conversions instead of accumulating.
    """
    assert rupees_to_paise(rupees) == paise


def test_an_amount_that_is_not_a_number_is_refused_by_name() -> None:
    """`Decimal("not-a-price")` raises `InvalidOperation`, which names neither the input nor
    the field it came from.

    This function converts strings that arrive from a vendor, so the realistic bad input is a
    price field carrying `"-"` or `"N/A"` rather than a number. Translating it to a `ValueError`
    that quotes the offending value is what lets the caller quarantine the record with a reason
    instead of reporting an arithmetic fault three modules from the data.
    """
    for bad in ("not-a-price", "", "N/A", "1,285.40"):
        with pytest.raises(ValueError, match="not a decimal amount"):
            rupees_to_paise(bad)
