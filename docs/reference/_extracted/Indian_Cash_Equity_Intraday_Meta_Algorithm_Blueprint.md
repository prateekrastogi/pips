**QUANTITATIVE SYSTEM DESIGN**

**Cash-Equity Intraday\
Alpha Discovery System**

A meta-algorithm architecture for bounded strategy search, universe selection, turnover economics, robust validation, and Python-to-Rust deployment

**NSE cash equities • scalping-to-intraday • capital below ₹10 lakh**

  --------------------------------------------------------------------------------
  **Research**   **Production**   **Market data**         **Execution contexts**
  -------------- ---------------- ----------------------- ------------------------
  Python         Rust             ICICI Direct Breeze\*   Flattrade / Zerodha

  --------------------------------------------------------------------------------

*\*Separate market-data and order APIs; see the pre-live data-use check in this blueprint.*

Version 1.0 \| Information verified through 27 August 2026

# Contents

A decision-oriented reading map. Section numbers follow the build sequence from mandate through live operation; appendices make the protocol executable.

  -----------------------------------------------------------------------------------------------
  **Foundations and discovery**                   **Validation, deployment and operation**
  ----------------------------------------------- -----------------------------------------------
  Executive decision                              8\. Simulator, costs and turnover

  1\. Mandate and boundary                        9\. Portfolio construction below ₹10 lakh

  2\. Meta-algorithm architecture                 10\. Validation architecture

  3\. Data architecture and Breeze feasibility    11\. Multiple testing and overfitting control

  4\. Point-in-time universe selection            12\. Choosing the top three to five bundles

  5\. Typed alpha-component library               13\. Python research to Rust production

  6\. Sessions, market state and regime routing   14\. Risk architecture

  7\. Bounded search without brute-force bias     15\. Regulatory and broker controls

  Appendix A --- Meta-search pseudocode           16\. Staged go-to-market plan

  Appendix B --- StrategyBundle manifest          17\. Concrete first research campaign

  Appendix C --- Pre-live checklist               18\. Operating cadence and rejection list

  Appendix D --- Source register                  Source notes and verification dates
  -----------------------------------------------------------------------------------------------

## Decision path

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **1 · Define**                                  **2 · Discover**                                         **3 · Disprove**                                     **4 · Release**
  ----------------------------------------------- -------------------------------------------------------- ---------------------------------------------------- -------------------------------------------------------------
  Freeze scope, data, costs and search grammar.   Generate causal, typed pipelines within fixed budgets.   Stress costs, regimes, folds and multiple testing.   Promote only diverse bundles through shadow and live gates.

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **HOW TO USE THIS DOCUMENT** Parts I--III define what may be searched. Parts IV--VIII define how it is simulated and validated. Parts IX--XII define promotion, live architecture, risk, and staged launch. The appendices provide the concrete starter protocol, bundle schema, pseudocode, and source register.
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# Executive decision

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **RECOMMENDATION** Build a research factory that produces a small set of versioned StrategyBundles---not a single all-purpose bot and not a leaderboard of thousands of backtests. Each bundle must bind its universe policy, session, signal graph, broker/capital cost model, portfolio rules, execution policy, risk limits, and validation evidence.
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

The system can comprehensively explore a declared search grammar, but it cannot find a globally optimal strategy over an unbounded space. Testing more variants without statistical discipline increases the probability of selecting noise. The honest target is the most robust non-dominated set within a predeclared, economically plausible, causally valid search space.

Optimal = arg max {robust net utility \| data version, universe policy, broker costs, capital, risk constraints, search budget}

-   **Output.** Up to three to five deployable, mutually useful StrategyBundles. If only one or two clear the gates, promote only those.

-   **Initial research floor.** One-minute causal replay for roughly 3--120 minute holding periods; true sub-minute scalping waits for collected quote/trade/depth data and calibrated fills.

-   **Breadth.** Search dynamic liquidity-ranked universes of 50, 100, 150, and 300 NSE names; do not optimize a hand-picked ticker list.

-   **Turnover.** Make rebalancing, holding time, no-trade bands, position count, and ticket size endogenous. Optimize net capital efficiency, not trade count.

-   **Broker context.** Run every surviving strategy separately at ₹2 lakh, ₹5 lakh, and ₹10 lakh under current Flattrade and Zerodha cost/operational assumptions.

-   **Technology.** Python owns data, research, fitting, search, and reports. Rust owns the live state machine, risk, orders, recovery, and reconciliation.

-   **No generative AI.** The research and production loops are deterministic/statistical. They need no LLM or generative component.

## Pre-live data-use check for the separate-API design

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **GATE 0 --- DATA-USE AUTHORITY** The chosen architecture uses Breeze only as a read-only market-data API and a separate broker API for orders; no Breeze quote needs to be sent to the execution broker. ICICI's current FAQ nevertheless says Breeze is for individual/personal trading and prohibits integration with third-party applications for trading. It explicitly supports self-built code on the customer's own computer, but publishes no data-only exception for signals executed through another broker. Obtain written ICICI clarification before live release; otherwise use the execution broker's feed or a separately licensed source. Never redistribute Breeze quotes. **^\[S3\]\ \[S4\]\ \[S5\]^**
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

The blueprint preserves this exact technical split: BreezeDataAdapter is read-only, while FlattradeOrderAdapter and ZerodhaOrderAdapter have the only order permissions. The permission check is a pre-live release gate, not an architecture change. Zerodha's Connect tier currently includes live WebSocket data and historical candles for ₹500/month; Flattrade advertises a free API/data context. These remain fallback inputs if their own terms and entitlements are confirmed for the intended personal algorithm. **^\[S13\]\ \[S17\]^**

## What success looks like

  --------------------------------------------------------------------------------------------------------------------------------------------
  **Deliverable**     **Acceptance meaning**
  ------------------- ------------------------------------------------------------------------------------------------------------------------
  Search protocol     Frozen grammar, budgets, folds, costs, seeds, promotion rules, and one-use lockbox before finalist testing.

  Research registry   Every completed, failed, abandoned, and manually viewed trial is logged under a content hash.

  Top 3--5 bundles    Pareto-diverse candidates with full broker/capital context, not five nearby parameter variants.

  Rust release        Golden replay matches Python bars, features, regimes, forecasts, targets, order intents, and risk rejections.

  Operational proof   Shadow/paper evidence, actual slippage, recovery drills, reconciled positions, and zero unintended overnight exposure.
  --------------------------------------------------------------------------------------------------------------------------------------------

# 1. Mandate and boundary

## 1.1 Frozen initial mandate

-   Instrument class: NSE cash equities; BSE stays out until an independently verified entitlement and instrument history are available.

-   Horizon: fast intraday through end-of-day; every position flat before the broker-, product-, side-, and instrument-specific cutoff.

-   Directions: long/flat plus intraday long/short only where current broker and exchange eligibility permit it.

-   Capital contexts: ₹2 lakh, ₹5 lakh, and ₹10 lakh; initial limited live operation is unlevered.

-   Execution: limit or protected marketable-limit logic; pure algo market orders are not assumed to be available.

-   Excluded initially: overnight inventory, derivatives/options, market making, sub-second queue alpha, and passive-fill claims unsupported by historical order-book data.

Breeze's current API reference lists NSE support and says BSE/MCX are unavailable, while parts of the SDK contain conflicting examples. The safe scope is NSE cash until account-level testing or written confirmation resolves that conflict. **^\[S1\]\ \[S2\]^**

