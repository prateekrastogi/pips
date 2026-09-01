"""The S1 smoke, as a recorded search  (§6 M12/M19, rule 4).

`record_halving_trials` writes rows and `multiplicity()` reads them, and until something runs a
real schedule the ledger stays empty on every registry the project actually produces. This runs
successive halving over A01 parameter variants on the fixture panel and records every look.

**The point is not the winner.** The fixtures are two synthetic symbols from a seeded random
walk, so any IC is noise — and a search over noise always returns a winner with a flattering
score. That is exactly the thing §3.6 exists to deflate, so the report carries the multiplicity
bracket beside the winner's raw score and never the raw score alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pips.search.multiplicity import multiplicity
from pips.search.registry import Registry
from pips.search.s1 import run_s1_search
from pips.search.trials import fixture_snapshot_root

FIXTURES = Path("fixtures")


@pytest.fixture(scope="module")
def searched(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, object], Registry]:
    """One real search, shared by every test that only reads its result.

    Module-scoped deliberately: the ladder is 4@400 + 2@800 + 1@1600 bars of genuine
    as-of evaluation, and re-running it per test made this file take 111 seconds. The
    determinism test below still runs its own two searches, because that is the thing it
    measures.
    """
    directory = tmp_path_factory.mktemp("s1search")
    registry = Registry(directory / "registry.db")
    report = run_s1_search(fixtures=FIXTURES, registry=registry, returns_dir=directory / "returns")
    return report, registry


# ------------------------------------------------------------ the ledger --------------


def test_the_search_records_every_look_it_took(
    searched: tuple[dict[str, object], Registry],
) -> None:
    report, reg = searched
    assert report["trials_viewed"] == len(reg.all_runs())
    assert int(str(report["trials_viewed"])) > int(str(report["candidates"]))


def test_the_multiplicity_ledger_is_no_longer_empty(
    searched: tuple[dict[str, object], Registry],
) -> None:
    """The whole point of the chain: a registry the project produced, with a count in it."""
    _, reg = searched
    assert multiplicity(reg).literal_count == len(reg.all_runs()) > 0


def test_eliminated_variants_are_in_the_ledger(
    searched: tuple[dict[str, object], Registry],
) -> None:
    report, reg = searched
    statuses = {r["status"] for r in reg.all_runs()}
    assert "viewed" in statuses, "the eliminated rungs are recorded"
    assert "completed" in statuses
    assert report["winner"] is not None


# ------------------------------------------------------------ the budget --------------


def test_the_budget_actually_changes_the_evaluation(
    searched: tuple[dict[str, object], Registry],
) -> None:
    """Otherwise the halving schedule is theatre.

    A score that ignores its budget makes every rung identical, so elimination is decided by the
    tie-break and the search is an expensive way to sort names.

    Counting how many distinct budgets appear does NOT test this — the budgets exist either way,
    because the schedule sets them. What tests it is the same config scoring DIFFERENTLY at two
    of them.
    """
    report, reg = searched
    winner = str(report["winner"])
    by_config: dict[str, list[float]] = {}
    for row in reg.all_runs():
        metrics = json.loads(row["metrics"])
        if "rank_ic" in metrics:
            by_config.setdefault(str(row["config_hash"]), []).append(metrics["rank_ic"])

    repeated = [ics for ics in by_config.values() if len(ics) > 1]
    assert repeated, f"{winner} survives several rungs, so some config was scored twice"
    assert any(len(set(ics)) > 1 for ics in repeated), (
        "a config scored identically at every budget means the budget was ignored"
    )


def test_the_scores_recorded_are_the_scores_that_decided(
    searched: tuple[dict[str, object], Registry],
) -> None:
    # A row whose metrics do not match the score used for elimination is a ledger of something
    # other than the search that happened.
    report, reg = searched
    completed = [r for r in reg.all_runs() if r["status"] == "completed"]
    assert completed
    assert any(str(report["winner_score"]) in str(r["metrics"]) for r in completed)


# ------------------------------------------------------------ provenance ---------------


def test_every_row_pins_the_fixtures_it_read(searched: tuple[dict[str, object], Registry]) -> None:
    _, reg = searched
    expected = fixture_snapshot_root(FIXTURES)
    assert {r["snapshot_root"] for r in reg.all_runs()} == {expected}


def test_every_trial_keeps_returns_so_the_coverage_is_complete(
    searched: tuple[dict[str, object], Registry],
) -> None:
    """M_erank must be computed over the same population M counts.

    Preserving only the final rung would leave an effective rank measured on 1 of 7 trials,
    which reads exactly like an effective rank of 1 measured on all 7 — a number that looks
    like a finding about correlation and is really a statement about coverage.
    """
    _, reg = searched
    assert all(r["daily_returns_ref"] for r in reg.all_runs())


def test_the_preserved_series_are_all_the_same_length(
    searched: tuple[dict[str, object], Registry],
) -> None:
    _, reg = searched
    matrix = reg.daily_returns_matrix()
    assert matrix is not None
    assert matrix.shape[1] == len([r for r in reg.all_runs() if r["daily_returns_ref"]])


# ------------------------------------------------------------ honesty -----------------


def test_the_winner_is_reported_with_its_deflation_never_alone(
    searched: tuple[dict[str, object], Registry],
) -> None:
    """A search over a random walk returns a winner with a flattering score, every time.

    Reporting that number by itself would be the exact error §3.6 exists to prevent, so the
    bracket is part of the same report and a test holds it there.
    """
    report, _ = searched
    assert "winner_score" in report
    assert "multiplicity_literal" in report
    assert "multiplicity_effective" in report
    assert int(str(report["multiplicity_literal"])) > 1

    # STRICTLY between 1 and M. Exactly 1.0 was what this reported while only the final rung
    # preserved returns — an effective rank measured on one series, which is 1 by construction
    # rather than by measurement, and which understates the deflation at the optimistic end of
    # the bracket. Below M because the variants are correlated and repeated looks at one config
    # are not independent trials.
    effective = float(str(report["multiplicity_effective"]))
    assert 1.0 < effective < int(str(report["multiplicity_literal"]))


def test_the_report_says_the_fixtures_cannot_contain_an_edge(
    searched: tuple[dict[str, object], Registry],
) -> None:
    report, _ = searched
    assert report["_is_an_edge"] is False


# ------------------------------------------------------------ determinism -------------


def test_two_runs_on_the_same_fixtures_agree(tmp_path: Path) -> None:
    """Rule 1. A search whose winner moves between runs has not searched anything."""
    first_reg = Registry(tmp_path / "one.db")
    second_reg = Registry(tmp_path / "two.db")
    first = run_s1_search(fixtures=FIXTURES, registry=first_reg, returns_dir=tmp_path / "r1")
    second = run_s1_search(fixtures=FIXTURES, registry=second_reg, returns_dir=tmp_path / "r2")

    assert first["winner"] == second["winner"]
    assert first["winner_score"] == second["winner_score"]
    assert [r["config_hash"] for r in first_reg.all_runs()] == [
        r["config_hash"] for r in second_reg.all_runs()
    ]
