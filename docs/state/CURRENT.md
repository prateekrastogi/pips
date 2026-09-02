# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-09-01 · **Branch:** `main` · **Phase:** P0 · loop running (5m).

> Rewritten after incremental edits left this file self-contradictory — two "action 2"s, one
> claiming the QC seam resolved nothing immediately after saying it was done. This is the
> document every tick orients on, so a stale one poisons the ticks that read it.

> This file is a snapshot, not a log. It had accreted every finished milestone since M0 and
> still named a branch we left and two owner-actions the owner had already cleared. The
> history lives in `docs/state/log/`; this file says what is true now.

## Active item
**M19 selection + turnover optimizer — the Pareto sort, the 1-corr clustering and the frontier
reduction that composes them have landed `[C-SEL-01]`.** Still ledgered `building`, precisely:
`select_frontier` gives the sort and the clustering a caller, but nothing in the SEARCH calls
`select_frontier` — the chain is connected to itself, not yet to a pipeline. τ*/h* per broker ×
tier have landed too `[C-TURN-01]`: §6.1's Faustmann rotation condition, §6.2's selectivity
threshold, and a planner that refuses an optimum beyond the horizon `alpha(h)` was fitted over.
§6.3's joint fixed point has landed too: coordinate descent that REFUSES rather than returning
the last iterate when the map does not contract, and names a cycle as a cycle. The
combined-blotter netting fixed point has landed too `[C-NET-01]`: the netting window is required
with no default, and a ratio of 1.0 (nothing reaches the market) is refused rather than priced
as a zero cost line. Order-budget constraints have landed `[C-OBUD-01]`, measured on a SLIDING
one-second window: the 5/s governor binds rather than SEBI's ~10/s threshold, because a strategy
the governor throttles is not the strategy that was validated.

**S5 now runs the chain** `[C-S5-01]`: frontier → clustering → correlation gate → netting fixed
point → τ*/h* at the re-priced line → order budget on the combined blotter, reporting the funnel
step by step so a filter that rejects everything cannot pass for a selective search.
S5 solves τ* and h* **jointly** per §6.3, at each venue's own cost line, naming any venue whose
coordinate descent will not settle rather than dropping it or answering it with the weaker
solver. `[C-SEL-01]`, `[C-TURN-01]`, `[C-NET-01]` and `[C-OBUD-01]` are all now **enforced** — by
construction, since no pipeline runs S5 against the registry yet.

**M18 is COMPLETE**: PSR/DSR, CSCV/PBO, the stationary bootstrap, Hansen's SPA, Romano–Wolf
stepdown, the sealed lockbox (enforced in the data layer, not just recorded in the ledger) and
hierarchical partial pooling for family means. M16 and M17 are done: stress battery, falsifier
binding with an honest coverage report, concentration leave-outs. M15 is DONE: purged/embargoed
outer and inner folds, plateau-centroid selection, successive halving that counts every viewed
trial (rule 4). M14 is complete: F1 state machine, flatten scheduler and F0/F1 reconciliation.
M6's masters are complete except ASM/GSM/T2T and index membership; all nine T1 alphas have
compute plugins.

`[G-PROV-01]` closed a defect in the gate itself: `docker compose run research make ci` — the
command the docs named as THE way to verify — reported `ci: green` from a day-old image. The
verify image now states which commit it holds and refuses to run the ladder against anything
else; `make ci-container` is the documented command (ADR-0013).

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

The **broker-capability snapshotter** is now on the store too, with the two clocks separated —
a change announced weeks before it takes effect is finally expressible, which one
`snapshot_date` column never could. Wiring it surfaced a real bug in `PitStore.as_of`: a
future-dated version was MASKING the one actually in force, so the key vanished from the table
entirely. Fixed, with the regression test in the store's own suite where it belonged.

Still unwritten for M6: ASM/GSM/T2T and index membership. The calendar's holiday list is still
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
  ruff 246 files · mypy --strict 246 files · 1803 pytest · clippy clean · cargo test ok
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
  coverage now reported: 6 records, comparisons made 4, skipped 2 (each symbol's first
  session has no predecessor) — "0 findings" finally arrives with its own scope attached
falsifier-binding mutation run — removing the registry's import killed NOTHING, and that
  import is the whole premise: without it "this check exists" is "this name is in a dict I
  wrote". Needed a phantom module entry to observe. Eighth test-level finding this session.
falsifier coverage — 15 bound, 17 unbound of 32. The unbound are NAMED, not just counted.
falsifier coverage — 22 bound, 10 unbound of 32; A02, A05, A07 and A12 fully bound.
  NOTHING LEFT IS UNBLOCKED: the last ten need a sector map, T2 quote data, an events or
  circuit master, or an out-of-sample refit.
stress battery — all_run_cases_passed True, certifies False (4 cases cannot run: 3 need
  per-bucket attribution, 1 needs a sector map). With every input provided it certifies.
stress-battery mutation run — 6 of 6 killed. The drop-best-block fixture could NOT be
  repaired by changing the fixture: any version spiky enough to matter fails the case under
  both implementations. Asserted the operation directly instead.
