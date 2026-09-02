"""M7's daily eligibility gates  (§4.2, `[C-UNIV-02]`).

The universe for a session is decided **before** it opens. §4.2 states the causality rule
outright: *"Intraday causal liquidity gate may veto a trade, but the completed day's volume
cannot retrospectively add a stock to that day's universe."* A name admitted on the strength of
the volume it went on to trade is a name selected by its own outcome, and every measurement over
that panel inherits it. So :class:`EligibilityInputs` carries nothing from the session being
decided — the same construction as `[C-LBOX-01]` taking no dates from its caller: the cheapest
way to guarantee a value cannot be used is to have nowhere to receive it.

**Unknown is not eligible.** A flag nobody could resolve before the open — a suspension feed
that did not arrive, a corporate action whose adjustment handling is uncertain — leaves the name
out and says so. Defaulting to eligible admits names on the strength of a missing file, which is
the flattering direction and produces a universe indistinguishable from one that genuinely
qualified.

**Ineligible and undetermined are reported apart**, because the fixes differ: one is a fact
about the security, the other a gap in the feed. Collapsing them sends whoever reads the report
to argue with an exchange about a file that never arrived.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "APPROVED_SERIES",
    "SUPPORTED_LISTING_HISTORY",
    "Eligibility",
    "EligibilityInputs",
    "eligible_on",
]

APPROVED_SERIES: frozenset[str] = frozenset({"EQ"})
"""§4.2's *EQ/approved series*. `EQ` is the normal rolling segment; `BE` and the T2T series
settle delivery-only, so an intraday strategy cannot trade them at all. Widening this set is a
policy change, not a configuration detail."""

SUPPORTED_LISTING_HISTORY: frozenset[int] = frozenset({60, 120, 250})
"""The warm-up requirements the blueprint registers. An unregistered one is a policy nobody
declared, chosen after seeing which names it admits."""


@dataclass(frozen=True)
class EligibilityInputs:
    """What is known about one symbol BEFORE a session opens.

    Every flag is optional and ``None`` means *unresolved*, which is a third state and not a
    quiet ``False``. Nothing here describes the session being decided.
    """

    symbol: str
    series: str
    suspended: bool | None
    trade_to_trade: bool | None
    unresolved_symbol_change: bool | None
    sessions_listed: int | None
    corporate_action_certain: bool | None


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    ineligible: tuple[str, ...]
    """Gates the name failed. Facts about the security."""
    undetermined: tuple[str, ...]
    """Gates that could not be evaluated. Gaps in the feed, and never a pass."""


def eligible_on(inputs: EligibilityInputs, *, min_sessions_listed: int) -> Eligibility:
    """Whether ``inputs`` may enter the universe for the session they precede.

    Every gate is evaluated, not the first that fails: a caller fixing them one at a time
    rebuilds the universe once per problem.
    """
    if min_sessions_listed not in SUPPORTED_LISTING_HISTORY:
        raise ValueError(
            f"min_sessions_listed={min_sessions_listed} is not one of the registered warm-up "
            f"requirements {sorted(SUPPORTED_LISTING_HISTORY)}."
        )

    ineligible: list[str] = []
    undetermined: list[str] = []

    if inputs.series not in APPROVED_SERIES:
        ineligible.append(
            f"series {inputs.series!r} is not in the approved set {sorted(APPROVED_SERIES)}"
        )

    for name, flag, bad in (
        ("suspended", inputs.suspended, True),
        ("trade_to_trade", inputs.trade_to_trade, True),
        ("unresolved_symbol_change", inputs.unresolved_symbol_change, True),
        # Inverted: the gate is CERTAINTY, so False is the failure and None is still a gap.
        ("corporate_action_certain", inputs.corporate_action_certain, False),
    ):
        if flag is None:
            undetermined.append(f"{name} could not be resolved before the open")
        elif flag is bad:
            ineligible.append(f"{name} is {flag}")

    if inputs.sessions_listed is None:
        undetermined.append("sessions_listed is unknown, so the warm-up cannot be checked")
    elif inputs.sessions_listed < min_sessions_listed:
        ineligible.append(
            f"sessions_listed {inputs.sessions_listed} is below the {min_sessions_listed} "
            "warm-up requirement"
        )

    return Eligibility(
        eligible=not ineligible and not undetermined,
        ineligible=tuple(ineligible),
        undetermined=tuple(undetermined),
    )
