"""M7's daily eligibility gates  (§4.2, `[C-UNIV-02]`).

The universe for a session is decided **before** it opens. §4.2 states the causality rule
outright: *"Intraday causal liquidity gate may veto a trade, but the completed day's volume
cannot retrospectively add a stock to that day's universe."* A name admitted on the strength of
the volume it went on to trade is a name selected by its own outcome, and every measurement over
that panel inherits it.

**Unknown is not eligible.** A flag nobody could resolve before the open — a suspension feed
that did not arrive, a corporate action whose adjustment is uncertain — leaves the name OUT and
says so. Defaulting to eligible admits names on the strength of a missing file, which is the
flattering direction and looks identical to a name that genuinely qualified.

**Ineligible and undetermined are reported apart.** They have different fixes: one is a fact
about the security, the other is a gap in the feed.
"""

from __future__ import annotations

import dataclasses

import pytest

from pips.universe.eligibility import (
    APPROVED_SERIES,
    SUPPORTED_LISTING_HISTORY,
    Eligibility,
    EligibilityInputs,
    eligible_on,
)


def inputs(**over: object) -> EligibilityInputs:
    base: dict[str, object] = {
        "symbol": "RELIANCE",
        "series": "EQ",
        "suspended": False,
        "trade_to_trade": False,
        "unresolved_symbol_change": False,
        "sessions_listed": 500,
        "corporate_action_certain": True,
        "mis_allowed": True,
    }
    base.update(over)
    return EligibilityInputs(**base)  # type: ignore[arg-type]


def verdict(**over: object) -> Eligibility:
    return eligible_on(inputs(**over), min_sessions_listed=250)


# --------------------------------------------------------------------- the happy path -----


def test_a_clean_name_is_eligible() -> None:
    result = verdict()
    assert result.eligible
    assert result.ineligible == () and result.undetermined == ()


# ------------------------------------------------------------- decided before the open -----


def test_the_inputs_carry_nothing_from_the_session_being_decided() -> None:
    """§4.2's causality rule, made structural.

    The cheapest way to guarantee the completed day's volume cannot admit a stock is to give
    the gate nowhere to receive it — the same construction as `[C-LBOX-01]` taking no dates and
    `plateau_for_winner` taking no scores of its own.
    """
    fields = {f.name for f in dataclasses.fields(EligibilityInputs)}
    forbidden = {"volume", "turnover", "close", "traded_value", "session_volume", "vwap"}
    assert not (fields & forbidden), fields


# --------------------------------------------------------- unknown is not eligibility -----


@pytest.mark.parametrize(
    "flag",
    ["suspended", "trade_to_trade", "unresolved_symbol_change", "corporate_action_certain"],
)
def test_an_unresolved_flag_leaves_the_name_out(flag: str) -> None:
    """A feed that did not arrive must not read as a clean bill of health."""
    result = verdict(**{flag: None})
    assert not result.eligible
    assert flag in " ".join(result.undetermined)
    assert result.ineligible == (), "undetermined is not the same as failing"


def test_an_unknown_listing_history_leaves_the_name_out() -> None:
    """The vendor file has a blank `DateOfListing` on every row, so this is the live case."""
    result = verdict(sessions_listed=None)
    assert not result.eligible
    assert "sessions_listed" in " ".join(result.undetermined)


# ------------------------------------------------------------------ the gates themselves -----


def test_a_suspended_name_is_ineligible() -> None:
    result = verdict(suspended=True)
    assert not result.eligible
    assert "suspended" in " ".join(result.ineligible)


def test_a_trade_to_trade_name_is_ineligible() -> None:
    """§4.2: *not forced into an incompatible auction/trade-to-trade process*. T2T settles
    delivery-only, so an intraday strategy cannot trade it at all."""
    assert not verdict(trade_to_trade=True).eligible


def test_a_non_approved_series_is_ineligible() -> None:
    assert not verdict(series="BE").eligible
    assert "EQ" in APPROVED_SERIES


def test_an_unresolved_symbol_change_is_ineligible() -> None:
    """A token whose identity is in doubt cannot be joined to its own history."""
    assert not verdict(unresolved_symbol_change=True).eligible


def test_an_uncertain_corporate_action_is_ineligible() -> None:
    """§4.2: *exclude when adjustment/auction handling is uncertain*. An unadjusted split is a
    -50% return that never happened."""
    assert not verdict(corporate_action_certain=False).eligible


def test_too_little_history_is_ineligible() -> None:
    assert not verdict(sessions_listed=249).eligible
    assert verdict(sessions_listed=250).eligible


def test_an_unregistered_history_requirement_is_refused() -> None:
    """The blueprint registers {60, 120, 250}; anything else is a policy nobody declared."""
    with pytest.raises(ValueError, match="250"):
        eligible_on(inputs(), min_sessions_listed=200)
    assert frozenset({60, 120, 250}) == SUPPORTED_LISTING_HISTORY


# ------------------------------------------------------------------ every reason at once -----


def test_every_failure_is_reported_not_just_the_first() -> None:
    """A caller fixing one at a time re-runs the universe once per problem."""
    result = verdict(suspended=True, trade_to_trade=True, series="BE")
    joined = " ".join(result.ineligible)
    assert "suspended" in joined
    assert "trade_to_trade" in joined
    assert "series" in joined


def test_failures_and_gaps_are_reported_apart() -> None:
    result = verdict(suspended=True, corporate_action_certain=None)
    assert "suspended" in " ".join(result.ineligible)
    assert "corporate_action_certain" in " ".join(result.undetermined)


# ------------------------------------------------- broker-MIS is its own gate (§4.1) -----


def test_a_name_the_broker_will_not_allow_mis_on_is_ineligible() -> None:
    """§4.1's formula names `broker-MIS allowed` as one of its six terms.

    This is an intraday strategy that must square off the same session. A name the BROKER will
    not grant MIS on cannot be traded intraday there at all: the order is either rejected or,
    worse, filled as a delivery position the strategy never intended to hold overnight.
    """
    result = verdict(mis_allowed=False)
    assert not result.eligible
    assert "mis_allowed" in " ".join(result.ineligible)


def test_an_unknown_mis_permission_leaves_the_name_out() -> None:
    """Unknown is not eligibility — the same rule every other gate here follows."""
    result = verdict(mis_allowed=None)
    assert not result.eligible
    assert "mis_allowed" in " ".join(result.undetermined)
    assert result.ineligible == (), "undetermined is not the same as failing"


def test_broker_mis_is_not_the_exchange_t2t_list() -> None:
    """The gate that earns the separate field.

    T2T is the EXCHANGE forbidding intraday trading in a name; broker-MIS is one BROKER's own,
    narrower list. A name can be perfectly free of T2T and still be one this broker declines to
    fund intraday — Flattrade and Zerodha publish different lists, and neither equals the
    exchange's. Reading one as the other admits names the broker will refuse.
    """
    not_t2t_but_no_mis = verdict(trade_to_trade=False, mis_allowed=False)
    assert not not_t2t_but_no_mis.eligible
    assert "mis_allowed" in " ".join(not_t2t_but_no_mis.ineligible)
    assert "trade_to_trade" not in " ".join(not_t2t_but_no_mis.ineligible), (
        "the T2T gate passed; only the MIS gate should have fired"
    )
