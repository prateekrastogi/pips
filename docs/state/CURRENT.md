# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M0 scaffold + M0.5 containerize** — bootstrap tick. Repo scaffolded to §4, ledger seeded,
CI ladder green locally, container/Jenkins rail written. Plus an owner-requested
constitution change: **test-first (TDD) is now rule 16** with mechanical enforcement
(`make tdd-check` `[G-TDD-01]`, ADR-0009, §7.1).

## Last verify output
```
make ci                       -> ci: green
  ruff check + format         -> All checks passed! (46 files)
  mypy --strict               -> Success: no issues found in 46 source files
  tdd-check                   -> OK (branch is test-first)
  pytest                      -> 82 passed
  cargo clippy -D warnings    -> clean, 22 crates
  cargo test --workspace      -> ok (0 tests: crates are M0 stubs, honestly empty)
  determinism                 -> two independent runs are bit-identical
  ledger-check                -> 26 rows (planned=23 building=2 enforced=1)
docker compose config         -> VALID
```
Container verify (`docker compose run research make ci`) — see the blocker line below.

## Next 3 actions
1. Finish M0.5: `docker compose run research make ci` green, then wire local Jenkins to the
   repo and get the pipeline green on a scratch commit (this is the M0.5 Verify, unmet).
2. Merge `m/0-scaffold` to main once Jenkins is green; confirm the P0 gate items that are
   already satisfiable (containerized CI green).
3. Start **M1 harvest audit** over `../past` (3 repos: `convexity`, `intraday`,
   `vol_research`) — full history sweep per §1.2, `salvage.yaml` + `SALVAGE.md` +
   needs-coverage table. Nothing in M4/M6/M21–M23 may be written before this exists.

## Blockers / awaiting
- **None escalated.** M0.5's Jenkins half is unverified: a local Jenkins is not yet wired to
  this repo. If wiring it fails at the Jenkins boundary, that is a BLK card + a
  Jenkins-pipeline specialist (§10.4), not in-session grinding.
- **Human-only, not blocking yet:** `G-AUTH-0` (written ICICI data-use clarification) is
  needed before any live order and is filed at M3. No credentials, spend or broker paperwork
  are required to proceed through P0–P2.
- `pandoc` is absent on the laptop; `make refs-extract` therefore runs in the research
  container (pandoc is installed in the image), not natively.
