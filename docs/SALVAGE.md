# SALVAGE.md — the harvest map (M1)

What exists in `../past` that pips should reuse, what it must write from scratch, and the
evidence for each. The machine-readable form is [`ledger/salvage.yaml`](ledger/salvage.yaml);
this file is the reading version. **Consult it before writing any connector, adapter,
session/token flow, instrument master, downloader or calendar** (constitution rule 13).

`make salvage-verify` resolves every donor row against `../past` read-only:

```
salvage-verify OK: 21 donor row(s) resolve to real blobs in ../past;
                   7 NONE_FOUND row(s) carry a search record
```

## The sweep

Three repos, every ref, full history — not just working trees. That distinction decided the
outcome: **the single most valuable donor is not present in any working tree.**

| repo | commits | refs swept | code paths ever | at HEAD | verdict |
|---|---|---|---|---|---|
| `intraday` | 47 | `main`, `origin/main`, `origin/HEAD` | 89 | **0** | the Breeze donor |
| `convexity` | 177 | `main`, `origin/main`, `origin/HEAD`, `origin/hardening`, `origin/journal-backups-convexity` | 816 | 453 | live-fleet machinery, wrong venue |
| `vol_research` | 26 | `main`, `origin/main`, `origin/HEAD` | 4 | 0 | no code at all |

No repo has tags. Method for every row: path sweep across all refs (`--diff-filter=AMR` plus
the deletion sweep), then `git grep -i` over every reachable commit, then — for each candidate
path — walking `rev-list --all` newest-first until a commit's tree actually contains the blob.
A commit message is a hint; the blob is the evidence.

> **`intraday`'s HEAD is a bare README.** Its entire `src/volarb/` tree was deleted by
> `9381e97` ("Strip to minimal directional-ITM ORB engine") and `1fa7ea8` ("Refactor code
> structure"). Judging that repo by its working tree would have concluded "nothing here" and
> pre-authorised writing the Breeze adapter from scratch. §1.2 exists for exactly this case.

## Needs-coverage table

Every infrastructure need in M4 / M6 / M21–M23 and ops, answered. `make ledger-check`
fails if any row here goes unanswered, so this table cannot silently rot.

| need | donor | decision | where |
|---|---|---|---|
| M4 session-token flow | Breeze daily-session auth | PORT | `intraday be8186d:src/volarb/adapters/breeze/auth.py` |
| M4 historical fetcher | Breeze OHLCV fetch + normalizer | PORT | `intraday be8186d:…/breeze/history.py` |
| M4 rate-limit budgeter | RateLimiter + Status-5 detection | PORT | `intraday be8186d:…/breeze/ratelimit.py` |
| M4 backfill orchestrator | resumable multi-instrument backfill | PORT | `intraday be8186d:…/breeze/backfill.py` |
| M4 websocket capture | — | **NONE_FOUND** | only a runtime `.log`; SAL-0025 |
| M6 instrument master | — | **NONE_FOUND** | SAL-0026 |
| M6 exchange calendar | — | **NONE_FOUND** | SAL-0027 |
| M6 corporate actions | small CA module (shape only) | PORT | `convexity 790d723:src/convexity/breakout/data/corporate_actions.py` |
| M7 universe policy | liquidity ranking, universe API, Amihud | PORT | `convexity 8b8ceae`, `a1ffbf1` |
| M9 cost model | NSE charge stack; spread/impact; Corwin–Schultz | PORT | `intraday ac3cba7`, `convexity c13fccaf`, `8b8ceae` |
| M15 nested walk-forward | walk-forward + embargo + holdout splitter | PORT | `intraday 8023ae3:src/volarb/backtest/splits.py` |
| M3.5 deploy rail | continuous deploy script | PORT | `convexity d7a733a:ops/deploy/autodeploy.sh` |
| M21 breeze reader (Rust) | — | **NONE_FOUND** | no Rust in `../past`; SAL-0028 |
| M23 broker-flattrade | — | **NONE_FOUND** | zero hits anywhere; SAL-0023 |
| ~~M23 broker-zerodha~~ | — | retired | need dropped by ADR-0010; SAL-0024 kept as history |
| M23 reconciliation / risk / accounting | reconcile map, brake engine, accounting | PORT | `convexity 635b051`, `c13fccaf` |
| ops alerting | fleet alert script | WRAP | `convexity eedf44f:scripts/fleet_alert.sh` |

## What each repo actually gives us

**`intraday` — the Breeze donor, entirely in history.** `be8186d` is the last commit where
the adapter demonstrably worked; an upstream commit says the parser was "validated on live
Breeze". Four substantial modules (auth 1.4 KB, history 3.7 KB, ratelimit 2.3 KB, backfill
14.7 KB) plus their tests. Also the NSE cost model with date-aware STT (`ac3cba7`, 6.1 KB)
and a walk-forward splitter whose commit claims 12 tests pinning no-lookahead and
holdout-isolation (`8023ae3`). Everything else in the tree — `data.py`, `execution.py`,
`factories.py`, `providers.py` — is a 100–260 byte scaffold stub, recorded as SKIP so a later
sweep does not re-investigate them.

