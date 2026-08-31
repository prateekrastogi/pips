# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M2 core + canaries — 3 of 4 parts done.** As-of panel view ✓, permanent leakage canary ✓,
calendars + session states `[C-SESS-01]` ✓ (**enforced**). Remaining: full trial identity for
`[C-ID-01]`. M2's Verify is `make test determinism`.

## Last verify output
```
make ci -> ci: green
  ruff 55 files · mypy --strict 55 files · 165 pytest · clippy clean (21 crates) ·
  cargo test ok · determinism bit-identical
  ledger-check 26 rows (planned=22 building=2 enforced=2)   <- C-SESS-01 joined G-TDD-01
make salvage-verify -> OK: 21 donors resolve; 7 NONE_FOUND carry search records
```

## Next 3 actions
1. **Finish M2** — full trial identity for `[C-ID-01]`, test-first: hash code commit, data
   snapshot root, instrument-master/CA/calendar hashes, pipeline DAG, universe policy,
   parameters, split definition, cost model, fill model, capital tier, seed and runtime
   versions into one id, with re-running an existing hash returning the cached result. Then
   flip `[C-ID-01]` to `enforced` and run M2's Verify (`make test determinism`).
2. Merge `m/0-scaffold` to main (CI-certified; awaiting the owner's go), then re-run `pips-ci`
   with `REF=main` so the merge commit carries its own green verdict.
3. **M3 GATE-0 + feasibility probe** — file the ICICI data-use question; probe Breeze for the
   real rate limit (SAL-0003 encodes 100/min; pips throttles to 75 until confirmed), history
   depth, and the bar-timestamp convention behind ADR-0001.

## Blockers / awaiting
- **None.** No open block cards.
- **Awaiting the owner (not blocking):** the merge of `m/0-scaffold` to main.
- **Carried from ADR-0010:** GATE-0's escape hatch is now a single option (Flattrade's API).
  M3 files the ICICI question early so the answer arrives before it gates anything.
- **Known gap, deliberately not filled:** `config/calendars/nse_equity.yaml` ships with an
  EMPTY holiday list and `holidays_verified: false`. Inventing plausible NSE dates would be
  worse than shipping none — an invented holiday is indistinguishable from a verified one at
  the point of use, and would silently fabricate or delete a trading day in every backtest
  spanning it. Sourced at M6 from the PIT exchange-calendar master, with `holidays_source`
  and `holidays_verified_on` filled in by the same commit. Until then anything on the path to
  real capital must call `require_verified_holidays()` and refuse.
