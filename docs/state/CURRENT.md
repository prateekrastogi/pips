# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M0 scaffold — DONE. M0.5 containerize — DONE.** Both M0.5 verifies are met: the
containerized ladder is green, and the pips-owned Jenkins controller builds this branch green
end to end. BLK-0001 is CLOSED. `m/0-scaffold` is CI-certified and ready to merge to main —
held only because a merge is the owner's call, not the loop's.

## Last verify output
```
pips-ci build #2, ref m/0-scaffold -> SUCCESS        # M0.5 Verify, second half
  Build image · lint · typecheck · tdd-check · py tests · rust tests ·
  determinism · ledger-check ............ all SUCCESS
  Tag image ............................. NOT_EXECUTED (correct: not main)
  tdd-check OK: 6 commits test-first ..... real history, not SKIPPED

docker compose run research make ci -> ci: green      # M0.5 Verify, first half
make ci (native) -> ci: green
  ruff 46 files · mypy --strict 46 files · 89 pytest · clippy clean (22 crates) ·
  cargo test ok (0 tests, stubs) · determinism bit-identical · ledger-check 26 rows
```
Controllers: pips `127.0.0.1:8081` (project `pips-ci`) · keeper `127.0.0.1:8080`, untouched
and verified healthy. Fully isolated: distinct project, container, image, volume and port.

## Next 3 actions
1. **M1 harvest audit** — resume the `../past` sweep. The `intraday` findings are already
   captured in `docs/state/log/2026-08-31.md`: a deleted `src/volarb/adapters/breeze/`
   package (auth/history/ratelimit/backfill — the M4 donor), `costs/nse_fees.py` (M9),
   `backtest/splits.py` (M15), with candidate source SHAs. Still to sweep: `convexity`
   (177 commits, refs `hardening` + `journal-backups-convexity`) and the `vol_research`
   keyword pass. Then write `salvage.yaml` + `docs/SALVAGE.md` + the needs-coverage table.
2. Merge `m/0-scaffold` to main (CI-certified, awaiting the owner's go), then re-run `pips-ci`
   with `REF=main` so the merge commit itself carries a green verdict.
3. **M2 core + canaries**: flip `[C-ID-01]` to `enforced`, calendars incl. CAS windows
   `[C-SESS-01]`, the AsOf panel view with adversarial tests, permanent leakage canary.

## Blockers / awaiting
- **None.** BLK-0001 closed: pips runs its own JCasC controller, so no credential was needed.
- **Awaiting the owner (not blocking):** the merge of `m/0-scaffold` to main. The loop commits
  on the branch; merging is a deliberate act.
- **Human-only, not blocking yet:** `G-AUTH-0` (written ICICI data-use clarification) is filed
  at M3 and gates only the live path. Nothing in P0–P2 needs credentials, spend or paperwork.
- **Note for M3.5:** the deploy rail will need an arb-vm SSH identity bound as a Jenkins
  credential. The controller ships the `ssh-agent`/`credentials` plugins for that but holds no
  key today and reaches nothing remote.
