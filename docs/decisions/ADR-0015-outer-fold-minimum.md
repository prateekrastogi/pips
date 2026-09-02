# ADR-0015 · At least twelve outer folds, measured after the seal

**Status:** accepted · **Date:** 2026-09-02 · **Decided by:** owner · **Affects:** `[G-P4-FOLDS]`, M15, M20

## Context
`stability.outer_folds` had no declared bar, so `[C-CERT-01]` could not gate on it and
`certify-smoke` reported it unsupplied. The blueprint names outer folds in §12.2's Stability row
without a number.

The splitter decides what numbers are even available. Measured against `walk_forward` at M15's
geometry — train 126, test 21, purge = horizon, embargo ≥ horizon + order duration:

| Post-seal trading days | Outer folds |
|---|---|
| ≤ 146 | 0 |
| 147 | 1 |
| 168 | 2 |
| 189 | 3 |
| 378 | **12** |

**The arithmetic that was wrong.** An earlier session log recorded the minimum as
"outer 21d + inner 21d + train 126d = 168". That is not how the splitter works:
`inner_folds(outer, inner_test_size)` carves its blocks out of `outer.train_indices`, so the
inner window costs **no extra days**. 147 is the first length yielding a fold; 168 is the first
yielding two. The corrected figures are recorded here because the bar is set against them.

## Decision
**≥ 12 outer folds**, measured on the panel **after the lockbox seal is subtracted** — never on
the gross backfill.

Twelve rather than two. At 168 gross days, any real holdout leaves fewer than 147 to walk and
the count collapses to zero; and two folds is a split, not a walk — it reports a mean over two
numbers and calls it stability. Twelve requires 378 post-seal days, which three years of NSE
sessions less a holdout clears with room (≈750 gross → 20–24 folds at a 15–25% seal).

**Post-seal is structural, not a convention.** `outer_fold_count` takes the panel span and the
seal separately and refuses a zero seal, so it is impossible to measure folds over data that
includes the holdout. The same reasoning as `[C-LBOX-01]` taking no dates from its caller: a
number produced over the wrong window looks exactly like one produced over the right one.

## Consequences
- `gates.yaml` gains `G-P4-FOLDS`; `stability.outer_folds` joins `HARD_GATES`; the writer
  declares the source. The ledger-agreement test holds the three together.
- The gate **fails today**, and correctly: nothing wires nested walk-forward into the search, so
  no folds are run. The bar is decided and recorded; producing the number is M15 integration
  work that the backfill unblocks.
- Truncating the backfill to 168 days would fail this gate by construction — which is a stronger
  reason not to truncate than the quota arithmetic that originally motivated it.
