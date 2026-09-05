# CURRENT.md — active state (overwritten every session)

**Updated:** 2026-09-04 · **Branch:** `main` · **Phase:** P0 · loop running (5m).

> Rewritten after incremental edits left this file self-contradictory — two "action 2"s, one
> claiming the QC seam resolved nothing immediately after saying it was done. This is the
> document every tick orients on, so a stale one poisons the ticks that read it.

> This file is a snapshot, not a log. It had accreted every finished milestone since M0 and
> still named a branch we left and two owner-actions the owner had already cleared. The
> history lives in `docs/state/log/`; this file says what is true now.

## Active item

**The seed is whole, the shortlist path is unblocked, and the next unit is the A+ pre-rank.**

The daily seed's missing first day is repaired: four paced runs re-fetched all 3,101 symbols with
the corrected window (6,208 bronze files, every range key terminal), and the totals — fetched
2,690, empty 411 — match the original seed exactly, so the only thing that changed is the day the
window bug dropped. `20MICR`/`3MIND` went 744 → 745 bars, first bar 2023-09-04.

**The vendor is measured**, not guessed: a burst of ~800 calls at ~600/min before rejection, three
times running. The donor's 100/min is disproven for this account; ~4,900 calls in one day with no
daily rejection makes the disputed 5,000/day unlikely. `config/breeze.yaml`'s conflict note stands,
narrowed. The pacer that measured it had a flaw — additive increase erased its learned backoff
within seconds — fixed by ratcheting the floor on rejection (committed, deploying).

**Decided this weekend (owner):** `BLK-0003` — daily panel beside silver; `gap_rate` a frequency
with corporate actions excluded. `BLK-0005` — **A+**: a three-component pre-rank picks the 500,
the superset property is CHECKED each refresh rather than guaranteed by construction, and an
exploration budget captures names just outside the 500 so a missed name is corrected rather than
permanently absent.

**The A+ pre-rank exists** (`pips.universe.prerank`): the three-component ranking, the superset
check, and the rotating exploration budget — 18 tests, sweep 8/8. **The DailyStats reader exists** (`pips.universe.daily_stats`, 13 tests, sweep 12/12 after two median-blind survivors were fixed). **`pips daily promote` exists** (9 tests; the daily panel had no caller — arb-vm has 6,202 daily records and no `bars_1d.parquet`). **Next unit:** once this deploys, run it on arb-vm inside `research`, then `daily_stats_from_panel` → `prerank_for_capture` for the actual 500 shortlist.

**Open, not blocking:** `BLK-0004` — the streaming namespace refusal is unexplained (entitlement and
whitelist both confirmed by the owner); the next test is Monday 2026-09-07's open. GATE-0's
`evidence_paths` still points at the owner's attestation, not ICICI's reply.

## Superseded by the above
**Nothing is in flight. The research factory is built and every part of it verified as far as
it can be without data; what remains needs the owner.** The four decisions are in *Next
actions* below. The shortlist width — which gated the rest — was decided on 2026-09-03: 500
`[C-M4-06]`. What remains needing the owner is a live market-data authorisation for forward
capture, which is the item where delay costs something that cannot be recovered.

Said plainly because the alternative is inventing work: the data path (M4–M6), the universe
policy (M7), the search funnel (M12/M15/M18), selection and turnover (M19) and certification
(M20) are all present, and every module under `python/pips/` has been through mutation testing.
What is NOT present is a panel — and nothing downstream of the panel can be exercised on
anything but fixtures until the seed runs.

**M19 selection + turnover optimizer — the Pareto sort, the 1-corr clustering and the frontier
reduction that composes them have landed `[C-SEL-01]`.** τ*/h* per broker ×
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
  ruff clean · mypy --strict 299 source files · 2481 pytest · clippy clean · cargo test ok
  determinism bit-identical ACROSS PROCESSES · ledger-check 70 rows
  (planned=7 building=34 enforced=29)
  provenance: running on the host, not in a pips image
  tdd-check NOT RUN: HEAD is main, the base itself, so the range is empty
