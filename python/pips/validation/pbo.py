"""CSCV and the Probability of Backtest Overfitting  (§6 M18).

CSCV asks a question no in-sample number can answer: **when I pick the best config on half the
data, how often is it below median on the other half?** If that happens about half the time,
the selection procedure is choosing noise — and it says so without needing to know which config
is "really" good, which is what makes it a check on the PROCEDURE rather than on a result.

Three things this insists on:

**All combinations, not a sample.** The "combinatorially symmetric" in the name is the method:
every way of splitting S blocks into halves of S/2, so each split and its complement both
appear. Sampling to go faster produces a different estimator with a different variance, and
reporting that as PBO would be reporting a number nobody computed.

**Boundary purge.** §6 M18 asks for it, and the reason is M15's: a label spanning the boundary
between an in-sample block and an out-of-sample one puts the same bars on both sides, so the
two halves are not independent and the "out-of-sample" half is partly in-sample.

The guarantee is STRUCTURAL and is what :func:`split_indices` is tested on — after purging, no
in-sample observation's label window reaches into an out-of-sample block. That is checkable and
exact.

**No claim is made about which way it moves PBO.** An earlier draft of this docstring asserted
that leakage biases PBO downward, toward declaring the procedure sound. That is a plausible
story and I could not reproduce it: on noise, and again on a fixture with genuinely overlapping
labels, purging LOWERED the statistic (0.900 -> 0.800) rather than raising it. Removing data
also adds estimation noise, and which effect dominates is not something these experiments
settle. Rather than keep a directional claim the tests contradict, the claim is withdrawn and
the structural guarantee is what is asserted.

Only boundaries where the neighbouring block is on the OTHER side are purged. Purging every
boundary regardless would discard data for no reason, and arbitrary caution is a parameter.

**The trials it consumes are the trials rule 4 counts.** PBO evaluates N configs; those are N
viewed trials, and a PBO computed over configs the multiplicity ledger never saw is a
correction that flatters twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from pips.validation.stress import sharpe

__all__ = ["PBOResult", "probability_of_backtest_overfitting", "split_indices"]


@dataclass(frozen=True)
class PBOResult:
    """How often the in-sample winner fell below the out-of-sample median."""

    pbo: float
    n_splits: int
    n_configs: int
    observations_purged: int
    most_selected: str
    selection_counts: dict[str, int]

    def describe(self) -> str:
        return (
            f"PBO {self.pbo:.3f} over {self.n_splits} splits of {self.n_configs} configs "
            f"({self.observations_purged} observation(s) purged at block boundaries); "
            f"most often selected in-sample: {self.most_selected}"
        )


def _blocks(n_obs: int, n_blocks: int) -> list[list[int]]:
    """Contiguous, near-equal index blocks. Contiguity matters: shuffled blocks would break
    the time ordering the purge depends on."""
    edges = [round(i * n_obs / n_blocks) for i in range(n_blocks + 1)]
    return [list(range(edges[i], edges[i + 1])) for i in range(n_blocks)]


def split_indices(
    blocks: list[list[int]], is_set: set[int], horizon: int
) -> tuple[list[int], list[int]]:
    """In-sample and out-of-sample indices for one split, after the boundary purge.

    Only a CROSSING boundary is purged: if the next block sits on the same side, a label
    spanning it stays within one side and leaks nothing. Purging every boundary regardless
    would discard data for no reason, and arbitrary caution is a parameter.
    """
    is_index: list[int] = []
    oos_index: list[int] = []
    for b, block in enumerate(blocks):
        crosses = b + 1 < len(blocks) and ((b in is_set) != (b + 1 in is_set))
        keep = block[: len(block) - horizon] if crosses and horizon else block
        (is_index if b in is_set else oos_index).extend(keep)
    return is_index, oos_index


def probability_of_backtest_overfitting(
    returns: dict[str, list[Decimal]], n_blocks: int, horizon: int = 0
) -> PBOResult:
    """PBO by combinatorially symmetric cross-validation, with a boundary purge."""
    if len(returns) < 2:
        raise ValueError(
            f"PBO needs at least 2 configs to rank, got {len(returns)}. A single config is "
            "always both the best and the median, and the statistic is undefined."
        )
    if n_blocks % 2 != 0:
        raise ValueError(
            f"n_blocks must be even, got {n_blocks}. Each side takes S/2 blocks, and rounding "
            "would make the two sides unequal — losing the symmetry the method is named for."
        )
    lengths = {len(v) for v in returns.values()}
    if len(lengths) != 1:
        raise ValueError(f"every config must have the same length, got {sorted(lengths)}")
    if horizon < 0:
        raise ValueError(f"horizon must not be negative, got {horizon}")

    n_obs = lengths.pop()
    blocks = _blocks(n_obs, n_blocks)
    if any(len(b) <= horizon for b in blocks):
        raise ValueError(
            f"a purge of {horizon} would empty a block of {min(len(b) for b in blocks)} "
            "observations. A PBO over empty blocks is a number with no data behind it."
        )

    names = sorted(returns)
    half = n_blocks // 2
    below_median = 0
    purged_total = 0
    selections: dict[str, int] = dict.fromkeys(names, 0)
    splits = list(combinations(range(n_blocks), half))

    for is_blocks in splits:
        is_set = set(is_blocks)
        is_index, oos_index = split_indices(blocks, is_set, horizon)
        purged_total += n_obs - len(is_index) - len(oos_index)

        in_sample = {n: sharpe([returns[n][i] for i in is_index]) for n in names}
        winner = max(in_sample, key=lambda n: (in_sample[n], n))
        selections[winner] += 1

        out_sample = {n: sharpe([returns[n][i] for i in oos_index]) for n in names}
        ordered = sorted(out_sample.values())
        middle = len(ordered) // 2
        median = (
            ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        )
        if out_sample[winner] < median:
            below_median += 1

    # Tie-break kept for consistency with the winner selection above, and LEFT UNTESTED
    # deliberately: a tie here needs two configs each winning exactly half of C(n,n/2) splits,
    # and both branches are deterministic given `names` is sorted -- plain `max` would take the
    # alphabetically first, this takes the last. Only the displayed name differs, never a
    # verdict, so engineering a 35/35 fixture would buy the appearance of coverage.
    most_selected = max(selections, key=lambda n: (selections[n], n))
    return PBOResult(
        pbo=below_median / len(splits),
        n_splits=len(splits),
        n_configs=len(names),
        observations_purged=purged_total,
        most_selected=most_selected,
        selection_counts=selections,
    )