## 1.2 What 'scalping' may honestly mean

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Research lane**   **Data required**                                                  **Credible claims**                                                     **Not credible yet**
  ------------------- ------------------------------------------------------------------ ----------------------------------------------------------------------- -------------------------------------------------------------------
  1-minute bar lane   Completed 1-minute OHLCV; next-event fills                         3--120 minute forecasts, aggressive-limit scenarios, cost sensitivity   Queue position, same-bar stop ordering, sub-minute spread capture

  1-second bar lane   1-second OHLCV/LTP bars plus live spread calibration               Fast price/volume features with conservative execution stress           Historical bid/ask/depth or precise passive fills

  Tick/depth lane     Locally captured quotes, depth, trades, receive timestamps, gaps   Sub-minute execution and microstructure research after calibration      Exchange-colocation/HFT assumptions
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **CAUSALITY RULE** A signal computed from completed bar t cannot fill on bar t. Its earliest simulated fill is the next executable event after decision and broker latency. If both stop and target occur inside one OHLC bar, use tick replay or the adverse sequence.
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 1.3 Formal objective: edge × rotation, after reality

Turnover is useful only while incremental opportunities retain positive net edge. As rotation rises, weaker signals are admitted, tickets fragment, spread/impact rise, and correlated positions compete for the same capital. The optimizer must model actual capital reuse through time rather than multiplying a backtest edge by an arbitrary trade count.

E\[r_day\^net\] ≈ R · \[e(R) − c(R)\] and R\* = arg max_R R\[e(R) − c(R)\]

Net P&L_t = q\_(t−1)ᵀ(P_t−P\_(t−1)) − C_b(Δq_t, market state_t)

  ------------------------------------------------------------------------------------------------------------------------------------------
  **Metric**                **Definition**                               **Why it matters**
  ------------------------- -------------------------------------------- -------------------------------------------------------------------
  Net return on NAV         Daily net P&L ÷ start-of-day equity          Actual ROI; traded notional is not capital.

  Gross-notional turnover   Σ \|executed notional\| ÷ average equity     Measures trading load and costs.

  Round-trip rotation       Gross-notional turnover ÷ 2                  Approximate capital recycling when buys and sells pair.

  Net bps per turnover      Net P&L ÷ gross traded notional              Separates edge quality from activity.

  Capital-time efficiency   Net P&L ÷ exposure integrated over session   Rewards rapid reuse without pretending idle capital was deployed.
  ------------------------------------------------------------------------------------------------------------------------------------------

# 2. Meta-algorithm architecture

![Flow from licensed data through universe construction, typed alphas, costed simulation, validation, Pareto selection, and Rust deployment.](media/image1.png){width="6.35in" height="4.5118416447944005in"}

Figure 1. The discovery system produces auditable StrategyBundles; validation and stress results feed back into the registered research process.

## 2.1 The unit of discovery is a StrategyBundle

A StrategyBundle is a complete deployable specification, not an isolated signal. It binds the following items under one immutable identity:

-   Point-in-time universe policy and daily membership snapshot.

-   Bar resolution, decision clock, feature graph, warm-up, missing-data policy, and numerical version.

-   Session buckets, regime inputs, forecast calibration, and forecast expiry.

-   Portfolio constraints, integer rounding, entry/rebalance/exit logic, and turnover controls.

-   Broker, capital tier, fee schedule, fill model, latency model, and cost-stress version.

-   Independent risk-policy reference, new-entry cutoff, flatten schedule, and failure behaviour.

-   Code/data/split hashes, trial lineage, validation evidence, golden fixture, and bundle checksum.

## 2.2 Typed pipeline grammar

UniversePolicy\
→ BarBuilder → DataQualityGate → RawFeatureBlocks\
→ \[FactorResidualizer\] → Normalizer → AlphaFamilyModules+\
→ ForecastCalibrator / Ensembler → \[SessionRegimeGate\]\
→ PortfolioWrapper → ExecutionPolicy → ExitPolicy → RiskPolicy

'Any method in any order' is not a useful search space. The grammar permits only semantically valid compositions. Residualizing raw returns before computing momentum is distinct from computing raw momentum and then sector-demeaning its score; each has a canonical graph identity. Algebraically duplicate graphs hash to one trial.

  ---------------------------------------------------------------------------------------------------
  **Module contract**   **Required declaration**
  --------------------- -----------------------------------------------------------------------------
  Input/output          Typed fields, units, time semantics, cross-sectional vs time-series scope

  Causality             Maximum lookback, warm-up, decision availability, forbidden future fields

  State                 Rolling buffers, reset rules, fold-boundary handling, restart serialization

  Missing data          Skip, stale, carry-forward, or impute policy; every policy explicit

  Parameters            Bounded schema, permitted transforms, default and search distribution

  Implementation        Version, numerical precision, rounding, Python/Rust parity tolerance
  ---------------------------------------------------------------------------------------------------

# 3. Data foundation and feasibility

## 3.1 What Breeze can and cannot supply

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Capability**      **Current official statement**                                                               **Engineering consequence**
  ------------------- -------------------------------------------------------------------------------------------- ---------------------------------------------------------------------------------------
  REST quota          100 calls/minute and 5,000/day; a marketing page still says 75/minute                        Throttle to ≤75/min until confirmed; cache every response.

  Historical v2       1-second, 1-minute, 5-minute, 30-minute, 1-day; 1,000 candles/request                        Chunk by candle count; broad one-second history is slow to acquire.

  History depth       Landing pages say 3 years; SDK README claims 10 years                                        Budget on 3 years; probe earliest valid date per symbol.

  Corporate actions   Historical series are not adjusted                                                           Maintain raw and adjusted prices; never use adjusted prices for fills.

  Live stream         Tick-by-tick quotes, best bid/ask, quantities, aggregate volume; live depth channel exists   Capture locally with exchange and receive timestamps; no public SLA/replay guarantee.

  Subscriptions       Up to 2,000 scripts across OHLC/live streaming                                               A 300-name universe is nominally feasible; load-test combined quote/depth channels.

  Instrument master   Daily security master updated around 08:00                                                   Snapshot it every day; never overwrite history.

  Service warranty    Timeliness, sequence, accuracy, completeness and availability are not guaranteed             Staleness/gap controls and independent reconciliation are mandatory.
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Official sources conflict on history depth, supported exchanges, and the minute-level request limit. A feasibility probe must become a saved artifact before the search budget is approved. **^\[S1\]\ \[S2\]\ \[S5\]^**

## 3.2 Backfill economics

The 1,000-candle response cap and 5,000-call daily quota make one-second breadth expensive even when the endpoint technically supports it. The estimates below are lower bounds: 250 trading days/year, 375 one-minute bars/day, 22,500 one-second bars/day, full 1,000-candle responses, no retries, and constant symbol history.

  ------------------------------------------------------------------------------------------------------------------
  **Resolution / scope**           **Approx. calls**   **Minimum quota days**   **Use**
  -------------------------------- ------------------- ------------------------ ------------------------------------
  1-minute • 100 names • 3 years   28,200              5.6                      Primary broad research lane

  1-minute • 300 names • 3 years   84,600              16.9                     Extended universe / robustness

  1-minute • 100 names • 5 years   47,000              9.4                      Longer regime history if available

  1-second • 100 names • 1 year    562,500             112.5                    Too slow for naïve broad backfill

  1-second • 300 names • 1 year    1,687,500           337.5                    Not a practical first milestone
  ------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **DATA PLAN** Backfill 1-minute data for the dynamic 100/150/300 research pools, then begin a forward raw quote/depth capture immediately. Use one-second/tick research only on a smaller, predeclared liquid subset until a sufficient forward archive exists.
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 3.3 Canonical point-in-time store

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Dataset**               **Minimum fields / rule**
  ------------------------- -------------------------------------------------------------------------------------------------------------------------------------------
  instrument_master_daily   date, exchange token, stable instrument ID, symbol, ISIN, series, tick, price band, listing/delisting, sector, broker product eligibility

  bars_raw                  instrument, interval, start/end, raw OHLCV, source, ingest time, completeness flags

  quotes_ticks              exchange timestamp, receive timestamp, bid/ask + size, LTP/LTQ, cumulative volume, depth, validity/gap flags

  corporate_actions         announcement/ex date, split/bonus/dividend terms, point-in-time source, adjustment factor

  exchange_calendar         normal/special sessions, CAS eligibility, holidays, halts, pre-open and close transitions

  broker_capability         effective date, instrument/product/side eligibility, leverage/margin, cutoff, order types, rate limits

  orders_fills              intent, submission/ack/exchange/fill timestamps, status transitions, fees, rejection, slippage, broker truth
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

