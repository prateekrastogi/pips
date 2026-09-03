"""Multiplicity ledger: M and M_erank  [C-REG-01] (§3.6).

Report **both** the literal trial count ``M`` and the effective count

    M_erank = (Σλ_j)² / Σλ_j²

from the eigenvalues of the cross-trial daily-return correlation matrix. §3.6 is careful about
what this is: *a sensitivity heuristic, not an exact correction* -- DSR is evaluated at
``N = M`` and ``N = M_erank`` as **bracketing cases**, not at some blend of them. Reporting one
without the other cannot produce the bracket, so :func:`multiplicity` returns both.

The intuition is worth keeping in view: eight clones of one strategy are one trial's worth of
multiplicity, not eight, and eight genuinely independent ideas are eight. ``M_erank`` moves
between those extremes and nowhere outside them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pips.search.registry import Registry

__all__ = ["Multiplicity", "effective_rank", "multiplicity"]


@dataclass(frozen=True)
class Multiplicity:
    """Both counts, together. DSR brackets between them."""

    literal_count: int
    effective_count: float | None

    def bracket(self) -> tuple[int, float]:
        """The ``(N = M_erank, N = M)`` pair DSR is evaluated at."""
        if self.effective_count is None:
            raise RuntimeError(
                "no daily returns were preserved, so M_erank is unavailable and the DSR "
                "bracket cannot be formed. Preserve daily_returns_ref per trial (§3.6)."
            )
        return self.literal_count, self.effective_count


def effective_rank(returns: np.ndarray) -> float:
    """``(Σλ)² / Σλ²`` over the eigenvalues of the cross-trial correlation matrix.

    ``returns`` is (observations x trials). Degenerate columns -- a trial that never traded,
    so its return series has zero variance -- are dropped rather than allowed to produce a
    correlation matrix full of NaN, which would silently poison the result for every *other*
    trial. Dropping them is right on the merits too: a constant series shares no information
    with anything, and it also carries none.
    """
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"expected an (observations x trials) matrix, got shape {matrix.shape}")
    if matrix.shape[1] == 0:
        raise ValueError("no trials to rank")

    varying = matrix[:, matrix.std(axis=0) > 0]
    if varying.shape[1] <= 1:
        # One informative trial (or none) is one trial's worth of multiplicity.
        return 1.0

    correlation = np.corrcoef(varying, rowvar=False)
    eigenvalues = np.linalg.eigvalsh(correlation)
    # Numerical noise can push a near-zero eigenvalue slightly negative; clip rather than let
    # it flip the sign of a sum. NOT reproducible on this platform -- 300 near-collinear
    # correlation matrices produced a minimum eigenvalue of exactly 0.0 -- so a mutation of
    # this line survives. Kept anyway, and the distinction from the guards this project has
    # deleted is deliberate: those were provably unreachable, this is merely un-triggered here,
    # and LAPACK's behaviour is not a property of our arithmetic.
    eigenvalues = np.clip(eigenvalues, 0.0, None)

    total = float(eigenvalues.sum())
    squared = float((eigenvalues**2).sum())
    # Provably unreachable, unlike the clip above: a correlation matrix has a unit diagonal, so
    # its trace -- and therefore the eigenvalue sum -- is the number of columns, which is at
    # least 2 here. A positive sum of non-negative values has a positive sum of squares. Kept as
    # the divisor's own precondition rather than as a claim about the data.
    if squared <= 0:
        return 1.0
    return total * total / squared


def multiplicity(registry: Registry) -> Multiplicity:
    """M over every recorded trial, and M_erank where returns were preserved.

    ``M`` counts **all** statuses -- completed, failed, abandoned and viewed alike (rule 4).
    Filtering to the successful ones is precisely the bias the multiplicity ledger exists to
    measure.
    """
    literal = len(registry.all_runs())
    matrix = registry.daily_returns_matrix()
    return Multiplicity(
        literal_count=literal,
        effective_count=None if matrix is None else effective_rank(matrix),
    )
