"""The 1-second capture shortlist: filter for admissibility, score to cut to N (§6 M4).

Two decisions are pinned here.

**The shortlist introduces no score of its own.** It ranks by M7's registered
:func:`liquidity_scores`, which is what makes it a **superset of every registered universe by
construction**: the universe is the top N of that same ordering, so a name cannot enter U300
without already being inside the 500. A second, differently-weighted score would break exactly
that, and would be a set of free parameters chosen after seeing the data -- the multiplicity
problem moved one layer down, which is the reason `top_n` refuses an unregistered N.

**The filter reports its reasons.** `liquidity_scores` drops an unscorable symbol silently, so
a caller cannot tell "excluded, no spread measured" from "never supplied". For the universe
that is tolerable; for acquisition it is not, because the shortlist decides what data will
exist, and a name missing from it is missing from the archive for as long as the archive runs.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from pips.data.breeze.campaign import CampaignPlan
from pips.universe.liquidity import SUPPORTED_N, SymbolStats, liquidity_scores, top_n
from pips.universe.shortlist import CAPTURE_SHORTLIST_N, build_shortlist

AS_OF = date(2026, 9, 3)


def stat(symbol: str, rank: float) -> SymbolStats:
    """A well-formed candidate whose liquidity rises with ``rank``."""
    return SymbolStats(
        symbol=symbol,
        median_rupee_volume=1_000_000.0 * (rank + 1),
        relative_spread=0.01 / (rank + 1),
        amihud=0.5 / (rank + 1),
        gap_rate=0.02 / (rank + 1),
    )


def population(size: int) -> list[SymbolStats]:
    return [stat(f"SYM{i:04d}", float(i)) for i in range(size)]


def test_the_shortlist_is_wider_than_the_widest_registered_universe() -> None:
    """The whole reason the number is 500.

    It is the stable-core buffer applied to DATA rather than to membership. A shortlist equal
    to U300 would mean every name entering the universe arrives with no 1-second history --
    a cold start on every refresh, and forward capture cannot be backfilled to repair it.
    """
    assert max(SUPPORTED_N) < CAPTURE_SHORTLIST_N


def test_the_shortlist_width_is_not_a_registered_universe_size() -> None:
    """500 must never become tradeable by being registered here.

    `top_n` refuses an N outside `SUPPORTED_N` because an arbitrary universe is one nobody
    pre-registered. The tempting way to make 500 work is to add it to that set -- which would
    silently authorise a U500 strategy. The shortlist is an ACQUISITION width: it decides what
    is recorded, never what is traded, and the two must not share a registry.
    """
    assert CAPTURE_SHORTLIST_N not in SUPPORTED_N


@pytest.mark.parametrize("n", sorted(SUPPORTED_N))
def test_every_registered_universe_fits_inside_the_shortlist(n: int) -> None:
    """The buffer invariant, against the real `top_n` rather than a restatement of the score.

    If this fails, a name can be in the tradeable universe while no 1-second data was ever
    captured for it -- and the gap is unrecoverable, because the sessions it needed have
    already happened.
    """
    pop = population(600)
    shortlist = build_shortlist(pop, as_of=AS_OF)
    universe = top_n(liquidity_scores(pop), n)

    assert set(universe) <= set(shortlist.symbols)


def test_the_shortlist_orders_by_the_registered_score_and_adds_no_weights_of_its_own() -> None:
    """The property the buffer rests on: one ordering, M7's, truncated at a different place."""
    pop = population(600)
    scores = liquidity_scores(pop)
    expected = sorted(scores, key=lambda s: (-scores[s], s))[:CAPTURE_SHORTLIST_N]

    assert list(build_shortlist(pop, as_of=AS_OF).symbols) == expected


@pytest.mark.parametrize(
    ("field", "value", "reason_names"),
    [
        ("median_rupee_volume", 0.0, "median_rupee_volume"),
        ("median_rupee_volume", math.nan, "median_rupee_volume"),
        ("relative_spread", math.inf, "relative_spread"),
        ("amihud", math.nan, "amihud"),
        ("gap_rate", math.nan, "gap_rate"),
    ],
)
def test_an_unmeasurable_symbol_is_rejected_by_the_field_that_failed(
    field: str, value: float, reason_names: str
) -> None:
    """A filter can say "I don't know"; a score cannot.

    This is the argument for filtering first. A composite would turn a missing spread into a
    middling z and admit the name on the strength of a number nobody measured -- the same
    defect as unknown coverage defaulting to covered. The reason names the field so the fix is
    a data question, not a debugging session.
    """
    pop = population(10)
    broken = SymbolStats(**{**vars(pop[3]), field: value})
    pop[3] = broken

    shortlist = build_shortlist(pop, as_of=AS_OF)

    assert broken.symbol not in shortlist.symbols
    assert reason_names in shortlist.rejected[broken.symbol]


