# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `m/0-scaffold` · **Phase:** P0

## Active item
**M3.5 arb-vm deploy rail — built and VM-bootstrapped; end-to-end verify blocked on two human
items.** arb-vm now has Docker 29.7.2 + Compose v5.5.0 running, `/srv/pips` with all data
zones and a 0700 secrets dir, and a read-only deploy keypair. The rail (`sync.sh`,
`rollback.sh`, `healthcheck.sh`, `alert.sh`, systemd unit + timer) is written and its
market-hours guard is tested. M0, M0.5, M1, M2 done; M3 done except the Breeze probe.

## Last verify output
```
arb-vm    Docker 29.7.2 · Compose v5.5.0 · daemon active · docker usable as ubuntu
          /srv/pips/{bronze,silver,gold,quarantine,snapshots,universes,deploy} owned by ubuntu
          /srv/pips/secrets 0700 · deploy.env 0600 · deploy keypair generated (private stays there)

pips deploy guard breeze-reader  --now 2026-06-01T12:00 -> DEFER (exit 1)  protected window
pips deploy guard breeze-reader  --now 2026-06-01T16:00 -> ALLOW (exit 0)
pips deploy guard research-runner --now 2026-06-01T12:00 -> ALLOW (exit 0)  rolls always

make ci -> ci: green
  ruff 65 files · mypy --strict 65 files · 255 pytest · clippy clean (21 crates) ·
  cargo test ok · determinism bit-identical · ledger-check 26 rows (20/2/4)
```

## Next 3 actions
1. **Unblock M3.5's end-to-end verify** — needs the two items below. Once main carries the
   rail and the VM can clone, the Verify is: push a trivial commit to main → the VM runs the
   new SHA within one poll; a deliberately failing health check rolls back; a main update
   during simulated market hours defers trading-path restarts.
2. **M4 Breeze ingest** — harvest-first from SAL-0001..0004 (`intraday be8186d`), running on
   arb-vm. Needs the Breeze token in `.env` and the deploy rail live.
3. **M6 masters** or **M9 cost model** — both have donors and neither needs credentials, so
   either is available if M4 stays blocked.

## Blockers / awaiting
- **ACTION FOR THE OWNER (1 of 2) — add the deploy key.** arb-vm cannot clone the private
  repo. A read-only keypair is already generated on the VM; the private half never leaves it.
  Add this as a **deploy key with write access OFF** at
  github.com/prateekrastogi/pips → Settings → Deploy keys:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIUoCb9mUgkJTiF/7AA2s/gNI6k5U2xu2YO+kR2qvyvB pips-deploy@arb-vm (read-only)`
- **ACTION FOR THE OWNER (2 of 2) — merge and push.** `main` on GitHub is still at the initial
  commit `46fbdbd`; none of this work is pushed. The rail polls `origin/main`, so it has
  nothing to deploy until `m/0-scaffold` lands there. Ten green `pips-ci` builds so far.
  I have deliberately not merged or pushed.
- **ACTION FOR THE OWNER (3) — Breeze token** in `.env` (tracked, ADR-0011) for the M3 probe
  and M4. `ops/runbooks/breeze-token.md` is the daily procedure. I put no credential there.
- **Recommended, not blocking:** upgrade `[G-AUTH-0]` evidence from `VERBAL_ATTESTATION` to
  `WRITTEN` by sending the letter in `ops/runbooks/authority.md`, and fill the four blank
  fields in `gate0-owner-attestation.md`.
- **Deliberate placeholders, all erring safe and all marked unverified:** Flattrade's MIS
  square-off (15:00), the Breeze per-minute rate (75/min, **not** inferred from 100k/day), and
  the NSE holiday list (empty). Each is an M3/M6 item.
