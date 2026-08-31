# IMPLEMENTATION.md — pips · Claude Code playbook (v2.0)

> **Project:** `pips` — NSE cash-equity intraday meta-algorithm.
> **Audience:** Claude Code (and any AI coding agent) working in this repository.
> **This version:** v2.0 merges the strengths of all four reference documents (two Claude, two
> ChatGPT — see §11) into one build plan, renames the project to **pips**, and introduces the
> **sharded doc layer + ledger** so documentation has an exact, machine-checkable
> representation in code without bloating any single context window.
>
> Where documents disagree, **this file wins**; each resolved disagreement is recorded as an
> ADR (see §10.5 for the pre-seeded ones). Human owner: Prateek. AI builds and verifies;
> the human approves phase gates and anything on the path to live orders.

---

## 0. Mission, in one paragraph

Build a research factory whose unit of output is the **StrategyBundle** — a complete, signed,
deployable specification (universe policy + signal graph + calibration + portfolio + execution
+ risk + cost context + validation evidence, under one content hash) — not a bot and not a
leaderboard of backtests. A Python research plant discovers and certifies at most 3–5
Pareto-diverse bundles through a staged funnel with multiplicity-honest statistics; a Rust
execution plant loads bundles read-only and trades them under an independent risk layer.
Capital < ₹10L across declared tiers (₹2L / ₹5L / ₹10L), **unlevered at launch**; data from
ICICI Breeze (read-only plane); orders through Flattrade or Zerodha (separate order plane);
horizons scalping→intraday with sub-minute claims quarantined until tick/depth data exists;
**no generative AI in the trading loop**. The machine is allowed — expected — to conclude that
some ideas produce *nothing* deployable; a defensible "no" is a valid output.

---

## 1. Workspace layout and the `past/` salvage protocol

```
quant/
├── past/               # PRE-EXISTING repos. READ-ONLY harvest source: working Breeze/broker
│                       #   connectors, token flows, WS capture, masters, downloaders, glue.
└── pips/               # THIS repo. ALL documentation lives INSIDE it, under pips/docs/
                        #   (there is no external managed docs folder).
```

`PAST_DIR` defaults to `../past`. Start Claude Code with `claude --add-dir ../past`.

**Why `past/` exists:** to avoid hand-writing adapter glue and infrastructure again. Those
repos contain working connector code — Breeze auth/session flows, historical fetchers,
websocket capture, broker order clients, instrument masters, downloaders, alerting. The
default for any such component is **harvest (vendor or port), not rewrite**; §1.2's audit
produces the harvest map that every later milestone consults.

**The donors may live in commit history, not at HEAD.** These repos have evolved; working
connector code may have been refactored away, moved, or deleted in later commits, and may sit
on non-default branches or tags. The harvest audit therefore searches **each repo's full git
history — all branches, tags, and deleted files — not just the current working tree**, and
every harvested component records the exact source commit SHA it was taken from (which is
frequently *not* HEAD).

### 1.1 Hard rules for `past/`

1. **Read-only.** Never edit, commit to, or run anything inside `past/` against live keys.
2. **Never import from `../past` at runtime.** Reuse = **vendor** (copy into
   `vendor/past/<repo>/…` with a `PROVENANCE.md`: source repo, paths, **exact source commit
   SHA — not necessarily HEAD** and branch/tag it was found on, date, changes) or **port**
   (rewrite to §3 contracts). Extracting from history is read-only and safe: use
   `git show <sha>:<path>` / `git worktree add` on a detached SHA — never `checkout` that
   moves the repo's state. Vendored code must pass this repo's lint/type/test bar or be
   demoted to PORT.
3. **The pips architecture wins.** Old code adapts to the contracts; contract changes require
   an ADR.
4. **Harvest-first.** Before implementing any connector, adapter, session/token flow,
   instrument master, downloader, calendar, or similar infrastructure glue, consult
   `ledger/salvage.yaml`. If a donor component exists, vendor or port it. Writing such code
   from scratch requires a `SAL-*` row with `decision: NONE_FOUND` stating what was searched
   and why nothing qualified — "I didn't look" is not a valid provenance.

### 1.2 Milestone M1 — harvest audit (the harvest map)

Per repo, run a **history sweep before judging the working tree** (read-only git commands):
`git branch -a && git tag` to enumerate refs; `git log --all --oneline` for the shape of the
history; `git log --all --diff-filter=D --summary` to find **deleted files** (deleted ≠ gone —
often the best donor); pathspec/keyword hunts across all refs, e.g.
`git log --all --oneline -- '*breeze*' '*kite*' '*flattrade*' '*websocket*' '*token*'
'*instrument*' '*ohlc*' '*order*'` and bounded `git grep <term> $(git rev-list --all | head)`.
For each candidate component, identify the **best commit** (the last one where it demonstrably
worked — commit messages and adjacent fix commits are evidence) and record it.

Produce `docs/ledger/salvage.yaml` — one entry per candidate component with decision
`VENDOR | PORT | WRAP | SKIP`, fields including `repo`, `path`, **`commit` (source SHA)**,
`ref` (branch/tag), `found_at_head: true|false` — plus a human-readable summary in
`docs/SALVAGE.md`, plus a **needs-coverage table**: for every infrastructure need in later
milestones (M4 Breeze ingest/token flow/WS capture, M6 masters & calendars, M21–M23 broker
adapters, ops alerting), name the donor component — or record `NONE_FOUND` so from-scratch
work is pre-authorized. A `NONE_FOUND` is only valid if the history sweep ran: it must state
which refs and keywords were searched.
Donors count even across languages: a Python Kite/Flattrade client that can't be vendored
into Rust still supplies the auth quirks, endpoint shapes, error taxonomy and edge-case
knowledge for the port, and is cited in the crate's PROVENANCE.md.
Scan priority: (1) Breeze session-token flow + historical fetchers + WS capture; (2) broker
order clients (Flattrade/Kite), order-state polling; (3) instrument masters, holiday
calendars, corporate-action handling; (4) bar/tick storage layers and downloaders; (5)
backtest loops / indicators / risk code (usually PORT: keep the logic and edge-case knowledge,
rewrite to contracts); (6) alerting, dashboards, deploy scripts. Timebox 10 min/repo for
build/test probes; fan out subagents if there are many repos.

---

## 2. Operating rules (the constitution)

1. **Determinism.** Every entry point takes `(config, data_snapshot_id, seed)`. Same inputs ⇒
   bit-identical outputs. `make determinism` runs a small pipeline twice and diffs hashes.
2. **Causality is measurability.** All research code reads the `AsOfPanelView`, which
   physically refuses rows later than the decision timestamp and records every accessed
   field. A signal computed on completed bar *t* may not fill within bar *t*; earliest fill is
   the next executable event after decision + modeled latency. Bars are labeled by **close
   time**. Full-day VWAP/volume used intraday is banned by the feature API. Smoothed state
   probabilities `P(S_t | F_T), T>t` are banned from anything that trades or tunes.
3. **Evidence is bitemporal and immutable.** Raw partitions are append-only and
   content-addressed; corrections create a new knowledge-time version (`known_from/known_to`),
   never an overwrite. Every derived dataset carries parent hashes. **A result without a
   resolvable snapshot root is not evidence.**
4. **Every viewed trial counts.** Completed, failed, abandoned, hand-tuned, alternative-seed
   and notebook-glanced variants all land in the registry and enter the multiplicity ledger
   (M and M_erank, §3.6). Deletion does not un-count a trial.
5. **No mathematical decoration.** A more elaborate operator is admissible only if it beats
   its simpler parent on nested out-of-sample net utility *and* the improvement survives
   perturbation. Every alpha ships with named null models and a **written rejection
   condition** (falsifier) before it is searched.
6. **Costs are effective-dated data, not constants.** Fee schedules live in
   `config/costs/*.yaml` with `source:` + `verified_on:` + validity dates; golden tests pin
   today's values (§3.7); production cost freeze requires reconciliation against a **real
   contract note** (NSE revised the transaction/IPFT split effective 1 Mar 2026 — schedules
   drift).
7. **Two planes, two credentials, two processes.** The Breeze adapter is the read-only market
   -data plane and holds only Breeze credentials; the broker order adapter is the only order
   plane and holds only broker credentials. Neither knows the other's secrets; the engine core
   knows neither vendor's wire formats. Broker quotes never silently substitute for the
   certified signal feed.
8. **DRY_RUN by default.** The order gateway compiles behind a `live` feature flag and
   additionally requires `PIPS_LIVE=1` plus a config containing
   `i_understand_live_trading: true`. Phases P0–P5 place zero orders. Launch is **unlevered**;
   leverage is a later, separately-validated overlay (ADR-0003).
