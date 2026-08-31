"""Benjamini-Hochberg false-discovery-rate control (§6 M13).

Applied **within family x universe**, not across the whole sweep. A family sweep is many
tests, and reporting the best of N without correction is the "unlimited grids branded
exhaustive" line of §7's rejection list.

BH is a *step-up* procedure, which is the part people get wrong when they reimplement it: a
relatively large p-value can still be rejected if enough smaller ones clear the line. A naive
per-test threshold is not BH and is markedly more conservative.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["benjamini_hochberg"]


def benjamini_hochberg(p_values: Sequence[float], q: float) -> list[bool]:
    """Which hypotheses BH rejects at false-discovery rate ``q``.

    Returns a mask in the caller's original order -- returning sorted results and leaving the
    caller to re-map is how the wrong alpha gets promoted.
    """
    if not 0 < q < 1:
        raise ValueError(f"q must be in (0, 1), got {q}")
    for p in p_values:
        if not 0 <= p <= 1:
            raise ValueError(f"p-value {p} is outside [0, 1]")
    n = len(p_values)
    if n == 0:
        return []

    ordered = sorted(range(n), key=lambda i: p_values[i])
    # Step UP: find the largest rank k where p_(k) <= k/n * q, then reject every hypothesis
    # at or below that rank. Scanning downward is what makes it a step-up procedure.
    cutoff_rank = 0
    for rank, index in enumerate(ordered, start=1):
        if p_values[index] <= rank / n * q:
            cutoff_rank = rank

    rejected = [False] * n
    for rank, index in enumerate(ordered, start=1):
        if rank <= cutoff_rank:
            rejected[index] = True
    return rejected