-   Append-only raw partitions; corrected data creates a new snapshot, never a silent overwrite.

-   Asia/Kolkata exchange calendar plus UTC storage; clock sync and receive timestamps are mandatory.

-   Adjusted series for return/factor research; raw traded prices for tick rounding, quantities, price filters, fills, fees and P&L.

-   Every missing or stale interval is explicit. A zero-volume bar is not interchangeable with a missing bar.

-   Cross-sectional normalization waits for a decision cutoff, then uses only instruments whose bar was available by that cutoff.

# 4. Point-in-time universe discovery

## 4.1 Universe is a daily policy, not today's constituent list

Eligible\_(i,d) = 1{listed ∧ series allowed ∧ broker-MIS allowed ∧ history sufficient ∧ data valid ∧ restrictions clear}

L\_(i,d) = z(log median ₹-volume) − 0.75z(spread_bps) − 0.50z(Amihud) − 0.25z(gap_rate)

U_d(N) = Top-N liquidity scores computed only from information available by close d−1

Do not search individual stock inclusion as an alpha parameter. That is a high-dimensional route to selection bias. Search a small set of interpretable, execution-oriented policies; their weights are fixed or stress-tested for liquidity, not tuned to maximize strategy P&L.

  --------------------------------------------------------------------------------------------------------------------------------------------
  **Policy dimension**   **Starter values**                            **Guardrail**
  ---------------------- --------------------------------------------- -----------------------------------------------------------------------
  N                      50, 100, 150, 300                             Equal development budget; 200 may be added only if useful.

  Liquidity lookback     20, 40, 60 sessions                           Use prior sessions; prefer median/lower quartile over one-day volume.

  Refresh                weekly, monthly; daily as stress              Membership fixed for each session.

  Listing history        60, 120, 250 sessions                         Warm-up requirement binds.

  Stable-core buffer     enter above N−k; exit below N+k               Reduces membership churn and hidden warm-up effects.

  Sector balance         unconstrained vs minimum/maximum per sector   Policy must be point-in-time.

  Shortable lane         current broker/exchange whitelist             Cash naked-short assumptions are prohibited.
  --------------------------------------------------------------------------------------------------------------------------------------------

## 4.2 Daily eligibility gates

-   EQ/approved series, normal continuous trading, not suspended, and not forced into an incompatible auction/trade-to-trade process.

-   Current broker product and side eligibility; short availability must be explicit and may differ from long eligibility.

-   No unresolved token/symbol change, insufficient history, or warm-up gap.

-   Prior-day liquidity and spread proxy above operational floors; price and volatility within broad predeclared bounds.

-   Corporate-action and extraordinary-session flags available before the open; exclude when adjustment/auction handling is uncertain.

-   Intraday causal liquidity gate may veto a trade, but the completed day's volume cannot retrospectively add a stock to that day's universe.

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **SURVIVORSHIP AUDIT** If the available history contains only currently listed names or current broker eligibility, label every result survivorship-biased. No candidate may be promoted until listings, delistings, token changes, corporate actions and daily eligibility have adequate archival coverage.
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 5. Injectable alpha library

## 5.1 Common forecast contract

Forecast {\
strategy_id, family_id, instrument_id, decision_time,\
expected_return_bps, confidence, forecast_horizon,\
half_life, valid_until, capacity_notional, validity_flags\
}

Every alpha outputs expected return in basis points and an expiry, independent of order logic. The portfolio layer can then compare forecasts on a common economic scale, net them across families, and decline trades whose expected benefit does not clear marginal cost and uncertainty.

## 5.2 Initial families and bounded hypotheses

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Family**                 **Core causal features**                                                      **Starter knobs**                                             **Primary risks**
  -------------------------- ----------------------------------------------------------------------------- ------------------------------------------------------------- ------------------------------------------
  Cross-sectional momentum   Vol-scaled 3--120m returns; sector/market relative strength; volume/breadth   lookback, skip, rank cut, hold, cadence                       micro-reversal, crowded open, churn

  Residual momentum          Market + sector regression or trailing PCA residual sums                      factor window, residual horizon, shrinkage                    unstable betas, factor leakage

  Residual mean reversion    Robust residual z-score, half-life, liquidity/volume/event gates              2--60m residual window, entry/exit z, cooldown                new information mistaken for dislocation

  Breakout / vol expansion   Prior range, compression, volume shock, breadth and sector confirmation       range 5--90m, compression/volume thresholds                   false breaks and late fills

  Gap / open digestion       Gap vs market/sector, opening volume, opening range, peer response            gap bins, 5--60m window, continue/fade as separate families   open spread and timestamp errors

  Seasonality                Stock/sector × same time-slot returns, day/session effects                    slot width, shrinkage, minimum history                        weak effect, multiple testing

  Slow lead-lag              Index/sector/large leader lags into stock returns                             1--15m lags, residual control, horizon                        synchronous-clock artefacts

  Microstructure later       Spread, imbalance, depth change, trade sign and replenishment                 only after tick/depth archive                                 no historical queue; latency race
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 5.3 Robust normalization and combination

z\_(k,i,t) = clip\[(α\_(k,i,t) − median_i α) / (1.4826·MAD_i α + ε), −z_max, z_max\]

μ̂\_(i,t) = κ\_(regime,session) · Σ_k w\_(k,regime,session) z\_(k,i,t)

-   Always-on equal-weight and ridge-weighted ensembles are mandatory baselines.

-   Use ridge/elastic-net shrinkage, maximum family weights, and leave-one-family-out ablation.

-   Fit scalers, winsor limits, factor exposures, weights, calibrators, and regime thresholds inside each training fold.

-   Combine only forecasts evaluated on identical folds, costs, latency and capital contexts.

-   A two- or three-family ensemble advances only when its incremental net value survives ablation and cost stress.

-   Complex session/regime weights shrink toward one global weight; no small regime receives a free parameter set.

# 6. Sessions and regimes

## 6.1 Session state is an input, not an afterthought

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **State**      **Initial research window**                 **Typical hypotheses**                                             **Operational note**
  -------------- ------------------------------------------- ------------------------------------------------------------------ --------------------------------------------------
  OPEN_SHOCK     09:15--09:30                                gap continuation/reversal, opening imbalance, range expansion      Highest spread/slippage; next-event fills only.

  OPEN_DIGEST    09:30--10:30                                momentum, opening range, sector confirmation                       Separate from first 15 minutes.

  MID            10:30--14:30                                residual MR, slower lead-lag, seasonality                          Often lower spread and volatility.

  LATE_CTS       14:30 to broker/CAS cutoff                  continuation, rebalance/flow proxies                               Cut short by product-specific RMS.

  CAS            NSE F&O-eligible cash names: 15:15--15:35   auction imbalance/forced flow only with specific data/fill model   Phase 1 CAS is separate from continuous trading.

  FLATTEN_ONLY   Configurable safety buffer                  No alpha entries                                                   Independent risk layer owns exits.
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