def test_every_candidate_ends_up_in_exactly_one_of_the_three_outcomes() -> None:
    """Selected, rejected for a stated reason, or admissible-but-outranked.

    Kept separate on purpose: a name that ranked 501st was not rejected, and folding the two
    together would make a healthy shortlist look like 100 data failures -- or hide 100 real
    ones among the merely-outranked.
    """
    pop = population(40)
    pop[7] = SymbolStats(**{**vars(pop[7]), "relative_spread": math.nan})
    shortlist = build_shortlist(pop, as_of=AS_OF, n=10)

    selected, rejected = set(shortlist.symbols), set(shortlist.rejected)
    assert not (selected & rejected)
    assert selected | rejected <= {s.symbol for s in pop}
    assert len(selected) == 10
    assert shortlist.n_admissible == 39
    assert shortlist.outranked == 29


def test_an_admissible_set_smaller_than_n_is_not_padded() -> None:
    """Same rule as `top_n`: N is a maximum. Padding would name a symbol nobody measured, and
    the campaign would then spend calls on it."""
    shortlist = build_shortlist(population(12), as_of=AS_OF, n=100)

    assert len(shortlist.symbols) == 12
    assert shortlist.n_admissible == 12
    assert shortlist.outranked == 0


def test_a_population_with_no_cross_section_selects_nothing_rather_than_itself() -> None:
    """One measurable name is not a cross-section: there is nothing to be liquid *relative to*.

    It is admissible -- nothing about it is unmeasurable -- and still unselected, which the
    accounting has to show rather than quietly reporting a one-name shortlist.
    """
    shortlist = build_shortlist(population(1), as_of=AS_OF)

    assert shortlist.symbols == ()
    assert shortlist.n_admissible == 1
    assert shortlist.rejected == {}
    assert shortlist.outranked == 1


def test_ties_are_broken_on_the_symbol_so_the_shortlist_is_reproducible() -> None:
    """Rule 1. An identical cross-section scores every name 0.0, and a shortlist that depended
    on input order would capture a different 500 on a re-run of the same day."""
    identical = [
        SymbolStats(
            symbol=f"SYM{i:04d}",
            median_rupee_volume=5e6,
            relative_spread=0.01,
            amihud=0.5,
            gap_rate=0.02,
        )
        for i in range(20)
    ]
    forward = build_shortlist(identical, as_of=AS_OF, n=5)
    backward = build_shortlist(list(reversed(identical)), as_of=AS_OF, n=5)

    assert (
        forward.symbols
        == backward.symbols
        == ("SYM0000", "SYM0001", "SYM0002", "SYM0003", "SYM0004")
    )


def test_the_shortlist_records_the_day_its_cross_section_came_from() -> None:
    """The shortlist decides what data exists, so anything researched on that data inherits its
    selection. Choosing it from a cross-section AFTER the capture window would contaminate
    every result downstream, so the day is carried on the artifact and is required -- there is
    no default to omit. It is recorded, not verified: the stats carry no date to check against.
    """
    assert build_shortlist(population(5), as_of=AS_OF).as_of == AS_OF
    with pytest.raises(TypeError):
        build_shortlist(population(5))  # type: ignore[call-arg]


def test_a_full_shortlist_of_one_second_bars_costs_a_number_the_plan_computes() -> None:
    """The seeding estimate that has already been wrong twice, in code rather than in prose.

    500 symbols x 60 sessions x 23 calls per symbol-day (22,500 one-second candles at 1,000 a
    call) = 690,000, about 7.7 days of a 90k quota. Written down here so the figure moves when
    the arithmetic does, instead of being rediscovered in a document.
    """
    plan = CampaignPlan(
        symbols=[f"SYM{i:04d}" for i in range(CAPTURE_SHORTLIST_N)],
        days=[date(2026, 6, 10) + timedelta(days=i) for i in range(60)],
        interval="1second",
    )

    assert plan.calls_per_symbol_day == 23
    assert plan.estimated_calls == 690_000
