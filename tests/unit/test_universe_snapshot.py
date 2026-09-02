"""M7's universe snapshot: the six pieces in the order that matters  (`[C-UNIV-06]`).

The composition carries correctness the pieces do not.

**Eligibility is applied BEFORE scoring.** The liquidity score is a *cross-sectional* z, so every
name in the population shifts the mean and spread for every other. A suspended name that cannot
be traded still moving everyone else's rank is a name influencing a selection it is barred from
— and the effect is invisible, because the ranking that comes out looks like any other.

**An ineligible incumbent exits regardless of the buffer.** The stable-core buffer exists to
damp *score* churn; it was never a licence to keep trading a suspended stock. Hysteresis over an
eligibility failure is the buffer being used for something it was not argued for.

**Every exclusion is named**, and the two kinds stay apart: a name that failed a gate and a name
whose statistics could not be computed are different problems.
"""

from __future__ import annotations

from pips.universe.eligibility import EligibilityInputs
from pips.universe.liquidity import SymbolStats
from pips.universe.snapshot import (
    UniverseCandidate,
    UniverseSnapshot,
    universe_snapshot,
)


def candidate(symbol: str, *, volume: float = 1e7, **elig: object) -> UniverseCandidate:
    eligibility = {
        "symbol": symbol,
        "series": "EQ",
        "suspended": False,
        "trade_to_trade": False,
        "unresolved_symbol_change": False,
        "sessions_listed": 500,
        "corporate_action_certain": True,
    }
    eligibility.update(elig)
    return UniverseCandidate(
        eligibility=EligibilityInputs(**eligibility),  # type: ignore[arg-type]
        stats=SymbolStats(
            symbol=symbol,
            median_rupee_volume=volume,
            relative_spread=0.001,
            amihud=1e-9,
            gap_rate=0.05,
        ),
    )


def population(count: int = 60) -> list[UniverseCandidate]:
    return [candidate(f"S{i:03d}", volume=10.0 ** (6 + i / 10)) for i in range(count)]


def snap(candidates: list[UniverseCandidate], **over: object) -> UniverseSnapshot:
    kwargs: dict[str, object] = {
        "candidates": candidates,
        "previous": (),
        "n": 50,
        "k": 5,
        "min_sessions_listed": 250,
    }
    kwargs.update(over)
    return universe_snapshot(**kwargs)  # type: ignore[arg-type]


# ------------------------------------------------ eligibility comes before scoring -----


def test_an_ineligible_name_does_not_move_anyone_elses_score() -> None:
    """The reason the order matters, stated as an equality.

    Scoring first and filtering after leaves a barred name inside the cross-section, where it
    shifts the mean and spread for every name that can trade. The ranking that comes out looks
    exactly like an honest one.
    """
    clean = snap(population())
    with_outlier = snap([*population(), candidate("BARRED", volume=1e15, suspended=True)])

    assert clean.members == with_outlier.members
    assert clean.scores == with_outlier.scores


def test_an_ineligible_name_is_never_a_member() -> None:
    result = snap([*population(), candidate("SUSP", volume=1e15, suspended=True)])
    assert "SUSP" not in result.members
    assert "suspended" in " ".join(result.excluded["SUSP"])


def test_an_undetermined_name_is_excluded_and_named_apart() -> None:
    result = snap([*population(), candidate("UNKNOWN", volume=1e15, suspended=None)])
    assert "UNKNOWN" not in result.members
    assert "could not be resolved" in " ".join(result.excluded["UNKNOWN"])


# ------------------------------------------- the buffer is not a licence to trade -----


def test_an_ineligible_incumbent_exits_despite_the_buffer() -> None:
    """The buffer damps SCORE churn. It was never argued for as a reason to keep trading a
    suspended stock, and using it that way is the mechanism doing something it was not built
    for."""
    people = population()
    people[0] = candidate("S000", volume=10.0**6, suspended=True)

    result = snap(people, previous=("S000",))
    assert "S000" not in result.members


def test_an_eligible_incumbent_inside_the_buffer_is_kept() -> None:
    """And the buffer still works for what it IS for."""
    people = population()
    result = snap(people, previous=("S007",))
    ranks = sorted(people, key=lambda c: -c.stats.median_rupee_volume)
    assert ranks[52].stats.symbol == "S007"
    assert "S007" in result.members


# ----------------------------------------------------------------- unscorable names -----


def test_a_name_that_cannot_be_scored_is_excluded_and_named() -> None:
    """Eligible to trade, but with no usable statistics — a different problem from a failed
    gate, and a different fix."""
    result = snap([*population(), candidate("NOVOL", volume=0.0)])
    assert "NOVOL" not in result.members
    assert "score" in " ".join(result.excluded["NOVOL"]).lower()


def test_the_snapshot_reports_how_many_were_scored() -> None:
    result = snap([*population(), candidate("SUSP", suspended=True)])
    assert result.scored == 60, "the barred name never entered the cross-section"