NSE's current Closing Auction Session applies in Phase 1 to cash stocks with derivative contracts. It runs 15:15--15:35, with order entry and matching subperiods. Zerodha currently starts MIS square-off for CAS stocks at 15:12, so a normal MIS strategy cannot assume it can carry those positions into the auction. Flattrade's published cutoff material is internally inconsistent. Session eligibility must therefore be broker × product × instrument × side, snapshotted daily---not a single hard-coded time. **^\[S7\]\ \[S14\]\ \[S20\]^**

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **CLOSING RULE** Until auction-specific data, broker support, and fills are validated, treat 15:15 CAS as a separate future strategy family. Phase 1 should flatten CAS-eligible MIS exposure before the earliest broker cutoff and never rely on broker auto-square-off.
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 6.2 Regime policy

Start with two to four interpretable, causal states using index volatility percentile, cross-sectional dispersion, breadth, trend, gap, volume/liquidity and spread proxies. Percentiles and classifier parameters are training-only.

μ̂\_(i,t) = Σ_g p\_(g,t) μ̂\_(i,t,g), where p_g is a soft, trailing-data regime probability

-   Minimum independent trading days per regime; hard gates with tiny samples are rejected.

-   Every gated strategy is compared with its always-on parent on identical outer folds.

-   Add a complexity penalty for every split; prefer soft shrinkage and hysteresis to rapid on/off switching.

-   A gate advances only if incremental net value is positive in most outer folds and not driven by one event.

# 7. Bounded comprehensive search

![Hierarchical funnel from data baselines through family search, robust plateaus, ensembles, stress and final bundles.](media/image2.png){width="6.35in" height="3.175in"}

Figure 2. Search depth rises as candidate count falls; expensive nested validation is reserved for stable survivors.

## 7.1 Why not a full Cartesian product

A Cartesian product of universes, bar sizes, lookbacks, thresholds, exits, regimes, portfolio wrappers and broker settings creates millions of highly correlated trials. That is neither unbiased nor exhaustive in a meaningful sense. It mostly increases compute, selection bias and duplicated hypotheses.

Use exhaustive enumeration for small categorical choices, low-discrepancy Sobol/random sampling for continuous parameters, successive halving inside development folds, and local refinement around stable parameter plateaus. Bayesian optimization may operate only on inner-development scores; it never sees an outer test or lockbox.

## 7.2 Search stages

1.  Foundation: verify data, simulator accounting, cost schedules, universe policies, and simple session baselines.

2.  Single-family discovery: give every family equal compute, no regime gate, and a simple common portfolio wrapper.

3.  Within-family refinement: locate broad stable parameter plateaus; add exit hysteresis and forecast calibration.

4.  Cross-family combinations: test two-family pairs first; allow three-family ensembles only after ablation evidence.

5.  Session/regime gating: add to surviving always-on candidates and charge a complexity/sample-fragmentation penalty.

6.  Portfolio/broker optimization: integer holdings, no-trade bands, ticket thresholds, capital tiers, and full fees/fills.

7.  Stress and promotion: nested outer tests, latency/fill/cost stresses, multiple-test correction, correlation clustering and Pareto selection.

## 7.3 Trial identity and cache

trial_hash = SHA256(\
code_commit + data_snapshot + instrument_master + corporate_actions +\
pipeline_DAG + universe_policy + parameters + split_definition +\
cost_model + fill_model + capital + seed + runtime_versions\
)

Re-running an existing content hash returns the prior result. Failed and manually abandoned trials remain in the registry and count toward selection-bias correction. Feature nodes are cached by their own content hashes so thousands of pipelines can share the same causal transforms.

# 8. Simulator, costs and turnover

## 8.1 Event-driven fill rules

-   Signal on completed data; earliest fill after decision + broker latency.

-   Integer shares and tick-size rounding; rejected/unfilled orders leave the prior position intact.

-   Protected marketable limits as the portable default; timeout/cancel/reprice is capped and costed.

-   Partial fills, open-order exposure, cancellations, modification limits, and unknown order state are simulated.

-   Passive limit fills require quote/depth calibration; an OHLC touch is never an automatic fill.

-   Spread, impact, latency and adverse selection vary by stock, size, session and regime.

-   Circuit/price-band states, halts, missing feed, short eligibility and broker RMS are explicit.

-   An independent flatten scheduler closes before the earliest effective cutoff; broker auto-square-off is a failure path with extra charges.

Cost_order = brokerage + STT + exchange + SEBI + IPFT + stamp + GST + spread + impact + latency + adverse selection

## 8.2 Current broker/cost context

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Item**               **Flattrade**                                    **Zerodha**                                             **Model rule**
  ---------------------- ------------------------------------------------ ------------------------------------------------------- -----------------------------------------------------
  Intraday brokerage     ₹0                                               min(0.03% of turnover, ₹20) per executed order          Exact by side/order; include GST base.

  Trading API/data       Advertised free API                              Orders free; live + historical Connect ₹500/month/app   Subscription is operating cost, not per-trade cost.

  Order rate             10/sec, 40/min                                   10/sec, 400/min, 5,000/day                              Use shared token bucket below broker maximum.

  Order type             Official support: limit only                     Market request requires protection                      Portable protected limit state machine.

  Auto-square            Published material conflicts; treat as dynamic   CAS 15:12; non-CAS 15:25                                Flatten earlier; daily capability snapshot.

  Admin square-off fee   ₹50 or 0.03% + GST, lower, per executed order    ₹50 + GST per square-off order                          Count as incident cost, never baseline.
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Current cash-intraday statutory rates include sell-side STT 0.025%, NSE transaction outflow around 0.00307% per side, SEBI fee, buy-side stamp duty 0.003%, and GST on the defined fee base. Effective-dated schedules and contract-note rounding must be reproduced. NSE changed the IPFT/transaction split from 1 March 2026, while Flattrade's current public page still displays an inconsistent IPFT line; validate a real contract note before freezing production costs. **^\[S12\]\ \[S16\]\ \[S21\]^**

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **ILLUSTRATIVE HARD COST** At current published rates, a ₹1 lakh NSE buy plus ₹1 lakh same-day sell is approximately ₹35.48 at Flattrade and ₹82.68 at Zerodha before spread, impact, slippage and rounding differences. This is a model check, not a permanent tariff. **^\[S12\]\ \[S16\]\ \[S21\]^**
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

![Line chart of round-trip brokerage basis points by order notional for Zerodha and Flattrade.](media/image3.png){width="6.25in" height="2.8472222222222223in"}

Figure 3. Brokerage component only. Zerodha is 6 bps round trip below the ₹20 cap transition, then declines with ticket size; statutory and execution costs remain additional.

## 8.3 Turnover is a portfolio decision

Trade Δx_i only if expected incremental benefit \> stressed marginal cost + uncertainty buffer

-   Search rebalance cadence, entry threshold, exit hysteresis, minimum/maximum holding, cooldown and forecast expiry.

-   Set a minimum economic ticket and maximum number of concurrent names; fixed fees punish fragmentation at small capital.

-   Net opposing alpha intents before routing; batch compatible changes into one order when safe.

-   Use no-trade bands around current targets so small score changes do not churn the book.