9. **Compliance by construction.** SEBI retail-algo framework (mandatory since 1 Apr 2026):
   all client-API orders are algo orders and get broker Algo-ID tagging; ≤10 orders/sec per
   exchange/segment stays registration-free; engine governor caps at 5/s shared token bucket
   (place+modify+cancel+square-off all count); static-IP binding; OAuth/2FA daily sessions;
   audit trail retained ≥5 years.
10. **Tests are the deliverable.** No milestone closes red. Never weaken a test, golden,
    gate constant, or ledger entry to go green — that is a human conversation plus an ADR.
11. **Small increments.** One milestone per branch `m/<id>-<slug>`, conventional commits, PR
    body pastes verify-command output, < ~800 changed lines per PR.
12. **Session hygiene.** Follow the sharded-doc protocol (§10) exactly: read little, update
    shards, never grow a hot file.
13. **Harvest before writing (§1.1 rule 4).** Adapter glue, connectors and infrastructure
    default to vendored/ported `past/` code with provenance; from-scratch requires a recorded
    `NONE_FOUND`.
14. **All market data and runtime state live on arb-vm, never on the laptop.** Local machines
    hold code and fixtures only; every service runs as a Docker Compose container on arb-vm
    (§2.2). Anything that needs real data (backfill, sweeps, capture, engines) executes on the
    VM. Images are immutable and SHA-tagged; data, journals, the registry and secrets live in
    VM volumes/env files and are **never baked into an image** `[C-DEPLOY-01]`.
16. **Test-first (TDD), always.** Every behavioural change starts as a test that fails
    for the right reason. Write the test, watch it go red, record that red output in the
    session log and the PR body, then write the smallest code that turns it green, then
    refactor under green. **No production code may be committed ahead of a test that
    covers it** — `make tdd-check` `[G-TDD-01]` walks the branch and refuses it. Pure
    renames and mechanical refactors whose behaviour is already pinned may carry a
    `TDD-Exempt: <reason>` commit trailer; the reason is printed by CI and reviewed, and
    an empty reason is not an exemption. "The test is obvious" is not a reason, and a
    milestone's Verify command passing is never a substitute for having watched the test
    fail. Full protocol in §7.1.

15. **Blocks are cleared by fresh, dynamically generated specialist agents, not by grinding.**
    When the current item is blocked (definition and protocol in §10.4), the working session
    writes a block card and spawns a *new* agent whose role is synthesized for that specific
    blocker's domain — a Jenkins-pipeline debugger, a docker-compose networking specialist, a
    Breeze-auth specialist, a systemd/deploy-rail engineer — never a generic helper. The
    specialist has cross-boundary reach (container, Jenkins, arb-vm over SSH, deploy rail)
    but is bound by this constitution like every session.

### 2.1 GATE-0 — data-use authority (pre-live, from the ChatGPT blueprint; adopted)

The architecture uses Breeze **only** as a read-only data API and a separate broker API for
orders. ICICI's public FAQ language restricts Breeze to personal trading and prohibits
third-party trading integration; it supports self-built code but publishes no explicit
data-only carve-out for signals executed at another broker. Therefore: **before any live
order**, obtain written ICICI clarification — or switch the certified signal feed to the
execution broker's entitled feed (Kite Connect live+historical tier, currently ₹500/month, or
Flattrade's free API subject to its terms). This is a release gate and an adapter swap, not an
architecture change. Breeze data is never redistributed. Tracked as ledger gate `G-AUTH-0`.

### 2.2 Runtime topology and the deploy rail (arb-vm) `[C-DEPLOY-01]` `[G-DEPLOY-01]`

**Where things run.** Everything runs as Docker Compose services on **arb-vm** (reachable via
SSH): `breeze-reader`, `live-engine`/`shadow-engine`, `research-runner`, `backfill`,
`telemetry`, plus scheduled jobs. arb-vm's fixed egress IP doubles as the SEBI **static-IP**
binding for broker API keys — the compliance requirement and the deployment choice are the
same fact. Data zones (`bronze/silver/gold/quarantine`), snapshots, the registry DB, journals
and reports live on VM volumes (`/srv/pips/...`); dev containers mount fixtures instead.
Dev image == prod image: `make ci` runs *inside* the same container locally, in Jenkins, and
on the VM — "works on my machine" is structurally impossible.

**Development flow (the only path to production):**

```
edit locally  →  Jenkins (LOCAL, not GitHub Actions) runs the containerized `make ci`
              →  push branch; merge to main on GitHub only if Jenkins is green
              →  arb-vm deploy rail detects new main SHA (systemd-timer poller, ~1–2 min;
                 webhook optional later), then:
                   git fetch && hard-reset a dedicated build checkout to origin/main
                   docker compose build   (images tagged with the git SHA)
                   docker compose up -d   (per-service restart policy below)
                   health checks → journal-replay warm restart where applicable
                   on failure: automatic rollback to the previous SHA tag + alert
```

**Restart policy is service-aware.** Research/data services (`research-runner`, `backfill`,
`telemetry`) roll immediately on every main update. **Trading-path services
(`breeze-reader`, `shadow-engine`, `live-engine`) never hot-swap during market hours**: the
deploy rail holds their restart until after the 15:35 close (or before 08:45), unless a human
forces it — and a forced intraday restart follows the crash-recovery path (journal replay +
broker reconciliation, §3.13) like any other restart. The live engine additionally only ever
runs signed bundles behind the live-flag chain (§2 rule 8), so a code deploy can never
silently change live behavior — only a new bundle can.

Deploy tooling lives in-repo: `docker/` (multi-stage Dockerfiles: `research`, `engine`,
`reader`), root `docker-compose.yml` + `docker-compose.dev.yml`, root `Jenkinsfile`
(stages = the `make ci` ladder + image build), `ops/deploy/` (`sync.sh` poller,
`rollback.sh <sha>`, systemd units, VM bootstrap runbook). Secrets stay in VM-side env files
referenced by compose, never in git or images.

---

## 3. Pinned contracts — build exactly these

Every contract below carries a ledger ID (`C-…`). `make ledger-check` (§9) verifies each ID
maps to real code and tests once its status passes `building`.

### 3.1 Config → identity `[C-ID-01]`

YAML configs validated by pydantic models; canonicalized (sorted keys, normalized floats) →
SHA-256 = `config_hash` (short id = first 16 hex). Every log line, registry row, artifact and
bundle carries it. Trial identity hashes **all** of: code commit, data snapshot root,
instrument-master/CA/calendar hashes, pipeline DAG, universe policy, parameters, split
definition, cost model, fill model, **capital tier**, seed, runtime versions. Re-running an
existing hash returns the cached result.

### 3.2 AlphaSpec — pre-registration object `[C-SPEC-01]`

No alpha enters as an indicator recipe. It enters as a tuple
`A = (H, I_t, T_h, φ_θ, C, E, N, F)`:

```yaml
AlphaSpec:
  id: A04            # catalogue id (§5)
  version: 1.0.0
  hypothesis: >       # named mechanism: who is constrained/informed/slow/forced?
  information_set:    # every field + earliest usable timestamp
  target:             # exact horizon, price convention, side
  feature_dag:        # typed nodes, warmups, missingness policy
  parameter_domain:   # bounded; coarse grid + refinement ranges
  fit_protocol:       # what is fitted, on which fold data, with what regularizer
  null_models:        # zero, naive sign/rank, simpler parent
  falsifiers:         # WRITTEN rejection conditions, predeclared
  data_tier: T1|T2|T3
  cost_context:       # broker × capital tiers it must clear
  execution_policy:   # protected-limit params
  heuristic: false    # true ⇒ quarantined per constitution rule 5; ensemble cap applies
  references: []
```

Any material change bumps the version and counts as a new trial. The plugin `compute(view,
params) → ForecastFrame` is pure, deterministic, warm-up-declared.

### 3.3 Forecast contract `[C-FCST-01]`

Every alpha emits comparable economics, independent of order logic:

```
Forecast { strategy_id, family_id, instrument_id, decision_ts,
           expected_return_bps, confidence, horizon, half_life,
           valid_until, capacity_notional, validity_flags }
```

The portfolio layer trades only where `|μ̂| > stressed marginal cost + κ·SE(μ̂)`.

### 3.4 Data plane `[C-DATA-01]`

Zones `bronze/` (raw, append-only, exact payloads + receive timestamps) → `silver/`
(validated, CA-adjusted views, explicit gap/stale states — a zero-volume bar ≠ a missing bar)
→ `gold/` (research panels, feature store) → `quarantine/`. Bitemporal columns
(`valid_from/valid_to/known_from/known_to`) on every PIT table. PIT tables (daily snapshots):
instrument master, corporate actions, exchange calendar **including CAS session windows**,
ASM/GSM/T2T lists, **broker_capability** (per broker × product × instrument × side:
eligibility, shortability, leverage, cutoff times, order types, rate limits — square-off times
are *data, not constants*), index membership, orders/fills truth. Snapshot manifests are
Merkle-rooted `[C-DATA-02]`; experiments pin `snapshot_root`.

