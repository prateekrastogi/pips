"""Ex-post selection by realized sign  (§6 M16, A06's falsifier).

A06 pre-registered *"Reject if continuation and reversal rules are selected ex post by realized
sign"* — and the obvious test is wrong.

One might check whether the A05/A06 assignment correlates with what actually happened. But if
the alphas have any edge at all, **it should**: names A05 claims ought to continue and names
A06 claims ought to revert. Correlation with the outcome is the intended result, not the crime.

The crime has a different signature. Ex-post selection means the assignment DEPENDS ON the
outcome, so it is caught by changing the outcome and watching the assignment move. Perturb only
bars strictly after the decision, recompute, and see whether any name changed hands. A rule
that reads the future partitions differently when the future differs; one that cannot see it
does not.

That also makes this an end-to-end check of the as-of machinery rather than a restatement of
it. :class:`~pips.core.asof.AsOfPanelView` is supposed to make this impossible — this verifies
the guarantee instead of trusting it, which is the same reason A05's falsifier gets a
perturbation rather than a comment.

**Only bars strictly after the decision are touched.** Perturbing a visible bar would change
the partition for a perfectly legitimate reason, and a correct rule would then look like a
cheating one — rejecting exactly the alphas this exists to protect.

**No bars after the decision means the check cannot run.** At the last bar there is no future,
nothing to perturb, and a clean pass would be a pass over an untouched panel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

__all__ = ["ExPostVerdict", "partition_invariance"]

Assign = Callable[[pl.DataFrame], dict[str, str]]
"""``frame -> {instrument: which rule claimed it}``."""

# THE PERTURBATION IS A MIRROR, NOT A SHIFT, and that distinction is the whole strength of the
# check. An additive shift moves every post-decision bar by the same amount, so every DIFFERENCE
# between them is unchanged — and a rule reading the future's shape rather than its level sees
# nothing at all. That blind spot surfaced from a mutation that perturbed every bar and still
# left the causal rule invariant: if a uniform shift cannot move a difference-based rule, it
# cannot catch one either.
#
# Mirroring each symbol's future path about its last visible close flips the direction while
# preserving every magnitude. A rule reading direction changes its answer; a causal rule cannot
# notice, because nothing it can see has moved.


@dataclass(frozen=True)
class ExPostVerdict:
    """Whether the partition survived its own future being rewritten."""

    ran: bool
    bars_perturbed: int
    reassigned: tuple[tuple[str, str, str], ...]
    """``(instrument, before, after)`` for every name that changed hands. Named, because
    which name moved is what turns a failure into a diagnosis."""

    note: str = ""

    @property
    def invariant(self) -> bool:
        """Ran, and nobody changed hands. A check that could not run is not invariant."""
        return self.ran and not self.reassigned


def _mirrored(frame: pl.DataFrame, decision_ts: int, price_column: str) -> list[int]:
    """Each symbol's post-decision path reflected about its last visible close."""
    stamps = frame["close_ts_ns"].to_list()
    symbols = frame["symbol"].to_list()
    prices = frame[price_column].to_list()

    anchor: dict[str, int] = {}
    for ts, symbol, price in zip(stamps, symbols, prices, strict=True):
        if ts <= decision_ts:
            anchor[symbol] = int(price)

    out: list[int] = []
    for ts, symbol, price in zip(stamps, symbols, prices, strict=True):
        if ts > decision_ts and symbol in anchor:
            out.append(2 * anchor[symbol] - int(price))
        else:
            out.append(int(price))
    return out


def partition_invariance(
    assign: Assign,
    frame: pl.DataFrame,
    decision_ts: int,
    price_column: str = "close_paise",
) -> ExPostVerdict:
    """Mirror the post-decision future and report which instruments changed rule."""
    if frame.height == 0:
        raise ValueError(
            "partition_invariance called with no bars. An empty panel partitions the same way "
            "however its future is rewritten, which reads as invariance and is the absence of "
            "a test."
        )

    stamps = frame["close_ts_ns"].to_list()
    future = [i for i, ts in enumerate(stamps) if ts > decision_ts]
    if not future:
        return ExPostVerdict(
            ran=False,
            bars_perturbed=0,
            reassigned=(),
            note=(
                f"no bars after the decision at {decision_ts}, so there is no future to "
                "perturb. Nothing was tested; this is not invariance."
            ),
        )

    before = assign(frame)
    original = frame[price_column].to_list()
    rewritten = _mirrored(frame, decision_ts, price_column)
    changed_bars = sum(1 for a, b in zip(original, rewritten, strict=True) if a != b)
    if changed_bars == 0:
        raise ValueError(
            f"mirroring the future changed no value in {price_column!r}, so any conclusion "
            "about invariance would be about a panel nobody perturbed. A future that never "
            "moves mirrors onto itself — the same hole a zero-magnitude shift would leave."
        )

    after = assign(frame.with_columns(pl.Series(price_column, rewritten)))
    reassigned = tuple(
        (name, before[name], after.get(name, "<absent>"))
        for name in sorted(before)
        if before[name] != after.get(name)
    )
    return ExPostVerdict(ran=True, bars_perturbed=changed_bars, reassigned=reassigned)