-   Report the full net-return surface over turnover × cost stress; select the centre of a plateau, not a sharp best point.

-   Treat broker and capital as part of the experiment identity---never select gross alpha first and retrofit fees later.

# 9. Portfolio construction below ₹10 lakh

## 9.1 Cost-aware integer target

q\* = arg max_q \[ μ̂ᵀx − (λ/2)xᵀΣx − TC_b(x−x₀) − δ·TailRisk(x) \], x_i = q_i·P_i

Fixed per-order fees make the exact problem non-convex. For this capital range, use an auditable two-stage method rather than a large opaque mixed-integer solver:

1.  Solve a continuous, cost-aware target under gross/net/name/sector/beta/liquidity constraints.

2.  Drop trades below the minimum economic notional or forecast-cost buffer.

3.  Round to integer shares and tick-valid prices.

4.  Recalculate cash, margin, exposure, fees, cost and expected benefit after rounding.

5.  Run local add/drop/swap improvements; reject any portfolio that violates risk or loses positive net benefit.

## 9.2 Portfolio wrappers to compare

  -----------------------------------------------------------------------------------------------------------------------------------------------------
  **Wrapper**                     **Purpose**                                               **Small-capital caveat**
  ------------------------------- --------------------------------------------------------- -----------------------------------------------------------
  Long/flat                       Simplest execution; cap market and sector risk            Directional beta may dominate stock-selection alpha.

  Top/bottom-k                    Transparent cross-sectional spread                        Short/product eligibility and duplicate order costs bind.

  Dollar-neutral tolerance        Reduces market direction                                  Exact neutrality may require uneconomic tickets.

  Beta/sector-neutral tolerance   Targets idiosyncratic alpha                               Use soft bands; factor estimates and rounding are noisy.

  Forecast/risk optimizer         Combines calibrated forecasts with covariance and costs   Complexity must earn stable incremental value.
  -----------------------------------------------------------------------------------------------------------------------------------------------------

## 9.3 Conservative launch ranges

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **RESEARCH DEFAULTS, NOT OPTIMAL SETTINGS** Begin limited live unlevered. Search per-name caps of 5--10% NAV, maximum 5--15 concurrent positions, interval participation of 0.25--1%, and a new-entry stop 15--30 minutes before the effective flatten deadline. Leverage is a later, separately validated overlay.
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Risk limits are hard constraints, not hyperparameters optimized for return. A daily loss stop in the 0.5--1.0% NAV research range may be precommitted for pilot testing, then set through risk appetite and live evidence---not relaxed to rescue a backtest.

# 10. Validation without leakage

## 10.1 Recommended chronology

1.  Reserve the final 3--6 months or 15--20% of history as a one-use lockbox.

2.  On earlier data, use nested chronological walk-forward selection; never random rows.

3.  Fit universe policy, factor exposures, transformations, model weights, calibrators and regimes inside each training fold.

4.  Purge every training label whose return interval overlaps validation/test; embargo at least the maximum holding horizon plus live order duration.

5.  Refit only on the permitted rolling window and roll exactly at the intended live retraining cadence.

6.  Freeze the shortlist, use the lockbox once, then forward shadow/paper trade for at least 6--8 weeks.

  -----------------------------------------------------------------------------------------------------------------------------------------------
  **Layer**              **Illustrative schedule**                                **Purpose**
  ---------------------- -------------------------------------------------------- ---------------------------------------------------------------
  Training               6, 9 or 12 rolling months; longer for weak seasonality   Fit all state and parameters.

  Inner validation       1 month blocks                                           Choose parameters/graphs inside development only.

  Outer test             1 month blocks                                           Estimate the performance of the complete selection process.

  Lockbox                Final 3--6 months; one use                               Final unbiased check after bundle freeze.

  Forward shadow/paper   6--8 weeks minimum                                       Calibrate latency/fills and expose operational failure modes.
  -----------------------------------------------------------------------------------------------------------------------------------------------

## 10.2 Automated causality assertions

-   Rolling features never read timestamps after the decision cutoff.

-   Daily VWAP/volume features are cumulative through decision time, never full-day values.

-   Same-clock volume surprise compares with historical volume through the same clock slot.

-   Cross-sectional ranks exclude late/missing bars and record the actual denominator.

-   Position state cannot cross fold or session boundaries except through explicitly modelled warm-up.

-   No adjusted execution price, present-day constituent list, current-only instrument master, or current eligibility leaks into past fills.

## 10.3 Required stress grid

  ----------------------------------------------------------------------------------------------------------------------------------
  **Stress**              **Levels**                                           **Failure interpretation**
  ----------------------- ---------------------------------------------------- -----------------------------------------------------
  All-in variable costs   1.0×, 1.5×, 2.0×                                     Negative at 1.5× means fragile implementation edge.

  Decision/order delay    baseline, +1 bar, +2 bars                            Fast decay or timestamp dependence.

  Spread/impact           session × liquidity quantiles; widened tails         Cost concentration in open/close or smaller names.

  Fill                    partial, timeout, capped reprices, missed fills      OHLC-touch optimism or excessive chasing.

  Universe                N±buffer, stable-core vs dynamic, leave-sector-out   Universe cherry-pick or concentration.

  Parameters              neighbourhood heat map                               Reject isolated spikes; prefer plateaus.

  Bootstrap               day/week blocks                                      Confidence intervals and tail dependence.

  Operational             feed gap, broker reject, restart, close cutoff       Strategy must fail safe and reconcile.
  ----------------------------------------------------------------------------------------------------------------------------------

# 11. Multiple testing and robust promotion

## 11.1 Every viewed variant is a trial

The trial count includes completed, failed, abandoned, hand-tuned, alternative-universe, fee/fill, and seed variants that influenced the next decision. Preserve candidate daily returns so the effective number of independent trials can be estimated from their correlation eigenvalues.

M_eff = (Σ_j λ_j)² / Σ_j λ_j²

-   Probabilistic and Deflated Sharpe on daily net returns; do not annualize minute observations as independent.

-   Hansen SPA or White Reality Check for finalist return differentials.

-   Embargoed combinatorial/purged CV or equivalent probability-of-backtest-overfitting estimate.

-   Stationary/block bootstrap by day or week and null search simulations over the maximum selected score.

-   Family-level false-discovery control, predeclared search budgets, and one-use lockbox.

## 11.2 Hard gates before ranking

  --------------------------------------------------------------------------------------------------------------
  **Gate**         **Example precommitted requirement**
  ---------------- ---------------------------------------------------------------------------------------------
  Integrity        Accounting reconciles; no leakage; point-in-time universe and corporate actions pass audit.

  Feasibility      Current broker/product/side/session allowed; integer tickets and margin valid.

  Evidence         Adequate independent days/trades; positive net result in a majority of outer folds.

  Selection bias   DSR probability target (illustratively ≥95%) and acceptable PBO/SPA evidence.

  Cost/latency     Positive after 1.5× cost and survives +1-bar delay; 2× result disclosed.

  Stability        Neighbouring parameters and nearby universe policies support the result.

  Concentration    No single stock/day/session/regime dominates net P&L.

  Production       Rust parity, risk tests, restart/reconciliation and flatten drills pass.
  --------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **TOP FIVE IS A MAXIMUM** If fewer than three candidates clear all gates, deploy fewer. Never weaken thresholds to fill a quota, and never call five nearby parameter settings five different strategies.
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 12. Selecting and combining the top 3--5

## 12.1 Pareto selection

