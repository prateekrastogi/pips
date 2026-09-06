# P0 — foundation & authority: approved

**Date:** 2026-09-06
**Approved by:** the owner (Prateek Rastogi), in a message to the agent: "i grant explicit approval
for p0 sign off file".

**Gate criteria (IMPLEMENTATION.md §6, P0 gate) and the evidence on this date:**

- Jenkins CI (containerized) green — builds #306–#327 green; the ladder is provenance, lint,
  typecheck, tdd-check, test, sweep, rust-test, determinism, ledger-check `[G-TDD-01]` `[G-SWEEP-01]`.
- Canary red-teams pass — the mutation sweep is a ladder and Jenkins gate with 63 committed
  mutations across nine specs, all killed.
- Deploy rail demonstrated end-to-end — every main SHA auto-built and run on arb-vm
  `[C-DEPLOY-01]` `[G-DEPLOY-01]`; eleven deploys on 2026-09-05 alone.
- Feasibility artifacts reviewed by human — GATE-0 `[G-AUTH-0]` cleared by owner decision
  (WRITTEN, 2026-09-05); the ICICI written reply waived as an artifact (2026-09-06).

**Not part of this approval:** anything in P1 or later. The loop may proceed past the P0 gate;
P1's gate holds until `P1-approved.md` exists.