**`convexity` — a live fleet, on the wrong venue.** Binance USDT-M crypto plus commodity and
equity books, trading real money since July 2026. No Breeze, no Kite, no Flattrade, no NSE
broker code exists in it. What it does have is the machinery around running a live fleet, and
most of it is at HEAD: a continuous deploy rail whose safety properties were written for real
capital, liquidity ranking and universe gating, a spread/impact friction model with a
Corwin–Schultz estimator and its rejection rules, Amihud calibration, broker-truth
reconciliation, and an exposure-reducing brake. Venue differs; the failure taxonomies do not.

**`vol_research` — no code.** Four code paths ever existed, none at HEAD. Its Kite/Zerodha
matches are **prose**: a vendor comparison table pricing Kite Connect at ~₹500/month and
ruling out QuantConnect for NSE. Not a donor — but useful context for ADR-0006 and
`[G-AUTH-0]`, which is where the fallback-feed decision lives, and it is cited there.

## Three warnings carried into the milestones that will use these

1. **Do not inherit the rate limit.** SAL-0003 encodes Breeze at 100/min. M3 records that the
   docs conflict (100/min vs 75/min) and pips throttles to **75** until confirmed. Port the
   Status-5 detection and the budgeter shape; the constant is a probe result, not a donor's.
2. **Do not inherit the fee numbers.** SAL-0006's rates are stale. Costs are effective-dated
   data with `verified_on` (rule 6), and §3.7 pins today's goldens. Port the structure and
   re-verify every number.
3. **Do not inherit the panel semantics.** SAL-0008 predates as-of discipline entirely. Every
   pips panel is read through `AsOfPanelView` and may not expose a row later than
   `decision_ts` (rule 2). It is a shape reference, nothing more.

## Cross-language donors still count

There is no Rust anywhere in `../past` — all three repos are Python. That does not make the
M21 `market-breeze` crate a from-scratch job in the sense that matters: SAL-0001…0004 supply
the auth quirks, endpoint shapes, error taxonomy and edge-case knowledge, and §1.2 says a
donor that cannot be vendored across languages is still a donor. Cite them in
`rust/crates/market-breeze/PROVENANCE.md`.

## Rules that bind anything taken from here

`../past` is **read-only** (§1.1 rule 1) — extraction is `git show <sha>:<path>`, never a
checkout that moves a donor repo's state. Reuse means **vendor** (copy into
`vendor/past/<repo>/…` with a `PROVENANCE.md` recording repo, path, exact source SHA, ref,
date and changes) or **port** (rewrite to §3 contracts). The pips architecture wins: old code
adapts to the contracts, and a contract change needs an ADR.
