"""Integer money and rounding at the schema boundary  [C-NUM-01].

Prices are integer paise, quantities integer shares, notionals integer paise. ``f64``
is confined to the math kernel; nothing non-integral crosses a boundary. Rounding is
half-to-even unless a venue tick rule says otherwise.

This is the Python side of the boundary types; the certified definitions live in the
Rust ``domain`` crate (M21) and the two are pinned together by parity tests.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Final, NewType

__all__ = [
    "NotionalPaise",
    "PricePaise",
    "Quantity",
    "notional_paise",
    "paise_to_rupees_str",
    "round_half_even",
    "round_to_tick",
    "rupees_to_paise",
]

PricePaise = NewType("PricePaise", int)
Quantity = NewType("Quantity", int)
NotionalPaise = NewType("NotionalPaise", int)

PAISE_PER_RUPEE: Final = 100
NSE_DEFAULT_TICK_PAISE: Final = 5  # ₹0.05


def round_half_even(value: Decimal) -> int:
    """Round a ``Decimal`` to the nearest integer, ties to even."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def rupees_to_paise(rupees: str | int | Decimal) -> PricePaise:
    """Convert a rupee amount to integer paise, half-to-even.

    ``str`` (or ``Decimal``) input is required for exactness -- a binary ``float``
    rupee amount is already lossy before it gets here, so it is refused.
    """
    if isinstance(rupees, float):
        raise TypeError("pass rupees as str/int/Decimal — a float amount is already lossy")
    try:
        amount = Decimal(rupees)
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal amount: {rupees!r}") from exc
    return PricePaise(round_half_even(amount * PAISE_PER_RUPEE))


def paise_to_rupees_str(paise: int) -> str:
    """Exact decimal rupee string for display and reports (never re-parsed as float)."""
    sign = "-" if paise < 0 else ""
    whole, frac = divmod(abs(paise), PAISE_PER_RUPEE)
    return f"{sign}{whole}.{frac:02d}"


def round_to_tick(price_paise: int, tick_paise: int = NSE_DEFAULT_TICK_PAISE) -> PricePaise:
    """Round a price to the nearest venue tick, ties to even *ticks*."""
    if tick_paise <= 0:
        raise ValueError(f"tick must be positive, got {tick_paise}")
    ticks = round_half_even(Decimal(price_paise) / Decimal(tick_paise))
    return PricePaise(ticks * tick_paise)


def notional_paise(price_paise: int, quantity: int) -> NotionalPaise:
    """Exact notional in paise. Integer arithmetic only -- no float ever touches this."""
    return NotionalPaise(price_paise * quantity)
