"""F1-vs-vectorized reconciliation  [C-FILL-01] (§6 M14's third Verify).

The Verify is not "the two engines agree". They must NOT agree: F0 assumes every intended trade
happens at the bar price, and F1 models the ways it does not. The claim is stronger and more
useful — **every paise of the difference is named.**

**The residual alone is not a check, and this module says so rather than selling it as one.**
``unfilled`` is defined as *intended minus traded*, so the components close the identity by
construction: an F1 result that filled 1,200 shares against a 1,000-share trade produces a
residual of exactly zero, absorbed as a NEGATIVE unfilled quantity. The first version of this
module presented ``unexplained_paise`` as the thing that catches a wrong engine. It catches
arithmetic, and nothing structural.

What catches a wrong engine is stated explicitly and checked separately: a fill quantity must
be positive, and the traded total must not exceed what was intended. Those are impossible
inputs rather than tolerances, so they raise unconditionally. The residual stays because an
arithmetic self-check is worth having and costs nothing — but it is documented as what it is.

This is M10's discipline (``pnl_gross - costs == pnl_net``, inside F0) applied BETWEEN the two
engines, which is the only place a disagreement between them can surface at all.

Sign convention: everything is a CASH FLOW. A sell brings cash in, a buy takes it out, and each
component answers one question — *by how much did F0 overstate the cash?* Keeping them all in
that one direction is what stops a buy's error and a sell's error from cancelling.
"""

from __future__ import annotations

from dataclasses import dataclass

from pips.sim.protected_limit import Fill, Side

__all__ = [
    "IntendedTrade",
    "Reconciliation",
    "ReconciliationError",
    "reconcile",
]


class ReconciliationError(AssertionError):
    """F0 and F1 differ by an amount the decomposition cannot name."""


@dataclass(frozen=True)
class IntendedTrade:
    """What F0 booked: a quantity at a reference price, with no execution risk."""

    instrument_id: str
    side: Side
    quantity: int
    reference_price_paise: int


@dataclass(frozen=True)
class Reconciliation:
    """The difference between the engines, fully attributed."""

    f0_cash_paise: int
    f1_cash_paise: int
    slippage_paise: int
    """Voluntary fills that traded away from the reference. Positive = F0 overstated."""

    unfilled_notional_paise: int
    """Quantity F0 booked and F1 never traded. NOT slippage -- a fill-rate problem hidden
    inside a price-quality number is a fill-rate problem nobody finds."""

    forced_notional_paise: int
    """Broker square-off, away from the reference. Kept apart from voluntary slippage because
    execution the strategy chose and execution imposed on it are different facts, and merging
    them hides square-off in exactly the number a live system watches."""

    unexplained_paise: int
    """Arithmetic self-check ONLY. The components close the identity by construction, so this
    cannot detect a structurally wrong F1 result -- see the module docstring. It is retained
    because an arithmetic check costs nothing, not because it proves anything about fills."""

    @property
    def reconciles(self) -> bool:
        return self.unexplained_paise == 0


def _cash(side: Side, quantity: int, price_paise: int) -> int:
    """Signed cash flow: a sell brings cash in, a buy takes it out."""
    return quantity * price_paise if side is Side.SELL else -quantity * price_paise


def _overstatement(side: Side, quantity: int, price_paise: int, reference_paise: int) -> int:
    """How much F0's cash exceeded F1's, for one quantity at one price.

    One direction for both sides, deliberately. A buy filled ABOVE the reference and a sell
    filled BELOW are both F0 overstating; sign one of them the other way and a mixed book
    cancels — the two errors offset, the residual stays zero, and the reconciliation certifies
    an engine that is wrong in both directions at once.
    """
    return _cash(side, quantity, reference_paise) - _cash(side, quantity, price_paise)


def _check_structure(intended: IntendedTrade, fills: list[Fill], traded: int) -> None:
    """Reject an F1 result that could not have happened.

    These are impossible inputs, not tolerances, so there is no mode in which they are
    acceptable and no flag to switch them off. They exist because the residual cannot see
    them: `unfilled` is a remainder, so an overfill closes the identity as a negative
    quantity and reports zero unexplained.
    """
    for one in fills:
        if one.quantity <= 0:
            raise ReconciliationError(
                f"{intended.instrument_id}: a fill of {one.quantity} shares is not a fill"
            )
    if traded > intended.quantity:
        raise ReconciliationError(
            f"{intended.instrument_id}: F1 traded {traded} shares against an intended "
            f"{intended.quantity}. An overfill is not slippage and not a residual — it is an "
            "F1 result inconsistent with its own intent, and the decomposition would absorb "
            "it silently as a negative unfilled quantity."
        )


def reconcile(
    book: list[tuple[IntendedTrade, list[Fill], list[Fill]]],
) -> Reconciliation:
    """Attribute the F0/F1 difference over ``(trade, voluntary_fills, forced_fills)`` triples.

    Structural violations raise unconditionally; see :func:`_check_structure`. There is no
    lenient mode, because there is nothing here worth tolerating — an impossible F1 result is
    not a small disagreement.
    """
    if not book:
        raise ValueError(
            "reconcile called with no trades. Reconciling nothing trivially succeeds, which "
            "is exactly the green that means nothing."
        )

    f0_cash = f1_cash = slippage = unfilled = forced = 0
    for intended, voluntary, forced_fills in book:
        f0_cash += _cash(intended.side, intended.quantity, intended.reference_price_paise)
        for one in (*voluntary, *forced_fills):
            f1_cash += _cash(intended.side, one.quantity, one.price_paise)

        for one in voluntary:
            slippage += _overstatement(
                intended.side, one.quantity, one.price_paise, intended.reference_price_paise
            )
        for one in forced_fills:
            forced += _overstatement(
                intended.side, one.quantity, one.price_paise, intended.reference_price_paise
            )

        traded = sum(f.quantity for f in (*voluntary, *forced_fills))
        _check_structure(intended, [*voluntary, *forced_fills], traded)
        unfilled += _cash(intended.side, intended.quantity - traded, intended.reference_price_paise)

    unexplained = (f0_cash - f1_cash) - (slippage + unfilled + forced)
    result = Reconciliation(
        f0_cash_paise=f0_cash,
        f1_cash_paise=f1_cash,
        slippage_paise=slippage,
        unfilled_notional_paise=unfilled,
        forced_notional_paise=forced,
        unexplained_paise=unexplained,
    )
    if not result.reconciles:
        # Unreachable through the public API given the structural checks above — the
        # components close the identity by construction. Kept because "unreachable" is a
        # claim about today's arithmetic, and an integer identity that stops holding is worth
        # hearing about immediately rather than through its consequences.
        raise ReconciliationError(
            f"{unexplained} paise unexplained between F0 and F1 — the cash identity itself "
            f"has stopped holding. F0 cash {f0_cash}, F1 cash {f1_cash}, slippage "
            f"{slippage}, unfilled {unfilled}, forced {forced}."
        )
    return result
