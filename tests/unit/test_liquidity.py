"""M7's liquidity score and the universe it ranks  (§6 M7, `[C-UNIV-01]`).

`U300` is not a list somebody supplies. It is **computed**: M7 specifies
`z(log median ₹vol) - 0.75·z(spread) - 0.50·z(Amihud) - 0.25·z(gap-rate)` with weights that are
*fixed, stress-tested, never P&L-tuned*, and N ∈ {50, 100, 150, 300}.

That phrase is the whole design. A weight the caller can pass is a weight somebody will tune
until the universe contains the names their strategy already liked — and a universe tuned on
P&L is a selection effect wearing the costume of an eligibility rule. So the weights are
constants and the scorer takes none.

**The z-scores are cross-sectional**, across symbols on one day. A time-series z would ask
"is this name liquid for itself lately", which every illiquid name passes.

**A symbol missing any component cannot be scored.** Defaulting a missing spread to zero makes
an illiquid name look tight, which is the flattering direction; excluding it is honest and the
exclusion is named.

**Signs matter and are stated**: volume helps, spread, Amihud and gap-rate hurt. A sign error
here ranks the worst names first and nothing downstream would notice.
"""

from __future__ import annotations

import inspect

import pytest

from pips.universe.liquidity import (
    WEIGHTS,
    SymbolStats,
    liquidity_scores,
    top_n,
)


def stats(symbol: str, **over: float) -> SymbolStats:
    base = {
        "median_rupee_volume": 1e7,
        "relative_spread": 0.001,
        "amihud": 1e-9,
        "gap_rate": 0.05,
    }
    base.update(over)
    return SymbolStats(symbol=symbol, **base)


def spread_of(names: list[SymbolStats]) -> dict[str, float]:
    return liquidity_scores(names)


# ------------------------------------------------------------- the weights are fixed -----


def test_the_scorer_takes_no_weights() -> None:
    """Structural. M7 says fixed, stress-tested, NEVER P&L-tuned — a parameter defeats that in
    one keyword, and nothing downstream would record that it had been passed."""
    taken = set(inspect.signature(liquidity_scores).parameters)
    assert not (taken & {"weights", "w", "coefficients", "alpha", "beta"}), taken


def test_the_weights_are_the_ones_m7_declares() -> None:
    assert WEIGHTS == {
        "median_rupee_volume": 1.0,
        "relative_spread": -0.75,
        "amihud": -0.50,
        "gap_rate": -0.25,
    }


# ------------------------------------------------------------------ signs and order -----


def test_more_volume_scores_higher() -> None:
    scores = spread_of(
        [stats("BIG", median_rupee_volume=1e9), stats("SMALL", median_rupee_volume=1e6)]
    )
    assert scores["BIG"] > scores["SMALL"]


@pytest.mark.parametrize("penalised", ["relative_spread", "amihud", "gap_rate"])
def test_a_worse_component_scores_lower(penalised: str) -> None:
    """One sign error ranks the worst names first, and the universe would look plausible."""
    base = stats("GOOD")
    worse = stats("BAD", **{penalised: getattr(base, penalised) * 100})
    scores = spread_of([base, worse])
    assert scores["GOOD"] > scores["BAD"]


def test_volume_enters_as_a_log_and_the_z_is_a_population_z() -> None:
    """THREE symbols, evenly spaced in log volume, and the other components identical.

    Two symbols cannot test this: a two-point z-score is always +/-1 whatever the values, so my
    first fixture compared two ratios and would have passed on a linear scale too. With three
    evenly log-spaced names the middle one sits exactly at the mean — under a LINEAR scale it
    does not, because 1e8 drags the mean above 1e7.

    The exact endpoint value also pins ddof: a population z over three points is
    sqrt(3/2) = 1.2247, where a sample z would be 1.0. Ordering alone cannot tell them apart,
    since ddof scales every score by the same factor.
    """
    scores = spread_of(
        [
            stats("LOW", median_rupee_volume=1e6),
            stats("MID", median_rupee_volume=1e7),
            stats("HIGH", median_rupee_volume=1e8),
        ]
    )

    assert scores["MID"] == pytest.approx(0.0, abs=1e-9), "the middle of an even log spacing"
    assert scores["HIGH"] == pytest.approx(1.224744871, rel=1e-6)
    assert scores["LOW"] == pytest.approx(-1.224744871, rel=1e-6)


