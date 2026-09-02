"""The S4 deflated-Sharpe gate  `[G-S4-DSR]` (§3.6, M18).

**The gate is applied at N = M, never at N = M_erank.** Understating the trial count *raises*
the DSR, and `M_erank ≤ M` always, so deflating by the effective count is the flattering
direction. Both ends are computed and reported — §3.6 asks for the bracket, and a single number
hides which N produced it — but only the conservative end decides.

**N is every trial ever viewed, not the candidates in front of the gate.** A gate that deflates
by "how many am I looking at right now" understates N by everything the funnel already
discarded, which is most of them. That is rule 4 made operational, and it is the difference
between a real correction and a decorative one: `multiplicity(registry)` counts completed,
failed, abandoned and viewed alike.

**A candidate that cannot be scored is named and refused.** Never silently dropped — a
disappearing candidate shrinks the population the funnel reports on — and never admitted, because
a series too short to estimate a Sharpe is not evidence of a good one.

The Sharpe here is at the observation frequency, not annualised: `probabilistic_sharpe_ratio`
pairs it with `n`, and scaling one without the other would misstate the confidence rather than
the return.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from pips.search.multiplicity import multiplicity
from pips.validation.deflated_sharpe import deflated_sharpe_ratio
from pips.validation.romano_wolf import romano_wolf

if TYPE_CHECKING:
    from pips.search.registry import Registry

__all__ = [
    "DSR_MIN",
    "MIN_OBSERVATIONS",
    "SPA_ALPHA",
    "SPA_BLOCK_LENGTH",
    "SPA_BOOTSTRAP",
    "SPA_SEED",
    "DsrBracket",
    "S4Report",
    "SpaReport",
    "gate_s4",
    "spa_adjusted_p",
]

DSR_MIN = 0.95
"""From `G-S4-DSR` in `gates.yaml`, and a test holds the two equal — the ledger is where a bar
is read from, and code that keeps its own copy is code that can drift from the ledger silently."""

MIN_OBSERVATIONS = 3
"""Below this there is no third or fourth moment to speak of. `probabilistic_sharpe_ratio`
refuses fewer than 2; this refuses a little earlier and says why, rather than letting a
degenerate skew and kurtosis decide a gate."""


@dataclass(frozen=True)
class DsrBracket:
    """One candidate's DSR at both ends of §3.6's `(M_erank, M)` bracket."""

    run_id: str
    sharpe: float
    observations: int
    dsr_at_literal: float
    """At N = M. The conservative end, and the only one the verdict reads."""
    dsr_at_effective: float
    """At N = M_erank. Reported, never decisive: it is always the more flattering number."""
    passes: bool


@dataclass(frozen=True)
class S4Report:
    admitted: tuple[DsrBracket, ...]
    rejected: tuple[DsrBracket, ...]
    excluded: tuple[str, ...]
    """Candidates that could not be scored, each with its reason. Refused, not dropped."""
    trials_literal: int
    trials_effective: float | None
    sharpe_variance: float


def _moments(series: np.ndarray) -> tuple[float, float, float, int]:
    """Sharpe, skew and RAW kurtosis at the observation frequency, plus the count."""
    n = int(series.size)
    mean = float(np.mean(series))
    # Population sd, matching the moment estimators below; mixing ddof between the Sharpe and
    # the moments would make the PSR variance term describe a different sample.
    sd = float(np.std(series))
    sharpe = mean / sd
    centred = (series - mean) / sd
    skew = float(np.mean(centred**3))
    kurtosis = float(np.mean(centred**4))
    return sharpe, skew, kurtosis, n


def gate_s4(registry: Registry, *, stage: str) -> S4Report:
    """Score every completed candidate at ``stage`` and admit those clearing `DSR_MIN` at N = M."""
    counts = multiplicity(registry)
    scored: list[tuple[str, float, float, float, int]] = []
    excluded: list[str] = []

    for row in registry.all_runs():
        if row["stage"] != stage or row["status"] != "completed":
            continue
        run_id = str(row["run_id"])
        if not row["daily_returns_ref"]:
            excluded.append(f"{run_id}: no daily returns recorded, so it cannot be scored")
            continue
        series = np.asarray(
            pl.read_parquet(row["daily_returns_ref"])["daily_return"].to_list(), dtype=float
        )
        if series.size < MIN_OBSERVATIONS:
            excluded.append(
                f"{run_id}: {series.size} observation(s), fewer than {MIN_OBSERVATIONS} — a "
                "series too short to estimate a Sharpe is not evidence of a good one"
            )
            continue
        if float(np.std(series)) == 0.0:
            excluded.append(f"{run_id}: the return series is flat, so its Sharpe is undefined")
            continue
        sharpe, skew, kurtosis, n = _moments(series)
        scored.append((run_id, sharpe, skew, kurtosis, n))

    # Across trials, not within one: the deflation asks how far the BEST of many would drift
    # under a null, and that depends on how much the trial Sharpes vary.
    variance = float(np.var([s for _, s, _, _, _ in scored])) if len(scored) > 1 else 0.0

    admitted: list[DsrBracket] = []
    rejected: list[DsrBracket] = []
    effective = counts.effective_count
    for run_id, sharpe, skew, kurtosis, n in scored:
        try:
            at_literal = deflated_sharpe_ratio(
                sharpe, n, skew, kurtosis, counts.literal_count, variance
            )
            at_effective = (
                at_literal
                if effective is None
                else deflated_sharpe_ratio(
                    sharpe, n, skew, kurtosis, max(1, round(effective)), variance
                )
            )
        except ValueError as exc:
            excluded.append(f"{run_id}: {exc}")
            continue
        bracket = DsrBracket(
            run_id=run_id,
            sharpe=sharpe,
            observations=n,
            dsr_at_literal=at_literal,
            dsr_at_effective=at_effective,
            # The LITERAL end decides. Reading the effective one would admit strictly more,
            # every time, and always in the direction the author would prefer.
            passes=at_literal >= DSR_MIN,
        )
        (admitted if bracket.passes else rejected).append(bracket)

    # No re-sorting. `Registry.all_runs` is `ORDER BY run_id`, and filtering preserves order, so
    # every list here is already in numeric run order. A sort on top of that is a claim no test
    # can distinguish -- and worse, sorting `excluded` as STRINGS would put run 10 before run 2.
    # The numeric-order test pins the contract at its real source instead.
    return S4Report(
        admitted=tuple(admitted),
        rejected=tuple(rejected),
        excluded=tuple(excluded),
        trials_literal=counts.literal_count,
        trials_effective=effective,
        sharpe_variance=variance,
    )


SPA_BOOTSTRAP = 500
"""Resamples for the stepdown. Fixed rather than a parameter: a p-value recorded in a dossier
must not depend on how patient the caller was feeling."""

SPA_BLOCK_LENGTH = 5
"""Mean block length for the stationary bootstrap. Daily returns of an intraday strategy carry
short-horizon dependence, and an i.i.d. resample would understate the variance and so the
p-value — the flattering direction."""

SPA_SEED = 20260902
"""Fixed so two runs of one cycle produce the same evidence (rule 1).

