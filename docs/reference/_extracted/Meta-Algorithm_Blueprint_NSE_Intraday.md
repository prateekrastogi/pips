**META-ALGORITHM BLUEPRINT**

Systematic discovery of cash-equity intraday strategies on the NSE

*An exhaustive, bias-controlled search over universes, alpha pipelines, turnover and broker economics --- scalping to intraday · Python research plant · Rust execution engine · no generative AI in the loop*

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Field**          **Value**
  ------------------ ---------------------------------------------------------------------------------------------------------------------------------------------------
  Prepared for       Prateek Rastogi --- personal quantitative trading program

  Version / date     1.0 · August 27, 2026

  Scope              NSE cash equity, MIS intraday (long/short), capital \< ₹10,00,000

  Data / execution   ICICI Direct Breeze API (data) · Flattrade ₹0 or Zerodha ₹20/order (execution)

  Status             Blueprint for build --- every threshold is a versioned config default

  Note               Research architecture document; not investment, legal or tax advice. Fee/regulatory facts verified Aug 2026 --- re-verify quarterly (Appendix D).
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

**Contents**

**1** Executive summary

**2** Mandate, objective function and constraints

**3** Ground truth: costs, microstructure, regulation

**4** Data plant

**5** Strategy grammar --- the injectable architecture

**6** Alpha family library --- the structural search space

**7** The meta-algorithm: a staged discovery funnel

**8** Turnover and cost optimization --- the frontier, per broker

**9** Universe discovery

**10** Portfolio construction and risk

**11** Validation protocol and statistics

**12** System architecture --- Python research plant, Rust execution engine

**13** Session and regime structure

**14** Failure modes and anti-patterns

**15** Roadmap and decision gates (research-to-market plan)

**Appendix A** Cost stack, worked to the paisa

**Appendix B** Coarse parameter grids and search-space arithmetic

**Appendix C** Metric and test definitions

**Appendix D** API facts, onboarding checklist, sources

**Appendix E** Glossary

**Appendix F** Reference library

*Figures: 1 --- system architecture (§5) · 2 --- discovery funnel (§7) · 3 --- turnover frontier per broker (§8). Key tables: cost stack (3.1, A.1), funnel gates (7.1), kill switches (10.1), runbook (12.1), roadmap (15.1), parameter grids (B.1).*

**1. Executive summary**

This document specifies a **meta-algorithm**: a research machine whose output is not one trading strategy but the **top 3--5 certified strategy pipelines** --- each with its own discovered universe, holding horizon, turnover, execution style and broker economics --- for **NSE cash-equity trading between the scalping and intraday horizons**, run on capital under ₹10 lakh, with market data from ICICI Direct\'s Breeze API, execution through Flattrade (₹0 brokerage) or Zerodha (₹20/order), research in Python and live execution in Rust. Nothing in the loop uses generative AI: every component is classical statistics, optimization and deterministic simulation, reproducible from a configuration hash plus a data-snapshot id.

The design rests on one identity. If T is how many times the capital is rotated per day (traded notional ÷ capital), ē the average gross edge per rotation and c the all-in cost per rotation, then

*daily return on capital ≈ T × (ē − c)* (bps)

Return on investment is therefore *edge × rotation*, exactly as framed in the mandate --- and both terms are endogenous. Trade more and the marginal trade is weaker (ē falls with T); hold longer and gross edge grows but rotations fall; change broker or ticket size and c moves. So \"which strategy\", \"which universe\", \"what turnover\" and even \"which broker\" are **outputs of one joint search**, not inputs chosen by taste. The meta-algorithm makes that search exhaustive at the structural level, adaptive at the parameter level, and statistically honest at the certification level.

Concretely, the machine is a **staged discovery funnel**. A pipeline grammar (§5) turns every candidate strategy into a typed, injectable configuration; ten alpha families (§6) spanning cross-sectional momentum and mean reversion, time-series trend, breakouts, gap digestion, seasonality, lead--lag, calendar events, flow proxies and pairs define the structural search space (≈20,000--60,000 coarse configurations). Stage S1 screens signals with cheap vectorized statistics; S2 re-tests survivors in cost-aware walk-forward backtests per broker; S3 stress-tests robustness; S4 applies multiple-testing-aware certification (deflated Sharpe ratio, probability of backtest overfitting, superior-predictive-ability tests, a sealed holdout); S5 assembles a low-correlation ensemble and optimizes turnover against each broker\'s cost line; S6 gates deployment through shadow trading in the Rust engine. Expect well over 95% attrition --- that is the system working, not failing.

Two hard numbers anchor everything. First, the statutory cost floor for NSE intraday equity is **≈3.5 bps per round trip** before brokerage; Zerodha\'s ₹20/order adds ≈4.7 bps at a ₹1 lakh ticket while Flattrade adds nothing, so the two brokers imply materially different optimal turnovers (§8). Second, a book rotating 5× daily on an 8 bps all-in cost line pays **≈100% of its capital in friction per year** --- the cost line, not the market, is the first adversary, and the funnel treats the cost model as a first-class input everywhere.

+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **What this blueprint commits to**                                                                                                                                                       |
|                                                                                                                                                                                          |
| Deliverable: a ranked, certified top-3--5 set of pipelines plus one ensemble, each shipped as a signed Strategy Bundle the Rust engine can load without code changes.                    |
|                                                                                                                                                                                          |
| Discipline: every trial logged to an append-only registry; final statistics deflated by the true number of trials; one sealed holdout, unlocked once per research cycle.                 |
|                                                                                                                                                                                          |
| Honesty: if nothing certifies net of the Flattrade cost line, the correct conclusion is that the cost line wins at this horizon --- the blueprint says so rather than shipping a mirage. |
+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

**2. Mandate, objective function and constraints**

**2.1 Mandate**

-   **Instruments:** NSE cash equities only (MIS product, long and short). No F&O, no overnight positions; everything squares off before the broker\'s cut-off.

-   **Horizon:** scalping (minutes) to full intraday (entry after 09:15, flat by ≈15:10). The horizon itself is a search dimension, not a prior.

-   **Capital:** \< ₹10,00,000. Intraday leverage via MIS up to \~5× on liquid names (SEBI peak-margin floor of 20% VaR+ELM), giving a maximum book of ≈₹50L; the risk system, not the broker limit, decides actual gross.

-   **Data:** ICICI Breeze API (historical 1s/1m/5m/30m/1d candles, websocket ticks and depth). **Execution:** Flattrade (₹0) or Zerodha (₹20/order) --- the search prices both.

-   **Stack:** Python for research; Rust for the live engine; bit-parity between the two enforced by golden-replay tests.

-   **Method boundary:** no generative AI anywhere. Classical ML (regularized regression, trees, isotonic calibration, meta-labeling) is permitted where flagged, and each such use is a config switch that can be disabled.

**2.2 The objective, formalized**

Let K be capital, and for day d let each executed round trip j have notional s_j, gross edge e_j (bps) and all-in cost c_j (bps). The day\'s return on capital is

*R_d = Σ_j s_j (e_j − c_j) / (10⁴ · K) = T_d × (ē_d − c̄\_d) / 10⁴*

with T_d = Σ_j s_j / K the day\'s rotation count. The program is:

*maximize E\[R_d\] subject to σ(R_d) ≤ σ\*, MDD ≤ D\*, gross ≤ L·K, participation ≤ p\*·ADV, orders/day ≤ O\*, flat by 15:10*

Risk enters as a **constraint, not a preference**: target daily volatility σ\* (initially 0.8--1.2% of capital), a drawdown budget D\* (10--12%), leverage L ≤ 4 (buffer under the 5× MIS ceiling), per-interval participation p\* ≤ 10% of traded value, and an order budget O\* set by the SEBI order-per-second threshold and broker daily caps (§3.3--3.4). Sharpe and Calmar are certification statistics; E\[R\] is what is maximized once constraints bind.

The decisive point: **ē is a function of T and of the holding period h** (edge decays as marginal signals are admitted and as holding stretches), and **c is a function of broker, ticket size and aggression**. Optimal turnover is therefore an interior optimum that differs by broker --- §8 derives it and Figure 3 shows it.

**2.3 Why turnover is the lever --- and the tax**

With breadth N names and independent-ish bets, the fundamental law of active management says gross information ratio scales like IC·√(number of bets). A modest rank-IC of 0.02 across 100 names rebalanced 4× a day gives naively √(100×4×250) ≈ 316 bets\^½ → gross IR ≈ 6; after an honest effective-breadth haircut (sector correlation, signal autocorrelation --- divide by 4--8) it is still IR ≈ 2--3 *before costs*. That is the prize of breadth × rotation. The tax is the friction table below: the same rotation multiplies the cost line. Both faces of turnover are priced explicitly in every backtest.

  ---------------------------------------------------------------------------------------------------------------------------------------------
  **Rotation T (×capital/day)**   **Annual friction @ c = 8 bps (Flattrade all-in)**   **Annual friction @ c = 12 bps (Zerodha, ₹1L ticket)**
  ------------------------------- ---------------------------------------------------- --------------------------------------------------------
  1×                              ≈ 20% of capital                                     ≈ 30% of capital

  2×                              ≈ 40%                                                ≈ 60%

  3×                              ≈ 60%                                                ≈ 90%

  5×                              ≈ 100%                                               ≈ 150%

  8×                              ≈ 160%                                               ≈ 240%
  ---------------------------------------------------------------------------------------------------------------------------------------------

