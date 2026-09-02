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
from pips.validation.bootstrap import stationary_bootstrap
from pips.validation.deflated_sharpe import deflated_sharpe_ratio
from pips.validation.pbo import PBOResult, probability_of_backtest_overfitting
from pips.validation.plateau import ParameterPoint, plateau_ratio
from pips.validation.romano_wolf import romano_wolf

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from pips.search.registry import Registry

__all__ = [
    "BLOCK_LENGTH",
    "CI_LEVEL",
    "CVAR_LEVEL",
    "DSR_MIN",
    "MIN_OBSERVATIONS",
    "PBO_BLOCKS",
    "PBO_HORIZON",
    "SPA_ALPHA",
    "SPA_BLOCK_LENGTH",
    "SPA_BOOTSTRAP",
    "SPA_SEED",
    "DsrBracket",
    "S4Report",
    "SpaReport",
    "bootstrap_sharpe_ci",
    "gate_s4",
    "pbo_for_configs",
    "plateau_for_winner",
    "report_card_economics",
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
        if series.min() == series.max():
            # NOT `np.std(...) == 0.0`. The standard deviation of a constant array is only
            # exactly zero for some lengths -- 60 gives 0.0 and 100 gives 2.2e-19 -- so the
            # exact comparison lets a flat series through at most lengths and divides by the
            # noise, producing a Sharpe around 4.6e15 that clears every threshold there is.
            # `min == max` is exact and length-independent.
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

BLOCK_LENGTH = 5
"""Mean block length for the stationary bootstrap, shared by the stepdown and the CI.

A property of the DATA, not of the test using it: daily returns of an intraday strategy carry
short-horizon dependence, and an i.i.d. resample understates the variance — for the p-value and
for the interval alike, both in the flattering direction."""

SPA_BLOCK_LENGTH = BLOCK_LENGTH
"""Kept as a name for the stepdown's use of it."""

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


def plateau_for_winner(
    *,
    winner: str,
    candidates: Sequence[str],
    score: Callable[[str], Decimal],
) -> Decimal | None:
    """`[G-P4-PLATEAU]`'s ratio for a search winner, perturbing one grid step either way.

    The neighbours are scored **fresh**, at the winner's own fidelity. Successive halving
    eliminates most configs at low budget, so its surface has holes exactly where the plateau
    matters — around the winner — and a ratio computed from what halving happened to leave
    behind would measure the search's bookkeeping rather than the parameter's robustness. The
    S3 battery describes a deliberate perturbation study, and this is one.

    ``None`` for a winner at the grid EDGE: one-sided evidence is not a plateau. An optimum at
    the boundary of the pre-registered domain is precisely the case where the honest answer is
    "we cannot tell", because the surface continues outside the range nobody registered. That
    reaches the dossier as unsupplied and `[C-CERT-01]` refuses to certify on it.

    Exactly three evaluations: the winner and its two neighbours.
    """
    if winner not in candidates:
        raise ValueError(
            f"{winner!r} is not on the grid, so it has no neighbours to perturb toward. A "
            "winner the search cannot locate is a winner nobody can reproduce."
        )
    index = list(candidates).index(winner)
    points = [
        ParameterPoint(coords=(offset,), score=score(candidates[offset]))
        for offset in (index - 1, index, index + 1)
        if 0 <= offset < len(candidates)
    ]
    return plateau_ratio(points, centre=(index,))


PBO_BLOCKS = 8
"""CSCV splits S blocks into two halves of S/2, so S must be even -- an odd one loses the
symmetry the method is named for. Eight gives C(8,4)=70 splits: enough for a stable fraction,
cheap enough to run per family. Sixteen is the literature's usual choice and gives 12,870."""

PBO_HORIZON = 1
"""Bars purged at a CROSSING block boundary. The forecast horizon here is one bar -- enter at i,
exit at i+1 -- so a label spans exactly one boundary, and not purging it lets the last in-sample
observation carry information about the first out-of-sample one."""


def pbo_for_configs(series_by_config: Mapping[str, Sequence[float]]) -> PBOResult | None:
    """`[G-P4-PBO]`'s value: how often the in-sample winner fell below the OOS median.

    The whole grid the search chose between, not the survivors: PBO asks how often selecting on
    in-sample performance picks a config that then fails, and restricting it to the ones that
    survived selection would ask that question of a population already filtered by the answer.

    ``None``, never 0.0, when there are fewer than two configs. A PBO of zero is the strongest
    statement this gate can make -- the in-sample winner never failed out of sample -- and a
    single config is both the best and the median, so the statistic is undefined. Undefined must
    not print as perfect.
    """
    if len(series_by_config) < 2:
        return None
    returns = {name: [Decimal(str(v)) for v in values] for name, values in series_by_config.items()}
    # The whole result, not just the fraction: `observations_purged` is how a reader (and a
    # test) can see the boundary purge actually ran. A wrapper returning only the number lets
    # the horizon be silently dropped, which is a leak nobody can observe.
    return probability_of_backtest_overfitting(returns, n_blocks=PBO_BLOCKS, horizon=PBO_HORIZON)


CVAR_LEVEL = 0.95
"""The quantile CVaR is reported beyond. A CVaR without a level is not a number, and 95% is the
overwhelming convention — declared here rather than left implicit because a reader comparing two
dossiers has to know they were measured at the same place. This is a REPORTING choice, not a
gate threshold: nothing is compared against it, so it is not the kind of bar ADR-0014 refuses to
invent."""


def report_card_economics(
    series: Sequence[float], turns: Sequence[int], stamps: Sequence[int]
) -> dict[str, float]:
    """§12.2's `rotation`, `orders_per_day` and `cvar` from a run the search already has.

    **`rotation` is round trips per bar.** Every position here is opened and closed within its
    holding bar, so the turnover count IS the rotation count; with several instruments trading
    each bar it exceeds one, which is correct rather than a bug.

    **`orders_per_day` counts ORDERS, two per round trip** — an entry and an exit. The ≤5
    orders/s governor counts orders, so reporting round trips under a name that says orders
    would understate the number that matters by half.

    **`cvar` is the mean loss beyond the** :data:`CVAR_LEVEL` **quantile, as a POSITIVE
    magnitude** — the same sign convention as `max_drawdown`, and stated for the same reason: a
    negative magnitude read as "larger is better" ranks the worst tail first. The MEAN beyond
    the quantile, not the single worst observation: on a fat tail those differ by exactly the
    thing CVaR was chosen to see.

    `rotation` and `orders_per_day` are **absent** when nothing traded. Zero is true and
    useless: a strategy that never traded has no economics to report, and `0.0` orders per day
    would read as one that is cheap to run.
    """
    if len(series) != len(turns):
        raise ValueError(
            f"series has length {len(series)} and turns {len(turns)}. They index the same bars, "
            "so a mismatch means one of them describes a different run."
        )
    out: dict[str, float] = {}

    total_turns = sum(turns)
    if total_turns:
        out["rotation"] = total_turns / len(turns)
        # Bucketed by UTC day, which is the same as the IST day for this market: an NSE
        # session runs 09:15-15:30 IST, i.e. 03:45-10:00 UTC, so it lies inside one calendar
        # day in both. An IST offset was here and no test could distinguish it, because none
        # ever can while the venue is NSE. A venue whose session crosses UTC midnight would
        # need one, and would need a test that says so.
        days = {ts // 86_400_000_000_000 for ts in stamps}
        out["orders_per_day"] = 2.0 * total_turns / len(days)

    if series:
        ordered = sorted(series)
        tail = max(1, round(len(ordered) * (1 - CVAR_LEVEL)))
        out["cvar"] = -sum(ordered[:tail]) / tail
    return out


CI_LEVEL = 0.95
"""Coverage of the reported interval. A reporting choice like :data:`CVAR_LEVEL`, not a bar:
nothing is compared against it, and a reader holding two dossiers side by side has to know they
were measured at the same coverage."""

CI_RESAMPLES = 500
"""Fixed, so the interval a dossier records does not depend on how patient the caller was."""


def bootstrap_sharpe_ci(series: Sequence[float]) -> tuple[float, float] | None:
    """A percentile interval for the Sharpe, from stationary-bootstrap resamples.

    Returned as an INTERVAL. Recording only the lower bound under the name `bootstrap_ci` — the
    decision-relevant half — would be a field whose name asserts more than the value holds, in a
    dossier built to be re-checked. Widening the metric channel to carry it was the honest route.

    ``None`` where the Sharpe itself is undefined: a flat series has no deviation to divide by,
    and an interval around a division by zero is not a measurement. `MIN_OBSERVATIONS` applies
    for the same reason it does to the DSR.
    """
    if len(series) < MIN_OBSERVATIONS:
        return None
    values = [Decimal(str(v)) for v in series]
    sharpes: list[float] = []
    for resample in stationary_bootstrap(values, CI_RESAMPLES, BLOCK_LENGTH, SPA_SEED):
        drawn = np.asarray([float(v) for v in resample])
        if drawn.min() == drawn.max():
            # See `gate_s4`: a constant array's standard deviation is not reliably 0.0, and
            # dividing by 1e-19 of float noise gives a Sharpe of about 4.6e15.
            continue
        sharpes.append(float(np.mean(drawn)) / float(np.std(drawn)))
    if not sharpes:
        return None
    sharpes.sort()
    tail = (1.0 - CI_LEVEL) / 2.0
    low = sharpes[max(0, min(len(sharpes) - 1, int(tail * len(sharpes))))]
    high = sharpes[max(0, min(len(sharpes) - 1, int((1.0 - tail) * len(sharpes))))]
    return (low, high)