Final ranking is multi-objective. Use non-dominated sorting across net return, Deflated Sharpe, drawdown/CVaR, cost share, turnover/order count, fold/regime stability, broker robustness and complexity. Then cluster outer-test daily net returns using 1−correlation.

1.  Treat close hyperparameter variants as one strategy cluster.

2.  Select a stable knee-point near the centre of a parameter plateau.

3.  Add another bundle only if it contributes diversification, a distinct session, a distinct family, or broker/capital robustness.

4.  Prefer the simpler graph whenever performance confidence intervals overlap.

5.  Re-optimize combined capital allocation with fixed-order costs; five simultaneous strategies can be worse than two below ₹10 lakh.

## 12.2 Bundle report card

  --------------------------------------------------------------------------------------------------------
  **Field**       **Required content**
  --------------- ----------------------------------------------------------------------------------------
  Identity        Strategy ID/hash, family graph, parents, code/data/cost versions

  Trade context   Universe policy, session/regime, horizon, broker, capital range, side/product

  Economics       Net return, DSR, MDD, CVaR, gross-to-net, cost share, breakeven edge, rotation, orders

  Stability       Outer folds, bootstrap CI, parameter plateau, universe sensitivity, concentration

  Stress          1.5×/2× cost, +1/+2 bar delay, fill degradation, outage/restart tests

  Capacity        Minimum economic ticket, positions, participation, capital-time use

  Operations      Entry cutoff, flatten deadline, broker limits, failure modes, kill thresholds

  Decision        Promotion/rejection rationale and correlation cluster
  --------------------------------------------------------------------------------------------------------

# 13. Python research / Rust production

![Split architecture with Python research plane, signed StrategyBundle, and Rust live plane connected by golden replay parity.](media/image4.png){width="6.35in" height="3.5092104111986in"}

Figure 4. The live process contains no Python pickle or notebook state. Only a versioned bundle and validated feature/state contract cross the boundary.

## 13.1 Responsibility split

  ---------------------------------------------------------------------------------------------------------------------------------
  **Python research plane**                                        **Rust live plane**
  ---------------------------------------------------------------- ----------------------------------------------------------------
  Backfill, quality reports, immutable snapshots                   Live feed adapter, timestamp/gap checks, raw capture

  Feature research, statistical fitting, universe reconstruction   Canonical bar/feature engine and state serialization

  Event backtests, walk-forward orchestration, search registry     Forecast evaluation and session/regime state

  Multiple-test correction, Pareto selection, reports              Integer portfolio, independent risk, broker capability checks

  Bundle export and golden fixtures                                Order state, idempotency, reconciliation, recovery and flatten
  ---------------------------------------------------------------------------------------------------------------------------------

Best drift control: implement the canonical causal feature/state engine in Rust and expose it to Python for replay/fitting via a narrow binding. Acceptable alternative: a tightly specified feature DSL implemented twice, with golden vectors. The bundle loader rejects unsupported nodes, incompatible schema, missing cost/risk versions, bad checksum, or parity failure.

## 13.2 Minimum StrategyBundle schema

schema_version, strategy_id, parent_experiment_ids\
code_hash, data_hash, universe_hash, cost_hash, risk_policy_hash\
valid_from, valid_until, broker_context, capital_range\
bar_spec, feature_DAG, warmups, normalizers, factor_parameters\
alpha_weights, calibration, session_regime_policy\
portfolio_constraints, execution_policy, exit_policy\
rounding_rules, golden_fixture_hash, bundle_checksum/signature

## 13.3 Order intent contract

OrderIntent {\
idempotency_key, strategy_id, instrument_id, side, product,\
quantity, limit_price_ticks, time_in_force, expiry_time,\
expected_edge_bps, stressed_cost_bps, reason_code\
}

Never blindly retry an unknown order. Query the broker order book and positions, reconcile broker truth, and only then decide whether a new idempotent intent is needed. Cross-broker failover is blocked until the original broker state is positively reconciled.

# 14. Independent production risk

## 14.1 State machine

BOOT → AUTHENTICATED → WARMUP → READY → TRADING → RISK_ONLY → FLATTENING → FLAT\
↘ HALTED / INCIDENT_PAUSED ↗

## 14.2 Risk controls

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Layer**     **Controls**
  ------------- -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  Pre-trade     eligibility, stale/crossed data, tick/price band, stressed edge\>cost, quantity, cash/margin, name/sector/gross/net, participation, open-order exposure, rate and turnover limits

  Intraday      daily loss/drawdown, heartbeat, reject spike, slippage divergence, spread shock, abnormal feature, concentration, broker/position mismatch, market halt/circuit

  Close         new-entry cutoff, independent flatten attempts, no new risk, broker reconciliation, unresolved-position alert, closing P&L snapshot

  Release       approved bundle only, parity, capability snapshot, static IP/auth, clock sync, audit logging, rollback package
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 14.3 Failure response matrix

  ----------------------------------------------------------------------------------------------------------------------------------------------------
  **Failure**                               **Required response**
  ----------------------------------------- ----------------------------------------------------------------------------------------------------------
  Breeze/feed stale or gap                  Stop new decisions; invalidate features; cancel nonessential entries; preserve/reconcile position state.

  Feed vs broker prices diverge             Pause affected symbols/system; do not choose the price that favours a trade.

  Order timeout / unknown                   Query orders and positions; never resend blindly.

  Broker disconnect with exposure           Enter risk-only; reconnect/reconcile; controlled flatten only when state is known.

  Restart/crash                             Replay log/checkpoint, then reconcile broker truth before any new intent.

  Position mismatch                         Cancel new risk, reconcile, and require explicit resolution.

  Repeated rejects/slippage breach          Circuit-break the strategy or adapter; recalibrate offline.

  Price near circuit / liquidity collapse   No new entry; controlled exit; escalate unresolved short risk.

  Clock drift                               Halt timestamp-sensitive decisions until synchronized.

  Daily loss/kill threshold                 Cancel entries and flatten under the independent risk policy.
  ----------------------------------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **SHORT-SALE TAIL** Cash short eligibility must come from the current exchange/broker whitelist. A short trapped at an upper circuit can become a delivery/auction obligation. The simulator and live risk layer must model this as a distinct tail event, not a normal stop-loss fill. **^\[S22\]^**
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 15. Regulatory and broker operating gate

