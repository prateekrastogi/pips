# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M1 harvest audit — DONE.** (M0 + M0.5 done in earlier ticks.) `../past` swept across every
ref and full history; 28 SAL rows — 21 donors resolving to real blobs, 7 NONE_FOUND with
search records. Every M4/M6/M21–M23/ops need is answered, and `make ledger-check` now fails
if one stops being.

## Last verify output
```
make salvage-verify -> OK: 21 donor row(s) resolve to real blobs in ../past;
                           7 NONE_FOUND row(s) carry a search record
make ci             -> ci: green
  ruff 49 files · mypy --strict 49 files · 104 pytest · clippy clean (22 crates) ·
  cargo test ok · determinism bit-identical · ledger-check 26 rows + harvest map covered
```
Headline finding: **`intraday`'s HEAD is a bare README**, and its entire Breeze adapter
(auth / history / ratelimit / backfill, ~22 KB) lives only in history at `be8186d`, deleted by
a later refactor. Judging that repo by its working tree would have concluded "nothing here"
and pre-authorised writing the M4 connector from scratch.

## Next 3 actions
1. **M2 core + canaries** — the next milestone in §6 order. Flip `[C-ID-01]` to `enforced`;
   calendars incl. CAS windows `[C-SESS-01]` (SAL-0027: NONE_FOUND, so from-scratch is
   pre-authorised); the AsOf panel view with adversarial tests; and the **permanent leakage
   canary** — spectacular in an unsafe harness, must fail every production path, stays in the
   suite forever. All test-first (rule 16).
2. Merge `m/0-scaffold` to main (CI-certified; awaiting the owner's go), then re-run `pips-ci`
   with `REF=main` so the merge commit carries its own green verdict.
3. **M3 GATE-0 + feasibility probe** — file the ICICI data-use question, and probe Breeze for
   the real rate limit (SAL-0003 encodes 100/min; pips throttles to 75 until confirmed), the
   true history depth, and the bar-timestamp convention behind ADR-0001.

## Blockers / awaiting
- **None.** No open block cards; BLK-0001 closed.
- **Awaiting the owner (not blocking):** the merge of `m/0-scaffold` to main. The loop commits
  on the branch; merging is a deliberate act.
- **Human-only, not blocking yet:** `G-AUTH-0` (written ICICI data-use clarification) is filed
  at M3 and gates only the live path. Nothing in P0–P2 needs credentials, spend or paperwork.
- **Three warnings recorded in `docs/SALVAGE.md`** for the milestones that will consume these
  donors: do not inherit SAL-0003's rate-limit constant, SAL-0006's fee numbers, or SAL-0008's
  panel semantics. Each is a probe result or a contract, not a donor's to give.
- **Note for M3.5:** the deploy rail has a real donor (SAL-0010, `convexity` autodeploy.sh,
  written for a live fleet) and will need an arb-vm SSH identity bound as a Jenkins credential.
