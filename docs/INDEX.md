# docs/INDEX.md — map of the doc layer and the load rules

**Load order at session start (and nothing else by default):**
`CLAUDE.md` → this file → `state/CURRENT.md` → the *single active milestone* section of
`../IMPLEMENTATION.md` (grep the `Mx` anchor) → `ledger/` rows with that `owner_milestone`.

**Load on demand only:** a specific `decisions/ADR-####`; a specific *section* of a
`reference/` document; an old `state/log/` shard. Never read `reference/*` end to end.

**Write at session end (mandatory):** overwrite `state/CURRENT.md`; append
`state/log/<date>.md` (including the RED test output, §7.1); new ADR shards for decisions;
ledger status flips; commit. A session that ends without updating `CURRENT.md` is unfinished.

| Path | What it holds | Size discipline |
|---|---|---|
| `state/CURRENT.md` | active item, last verify output, next 3 actions, blockers | ≤60 lines, overwritten |
| `state/log/<date>.md` | append-only session history | never auto-loaded |
| `state/blocks/BLK-####.md` | one block card each (§10.4); closed cards stay | ≤50 lines each |
| `state/gates/P<k>-approved.md` | human phase-gate sign-off; absence = the loop holds | dated note |
| `decisions/INDEX.md` | one line per ADR: id · title · status | one line per ADR |
| `decisions/ADR-####-*.md` | one decision each | ≤40 lines each |
| `ledger/contracts.yaml` | `C-*` rows: contract → code → tests → status | one row per contract |
| `ledger/gates.yaml` | `G-*` rows: threshold → enforcing code → evidence | one row per gate |
| `ledger/salvage.yaml` | `SAL-*` rows from the M1 harvest audit | one row per donor |
| `reference/` | the four companion documents + `_extracted/` cache | consult by section |
| `reports/` | feasibility probes, signal cards, dossiers, top-K | generated |
| `runbooks/` | token bootstrap, backfill, incident, authority | operational |
| `DATA_DICTIONARY.md` | field-level semantics per zone | shard past ~300 lines |

**Verification:** `make ledger-check` proves prose ↔ ledger ↔ code ↔ tests agree;
`make tdd-check` proves the branch was written test-first `[G-TDD-01]`; `make sweep` mutation-sweeps every changed production module by its committed spec `[G-SWEEP-01]`. All run in `make ci`.
