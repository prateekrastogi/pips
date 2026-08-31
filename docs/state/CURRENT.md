# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M2 core + canaries — in progress (1 of 4 parts done).** The as-of panel view and the
permanent leakage canary have landed. Also landed this tick, on owner instruction: **Flattrade
is now the sole execution venue (ADR-0010)**, Zerodha deferred.

## Last verify output
```
make ci -> ci: green
  ruff 53 files · mypy --strict 53 files · 139 pytest · clippy clean (21 crates) ·
  cargo test ok · determinism bit-identical · ledger-check 26 rows + harvest map covered
make salvage-verify -> OK: 21 donors resolve; 7 NONE_FOUND carry search records

leakage canary — unsafe |IC|, all three cheats: 1.0000 / 1.0000 / 1.0000
                 honest control (lagged volume):  0.0071
                 all three refused on the production path
```

## Next 3 actions
1. **Finish M2.** Remaining parts, each test-first: calendars incl. CAS windows
   `[C-SESS-01]` (SAL-0027 is NONE_FOUND, so from-scratch is pre-authorised); full trial
   identity for `[C-ID-01]` — hashing code commit, snapshot root, master/CA/calendar hashes,
   DAG, universe policy, params, split, cost model, fill model, capital tier, seed, runtime
   versions — then flip both rows to `enforced`. M2's Verify is `make test determinism`.
2. Merge `m/0-scaffold` to main (CI-certified; awaiting the owner's go), then re-run `pips-ci`
   with `REF=main` so the merge commit carries its own green verdict.
3. **M3 GATE-0 + feasibility probe** — file the ICICI data-use question; probe Breeze for the
   real rate limit (SAL-0003 encodes 100/min; pips throttles to 75 until confirmed), history
   depth, and the bar-timestamp convention behind ADR-0001.

## Blockers / awaiting
- **None.** No open block cards.
- **Awaiting the owner (not blocking):** the merge of `m/0-scaffold` to main.
- **Raised by ADR-0010 — worth the owner knowing now:** GATE-0's escape hatch has narrowed to
  a single option. ADR-0006 offered two fallback feeds if ICICI's data-use answer is
  unfavourable (Kite Connect entitled feed, or Flattrade's API); only Flattrade remains. If
  its terms do not permit the use, `[G-AUTH-0]` can be cleared only by the ICICI clarification
  itself or by reopening a second venue. M3 files that question, so the answer arrives well
  before it gates anything.
- **Human-only, not blocking yet:** `G-AUTH-0` gates only the live path. Nothing in P0–P2
  needs credentials, spend or paperwork.
- **Retained deliberately:** the high-cost reference line (§3.7, `[C-COST-02]`, P3 gate
  `net_sharpe_min_high_cost_line: 1.0`). It is a stress line, not a venue — pinned by
  `tests/unit/test_venue_scope.py` so it cannot be tidied away as leftover Zerodha.