SEBI's retail-algo framework became mandatory for stockbrokers on 1 April 2026. Under NSE's implementation standards, all client-API orders are algo orders and must be tagged. At not more than 10 orders/second per exchange/segment, a self-developed retail strategy uses the registration-free/generic algo-ID route; above that threshold it must be registered through the broker. Brokers may impose lower limits. **^\[S8\]\ \[S9\]\ \[S10\]\ \[S11\]^**

  --------------------------------------------------------------------------------------------------------------------------------------------
  **Requirement**         **Blueprint control**
  ----------------------- --------------------------------------------------------------------------------------------------------------------
  Static IP               One primary plus permitted secondary; fixed-egress host; weekly change restriction; deployment blocks on mismatch.

  OPS threshold           Shared exchange/segment token bucket; target well below 10/sec; place/modify/cancel/square-off all count.

  Algo tagging            Broker onboarding confirmation and logged generic/registered algo identity for every API order.

  Authentication          OAuth/allowed mechanism, 2FA, daily session lifecycle, secrets outside bundles/logs.

  Order types             Protected limit logic; no assumption of pure algo market orders.

  Audit trail             Signal, state, intent, order, fill, config and identity retained for at least five years where required.

  Broker responsibility   Current broker capability and RMS policy is authoritative; refresh before every session.

  Data terms              Breeze raw data remains private; cross-broker execution requires ICICI approval or a licensed substitute feed.
  --------------------------------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **BEFORE ANY LIVE API ORDER** Obtain written broker confirmation of self-developed algo onboarding, algo-ID/tagging, static-IP mapping, allowed order types, rate limits, short/MIS universe, CAS handling and square-off times. Capital below ₹10 lakh does not create a separate exemption.
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 16. Staged algorithm GTM

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Phase**                  **Indicative duration**   **Deliverables**                                                                            **Exit gate**
  -------------------------- ------------------------- ------------------------------------------------------------------------------------------- ---------------------------------------------------------
  0 • Authority + protocol   1--2 weeks                ICICI data-use answer; broker/API onboarding; frozen mandate, metrics, risks, budgets       Legal/terms path and minimum credible horizon confirmed

  1 • Data foundation        3--4 weeks                raw store, point-in-time master, corporate actions, calendar, quality dashboard             sample days reconcile; gaps explicit

  2 • Costed simulator       3--5 weeks                broker fee versions, order/fill state, integer holdings, latency/fill stresses, EOD close   cash/equity accounting reconciles to rounding

  3 • Alpha baselines        4--6 weeks                family modules, causal tests, common forecasts, ablations                                   every module has net fold reports

  4 • Meta-search            5--8 weeks                typed grammar, registry, nested WFO, multiple-test controls, robust surfaces                shortlist frozen without lockbox

  5 • Portfolio + bundles    3--5 weeks                turnover optimizer, Pareto clusters, final 3--5 or fewer bundles                            hard gates and one-shot lockbox pass

  6 • Rust + shadow          4--6 weeks                bundle loader, live engine, parity, recovery, reconciliation                                golden parity and failure drills pass

  7 • Paper                  6--8 weeks min.           actual latency/fills/rejects/cost calibration; operational runbook                          no critical incident; costs inside stress bands

  8 • Limited live           evidence-driven           10--20% → 25% → 50% → approved full allocation                                              advance by sample/risk evidence, not elapsed days
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 16.1 Limited-live advancement

-   Unlevered and one champion first; challengers remain shadow-only.

-   No unintended overnight position, ambiguous order retry, or unresolved reconciliation incident.

-   Observed spread/slippage and reject/fill rates remain within approved stress bands over a predeclared trade sample.

-   Live decision parity against replay is stable; cost-to-gross and turnover match the expected range.

-   Drawdown, concentration and session/regime attribution remain inside the bundle's risk envelope.

-   Any material feature, alpha, universe, execution or risk change creates a new bundle and restarts the appropriate gate.

# 17. Concrete first research campaign

## 17.1 Pre-registered search matrix

  -----------------------------------------------------------------------------------------------------------
  **Dimension**       **Starter space**
  ------------------- ---------------------------------------------------------------------------------------
  Capital             ₹2L, ₹5L, ₹10L; 1× gross initial

  Universe            N=50/100/150/300; 20/40/60-day liquidity; weekly/monthly refresh; stable-core/dynamic

  Bar                 1, 2, 3, 5, 10, 15 minutes, subject to source fidelity

  Hold                2, 3, 5, 10, 15, 30, 60, 120 minutes; truncated before flatten

  Rebalance           1, 2, 3, 5, 10, 15 minutes

  Momentum            lookback 3/5/10/20/30/60 bars; skip 0/1/2

  Residual MR         lookback 2/3/5/10/20 bars; robust z; entry/exit/cooldown

  Breakout            range 5/10/20/30/60 bars; compression, volume, breadth confirmation

  Entry breadth       top/bottom 5%, 10%, 20% or k=3/5/8/10

  Turnover controls   cost buffer 1.0/1.25/1.5/2.0×; cooldown 0/1/2/5; minimum ticket; no-trade band

  Risk/capacity       name 5/7.5/10%; participation 0.25/0.5/1%; max 5/8/10/15 positions

  Stress              cost 1/1.5/2×; delay base/+1/+2 bars; fill degradation; nearby universes
  -----------------------------------------------------------------------------------------------------------

## 17.2 Compute budget and promotion funnel

  -----------------------------------------------------------------------------------------------------------------------------------------------------
  **Pass**    **Illustrative budget**     **Simulation fidelity**                                         **Keep rule**
  ----------- --------------------------- --------------------------------------------------------------- ---------------------------------------------
  Coarse      10k--50k unique manifests   vectorized causal returns + conservative rough cost             family-balanced stability and economic sign

  Full-cost   1k--5k                      event fills, integer shares, fees, session/broker constraints   positive development utility + plateau

  Nested      100--500                    purged inner/outer WFO, full stresses                           fold consistency, DSR/PBO, ablation

  Finalist    10--30                      complete broker/capital contexts + operational tests            hard gates + Pareto diversity

  Promoted    0--5                        lockbox once + forward shadow/paper                             release board/risk sign-off
  -----------------------------------------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **FIRST LIKELY DELIVERABLE** Not 'the winner.' The first trustworthy output is a map of where net edge survives: family × session × universe × capital × broker × turnover. That map determines which 100--500 candidates deserve the expensive validation pass.
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 18. Operating cadence after launch

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Cadence**         **Activity**                                                                                **Rule**
  ------------------- ------------------------------------------------------------------------------------------- ----------------------------------------------------------------
  Every session       capability/eligibility snapshot, auth/static IP, data health, risk limits, close schedule   No READY state unless all preflights pass.

  Intraday            forecast drift, feed age, costs, fills, rejects, exposure, drawdown, reconciliation         Throttling/pausing only; no live self-retraining.

  Daily               P&L/cost attribution, broker contract-note reconciliation, incident review                  Any unresolved position/order discrepancy blocks next session.

  Weekly              champion vs shadow challengers, parameter/state health, data gaps                           No promotion based on one week of P&L.

  Monthly/quarterly   offline retraining/search per predeclared cadence, new bundle candidate                     Full lineage and promotion path repeat.

  Incident            freeze bundle, preserve logs, reconcile, root-cause, replay                                 Restart only after explicit acceptance criteria pass.
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

## 18.1 Non-negotiable rejection list

-   Present-day constituent lists applied through history; random train/test rows; same-bar signal and fill.

-   Full-day VWAP/volume used intraday; current-only instrument/product eligibility projected backward.

-   Brokerage-only costs; optimistic passive fills from OHLC touches; guaranteed market-order assumptions.

-   Minute-level Sharpe annualized as if observations were independent.

-   Selecting on all history and renaming it out-of-sample; reusing a lockbox after tuning.

-   Ignoring failed/manual trials; unlimited grids branded as exhaustive; five clones branded as diversified.

-   Exact neutrality regardless of cost; leverage added to rescue return; broker auto-square-off as primary exit.

-   Sub-minute alpha claims without quote/trade/depth and realistic fill data.

-   Automatic live retraining, blind retry after timeout, or failover without broker-state reconciliation.

-   Breeze-derived orders at another broker without explicit ICICI permission or a licensed substitute data path.

# Appendix A --- Meta-search pseudocode

