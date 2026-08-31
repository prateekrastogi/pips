# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `main` · **Phase:** P0

> This file is a snapshot, not a log. It had accreted every finished milestone since M0 and
> still named a branch we left and two owner-actions the owner had already cleared. The
> history lives in `docs/state/log/`; this file says what is true now.

## Active item
**M6 PIT masters — bitemporal store and root-pinning landed; the masters themselves are next.**

`pips/data/pit/store.py` gives the project its two clocks: `valid_from` (when a fact was true
of the world) and `known_from` (when we knew it). The log is append-only in the literal sense —
`correct()` and `close()` append new versions, `known_to` is never stored but implied by the
next version, so no row is ever edited. §6 M6's headline Verify holds as written: an as-of read
is **byte-identical** before and after later snapshots, corrections and delistings land. The
survivorship audit names what disappeared between two dates. `MerkleTree` roots the snapshot
manifests and is pinned by golden vectors, not just by structural properties.

`[C-DATA-02]` is now **`enforced`**: a run cannot be recorded without a validated 64-hex
`snapshot_root`, so no code path writes an unpinned trial, and `verify_pinned_root` checks a
pin against the store that produced it. Stated precisely, because the label invites more than
it means — no runner writes RunRecords yet, so the constraint holds *by construction rather
than by observation*, and nothing calls `verify_pinned_root` in a pipeline. The gate is built
ahead of the traffic, which is the right order, but it has not yet stopped anything.

`[C-DATA-01]` stays **`building`**: bitemporal columns are done, the **zone** half is not —
bronze exists, quarantine exists, nothing promotes bronze→silver→gold.

Still unwritten for M6: the instrument master with token/symbol change history, corporate
actions, ASM/GSM/T2T, the broker-capability daily snapshotter (M3's manual CSV is the v0), and
index membership. Two things already wait on it — the calendar's holiday list is still
`holidays_verified: false`, and QC quarantines every unexplained ratio jump because no
corporate-action master exists to explain one.

## Done
M0, M0.5, M1, M2, M3, M3.5, M4, M5, M9, M10, M11, M12. M13 mostly (compute plugins for
A02–A08/A12 and the first real sweep report outstanding).

The deploy rail is live: `main` is the shipping branch, arb-vm builds and runs every green SHA
within one 2-minute poll, trading-path services never restart in the protected window, and
`ops/git-hooks/pre-push` blocks a red push. Real data is on the VM — 6 symbol-days of bronze
at `/srv/pips/bronze`, QC-green against a calendar-derived coverage expectation.

## Last verify output
```
make ci -> ci: green
  ruff 118 files · mypy --strict 118 files · 600 pytest · clippy clean · cargo test ok
  determinism bit-identical · ledger-check 26 rows (planned=10 building=2 enforced=14)

M6 mutation run — 5 deliberate breaks, 4 killed by tests:
  Merkle duplicates odd node       -> killed (test_every_index_proves_against_the_root[9])
  as_of ignores valid time         -> killed (test_a_fact_not_yet_valid_is_withheld…)
  backdating guard removed         -> killed (test_backdating_a_knowledge_date_is_refused)
  CLOSE tombstone ignored          -> killed (test_the_survivorship_audit_names_what…)
  leaf/node domain separation off  -> SURVIVED  ->  golden vectors added, see the log

snapshot-pinning mutation run — 3 of 3 killed:
  root validator removed · verify_pinned_root always true · open-time drift raise removed

deploy rail — TWO defects found by verifying a push (both fixed, see the log):
  1. wedged silently: a failed deploy that had already fast-forwarded was never retried,
     because the up-to-date check consulted the CHECKOUT, not what was deployed.
     Every poll then logged `already at 8aa1a61; nothing to do` — forever.
  2. `config --services` failed transiently and the rail reported it as
     `service 'breeze-reader' vanished` — a failed command read as a fact about the fleet.

M9 §3.7 cost goldens — all five exact (Flattrade Rs1L RT 3.548 bps; high-cost 8.268 bps)
null-search calibration — q=0.05 -> 0.05 · q=0.10 -> 0.08 · q=0.20 -> 0.17  (calibrated)
make s1-smoke — 9 specs · 4 with plugins · rank_ic 0.0063 · p 0.7114 (correctly no promotion)
```

## Next 3 actions
1. **Instrument master on the PIT store** — token/symbol change history is the master the
   rest of M6 rests on, and the one that makes a symbol-keyed join honest. It is also what
   turns `snapshot_root` from a built gate into a used one, since a real master is the first
   thing a run would pin a root over.
2. **Corporate-action master** — QC currently quarantines *every* unexplained ratio jump
   because nothing exists to explain one, so this directly unblocks a check that is firing
   blind today.
3. **Compute plugins for A05–A08 and A12** — the session-structure family plus the intraday
   seasonal. Exercises the M2 calendar and needs no credentials or data.

## Blockers / awaiting
- **ACTION FOR THE OWNER — an orphaned compose project is running a duplicate fleet.**
  arb-vm has TWO compose projects from the same file: `pips` (correct) and `checkout`, a
  leftover from before `name: pips` landed, whose containers are still up on SHA `a7248c2`.
  That means **two breeze-readers**, which doubles consumption against the 100k/day budget.
  I did not remove them unilaterally — they are running services on your VM. To clear:
  `ssh arb-vm 'docker compose -p checkout down'`. Say the word and I will run it.
- None otherwise. All three original owner-actions (deploy key, Breeze token, merge to main)
  are cleared.
- **Recommended, not blocking:** upgrade `[G-AUTH-0]` evidence from `VERBAL_ATTESTATION` to
  `WRITTEN` by sending the letter in `ops/runbooks/authority.md`, and fill the four blank
  fields in `gate0-owner-attestation.md`.
- **Deliberate placeholders, all erring safe and all marked unverified:** Flattrade's MIS
  square-off (15:00), the Breeze per-minute rate (75/min — **not** inferred from the owner's
  100k/day and 32 parallel fetches), and the NSE holiday list (empty). Each is an M6 item.
- **Never measured, deliberately:** Breeze's true per-minute limit, WS subscription capacity,
  BSE support. Each would cost live calls to learn and none blocks current work.
