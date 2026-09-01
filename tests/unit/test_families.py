"""A search per family, and S5 across the winners  (§6 M12/M19).

The last gap. Every piece has existed and none of them met: halving converges to one winner, so
a single family can never give S5 more than one candidate. `[C-DISP-01]` provides six drivers
that run on the fixture panel; this runs a search for each, PROMOTES each winner to a later
stage, and hands the promoted rows to `run_s5_from_registry`.

**A promotion is another look, not a copy.** The S1 rows stay and the promoted row is added, so
`multiplicity()` counts both — which is the established meaning here: M counts evaluations, and
a config re-evaluated at higher fidelity was looked at again.

**A family that fails is named, not dropped.** Six winners from six drivers, or a report saying
which family produced none and why.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from pips.alphas.dispatch import DRIVERS
from pips.search.families import run_family_searches
from pips.search.multiplicity import multiplicity
from pips.search.registry import Registry
from pips.search.s5 import StageStep
from pips.selection.pareto import Candidate

FIXTURES = Path("fixtures")


@pytest.fixture(scope="module")
def searched(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, object], Registry]:
    """One run of all six family searches, shared by the tests that only read it.

    Small budget and a two-point grid on purpose: the full ladder over six families is minutes
    of genuine as-of evaluation, and what these tests check is the wiring, not the numbers.
    """
    directory = tmp_path_factory.mktemp("families")
    registry = Registry(directory / "registry.db")
    report = run_family_searches(
        fixtures=FIXTURES,
        registry=registry,
        returns_dir=directory / "returns",
        grid_points=2,
        initial_budget=400,
        returns_bars=900,
    )
    return report, registry


# ------------------------------------------------------------ every family ------------


def test_every_driver_produced_a_winner(searched: tuple[dict[str, object], Registry]) -> None:
    report, _ = searched
    winners = report["winners"]
    assert isinstance(winners, dict)
    assert set(winners) == set(DRIVERS)
    assert all(w for w in winners.values())


def test_no_family_is_silently_missing(searched: tuple[dict[str, object], Registry]) -> None:
    """A family that failed must be named. Six of six, or a report that says which and why."""
    report, _ = searched
    assert report["families_run"] == len(DRIVERS)
    assert report["families_promoted"] == len(DRIVERS)
    assert report["failures"] == {}


def test_the_trials_are_recorded_for_every_family(
    searched: tuple[dict[str, object], Registry],
) -> None:
    _, reg = searched
    families = {r["family"] for r in reg.all_runs()}
    assert families == set(DRIVERS)


def test_multiplicity_counts_across_all_families(
    searched: tuple[dict[str, object], Registry],
) -> None:
    report, reg = searched
    assert multiplicity(reg).literal_count == len(reg.all_runs())
    assert multiplicity(reg).literal_count > len(DRIVERS), "more looks than families"
    assert report["trials_viewed"] == len(reg.all_runs())


# ------------------------------------------------------------ promotion ---------------


def test_each_winner_is_promoted_to_the_later_stage(
    searched: tuple[dict[str, object], Registry],
) -> None:
    report, reg = searched
    promoted = [r for r in reg.all_runs() if r["stage"] == report["promoted_stage"]]
    assert len(promoted) == len(DRIVERS)
    assert {r["family"] for r in promoted} == set(DRIVERS)


def test_promotion_adds_a_row_rather_than_moving_one(
    searched: tuple[dict[str, object], Registry],
) -> None:
    """The registry is append-only, and a promotion is another look at higher fidelity.

    Moving the row would erase the evidence that the config was also viewed at S1, which is a
    count rule 4 asks for.
    """
    _, reg = searched
    stages = {r["stage"] for r in reg.all_runs()}
    assert len(stages) == 2, "the S1 rows survive alongside the promoted ones"


def test_promoted_rows_carry_returns_and_the_selection_objectives(
    searched: tuple[dict[str, object], Registry],
) -> None:
    # Without both, S5 can neither sort nor cluster them.
    import json

    report, reg = searched
    for row in reg.all_runs():
        if row["stage"] != report["promoted_stage"]:
            continue
        assert row["daily_returns_ref"], "S5 clusters on returns"
        metrics = json.loads(row["metrics"])
        assert "net_return" in metrics
        assert "max_drawdown" in metrics


# ------------------------------------------------------------ the payoff --------------


def test_s5_selects_an_ensemble_from_the_promoted_winners(
    searched: tuple[dict[str, object], Registry],
) -> None:
    """The thing every M19 module was built for, running on rows a search actually produced.

    What is asserted is that every STAGE ran and accounted for its input — not that a particular
    number survived. I have now asserted an ensemble size on this data three times and been
    wrong twice: the members are noise draws, so how many are mutually non-dominated is a
    property of the draw. A frontier that leaves one survivor is the frontier working.
    """
    report, _ = searched
    ensemble = report["ensemble"]
    assert isinstance(ensemble, tuple)
    assert 1 <= len(ensemble) <= int(str(report["families_promoted"]))

    funnel = cast("tuple[StageStep, ...]", report["s5_funnel"])
    names = [step.name for step in funnel]
    assert names == [
        "registry-intake",
        "pareto-frontier",
        "correlation-clustering",
        "pairwise-correlation-gate",
    ]
    for step in funnel:
        assert step.admitted + len(step.dropped) == step.considered, step.name


def test_the_s5_funnel_accounts_for_every_promoted_candidate(
    searched: tuple[dict[str, object], Registry],
) -> None:
    report, _ = searched
    funnel = report["s5_funnel"]
    assert isinstance(funnel, tuple)

    # The intake step drops every S1 row, because S5 reads the PROMOTED stage. So the accounting
    # runs from what intake admitted, not from the driver count — a subtlety my first version of
    # this test got wrong by assuming the funnel started at the candidates.
    intake = next(s for s in funnel if s.name == "registry-intake")
    assert intake.admitted == len(DRIVERS)
    after = [cid for step in funnel if step.name != "registry-intake" for cid in step.dropped]
    assert len(after) + len(report["ensemble"]) == intake.admitted  # type: ignore[arg-type]


def test_a_winner_that_never_traded_is_named_rather_than_crashing_s5(tmp_path: Path) -> None:
    """A05 cannot trade in a window with no session boundary: a gap needs a prior close.

    Its PnL series is then flat, and S5's clustering correctly refuses a zero-variance series —
    but that refusal arrives from three modules away and names nothing. Caught at promotion, it
    is a statement about the window, and the other five families still form an ensemble.
    """
    # The floor guards the SEARCH window; this guards the PRESERVED one, and they are different
    # windows. A budget of 400 bars crosses a session boundary, so A05, A06 and A07 are searched
    # properly — and a preserved window of 300 bars crosses none, so their returns are flat and
    # cannot be correlated. The backstop is not made redundant by the floor; it covers the case
    # the floor does not look at.
    report = run_family_searches(
        fixtures=FIXTURES,
        registry=Registry(tmp_path / "short.db"),
        returns_dir=tmp_path / "rs",
        grid_points=2,
        initial_budget=400,
        returns_bars=300,
    )
    failures = report["failures"]
    assert isinstance(failures, dict)

    # BOTH session-structure families, not just A05. A07 is opening-range breakout and needs a
    # session's opening range the same way A05 needs a prior close, so a window inside one
    # session gives neither anything to trade. Asserting "exactly one fails" hardcoded the
    # driver set of the hour and broke the moment A07 joined it.
    assert {"A05", "A06", "A07"} <= set(failures)
    for alpha_id, reason in failures.items():
        assert "no trades in the preserved window" in reason, alpha_id
        assert alpha_id not in report["promoted"]  # type: ignore[operator]
    assert report["families_promoted"] == report["families_run"] - len(failures)  # type: ignore[operator]

    # S5 RAN on the rest rather than dying on the flat series, which is the point here. How many
    # survive is a separate question and belongs to the longer-window test: over 300 bars of one
    # session the five remaining alphas trade the same two random-walk symbols and correlate
    # heavily, so the pairwise gate collapses them to one — correct behaviour, not a failure.
    assert len(report["ensemble"]) >= 1  # type: ignore[arg-type]
    assert report["s5_admissible"] is True


def test_the_run_is_deterministic(tmp_path: Path) -> None:
    first = run_family_searches(
        fixtures=FIXTURES,
        registry=Registry(tmp_path / "a.db"),
        returns_dir=tmp_path / "ra",
        grid_points=2,
        initial_budget=120,
        returns_bars=300,
    )
    second = run_family_searches(
        fixtures=FIXTURES,
        registry=Registry(tmp_path / "b.db"),
        returns_dir=tmp_path / "rb",
        grid_points=2,
        initial_budget=120,
        returns_bars=300,
    )
    assert first["winners"] == second["winners"]
    assert [c.id for c in cast("tuple[Candidate, ...]", first["ensemble"])] == [
        c.id for c in cast("tuple[Candidate, ...]", second["ensemble"])
    ]


# ------------------------------------------------------------ warm-up, anticipated ----


@pytest.fixture(scope="module")
def below_floor(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, object], Registry]:
    """One run below three families' session floors, shared by the tests that read it."""
    directory = tmp_path_factory.mktemp("belowfloor")
    registry = Registry(directory / "registry.db")
    report = run_family_searches(
        fixtures=FIXTURES,
        registry=registry,
        returns_dir=directory / "returns",
        grid_points=2,
        initial_budget=120,
        returns_bars=300,
    )
    return report, registry