### 3.5 Bar builder `[C-BAR-01]`

Label = close time; usable at/after label. Boundary tie: trade at boundary `t` belongs to the
bar **ending** at `t`. Sessions per exchange calendar (pre-open excluded from continuous
bars; CAS separate). Late data beyond a bounded reorder window becomes a journaled
`LateMarketEvent` and cannot mutate a finalized bar (watermark rule). Shared fixture files
(`fixtures/bars/*.json`) are consumed by **both** Python and Rust test suites. Empirically
verify Breeze's own labeling convention in M4 and normalize on ingest (record as ADR).

### 3.6 Experiment registry & multiplicity ledger `[C-REG-01]`

SQLite, append-only (application code has no UPDATE/DELETE):

```sql
CREATE TABLE runs (
  run_id INTEGER PRIMARY KEY, config_hash TEXT NOT NULL, stage TEXT NOT NULL,
  stage_rank INTEGER NOT NULL,          -- S1=1, S2V=2, S2E=3, S3=4, S4=5, S5=6, S6=7
  family TEXT, universe_id TEXT, session_mask TEXT, capital_tier TEXT, broker TEXT,
  data_snapshot TEXT NOT NULL, cost_model TEXT NOT NULL, fill_tier TEXT NOT NULL,
  seed INTEGER NOT NULL, git_sha TEXT NOT NULL, metrics TEXT NOT NULL, n_trades INTEGER,
  daily_returns_ref TEXT,               -- parquet path: preserved for M_erank & SPA
  status TEXT NOT NULL,                 -- completed|failed|abandoned|viewed
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE holdout_unlocks (cycle_id TEXT, config_hash TEXT,
  unlocked_at TEXT DEFAULT (datetime('now')));   -- one unlock per cycle; twice = void
```

Report **both** the literal trial count `M` and the effective count
`M_erank = (Σλ_j)² / Σλ_j²` from the eigenvalues of the cross-trial daily-return correlation
matrix (a sensitivity heuristic, not an exact correction — DSR is evaluated at `N = M` and
`N = M_erank` as bracketing cases). Candidate daily returns are preserved for exactly this.

### 3.7 Cost model — golden numbers `[C-COST-01…04]`

`cost_rt_bps(broker, notional, aggression, symbol, ts, capital_tier)` = statutory (exact,
effective-dated) + brokerage + spread·aggression + impact `κ(q/ADV_interval)^ψ` + latency +
adverse-selection terms. **Golden tests (₹1,00,000/side, fees only, schedules as verified
Aug 2026):** Flattrade buy ₹6.74 / sell ₹28.74 / RT **₹35.48 = 3.548 bps**; Zerodha buy
₹30.34 / sell ₹52.34 / RT **₹82.68 = 8.268 bps**; Zerodha RT bps at 50k/2L/5L =
10.63 / 5.91 / 4.49. Broker operational facts carried as data: Flattrade API **limit-only**
(protected marketable-limit is the portable default order type everywhere); Flattrade rate
10/s & 40/min; Kite 10/s, 400/min, 5,000 orders/day, 25 modifications/order; Zerodha MIS
square-off ≈15:12 for CAS-eligible names / ≈15:25 otherwise; admin square-off ≈₹50+GST is an
incident cost, never a baseline. If a verified rate change breaks goldens: update YAML +
goldens + `verified_on` in one commit, and log a `D-COST-*` decision.

### 3.8 Fill-fidelity tiers `[C-FILL-01]`

| Tier | Rule | Permits |
|---|---|---|
| F0 screen | next-bar return − conservative rough cost | feature triage only (S1) |
| F1 event bars | next-event **protected marketable-limit** with partial/reject/timeout/reprice-cap states, integer shares, tick rounding | T1 candidate comparison (S2+) |
| F2 quote/trade | price-through + participation ≤10% interval volume + latency + adverse selection, calibrated from captured quotes | T2 certification |
| F3 auction | auction state machine + observed clearing fills | T3 only |

Every result is stamped with its tier; cross-tier comparisons are refused by report code. An
OHLC touch is never a fill. Stop+target inside one bar resolves by adverse sequence (or tick
replay at F2).

### 3.9 StrategyBundle `[C-BNDL-01]`

```
StrategyBundle { schema_version, bundle_id, strategy_id, parent_experiment_ids,
  code_hash, build_environment_hash, data_snapshot_root, universe_hash, calendar_hash,
  instrument_master_hash, corporate_action_hash, cost_hash, risk_policy_hash,
  numeric_semantics_version, bar_semantics_version, alpha_ir_version, portfolio_ir_version,
  valid_from, valid_until, broker_context, capital_range,
  alpha_ir, portfolio_ir, fit_state, calibration, session_regime_policy,
  execution_policy, exit_policy, validation_dossier_hash, trial_registry_root,
  golden_fixture_hashes[], content_checksums[], signature }
```

Only **registered IR operations** cross the bundle boundary — arbitrary callables cannot be
signed. On boot the Rust loader executes the bundle's golden fixtures and refuses unknown
nodes, schema/semantic-version mismatch, missing cost/risk versions, bad checksum, or unequal
quantized output, before entering READY.

### 3.10 Order plane `[C-OMS-01…03]`

```
OrderIntent { idempotency_key, bundle_id, strategy_id, instrument_id, side, quantity,
  limit_paise, time_in_force, expiry_time, expected_edge_bps, stressed_cost_bps,
  reason_code, decision_ts }
ExecutionEvent { broker_order_id, intent_key, state, last_fill_qty, last_fill_price_paise,
  cumulative_filled_qty, remaining_qty, fees_paise, exchange_ts?, receive_ts,
  reject_code, raw_event_hash }
```

Order state machine: `CREATED → RISK_REJECTED | APPROVED → SUBMISSION_PENDING →
ACKNOWLEDGED | SUBMISSION_UNKNOWN → RECONCILING; ACKNOWLEDGED → PARTIALLY_FILLED | FILLED |
CANCEL_PENDING | REJECTED | EXPIRED`. Cumulative fill is monotone; terminal states absorbing
except explicit broker correction. Network submission is at-least-once; logical intent is
exactly-once via idempotency keys. **Unknown state is never retried blindly** — query orders
and positions, reconcile broker truth, then decide. Cross-broker failover is blocked until the
original broker's state is positively reconciled. Pre-trade risk evaluates against
broker-reconciled positions **plus every live order as if filled**; pending cancels consume
exposure until acknowledged.

### 3.11 Numeric boundary semantics `[C-NUM-01]`

Certified boundary types: `PricePaise:i64, Quantity:i64, NotionalPaise:i128, RateQ12:i64,
ScoreQ8:i64, TimestampNs:i64`. `f64` is confined to the math kernel; NaN/∞ cannot cross a
schema boundary (invalid division → explicit null; overflow → decision rejected). Rounding is
half-to-even unless a venue tick rule says otherwise; equal scores tie-break by
`instrument_id`. Float oracles may differ ≤2 ULP on designated primitive tests; tolerance is
**zero** for bar membership, null masks, quantized scores, ranks, target quantities, risk
decisions, OrderIntents, fills, fees, cash, and state hashes.

### 3.12 Kernel & parity strategy `[C-PAR-01]` (ADR-0002, decided)

Anything that ships inside a bundle — rolling/stateful primitives, bar building, robust z,
EWMA, residualizers, calibration application, band logic — is implemented **once, in the Rust
`math-kernel` crate**, exposed to Python research through a narrow PyO3 binding. A small,
deliberately slow pure-Python oracle exists only for property tests. Research-only statistics
(DSR/PBO/SPA, bootstraps, reports) stay Python. Release parity: replay recorded days through
the Python reference path and the Rust engine; canonical OrderIntent JSONL streams must be
byte-equal (`sha256(py) == sha256(rs)`), staged from schema → primitive → feature → score →
target → intent → accounting → crash recovery.

### 3.13 Live journal `[C-JRNL-01]`

Every live event is wrapped in a canonical envelope with `journal_seq`, hash-chained
(`event_hash = SHA256(seq ‖ header ‖ payload ‖ previous_hash)`). Replay order is
`journal_seq`, never re-sorted; reducers deterministic; duplicate IDs idempotent; checkpoints
bind state hash to final event hash before new risk is admitted. Restart = replay journal,
then reconcile broker truth, then (and only then) arm.

### 3.14 Risk state machine `[C-RISK-01]`

