"""Pooling the trial registry's family means  (§6 M18).

:mod:`pips.validation.partial_pooling` is arithmetic. This is the thing that feeds it, and it
exists because a check nothing consults is a dead check — the lesson `check_unexplained_ratio_
jump` taught by being unit-tested at M5 and never called by the runner for a whole milestone.

What it has to get right is not the pooling but the SELECTION: which trials are a family's
evidence. Every exclusion here is a way to compute a confident number over the wrong rows.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from pips.search.registry import Registry, RunRecord
from pips.validation.family_pooling import pooled_family_means


def record(**over: object) -> RunRecord:
    base: dict[str, object] = {
        "config_hash": "a" * 64,
        "stage": "S1",
        "stage_rank": 1,
        "family": "A01",
        "universe_id": "U100",
        "session_mask": "MID",
        "capital_tier": "2L",
        "broker": "FLATTRADE",
        "data_snapshot": "nifty100-1m-2026H1",
        "snapshot_root": "b" * 64,
        "cost_model": "c" * 64,
        "fill_tier": "F1",
        "seed": 7,
        "git_sha": "d" * 40,
        "metrics": {"rank_ic": 0.03},
        "n_trades": 412,
        "daily_returns_ref": None,
        "status": "completed",
    }
    base.update(over)
    return RunRecord.model_validate(base)


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.db")


def fill(reg: Registry, family: str, values: list[float], **over: object) -> None:
    for i, v in enumerate(values):
        reg.record(record(family=family, seed=i, metrics={"rank_ic": v}, **over))


# ------------------------------------------------------------ the grouping -------------


def test_completed_runs_are_grouped_by_family_and_pooled(reg: Registry) -> None:
    fill(reg, "A01", [0.030, 0.034, 0.028, 0.032])
    fill(reg, "A05", [0.004, 0.002, 0.006, 0.003])
    report = pooled_family_means(reg, metric="rank_ic")

    assert set(report.pooling.estimates) == {"A01", "A05"}
    assert report.pooling.estimates["A01"].n == 4
    assert report.pooling.estimates["A01"].raw_mean > report.pooling.estimates["A05"].raw_mean


def test_the_metric_is_read_by_name_from_each_run(reg: Registry) -> None:
    # Two metrics per run; asking for one must not silently average the other.
    for i, v in enumerate((0.01, 0.03)):
        reg.record(record(family="A01", seed=i, metrics={"rank_ic": v, "sharpe": 9.0}))
    for i, v in enumerate((0.05, 0.07)):
        reg.record(record(family="A05", seed=i, metrics={"rank_ic": v, "sharpe": 9.0}))
    report = pooled_family_means(reg, metric="rank_ic")
    assert report.pooling.estimates["A01"].raw_mean == Decimal("0.02")


# ------------------------------------------------------------ the exclusions -----------


def test_runs_that_did_not_complete_are_excluded_and_counted(reg: Registry) -> None:
    """A failed or abandoned trial has no metric worth averaging.

    It still COUNTS for multiplicity (rule 4) — that is the registry's job and it keeps the
    row. It does not count as evidence about the family's mean, and the difference between
    those two ledgers has to be visible in the output rather than inferred from a smaller n.
    """
    fill(reg, "A01", [0.03, 0.04])
    fill(reg, "A05", [0.01, 0.02])
    reg.record(record(family="A01", seed=99, status="failed", metrics={"rank_ic": 9.0}))
    reg.record(record(family="A01", seed=98, status="abandoned", metrics={"rank_ic": 9.0}))

    report = pooled_family_means(reg, metric="rank_ic")
    assert report.pooling.estimates["A01"].n == 2
    assert report.excluded_not_completed == 2
    assert report.pooling.estimates["A01"].raw_mean == Decimal("0.035")


def test_viewed_trials_are_excluded_and_counted_separately(reg: Registry) -> None:
    """'viewed' is the rule-4 status: looked at, never run to completion.

    It is the one exclusion most likely to be mistaken for an oversight, so it is reported
    under its own name rather than folded in with failures.
    """
    fill(reg, "A01", [0.03, 0.04])
    fill(reg, "A05", [0.01, 0.02])
    reg.record(record(family="A01", seed=97, status="viewed", metrics={}))

    report = pooled_family_means(reg, metric="rank_ic")
    assert report.pooling.estimates["A01"].n == 2
    assert report.excluded_viewed == 1


def test_runs_with_no_family_are_excluded_and_counted(reg: Registry) -> None:
    # A run that names no family cannot be attributed to one. Dropping it silently would pool
    # over a subset with nothing in the output to say so.
    fill(reg, "A01", [0.03, 0.04])
    fill(reg, "A05", [0.01, 0.02])
    reg.record(record(family=None, seed=96))

    report = pooled_family_means(reg, metric="rank_ic")
    assert report.excluded_no_family == 1
    assert set(report.pooling.estimates) == {"A01", "A05"}


def test_a_run_missing_the_metric_is_refused_not_treated_as_zero(reg: Registry) -> None:
    """The flattering failure: a missing key defaulting to 0.0.

    A completed run whose metrics lack the requested key is not a run that scored zero. Reading
    it as zero drags that family's mean toward the grand mean, which looks exactly like honest
    shrinkage and is not.
    """
    fill(reg, "A01", [0.03, 0.04])
    fill(reg, "A05", [0.01, 0.02])
    reg.record(record(family="A01", seed=95, metrics={"sharpe": 1.2}))

    with pytest.raises(ValueError, match="rank_ic"):
        pooled_family_means(reg, metric="rank_ic")


def test_a_family_left_with_too_few_runs_is_refused_loudly(reg: Registry) -> None:
    # The exclusions above can leave a family with one usable run. That must surface as the
    # pooling refusal it is, not as a family quietly missing from the report.
    fill(reg, "A01", [0.03, 0.04])
    reg.record(record(family="A05", seed=0, metrics={"rank_ic": 0.01}))
    with pytest.raises(ValueError, match="observations"):
        pooled_family_means(reg, metric="rank_ic")


def test_an_empty_registry_is_refused(reg: Registry) -> None:
    with pytest.raises(ValueError, match="at least 2 families"):
        pooled_family_means(reg, metric="rank_ic")


# ------------------------------------------------------------ provenance ---------------


def test_the_report_says_which_metric_and_how_many_rows_it_read(reg: Registry) -> None:
    fill(reg, "A01", [0.03, 0.04])
    fill(reg, "A05", [0.01, 0.02])
    report = pooled_family_means(reg, metric="rank_ic")
    assert report.metric == "rank_ic"
    assert report.rows_read == 4
    assert report.rows_used == 4


def test_the_row_counts_account_for_every_row_read(reg: Registry) -> None:
    # rows_read must equal rows_used plus every exclusion. An exclusion path that forgets to
    # count is how a silent drop stays silent.
    fill(reg, "A01", [0.03, 0.04])
    fill(reg, "A05", [0.01, 0.02])
    reg.record(record(family="A01", seed=99, status="failed"))
    reg.record(record(family="A01", seed=97, status="viewed"))
    reg.record(record(family=None, seed=96))

    report = pooled_family_means(reg, metric="rank_ic")
    assert report.rows_read == 7
    assert (
        report.rows_used
        + report.excluded_not_completed
        + report.excluded_viewed
        + report.excluded_no_family
        == report.rows_read
    )
