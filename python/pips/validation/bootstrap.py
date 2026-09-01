"""Stationary bootstrap  (§6 M18, day/week blocks).

A bootstrap that resamples single observations destroys serial dependence — and serial
dependence is most of what makes a trading return series hard. Resample it away and every
confidence interval comes out too narrow, which is to say every result looks more significant
than it is. That is the failure mode: not a crash, a number that is confidently wrong in the
flattering direction.

The stationary bootstrap (Politis & Romano, 1994) resamples BLOCKS of random geometric length,
so runs survive. Two details do the work:

**It wraps.** The series is treated as a circle, which is what "stationary" refers to. Without
wrapping, an observation near the end can only ever appear at a block's end, and the tail of
the sample is systematically under-represented — a bias in the resample with nothing to do with
the data.

**Blocks are geometric, not fixed.** A fixed length imposes a period on the resample and leaves
a signature at that frequency; random lengths with the right mean do not. With probability
``1/L`` the walk jumps to a fresh random position, otherwise it steps forward — which produces
geometric run lengths of mean ``L`` without ever choosing one.

The RNG is a local :class:`random.Random`, never the module-level functions. A bootstrap
reading global state is reproducible only until something else in the process draws a number,
which is a determinism guarantee that holds right up until it matters (rule 1).
"""

from __future__ import annotations

import random
from decimal import Decimal

__all__ = ["bootstrap_indices", "stationary_bootstrap"]


def bootstrap_indices(n: int, mean_block_length: int, seed: int) -> list[int]:
    """Indices for one stationary-bootstrap resample of a length-``n`` series."""
    if n <= 0:
        raise ValueError(f"cannot bootstrap an empty series, got n={n}")
    if mean_block_length < 1:
        raise ValueError(
            f"mean block length must be at least 1, got {mean_block_length}. Below 1 there is "
            "no block to speak of, and the geometric jump probability would exceed certainty."
        )

    rng = random.Random(seed)
    jump_probability = 1.0 / mean_block_length
    indices: list[int] = []
    position = rng.randrange(n)
    for _ in range(n):
        indices.append(position)
        # MODULO on the step: the series is a circle. Stopping at the end instead would make
        # late observations reachable only as a block's final element.
        position = rng.randrange(n) if rng.random() < jump_probability else (position + 1) % n
    return indices


def stationary_bootstrap(
    series: list[Decimal], n_resamples: int, mean_block_length: int, seed: int
) -> list[list[Decimal]]:
    """``n_resamples`` block-resamples of ``series``, reproducible from ``seed``."""
    if not series:
        raise ValueError(
            "cannot bootstrap an empty series. Every resample would be empty, and an empty "
            "confidence interval reads as a result."
        )
    if n_resamples < 1:
        raise ValueError(
            f"n_resamples must be at least 1, got {n_resamples}. A bootstrap of nothing "
            "produces no interval, which is not the same as a narrow one."
        )
    return [
        [series[i] for i in bootstrap_indices(len(series), mean_block_length, seed + r)]
        for r in range(n_resamples)
    ]