*Table 2.1 --- Friction as a % of capital per year (250 sessions), fees + typical spread/impact. Edges must clear this before a rupee is earned.*

**3. Ground truth: costs, microstructure, regulation**

*Everything below is a hard input to the search. Rates verified August 2026 against broker schedules; re-verify quarterly and at every Union Budget --- the cost model is versioned like code (§8.6).*

**3.1 The cost stack**

Statutory charges are identical at both brokers for intraday equity: STT 0.025% on the sell side, NSE transaction charge 0.00307% per side, SEBI fee ₹10/crore per side, stamp duty 0.003% on the buy side, GST 18% on (brokerage + transaction + SEBI). There are no DP charges intraday. On a ₹1,00,000 round trip this sums to **₹35.5 ≈ 3.55 bps**. Brokerage then separates the brokers: Flattrade adds zero; Zerodha adds min(0.03%, ₹20) per executed order plus GST --- a *fixed* rupee amount above ₹66,667/ticket, which is why its bps cost falls with ticket size.

  --------------------------------------------------------------------------------------------------------------------------
  **Ticket size (per side)**   **Flattrade --- fees RT (bps)**   **Zerodha --- fees RT (bps)**   **Zerodha premium (bps)**
  ---------------------------- --------------------------------- ------------------------------- ---------------------------
  ₹25,000                      3.55                              10.63                           +7.08

  ₹50,000                      3.55                              10.63                           +7.08

  ₹1,00,000                    3.55                              8.27                            +4.72

  ₹2,00,000                    3.55                              5.91                            +2.36

  ₹5,00,000                    3.55                              4.49                            +0.94
  --------------------------------------------------------------------------------------------------------------------------

*Table 3.1 --- Fees-only round-trip cost. Below ₹66,667 Zerodha\'s 0.03%/side binds (constant 7.08 bps incl. GST); above it, ₹20/side amortizes. Worked paise-level derivation in Appendix A.*

Fees are not the whole cost. Crossing the spread twice adds 2× half-spread (top-100 NSE names: median half-spread ≈1--3 bps in continuous trading); market impact at our ticket sizes in ₹100cr+ ADV names is ≈0--3 bps if participation stays below \~10% of interval volume. Planning numbers used until live TCA recalibrates them (§8.6): **Flattrade all-in ≈ 6--12 bps per round trip aggressive-aggressive; Zerodha ≈ 11--17 bps at ₹1L tickets.** Passive fills rebate spread but add adverse selection and non-fill risk --- modeled only at fill-model tier B and beyond (§11.2).

**3.2 Microstructure constraints that shape the universe**

-   **Tick size:** ₹0.01 for stocks priced below ₹250 (NSE, since June 2024), ₹0.05 at and above. Relative tick = tick/price is a universe filter: a ₹260 stock has a 1.9 bps minimum increment --- material for scalps; a ₹80 stock has 1.25 bps. Filter: relative tick ≤ 2.5 bps for sub-30-minute families.

-   **Sessions:** pre-open 09:00--09:08 (call auction), continuous 09:15--15:30. First seconds after open show unstable quotes --- families opt in per session bucket (§13). Closing session and block windows are excluded from fills.

-   **Circuits & surveillance:** 5/10/20% price bands, ASM/GSM surveillance lists (higher margins, MIS often blocked) and T2T-segment stocks (intraday prohibited) are excluded point-in-time; the lists churn, so they are ingested daily (§4.3).

-   **MIS mechanics:** intraday shorts are fine (no borrow); brokers publish per-stock MIS eligibility and leverage; auto square-off runs ≈15:15--15:26 and costs ₹50+GST per position --- the engine squares off itself by 15:05--15:12 (randomized) to avoid both the charge and the crowd.

**3.3 Regulatory envelope for a self-run algo (SEBI framework, in force)**

SEBI\'s retail algorithmic-trading framework (circular of Feb 2025; fully enforced across brokers since April 1, 2026) governs this system directly. The operative rules: API orders are tagged with an exchange-assigned **Algo-ID** by the broker; a self-run strategy staying **below \~10 orders per second** is treated as a regular API user and needs no exchange registration of the strategy; API keys must be bound to a **static IP**; authentication is OAuth/2FA with daily session tokens. A third-party or distributed black-box algo would trigger registration and research-analyst requirements --- irrelevant here as long as the system remains self-run and white-box.

+---------------------------------------------------------------------------------------------------------------------------+
| **Engine-level compliance guarantees (built in, §12)**                                                                    |
|                                                                                                                           |
| Global order-rate governor capped at 5 orders/second (half the threshold), per-symbol throttle 2/s.                       |
|                                                                                                                           |
| Deployment on a fixed-IP VPS; keys bound to that IP; daily token bootstrap with alerting.                                 |
|                                                                                                                           |
| Append-only order/audit journal reconciled to broker logs at EOD.                                                         |
|                                                                                                                           |
| Order budget respected as an optimizer constraint, so research never certifies a strategy the engine may not legally run. |
+---------------------------------------------------------------------------------------------------------------------------+

**3.4 Broker & API constraint matrix**

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Constraint**               **Flattrade**                                     **Zerodha (Kite)**                                       **Breeze (data role)**
  ---------------------------- ------------------------------------------------- -------------------------------------------------------- ------------------------------------------------------------------------------
  Brokerage, intraday equity   ₹0                                                min(0.03%, ₹20)/order + GST                              n/a (data only)

  API cost                     Free                                              Free for personal use (paid tiers exist for platforms)   Free with ICICI account

  Order rate / caps            Verify at onboarding; assume exchange OPS norms   \~10 req/s; per-day order cap (≈3k) --- verify current   10 orders/s (unused --- no market orders permitted)

  Historical data              ---                                               add-on (not needed)                                      1s/1m/5m/30m/1d candles, ≤1,000 candles/call, 100 calls/min, 5,000 calls/day

  Live streams                 WS quotes/orders                                  WS quotes/orders (backup feed)                           WS ticks, depth, 1s/1m OHLC streams; daily session token

  MIS square-off               ≈15:15--15:20; ₹50+GST if auto                    from ≈15:20; ₹50+GST if auto                             ---
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

*Table 3.2 --- Operating constraints the optimizer and engine must respect. Items marked \"verify\" are captured in the onboarding checklist (Appendix D) --- caps drift.*

**3.5 Capacity sanity check**

At ₹10L capital and 4× gross, a 50-name book runs ₹2,00,000 tickets. Against top-100 names turning over ₹100--2,000 crore/day, that is ≤0.02% of ADV --- **capacity is a non-issue at this size**. The binding constraints are the cost line, the order budget, and statistical discipline; the search is designed around those, not around market footprint. (This also means backtest fills can be modeled credibly --- the strategy does not move these markets.)

**4. Data plant**

**4.1 What Breeze provides and how it is used**

Breeze supplies historical candles via get_historical_data_v2 at 1-second, 1-minute, 5-minute, 30-minute and daily granularity (≤1,000 candles per call), and websocket streams for ticks, quotes/depth and live OHLC bars. Data is *not* corporate-action adjusted --- adjustment is applied in-house from a corporate-actions table so that raw and adjusted series are both retained. Note the API\'s own budget: **100 calls/minute and 5,000 calls/day**; the backfill plan below is designed inside it, reserving ≈500 calls/day for operations.

**4.2 Backfill arithmetic (the part everyone skips)**

One trading day is 375 one-minute candles or ≈22,500 one-second candles. At 1,000 candles/call and 4,500 calls/day of budget, history acquisition is a scheduled campaign, not an afternoon script:

  ---------------------------------------------------------------------------------------------------------------------------
  **Dataset**                        **Scope**                       **Calls required**      **Elapsed at 4,500 calls/day**
  ---------------------------------- ------------------------------- ----------------------- --------------------------------
  1-minute, 5 years                  Universe U200                   ≈ 92,000                ≈ 3 weeks

  1-minute, 5 years                  extend to U500 (optional)       ≈ 230,000               ≈ 7--8 weeks

  1-second, 6 months                 U50 (scalping tier, priority)   ≈ 141,000               ≈ 4--5 weeks

  1-second, 1 year                   U100 (background job)           ≈ 564,000               ≈ 4 months

  Ticks + depth + 1s bars, forward   full universe from day 1        0 (websocket capture)   continuous
  ---------------------------------------------------------------------------------------------------------------------------

*Table 4.1 --- Backfill plan under Breeze rate limits. Forward websocket capture starts on day one so the scalping tier accumulates its own high-fidelity history regardless of backfill pace.*

Research sequencing follows the data: families needing only 1-minute bars (horizons ≥ 15--30 min) start after week 3; sub-5-minute families wait for the 1-second tier and forward capture to mature. This ordering is baked into the roadmap (§15).

**4.3 Storage, point-in-time tables, and the feature store**

