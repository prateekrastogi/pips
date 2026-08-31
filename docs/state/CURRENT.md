# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M3 GATE-0 + feasibility probe — in progress.** GATE-0 half done: the ICICI question is
written and ready to send, and `[G-AUTH-0]` is now machine-enforced (**enforced ≠ cleared** —
it is currently BLOCKING). Remaining for M3: the Breeze feasibility probe and broker
capability snapshots v0. M0, M0.5, M1, M2 done.

## Last verify output
```
make authority-check
  [G-AUTH-0] status=UNFILED feed=BREEZE
    live trading: BLOCKED
    the ICICI data-use question has not been filed. Send the letter in
    ops/runbooks/authority.md, then record the filing date here.

make ci -> ci: green
  ruff 59 files · mypy --strict 59 files · 207 pytest · clippy clean (21 crates) ·
  cargo test ok · determinism bit-identical
  ledger-check 26 rows (planned=21 building=1 enforced=4)
```

## Next 3 actions
1. **Continue M3** — build the Breeze feasibility probe as saved artifacts under
   `docs/reports/feasibility/`: real rate limits (docs conflict 100/min vs 75/min → throttle
   to 75 until confirmed), true history depth per symbol, bar-timestamp convention (feeds
   ADR-0001), WS subscription capacity, BSE support ambiguity. The probe harness and its
   recorded-cassette tests can be built now; **running it against live Breeze needs
   credentials** (see blockers).
2. **Broker capability snapshot v0** (manual CSV acceptable, §3.4) — this closes the loop on
   the calendar: `session_at()` already requires the broker cutoff as data, and the snapshot
   is where that datum comes from.
3. Merge `m/0-scaffold` to main (CI-certified across eight green builds; awaiting the owner's
   go), then re-run `pips-ci` with `REF=main`.

## Blockers / awaiting
- **ACTION FOR THE OWNER — worth doing today, long lead time.** `ops/runbooks/authority.md`
  contains a ready-to-send letter asking ICICI to confirm that Breeze may be used as a
  read-only data source for signals executed at another broker, on your own account. Nothing
  before P6 is blocked by it, but a written answer from a bank's API-support desk takes weeks,
  and the cost of asking is one email. Send it, then record the filing date in
  `docs/reports/feasibility/gate0-authority.yaml` (the runbook gives the exact YAML).
  The loop cannot file it, answer it, or clear it — GATE-0 is human-only (§10.6).
- **Human-only, needed to finish M3:** Breeze API credentials for the feasibility probe.
  Probe results are committed as saved artifacts; CI never makes live calls.
- **Awaiting the owner (not blocking):** the merge of `m/0-scaffold` to main.
- **Known gap, deliberately not filled:** `config/calendars/nse_equity.yaml` ships an empty
  holiday list with `holidays_verified: false`; sourced at M6.