```

The two lines that are not simply green are the point of them. `provenance` says it is on the
host, where the working tree IS the thing under test and there is nothing to be stale; the
image path is `make ci-container`. `tdd-check` says it verified nothing, because every commit
goes straight onto `main` and `main..HEAD` is therefore empty — it used to print `OK` for that,
which is a NOT_RUN reading as a PASS in the gate for the constitution's central rule.

**Mutation coverage: every module under `python/pips/` has been swept.** The per-module results
are in `docs/state/log/`, not here — this file is a snapshot. What matters as state:

- The harness lives at `ops/mutate/` with a README, rather than dying with a session. It refuses
  to run when a module-level `raise` leaves the listed tests passing (the tests do not exercise
  that file), and names any market data a mutant wrote into `./data`.
- Its limit is known: the canary detects *"these tests do not touch this file"*, never *"these
  tests do not check this property"*. A surprising number of survivors means the test set is too
  narrow — that misled three sweeps before it was written down.
- Four of six `make ci` rungs were found green for the wrong reason and fixed: an unreachable
  Jenkins reported as a red build, a process compared against itself reported as determinism, an
  empty commit range reported as test-first, and a dirty tree reported as clean. `lint`/`typecheck`
  and `test`/`rust-test` are sound; `cargo test` passes with zero test functions because all 21
  crates are M0 scaffolds and all six rust contract rows are `planned`, which is honest.

The recurring defect shape, across the whole sweep, is one thing wearing many costumes: **a check
that did not run reading as a check that passed.** A rate-limited HTTP 200 recorded as "no data",
`NOT_RUN` read as `PASSED`, unknown archival coverage defaulting to covered, an unmeasured
correlation defaulting to diverse, clustering that never ran reported as "in no cluster", a
half-declared gate silently becoming no gate. The second shape is mine rather than the code's:
**a fixture too tidy to distinguish the property from its absence** — a symmetric neighbourhood,
prices exact to the paise, an empty holiday list, a machine that happens to be in IST.


## Next 3 actions — the backfill needs a cheaper first pass

**Correction to the previous entry: U300 is not a list to supply.** §6 M7 specifies it as
`N=300` of the liquidity score `z(log median ₹vol) - 0.75·z(spread) - 0.50·z(Amihud) -
0.25·z(gap-rate)`. The score landed this tick as `[C-UNIV-01]`; M7 had no row and no code.

1. **THE OWNER'S CALL: how to seed the universe — and the previous framing of it was wrong
   in both halves.** Corrected 2026-09-03; the arithmetic below is computed from the repo's own
   calendar and config, not asserted.

   **The blocker is a FETCH SHAPE, not a quota.** Two corrections, the second of which
   corrects the first — both now computed by `plan_campaign` rather than asserted in prose, so
   they can be re-derived instead of re-argued.

   *The vendor's allowance:* `get_historical_data_v2` serves ≤1,000 candles per call over an
   arbitrary range (blueprint §4.4), so three years of DAILY bars is 782 candles — **one call
   per symbol**. The old "~16 quota-days for daily bars" figure applied the 1-minute cost
   model, which is 1 call per symbol-day only because a 375-candle session fills one call.

   *What this code can actually issue:* `budgeted_fetcher` requests `ist_window(day)` — a
   single day — and the manifest and bronze layout are keyed per symbol-day, which is what
   makes a resume granular. **So the per-day toll is paid whatever the interval**, and a daily
   seed costs exactly what a 1-minute one does. Per 1,800 names over 3y:

   | interval | this fetcher | if one call could span days |
   |---|---|---|
   | 1day | 15.6 quota-days | **0.02** |
   | 30minute | 15.6 | 0.22 |
   | 1minute | 15.6 | 5.9 |
   | 1second | 359.7 | 351.9 |

   So the cheap seed is real and was **gated on a bounded code change** — which has now landed:
   `run_range_backfill` + `ranged_fetcher` fetch one call per symbol over a span, keyed in the
   manifest by symbol, interval and range. **What remains is a live probe**, not engineering:
   the multi-day window has never been tried, and `ist_window` exists because Breeze silently
   CLIPS a UTC window rather than erroring. One call for one symbol would settle it, and it
   needs the owner's authorisation.

   **And the score's four inputs are not equally cheap, which the old framing never mentioned.**
   Daily bars give median ₹volume, Amihud and gap-rate. They cannot give **spread** — OHLC has
   no spread at any interval — and `[C-UNIV-01]` requires it: `_usable` drops any symbol missing
   a component, because "a missing spread read as zero makes an illiquid name look tight". The
   blueprint (§4.4) sources spread from **1-second ranges or quote captures**, over the trailing
   **60 sessions** rather than three years. At 23 calls per symbol-session that is **2.48M calls
   (27.6 quota-days) for all 1,800 names** — the genuinely expensive item, and worse than the
   number the old blocker warned about, for a component it did not name. A shortlist of 600
   costs 9.2 quota-days; of 400, 6.1.

   The ordering that falls out: range-fetch daily for everything (1,800 calls once the fetch
   shape exists) → rank on the three daily-derivable components → 1-second for a shortlist →
   the full four-component score → U300 → the 1m campaign already authorised (235,200 calls
   per symbol-day at 2.61 quota-days, or **117,600 at 1.31 with `pips backfill --ranged`**
   `[C-M4-10]`. The ranged path was unreachable from the CLI until 2026-09-04 — the chunker was
   wired into `run_range_backfill` and nothing called it, so the cheaper figure was quoted from
   a code path nobody could invoke).

   **DECIDED: the shortlist is 500** `[C-M4-06]`, authorised 2026-09-03. It was a bias question
   rather than a budget one. Acquiring spread only for the volume-top-N makes the spread z
   cross-sectional over N rather than over the eligible list, so a modest-volume name with an
   excellent spread could never surface — and spread carries the second-largest weight
   (−0.75). 500 also buys the property that matters more: it is the stable-core buffer applied
   to DATA, so a name entering U300 is already being captured rather than arriving cold.

   The mechanism is *filter for admissibility, then score to cut to N*. The filter names the
   field behind every rejection and can say "not measured"; the score is M7's own, unchanged,
   which makes the shortlist a superset of every registered universe by construction. 500 is
   deliberately absent from `SUPPORTED_N`: an acquisition width decides what is recorded, never
   what is traded.

   *Inputs, flagged rather than buried:* `candles_per_call: 1000` is **verified as of
   2026-09-03** — the probe asked for 1,125 one-minute bars and got exactly 1,000, oldest
   truncated silently — and `config/breeze.yaml` now records the measurement with its date. The
   number is a `Final` in `campaign.py` rather than loaded, and a test pins the two together so
   they cannot drift. Still open: the `1second` interval's availability and per-symbol history
   depth are on the M3 probe's outstanding list; and Breeze **omits untraded bars**, so the
   1-second counts are an upper bound that illiquid names will come in well under.
2. **M7's pure layer is COMPLETE and composed** — `[C-UNIV-01]` to `[C-UNIV-06]`: the liquidity
   score, the stable-core buffer, the daily eligibility gates, the refresh cadence, the
   survivorship audit (which blocks promotion outright, and blocks on *unknown* coverage too),
   the liquidity lookback, and the per-session snapshot that joins them — eligibility BEFORE
   scoring, since the score is a cross-sectional z and a barred name would otherwise move every
   other name's rank. **Nothing calls any of it**; every piece waits on
   a panel. What remains of M7 is not pure: the **feeds that produce the eligibility flags** — suspension, T2T status, symbol-change
   resolution, corporate-action certainty. None of those exists, and §4.2's SURVIVORSHIP AUDIT
   is explicit that until listings, delistings, token changes, corporate actions and daily
   eligibility have archival coverage, every result is labelled survivorship-biased and **no
   candidate may be promoted**. Then universe snapshots, then the 1m backfill, then
   walk-forward.
   *Open, and smaller than a decision:* the blueprint gives starter values for every policy
   dimension except the stable-core `k`, whose column holds the rule rather than numbers.
3. **Not decided, per the owner: whether the gates FILTER rather than score.** Waits until the
   gates have real data.
4. **Forward capture is built end to end and nothing starts it.** `[C-M4-04]` + `[C-M4-05]`:
   the writer, the supervisor that records a hole on every disconnect and none on a clean stop,
   and now the **vendor adapter** — the two halves tested together across a simulated drop,
   producing a `GAP` record on disk between the ticks either side of it. Reading the SDK found
   the failure worth guarding: `subscribe_feeds` swallows every exception and returns it as a
   *string*, and returns `None` when the socket was never connected, so a subscription that
   failed completely looks exactly like one that worked. That is now refused, per symbol.

   **What is missing is a service that starts it at 09:15.** "Forward capture from day one" is
   the milestone's own phrase, and every session that passes is spread and depth that cannot be
   recovered later, which makes this the one open item where delay costs something permanent.
   Running it is a live market-data subscription and therefore the owner's to authorise — the
   standing authorisation covered one historical call per symbol, not a live feed. Two things
   are unverified until then: what a real tick payload holds, and whether a real drop shows up
   as `sio.connected` going false. The same nothing-runs-it problem applies to QC below.

5. **QC now gates promotion; nothing yet RUNS QC.** `[C-QC-01]` is `enforced`:
   `promote_bronze` consults `QcVerdicts` and refuses a record QC quarantined, counts every
   record promoted with no verdict behind it, and offers `require_qc_coverage()` as the hard
   refusal for anything on the path to real capital. Bars can no longer reach the panel with QC
   silently never having run — but they can still reach it with QC *loudly* never having run,
   because `make ci` does not invoke QC and no compose service or Jenkins stage does either.
   The only entry point is still a human typing `make qc` — which now at least WRITES its
   verdicts to `<root>/state/qc-verdicts.json`, so a promotion in another process can read
   them; before, the verdict never left the process that reached it and the gate could not be
   reached at all. Running QC where the data lives is arb-vm work, and that rail auto-deploys
   every main SHA, so it is the owner's to authorise exactly as `reader.Dockerfile` is. Making promotion depend on
   it is a pipeline change. **RESOLVED, and this entry had it backwards.** It read
   the prose/code difference as the spec overpromising "calendar gaps", to be fixed by
   correcting the prose. The prose was right. The ratio floor takes ONE SESSION'S BARS, and
   `run_qc` walks the records that exist — so a trading day never fetched has no record, gets
   no check, and the hole is invisible to the whole pass. Both checks were needed and only one
   existed; `check_calendar_gaps` is now the other `[C-QC-01]`. What still blocks `enforced` is
   only the first half: nothing makes QC a precondition of anything.

`certify-smoke` — **measured 2026-09-04 by `make certify-smoke`, not asserted.** The previous
entry here said "0 certified, 18 unsupplied; seven of eight hard gates compute; concentration is
measured but ungated", and three of those four numbers had drifted. Running it:

- **0 certified** — unchanged, and expected.
- **21 dossier fields the factory cannot supply**, not 18.
- **Five of eight hard gates compute**, not seven: `economics.dsr` (0.0), `stability.pbo`
  (0.81), `stability.spa_p` (1.0), `stress.cost_1_5x` (−2.16), `stress.delay_1_bar` (−1.45).
  All five compute and all five fail, which on fixtures of seeded noise is the right answer.
- **Three are ungated because they are not `Measurement`s at all** — `parameter_plateau`,
  `concentration`, `outer_folds`. "Concentration is *measured* but ungated" was the stale part:
  it is not measured. ADR-0014 declares no bar for it, so it has nowhere to come from, and
  `outer_folds` waits on walk-forward, which waits on the panel from (1).

These are tool outputs, so they are a snapshot and go stale the moment the factory supplies one
more field. Re-run the command rather than trusting the numbers.

*Verified 2026-09-02, so it is not re-litigated:* `capacity.minimum_economic_ticket` needs a
**price**, not a cost model. Every component of `config/costs/nse_equity_intraday.yaml` is
proportional — the `+ 3.00` in its derivation is stamp duty at ₹1 lakh, and the only
non-proportional term is the brokerage *cap*, a ceiling not a floor. So cost is a constant
fraction at every size and no minimum economic ticket arises from it; the constraint is integer
shares, which needs a price, which needs the panel. The size-independent form of the question is
already `economics.breakeven_edge`.

## `../past` is gone (2026-09-04)

The harvest finished and the folder was deleted on the owner's instruction. All 15 `PORT` rows
carry an AUDITED / HARVESTED / KNOWLEDGE CAPTURED note, so `docs/ledger/salvage.yaml` is the
artifact and the folder was working material.

Verified before deleting, not assumed: **0 commits not on any remote** in all three repos, 0
dirty files, 0 stashes, 0 untracked files, and every one of the 21 donor SHAs reachable from a
remote branch. `make ci` is unaffected (`salvage-verify` was never in the ladder) and
`tests/unit/test_salvage.py` builds its own repo under `tmp_path`. `make salvage-verify` now
explains that the folder was removed on purpose and prints the `git clone` lines that restore it.

## The pre-push gate had a window, and one commit went through it (2026-09-05)

`dd3a55b` reached `main` and was deployed **without any Jenkins build having seen it**: a gated
push began with `main` at e13dc08, Jenkins built e13dc08, dd3a55b was committed mid-gate, and
GitHub records the single push landing dd3a55b. The mechanism is UNEXPLAINED — two controlled
experiments show git sending the pre-hook ref — and is recorded as such rather than guessed at.

Closed regardless of mechanism: the hook now pins `HEAD` when the gate begins and refuses the
push if `HEAD` differs when it returns. Tested against the real hook; both natural mutations
verified by hand (`mutate.py`'s canary is inert in bash).

**Consequence for anyone committing:** do not commit on `main` while a push is gating. The gate
takes ~15 minutes; a commit made in that window now makes the push REFUSE (correctly) rather than
slip through. Wait for the push to land, then commit.

A post-hoc `make ci` on dd3a55b is the mitigation for the commit that already landed; its result
is recorded in the log when it finishes.

## Blockers / awaiting
- **`BLK-0005` RESOLVED 2026-09-05 — owner chose A+.** A three-component pre-rank picks the
  500; the superset property becomes *checked each refresh* rather than guaranteed by
  construction, and an exploration budget captures names just outside the 500 so a missed name
  is corrected rather than permanently absent from the archive.
- **Owner approved three items on 2026-09-05:** re-fetch the seed's missing 2023-09-04 (clear
  the terminal manifest keys first), wire `AdaptivePacer` into the fetchers, and retry live
  capture at Monday's open for `BLK-0004`.
- **`BLK-0003` RESOLVED 2026-09-05.** Both decisions made; the daily panel and `gap_rate` are
  built and swept. Three of the four score components now exist.
- **Awaiting the owner, not blocking a tick:** (a) whether to clear the manifest keys and
  re-fetch the seed's missing first day before promoting — one call per symbol, see *Active
  item*; (b) ICICI's written reply for `[G-AUTH-0]`'s `evidence_paths`; (c) whether to wire
  `AdaptivePacer` into the fetchers, which changes live campaign behaviour.
- **`BLK-0004` — Breeze refuses our streaming namespace.** Not on the critical path for the
  shortlist, so it does not stop a tick, but it is a human-only item that had no card and lived
  only in a dead container's log. The transport is fine (Engine.IO handshake returns 200 with a
  session id); the authenticated Socket.IO namespace connect is refused, while REST with the same
  token succeeds. It needs a question put to ICICI, not a code change.
- Everything below was true before that block opened and still is.
- The security-master download was approved and completed; 5,851 instruments
  are live in the PIT store on arb-vm and the QC verdict seam resolves end to end. The orphaned `checkout` compose project was cleared with the
  owner's go-ahead. All three original owner-actions remain cleared.
- **`[G-AUTH-0]` is now `WRITTEN`** (2026-09-05, owner's explicit instruction), so
  `pips authority check` no longer prints the verbal-evidence caveat. Two documentary items
  remain and neither blocks: `evidence_paths` should gain ICICI's reply itself when filed, and
  the four blank fields in `gate0-owner-attestation.md` are still blank.
- **Deliberate placeholders, all erring safe and all marked unverified:** Flattrade's MIS
  square-off (15:00), the Breeze per-minute rate (75/min — **not** inferred from the owner's
  100k/day and 32 parallel fetches), and the NSE holiday list (empty). Each is an M6 item.
- **Never measured, deliberately:** Breeze's true per-minute limit, WS subscription capacity,
  BSE support. Each would cost live calls to learn and none blocks current work.
