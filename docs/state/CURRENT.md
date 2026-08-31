# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M2 core + canaries — DONE.** All four parts landed and both ledger rows are `enforced`:
config/trial identity `[C-ID-01]`, calendars + session states `[C-SESS-01]`, the as-of panel
view with its adversarial battery, and the permanent leakage canary. M0, M0.5 and M1 also done.

## Last verify output
```
M2 Verify — make test determinism
  194 passed
  determinism OK: two independent runs are bit-identical

make ci -> ci: green
  ruff 57 files · mypy --strict 57 files · 194 pytest · clippy clean (21 crates) ·
  cargo test ok · ledger-check 26 rows (planned=22 building=1 enforced=3)
make salvage-verify -> OK: 21 donors resolve; 7 NONE_FOUND carry search records
```

## Next 3 actions
1. **M3 GATE-0 + feasibility probe** — the next milestone, and it splits cleanly:
   - *Doable now:* write `ops/runbooks/authority.md` (the ICICI data-use question template),
     and build the probe harness with recorded cassettes so CI makes no live calls.
   - *Human-only:* actually filing the question with ICICI, and supplying Breeze credentials
     for the live probe. Both are recorded below rather than simulated.
2. Merge `m/0-scaffold` to main (CI-certified across seven green builds; awaiting the owner's
   go), then re-run `pips-ci` with `REF=main`.
3. **M3.5 arb-vm deploy rail** `[C-DEPLOY-01]` `[G-DEPLOY-01]` — has a real donor (SAL-0010,
   `convexity` autodeploy.sh, written for a live fleet). Needs arb-vm SSH access, so it will
   want a Jenkins credential binding; the controller already ships the plugins for it.

## Blockers / awaiting
- **None blocking today.** No open block cards.
- **Awaiting the owner (not blocking):** the merge of `m/0-scaffold` to main.
- **Human-only, arriving at M3 — worth starting now because it has a long lead time:**
  `[G-AUTH-0]` needs written ICICI clarification that Breeze may be used as a data-only plane
  while orders execute elsewhere. ADR-0010 narrowed the fallback to one option (Flattrade's
  API), so if that answer is unfavourable AND Flattrade's terms do not permit it, the gate can
  only be cleared by reopening a second venue. Nothing before P6 is blocked by it.
- **Human-only, also at M3:** Breeze API credentials for the feasibility probe (real rate
  limits, history depth, bar-timestamp convention). The probe writes saved artifacts under
  `docs/reports/feasibility/`; CI never makes live calls.
- **Known gap, deliberately not filled:** `config/calendars/nse_equity.yaml` ships an empty
  holiday list with `holidays_verified: false`; sourced at M6. `require_verified_holidays()`
  refuses until then.