def discover(protocol):\
data = freeze_and_hash(protocol.data)\
development, lockbox = chronological_lockbox(data)\
\
outer_reports = \[\]\
for outer in purged_walk_forward(development, protocol.outer):\
trials = propose_from_typed_grammar(\
budget=protocol.fixed_budget, seed=outer.seed)\
\
for theta in trials:\
inner = \[\]\
for fold in purged_walk_forward(outer.train, protocol.inner):\
fitted = fit_all_state(theta, fold.train)\
inner.append(event_backtest(\
fitted, fold.validation, theta.broker, theta.capital))\
registry.record(theta, inner)\
\
selected = locked_inner_selection(registry, outer.id)\
refit = fit_all_state(selected, outer.train)\
outer_reports.append(event_backtest(\
refit, outer.test, selected.broker, selected.capital))\
\
shortlist = pareto_diverse_selection(outer_reports)\
bundles = freeze_bundles(shortlist)\
lockbox_reports = evaluate_once(bundles, lockbox)\
return apply_promotion_gates(bundles, lockbox_reports)

# Appendix B --- Example experiment manifest

experiment:\
protocol: intraday_discovery_v1\
data_snapshot: nse_cash_1m_2023_2026_sha256\...\
universe: {policy: liquidity_ranked, n: 100, lookback_days: 40, refresh: weekly}\
session: MID\
alpha:\
family: residual_mean_reversion\
residualizer: {factors: \[market, sector\], window_days: 60}\
z_lookback_min: 30\
entry_z: 1.75\
exit_z: 0.35\
portfolio: {wrapper: beta_sector_tolerance, max_positions: 10, name_cap: 0.10}\
execution: {policy: protected_marketable_limit, timeout_ms: 1500, max_reprices: 2}\
context: {broker: zerodha, capital_inr: 500000, costs: zerodha_2026_08_27}\
validation: {split: nested_purged_wfo_v1, seed: 1407}\
status: PROPOSED

# Appendix C --- Acceptance checklist

  -------------------------------------------------------------------------------------------------------------------------
  **Area**       **Release checklist**
  -------------- ----------------------------------------------------------------------------------------------------------
  Authority      Written Breeze cross-broker approval OR licensed substitute feed; broker algo onboarding complete.

  Data           Point-in-time instruments/corporate actions; raw/adjusted split; gaps; clock/calendar; source checksums.

  Research       Frozen grammar/budget/folds; registry includes failures; lockbox unused; daily-return statistics.

  Simulation     Next-event fills; fees/rounding; integer positions; partial/reject/timeout; circuits; close.

  Selection      Hard gates; DSR/PBO; 1.5× cost/+1 bar; plateaus; concentration; Pareto clusters.

  Bundle         Complete schema, hashes, validity, risk reference, golden fixture, checksum/signature.

  Rust           Parity, idempotency, persistence, restart, reconciliation, rate limiting, independent risk.

  Operations     Static IP/auth, data and broker health, alerts, kill/flatten, runbook, incident retention.

  Pilot          Shadow/paper evidence; actual costs; zero critical open incidents; staged unlevered capital.
  -------------------------------------------------------------------------------------------------------------------------

# Appendix D --- Primary sources and current facts

All broker, API, exchange and regulatory facts were checked against primary sources on 27 August 2026. Tariffs, limits, eligibility and square-off times can change; store effective-dated snapshots and confirm them before production use. This source register supports the current-context statements in the blueprint.

**\[S1\]** [[ICICI Direct Breeze API Reference]{.underline}](https://api.icicidirect.com/breezeapi/documents/index.html) --- rate limits, supported segments, live streams, instruments, static-IP and order restrictions

**\[S2\]** [[Official Breeze Python SDK README]{.underline}](https://github.com/Idirect-Tech/Breeze-Python-SDK/blob/main/README.md) --- historical intervals, 1,000-candle cap, unadjusted history, WebSocket and SDK behaviour

**\[S3\]** [[ICICI FAQ --- third-party platform via Breeze]{.underline}](https://www.icicidirect.com/faqs/fno/how-can-i-use-a-third-party-platform-to-trade-via-breeze-api) --- personal-use and third-party integration restriction

**\[S4\]** [[ICICI FAQ --- create and deploy self-built Breeze strategies]{.underline}](https://www.icicidirect.com/faqs/fno/how-can-i-create-and-deploy-strategies-with-breeze-api) --- private self-built deployment on the customer's computer

**\[S5\]** [[ICICI resident account terms]{.underline}](https://www.icicidirect.com/mailimages/einvest_resident_part_c_ndsl.pdf) --- individual-use quote entitlement, proprietary data interests and service disclaimers

**\[S6\]** [[NSE market timings]{.underline}](https://www.nseindia.com/static/market-data/market-timings) --- normal cash-market and exchange session timings

**\[S7\]** [[NSE Closing Auction Session]{.underline}](https://www.nseindia.com/static/products-services/closing-auction-session) --- Phase 1 eligibility, 15:15--15:35 auction phases and order/fill rules

**\[S8\]** [[SEBI --- safer participation of retail investors in algorithmic trading]{.underline}](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf) --- retail API/algo regulatory framework

**\[S9\]** [[SEBI --- final retail-algo implementation timeline]{.underline}](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf) --- mandatory framework application from 1 April 2026

**\[S10\]** [[NSE implementation standards for retail algos]{.underline}](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf) --- static IP, 10 OPS, tagging, authentication, audit and controls

**\[S11\]** [[NSE retail-algo FAQ]{.underline}](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail%20Algo_03112025_NSE.pdf) --- tech-savvy client hosting, tagging and API order classification

**\[S12\]** [[Flattrade charges]{.underline}](https://flattrade.in/charges/) --- brokerage, statutory rates and administrative square-off charges

**\[S13\]** [[Flattrade algo/API]{.underline}](https://flattrade.in/algotrading/) --- free API context and published rate limits

**\[S14\]** [[Flattrade risk-management policy]{.underline}](https://flattrade.in/assets/forms/Risk_management_policy.pdf) --- margin/RMS and time-based square-off policy; public inconsistencies noted

**\[S15\]** [[Flattrade API order types]{.underline}](https://flattrade.in/support/knowledge-base/what-types-of-orders-are-accepted-through-api/) --- limit-only API rule

**\[S16\]** [[Zerodha charges]{.underline}](https://zerodha.com/charges) --- intraday brokerage and statutory fee schedule

**\[S17\]** [[Zerodha Kite API pricing]{.underline}](https://zerodha.com/products/api) --- free personal order tier and ₹500/month live/historical Connect tier

**\[S18\]** [[Kite Connect rate limits and exceptions]{.underline}](https://kite.trade/docs/connect/v3/exceptions/) --- 10/sec, 400/min, 5,000/day and 25 modifications/order

**\[S19\]** [[Kite Connect WebSocket]{.underline}](https://kite.trade/docs/connect/v3/websocket/) --- live data fields and subscription capacity

**\[S20\]** [[Zerodha intraday auto-square-off timings]{.underline}](https://support.zerodha.com/category/trading-and-markets/trading-faqs/market-sessions/articles/intraday-auto-square-off-timings) --- CAS/non-CAS cutoffs and administrative charge

**\[S21\]** [[NSE transaction/IPFT revision effective 1 March 2026]{.underline}](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf) --- current exchange transaction and IPFT split

**\[S22\]** [[SEBI short-selling framework]{.underline}](https://www.sebi.gov.in/sebi_data/attachdocs/jan-2024/1704466451731.pdf) --- cash short-sale framework and delivery obligation context

# Closing note

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **THE CORRECT PRODUCT** A repeatable discovery machine that can say 'no strategy passed' is more valuable than a bot guaranteed to return five attractive backtests. The edge is the combination of causal data, controlled breadth, complete costs, disciplined selection, small-capital portfolio economics, and operational execution---not the number of indicators in the pipe.
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

This is an engineering and research blueprint, not investment, legal, tax or regulatory advice and not a promise of profitability. Confirm current exchange, broker, API and data-entitlement requirements before implementation and trading.
