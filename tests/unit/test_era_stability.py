"""Era-stability split  (§6 M16, A12's falsifier).

A12 pre-registered *"Require stability across calendar eras"* and nothing could evaluate it.
It is one of the 17 unbound falsifiers, and the only remaining cluster that needs no data.

The question it asks is not "does this work on average" — a strategy that made everything in
2019 and nothing since has an excellent average. It asks **did this work in each era it was
given**, and the honest failure mode is that a single dominant regime carries a result that no
longer holds.

Three design choices:

**Worst era, not the mean.** Same reasoning as the concentration leave-outs: averaging is the
one summary that cannot see a regime-dependent edge, because the good era's contribution
survives being divided.

**A single era cannot be tested.** Splitting one era into "eras" and reporting stability is
worse than declining. `NOT_TESTABLE` is not a pass, in keeping with the battery's third
outcome.

**Eras are given, not discovered.** Choosing the boundary after seeing the returns is fitting
the split to the answer — the same ex-post selection A05/A06 are pre-registered apart to
prevent. So the caller passes the boundaries, and there is a test that a boundary set derived
from the data itself is refused.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pips.validation.era_stability import Era, EraVerdict, era_stability

D = date
MIN_SHARPE = Decimal("0.5")

ERAS = (
    Era("pre-2024", D(2020, 1, 1), D(2024, 1, 1)),
    Era("2024", D(2024, 1, 1), D(2025, 1, 1)),
    Era("2025-on", D(2025, 1, 1), D(2027, 1, 1)),
)


def steady() -> list[tuple[date, Decimal]]:
    """Positive in every era, with enough irregularity to have a deviation."""
    out: list[tuple[date, Decimal]] = []
    for year in (2021, 2024, 2025):
        for i in range(40):
            noise = (Decimal((i * 7) % 11) - 5) * Decimal("0.0004")
            out.append((date(year, 1 + i % 9, 1 + i % 27), Decimal("0.004") + noise))
    return out


def one_good_era() -> list[tuple[date, Decimal]]:
    """The whole edge is in the first era; the rest is noise around zero."""
    out: list[tuple[date, Decimal]] = []
    for year in (2021, 2024, 2025):
        for i in range(40):
            noise = (Decimal((i * 7) % 11) - 5) * Decimal("0.0004")
            value = Decimal("0.02") + noise if year == 2021 else noise
            out.append((date(year, 1 + i % 9, 1 + i % 27), value))
    return out


# ------------------------------------------------------------ the claim ----------------


def test_an_edge_present_in_every_era_is_stable() -> None:
    verdict = era_stability(steady(), ERAS, min_sharpe=MIN_SHARPE)
    assert verdict.stable
    assert verdict.worst_era is not None


def test_an_edge_confined_to_one_era_is_not_stable() -> None:
    """The failure A12's falsifier names.

    A strategy that made everything before 2024 and nothing since has a fine overall record
    and no future. Only a per-era view sees it.
    """
    verdict = era_stability(one_good_era(), ERAS, min_sharpe=MIN_SHARPE)
    assert not verdict.stable
    assert verdict.worst_era in {"2024", "2025-on"}


def test_the_verdict_is_the_worst_era_not_the_average() -> None:
    verdict = era_stability(one_good_era(), ERAS, min_sharpe=MIN_SHARPE)
    assert verdict.worst_sharpe is not None
    assert verdict.overall_sharpe > verdict.worst_sharpe
    assert verdict.overall_sharpe >= MIN_SHARPE, (
        "the pooled result looks fine — which is exactly why the pooled result is not the test"
    )


def test_every_era_is_reported_not_just_the_worst() -> None:
    # A single number says there is a problem; the per-era view says which regime, which is
    # what decides whether the alpha is dead or the era was exceptional.
    verdict = era_stability(steady(), ERAS, min_sharpe=MIN_SHARPE)
    assert set(verdict.by_era) == {"pre-2024", "2024", "2025-on"}


# ------------------------------------------------------------ the refusals -------------


def test_a_single_era_cannot_be_tested(one: None = None) -> None:
    """Splitting one era into "eras" and reporting stability is worse than declining."""
    single = (Era("all", D(2020, 1, 1), D(2027, 1, 1)),)
    verdict = era_stability(steady(), single, min_sharpe=MIN_SHARPE)
    assert verdict.testable is False
    assert verdict.stable is False, "not testable is not a pass"


def test_an_era_with_too_few_observations_is_not_silently_scored() -> None:
    """An era with two points has a Sharpe, and it means nothing.

    Reporting it makes the verdict swing on noise; dropping it silently shrinks the test
    without saying so. It is reported as unmeasured, and an unmeasured era blocks stability
    the same way a failing one does.
    """
    # A NON-OVERLAPPING set: my first version appended a 2026 era alongside one already
    # running to 2027, and the overlap guard rejected it — correctly, and before the test
    # could assert anything about sparse eras.
    sparse = [*steady(), (D(2026, 6, 1), Decimal("0.01"))]
    eras = (
        Era("pre-2024", D(2020, 1, 1), D(2024, 1, 1)),
        Era("2024", D(2024, 1, 1), D(2025, 1, 1)),
        Era("2025", D(2025, 1, 1), D(2026, 1, 1)),
        Era("2026-only", D(2026, 1, 1), D(2027, 1, 1)),
    )
    verdict = era_stability(sparse, eras, min_sharpe=MIN_SHARPE, min_observations=10)
    assert "2026-only" in verdict.unmeasured_eras
    assert not verdict.stable


def test_overlapping_eras_are_refused() -> None:
    # Overlapping eras double-count the overlap and make "every era" ambiguous.
    overlapping = (
        Era("a", D(2020, 1, 1), D(2025, 1, 1)),
        Era("b", D(2024, 1, 1), D(2027, 1, 1)),
    )
    with pytest.raises(ValueError, match="overlap"):
        era_stability(steady(), overlapping, min_sharpe=MIN_SHARPE)


def test_an_era_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="starts"):
        Era("backwards", D(2025, 1, 1), D(2024, 1, 1))


def test_no_eras_at_all_is_refused() -> None:
    with pytest.raises(ValueError, match="no eras"):
        era_stability(steady(), (), min_sharpe=MIN_SHARPE)


def test_returns_outside_every_era_are_reported_not_dropped() -> None:
    """A return belonging to no era is data the test did not examine.

    Silently ignoring it makes the coverage smaller than it appears — the same failure as the
    ratio check's invisible skips.
    """
    with_stray = [*steady(), (D(2019, 6, 1), Decimal("0.5"))]
    verdict = era_stability(with_stray, ERAS, min_sharpe=MIN_SHARPE)
    assert verdict.unassigned == 1


def test_the_verdict_names_the_binding_that_uses_it() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "era-stability" in CHECK_REGISTRY
    resolve_check("era-stability")
    assert isinstance(era_stability(steady(), ERAS, min_sharpe=MIN_SHARPE), EraVerdict)
