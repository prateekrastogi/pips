# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M13 S1 runner — mostly DONE.** BH-FDR within family×universe, Newey-West HAC t, half-life,
monotonicity, coverage, and **null-search calibration** — which caught a real 7x over-rejection
in the statistics chain. Remaining: compute plugins for A02-A08/A12, and the first real sweep
report (needs data).

**M12 alpha wave 1 — DONE.** All nine T1 families (A01-A08, A12) are pre-registered with
falsifiers transcribed from their reference cards, A05/A06 are structurally independent
(no ex-post sign selection), and `make s1-smoke` runs the funnel. Contracts enforced: The contracts are `enforced`: `[C-SPEC-01]` refuses a spec
without null models or a written falsifier (rule 5, at entry), `[C-FCST-01]` carries the
two-term trade gate. A01 also carries a compute plugin that passes the
neutralization test; A02-A08 and A12 are pre-registrations awaiting their plugins.

**M10 vectorized engine (F0) — DONE.** Three-day toy case reconciles to the paisa
(gross 3,000,000 · cost 10,644 · net 2,989,356), the accounting identity holds by
construction, and a peeking signal dies *inside* the engine. `[C-FILL-01]` is now `building`:
F0 and the tier-stamping half landed; F1-F3 are M14/M24.

**M11 registry + multiplicity ledger — DONE** (`[C-REG-01]` `enforced`). Append-only is
enforced by SQLite triggers, M counts every status, M_erank collapses to 1 on clones and
rises to N on independent trials, and the Appendix B experiment manifest parses.

**M9 cost model — DONE.** All four `[C-COST-*]` rows are `enforced`: the statutory stack
reproduces all five §3.7 goldens exactly, and the execution-friction terms enforce the
*structure* reference §10.2-§10.3 specifies (additive, monotone in aggression, square-root
impact) with every constant declaring itself an uncalibrated placeholder.

**M3.5 arb-vm deploy rail — built and VM-bootstrapped; end-to-end verify blocked on two human
items.** arb-vm now has Docker 29.7.2 + Compose v5.5.0 running, `/srv/pips` with all data
zones and a 0700 secrets dir, and a read-only deploy keypair. The rail (`sync.sh`,
`rollback.sh`, `healthcheck.sh`, `alert.sh`, systemd unit + timer) is written and its
market-hours guard is tested. M0, M0.5, M1, M2 done; M3 done except the Breeze probe.

## Last verify output
```
M9 Verify (§6) — pytest tests/unit/costs -q -> 15 passed
  Flattrade  Rs1L: buy 6.74 / sell 28.74 / RT 35.48 = 3.548 bps      <- §3.7 golden, exact
  High-cost  Rs1L: buy 30.34 / sell 52.34 / RT 82.68 = 8.268 bps     <- §3.7 golden, exact
  High-cost RT bps at 50k / 2L / 5L: 10.63 / 5.91 / 4.49             <- §3.7 goldens, exact

arb-vm    Docker 29.7.2 · Compose v5.5.0 · daemon active · docker usable as ubuntu
          /srv/pips/{bronze,silver,gold,quarantine,snapshots,universes,deploy} owned by ubuntu
          /srv/pips/secrets 0700 · deploy.env 0600 · deploy keypair generated (private stays there)

pips deploy guard breeze-reader  --now 2026-06-01T12:00 -> DEFER (exit 1)  protected window
pips deploy guard breeze-reader  --now 2026-06-01T16:00 -> ALLOW (exit 0)
pips deploy guard research-runner --now 2026-06-01T12:00 -> ALLOW (exit 0)  rolls always

make ci -> ci: green
  ruff 96 files · mypy --strict 96 files · 440 pytest · clippy clean (21 crates) ·
  cargo test ok · determinism bit-identical · ledger-check 26 rows (12/3/11)

null-search calibration (the S1 chain checking itself on destroyed data)
  q=0.05 -> survivor 0.05 · q=0.10 -> 0.08 · q=0.20 -> 0.17   all calibrated

make s1-smoke -> the S1 funnel ran end to end on fixtures
  9 specs registered · 4 with compute plugins (A01-A04) · 5 awaiting one (stated, not hidden)
  1875 bars · 3708 forecasts · rank_ic 0.0063 · p 0.7114 (correctly does NOT promote)
  harness_self_test OK (shuffled mean |IC| 0.0138 < bound 0.0821)
  — an IC of 0.006 on a seeded random walk is the RIGHT answer: there is nothing there.
```

## Next 3 actions
1. **Unblock M3.5's end-to-end verify** — needs the two items below. Once main carries the
   rail and the VM can clone, the Verify is: push a trivial commit to main → the VM runs the
   new SHA within one poll; a deliberately failing health check rolls back; a main update
   during simulated market hours defers trading-path restarts.
2. **M4 Breeze ingest** — harvest-first from SAL-0001..0004 (`intraday be8186d`), running on
   arb-vm. Needs the Breeze token in `.env` and the deploy rail live.
3. **Compute plugins for A05-A08 and A12** — the session-structure family (gap
   continuation/reversal, opening-range breakout, compression-to-expansion) plus the
   intraday seasonal. These exercise the calendar and session states built at M2. Still no
   credentials required.

## Blockers / awaiting
- **ACTION FOR THE OWNER (1 of 2) — add the deploy key.** arb-vm cannot clone the private
  repo. A read-only keypair is already generated on the VM; the private half never leaves it.
  Add this as a **deploy key with write access OFF** at
  github.com/prateekrastogi/pips → Settings → Deploy keys:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIUoCb9mUgkJTiF/7AA2s/gNI6k5U2xu2YO+kR2qvyvB pips-deploy@arb-vm (read-only)`
- **PUSHED.** `m/0-scaffold` is now on GitHub (14 green `pips-ci` builds). Pushing is now
  gated: `ops/git-hooks/pre-push` runs `pips-ci` for the branch and blocks on red
  (`make install-hooks`), so a push cannot outrun the gate.
- **ACTION FOR THE OWNER — merge to main.** `main` is still at `46fbdbd`. The deploy rail
  polls `origin/main`, so it has nothing to deploy until the branch lands there. I have not
  merged: that is an outward, hard-to-reverse step and I would rather have it as an explicit
  standing decision than assume it.
- **ACTION FOR THE OWNER (3) — Breeze token** in `.env` (tracked, ADR-0011) for the M3 probe
  and M4. `ops/runbooks/breeze-token.md` is the daily procedure. I put no credential there.
- **Recommended, not blocking:** upgrade `[G-AUTH-0]` evidence from `VERBAL_ATTESTATION` to
  `WRITTEN` by sending the letter in `ops/runbooks/authority.md`, and fill the four blank
  fields in `gate0-owner-attestation.md`.
- **Deliberate placeholders, all erring safe and all marked unverified:** Flattrade's MIS
  square-off (15:00), the Breeze per-minute rate (75/min, **not** inferred from 100k/day), and
  the NSE holiday list (empty). Each is an M3/M6 item.