`BOOTSTRAP → VERIFYING → RECONCILING → WARMUP → READY → ACTIVE → DEGRADED`, with any
risk-bearing state `→ HALTED → FLATTENING → FLAT → LOCKED`. DEGRADED permits only
exposure-reducing actions. A hard halt cannot auto-return to ACTIVE: reactivation requires
broker reconciliation, healthy data for a stabilization interval, and authenticated human
approval. Failure matrix (feed stale → stop decisions, invalidate features; price divergence →
pause symbol, never pick the favorable price; order unknown → reconcile-first; restart →
journal replay + reconcile; mismatch → cancel new risk; clock drift → halt timestamp-sensitive
decisions; loss/kill → cancel + flatten). **Short-at-upper-circuit is modeled as a distinct
tail event** (possible delivery/auction obligation), not a normal stop fill. An independent
flatten scheduler closes before the earliest broker/product cutoff (from the capability
snapshot); broker auto-square-off is a failure path.

### 3.15 Session & regime structure `[C-SESS-01]`

Session states (finer than v1): `OPEN_SHOCK` 09:15–09:30 · `OPEN_DIGEST` 09:30–10:30 · `MID`
10:30–14:30 · `LATE_CTS` 14:30→broker cutoff · `CAS` (15:15–15:35, F&O-eligible names —
**disabled as an alpha venue until auction data + broker support are verified**) ·
`FLATTEN_ONLY`. Session eligibility is broker × product × instrument × side from the daily
capability snapshot — never a hard-coded time. Regimes: 2–4 interpretable causal states
(index-vol percentile, dispersion, breadth, trend/chop), filtered probabilities only,
training-fold thresholds, minimum independent days per regime cell, complexity penalty per
split, always compared against the always-on parent.

---

## 4. Toolchain and scaffold (Milestone M0)

Python 3.12 via `uv`; `ruff`, `mypy --strict` on `core/` + `schemas/`; `pytest` + `hypothesis`.
Polars + DuckDB; cvxpy only inside `portfolio/optimizer.py`; Optuna inner-fold only. Rust
stable cargo workspace; `clippy -D warnings`; `proptest`; PyO3 for the kernel binding. Task
entry points are a plain **`Makefile`** (ADR-0007 — no `just`, no archived/abandoned
tooling): targets `setup test lint typecheck ci determinism tdd-check ledger-check s1-smoke
backtest-smoke parity DAY=<day> qc`, each a thin wrapper over the real command.
**CI is native Jenkins, run locally** (root `Jenkinsfile`, declarative; no GitHub Actions):
stages = lint → typecheck → **tdd-check** → py tests → rust tests → fixture parity →
determinism → **ledger-check** → image build, all executed inside the project's own Docker image so the
Jenkins result certifies exactly what arb-vm will run (§2.2). Merging to main requires a
green Jenkins build; main is what the arb-vm deploy rail ships.

```
pips/
  CLAUDE.md  IMPLEMENTATION.md  LOOP.md  Makefile  pyproject.toml  Cargo.toml  .env.example
  Jenkinsfile  docker-compose.yml  docker-compose.dev.yml
  docker/      research.Dockerfile  engine.Dockerfile  reader.Dockerfile
  config/      costs/  gates.yaml  search_spaces/  calendars/  live.yaml.example
  schemas/     alpha_spec/ forecast/ strategy_bundle/ order_intent/ execution_event/ envelope/
  data/        bronze/ silver/ gold/ quarantine/ snapshots/ universes/
  python/pips/
    core/        time, asof, money, ids, config
    data/        breeze/ raw_store/ qc/ instruments/ corporate_actions/ pit/
    universe/    eligibility, liquidity, snapshots
    features/    dag, primitives(→kernel binding), residuals, diurnal
    alphas/      t1/ t2/ t3/ manifest
    models/      calibration, shrinkage, state_space
    sim/         vector, events, fills/{f0,f1,f2}, accounting
    costs/       statutory, brokerage, spread, impact, adverse_selection
    validation/  folds, purge, bootstrap, dsr, pbo, spa, nulls
    search/      registry, budgets, funnel, plateaus, pareto, turnover_opt
    portfolio/   covariance, optimizer, rounding, netting, bands
    certification/ dossiers, trial_root
    bundles/     build, sign, validate
  rust/crates/  domain math-kernel math-python market-protocol market-breeze bars
                feature-ir alpha-ir portfolio-ir strategy-bundle event-reducer sim-venue
                broker-protocol broker-flattrade broker-zerodha oms risk accounting
                journal replay telemetry engine
  apps/         breeze-reader live-engine shadow-engine replay-engine backfill research-runner
  fixtures/     bars/ quotes/ orders/ costs/ golden_days/ leakage_canaries/
  vendor/past/  provenance-tracked salvage
  tests/        unit/ property/ integration/ parity/ chaos/
  ops/          deploy/ (sync.sh, rollback.sh, systemd units, vm-bootstrap runbook)
                runbooks/ dashboards/ alerts/
  docs/         INDEX.md  state/  decisions/  ledger/  reference/  reports/  runbooks/
```

`apps/breeze-reader` and `apps/live-engine` are **separate OS processes** with separate
credentials, connected by length-prefixed canonical MarketEvents over a Unix-domain socket;
one live trading authority at a time (standby needs a fencing lease + reconciliation).
Smoke fixtures (2 symbols × 5 days synthetic 1m + one day of 1s, seeded generator) make the
entire funnel runnable with zero API access.

---

## 5. Alpha catalogue — tiered registry (adopted from the ChatGPT spec, superset of v1)

The canonical family registry is the **A-catalogue (A01–A36)** from
`docs/reference/` (AlphaForge spec, Part II), organized by data tier with certification
boundaries. v1's F-families map into it:

| v1 | A-catalogue | | v1 | A-catalogue |
|---|---|---|---|---|
| F1 CS momentum | A01 | | F6 seasonality | A12 |
| F2 CS mean reversion | A03 + A04 | | F7 lead–lag | A13 |
| F3 TS momentum | A02 | | F8 calendar events | A25 + A26 (numeric/calendar only) |
| F4 breakout | A07 + A08 | | F9 flow proxies | A09 + A10 + A11 (+A21 at T2) |
| F5 gap digestion | A05 + A06 (continue/fade **separate**, never chosen ex post) | | F10 pairs | A14 + A15 |

Tier rules: **T1** (A01–A18, A27, A29, A30) researchable on 1-minute bars after PIT/QC with
F1 fills — this is the launch surface. **T2** (A19–A23, A28, A31–A36) requires the forward
quote/trade/depth archive, clock audit and F2 fills — microstructure claims are quarantined
until then. **T3** (A24–A26) requires event/auction entitlements and F3 fills; CAS stays
disabled until verified. Every family enters as an AlphaSpec (§3.2) with falsifiers copied or
adapted from the reference cards; the deep math for the shared machinery (OU thresholds,
Faustmann h*, threshold economics, DSR/PBO derivations, no-trade bands, Kalman recursions)
lives in `docs/reference/Quantitative_Foundations_Alpha_Math.docx` and its §12 theory→module
map — implement against those formulas.

---

## 6. Milestone plan

Format: **Mx — name** → build → **Verify:** commands. One branch/PR each. Phases end at a
human gate. **Gate sign-off is a file**, so the autonomous loop (§10.6) can run unattended:
the human approves phase P\<k\> by creating `docs/state/gates/P<k>-approved.md` (a dated note;
its absence means the loop holds at the gate and only re-verifies). Ledger rows (`owner_milestone`) tie every contract/gate to its milestone.

### Phase P0 — foundation & authority

- **M0 scaffold**: §4 tree, CI, Makefile, schemas/ stubs, fixtures generator, docs shards
  (§10.1) seeded, ledger tooling `pips ledger check`, test-first tooling `pips tdd check`
  `[G-TDD-01]`; **populate `docs/reference/` with the
  four companion documents** (copy from `../deliverables/`; ask the human if absent) and cache
  their pandoc extractions under `docs/reference/_extracted/`. *Verify:* `make ci`;
  `docs/reference/` holds all four files.
- **M0.5 containerize the toolchain** (as early as possible, by design): multi-stage
  Dockerfiles (`docker/research.Dockerfile` first; engine/reader stubs), root
  `docker-compose.yml` + dev override mounting fixtures, `make ci` runnable **inside** the
  research container, root `Jenkinsfile` (declarative pipeline, native Jenkins) whose stages
  are the `make ci` ladder + image build,
  local Jenkins wired to the repo. From this point every milestone's Verify commands run in
  the container. *Verify:* `docker compose run research make ci` green; Jenkins pipeline
  green on a scratch commit.