halving mutation run — 7 of 7 killed once run INDIVIDUALLY; a batched shell loop reported
  two false survivors by swallowing output. Second harness defect this session (after stale
  .pyc), same bias: towards false survivors. Rule now: one mutation at a time, output visible.
plateau mutation run — 5 of 7 killed, 2 SURVIVED, both FIXTURES that could not distinguish
  the right answer from a wrong one (a uniform plateau makes centre == argmax; a size floor
  filtered out the region the choice was meant to test). Fifth and sixth time this session.
M15 mutation run — found the embargo was DECORATION in a forward-only walk (it can never
  bind when training is entirely in the past), which is what drove building the inner folds.
  ALSO found a flaw in the mutation harness itself: fast write/restore cycles left stale
  .pyc files, so pytest re-ran cached mutated modules against restored sources. Biases
  towards FALSE SURVIVORS. The harness now clears __pycache__ before every run.
F1 mutation run — 5 of 7 killed, 2 SURVIVED, both SLACK ASSERTIONS rather than code faults:
  a bound the wrong answer also satisfies is not a test (third time this session).
verdict-seam mutation run — 3 of 4 killed, 1 SURVIVED:
  resolve_symbol(on=day) -> on=date.max killed nothing — the reused-symbol splice
  reintroduced at the JOIN. Now covered; mutation caught.

M9 §3.7 cost goldens — all five exact (Flattrade Rs1L RT 3.548 bps; high-cost 8.268 bps)
null-search calibration — q=0.05 -> 0.05 · q=0.10 -> 0.08 · q=0.20 -> 0.17  (calibrated)
make s1-smoke — 9 specs · ALL NINE with plugins (DERIVED not hardcoded) · 0 awaiting
  rank_ic 0.0063 · p 0.7114 (correctly no promotion)
gap-family mutation run — 5 of 6 killed, 1 SURVIVED:
  breadth counting the name itself — a floor of 1/n, so a name whose only peer disagrees
  reads half-confirmed BY ITSELF. Now tested at a threshold that separates the two.
A07 mutation run — 5 of 6 killed, 1 SURVIVED:
  dropping the volatility buffer entirely — my fixture never cleared even the RAW range.
  Fixed by pairing: zero with the buffer, positive with buffer_atr=0.
A12 mutation run — 5 of 6 killed; the survivor was the zero-variance branch, whose only
  coverage I had just removed by de-degenerating the fixtures.
capability-master mutation run — 5 of 5 killed. And it found a PitStore bug its own suite
  missed: a future-dated version masked the version in force, so the key vanished entirely.
A08 mutation run — 3 of 6 killed, 3 SURVIVED, incl. THE HEADLINE CLAIM:
  removing volatility normalisation killed nothing —  held under the alpha
  AND under the variance forecast it must not be. Fixed with a RATIO (>5x), not an ordering.
  Two more survived because the test never reached the guard.
```

## Next 3 actions
1. **`stability.concentration` — the owner's call**, and the LAST gate with no declared bar.
   Every other hard gate now computes: DSR 0.229, SPA p 0.844, plateau 0.903 (for the families
   whose winner is not at a grid edge). Its figures appear only under §11.4 *Tripwires —
   auto-flags in every report*; the certification table gives no number. Setting it = a
   `gates.yaml` row + enforcing code + an ADR in one commit.
2. **Backfill, and the related question: should S4 filter?** Every gate now says the same thing
   about two synthetic random walks, correctly. Deciding whether the gates should DROP
   candidates rather than score them is a judgement that wants real bars behind it. External
   Breeze calls on a metered budget with the owner's credentials; 100k calls/day, 32 parallel.
3. **Six of eight fixture winners sit at a grid EDGE**, so their plateau is undefined by design.
   Worth understanding rather than working around: an optimum at the boundary of a
   pre-registered domain means either the domain is wrong or the surface is noise. On two
   symbols over three days it is almost certainly noise — another argument for (2).

`certify-smoke`: **0 certified, 31 unsupplied** for the best-documented candidate. PBO needs
walk-forward IS/OOS matrices; the stress battery belongs to M14's event engine; capacity to the
order-budget planner; operations to session policy that does not exist;
`decision.rationale`/`outcome` a human writes.

## Blockers / awaiting
- None blocking. The security-master download was approved and completed; 5,851 instruments
  are live in the PIT store on arb-vm and the QC verdict seam resolves end to end. The orphaned `checkout` compose project was cleared with the
  owner's go-ahead. All three original owner-actions remain cleared.
- **Recommended, not blocking:** upgrade `[G-AUTH-0]` evidence from `VERBAL_ATTESTATION` to
  `WRITTEN` by sending the letter in `ops/runbooks/authority.md`, and fill the four blank
  fields in `gate0-owner-attestation.md`.
- **Deliberate placeholders, all erring safe and all marked unverified:** Flattrade's MIS
  square-off (15:00), the Breeze per-minute rate (75/min — **not** inferred from the owner's
  100k/day and 32 parallel fetches), and the NSE holiday list (empty). Each is an M6 item.
- **Never measured, deliberately:** Breeze's true per-minute limit, WS subscription capacity,
  BSE support. Each would cost live calls to learn and none blocks current work.