-   **Bars & ticks:** Parquet partitioned by (granularity, symbol, month), queried by Polars/DuckDB lazy scans. Raw immutable; adjusted views derived. Every research dataset version gets a content hash; experiments pin the snapshot id.

-   **Point-in-time (PIT) tables, snapshotted daily:** symbol master (ISIN ↔ ticker history), index constituents, ASM/GSM/T2T lists, broker MIS-eligibility and leverage lists, circuit bands, corporate actions, earnings calendar, index-rebalance announcements, exchange holidays/expiry calendar. Universe construction (§9) reads only what was knowable on the as-of date; delisted names stay in the store to kill survivorship bias.

-   **Feature store:** rolling statistics precomputed once per bar (returns over standard windows, realized vol, RVOL, VWAP distance, ranges, betas to index/sector) so S1 evaluates a signal as a cheap panel join instead of recomputing windows per config.

**4.4 Quality gates (run nightly; failures quarantine the day)**

-   OHLC ordering and non-negative volume; bar-count vs exchange calendar (gap detection); spike/decimal-shift detection; cross-check of splits/bonuses against the CA table; duplicate and late-tick policy for the WS capture.

-   **Timestamp convention test:** verify empirically whether Breeze labels candles by open or close time (classic lookahead bug). The bar-builder spec (§12.4) fixes the convention: a bar timestamped t is usable at t + Δ only, Δ = bar length; a unit test with shuffled future data guards every feature.

-   Session boundaries: drop pre-open prints from continuous-session features; flag auction-adjacent bars; expiry-day and event-day flags joined from the calendar tables.

**5. Strategy grammar --- the injectable architecture**

*The search can only be exhaustive and unbiased if every candidate strategy is a point in one well-defined space. The grammar is that space.*

**5.1 Pipeline algebra**

Every strategy is a typed pipeline

*P = ⟨ U, B, F, R, A, C, Π, X, K ⟩*

read as: **U**niverse (§9) → **B**ar/sampling scheme (1s/1m/5m, session buckets) → **F**eature set (from the feature store) → **R**esidualizer (none \| market \| market+sector \| statistical factors via PCA) → **A**lpha set (one or more family plugins, §6) → **C**ombiner (weights across alphas) → **Π** portfolio constructor (§10) → e**X**ecution policy (taker / passive-with-timeout; slicing) → ris**K** overlay (limits, session mask, kill switches). Each stage is a plugin behind a fixed interface; a pipeline is fully described by a YAML config; the config canonicalized and hashed (SHA-256) is the experiment\'s identity everywhere --- registry, backtests, bundles, live logs.

**5.2 The plugin contract**

A stage plugin declares: id, version, a typed parameter schema (with the coarse grid and the refinement range for every parameter), warmup (bars needed before first output), horizon (for purge/embargo computation), declared data dependencies (granularity, features), and a pure compute(view) → scores function. The framework hands plugins an **as-of view** that physically cannot address future rows --- lookahead is prevented by construction, then re-checked by shuffled-future tests. Determinism is mandatory: same config + same snapshot ⇒ identical output bit-for-bit.

**5.3 The Strategy Bundle --- research-to-production interface**

Research does not deploy code; it deploys a **bundle**: pipeline.yaml (structure + frozen parameters), the universe file, calibration tables (signal→expected-edge curve g(s), thresholds τ, no-trade bands), risk limits, cost-model id, session mask, data requirements, git SHA of the research code, and the bundle hash, signed. The Rust engine loads bundles read-only and refuses anything unsigned or schema-incompatible. **Injecting a new strategy is therefore a data operation, not an engine release** --- the engine implements stage primitives, not strategies.

**5.4 Experiment registry**

An append-only store (SQLite → Postgres when convenient) with one row per evaluation: config hash, stage reached, data-snapshot id, universe id, cost-model id, seed, metrics JSON, trade count, timestamps, git SHA. Three consumers: (i) the funnel\'s promotion logic; (ii) the **global trial count N** that deflates every Sharpe ratio at S4 --- the registry is what makes \"exhaustive search\" statistically survivable; (iii) audit --- any number in any report reproduces from hash + snapshot.