- **M1 harvest audit**: §1.2 → `ledger/salvage.yaml` + `docs/SALVAGE.md` + needs-coverage
  table. *Verify:* every repo covered **including its full git history (all branches, tags,
  deleted files — donors are often not at HEAD)**; every salvage row carries a source commit
  SHA; every M4/M6/M21–M23 infrastructure need has a named donor or a `NONE_FOUND` row that
  documents the refs and keywords searched.
- **M2 core + canaries**: config hashing `[C-ID-01]`; calendars (incl. CAS windows); AsOf view
  with adversarial tests; **permanent leakage-canary alpha** (spectacular in an unsafe
  harness, must fail every production path, stays in the suite forever); determinism check.
  *Verify:* `make test determinism`.
- **M3 GATE-0 + feasibility probe**: file the ICICI data-use question (template in
  `ops/runbooks/authority.md`); probe Breeze as saved artifacts — real rate limits (docs
  conflict: 100/min vs 75/min → throttle to 75 until confirmed), true history depth per
  symbol (3y vs 10y claims), bar-timestamp convention, WS subscription capacity (~2,000
  scripts nominal), BSE support ambiguity; ingest broker capability snapshots v0 (manual CSV
  acceptable). Decision ADRs recorded. *Verify:* probe artifacts committed under
  `docs/reports/feasibility/`; `G-AUTH-0` status set.
- **M3.5 arb-vm deploy rail** `[C-DEPLOY-01]` `[G-DEPLOY-01]`: bootstrap arb-vm over SSH
  (docker, compose, volumes at `/srv/pips/...`, VM-side env files for secrets); build
  checkout + `ops/deploy/sync.sh` on a systemd timer: detect new `origin/main` SHA →
  SHA-tagged `docker compose build` → service-aware `up -d` (market-hours guard for
  trading-path services, §2.2) → health checks → auto-rollback to previous SHA on failure +
  alert; `rollback.sh <sha>` for manual reverts. From here on, **all real data work (M4+)
  runs on arb-vm**; the laptop touches fixtures only. *Verify:* push a trivial commit to
  main → VM runs the new SHA within one poll interval; a deliberately failing health check
  rolls back automatically; a main update during simulated market hours defers trading-path
  restarts.

**P0 gate:** Jenkins CI (containerized) green; canary red-teams pass; deploy rail
demonstrated end-to-end (commit → arb-vm running it); feasibility artifacts reviewed by
human.

### Phase P1 — data plant

- **M4 Breeze ingest** (runs as compose services on arb-vm via the M3.5 rail — backfill and
  WS capture write to VM volumes, never to a laptop; harvest-first: the harvest map's Breeze
  donors — token flow, fetchers, WS capture — are vendored/ported before any new connector
  code is written):
  session-token bootstrap; historical v2 fetcher with resumable budgeter (≤75/min, ≤4,500/day, 1,000 candles/call; priority
  campaign: 1m × U100/U150/U300 ≈ 28k–85k calls ≈ 6–17 quota-days for 3y; 1s only for a
  predeclared liquid subset); **forward WS capture from day one** (ticks/quotes/depth →
  bronze with receive timestamps, reconnect + gap log). *Verify:* recorded-cassette tests; no
  live calls in CI; backfill runbook.
- **M5 QC + quarantine**: OHLC sanity, calendar gaps, spike/decimal detection, CA cross-check,
  explicit stale/missing states. *Verify:* seeded corrupt fixtures caught; `make qc`.
- **M6 PIT masters**: instruments (token/symbol change history), corporate actions, ASM/GSM/
  T2T, **broker_capability daily snapshotter**, index membership; bitemporal storage +
  Merkle snapshot manifests `[C-DATA-02]`. *Verify:* as-of reads are byte-identical
  regardless of later snapshots; survivorship audit query runs.
- **M7 universe policies**: liquidity score `z(log median ₹vol) − 0.75·z(spread) −
  0.50·z(Amihud) − 0.25·z(gap-rate)` with fixed (stress-tested, never P&L-tuned) weights;
  N ∈ {50,100,150,300}; lookback {20,40,60}d; weekly/monthly refresh; stable-core hysteresis;
  eligibility gates (series, suspension, MIS/short per capability snapshot, history, bands).
  *Verify:* PIT test; churn ≤ target; survivorship label logic.
- **M8 feature store + diurnal profiles**: rolling stats via kernel binding; same-clock
  volume baselines; U-shape vol normalization. *Verify:* incremental == full recompute.

**P1 gate:** ≥ some weeks of live capture running nightly; 1m backfill for U300×3y complete;
QC green; universe snapshots exist.

### Phase P2 — screening machinery

- **M9 cost model**: `[C-COST-*]` goldens; effective-dated schedules; both brokers × three
  capital tiers; session-dependent spread table. *Verify:* `pytest tests/unit/costs -q`.
- **M10 vectorized engine (F0/F1-lite)**: panel forward returns, portfolio wrappers
  (long/flat, top-k, tolerance-neutral), cost application. *Verify:* 3-day toy case to the
  paisa.
- **M11 registry + manifests**: `[C-REG-01]`, experiment manifest format (Appendix B of the
  reference spec), daily-return preservation, M/M_erank computation. *Verify:* append-only
  enforced; erank on synthetic correlated trials.
- **M12 alpha wave 1 (T1 core)**: A01–A08 + A12 as AlphaSpecs with falsifiers + shuffled-
  future tests. *Verify:* `make s1-smoke` on fixtures.
- **M13 S1 runner**: enumerate `search_spaces/`; rank-IC curves + NW t + half-life + coverage
  + monotonicity; BH-FDR within family×universe; **null-search calibration** (feature/label
  destruction ⇒ survivor rate ≈ q). *Verify:* smoke; then first real sweep report for human.

**P2 gate:** family-balanced signal cards across ≥3 families on ≥2y × U150; null search
calibrated; multiplicity ledger populated.

### Phase P3 — honest simulation

- **M14 event engine + F1 fills**: protected-limit state machine (timeout/cancel/reprice
  capped and costed), partials/rejects, integer shares, paise accounting, flatten scheduler.
  *Verify:* replay determinism; accounting identity `pnl_gross − costs == pnl_net`; F1 vs
  vectorized reconciliation.
- **M15 nested walk-forward**: outer 21d / inner 21d / train 126d, purge = horizon, embargo ≥
  horizon + order duration; successive halving; Optuna inner-only; plateau-centroid
  selection. *Verify:* leakage canary dies here; overlap-inflation demo.
- **M16 stress battery**: costs ×1.5/×2, delay +1/+2 bars, fill degradation, universe
  N±buffer & leave-sector-out, drop-best-month, concentration (leave stock/day/session out),
  parameter heat maps. *Verify:* known-fragile toy fails, known-robust toy passes.
- **M17 alpha wave 2**: A09–A11, A13–A18, A27, A29, A30 (as data permits). Same bar.

**P3 gate:** ≥8 configs through stress with net SR ≥ 1.5 on the ₹0 line (≥1.0 on Zerodha
line), positive at 1.5× cost and +1 bar delay, ≥400 test trades each.

### Phase P4 — certification & bundles

- **M18 stats stack**: PSR/DSR (kurtosis convention: γ₄ raw; excess+... guard in code), CSCV/
  PBO with boundary purge, SPA with Hansen recentering + **Romano–Wolf stepdown / model
  confidence set** for final survivors, stationary bootstrap (day/week blocks), hierarchical
  partial pooling for family means; sealed-lockbox enforcement in the data layer (refuses
  those dates below release stage). *Verify:* Monte-Carlo size/coverage tests; lockbox-refusal
  test; null search on max-Sharpe.
- **M19 selection + turnover optimizer**: non-dominated (Pareto) sort across net return, DSR,
  MDD/CVaR, cost share, turnover/order count, stability, broker & capital-tier robustness;
  correlation clustering (1−corr) so near-variants form one cluster; τ*, h* per broker × tier
  (threshold economics + rotation condition from the Quant Foundations doc); combined-blotter
  netting fixed point; order-budget constraints. *Verify:* frontier reproduction on
  fixtures; netting ratio reported.
- **M20 bundles + dossiers**: `[C-BNDL-01]` build/sign/validate + tamper test; certification
  dossier (report card fields from the reference blueprint §12.2); lockbox one-shot run;
  **top-5 is a maximum — fewer is a valid output**. *Verify:* bundle round-trip; dossier
  completeness check.

**P4 gate (human):** 0–5 bundles; every certified one passes hard gates (integrity,
feasibility incl. broker capability, evidence, DSR ≥ 0.95 at N = M and sane at N = M_erank,
PBO ≤ 0.25, SPA p ≤ 0.10, cost/delay stress, plateau stability, concentration, lockbox);
pairwise PnL corr ≤ 0.5.

### Phase P5 — Rust production plant