# ------------------------------------------------------- cross-sectional, not per-name -----


def test_the_z_is_across_symbols_not_across_time() -> None:
    """A name is liquid relative to the OTHERS on the day. Scored alone it has no cross-section,
    so every name would pass — which is what a time-series z would do here."""
    alone = spread_of([stats("ONLY")])
    assert alone == {}


def test_a_degenerate_cross_section_contributes_nothing() -> None:
    """Identical values have no spread to divide by. Contributing zero is the conservative
    reading; dividing by float noise gives a z of 1e15 and one name takes the whole universe.
    """
    identical = spread_of([stats("A"), stats("B"), stats("C")])
    assert set(identical) == {"A", "B", "C"}
    assert all(abs(v) < 1e-9 for v in identical.values()), identical


# ------------------------------------------------------------- unscorable is excluded -----


@pytest.mark.parametrize(
    "missing", ["median_rupee_volume", "relative_spread", "amihud", "gap_rate"]
)
def test_a_symbol_missing_a_component_is_excluded(missing: str) -> None:
    """Defaulting a missing spread to zero makes an illiquid name look tight."""
    broken = stats("BROKEN", **{missing: float("nan")})
    scores = spread_of([stats("A"), stats("B"), broken])
    assert "BROKEN" not in scores


def test_a_non_positive_volume_cannot_be_logged() -> None:
    """A name that traded nothing has no log-volume, and clamping it to a floor invents one."""
    scores = spread_of([stats("A"), stats("B"), stats("DEAD", median_rupee_volume=0.0)])
    assert "DEAD" not in scores


# ------------------------------------------------------------------------- top_n -----


def test_top_n_takes_the_highest_scores() -> None:
    """A registered N, and a population larger than it, so truncation is actually exercised.

    My first version asked for the top 2 of 5 — which `SUPPORTED_N` refuses, and rightly: an
    unregistered universe size is one nobody pre-registered. Sixty names and N=50 tests the
    same property without arguing with the rule.
    """
    scores = {f"S{i:03d}": float(i) for i in range(60)}
    ranked = top_n(scores, 50)

    assert len(ranked) == 50
    assert ranked[0] == "S059", "the highest score must lead"
    assert set(scores) - set(ranked) == {f"S{i:03d}" for i in range(10)}


def test_top_n_breaks_ties_on_the_symbol() -> None:
    """Two runs of one day must name the same universe, and the tie is AT the boundary — where
    the choice actually decides membership rather than order."""
    # The tied LOSER is inserted FIRST, so a stable sort alone would keep it and only an
    # explicit tie-break on the symbol puts S049 in. Without that ordering the test passes with
    # the tie-break deleted, which is what let `ties-unbroken` survive.
    scores: dict[str, float] = {"S050": 11.0, "S049": 11.0}
    scores.update({f"S{i:03d}": float(100 - i) for i in range(49)})

    ranked = top_n(scores, 50)
    assert len(ranked) == 50
    assert "S049" in ranked, "the lower symbol takes the place"
    assert "S050" not in ranked


def test_top_n_returns_fewer_when_fewer_qualify() -> None:
    """Same rule as the top-5 report: N is a maximum, and padding it would name a universe
    member that was never scored."""
    assert top_n({"A": 1.0}, 300) == ("A",)


def test_an_unsupported_n_is_refused() -> None:
    """M7 declares N in {50, 100, 150, 300}. An arbitrary N is a universe nobody registered."""
    with pytest.raises(ValueError, match="300"):
        top_n({"A": 1.0}, 137)


# ---------------------------------------- the stable-core buffer `[C-UNIV-01]` -----


def ranked(names: list[str]) -> dict[str, float]:
    """Scores descending in the given order, so rank 1 is `names[0]`."""
    return {name: float(len(names) - i) for i, name in enumerate(names)}


