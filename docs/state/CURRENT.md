# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-08-31 · **Branch:** `main` · **Phase:** P0

> This file is a snapshot, not a log. It had accreted every finished milestone since M0 and
> still named a branch we left and two owner-actions the owner had already cleared. The
> history lives in `docs/state/log/`; this file says what is true now.

## Active item
**M6 PIT masters — store, root-pinning, instrument master and corporate actions landed.**

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

The **instrument master** now sits on the store (`pips/data/pit/instruments.py`, from scratch
per SAL-0026 NONE_FOUND). Keyed on ISIN, with symbol and exchange-token histories, because a
symbol is a label the exchange lends out rather than an identity: NSE frees it on delisting and
can lend the same letters to a different company later, and a symbol-keyed join across that
boundary splices two companies into one price series. An ambiguous resolution is refused, not
guessed — guessing would usually be right, which is what makes it dangerous.

The **corporate-action master** followed (SAL-0016 harvested for shape only — the donor's own
adjustment rule is a lookahead, and both of its bugs are now pinned as mutations that must
fail). Its causality rule is the substance: adjust a bar at `bar_on`, as of `as_of`, using
actions where `bar_on < ex_date <= as_of` **and** `known_from <= as_of`.

Wiring it turned up a real hole: `check_unexplained_ratio_jump` had **never been called by the
runner** — written at M5, unit-tested, dead — and it also cleared *any* jump if *any* action
was declared that day. Both fixed, plus a meta-test asserting every check the suite defines is
actually run.

Still unwritten for M6: ASM/GSM/T2T, the broker-capability daily snapshotter (M3's manual CSV
is the v0), and index membership. The calendar's holiday list is still
`holidays_verified: false`.

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
  ruff 130 files · mypy --strict 130 files · 688 pytest · clippy clean · cargo test ok
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
  Both fixed and deployed; the rail promoted 3205586 cleanly at 12:18 with no alerts.

instrument-master mutation run — 4 mutations, 3 killed immediately, 1 SURVIVED:
  gap fallback · ambiguity picks first · ISIN validation  -> killed
  symbol_history dedup removed -> SURVIVED (untested claim; now covered, mutation caught)

corporate-action mutation run — 6 of 6 killed, including both donor bugs reproduced:
  drop ex_date<=as_of (the donor's lookahead) · drop bar_on<ex_date · tolerance accepts all
  unadjustable kind silently returns 1 (the donor's other bug) · explains_jump ignores as_of
  ratio sanity check removed
QC runner wiring — 3 of 3 killed: adjacency guard, finding discarded, previous close never kept
QC on real arb-vm data — control 0 findings; injected halving -> ratio_jump quarantined
verdict-seam mutation run — 3 of 4 killed, 1 SURVIVED:
  resolve_symbol(on=day) -> on=date.max killed nothing — the reused-symbol splice
  reintroduced at the JOIN. Now covered; mutation caught.

M9 §3.7 cost goldens — all five exact (Flattrade Rs1L RT 3.548 bps; high-cost 8.268 bps)
null-search calibration — q=0.05 -> 0.05 · q=0.10 -> 0.08 · q=0.20 -> 0.17  (calibrated)
make s1-smoke — 9 specs · 8 with plugins (A01-A08, DERIVED not hardcoded) · 1 awaiting
  rank_ic 0.0063 · p 0.7114 (correctly no promotion)
gap-family mutation run — 5 of 6 killed, 1 SURVIVED:
  breadth counting the name itself — a floor of 1/n, so a name whose only peer disagrees
  reads half-confirmed BY ITSELF. Now tested at a threshold that separates the two.
A07 mutation run — 5 of 6 killed, 1 SURVIVED:
  dropping the volatility buffer entirely — my fixture never cleared even the RAW range.
  Fixed by pairing: zero with the buffer, positive with buffer_atr=0.
A08 mutation run — 3 of 6 killed, 3 SURVIVED, incl. THE HEADLINE CLAIM:
  removing volatility normalisation killed nothing —  held under the alpha
  AND under the variance forecast it must not be. Fixed with a RATIO (>5x), not an ordering.
  Two more survived because the test never reached the guard.
```

## Next 3 actions
1. **AWAITING OWNER: the security-master download.** The seam is connected (symbol → as-of
   instrument master → ISIN → action master → verdict) and tested end to end, but no real
   instruments are loaded, so it still resolves nothing and fails closed. Probing settled how
   to load them: `get_names` returns no ISIN, and the SDK's own master loader discards every
   column except code/token/name — so the 2.9 MB `SecurityMaster.zip` must be fetched and its
   raw `.txt` parsed. See `docs/reports/feasibility/breeze-security-master.md`.
2. **NSE holiday list** — `holidays_verified: false` today, so every session-state decision
   rests on an empty list. It is the last unverified placeholder in the calendar.
3. **Compute plugin for A12** — the intraday seasonal, the last of the nine. A05/A06 landed as
   a pair (writing one first would itself be the ex-post sign selection their pre-registration
   forbids), then A07 and A08. Needs no credentials or data.

## Blockers / awaiting
- **ACTION FOR THE OWNER — may I download the ICICI security master to the VM?**
  `https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip` · 2.9 MB ·
  `application/zip` · refreshed daily. It is the only source of ISIN/series/lot/tick for the
  M6 instrument master (`get_names` has none of them, and the SDK's own loader throws them
  away). Same vendor and same read-only data plane as Breeze, but a different endpoint from
  the one the GATE-0 attestation names, so I am asking rather than assuming. Fetched by the
  official SDK's own method; would land on the VM only, per rule 14.
- Otherwise none blocking. The orphaned `checkout` compose project was cleared with the
  owner's go-ahead. All three original owner-actions remain cleared.
- **Recommended, not blocking:** upgrade `[G-AUTH-0]` evidence from `VERBAL_ATTESTATION` to
  `WRITTEN` by sending the letter in `ops/runbooks/authority.md`, and fill the four blank
  fields in `gate0-owner-attestation.md`.
- **Deliberate placeholders, all erring safe and all marked unverified:** Flattrade's MIS
  square-off (15:00), the Breeze per-minute rate (75/min — **not** inferred from the owner's
  100k/day and 32 parallel fetches), and the NSE holiday list (empty). Each is an M6 item.
- **Never measured, deliberately:** Breeze's true per-minute limit, WS subscription capacity,
  BSE support. Each would cost live calls to learn and none blocks current work.