- **M21 kernel + market + bars**: `math-kernel` (+PyO3 `math-python`), Breeze reader app,
  bar builder passing shared fixtures; watermark/late-event handling. *Verify:* `cargo test`;
  fixture parity; ULP policy tests.
- **M22 IR runtime**: alpha-IR/portfolio-IR interpreters, calibration application, no-trade
  bands; bundle loader with golden-fixture boot check. *Verify:* golden replay byte-equality
  on ≥3 recorded days.
- **M23 OMS + risk + journal**: order state machines `[C-OMS-*]`, idempotency, throttles
  (shared 5/s token bucket), risk governor + state machine `[C-RISK-01]`, hash-chained
  journal `[C-JRNL-01]`, crash-replay + broker reconciliation, flatten scheduler from
  capability snapshots. Broker adapter crates (`broker-flattrade`, `broker-zerodha`) are
  built harvest-first: port the auth flows, endpoint shapes, error taxonomies and quirks from
  the `past/` clients named in the harvest map, citing donors in each crate's PROVENANCE.md.
  **DRY_RUN only.** *Verify:* proptest on state machines; crash-mid-day
  replay reconstructs exactly.
- **M24 chaos + release parity**: disconnects, duplicate acks, timeouts, unknown orders,
  stale feed, circuit states, restart storms; staged parity ladder through accounting.
  *Verify:* chaos suite green; ≥5 golden days byte-exact incl. a gap day and an outage day.

**P5 gate:** parity + chaos green; 2-week dry run, zero unexplained diffs.

### Phase P6 — shadow, live, operate

- **M25 shadow on both brokers** (4–6 weeks minimum): real quotes, simulated orders; TCA
  (implementation-shortfall decomposition); **contract-note reconciliation** finalizes the
  production cost model; venue chosen by measured shortfall, not brochures. *Verify:*
  shortfall ≤ 30% of gross edge; slippage/reject/fill rates inside stress bands.
- **M26 limited live**: unlevered, one champion bundle, challengers shadow-only; ramp
  10–20% → 25% → 50% → approved full allocation **by evidence, not elapsed days**; CUSUM
  drift monitors (ARL₀ ≈ 250) de-risk 50% on first alarm, suspend on second; champion–
  challenger promotion repeats the full lineage; daily dossier binds bundle/binary/snapshot/
  state-chain hashes; operating cadence per session/day/week/month; any material change =
  new bundle = restart the appropriate gate.

### Kill criteria (pre-committed)

If a full honest cycle certifies nothing on the ₹0 cost line: do not loosen gates. The
registry postmortem distinguishes "edges existed gross, died to costs" (pivot: longer
horizons/delivery — new plan, same machinery) from "never existed" (stop, capital intact).
A machine that can say **no** is the product.

---

## 7. Testing policy

| Suite | Examples | Release effect |
|---|---|---|
| Unit | cost goldens, RZ, residuals, bar boundaries, calendars | blocks merge |
| Property | no-future-access, accounting conservation, idempotent order transitions, monotone fills | blocks merge |
| Golden | shared Py/Rust bars, features, intents, fees, replay days | blocks bundle release |
| Statistical | null-search calibration, DSR/PBO/SPA fixtures, bootstrap coverage | blocks promotion |
| Chaos | disconnect, duplicate ack, timeout, restart, stale feed, circuit | blocks live flag |
| Shadow | live feed + simulated orders, TCA, parity drift | blocks capital ramp |

Research invariants asserted continuously: `feature.max_source_ts ≤ decision_ts`;
`fill.ts > decision_ts`; `registry.is_append_only`; `pnl_gross − costs == pnl_net`;
`broker_positions == reconciled_internal_positions`; `no_open_position_after(flatten_deadline)`;
`shuffled_future_alpha_fails_promotion`; `repeated_run_hashes_are_equal`. The leakage canary
is permanent: if it ever passes, the infrastructure — not the market — changed.

**Anti-voodoo rejection list** (merged from both reference docs; PRs implementing any of
these are rejected): present-day constituents/eligibility projected backward · random-row
splits · same-bar signal+fill · full-day VWAP intraday · brokerage-only costs · OHLC-touch
passive fills · queue priority from snapshots · minute-Sharpe annualized as independent ·
lockbox reuse · hidden/deleted trials · unlimited grids branded exhaustive · five clones
branded diversified · exact neutrality regardless of ticket economics · leverage to rescue a
backtest · broker auto-square-off as primary exit · sub-minute claims without quote/depth
data · automatic live retraining · blind retry · failover without reconciliation · indicator
without estimand/mechanism/null/falsifier · elaborate model admitted for elaborateness.

---

### 7.1 Test-first protocol (TDD) `[G-TDD-01]`

Constitution rule 16 in operational form. The unit of work is one red→green→refactor
cycle, never "implement, then test":

1. **Red.** Write the smallest failing test that expresses the next increment — an
   AlphaSpec falsifier, a cost golden, a state-machine transition, a parity byte-check,
   a leakage canary. Run it. It must fail *for the reason you expect*: a test that errors
   on an import or a typo has not been observed to fail. Record the red output.
2. **Green.** Write the least code that passes it. Nothing speculative, nothing "while
   I'm here".
3. **Refactor.** Clean up with the suite green — behaviour is now pinned.

**Evidence.** The red output goes into `docs/state/log/<date>.md` and the PR body, beside
the green run. A milestone whose log shows only green output did not do TDD.

**Enforcement.** `make tdd-check` walks every commit on the branch oldest-first and fails
any commit that adds production code (`python/pips/`, `rust/crates/`, `schemas/`,
`apps/`) without a test landing in that commit or an earlier one. It runs inside
`make ci`, so Jenkins refuses the branch and the deploy rail never sees it. Docs, `ops/`
and `config/` changes are not production code and are not forced to carry tests. The
`TDD-Exempt: <reason>` trailer is the only bypass, and it is loud by construction.

**Ordering, not sincerity.** The machine can see ordering; only the recorded red output
proves the test was capable of failing. Both are required. Writing a test that cannot
fail, or back-dating an exemption, is the same offence as weakening a golden (rule 10) —
a human conversation plus an ADR, not an edit.

---

## 8. The doc layer: sharded state, decisions, and the ledger

**Problem this solves:** a single growing STATE/DECISIONS file eventually eats every context
window, and prose contracts drift from code silently. The fix is (a) shard everything hot,
(b) make the normative layer machine-readable and CI-checked — the **ledger**.

### 8.1 Sharded layout (all shards small by construction)

```
docs/
  INDEX.md                 # ≤40 lines: map of the doc layer + load rules (below)
  state/
    CURRENT.md             # ≤60 lines, OVERWRITTEN each session: active milestone,
                           #   last verified commands, next 3 actions, blockers
    log/YYYY-MM-DD.md      # append-only per-session shards; history, never auto-loaded
    blocks/BLK-####.md     # one block card per file (§10.4): symptom, repro, tried,
                           #   boundary, specialist role, resolution; closed cards stay
  decisions/
    INDEX.md               # one line per ADR: id · title · status
    ADR-0001-*.md          # one decision per file, ≤40 lines (context/choice/alternatives)
  ledger/
    INDEX.md               # counts by status + pointers
    contracts.yaml         # C-* rows (schema §8.2)
    gates.yaml             # G-* rows: threshold, enforcing code, evidence artifact
    salvage.yaml           # SAL-* rows from M1
  reference/               # the four companion documents (see §9) — consult, never ingest
  reports/                 # generated: feasibility probes, signal cards, dossiers, top-K
  runbooks/                # ops procedures (token bootstrap, backfill, incident, authority)
  DATA_DICTIONARY.md       # grows slowly; sharded per zone if it exceeds ~300 lines
```

### 8.2 The ledger — docs represented exactly in code

Every normative object has an ID and one row. Prose (this file) cites IDs; the ledger binds
IDs to code and tests; CI closes the loop.

```yaml
# ledger/contracts.yaml — one row per contract
- id: C-COST-01
  title: "RT statutory cost, ₹1L, Flattrade = ₹35.48 (3.548 bps)"
  spec: "IMPLEMENTATION.md#37-cost-model"          # where the prose lives
  source_refs: ["reference/cg-meta §8.2", "reference/blueprint Appendix A"]
  code: "python/pips/costs/statutory.py"
  tests: ["tests/unit/costs/test_golden.py::test_flattrade_1l_rt"]
  status: planned          # planned → building → enforced
  owner_milestone: M9

# ledger/gates.yaml — one row per promotion/release gate
- id: G-S4-DSR
  title: "Deflated Sharpe ≥ 0.95 at N=M (report N=M_erank)"
  threshold: {dsr_min: 0.95}
  enforced_by: "python/pips/search/funnel.py::gate_s4"
  evidence: "docs/reports/dossiers/<bundle_id>.md"
  status: planned
  owner_milestone: M18
```

