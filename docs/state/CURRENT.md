# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M3 GATE-0 + feasibility probe — mostly done.** `[G-AUTH-0]` is **CLEARED** (owner-attested
verbal confirmation from ICICI; caveat surfaced on every check). Broker capability snapshot v0
landed and now drives the calendar's cutoff. Breeze quota confirmed and recorded. Remaining:
the live Breeze probe (needs the token in `.env`).

## Last verify output
```
make authority-check
  [G-AUTH-0] status=GRANTED feed=BREEZE   live trading: PERMITTED by this gate
  CAVEAT: cleared on a VERBAL confirmation — §2.1 asks for written; follow-up recommended
  (still gated by the rest of the live-flag chain — rule 8)

make ci -> ci: green
  ruff 62 files · mypy --strict 62 files · 235 pytest · clippy clean (21 crates) ·
  cargo test ok · determinism bit-identical · ledger-check 26 rows
```

## Next 3 actions
1. **Finish M3 — the Breeze probe.** Everything else is in place: `config/breeze.yaml` holds
   the confirmed quota, and the probe's job is now narrower (per-minute sustained/burst rate,
   daily-counter reset boundary, history depth per symbol, bar-timestamp convention for
   ADR-0001, WS capacity, BSE ambiguity). **It runs on arb-vm, never the laptop** (rule 14),
   and writes saved artifacts under `docs/reports/feasibility/`. Needs `BREEZE_SESSION_TOKEN`
   in `.env` — see blockers.
2. **M3.5 arb-vm deploy rail** `[C-DEPLOY-01]` `[G-DEPLOY-01]` — has a real donor (SAL-0010).
   This is the prerequisite for running anything on the VM, so it may be worth taking before
   the probe rather than after.
3. Merge `m/0-scaffold` to main (CI-certified across nine green builds; awaiting the owner's
   go), then re-run `pips-ci` with `REF=main`.

## Blockers / awaiting
- **ACTION FOR THE OWNER:** paste the Breeze API key, secret and daily session token into
  `.env` (now tracked, ADR-0011) and commit. `ops/runbooks/breeze-token.md` is the daily
  procedure. Until then the M3 probe cannot run. **I have not put any credential in that
  file — the placeholders are empty and filling them is yours.**
- **ACTION FOR THE OWNER (not blocking, recommended):** send the letter in
  `ops/runbooks/authority.md` anyway and upgrade `evidence_kind` to `WRITTEN`. The gate is
  cleared on verbal evidence, which §2.1 does not ask for; a written reply costs one email
  and is what a compliance review would expect to see.
- **Also for the owner:** `docs/reports/feasibility/gate0-owner-attestation.md` has four
  blank fields (channel, person/reference, date of the confirmation, their words). An
  attestation that can be corroborated is worth much more than one that cannot.
- **Awaiting the owner (not blocking):** the merge of `m/0-scaffold` to main.
- **Deliberate placeholders, both erring safe and both marked unverified:** Flattrade's MIS
  square-off (15:00 in the capability CSV — the ~15:12/~15:25 figures on record are
  *Zerodha's*) and the Breeze per-minute rate (75/min in `config/breeze.yaml`, **not** inferred
  from the 100k/day cap). Both are M3-probe items; `require_verified_square_off()` refuses the
  first on any path to real capital.
- **Known gap:** `config/calendars/nse_equity.yaml` ships an empty holiday list; sourced at M6.