def test_a_family_below_its_session_floor_is_skipped_before_it_runs(
    below_floor: tuple[dict[str, object], Registry],
) -> None:
    """Declared, not discovered.

    At 120 bars the window crosses no session boundary at all (375 bars to a session), so A05,
    A06 and A07 can produce nothing — a gap needs a prior close and an opening range needs a
    session start. Until now the search scored all three at zero across every rung, halving
    eliminated their configs on noise, and the emptiness surfaced at promotion as a flat PnL
    series. The reason must name the BUDGET, not the flat series: one says the schedule was
    wrong, the other says the alpha was.
    """
    report, _ = below_floor
    failures = report["failures"]
    assert isinstance(failures, dict)
    assert {"A05", "A06", "A07"} <= set(failures)
    for alpha_id in ("A05", "A06", "A07"):
        assert "session" in failures[alpha_id]
        assert "no trades in the preserved window" not in failures[alpha_id], (
            f"{alpha_id} was caught after the fact rather than anticipated"
        )


def test_no_trials_are_recorded_for_a_family_that_never_ran(
    below_floor: tuple[dict[str, object], Registry],
) -> None:
    """Skipping happens BEFORE the search, so the ledger carries no looks it did not take.

    Recording rungs for a family whose schedule could not evaluate it would inflate the
    multiplicity denominator with trials that measured nothing.
    """
    _, registry = below_floor
    families = {r["family"] for r in registry.all_runs()}
    assert not ({"A05", "A06", "A07"} & families)


def test_at_a_budget_that_meets_the_floor_every_family_runs(
    searched: tuple[dict[str, object], Registry],
) -> None:
    # The shared fixture already runs at 400 bars, which crosses a boundary. Re-running the same
    # configuration to assert the same thing was a fifth full family search for nothing.
    report, _ = searched
    assert report["failures"] == {}
    assert report["families_promoted"] == len(DRIVERS)