`pips ledger check` (runs in CI) verifies: IDs unique; every `C-`/`G-` ID cited in
IMPLEMENTATION.md exists in the ledger and vice versa; for status ≥ `building` the code path
exists; for `enforced` the tests exist and are collected by pytest/cargo; every row cites a
spec anchor. **Definition of done for any milestone includes flipping its ledger rows to
`enforced`.** Changing a threshold means editing gates.yaml + the enforcing code + an ADR —
one commit, reviewable.

### 8.3 Session protocol (context-bloat prevention, mandatory)

**Load at session start (and nothing else by default):** `CLAUDE.md` → `docs/INDEX.md` →
`docs/state/CURRENT.md` → the **single active milestone section** of IMPLEMENTATION.md
(grep by `Mx` anchor) → ledger rows with `owner_milestone == Mx`.
**Load on demand only:** specific ADRs by ID; specific reference-doc sections (§9); old state
logs (rare). Never read `docs/reference/*` end-to-end and never paste more than the needed
subsection into context.
**Write at session end:** overwrite `state/CURRENT.md`; append `state/log/<date>.md` (what
was done, verify output, hashes); new ADR shards for any decision; ledger status flips; then
commit. A session that ends without updating CURRENT.md is an unfinished session.

---

## 9. Reference library — `pips/docs/reference/` (inside the repo)

Four documents, complementary by design, committed **inside this repository** at
`docs/reference/` (copied there at M0 — there is no external docs folder). Rule: **extract,
don't ingest** — pull the specific section you need (they are docx; run
`pandoc -t markdown` once per file and cache under `docs/reference/_extracted/`).

| File | Consult it for |
|---|---|
| `Meta-Algorithm_Blueprint_NSE_Intraday.docx` (Claude) | funnel gates rationale, turnover/cost math intuition, universe economics, roadmap logic, worked cost tables |
| `Quantitative_Foundations_Alpha_Math.docx` (Claude) | the formulas to implement: OU/MFPT thresholds, Faustmann h*, DSR/PBO/SPA, no-trade bands, Kalman recursions, theory→module→test map |
| `Indian_Cash_Equity_Intraday_Meta_Algorithm_Blueprint.docx` (ChatGPT) | GATE-0 authority details + source register [S1–S22], broker/exchange operational facts (CAS, square-off, rate limits, order types), stress grid, rejection list, staged GTM |
| `AlphaForge_PhD_Quant_Research_and_Engineering_Specification.docx` (ChatGPT) | the A01–A36 alpha cards (mechanism/estimand/domain/falsifiers/code), schemas (bundle, intent, envelope), bitemporal lineage, numeric semantics, dependency rules, test architecture |

Facts inside them carry verification dates (≈27–28 Aug 2026); anything operational must be
re-verified at use time and snapshotted into `broker_capability` / cost YAMLs — the reference
docs are rationale, the ledger + config are truth.

---

## 10. Session workflow, prompts, and governance files

### 10.1 Seeded at M0