**5.5 Injection playbook (adding alpha #11 later)**

-   Write the plugin (≈100--300 lines): schema + hypothesis paragraph (one paragraph of economic rationale --- **mandatory**; no rationale, no promotion) + compute().

-   Register it in the family manifest with its coarse grid. The nightly research run picks it up automatically: S1 next night, S2+ as it earns promotion. No other code changes.

-   Certification treats it like every sibling: its trials increment N, its statistics are deflated accordingly, and it can only displace an incumbent through the champion--challenger rule (§12.7).

![](media/68a27079349c015d76c03b164eac29df0d672b8a.png){width="6.197916666666667in" height="4.3125in"}

*Figure 1 --- The two plants and the bundle interface between them. The TCA loop closes the system: realized costs recalibrate the cost model, which re-prices optimal turnover and even broker choice.*

**6. Alpha family library --- the structural search space**

*Ten families adapted to NSE cash intraday. Each subsection states the hypothesis, the signal skeleton, and what the family is sensitive to; Appendix B carries the full parameter grids. Families are plugins --- the list is designed to be extended, not worshipped.*

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **\#**   **Family**                       **Core signal**                                                **Horizon**     **Data**         **Cost sensitivity**   **Session affinity**
  -------- -------------------------------- -------------------------------------------------------------- --------------- ---------------- ---------------------- ----------------------
  F1       Cross-sectional momentum         ranked multi-window relative strength, residualized            30m -- EOD      1m               medium                 post-open, mid

  F2       Cross-sectional mean reversion   z-score of residual return, fade extremes                      5m -- 2h        1m (1s better)   high                   all; strongest mid

  F3       Time-series momentum             own normalized multi-window trend                              1h -- EOD       1m               low--medium            post-10:00

  F4       Breakout / range expansion       opening-range & compression breakouts, volume-confirmed        30m -- EOD      1m               medium                 open, post-open

  F5       Overnight-gap digestion          conditional continuation/fade of the gap                       first 30--90m   1m + daily       medium                 open

  F6       Intraday seasonality             time-of-day drift/reversion conditioned on state               15m -- 2h       1m               medium                 open & close

  F7       Lead--lag                        index/leader move → laggard constituents                       1m -- 30m       1s               very high              all

  F8       Calendar events                  earnings-day, expiry-day, rebalance-day conditional patterns   30m -- EOD      1m + calendars   low                    event days

  F9       Flow/volume proxies              signed intrabar volume, VWAP deviation, RVOL gates             5m -- 1h        1s (ticks fwd)   high                   all

  F10      Intraday pairs / spreads         z of hedge-ratio spread within sector cliques                  15m -- EOD      1m               high (two legs)        mid
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

*Table 6.1 --- Family overview. \"Cost sensitivity\" = how quickly the edge dies as the all-in cost line rises; it predicts which broker/turnover region each family will certify in.*

**F1 --- Cross-sectional intraday momentum**

*Hypothesis:* information diffuses across the tape over tens of minutes; intraday relative winners keep outperforming relative losers after controlling for market and sector moves. *Signal:* z-scored returns over windows {15, 30, 60, 120 min}, combined with weights w, optionally gated by relative volume; residualized against market/sector (§F-residualization below); long top decile, short bottom decile, rebalanced every 15--60 min. Watch for reversal contamination at the shortest windows --- the IC-decay curve from S1 decides where momentum ends and reversion begins for this market.

**F2 --- Cross-sectional mean reversion on residuals**

*Hypothesis:* liquidity shocks displace single names from their factor-implied path; absent news, displacement decays within minutes to hours. *Signal:* regress each name\'s bar return on market and sector returns (rolling betas); accumulate residuals over a window W; fade z(ε) beyond a threshold, exit on half-life decay, z→0, or a stop. Conditioning that historically separates alpha from adverse selection: skip names with volume surprise or gap flags (proxy for real news), require spread ≤ its own median (avoid fading a widening market). This family is the natural high-turnover workhorse and the most cost-sensitive after F7 --- it is where the Flattrade-vs-Zerodha frontier gap (Fig. 3) is widest.

**F3 --- Time-series momentum**

*Hypothesis:* each name\'s own trend persists intraday once established, especially after the open\'s noise settles. *Signal:* sign/magnitude of vol-normalized returns over {30m, 1h, 2h, day-anchored}; enter above threshold, exit on reversal or EOD. Combined multi-window version: TS_i = Σ w_k·m_k. Low turnover per name; portfolio breadth restores rotation.

**F4 --- Breakout / range expansion**

*Hypothesis:* escape from an established range with volume marks regime change in that name; continuation exceeds false-break cost when compression preceded the break. *Signal:* opening-range breakout (OR of first {15,30,60} min), or intraday compression breakouts (rolling range percentile \< q_low, then close beyond band × k with RVOL \> r). Structural stop at the range\'s far edge gives the family a defined risk unit --- sizing uses it. Distinguishing continuation from liquidity-sweep reversal is exactly what conditioning features (breadth of sector confirmation, imbalance proxy F9) are for; the funnel tests them jointly.

**F5 --- Overnight-gap digestion**

*Hypothesis:* the open mis-prices overnight information in predictable, state-dependent ways: small gaps against the trend fade; large gaps with sector confirmation continue. *Signal:* condition E\[R_intraday\] on gap size (in ATR units), market-relative gap, sector-relative gap, RVOL at open, and earnings-day flag; trade the first 30--90 minutes with a time stop. The conditional table is estimated, not assumed --- \"fade every gap\" is precisely the retail version this family exists to beat.

**F6 --- Intraday seasonality**

*Hypothesis:* the Indian cash session has stable time-of-day structure --- open volatility burst, midday reversion drift, close-driven flows --- which conditions the other families and carries a small standalone edge. *Signal:* time-of-day fixed effects on returns/vol/volume estimated per liquidity bucket with shrinkage across names; conditional versions (e.g., E\[R_close-window \| morning move, RVOL\]) are where the real content is. Also supplies the session masks other families search over (§13).

**F7 --- Lead--lag**

*Hypothesis:* index moves and sector leaders propagate to laggard constituents over seconds-to-minutes. *Signal:* regression of laggard forward returns on leader/index contemporaneous returns; trade laggards when the leader composite moves \> θ and the laggard hasn\'t. Needs the 1-second tier and lives closest to the cost line --- it will only certify on the zero-brokerage line, if at all; treat as an option on the forward tick capture, not a pillar.

**F8 --- Calendar events**

*Hypothesis:* known-in-advance events (earnings dates, derivative expiry, index-rebalance effective dates, ex-dates) create crowded, partly-forced flows with conditional structure. *Signals:* earnings-day post-open drift conditioned on gap direction and first-30-min range; expiry-day basket pressure around 14:30--15:20; announced index add/delete drift into effective date (flow = weight change × tracking AUM vs ADV). All information is calendar + prices/volumes --- no news text, keeping the no-genAI boundary clean.

**F9 --- Flow / volume proxies**

*Hypothesis:* who is hitting matters; even bar data betrays it. *Signals:* up-tick vs down-tick volume split from 1s bars (tick-rule signed volume once forward tick capture matures), close-location-value inside bar ranges, VWAP-deviation with RVOL context (institutional-execution footprints mean stretched VWAP deviation reverts differently on high vs low RVOL). Used both standalone (5m--1h reversion/continuation) and as a conditioning layer improving F2/F4 entries --- the grammar lets a family be a *feature supplier* to another family\'s pipeline.

**F10 --- Intraday pairs / sector spreads**

*Hypothesis:* tightly related names (same sector/owner/product) mean-revert against each other intraday even when the sector trends. *Signal:* rolling hedge-ratio spread (OLS or Kalman) within pre-registered sector cliques (banks, IT, autos, NBFCs...); enter \|z\| \> 2, exit z ≈ 0 or EOD. Two-legged costs double the hurdle: viable mainly on the ₹0 line with tickets ≥ ₹1L per leg. Cliques are frozen ex-ante to avoid data-mined pairings.

+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **Residualization (shared infrastructure)**                                                                                                                                                                                                                                                                                                                                                                                             |
|                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| F1, F2, F7 and F10 consume residual returns: r_i − β_M·r_M − β_S·r_S with betas from rolling 60-day daily + intraday shrinkage, or PCA factors (first 3--5 components on the universe\'s bar returns). The residualizer is one plugin slot with options {none, market, market+sector, PCA-k}; the funnel searches it like any other axis, so \"does residualization pay after costs?\" is answered empirically per family, not assumed. |
+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

**Explicitly out of scope** (cash-only mandate, infrastructure realism): options families (volatility RV, dispersion), sub-second microstructure/market-making (queue games the SEBI OPS ceiling and colocation economics preclude), and anything needing news text. The grammar accepts them later without redesign if the mandate widens.

**7. The meta-algorithm: a staged discovery funnel**

*Exhaustive at the structural layer, adaptive at the parameter layer, priced for multiplicity at the certification layer. Compute is spent where information per rupee of compute is highest.*

The funnel exists because the two naive alternatives both fail. Backtesting every configuration end-to-end is computationally absurd and statistically suicidal (millions of trials destroy any Sharpe you find); hand-picking a few ideas is biased and incomplete --- the opposite of the mandate. The funnel screens cheaply and universally first, then concentrates expensive, honest simulation on survivors, while the registry counts every look at the data so the final statistics can pay for all of them.

![](media/431b1f844bd375f7350141ce659c856dccd82d15.png){width="6.0in" height="3.5in"}

*Figure 2 --- The discovery funnel. Survivor counts are illustrative targets for the first full cycle; the gates, not the counts, are the specification.*

**7.1 Stage definitions and promotion gates**

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Stage**                      **Question answered**                   **Method**                                                                                                                                           **Promotion gate (initial defaults)**
  ------------------------------ --------------------------------------- ---------------------------------------------------------------------------------------------------------------------------------------------------- ------------------------------------------------------------------------------------------------------------------------------
  S0 Search-space definition     What is a candidate?                    grammar enumeration: ≈1,000 coarse structures × 4 universes × 4 session masks (Appendix B)                                                           well-formed config; data budget satisfied; hypothesis paragraph present

  S1 Signal screen               Is there any predictive content?        vectorized panel stats on train span: rank-IC by horizon, Newey--West t, IC half-life, quantile monotonicity, coverage                               \|t(rank-IC)\| ≥ 3 on train; IC half-life within 0.5--2× target horizon; coverage ≥ 60% of days; monotone quantiles

  S2 Cost-aware walk-forward     Does it survive costs as a portfolio?   standardized construction; walk-forward (train 126d / test 21d, purge = horizon, embargo = 1d); event-driven fills tier A; both broker cost models   net SR ≥ 1.5 (Flattrade line) or ≥ 1.0 (Zerodha line); ≥ 400 test trades; maxDD within budget; order counts within §3.4 caps

  S3 Robustness battery          Is it a plateau or a needle?            ±20--30% parameter perturbation; universe swap U100↔U200 and random 20% name drop; start-date jitter; cost ×1.5; drop-best-month; regime slices      median perturbed net SR ≥ 70% of center; no slice with catastrophic loss; sign stable across years

  S4 Statistical certification   Is it real after N trials?              DSR with registry-wide N; PBO via CPCV (16 blocks); SPA vs the tried family; then single-use sealed holdout (latest 6 months)                        DSR ≥ 0.95; PBO ≤ 0.25; SPA p ≤ 0.10; holdout net SR ≥ 0.6 × walk-forward SR

  S5 Ensemble & turnover         What do we actually run?                greedy selection with correlation penalty; ERC weights; combined-blotter netting; re-optimize τ\*, h\* per broker (§8)                               pairwise PnL corr ≤ 0.5; ensemble net SR ≥ max individual; every member adds marginal SR

  S6 Shadow & ramp               Does live match sim?                    4--6 weeks paper via the Rust engine on live data; implementation-shortfall decomposition; then staged capital                                       shortfall ≤ 30% of gross edge; fill-rate and slippage inside model bands; zero compliance/ops incidents
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

*Table 7.1 --- The funnel specification. Gates are versioned constants in config --- tightening them later is a config change, and the registry records which gate-version certified which pipeline.*

**7.2 Search mechanics**

-   **Structural axes (family, residualizer, universe, session mask):** exhaustive enumeration --- this is affordable precisely because S1 is vectorized and cheap.

-   **Continuous parameters:** coarse grid at S1 (Appendix B); Bayesian refinement (Optuna/TPE, 30--60 trials) only for structures promoted to S2, run against the *vectorized* engine, with the event-driven engine confirming finalists. Every TPE trial is still a registry row --- refinement is not free statistically and is counted.

-   **Final parameters = plateau centroid, never argmax.** The chosen point is the center of the widest parameter region whose perturbed performance stays within 30% of peak --- a structural defense against needle-fitting.

-   **Horizon grid is evaluated inside S1** (the IC-decay curve prices every horizon at once), so \"scalping vs intraday\" is not branched a priori: each family\'s natural horizon emerges from where its IC half-life and the cost line intersect (§8).

**7.3 Multiplicity accounting --- the license to search exhaustively**

Every evaluated config increments the registry\'s trial count N (S1 screens count with a discount factor since gates there are weak filters on correlated trials; S2+ counts fully --- the convention is fixed ex-ante and recorded). At S4, the observed Sharpe of a candidate is deflated by the expected maximum Sharpe of N correlated trials (Bailey--López de Prado); CPCV estimates the probability that the in-sample winner underperforms out-of-sample (PBO); an SPA-style bootstrap asks whether the candidate beats the whole tried family, not a cherry-picked benchmark. Formulas in Appendix C. The sealed holdout --- the most recent six months, physically excluded from every earlier stage --- is opened once per research cycle, and each unlock is a logged event. **This machinery is what lets the search be exhaustive without the results being fiction.**

**7.4 Compute budget (single 16-core workstation, first full cycle)**

  ----------------------------------------------------------------------------------------------------------------
  **Stage**                 **Evaluations**              **Unit cost**                    **Wall-clock**
  ------------------------- ---------------------------- -------------------------------- ------------------------
  S1                        20k--60k signal evals        0.5--3 s (feature-store joins)   ≈ 1--2 days

  S2 vectorized + TPE       ≈ 5k--15k trials             5--20 s                          ≈ 1--2 days

  S2 event-driven confirm   300--600 walk-forwards       2--5 min                         ≈ 1--2 days

  S3 battery                ≈ 60 configs × 30 variants   ≈ 2 min                          ≈ 2--3 days

  S4 CPCV + bootstraps      10--15 configs               hours total (vectorized)         ≈ 1 day

  Full first cycle          ---                          ---                              ≈ 1.5--2 weeks compute
  ----------------------------------------------------------------------------------------------------------------

*Table 7.2 --- Order-of-magnitude compute plan. Nightly incremental runs (new day of data, drift checks, challenger evals) fit in hours; a full re-search runs quarterly.*

**7.5 What the funnel emits**

For each certified pipeline: the signed Strategy Bundle; a certification dossier (all gate values, DSR/PBO/SPA numbers, N at certification, holdout result, robustness heatmaps); expected operating envelope (net SR confidence band, expected daily turnover and order counts per broker, capacity ceiling); and the monitoring spec --- the exact statistics whose live breach de-risks it (§12.7). The **top-3--5 report** ranks certified pipelines by expected E\[R\] at the risk target on each broker\'s cost line, and ships alongside **one ensemble bundle** --- in expectation the ensemble, not any single pipeline, is what runs at full weight.

**8. Turnover and cost optimization --- the frontier, per broker**

*Turnover is not a style choice. It is the solution to an optimization whose inputs are the edge-decay curve and the cost line --- measured, then solved, then re-measured live.*

**8.1 Optimal holding period: the rotation condition**

Let α(h) be the gross edge (bps) a signal family delivers over holding period h, estimated from S1\'s IC-decay curve; let c be the all-in round-trip cost. Rotating capital repeatedly, the value rate is

*ρ(h) = ( α(h) − c ) / h → maximize over h; first-order condition α′(h\*) = ρ(h\*)*

Hold until the *marginal* edge accrual rate falls to the *average* net rate. For the canonical concave decay α(h) = a·h\^γ (γ\<1):

*h\* = \[ c / (a(1−γ)) \]\^(1/γ), net edge per trade at optimum = c·γ/(1−γ)*

Two consequences worth memorizing. With square-root decay (γ = ½), the optimum implies **gross edge ≈ 2× cost per round trip** --- a clean screening heuristic: a setup whose expected gross edge is under twice the all-in cost line is not worth executing even when it is \"real\". And h\* scales like (c/a)²: cutting cost from 12 bps to 8 bps shrinks the optimal holding by ≈55% and raises rotation correspondingly --- **the broker changes the strategy you should run, not just its profitability.**

**8.2 Optimal selectivity: the threshold condition**

Within a horizon, the calibration curve g(s) = E\[r_h \| signal = s\] (isotonic or binned fit on train data) converts scores into expected edge. Trade only where \|g(s)\| \> c + λ·σ_trade (λ prices risk aversion on the marginal trade). Sweeping the threshold τ maps out n(τ) trades/day and ē(τ) average edge; daily net = n·(ē − c) is concave in n, and its peak --- the same marginal condition, *expected edge of the last trade admitted equals the cost line* --- sets optimal turnover T\*. Figure 3 shows the frontier for one illustrative edge-decay curve under both brokers\' cost lines:

![](media/ba7123f99964eea739f9a2ec181334c8e815c538.png){width="6.197916666666667in" height="3.71875in"}

*Figure 3 --- Same alpha, two cost lines. Zero brokerage roughly triples the optimal rotation and doubles the attainable net edge in this illustration; past the optimum, additional turnover is pure friction. All parameters are re-estimated from own data in S5.*

**8.3 What this implies at our ticket sizes**

-   Below ₹66,667/ticket Zerodha\'s percentage brokerage makes high-frequency families strictly worse there; breadth strategies with 40--60 small tickets (₹50k--1L) --- exactly the cross-sectional families --- should certify materially better on the ₹0 line. Expect the funnel to output **Flattrade as primary execution venue for F2/F7/F9-style pipelines**, with Zerodha competitive for low-rotation, larger-ticket pipelines (F3/F4/F8) --- subject to live fill quality (§8.5).

-   Sub-5-minute scalping must clear ≈2× (all-in cost) ≈ 12--24 bps gross per trade depending on venue and spread --- a high bar that most known cash-equity anomalies fail; the funnel will likely concentrate certified turnover in the **15-minute--2-hour band**, i.e., portfolio rotation ≈ 2--8× capital/day. That is a prediction, not an assumption --- the machinery is exactly what tests it.

**8.4 Order-budget constraints close the frontier**

Turnover optimization runs under hard caps: the engine\'s 5 orders/second governor (SEBI headroom), any broker per-day order cap (≈1,500 round trips/day on a 3,000-order cap), and per-symbol throttles. These enter the optimizer as constraints so a certified pipeline is *constructively* compliant --- research cannot output an operating point the engine would have to refuse.

**8.5 Broker choice as a measured, refreshable output**

Fees are only one axis; realized half-spread, fill ratio on passive orders, reject rates, API latency and stability differ by broker and can outweigh the fee delta. The blueprint\'s answer: run the same bundle in shadow on both brokers\' APIs during S6, measure implementation shortfall on each, and let **TCA pick the venue** --- then keep measuring monthly. The cost model per broker is versioned; when a fee schedule or measured friction changes materially, S5\'s turnover optimization re-runs and the frontier (and possibly the venue) updates.

**8.6 Cost model specification**

*c(order) = statutory(exact) + brokerage(broker, notional) + spread_half(name, time) × aggression + impact κ·(q/ADV_bar)\^ψ*

Statutory terms are exact (Appendix A). Spread and impact start at conservative planning values (§3.1) estimated from 1-second ranges and quote captures, then are refitted quarterly from own fills (κ, ψ from a regression of realized slippage on participation). Every backtest and every optimizer run names the cost-model version it used; a cost-model bump automatically re-flags any certified pipeline whose margin over the new line has thinned.

**9. Universe discovery**

*The universe is a searched axis with the same discipline as any parameter --- constructed point-in-time, filtered for tradability, and sized by breadth economics.*

**9.1 Point-in-time construction**

On the first trading day of each month, rank all NSE equities by a liquidity score computed over the trailing 60 sessions: median daily traded value, median spread (from 1-second ranges/quote captures), fraction of bars with trades, and ATR%. Apply hard filters: not in ASM/GSM at snapshot, not T2T-segment, listed ≥ 60 days, price ≥ ₹50, relative tick ≤ 2.5 bps for sub-30-minute families, MIS-eligible at the execution broker (intersection of both broker lists for portability). Only information knowable on the snapshot date enters --- historical index membership and delisted names included, killing survivorship bias.

**9.2 Candidate universes and hysteresis**

Candidates: **U50, U100, U200, U400** by rank, plus a sector-capped variant of each (max 25% of names per sector) and an \"F&O-intersect\" variant (names also in the derivatives segment --- a free liquidity/shortability screen). Membership uses hysteresis --- enter at rank ≤ 0.8·N, exit at rank \> 1.2·N --- capping monthly churn near 10% so that strategy PnL is not an artifact of universe turnover.

**9.3 Breadth economics**

Grinold\'s law says IR grows with √breadth, but the liquidity tail raises spread and shrinks shortability, so net IR has an interior optimum in N. The funnel evaluates every promoted structure on every candidate universe (it is one more enumerated axis, Table 7.1); expect cross-sectional reversion to prefer U100--U200, momentum/breakout U100, lead--lag U50. The certified bundle pins its universe *definition* (the rule), not the name list --- the list refreshes monthly by the rule.

**10. Portfolio construction and risk**

**10.1 From scores to positions**

-   **Cross-sectional families:** z-score → rank → centered weights within the tradable set; sector-demeaned; beta-neutralized against rolling betas; dollar-neutral long/short (MIS shorts intraday). Position cap 10% of capital per name; gross scaled to the risk target.

-   **Directional families (F3--F5, F8):** unit-risk sizing w_i ∝ σ_target/σ_i with the family\'s structural stop defining the risk unit; portfolio-level vol targeting reconciles families.

-   **Cash-only neutrality caveat:** with no index futures in scope, beta-neutrality costs a short basket (both legs pay the cost line). Each cross-sectional pipeline is therefore also evaluated in a \"long-tilt + market-state gate\" mode; if the mandate later adds a single NIFTY-futures hedge, neutrality gets dramatically cheaper --- flagged as a future decision point, not assumed.

**10.2 Combining pipelines: netting is real money**

The ensemble\'s internal crossing (one pipeline buying what another sells) reduces *realized* turnover below the sum of parts; the combined-blotter simulation at S5 measures this netting ratio and re-prices the ensemble\'s cost line, which in turn shifts each member\'s optimal threshold --- S5 iterates this to a fixed point (coordinate descent, 1--2 passes suffice in practice).

**10.3 Turnover-aware optimization in production form**

Research-side, target weights solve a small QP: maximize wᵀα − λ·wᵀΣw − κ·‖w − w₋₁‖₁ with the L1 coefficient κ set to the cost line --- the optimizer literally refuses trades that don\'t clear cost. Engine-side this collapses to **no-trade bands**: trade only when \|target − current\| exceeds a band proportional to c/E\[edge volatility\] (Gârleanu--Pedersen logic in implementable form). Band width is part of the bundle\'s calibration table.

**10.4 Risk overlays and kill switches**

  -------------------------------------------------------------------------------------------------------------------------------------------------
  **Trigger**                    **Threshold (initial)**                                          **Automatic action**
  ------------------------------ ---------------------------------------------------------------- -------------------------------------------------
  Per-trade stop                 family-specific (e.g., 1.2× range unit for F4; z-reset for F2)   exit position

  Per-name exposure              \> 10% of capital                                                clip at cap

  Pipeline daily loss            −0.6% of capital                                                 flatten pipeline; disabled rest of day

  Portfolio daily loss           −1.5% of capital                                                 flatten everything; halt; human re-arm required

  Gross exposure                 \> 4× capital                                                    block new entries

  Net beta (neutral pipelines)   \|β\| \> 0.3                                                     rebalance hedge legs

  Stale data watchdog            no ticks 3 s on a held name / 10 s market-wide                   cancel opens; flatten name / halt

  Reject/error storm             ≥ 5 rejects or 3 API errors per minute                           halt order flow; alert

  Position reconciliation        engine vs broker mismatch                                        freeze symbol; force reconcile

  Square-off scheduler           15:05--15:12 (randomized)                                        flatten all MIS; verify by 15:15

  Order-rate governor            5 orders/s global; 2/s per symbol                                queue/shed excess (never breach)
  -------------------------------------------------------------------------------------------------------------------------------------------------

*Table 10.1 --- The kill-switch matrix. Every trigger, threshold and action lives in the bundle\'s limits file; the Rust risk governor enforces them pre-trade and cannot be bypassed by a strategy.*

**11. Validation protocol and statistics**

**11.1 Splits**

Development span (oldest data) for S1 exploration; walk-forward span for S2--S3 (train 126d / test 21d, stepping 21d; purge = strategy horizon; embargo = 1 day --- intraday horizons make leakage windows short, but overnight feature lookbacks still demand the embargo); **sealed holdout = most recent 6 months**, untouched until S4, opened once per cycle, unlock logged. Retired holdouts rotate into the walk-forward span for the next cycle.

**11.2 Fill-model tiers (the silent killer, made explicit)**

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Tier**                   **Mechanics**                                                                              **Used at**              **Bias**
  -------------------------- ------------------------------------------------------------------------------------------ ------------------------ ---------------------------------
  A --- conservative taker   next-bar-open fill ± half-spread + impact κ√(q/ADV_bar); market orders only                S2                       understates edge (safe)

  B --- 1s limit simulator   limit fills on price-through with ≤10% participation of interval volume; timeout → cross   S3--S5 (needs 1s tier)   closer to truth; still no queue

  C --- live shadow          real quotes, real acks, no capital                                                         S6                       ground truth for shortfall
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

*Table 11.1 --- No cross-tier comparisons, ever; every result is stamped with its tier. A strategy that only works at tier B with optimistic queue assumptions is not certified.*

**11.3 Certification statistics**

Definitions and formulas in Appendix C: net Sharpe = √252 × mean/sd of daily net PnL over capital (never per-trade annualization); DSR --- the probability the true Sharpe exceeds zero given N registry trials, their variance, skew and kurtosis; PBO --- fraction of CPCV splits where the in-sample winner falls below the out-of-sample median; SPA --- stationary-bootstrap test of the candidate against the entire tried family; plus Calmar, hit rate, average net bps/trade, turnover, deployment ratio, ES95, worst-day.

**11.4 Tripwires (auto-flags in every report)**

-   Net SR \> 4 on any intraday cash pipeline → presumed bug/lookahead until a line-by-line trade audit passes.

-   PnL concentration: \> 30% of annual PnL from \< 5% of days, or \> 40% from one name → flag.

-   IS/OOS gap \> 50%, parameter cliff (±20% perturbation kills \> 50% of SR), or backtest turnover inconsistent with signal autocorrelation → flag.

-   Any use of the holdout beyond its single unlock → the cycle\'s certifications are void. (Governance beats good intentions.)

**12. System architecture --- Python research plant, Rust execution engine**

**12.1 Repository layout**

> quant/
>
> data/ ingestors (breeze), qc, corporate_actions, pit_tables, calendars
>
> features/ feature store builders (rolling stats, betas, rvol, vwap)
>
> alphas/ family plugins F1..F10 (schema + hypothesis + compute)
>
> sim/ vectorized engine · event-driven engine · fill models A/B
>
> portfolio/ constructors, netting, QP/no-trade bands, risk overlays
>
> search/ funnel orchestrator, grids, optuna spaces, gates
>
> stats/ ic, dsr, pbo_cpcv, spa_bootstrap, reports
>
> registry/ experiment ledger (append-only) + snapshot hashes
>
> bundles/ build, sign, validate strategy bundles
>
> rust/ market/ bars/ signals/ oms/ risk/ tca/ ops/ parity/
>
> ops/ token bootstrap, runbooks, alerting, dashboards

**12.2 Research plant (Python)**

Polars + DuckDB over Parquet for panel work; NumPy/Numba in the vectorized engine\'s hot loops; cvxpy for the QP; Optuna for refinement; statsmodels for NW/bootstraps. Multiprocessing fan-out across the 16 cores; everything seeded; every entry point takes (config, snapshot-id) and nothing else --- the CLI *is* the reproducibility contract.

**12.3 Execution plant (Rust)**

Tokio async shell for IO (websockets, REST, journal) around a **deterministic single-threaded strategy core per symbol shard**: prices as i64 paise (no floats in money paths), event-sourced state (append-only journal), crash-only design --- on restart, replay journal then reconcile against broker positions before arming. Modules: market-data client (Breeze WS primary, broker WS backup, gap detector), bar builder (spec-identical to research), signal runtime (stage primitives interpreting bundles), portfolio/no-trade bands, risk governor (Table 10.1, pre-trade, unbypassable), OMS (order state machines, idempotent retries, throttles), TCA logger, ops (token bootstrap, square-off scheduler, alerts).

**12.4 Parity: the golden-replay contract**

Any recorded market-data day can be replayed through both the Python reference and the Rust engine; the emitted **order-intent streams must match exactly** (same bars → same signals → same target → same order at the same tick). Golden days (including gap days, halts, expiry, a data-outage day) run in CI on every bundle release and every engine change; property tests cover bar-boundary ties, missing bars, and restart-mid-day. Parity failures block deployment --- no exceptions, because every later live-vs-sim discrepancy investigation stands on this.

**12.5 Latency truth**

Internal decision latency will be \< 1 ms; broker REST acknowledgment is 30--150 ms; Breeze tick delivery adds its own jitter. Nothing here competes at sub-second horizons --- by design, strategies are certified on decision-at-bar-close semantics with tier-A/B fills, so the live edge does not depend on winning races. Where latency does bite (queue priority for passive fills), it is *measured* in TCA rather than assumed in backtests.

**12.6 Daily runbook (IST)**

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Time**       **Action**                                                                                                                   **On failure**
  -------------- ---------------------------------------------------------------------------------------------------------------------------- --------------------------------------------
  08:30          Token bootstrap: Breeze + execution broker sessions; key/IP check                                                            alert; no-trade day if unresolved by 09:00

  08:45          Pre-flight: bundle hashes, universe file freshness, PIT lists (ASM/GSM/MIS), margin check, calendar flags, risk limits ack   block arming

  09:00--09:15   Warm feeds through pre-open; bar builder sync; no orders                                                                     ---

  09:15          Arm per session mask                                                                                                         ---

  15:05--15:12   Randomized square-off; verify flat by 15:15                                                                                  escalate: manual square-off

  15:35          EOD: reconcile fills vs broker contract notes; TCA; journal archive; registry sync                                           block next-day arming until clean

  Nightly        Data sync + QC gates; incremental S1/S2 on new day; drift monitors; challenger evals                                         quarantine data day
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

*Table 12.1 --- Operating cadence. Ops failures are trading-blocking by default; the system prefers a missed day to an unaudited one.*

**12.7 Monitoring, decay and champion--challenger**

Each live pipeline carries its certification envelope; live rolling statistics (20-day net SR, live IC vs backtest IC, slippage vs model, fill rates) run under **CUSUM drift detectors** --- first breach de-risks the pipeline to 50% weight, second suspends it pending investigation; recovery requires re-passing S4 on data including the drawdown. Challengers (new configs that cleared S4 on nightly/quarterly research) run permanently in shadow; promotion swaps weights only after a pre-declared shadow period beats the incumbent net of costs. Decay is expected: intraday alphas rot; the machine\'s job is to notice before the PnL does.

**13. Session and regime structure**

Session buckets are first-class config: **O** (09:15--10:00, wide spreads, gap digestion, breakout births), **M** (10:00--14:30, tighter spreads, reversion-friendly), **C** (14:30--15:20, closing flows, forced MIS unwinds --- including everyone else\'s). Every family searches its session mask; costs are session-dependent in the model (open spreads run wider).

Regime gates are deliberately few and defined **ex-ante**: previous-day realized-vol tercile of the index; overnight gap bucket; trend-vs-chop via a variance-ratio statistic on NIFTY; expiry-day flag. Gates act multiplicatively on exposure {0, 0.5, 1}. A regime-gated pipeline is just another config --- it passes the same funnel, with two guards: ≤ 9 regime cells, and ≥ 200 test trades per active cell, otherwise the gate is disallowed. This is how regime-awareness is bought without buying regime-overfit.

**14. Failure modes and anti-patterns**

The blueprint\'s controls exist because these are the standard ways such projects die. Each maps to its control section:

-   **Lookahead via timestamp conventions or adjusted data** --- bar-labeling verified empirically; as-of views; shuffled-future tests (§4.4, §5.2).

-   **Backtest fills that cannot exist** --- tiered fill models; taker-only until tier B earns trust; shadow shortfall gate (§11.2, S6).

-   **Multiplicity laundering** --- \"we tried 40,000 things and report the best three\" is fraud against yourself unless N is priced; the registry + DSR/PBO/SPA machinery is the antidote (§7.3).

-   **Needle parameters, regime stories after the fact, holdout reuse** --- plateau centroids; ex-ante regimes; single-unlock holdout (§7.2, §13, §11.1).

-   **Universe fictions** --- survivorship, ASM churn, T2T names, MIS-ineligible shorts: all PIT-filtered (§9.1).

-   **Cost drift** --- budgets change STT, exchanges revise fees, brokers reprice: the versioned cost model and quarterly re-optimization catch it (§8.6); a fee-review task is on the ops calendar.

-   **Operational deaths** --- token expiry mid-session, API bans from rate breaches, silent symbol remaps, un-reconciled fills: runbook + governors + reconciliation (Table 12.1, §3.3).

-   **Correlated \'diversification\'** --- five reversion clones are one strategy; the ensemble\'s correlation cap and marginal-SR rule enforce genuine breadth (S5).

+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **The cultural rule**                                                                                                                                                                                                                                                                                                       |
|                                                                                                                                                                                                                                                                                                                             |
| No result is discussed unless it renders from the registry by config hash. No parameter is chosen by eye. No holdout peeks. Manual overrides exist (markets demand them) but every override is a logged event reviewed weekly. The meta-algorithm is a machine precisely so that discipline is architecture, not willpower. |
+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

**15. Roadmap and decision gates (research-to-market plan)**

*Assumes one focused person plus this document; calendar estimates at \~15--20 hours/week. Every phase ends at a quantitative gate --- the project advances on numbers, not enthusiasm.*

  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Phase**                     **Weeks**   **Build**                                                                                                      **Gate to advance**
  ----------------------------- ----------- -------------------------------------------------------------------------------------------------------------- ------------------------------------------------------------------------------------------------------------------
  P0 Data plant                 1--3        Breeze ingestors + WS capture; QC gates; PIT tables; feature store v1; U-universe generator                    5y × U200 1-minute clean (\<0.1% quarantined); forward tick/1s capture running; PIT lists snapshotting daily

  P1 Screening machinery        3--8        vectorized engine; cost model v1 (both brokers); S1 harness; registry; family plugins F1--F6, F8               S1 sweep complete; ≥ 25 signal cards passing gates across ≥ 3 families

  P2 Honest simulation          8--14       event-driven engine + fill tiers A/B; walk-forward S2; robustness S3; F9--F10 (F7 when 1s tier matures)        ≥ 8 configs through S3 with net SR ≥ 1.5 on the ₹0 cost line

  P3 Certification & ensemble   12--16      DSR/PBO/SPA stack; holdout protocol; S5 ensemble + turnover/broker optimizer; top-K report v1                  ≥ 3 certified pipelines, pairwise PnL corr ≤ 0.5; ensemble walk-forward net SR ≥ 1.8, DSR ≥ 0.95, PBO ≤ 0.25

  P4 Rust engine & parity       14--20      engine modules (§12.3); golden-replay CI; ops runbook automation; static-IP deployment; compliance checks      byte-exact parity on golden days; 2 weeks dry-run with zero ops incidents

  P5 Shadow & first capital     20--24      4-week shadow on both brokers; TCA; venue selection; then ₹1L live on best single pipeline                     shortfall ≤ 30% of gross edge; live 4-week net PnL \> 0 with slippage inside model bands; zero compliance events

  P6 Scale & institutionalize   24+         ensemble live; ramp ₹1L → ₹3L → full ≤ ₹10L in 4-week steps; nightly research loop; quarterly full re-search   each ramp step: live SR consistent with certification band; drawdown inside budget; monitoring green
  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

*Table 15.1 --- Phased plan. P3 overlaps P2, P4 overlaps P3 deliberately: engine work starts once the first pipeline looks certifiable.*

**15.1 Kill criteria (pre-committed)**

If a full, honest cycle certifies **nothing** on the Flattrade cost line: do not loosen gates. The finding is that at this data/infrastructure tier, sub-day cash-equity edges net of friction are absent --- itself valuable. The documented pivots, in order: extend horizons toward multi-day (delivery, different cost structure --- new blueprint section, same machinery); upgrade the data tier (full order-book capture, longer 1s history) and re-run the cost-sensitive families; or stop, with capital intact. The registry makes the postmortem exact: it will show whether edges existed gross and died to costs (pivot #1 helps) or never existed (stop).

**15.2 Realistic expectations**

Sober reference points, stated once and not as promises: a certified intraday cash ensemble at this capital, run at 0.8--1.2% daily vol with rotation in the 2--8× band on the ₹0 line, targets net Sharpe ≈ 1.5--2.5 with net returns plausibly in the mid-teens to \~40% of capital per year --- *if* edges certify, which is precisely what the funnel exists to determine rather than assume. Expected drawdowns at that vol run 6--12%; leverage amplifies both sides symmetrically. Intraday PnL is taxed as (speculative) business income at slab rates --- keep the journal audit-ready; none of this document is investment or tax advice.

**Appendix A --- Cost stack, worked to the paisa**

Per side on a ₹1,00,000 intraday equity order (NSE, August 2026 schedules). GST = 18% on (brokerage + exchange transaction charge + SEBI fee).

  --------------------------------------------------------------------------------------------------------------------------------------------
  **Component**              **Basis**                           **Flattrade buy**   **Flattrade sell**   **Zerodha buy**   **Zerodha sell**
  -------------------------- ----------------------------------- ------------------- -------------------- ----------------- ------------------
  Brokerage                  FT: ₹0 · Z: min(0.03%, ₹20)/order   0.00                0.00                 20.00             20.00

  STT                        0.025% sell side                    0.00                25.00                0.00              25.00

  Exchange txn (NSE)         0.00307%                            3.07                3.07                 3.07              3.07

  SEBI fee                   ₹10/crore                           0.10                0.10                 0.10              0.10

  Stamp duty                 0.003% buy side                     3.00                0.00                 3.00              0.00

  GST                        18% × (brok + txn + SEBI)           0.57                0.57                 4.17              4.17

  **Per-side total (₹)**                                         **6.74**            **28.74**            **30.34**         **52.34**

  **Round trip (₹ / bps)**                                       **₹35.48**          **3.55 bps**         **₹82.68**        **8.27 bps**
  --------------------------------------------------------------------------------------------------------------------------------------------

*Table A.1 --- BSE transaction charge differs slightly (0.00375%); DP charges do not apply intraday; broker auto square-off adds ₹50+GST (avoided by the engine\'s own scheduler). Delivery (out of scope) carries 0.1% STT both sides + DP on sells.*

Break-even gross edge per round trip = fees + 2× half-spread × aggression + impact. Planning values (§3.1) put this at ≈6--12 bps (Flattrade) and ≈11--17 bps (Zerodha, ₹1L) on top-100 names --- the lines drawn in Figure 3.

**Appendix B --- Coarse parameter grids and search-space arithmetic**

Coarse grids for S1 (refinement ranges live in each plugin\'s schema). Values are start-of-cycle defaults; the grids are config, not code.

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Family**             **Structural axes (coarse values)**                                                                                                                                        **Coarse configs**
  ---------------------- -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- --------------------
  F1 CS momentum         lookbacks {15,30,60,120m} & 1 combo · residualizer {none, mkt, mkt+sec} · RVOL gate {off, ≥1.5} · rebalance {15,30,60m} · quantile {10%, 20%} --- dominated cells pruned   ≈ 96

  F2 CS mean reversion   window {5,15,30,60m} · residualizer {mkt, mkt+sec, PCA-3} · entry z {1.5, 2, 2.5} · exit {half-life, z→0, time-stop} · news/volume gate {on, off}                          ≈ 144

  F3 TS momentum         windows {30m, 1h, 2h, day-anchored} · threshold {0.5, 1, 1.5}σ · exit {reversal, EOD, trail}                                                                               36

  F4 Breakout            type {ORB-15, ORB-30, ORB-60, compression} · confirm {RVOL≥1.5, ≥2, none} · trigger k {0.25, 0.5} ATR · stop {range edge, ATR}                                             48

  F5 Gap digestion       conditioning {market-rel, sector-rel, both} · response {fade, follow, conditional table} · window {30, 60, 90m}                                                            27

  F6 Seasonality         bucket grid (fixed) · conditioning {none, morning move, RVOL} · target windows                                                                                             ≈ 30

  F7 Lead--lag           leader {index, sector composite, both} · lag window {1, 5, 15, 30m} · trigger {1, 2}σ                                                                                      24

  F8 Calendar events     event {earnings, expiry, rebalance, ex-date} · template {drift, fade, conditional} · window {2}                                                                            24

  F9 Flow proxies        proxy {signed vol, CLV, VWAP-dev} · window {5,15,30,60m} · mode {revert, follow} · RVOL split {on, off}                                                                    48

  F10 Pairs              6 pre-registered sector cliques · hedge {OLS, Kalman} · entry z {2, 2.5} · exit {z→0, half-life, EOD}                                                                      72

  **Total structures**                                                                                                                                                                              **≈ 550**
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

*Table B.1 --- ≈550 structures × 4 universes × 4 session masks ≈ 9,000 cells; residualizer/execution-policy shared-slot variants take S1 to the 20k--60k evaluations planned in Table 7.2. Horizons are not multiplied in: S1\'s IC-decay curve prices the whole horizon grid per evaluation.*

**Appendix C --- Metric and test definitions**

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Metric / test**          **Definition**                                                                                                                      **Convention**
  -------------------------- ----------------------------------------------------------------------------------------------------------------------------------- --------------------------------------------------------------
  Daily net return           Σ trade PnL net of cost model ÷ capital                                                                                             capital = account equity, not deployed notional

  Net Sharpe (SR)            √252 × mean(R_d)/sd(R_d)                                                                                                            daily aggregation only; per-trade annualization banned

  Rank IC (h)                Spearman corr(score_t, forward return t→t+h) per cross-section, averaged                                                            t-stat via Newey--West, lag ≈ 1.5 × horizon/bar

  IC half-life               h at which IC decays to half its peak                                                                                               sets natural holding period; input to §8.1

  Fundamental law            IR ≈ IC × √BR, BR = effective independent bets/yr                                                                                   effective breadth = nominal ÷ 4--8 (correlation haircut)

  DSR                        P(true SR \> 0) after deflating observed SR by E\[max SR\] of N trials (registry N), using SR variance, skew γ₃, kurtosis γ₄        Bailey--López de Prado (2014); gate ≥ 0.95

  PBO (CPCV)                 split data into 16 blocks; over C(16,8) train/test recombinations (subsampled 500), fraction where IS-best ranks below OOS median   gate ≤ 0.25; purge+embargo inside splits

  SPA test                   stationary bootstrap of daily net PnL of candidate vs the full set of tried configs                                                 Hansen (2005); gate p ≤ 0.10

  Turnover T                 Σ traded notional ÷ capital, per day                                                                                                the x-axis of Figure 3

  Deployment                 time-weighted deployed notional ÷ (L × capital)                                                                                     expect 10--30%; low deployment caps realized return

  Netting ratio              1 − ensemble external turnover ÷ Σ member turnovers                                                                                 measured at S5 on the combined blotter

  Implementation shortfall   (paper PnL at decision prices − live PnL) ÷ gross edge                                                                              gate ≤ 30% at S6; decomposed into spread/impact/latency/fees

  Rotation optimum           h\* = \[c/(a(1−γ))\]\^(1/γ) for α(h)=a·h\^γ; at γ=½, gross edge at optimum = 2c                                                     derivation: maximize (α(h)−c)/h; §8.1
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

**Appendix D --- API facts, onboarding checklist, sources**

**D.1 Breeze (data plane) --- operating notes**

-   Historical: get_historical_data_v2, intervals {1second, 1minute, 5minute, 30minute, 1day}, ≤ 1,000 candles/call; not corporate-action adjusted; empirically verify the bar-timestamp convention before first use (§4.4).

-   Rate limits: 100 calls/min, 5,000 calls/day (backfill plan in Table 4.1); order endpoints unused (and Breeze disallows market orders anyway) --- Breeze is the data plane, never the execution plane.

-   Websocket: ticks, quotes/depth, live OHLC streams including 1-second; daily session-token login automated at 08:30 with alerting; capture archived to Parquet from day one.

**D.2 Execution-broker onboarding checklist (run for both, keep results in the registry)**

-   Confirm current brokerage schedule and API pricing; record in cost-model version. Verify per-second and per-day order caps in writing; set engine governors below them.

-   Static-IP binding of API keys; Algo-ID tagging confirmation; auto-square-off timing and charge; MIS eligibility/leverage list feed; exchange/segment activation (NSE cash).

-   Measure in shadow (S6): REST latency distribution, WS stability, reject taxonomy, fill quality vs Breeze-timestamped decisions --- venue choice follows Table\'s measured shortfall, not brochures (§8.5).

**D.3 Compliance posture (self-run, white-box, sub-threshold)**

-   Stay below the exchange order-per-second registration threshold (engine cap 5/s); self-run strategies with no third-party distribution avoid strategy registration; static IP + OAuth/2FA + daily tokens; append-only audit journal reconciled to broker logs; review SEBI/exchange circulars quarterly --- the framework hardened through FY2025-26 and specifics (thresholds, forms) can move.

**D.4 Sources consulted (August 2026)**

Zerodha charge schedule --- zerodha.com/charges · Flattrade charge schedule --- flattrade.in/charges · Breeze API documentation & Python SDK --- api.icicidirect.com/breezeapi, github.com/Idirect-Tech/Breeze-Python-SDK · SEBI retail algo framework coverage --- sahi.com, shareindia.com, cskruti.com summaries of the Feb-2025 circular and FY26 enforcement · NSE tick-size revision (₹0.01 below ₹250, June 2024) --- exchange circular coverage (marketcalls.in, Business Standard). Rates and limits drift: the cost model and Appendix D checklists are re-verified quarterly and at every budget.

**Appendix E --- Glossary**

  ------------------------------------------------------------------------------------------------------------------------
  **Term**          **Meaning**
  ----------------- ------------------------------------------------------------------------------------------------------
  ADV               average daily traded value of a stock

  ASM / GSM         NSE surveillance lists carrying extra margins/restrictions; excluded from the universe point-in-time

  Bundle            signed artifact (config + params + universe + limits) that research ships and the Rust engine runs

  CPCV              combinatorially purged cross-validation --- the split scheme behind PBO

  DSR               deflated Sharpe ratio --- Sharpe honesty after N trials

  Fill-model tier   A conservative-taker sim / B 1-second limit sim / C live shadow (§11.2)

  IC                information coefficient --- correlation between signal and forward return

  MIS               margin intraday square-off product code --- leveraged intraday, force-closed same day

  Netting ratio     turnover saved when ensemble members trade against each other internally

  No-trade band     region around target weight within which the engine refuses to trade (cost-aware)

  OPS               orders per second --- SEBI registration threshold ≈ 10/s; engine governor 5/s

  PBO               probability of backtest overfitting

  PIT               point-in-time --- using only information knowable on the as-of date

  Rotation T        traded notional ÷ capital per day; \"how many times we rotate\"

  RVOL              relative volume vs same-time-of-day baseline

  SPA               superior predictive ability test (bootstrap, multiplicity-aware)

  T2T               trade-to-trade segment --- delivery-only, no intraday; excluded

  TCA               transaction-cost analysis --- measuring realized spread/impact/latency from own fills
  ------------------------------------------------------------------------------------------------------------------------

**Appendix F --- Reference library**

-   Grinold & Kahn, *Active Portfolio Management* --- the fundamental law; breadth × skill framing used in §2.3/§9.3.

-   López de Prado, *Advances in Financial Machine Learning* (2018) --- purged CV, embargo, CPCV/PBO, meta-labeling, deflated Sharpe context.

-   Bailey & López de Prado, \"The Deflated Sharpe Ratio\" (2014); Bailey, Borwein, López de Prado & Zhu, \"The Probability of Backtest Overfitting\" (2015).

-   White, \"A Reality Check for Data Snooping\" (2000); Hansen, \"A Test for Superior Predictive Ability\" (2005) --- the S4 family tests.

-   Harvey, Liu & Zhu, \"...and the Cross-Section of Expected Returns\" (2016) --- why t-stats must clear multiplicity-adjusted bars.

-   Gârleanu & Pedersen, \"Dynamic Trading with Predictable Returns and Transaction Costs\" (2013) --- the theory behind no-trade bands and partial adjustment (§10.3).

-   Almgren & Chriss, \"Optimal Execution of Portfolio Transactions\" (2000) --- impact modeling vocabulary for the cost model.

*End of blueprint. Version 1.0 --- treat every threshold herein as a versioned config default, and let the registry, not memory, be the source of truth.*
