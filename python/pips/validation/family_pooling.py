"""Pooling the trial registry's family means  (§6 M18).

:mod:`pips.validation.partial_pooling` is arithmetic; this is what feeds it. It exists so the
estimator has a caller — a check nothing consults is a dead check, which is what
``check_unexplained_ratio_jump`` was for a whole milestone while passing its own unit tests.

The pooling is the easy half. The hard half is SELECTION: deciding which trials are a family's
evidence. Three exclusions are unavoidable and each is a way to compute a confident number over
the wrong rows, so each is counted and reported rather than applied quietly:

* **not completed** — a failed or abandoned trial has no metric worth averaging. It still
  counts for multiplicity (rule 4) and the registry keeps its row; it is not evidence about the
  family's mean. Those are two different ledgers and the output has to show both.
* **viewed** — the rule-4 status: looked at, never run. The exclusion most likely to be
  mistaken for an oversight, so it is named separately rather than folded in with failures.
* **no family** — a run that names no family cannot be attributed to one.

A completed run whose metrics lack the requested key is **refused, not read as zero**. Zero is
a score; a missing key is the absence of one, and substituting the first for the second drags
that family toward the grand mean in a way indistinguishable from honest shrinkage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pips.validation.partial_pooling import PoolingResult, partial_pool

if TYPE_CHECKING:
    from pips.search.registry import Registry

__all__ = ["FamilyPoolingReport", "pooled_family_means"]

_USABLE_STATUS = "completed"


@dataclass(frozen=True)
class FamilyPoolingReport:
    """The pooled estimates, plus the accounting that says what they were computed over."""

    metric: str
    rows_read: int
    rows_used: int
    excluded_not_completed: int
    excluded_viewed: int
    excluded_no_family: int
    pooling: PoolingResult


def pooled_family_means(registry: Registry, *, metric: str) -> FamilyPoolingReport:
    """Group completed trials by family and shrink each family's mean toward the grand mean."""
    rows = registry.all_runs()
    observations: dict[str, list[Decimal]] = {}
    not_completed = viewed = no_family = 0

    for row in rows:
        status = row["status"]
        if status == "viewed":
            viewed += 1
            continue
        if status != _USABLE_STATUS:
            not_completed += 1
            continue
        family = row["family"]
        if family is None:
            no_family += 1
            continue

        metrics = json.loads(row["metrics"])
        if metric not in metrics:
            raise ValueError(
                f"run {row['run_id']} (family {family}) completed without a {metric!r} metric. "
                "Refusing rather than reading it as zero: zero is a score, a missing key is the "
                "absence of one, and the difference moves the family's mean."
            )
        observations.setdefault(family, []).append(Decimal(str(metrics[metric])))

    used = sum(len(v) for v in observations.values())
    return FamilyPoolingReport(
        metric=metric,
        rows_read=len(rows),
        rows_used=used,
        excluded_not_completed=not_completed,
        excluded_viewed=viewed,
        excluded_no_family=no_family,
        # Refuses on one family, or on a family the exclusions left with a single run. That
        # surfaces as an error rather than as a family quietly absent from the report.
        pooling=partial_pool(observations),
    )