`docs/INDEX.md`, `docs/state/CURRENT.md` (template), `docs/state/gates/` (empty — approval
files land here), `docs/decisions/INDEX.md`, `ledger/{contracts,gates,salvage}.yaml`
pre-populated with every `C-*`/`G-*` ID cited in this file at status `planned`,
`docs/reference/` populated with the four documents, and root `LOOP.md` written verbatim from
§10.6 (if the human hasn't already copied it in).

### 10.2 Kickoff prompts (copy-paste)

*(All of these are optional if you drive the project with `/loop 5m LOOP.md` — §10.6. The
loop covers bootstrap → harvest → every later session automatically; the prompts below remain
useful for one-off interactive sessions.)*

**First session:**
> Read IMPLEMENTATION.md end to end once (this is the only session that reads it fully).
> Execute M0 exactly: scaffold, CI, fixtures, docs shards, ledger seeded from the IDs in this
> file, `make ci` green. Overwrite docs/state/CURRENT.md, append a session log, commit on
> m/0-scaffold.

**Harvest session:**
> Follow docs/INDEX.md load rules. Execute M1 over ../past (read-only): produce
> ledger/salvage.yaml + docs/SALVAGE.md with a decision per component and the needs-coverage
> table naming a donor (or NONE_FOUND) for every M4/M6/M21–M23 infrastructure need. We harvest
> adapter glue from past/ instead of rewriting it — bias toward VENDOR/PORT. Important: the
> relevant code is often in each repo's COMMIT HISTORY, not at HEAD — sweep all branches,
> tags and deleted files per §1.2 and record the source commit SHA on every row.

**Every later session:**
> Follow docs/INDEX.md load rules: CURRENT.md, the active milestone section, its ledger rows.
> Plan, implement, run the milestone's Verify commands, flip ledger rows, update shards,
> commit on m/<id>.

**Phase-gate session (human present):**
> Assemble the P<k> gate evidence pack from ledger + reports (no re-running numbers from
> memory). Wait for sign-off before opening P<k+1>.

### 10.3 CLAUDE.md — paste as the repo's CLAUDE.md

```md
# pips — NSE cash-equity intraday meta-algorithm
Research factory (Python) certifies signed StrategyBundles; Rust plant executes them under an
independent risk layer. Breeze = read-only data plane; broker adapter = only order plane.
DRY_RUN by default; launch unlevered; no generative AI in the trading loop.

Environment: everything runs as Docker Compose services on arb-vm (SSH); ALL market data and
runtime state live on VM volumes — laptop = code + fixtures only. CI is LOCAL JENKINS (root
Jenkinsfile running the containerized `make ci`), not GitHub Actions; merge to main only on
green; arb-vm's deploy rail auto-builds and runs every new main SHA (trading-path services
never restart during market hours). Verify commands run inside the container:
`docker compose run research make ci`.

LOAD ORDER (strict, to protect context): docs/INDEX.md → docs/state/CURRENT.md → the active
milestone section of IMPLEMENTATION.md → its ledger rows. Everything else on demand only.
Reference docs in docs/reference/ are consulted by section, never ingested.

Commands (Make targets): make setup · test · lint · typecheck · ci · determinism · tdd-check ·
ledger-check · s1-smoke · backtest-smoke · parity DAY=<day> · qc

Constitution (full text IMPLEMENTATION.md §2): TEST-FIRST — every behavioural change starts
as a failing test (red→green→refactor); never write production code before its test, record
the red output in the session log + PR body (rule 16 / §7.1; `make tdd-check` enforces it,
`TDD-Exempt: <reason>` is the only, loud, bypass); determinism; causality = F_t-measurability
(AsOf view; bars close-labeled; no full-day fields intraday; no smoothed states); bitemporal
append-only evidence; every viewed trial counts; falsifiers before search; costs are
effective-dated data; two planes/two credentials/two processes; ≤5 orders/s governor;
../past is a READ-ONLY harvest source — check ledger/salvage.yaml before writing any
connector/adapter/glue (vendor or port donors; from-scratch needs a NONE_FOUND row); donors
often live in commit history rather than HEAD — sweep all branches/tags/deleted files and
extract with `git show <sha>:<path>`, recording the source SHA;
never weaken tests/goldens/gates/ledger to go green; update docs/state/CURRENT.md before
ending every session. BLOCKED? Don't grind: write docs/state/blocks/BLK-####.md and spawn a
FRESH agent with a role synthesized for that blocker's domain (Jenkins / compose / arb-vm /
deploy rail / broker onboarding …) per IMPLEMENTATION.md §10.4 — specialist, never generic.
```

### 10.4 Unblock protocol — dynamically generated specialist agents

**When an item is "blocked":** a milestone's Verify command still fails after ~3 distinct fix
attempts; or the failure sits at a boundary outside the working session's loaded context
(Jenkins pipeline, docker/compose, arb-vm, deploy rail, SSH/networking, broker/exchange
onboarding, data entitlement); or the session judges that more grinding is burning context
without new information. Grinding past this point is a protocol violation — escalate to a
specialist instead.

**Step 1 — write the block card** `docs/state/blocks/BLK-####.md` (≤50 lines):

```md
# BLK-0007 · deploy rail: compose build OOM on arb-vm
milestone: M3.5        boundary: arb-vm / docker build
symptom: <one line>    repro: <exact command + where it runs>
expected vs actual: <short>
tried: <numbered list of distinct attempts + outcomes>
suspected domain(s): docker buildkit memory, VM swap, rust build parallelism
relevant shards: ledger rows touched, ADRs, runbook paths   # pointers, not pasted content
danger notes: what the specialist must NOT touch (live flags, data volumes, past/)
```

**Step 2 — synthesize the specialist role, then spawn a FRESH agent with it.** Never a
generic "please help" agent: generate a role definition *from the block card's domain* and
give the new agent only that role + the block card + the constitution pointer — not the
milestone context, not the whole doc layer (fresh context is the point). Role template:

```md
You are a <DOMAIN> specialist (e.g., "Jenkins declarative-pipeline + dockerized-CI debugger",
"docker compose networking/volumes engineer", "systemd-timer deploy-rail engineer",
"Breeze session/auth integration specialist", "Rust cross-compilation in containers").
Mandate: resolve BLK-#### — root-cause it, fix it or produce an exact fix plan, and leave a
prevention artifact (regression test, runbook section, or ledger row).
Reach: local repo; the project containers; Jenkins logs/config; arb-vm over SSH (read +
service-level actions); deploy-rail scripts. Boundaries: pips constitution applies in full —
../past read-only, no live-flag chain, no gate/test/golden weakening, no data-volume
deletions; anything requiring credentials, spend, or an irreversible step goes back as a
human question on the block card.
Deliverable: append to BLK-####.md — root cause, change made (commit/branch), verification
output, prevention artifact path — then stop.
```

Mechanics in Claude Code: spawn via the agent/subagent facility with the synthesized role as
its prompt, or launch a fresh `claude` session pointed at `docs/state/blocks/BLK-####.md`
(`BLK-####-role.md` beside it). The blocked session commits the card first, so the specialist
starts from disk truth, then either waits (if interactive) or ends its session cleanly with
CURRENT.md noting "blocked on BLK-####, specialist dispatched".

**Step 3 — resume or escalate.** The main-line session resumes from the updated block card;
a closed card cites its prevention artifact (a block that can recur without a tripwire isn't
closed). If the specialist also fails or hits a human-only decision (credentials, approvals,
money, broker paperwork), the card flips to `escalated: human` and appears in CURRENT.md's
blockers line until resolved. Block cards are never deleted — they are the outage history of
the project, and recurring domains tell us where to invest (a third Jenkins BLK means the
pipeline needs redesign, not a third rescue).

### 10.5 Pre-seeded ADRs (write these files at M0)

- **ADR-0001** Bar timestamp convention: close-labeled; Breeze convention probed at M3/M4 and
  normalized on ingest.
- **ADR-0002** Kernel strategy: bundle-crossing primitives implemented once in Rust
  `math-kernel` with PyO3 binding; slow Python oracle for property tests only (§3.12).
- **ADR-0003** Launch leverage: unlevered at go-live across ₹2L/₹5L/₹10L tiers; MIS leverage
  is a later overlay requiring its own validation cycle (supersedes v1's 4× working
  assumption for launch).
- **ADR-0004** Session taxonomy: six states incl. CAS (§3.15), replacing v1's O/M/C; CAS
  disabled as an alpha venue pending data + broker support.
- **ADR-0005** Alpha registry: A-catalogue (A01–A36) is canonical; v1 F-ids retained as
  aliases per the §5 mapping.
- **ADR-0006** Signal-feed authority: Breeze pending GATE-0 written clarification; fallback =
  execution-broker feed (Kite Connect tier or Flattrade API) via adapter swap.
- **ADR-0007** Task runner & CI: plain `Makefile` targets + native Jenkins declarative
  pipeline (local), no `just` (owner policy: no archived/abandoned tooling under a trading
  system) and no GitHub Actions; Jenkinsfile stages mirror the Make targets 1:1 inside the
  project container.
- **ADR-0008** Unblock protocol (§10.4): blocks are cleared by fresh, dynamically synthesized
  domain-specialist agents working from block cards, with cross-boundary reach (Jenkins,
  containers, arb-vm) under the full constitution; recurring block domains trigger redesign,
  not repeated rescues.
- **ADR-0009** Test-first (§7.1): TDD is constitution rule 16, not a preference —
  red→green→refactor with the red output recorded, enforced mechanically by `make tdd-check`
  `[G-TDD-01]` inside `make ci`; `TDD-Exempt: <reason>` is the only, deliberately loud, bypass.

### 10.6 LOOP.md — paste as the repo's LOOP.md (autonomous loop driver)

The one command the human needs: **`/loop 5m LOOP.md`**. Every tick re-delivers this file;
it must therefore be idempotent, re-entrant, and cheap on context — continuity lives in git +
the doc shards, never in chat memory. Copy this verbatim to the repo root (next to CLAUDE.md;
on a brand-new checkout the human copies IMPLEMENTATION.md, CLAUDE.md and LOOP.md in, then
starts the loop — nothing else is required from bootstrap through live-ramp prep):

```md
# LOOP.md — pips autonomous driver (re-delivered every tick; heartbeat, not a reset)

If you are mid-task in this same session, IGNORE the rest of this file and continue; treat
this delivery as a heartbeat. Otherwise run ONE bounded work unit:

## 0 · Orient (cheapest sufficient read — never more)
- No docs/INDEX.md yet? → BOOTSTRAP: read IMPLEMENTATION.md fully (the only full read,
  ever), then execute M0 and M0.5. Stop after committing.
- Else: read docs/INDEX.md → docs/state/CURRENT.md → the ACTIVE MILESTONE section only of
  IMPLEMENTATION.md → its ledger rows. Do not open reference docs unless the task needs a
  specific section.

## 1 · Pick exactly one action, in this priority order
1. `git status` dirty or verify half-run from a previous tick → finish/commit that first.
2. Open block card escalated to human → check for the human's answer on the card. If the
   human has answered, act on it. If not: note "waiting on BLK-####" in CURRENT.md, then —
   only if that block sits on the ACTIVE item / critical path — stop the tick. An escalated
   block that does not gate the next milestone must NOT halt the project: record it and fall
   through to the next actionable item below. (Don't grind on a blocked item; don't idle the
   whole plant because one side road is closed.)
3. Open non-escalated block card → act as (or spawn) the §10.4 domain specialist for it.
4. CURRENT.md says awaiting phase gate → if docs/state/gates/P<k>-approved.md exists, open
   the next phase; else re-run the phase's headline Verify (regression watch), update
   CURRENT.md, stop.
5. Otherwise → advance the active milestone (or start the next per §6 order): plan briefly,
   then TDD ONE coherent chunk — write the failing test FIRST, run it, keep the red output;
   write the least code that turns it green; refactor under green. Then run that milestone's
   Verify commands (`docker compose run research make ci` or the milestone-specific target)
   and commit on m/<id>-<slug>.

## 2 · Close the tick (mandatory, even for "nothing to do")
- Overwrite docs/state/CURRENT.md (active item, last verify output, next 3 actions,
  blockers/awaiting). Append one line to docs/state/log/<today>.md — including the RED
  output you observed before the code went green (§7.1 evidence; green-only logs are not TDD).
- Flip any ledger rows you completed. New decision → ADR shard. New block → BLK card.
- Commit. End with a one-line status: DONE <what> | BLOCKED BLK-#### | AWAITING P<k> gate.

## Hard rails (constitution §2 binds every tick)
- Never create/enable anything on the live path: no PIPS_LIVE, no live flags, no real orders.
- Never weaken tests/goldens/gates/ledger to go green. Never touch ../past except read-only.
- Never write production code before a failing test (rule 16). `make tdd-check` refuses the
  branch; a `TDD-Exempt: <reason>` trailer is the only bypass and it must state a real reason.
- Never merge to main with red CI; never proceed past a phase gate without its approved-file.
- Milestone Verify failing after ~3 distinct attempts, or any Jenkins/compose/arb-vm/deploy
  boundary issue → STOP grinding, write the block card, dispatch the specialist (§10.4).
- Human-only items (credentials, spend, broker paperwork, GATE-0 authority, gate sign-offs)
  → record precisely what is needed in CURRENT.md and hold; never simulate or fake them.
- If everything is blocked or awaiting humans: say so in one line and idle — do not invent
  work, do not refactor for sport.
```

Notes for the human: the loop holds at every phase gate until you drop
`docs/state/gates/P<k>-approved.md`; it holds on escalated block cards until you answer on
the card; and it can never start live trading — the live-flag chain (§2 rule 8) is outside
the loop's authority by construction. Those three pause points are the entire manual surface
of the project.

---

## 11. What "done" means

Nightly: capture + QC green, incremental S1/S2, drift monitors, challenger evals, and
`docs/reports/topk-<date>.md` regenerating the certified set with live-vs-certification
tracking. A new idea goes from `AlphaSpec` YAML to searched-counted-and-judged with zero
engine changes. Every number in every report resolves to a config hash + snapshot root; every
contract in this file resolves, via the ledger, to code and a passing test. The system can
say "no strategy passed" — and when it says yes, the evidence chain is the reason to believe
it.
```