def sixty() -> dict[str, float]:
    """A realistic cross-section: S000 is rank 1, S059 is rank 60.

    Small readable fixtures cannot be used here — `n` must be one of M7's registered sizes, and
    a universe size nobody pre-registered is exactly what `SUPPORTED_N` refuses. With n=50 and
    k=5 the buffer is ranks 46-55.
    """
    return {f"S{i:03d}": float(100 - i) for i in range(60)}


def test_an_incumbent_inside_the_band_is_kept() -> None:
    """The asymmetry IS the hysteresis: *enter above N-k; exit below N+k*.

    A name already in the universe survives a slip into the buffer. Without that, a name
    oscillating around rank N enters and leaves every refresh, and each round trip is a warm-up
    the panel pays for and a turnover the strategy did not ask for.
    """
    from pips.universe.liquidity import stable_core

    kept = stable_core(previous=("S052",), scores=sixty(), n=50, k=5)
    assert "S052" in kept, "rank 53 is inside the 46-55 buffer, and it was already a member"


def test_a_newcomer_inside_the_band_is_not_admitted() -> None:
    """The other half of the asymmetry. If the band admitted newcomers it would just be a wider
    universe, and nothing would be stabilised."""
    from pips.universe.liquidity import stable_core

    kept = stable_core(previous=(), scores=sixty(), n=50, k=5)
    assert "S052" not in kept
    assert len(kept) == 45, "newcomers must clear the TIGHTER bar, n-k"


def test_an_incumbent_below_the_wide_bar_is_dropped() -> None:
    from pips.universe.liquidity import stable_core

    kept = stable_core(previous=("S058",), scores=sixty(), n=50, k=5)
    assert "S058" not in kept, "rank 59 is below n+k=55"


def test_an_unscored_incumbent_cannot_be_kept() -> None:
    """A name with no score today was not measured today — suspended, delisted, or simply
    absent from the cross-section. Keeping it carries a universe member on stale evidence, and
    the panel would then contain a name with no bars.
    """
    from pips.universe.liquidity import stable_core

    kept = stable_core(previous=("GONE", "S000"), scores=sixty(), n=50, k=5)
    assert "GONE" not in kept
    assert "S000" in kept


def test_no_buffer_is_a_plain_top_n() -> None:
    """`k=0` is the "daily as stress" policy: no hysteresis, and it must reduce exactly."""
    from pips.universe.liquidity import stable_core, top_n

    scores = {f"S{i:03d}": float(100 - i) for i in range(60)}
    assert stable_core(previous=("S059",), scores=scores, n=50, k=0) == top_n(scores, 50)


def test_membership_stays_within_the_band() -> None:
    """Hysteresis lets the size drift, but only inside the buffer — a universe called U50 that
    quietly grows to 200 is not the policy that was registered."""
    from pips.universe.liquidity import stable_core

    scores = {f"S{i:03d}": float(100 - i) for i in range(100)}
    everyone = tuple(scores)
    kept = stable_core(previous=everyone, scores=scores, n=50, k=10)
    assert len(kept) <= 60


def test_a_negative_buffer_is_refused() -> None:
    """A negative k inverts the bars: names would have to be WORSE to stay."""
    from pips.universe.liquidity import stable_core

    with pytest.raises(ValueError, match="k"):
        stable_core(previous=(), scores=sixty(), n=50, k=-1)


def test_the_universe_size_is_still_registered() -> None:
    from pips.universe.liquidity import stable_core

    with pytest.raises(ValueError, match="300"):
        stable_core(previous=(), scores=sixty(), n=137, k=1)


def test_the_core_breaks_ties_on_the_symbol() -> None:
    """Two refreshes of one day must name the same universe.

    The tied loser is inserted FIRST, so a stable sort alone keeps it and only the explicit
    tie-break puts the right name in — the same shape that let `ties-unbroken` survive against
    `top_n`.
    """
    from pips.universe.liquidity import stable_core

    scores: dict[str, float] = {"S050": 11.0, "S049": 11.0}
    scores.update({f"S{i:03d}": float(100 - i) for i in range(49)})

    kept = stable_core(previous=(), scores=scores, n=50, k=0)
    assert "S049" in kept
    assert "S050" not in kept
