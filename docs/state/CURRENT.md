# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M0 scaffold — DONE. M0.5 containerize — half done.** Repo scaffolded to §4, ledger seeded,
`make ci` green both natively and inside the research container. Jenkins wiring is blocked on
a credential (BLK-0001). Owner-requested constitution change landed: **test-first (TDD) is
rule 16**, enforced by `make tdd-check` `[G-TDD-01]` (ADR-0009, §7.1).

## Last verify output
```
docker compose run research make ci   ->  ci: green          # M0.5 Verify, first half
  ruff check + format .............. All checks passed! (46 files)
  mypy --strict .................... Success: no issues found in 46 source files
  tdd-check ........................ OK (real repo: 2 commits, test-first)
  pytest ........................... 85 passed
  cargo clippy -D warnings ......... clean, 22 crates
  cargo test --workspace ........... ok (0 tests — crates are M0 stubs, honestly empty)
  determinism ...................... two independent runs are bit-identical
  ledger-check ..................... 26 rows (planned=23 building=2 enforced=1)
```
Fixture manifest root `eccc5e2f268b4ad125163f58815710a68a524943f8a34b79597199f07bda44b4`.

## Next 3 actions
1. **M1 harvest audit** over `../past` (`convexity`, `intraday`, `vol_research`) — full
   history sweep per §1.2 (all branches, tags, deleted files; record source SHAs), producing
   `docs/ledger/salvage.yaml` + `docs/SALVAGE.md` + the needs-coverage table. This is the next
   real milestone and is **not** blocked by BLK-0001.
2. Close M0.5 when BLK-0001 is answered: create/trigger the `pips` job and get the pipeline
   green on a scratch commit, then merge `m/0-scaffold` to main on green.
3. **M2 core + canaries**: `[C-ID-01]` to `enforced`, calendars incl. CAS windows
   `[C-SESS-01]`, the AsOf panel view with adversarial tests, and the permanent leakage canary.

## Blockers / awaiting
- **BLK-0001 · escalated: human** — M0.5's Jenkins Verify. A Jenkins is running
  (`keeper-jenkins`, localhost:8080, docker socket mounted so the pipeline will work) but the
  API requires auth. Needed from the human: either Jenkins `JENKINS_URL`/`JENKINS_USER`/
  `JENKINS_TOKEN` in a VM-side env file, **or** the job created by hand (Pipeline from SCM,
  script path `Jenkinsfile`) and a note on the card. Also state whether `pips` should share
  the `keeper` controller or get its own compose-managed one. See
  `docs/state/blocks/BLK-0001.md`. Not simulated, not worked around.
- **Consequence while open:** merges to main are not CI-certified. Research work is
  unaffected — the containerized ladder is green. BLK-0001 is **off the critical path**, so
  per LOOP.md §1.2 the loop records it and proceeds to M1 rather than idling.
- **Human-only, not blocking yet:** `G-AUTH-0` (written ICICI data-use clarification) is filed
  at M3 and gates only the live path. Nothing in P0–P2 needs credentials, spend or paperwork.
- `pandoc` is absent on the laptop, so `make refs-extract` runs in the research container
  (pandoc is in the image), via the dev override that mounts the tree. Done: all four
  documents are cached under `docs/reference/_extracted/` (4,414 lines). Consult these by
  section — never ingest one end to end (§9).
