# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `main` · **Phase:** P0

> This file is a snapshot, not a log. It had accreted every finished milestone since M0 and
> still named a branch we left and two owner-actions the owner had already cleared. The
> history lives in `docs/state/log/`; this file says what is true now.

## Active item
**M6 PIT masters — bitemporal store landed; masters and pinning still to come.**

`pips/data/pit/store.py` gives the project its two clocks: `valid_from` (when a fact was true
of the world) and `known_from` (when we knew it). The log is append-only in the literal sense —
`correct()` and `close()` append new versions, `known_to` is never stored but implied by the
next version, so no row is ever edited. §6 M6's headline Verify holds as written: an as-of read
is **byte-identical** before and after later snapshots, corrections and delistings land. The
survivorship audit names what disappeared between two dates. `MerkleTree` roots the snapshot
manifests and is pinned by golden vectors, not just by structural properties.

Both M6 ledger rows are `building` rather than `enforced`, and the gap is the point:

- `[C-DATA-01]` — bitemporal columns done. The **zone** half is not: bronze exists, quarantine
  exists, nothing promotes bronze→silver→gold.
- `[C-DATA-02]` — Merkle manifests done. **"Experiments pin `snapshot_root`"** is not: the
  search registry records no root, so a result still cannot be tied to the data it was
  computed on.

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
  ruff 116 files · mypy --strict 116 files · 590 pytest · clippy clean · cargo test ok
  determinism bit-identical · ledger-check 26 rows (planned=10 building=3 enforced=13)

M6 mutation run — 5 deliberate breaks, 4 killed by tests:
  Merkle duplicates odd node       -> killed (test_every_index_proves_against_the_root[9])
  as_of ignores valid time         -> killed (test_a_fact_not_yet_valid_is_withheld…)
  backdating guard removed         -> killed (test_backdating_a_knowledge_date_is_refused)
  CLOSE tombstone ignored          -> killed (test_the_survivorship_audit_names_what…)
  leaf/node domain separation off  -> SURVIVED  ->  golden vectors added, see the log

M9 §3.7 cost goldens — all five exact (Flattrade Rs1L RT 3.548 bps; high-cost 8.268 bps)
null-search calibration — q=0.05 -> 0.05 · q=0.10 -> 0.08 · q=0.20 -> 0.17  (calibrated)
make s1-smoke — 9 specs · 4 with plugins · rank_ic 0.0063 · p 0.7114 (correctly no promotion)
```

## Next 3 actions
1. **Pin `snapshot_root` in the search registry** — the second half of `[C-DATA-02]`, and the
   smallest remaining step that promotes a row. A trial record gains the root of the data
   snapshot it read, so a result can be re-derived years later against the same bytes.
2. **Instrument master on the PIT store** — token/symbol change history is the master that
   makes the rest of M6 possible, and the one that makes a symbol-keyed join honest.
3. **Compute plugins for A05–A08 and A12** — the session-structure family plus the intraday
   seasonal. Exercises the M2 calendar and needs no credentials or data.

## Blockers / awaiting
- None blocking. All three owner-actions (deploy key, Breeze token, merge to main) are cleared.
- **Recommended, not blocking:** upgrade `[G-AUTH-0]` evidence from `VERBAL_ATTESTATION` to
  `WRITTEN` by sending the letter in `ops/runbooks/authority.md`, and fill the four blank
  fields in `gate0-owner-attestation.md`.
- **Deliberate placeholders, all erring safe and all marked unverified:** Flattrade's MIS
  square-off (15:00), the Breeze per-minute rate (75/min — **not** inferred from the owner's
  100k/day and 32 parallel fetches), and the NSE holiday list (empty). Each is an M6 item.
- **Never measured, deliberately:** Breeze's true per-minute limit, WS subscription capacity,
  BSE support. Each would cost live calls to learn and none blocks current work.