Any fixed function of the family would be equally deterministic, so `seed + len(models)` is an
EQUIVALENT mutant and no test distinguishes it. A constant is chosen because a seed derived from
the population changes the draws when a candidate is added for unrelated reasons, and then two
reports differ for a cause nobody can see in either."""

SPA_ALPHA = 0.10
"""Only reaches `RomanoWolfResult.rejected`, which this does not read. The adjusted p-values are
alpha-independent by construction; passing the gate's own level keeps the unused half of the
result consistent with `[G-P4-SPA]` rather than arbitrary."""


@dataclass(frozen=True)
class SpaReport:
    """Per-candidate stepdown-adjusted p-values against a zero benchmark."""

    adjusted_p: dict[str, float]
    excluded: tuple[str, ...]


def spa_adjusted_p(registry: Registry, *, stage: str) -> SpaReport:
    """Per-candidate SPA evidence for the completed runs at ``stage``.

    The benchmark is **zero** — cash — so a strategy's performance differential against it is
    its return series unchanged. That is the right null for an intraday cash strategy that is
    flat overnight, and it is stated because a differential against an unnamed benchmark is a
    number nobody can reproduce.

    Per-candidate, not family-wise: `spa_test` returns one p-value earned by the BEST model, and
    writing that into every dossier would hand candidate five the evidence candidate one
    produced. The stepdown's adjusted p-value is defensible for each on its own.
    """
    series: dict[str, list[Decimal]] = {}
    excluded: list[str] = []

    for row in registry.all_runs():
        if row["stage"] != stage or row["status"] != "completed":
            continue
        run_id = str(row["run_id"])
        if not row["daily_returns_ref"]:
            excluded.append(f"{run_id}: no daily returns recorded, so it cannot be scored")
            continue
        values = pl.read_parquet(row["daily_returns_ref"])["daily_return"].to_list()
        series[run_id] = [Decimal(str(v)) for v in values]

    if not series:
        # `romano_wolf` refuses an empty family, and rightly -- but an empty family here means
        # nothing reached the stage, which is a finding, not a crash mid-search.
        return SpaReport(adjusted_p={}, excluded=tuple(excluded))

    lengths = {len(v) for v in series.values()}
    if len(lengths) != 1:
        raise ValueError(
            f"candidates at stage {stage} have return series of differing length "
            f"{sorted(lengths)}. Truncating to the common length aligns them at index 0, which "
            "is only correct if every run started on the same day -- otherwise it compares one "
            "strategy's first days against another's and calls the result a p-value."
        )

    result = romano_wolf(
        series,
        alpha=SPA_ALPHA,
        n_bootstrap=SPA_BOOTSTRAP,
        block_length=SPA_BLOCK_LENGTH,
        seed=SPA_SEED,
    )
    return SpaReport(adjusted_p=dict(result.adjusted_p), excluded=tuple(excluded))
