**QUANTITATIVE RESEARCH MONOGRAPH**

**AlphaForge**

A Falsifiable Alpha Library and Deterministic Research-to-Execution Specification

*NSE cash equities \| scalping to intraday \| Breeze market data \| separate broker order API \| capital below INR 10 lakh*

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **SCIENTIFIC STANDARD** No alpha enters the repository as an indicator recipe. It enters as a timestamped economic hypothesis, an estimand, a causal operator, a null model, a costed implementation and a predeclared rejection rule. The system is allowed to conclude that no candidate survives.
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

**Version 2.0 \| 28 August 2026**

# Reading map

  ------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Part**                          **Purpose**                                                    **Principal output**
  --------------------------------- -------------------------------------------------------------- -----------------------------------------------------------
  I. Epistemology and notation      Defines what can be claimed and when information exists        Causal data/label contract

  II\. Alpha research cards         Thirty-six distinct, injectable alpha families                 Logic, equations, code and falsifiers per family

  III\. Combination and portfolio   Turns forecasts into small-capital positions                   Calibrated ensemble, costs, integer optimization

  IV\. Honest validation            Controls leakage, dependence and search bias                   Nested walk-forward, DSR/PBO/SPA and stress gates

  V. Repository construction        Maps the mathematics to Python research and Rust execution     Directory tree, interfaces, schemas, tests and milestones

  Appendices                        Operational checklists, canonical code templates and sources   Build-ready acceptance standard
  ------------------------------------------------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **SCOPE** This is a research and engineering specification, not a promise of profitability. It intentionally excludes generative AI from signal production and live decision-making. All live permissions, data entitlements, broker capabilities and exchange rules must be re-verified before implementation.
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# Part I --- Epistemology, causality and mathematical contracts

# 1. What counts as an alpha

An alpha is a conditional forecast with an information set and an economic mechanism. It is not a named indicator. The research object is a complete tuple:

A = (H, I_t, T_h, phi_theta, C, E, N, F) \[hypothesis, information, target, estimator, costs, execution, nulls, falsifiers\]

  --------------------------------------------------------------------------------------------------------------------------------------
  **Element**                 **Required declaration**                                             **Voodoo failure prevented**
  --------------------------- -------------------------------------------------------------------- -------------------------------------
  H: mechanism                Who is constrained, informed, slow, forced or providing liquidity?   story added after seeing P&L

  I_t: information set        Every field and its earliest usable timestamp                        look-ahead and revised-data leakage

  T_h: target                 Exact horizon, price convention and side                             moving goalposts

  phi_theta: estimator        Formula, parameter domain, fit window and regularizer                opaque indicator stacking

  C/E: costs and execution    Broker, spread, impact, delay, fill and rounding                     gross-alpha fantasy

  N/F: nulls and falsifiers   Baselines, perturbations and rejection thresholds                    unfalsifiable narratives
  --------------------------------------------------------------------------------------------------------------------------------------

## 1.1 Pre-registration object

AlphaSpec {\
id, version, hypothesis, information_set, target, feature_dag,\
parameter_domain, fit_protocol, null_models, falsifiers,\
data_tier, horizon, cost_context, execution_policy, references\
}

Any material change creates a new AlphaSpec version and a new counted trial. A notebook observation that influences the next experiment is also a trial; deletion does not erase it from the registry.

# 2. Time, information and labels

F_t = sigma-field generated by records whose exchange timestamp and local-receipt timestamp are both \<= t

x_i,t must be F_t-measurable ; order_intent_i,t is emitted after decision latency ; fill occurs at the next executable event

Bars are labeled by close time. A feature computed from bar t may not fill within bar t. Point-in-time instruments, corporate actions, universe eligibility, broker product eligibility and event versions are first-class datasets rather than mutable lookup tables.

## 2.1 Target and accounting convention

y_i,t(h) = side_i,t \[log P_i,exit - log P_i,entry\] - cost_i(entry, exit, size, state)

daily net return_d = (realized PnL_d - fees_d - modeled slippage_d) / start_of_day_NAV_d

-   Execution prices use raw, tick-valid prices; adjusted series may be used only for research transforms with an explicit raw/adjusted bridge.

-   All quantities are integer shares; Rust money and fees are integer paise. Python may use floating-point for estimation but not as the accounting authority.

-   Missing bars, stale quotes and late events are states, not silently forward-filled evidence.

-   The same calendar, boundary rules and corporate-action fixtures are consumed by Python and Rust.

# 3. Common statistical primitives

## 3.1 Robust normalization

RZ(x) = clip((x - median(x)) / (1.4826 MAD(x) + eta), -z_max, z_max)

Use cross-sectional RZ at a common timestamp or trailing RZ on a single series; never mix their denominators. Winsor limits and scales are fitted in training data and serialized in the bundle.

## 3.2 Factor residualization

beta_i,t = argmin_beta sum\_{u=t-W+1..t} w_u (r_i,u - beta\' f_u)\^2 + lambda \|\|beta\|\|\_2\^2

epsilon_i,t = r_i,t - beta_i,t\' f_t ; factors include market, sector and only predeclared statistical components

## 3.3 Forecast calibration

mu_hat(s) = E\[y_net \| s\] ; use monotone bins, isotonic regression or ridge calibration fitted inside the inner fold

trade iff \|mu_hat_i,t\| \> marginal_cost_i,t + kappa \* SE(mu_hat_i,t)

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **NO MATHEMATICAL DECORATION** A more elaborate operator is admissible only if it improves nested out-of-sample loss or net utility over its simpler parent and the improvement survives perturbation. Complexity is a liability until it earns evidence.
  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 4. Alpha plugin and feature-DAG contract

class AlphaPlugin(Protocol):\
id: str; version: str; spec: AlphaSpec\
warmup_bars: int; horizon_bars: int; requires: DataRequires\
\
def compute(self, view: AsOfPanelView, params: Params) -\> ForecastFrame:\
\# returns \[decision_ts, symbol, score, horizon, validity_flags\]\
\# view refuses rows later than decision_ts\
\...

  ---------------------------------------------------------------------------------------------
  **Contract**     **Invariant**
  ---------------- ----------------------------------------------------------------------------
  AsOfPanelView    Physically refuses t+1 data and records every accessed field/version

  FeatureNode      Pure function of declared parents; content-addressed cache; causal warm-up

  ForecastFrame    One row per symbol/decision with score, expiry, capacity and flags

  TrialManifest    Hashes code, data, universe, costs, folds, params, seed and runtime

  StrategyBundle   Only certified, frozen nodes and calibration cross into Rust
  ---------------------------------------------------------------------------------------------

## 4.1 Common causal primitives used in all code sketches

\# Implement once; property-test aggressively.\
logret(x,k); causal_ewma(x); rolling_wls_residual(y,F); robust_z(x); cs_robust_z(x)\
same_clock_rvol(volume); pit_peer_set(symbol,asof); fold_fit(model,train_only=True)\
forecast(score,horizon); liquidity_gate(view); next_event_fill(intent); stressed_cost(order,state)

# Part II --- Falsifiable alpha-family catalogue

The catalogue contains 36 families, not 36 fixed strategies. Every family expands into versioned candidates across admissible horizons, transformations, universes, sessions, brokers and portfolio wrappers. Search breadth is controlled by predeclared budgets and hierarchical promotion; no full Cartesian lottery is permitted.

  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Tier**   **Admissible data**                                               **Families**            **Certification boundary**
  ---------- ----------------------------------------------------------------- ----------------------- -----------------------------------------------------------------
  T1         completed 1-minute OHLCV, PIT masters, calendar, factors          A01-A18, A27, A29-A30   may be researched after PIT/QC and costed next-event fills

  T2         synchronized quotes, trades and sequence-complete ordered depth   A19-A23, A28, A31-A36   requires forward archive, clock audit and calibrated fills

  T3         auction/event/index files with release timestamps                 A24-A26                 requires specific entitlement, event lineage and broker support
  ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 5. Tier 1 --- Minute-bar and point-in-time families

## A01 Cross-sectional residual momentum

  --------------------------------------------------------------------------------------------------------------------
  **Data tier**               **Natural horizon**   **Output**                        **Primary nuisance**
  --------------------------- --------------------- --------------------------------- --------------------------------
  T1: causal 1-minute OHLCV   15-120 minutes        ranked expected relative return   market/sector beta drift

  --------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Information diffuses at different speeds across stocks. The claim is idiosyncratic continuation after removing contemporaneously estimable market and sector moves, not raw winner chasing. **^\[R01\]\ \[R04\]^**

**Estimand.** The conditional mean of future stock residual return given a trailing residual path, measured cross-sectionally at a common decision time.

**Bounded parameter domain.** residual lookback 3-120m; scale window 10-120m; beta history 20-120 sessions; hold 15-120m; skip 0-3 bars; ridge on a log grid

r_i,t = beta_i,t\' f_t + epsilon_i,t ; m_i,t(L) = sum\_{j=0..L-1} epsilon_i,t-j

s_i,t = RZ_CS(m_i,t / sigma_i,t) ; mu_i,t(h) = E\[epsilon_i,t:t+h \| s_i,t, X_t\]

**Causal implementation.** Estimate betas only on observations ending at t, lag factor inputs, robustly standardize across the eligible point-in-time universe, and execute no earlier than the next event.

resid = rolling_wls_residual(view.returns, view.factors, window=W)\
raw = resid.rolling_sum(L) / resid.rolling_std(V)\
return forecast(cs_robust_z(raw), horizon=H)

**Falsification / rejection.** Reject if performance disappears after sector neutralization, a one-bar execution delay, beta-window perturbation, or removal of the best month; require monotone rank-IC and stable cross-sectional breadth.

## A02 Time-series momentum with volatility scaling

  -----------------------------------------------------------------------------------------------------------------------
  **Data tier**               **Natural horizon**   **Output**                  **Primary nuisance**
  --------------------------- --------------------- --------------------------- -----------------------------------------
  T1: causal 1-minute OHLCV   30-240 minutes        signed forecast per stock   autocorrelation induced by stale prices

  -----------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Persistent order splitting and gradual information incorporation can create continuation in each instrument\'s own return process. **^\[R02\]\ \[R13\]^**

**Estimand.** E\[r_i,t:t+h \| multi-horizon own-history\], scaled so high-volatility names do not mechanically dominate.

**Bounded parameter domain.** own-return lookbacks 5-240m; 2-5 predeclared horizons; volatility half-life 10-120m; hold 30-240m

q_i,t(k) = (p_i,t - p_i,t-k) / sigma_i,t(k) ; s_i,t = sum_k omega_k q_i,t(k)

omega = argmin \|\|y - Q omega\|\|\_2\^2 + lambda \|\|omega\|\|\_2\^2, fitted inside each training fold

**Causal implementation.** Use completed bars, causal volatility estimates, and skip variants to distinguish continuation from the most recent-bar reversal.

q = stack(\[logret(view.close, k) / rv(view.ret, k) for k in K\])\
w = ridge_fit(q.train, target.train, penalty=lam)\
return forecast(q @ w, horizon=H)

**Falsification / rejection.** Reject if only one lookback works, if HAC-adjusted evidence is weak, if results are dominated by open gaps, or if the sign flips under a one-bar skip.

## A03 Cross-sectional short-horizon reversal

  --------------------------------------------------------------------------------------------------------------------------
  **Data tier**               **Natural horizon**   **Output**                   **Primary nuisance**
  --------------------------- --------------------- ---------------------------- -------------------------------------------
  T1: causal 1-minute OHLCV   2-30 minutes          ranked contrarian forecast   bid-ask bounce and non-synchronous prints

  --------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Temporary inventory and liquidity shocks may reverse once urgent flow is absorbed. The tradable claim must survive costs and cannot be merely mechanical bid-ask bounce. **^\[R03\]\ \[R10\]^**

**Estimand.** The future relative residual return conditional on an extreme recent residual move and contemporaneous liquidity proxies.

**Bounded parameter domain.** shock 1-15m; robust tail 1.5-3.5; hold 2-30m; liquidity floors and cooldowns preregistered

u_i,t = epsilon_i,t-L:t / max(sigma_i,t, sigma_floor) ; s_i,t = -RZ_CS(u_i,t)

mu_i,t(h) = g(s_i,t, volume_surprise_i,t, range_i,t, session_t)

**Causal implementation.** Residualize first; gate on prior and current completed-bar liquidity; require next-event fills and a minimum economic displacement beyond spread plus stressed impact.

shock = residual_return(view, lookback=L) / causal_vol(view, V)\
score = -cs_robust_z(shock) \* liquidity_gate(view)\
return forecast(score.where(abs(score) \> z0), horizon=H)

**Falsification / rejection.** Reject if midquote-based or next-bar-open returns do not confirm trade-price results, if alpha vanishes after crossing the spread twice, or if it relies on illiquid tail names.

## A04 Residual mean reversion / factor-neutral dislocation

  ---------------------------------------------------------------------------------------------------------------------------------
  **Data tier**              **Natural horizon**   **Output**                      **Primary nuisance**
  -------------------------- --------------------- ------------------------------- ------------------------------------------------
  T1: OHLCV + factor panel   5-90 minutes          expected residual convergence   new information misclassified as a dislocation

  ---------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** A stock may temporarily deviate from a dynamically estimated market-sector-statistical factor manifold and then converge after a transient liquidity shock. **^\[R04\]\ \[R12\]^**

**Estimand.** The conditional error-correction response of a factor-relative log-price state, not the unconditional tendency of a return or price to revisit a moving average.

**Bounded parameter domain.** factor window 20-120 sessions; log-price-spread z window 5-60m; entry 1.5-3.5; exit 0-1.0; hold 5-90m

d_i,t = log P_i,t - a_i,t - beta_i,t\' F_t ; z_i,t = (d_i,t-med_W d_i)/(1.4826 MAD_W(d_i)+eta)

Delta d_i,t+1 = kappa_i d_i,t + Gamma\' Delta f_t + nu_i,t+1 ; require -1 \< kappa_i \< 0

**Causal implementation.** Fit rolling shrinkage betas and residual scale inside the fold; add event, gap, volume and circuit filters; allow asymmetric entry/exit hysteresis.

d = rolling_factor_price_residual(view.log_price, integrated_factors=F, window=W, ridge=lam)\
z = robust_z(d, window=Z)\
return forecast(-z \* transient_gate(view), horizon=H)

**Falsification / rejection.** Reject if the estimated half-life is unstable, phi is not negative out of sample, residualization adds no value over raw reversal, or event-day exclusions erase the result.

## A05 Opening-gap continuation

  -------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                    **Natural horizon**        **Output**                         **Primary nuisance**
  -------------------------------- -------------------------- ---------------------------------- --------------------------------
  T1: daily close + minute OHLCV   5-120 minutes after open   conditional directional forecast   overnight market/sector news

  -------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Large overnight information shocks may be incorporated gradually when opening demand is broad, liquid and confirmed by peers.

**Estimand.** E\[r_open:t+h \| idiosyncratic gap, opening volume, breadth, sector confirmation\], with gap reversal modeled separately.

**Bounded parameter domain.** idiosyncratic gap 0.5-3 prior-day vol; observe 5-30m; hold 5-120m; confirmation thresholds on coarse grids

gap_i = log(O_i,d / C_i,d-1) - beta_M gap_M - beta_S gap_S

s_i,t = gap_i \* I(volume_surprise\>v0) \* I(sign(open_range)=sign(gap_i))

**Causal implementation.** Freeze the prior close and corporate-action adjustment before the session; calculate opening features only from bars completed by the decision time.

gap = idio_gap(view.open, view.prev_close, view.market_gap, view.sector_gap)\
confirm = opening_volume_z(view) \* same_sign(open_range_ret(view), gap)\
return forecast(gap \* positive_gate(confirm), horizon=H)

**Falsification / rejection.** Reject if the result depends on the first untradeable print, disappears after realistic opening spread stress, or is not distinct from market direction.

## A06 Opening-gap reversal

  -----------------------------------------------------------------------------------------------------------------------------
  **Data tier**                    **Natural horizon**       **Output**                        **Primary nuisance**
  -------------------------------- ------------------------- --------------------------------- --------------------------------
  T1: daily close + minute OHLCV   5-90 minutes after open   conditional contrarian forecast   fading genuine information

  -----------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** An idiosyncratic gap unsupported by peer breadth, sustained volume or range continuation may reflect an opening liquidity imbalance that subsequently mean reverts. **^\[R03\]^**

**Estimand.** E\[-r_open:t+h \| idiosyncratic gap, weak confirmation, no event flag\], estimated separately from continuation.

**Bounded parameter domain.** same gap domain as A05; separate weak-confirmation grid; no-event flag mandatory; hold 5-90m

s_i,t = -gap_i \* I(\|gap_i\|\>g0) \* I(peer_confirm\<c0) \* I(volume_confirm\<v0)

trade only if \|mu_i,t\| \> stressed_cost_i,t + uncertainty_buffer_i,t

**Causal implementation.** Use explicit event exclusions, completed opening bars, and an economic threshold before entry; never choose continuation versus fade from the same holdout data.

unsupported = (peer_confirm(view) \< c0) & (opening_rvol(view) \< v0)\
score = -idio_gap_feature(view) \* unsupported \* no_event_flag(view)\
return forecast(score, horizon=H)

**Falsification / rejection.** Reject if continuation and reversal rules are selected ex post by realized sign, if event metadata is incomplete, or if the edge fails a protected-market-limit fill model.

## A07 Opening-range breakout

  ----------------------------------------------------------------------------------------------------------
  **Data tier**      **Natural horizon**   **Output**                      **Primary nuisance**
  ------------------ --------------------- ------------------------------- ---------------------------------
  T1: minute OHLCV   15-120 minutes        directional breakout forecast   range definition and late entry

  ----------------------------------------------------------------------------------------------------------

**Economic mechanism.** The opening range aggregates overnight information. A later escape accompanied by abnormal participation and cross-sectional confirmation may indicate unresolved directional demand.

**Estimand.** The conditional return after a causally fixed opening range is breached by more than a volatility-scaled buffer.

**Bounded parameter domain.** opening range endpoint 5/10/15/30m; volatility buffer 0-1 ATR; hold 15-120m

ORH_i = max\_{09:15..tau} H_i ; ORL_i = min\_{09:15..tau} L_i

s_i,t = sign(break_i,t) \* max(0, \|P_i,t-bound_i\|/ATR_i,t - delta) \* confirm_i,t

**Causal implementation.** The range endpoint tau is predeclared; the signal exists only after the breach bar closes; entries use next-event prices.

orh, orl = fixed_opening_range(view, end=range_end)\
break_z = buffered_break(view.close, orh, orl, causal_atr(view))\
return forecast(break_z \* breadth_volume_confirm(view), horizon=H)

**Falsification / rejection.** Reject if small changes to range_end or buffer reverse the result, if most P&L comes from same-bar fills, or if spread/impact consumes the apparent edge.

## A08 Compression-to-expansion continuation

  ---------------------------------------------------------------------------------------------------------------
  **Data tier**      **Natural horizon**   **Output**                   **Primary nuisance**
  ------------------ --------------------- ---------------------------- -----------------------------------------
  T1: minute OHLCV   10-120 minutes        conditional trend forecast   volatility clustering without direction

  ---------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Low realized range followed by directional range and volume expansion can mark a transition from balanced liquidity to one-sided information flow.

**Estimand.** The directional component of post-compression expansion after controlling for unconditional volatility clustering.

**Bounded parameter domain.** compression windows 10-120m; compression percentile c0=5-30%; expansion threshold e0=1-3 MAD; hold 10-120m

comp_i,t = ECDF_train,t-\[RV_i,t,W_short / RV_i,t,W_long\] ; exp_i,t = RZ_train,t-(TR_i,t)

s_i,t = direction_i,t \* I(comp_i,t\<c0) \* I(exp_i,t\>e0) \* volume_z\_i,t

**Causal implementation.** All quantiles are trailing; compression and expansion windows do not overlap the future label; compare with a volatility-only null.

compressed = causal_percentile(rv_ratio(view,S,L), fold_state) \< c0\
expansion = true_range_z(view, W, fit=fold_state) \> e0\
return forecast(sign(view.ret) \* compressed \* expansion \* volume_z(view), H)

**Falsification / rejection.** Reject if direction adds no information beyond a volatility forecast, if the effect is confined to circuit moves, or if nearby threshold surfaces lack a plateau.

## A09 Causal VWAP displacement

  ------------------------------------------------------------------------------------------------------------
  **Data tier**      **Natural horizon**   **Output**                         **Primary nuisance**
  ------------------ --------------------- ---------------------------------- --------------------------------
  T1: minute OHLCV   5-60 minutes          reversion or continuation branch   full-day VWAP leakage

  ------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Price displacement from same-day volume-weighted consensus can reflect either temporary pressure or informed flow. Reversion and continuation are separate predeclared hypotheses conditioned on participation. **^\[R10\]^**

**Estimand.** The future return conditional on distance from cumulative VWAP computed only through decision time and on a causal volume state.

**Bounded parameter domain.** cumulative VWAP only; distance 0.5-3.5 robust z; causal RVOL quantiles; hold 5-60m; fade/continue separate

VWAP_i,t = sum\_{u\<=t} P_i,u V_i,u / sum\_{u\<=t} V_i,u ; d_i,t=log(P_i,t/VWAP_i,t)/sigma_r,i,t

s_rev=-d I(RVOL\<q0); s_cont=d I(RVOL\>q1 and breadth confirms)

**Causal implementation.** Never use completed-day VWAP or volume. Fit same-clock expected volume from prior sessions inside the training fold.

d = log(view.close / cumulative_vwap(view)) / causal_return_vol(view, W)\
rvol = same_clock_volume_ratio(view, history=D)\
return forecast(branch(d, rvol, mode=params.mode), horizon=H)

**Falsification / rejection.** Reject if causal cumulative VWAP performs materially worse than the mistakenly leaked full-day version without explaining why; reject pooled fade/continue logic selected after outcomes.

  ----------------------------------------------------------------------------------------------------------------------------
  **RESEARCH BOUNDARY** A full-day VWAP used before the close is direct look-ahead leakage and is banned by the feature API.
  ----------------------------------------------------------------------------------------------------------------------------

  ----------------------------------------------------------------------------------------------------------------------------

## A10 Abnormal-volume continuation

  ---------------------------------------------------------------------------------------------------------------------
  **Data tier**      **Natural horizon**   **Output**                            **Primary nuisance**
  ------------------ --------------------- ------------------------------------- --------------------------------------
  T1: minute OHLCV   5-90 minutes          participation-conditioned direction   intraday U-shaped volume seasonality

  ---------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Unexpected participation at a given clock time can proxy for information arrival or institutional urgency; direction is taken from contemporaneous residual return. **^\[R08\]\ \[R10\]^**

**Estimand.** The incremental predictive effect of same-clock volume surprise beyond price movement and volatility.

**Bounded parameter domain.** same-clock history 20-120 sessions; RVOL 1-3 MAD; price lookback 3-30m; hold 5-90m

RVOL_i,t = cumulative_volume_i,t / median_d\<cumulative_volume_i,d,same_clock(t)\>

v_i,t = RZ_train,same-clock(log RVOL_i,t) ; s_i,t = residual_return_i,t(L) \* v_i,t

**Causal implementation.** Expected same-clock volume uses prior days only; corporate-action and partial-session days are excluded or modeled explicitly.

rvol = same_clock_rvol(view.volume, lookback_days=D)\
v = fold_robust_z(log(rvol), clock_bucket=view.clock_bucket)\
price = residual_return(view, lookback=L)\
return forecast(incremental_ridge(price\*v, controls=\[price,v,view.vol_range\]), H)

**Falsification / rejection.** Reject if volume surprise adds no nested-fold incremental value, if half-days dominate, or if the effect is simply a wider-spread proxy.

## A11 Price-volume divergence

  ---------------------------------------------------------------------------------------------------------------
  **Data tier**      **Natural horizon**   **Output**                          **Primary nuisance**
  ------------------ --------------------- ----------------------------------- ----------------------------------
  T1: minute OHLCV   10-120 minutes        conditional reversal/continuation   arbitrary divergence definitions

  ---------------------------------------------------------------------------------------------------------------

**Economic mechanism.** A price move with unusually weak participation may be fragile, while strong signed participation can support continuation. The hypothesis is incremental conditional information, not a chart pattern. **^\[R08\]^**

**Estimand.** The interaction effect between residual return magnitude and same-clock standardized volume after controlling for each marginal effect.

**Bounded parameter domain.** price/volume windows 3-60m; ridge penalty log grid; hold 10-120m; interaction sign declared before testing

x1=RZ(residual_return); x2=RZ(log RVOL); x3=x1\*x2

E\[y_h\|X\] = theta1 x1 + theta2 x2 + theta3 x3 ; test theta3 out of sample

**Causal implementation.** Declare whether low-volume moves reverse or high-volume moves continue before testing; fit interaction coefficients in training folds with shrinkage.

x1 = cs_robust_z(residual_return(view, L))\
x2 = cs_robust_z(log1p(same_clock_rvol(view, D)))\
return forecast(ridge_predict(\[x1, x2, x1\*x2\], fold_state), H)

**Falsification / rejection.** Reject if the interaction coefficient is unstable across folds, if marginal signals explain all value, or if sign rules were chosen after inspection.

## A12 Intraday seasonal residual

  ------------------------------------------------------------------------------------------------------
  **Data tier**      **Natural horizon**   **Output**                   **Primary nuisance**
  ------------------ --------------------- ---------------------------- --------------------------------
  T1: minute OHLCV   5-60 minutes          clock-conditioned forecast   calendar multiple testing

  ------------------------------------------------------------------------------------------------------

**Economic mechanism.** Recurring institutional schedules and liquidity cycles can create weak, stable conditional return patterns at specific clock slots. **^\[R13\]\ \[R20\]^**

**Estimand.** A hierarchically shrunk stock/sector/time-slot mean residual return, conditional on observable session state.

**Bounded parameter domain.** clock bins 5/10/15m; history 60-250 sessions; shrinkage strength fit internally; hold 5-60m

theta_i,s = (n_i,s \* mean(y_i,s) + kappa \* theta_sector,s) / (n_i,s+kappa)

s_i,t = theta_i,slot(t) / SE_HAC(theta_i,slot(t))

**Causal implementation.** Estimate slot effects only on prior sessions, use exchange calendars, and shrink stock effects toward sector/global means.

state = fit_hierarchical_slot_means(train, levels=\[\'global\',\'sector\',\'stock\'\])\
score = state.posterior_mean(view.symbol, view.slot) / state.posterior_se(\...)\
return forecast(score, horizon=H)

**Falsification / rejection.** Reject isolated day-of-week or slot spikes after family-wise correction; require stability across calendar eras and no dependence on a handful of expiry days.

## A13 Slow sector/leader lead-lag

  -----------------------------------------------------------------------------------------------------------------
  **Data tier**                   **Natural horizon**   **Output**                 **Primary nuisance**
  ------------------------------- --------------------- -------------------------- --------------------------------
  T1: synchronized minute panel   2-30 minutes          lagged response forecast   non-synchronous sampling

  -----------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Large leaders, sectors or indices may incorporate information before less liquid constituents; only economically slow diffusion is relevant without colocated infrastructure. **^\[R08\]\ \[R13\]^**

**Estimand.** The incremental forecast of a stock residual from lagged leader innovations after controlling for its own lags and common contemporaneous factors.

**Bounded parameter domain.** lags 1-15m; 3-20 economic leaders; 20-120 session fit; elastic-net penalty log grid; hold 2-30m

epsilon_i,t:t+h = a_h + sum_l phi_h,l epsilon_i,t-l + sum_l gamma_h,l leaderShock_t-l + nu_i,t:h

H0: gamma_1=\...=gamma_L=0 ; evaluate nested predictive loss and net returns

**Causal implementation.** Synchronize clocks, exclude stale bars, lag every explanatory return, and fit sparse distributed lags inside each fold.

X = lag_matrix(\[own_resid(view), leader_innovation(view)\], lags=range(1,L+1))\
model = elastic_net_fit(X.train, target.train, lam=lam)\
return forecast(model.predict(X.now), horizon=H)

**Falsification / rejection.** Reject if contemporaneous inputs are required, if lead-lag vanishes after stale-price filters, or if sub-minute latency would be necessary to realize fills.

## A14 Sparse basket relative value

  --------------------------------------------------------------------------------------------------------------------
  **Data tier**                   **Natural horizon**   **Output**                    **Primary nuisance**
  ------------------------------- --------------------- ----------------------------- --------------------------------
  T1: synchronized minute panel   10-120 minutes        basket residual convergence   unstable peer selection

  --------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** A target stock may be priced relative to a sparse, economically coherent peer basket. Temporary residual displacement can converge without taking broad market risk. **^\[R04\]\ \[R12\]^**

**Estimand.** The future correction of a cross-validated factor-relative log-price spread whose hedge weights were estimated from returns.

**Bounded parameter domain.** peer basket 2-10 names; fit 20-120 sessions; price-spread window 5-60m; gross basket cap; hold 10-120m

beta_i = argmin_beta \|\|r_i - R_peers beta\|\|\_2\^2 + lambda1\|\|beta\|\|\_1 + lambda2\|\|beta\|\|\_2\^2

d_i,t = log P_i,t - a_i - beta_i\' log P_peers,t ; s_i,t = -RZ_TS(d_i,t); require stable error correction

**Causal implementation.** Peer sets come from prior classifications/clustering; coefficient fitting and peer selection occur inside each training fold; impose sign and gross-exposure bounds where appropriate.

peers = pit_peer_set(view.symbol, asof=view.ts)\
beta = elastic_net_fit(view.ret\[peers\].train, view.ret.target.train, lam)\
d = anchored_log_spread(view.log_price.target, view.log_price\[peers\], beta)\
return forecast(-robust_z(d, W), H)

**Falsification / rejection.** Reject if peer membership is unstable, residual variance is not reduced out of sample, or convergence disappears after basket-leg execution costs and integer rounding.

## A15 Cointegration / error-correction spread

  ---------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                     **Natural horizon**   **Output**                    **Primary nuisance**
  --------------------------------- --------------------- ----------------------------- -------------------------------------------
  T1: minute/daily hybrid history   30-240 minutes        spread convergence forecast   spurious regression and structural breaks

  ---------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Economically linked price series may share a stable stochastic trend; deviations from a pre-estimated equilibrium can correct over intraday horizons. **^\[R05\]\ \[R06\]^**

**Estimand.** The error-correction coefficient and forecast conditional on a cointegrating vector selected without the test period.

**Bounded parameter domain.** formation 40-250 sessions; basket 2-8; half-life 10-240m; rank/vector choices nested; structural-break stop

z_t = log P_A,t - beta\' log P_B,t ; Delta z_t = alpha z_t-1 + sum_j Gamma_j Delta z_t-j + u_t

require -1\<alpha\<0, stable beta, and finite cost-adjusted half-life tau_1/2 = log(0.5)/log\|1+alpha\|

**Causal implementation.** Select economic pairs first, estimate rank/vector in training data, monitor parameter drift, and stop trading when equilibrium tests fail.

beta = fit_cointegrating_vector(train.log_prices, rank_rule=params.rank_rule)\
spread = view.log_prices @ beta\
return forecast(error_correction_signal(spread, train_state), horizon=H)

**Falsification / rejection.** Reject if stationarity does not survive rolling windows, if the pair was data-mined from the full universe without trial accounting, or if legging/cost risk dominates.

## A16 Factor-neutral cross-sectional composite

  ---------------------------------------------------------------------------------------------------------------------------
  **Data tier**                 **Natural horizon**   **Output**                             **Primary nuisance**
  ----------------------------- --------------------- -------------------------------------- --------------------------------
  T1: OHLCV + PIT descriptors   30-240 minutes        neutralized stock-selection forecast   factor estimation error

  ---------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** A preregistered subset of A01 residual momentum, A03 reversal, A09 VWAP displacement, A10 volume surprise, A12 seasonality and A13 lead-lag may contain complementary conditional information after common exposures are projected out. **^\[R21\]\ \[R22\]\ \[R23\]^**

**Estimand.** The cross-sectional conditional mean attributable only to a frozen subset of the named parent-family forecasts after nuisance-exposure control.

**Bounded parameter domain.** 2-6 parents chosen only from A01/A03/A09/A10/A12/A13; ridge log grid; neutrality tolerances 0.02-0.20; hold 30-240m

mu_t = Z_t theta ; theta = argmin \|\|y-Z theta\|\|\_2\^2 + lambda\|\|theta\|\|\_2\^2

mu_perp = (I - B(B\'W B + eta I)\^-1 B\'W) mu

**Causal implementation.** The allowed parent IDs and maximum count are declared before search. All normalization, exposure estimates and shrinkage are fold-local; missingness is explicit and no current constituent list is projected backward.

Z = parent_forecasts(view, allowed={\'A01\',\'A03\',\'A09\',\'A10\',\'A12\',\'A13\'})\
mu = ridge_cross_section(Z, fold_target, penalty=lam)\
return forecast(weighted_residualize(mu, pit_risk_exposures(view), ridge=eta), H)

**Falsification / rejection.** Reject if raw factor tilts explain performance, if neutralization is unstable under covariance shrinkage, or if the composite beats constituents only in the training sample.

## A17 Residual acceleration and trend curvature

  ---------------------------------------------------------------------------------------------------------
  **Data tier**      **Natural horizon**   **Output**                 **Primary nuisance**
  ------------------ --------------------- -------------------------- -------------------------------------
  T1: minute OHLCV   10-90 minutes         change-in-trend forecast   noise amplification by differencing

  ---------------------------------------------------------------------------------------------------------

**Economic mechanism.** The rate of change of a residual trend may distinguish a strengthening information move from a decaying one, provided estimation is heavily regularized. **^\[R07\]^**

**Estimand.** The incremental predictive content of a smoothed second difference beyond level momentum and volatility.

**Bounded parameter domain.** one-sided EWMA half-life 3-60m; difference lag 1-15m; hold 10-90m; curvature tested only beyond level/slope

m_t = EWMA_lambda(epsilon_t) ; a_t = m_t - m_t-k ; c_t = a_t - a_t-k

E\[y_h\|m,a,c\] with H0: coefficient(c)=0 conditional on m and a

**Causal implementation.** Use one-sided filters only, predeclare smoothing scales, and orthogonalize curvature to simpler momentum baselines.

m = causal_ewma(residual_return(view, 1), half_life=hl)\
a = m - m.shift(k); c = a - a.shift(k)\
return forecast(ridge_predict(\[m,a,c\], fold_state), H)

**Falsification / rejection.** Reject if curvature adds no nested-fold value over momentum, if it is hypersensitive to smoothing, or if delay stress eliminates the effect.

## A18 Late-session signed-participation continuation

  -----------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                 **Natural horizon**                 **Output**                         **Primary nuisance**
  ----------------------------- ----------------------------------- ---------------------------------- ------------------------------------------
  T1: minute OHLCV + calendar   10-45 minutes; flat before cutoff   late continuous-session forecast   broker square-off and auction transition

  -----------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Benchmarking, fund-flow completion and risk reduction can create persistent late-session demand before the closing auction, but the execution window is operationally constrained. **^\[D04\]^**

**Estimand.** The future residual return in a fixed late continuous-trading window conditional on accumulated bar-signed abnormal participation.

**Bounded parameter domain.** decision 14:30 onward; lookback 15-180m; hold 10-45m; entry stops 15-30m before effective flatten cutoff

flowProxy_i,t(L) = sum\_{u=t-L+1..t} sign(epsilon_i,u) V_i,u / E_train\[V_i,u \| same clock\]

s_i,t = flowProxy_i,t \* I(t in predeclared late window) \* I(time_to_flat\>H+buffer)

**Causal implementation.** Use a broker/product capability snapshot each morning; do not assume positions can enter the auction; the independent flatten scheduler dominates alpha.

eligible = session_clock(view).allows_entry(H, safety_buffer)\
flow = signed_abnormal_participation(view, lookback=L, history_days=D)\
return forecast((flow\*sector_breadth(view)).where(eligible), horizon=H)

**Falsification / rejection.** Reject if profits rely on broker auto-square-off, unmodeled auction fills, or a cutoff unavailable at the selected broker.

# 6. Tier 2 --- Quote, trade and depth families

## A19 Quoted-spread shock reversion

  ------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                      **Natural horizon**     **Output**                         **Primary nuisance**
  ---------------------------------- ----------------------- ---------------------------------- --------------------------------
  T2: synchronized quotes + trades   seconds to 10 minutes   liquidity-normalization forecast   stale or crossed quotes

  ------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** A transient spread widening without commensurate information flow may normalize, allowing a cautious forecast of midpoint reversion rather than guaranteed passive capture. **^\[R10\]^**

**Estimand.** The midpoint return after a side-identified standardized spread shock, conditional on quote age, replenishment and signed trade flow; no exogeneity is claimed.

**Bounded parameter domain.** spread shock 90-99%; quote age ceiling 100-2000ms; lookback 10s-10m; horizon 5s-10m

spread_bps_t = 10\^4 (ask_t-bid_t)/mid_t ; shock_t = RZ_TS(spread_bps_t)

retreat_t=I(Delta ask_t\>0)-I(Delta bid_t\<0); s_t=-retreat_t shock_t I(replenishment) I(\|signed_flow\|\<f0)

**Causal implementation.** Reject crossed/stale quotes, maintain exchange-sequence ordering, and estimate fills from price-through/participation rather than touch.

q = clean_nbbo_like_quote(view.quotes, max_age_ms=A)\
shock = robust_z(spread_bps(q), window=W); side = quote_retreat_side(q)\
gate = replenishment_gate(q) \* low_signed_trade_flow(view.trades, q)\
return forecast(-side\*shock\*gate, H)

**Falsification / rejection.** Reject if only passive touch fills are profitable, if quote cleaning drives the result, or if latency stress converts gains into adverse selection.

  -------------------------------------------------------------------------------------------------------------------------------------------------
  **RESEARCH BOUNDARY** Tier-2 candidates cannot be certified from minute OHLCV. A forward quote archive and calibrated fill model are mandatory.
  -------------------------------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------------------------------

## A20 Order-book imbalance and microprice

  ---------------------------------------------------------------------------------------------------------------------------------
  **Data tier**               **Natural horizon**     **Output**                                   **Primary nuisance**
  --------------------------- ----------------------- -------------------------------------------- --------------------------------
  T2: level-1/level-5 depth   1 second to 5 minutes   very-short-horizon price-pressure forecast   latency and queue dynamics

  ---------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Asymmetric displayed depth can shift the expected next price move when it reflects genuine supply-demand pressure rather than fleeting orders. **^\[R09\]\ \[R10\]^**

**Estimand.** The conditional midpoint change given lagged imbalance, microprice displacement, spread state and cancellation intensity.

**Bounded parameter domain.** book levels 1-5; imbalance window 100ms-10s; quote stability 100ms-5s; horizon 1s-5m

I_t(k)=(B_t(k)-A_t(k))/(B_t(k)+A_t(k)); micro_t=(ask B_t(1)+bid A_t(1))/(B_t(1)+A_t(1))

P(Delta mid\_{t+h}\>0 \| (micro-mid)/tick, sum_k omega_k I_t(k), cancel_intensity, spread, stability)

**Causal implementation.** Use event-time ordering, lagged book state, quote stability and explicit clock synchronization; do not infer queue priority from snapshots.

book = synchronized_book(view.depth_events)\
X = \[microprice_displacement(book), depth_shape(book,K), cancel_intensity(book),\
book.spread_ticks, quote_stability(book)\]\
return forecast(fold_calibrated_logit.predict(X), H)

**Falsification / rejection.** Reject if the forecast horizon is shorter than achievable end-to-end latency, if cancellations reverse the sign, or if net value requires unknown queue position.

## A21 Signed trade-volume imbalance

  -----------------------------------------------------------------------------------------------------------------
  **Data tier**         **Natural horizon**     **Output**                        **Primary nuisance**
  --------------------- ----------------------- --------------------------------- ---------------------------------
  T2: trades + quotes   seconds to 10 minutes   flow-conditioned price forecast   trade-sign classification error

  -----------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Persistent aggressive buying or selling can produce short-lived price impact when liquidity replenishment is slower than informed or urgent flow. **^\[R08\]\ \[R09\]^**

**Estimand.** The incremental response of future midpoint returns to lagged signed trade volume after controlling for spread, volatility and book imbalance.

**Bounded parameter domain.** 10-500 trades or 1s-5m windows; sign classifiers preregistered; horizon 1s-10m

STVI_t = sum\_{u in window} aggressor_sign_u size_u / sum\_{u in window} size_u

Delta mid\_{t+h} = theta STVI_t + gamma\' controls_t + e\_{t+h}

**Causal implementation.** Classify trades using synchronized quotes with uncertainty flags; aggregate in event or clock time; use strictly lagged STVI for decisions. Book-event OFI is a separate control, not this feature.

signed = classify_trades(view.trades, synchronized_quotes=view.quotes)\
stvi = signed.size.mul(signed.sign).rolling(W).sum() / signed.size.rolling(W).sum()\
return forecast(residualize(stvi, micro_controls(view)), H)

**Falsification / rejection.** Reject if alternative sign classifiers disagree materially, if effect exists only at zero delay, or if impact cost exceeds forecast magnitude.

## A22 Depth depletion and replenishment

  ---------------------------------------------------------------------------------------------------------------------------------
  **Data tier**               **Natural horizon**    **Output**                             **Primary nuisance**
  --------------------------- ---------------------- -------------------------------------- ---------------------------------------
  T2: ordered depth updates   seconds to 5 minutes   continuation versus resilience state   snapshot feeds miss message causality

  ---------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** The rate at which consumed depth replenishes distinguishes resilient liquidity from a genuine liquidity vacuum. **^\[R09\]^**

**Estimand.** The hazard of another price move conditional on depletion and replenishment intensities on each side of the book.

**Bounded parameter domain.** sequence-complete typed events mandatory; intensity half-life 0.1-30s; depth levels 1-5; eta_cancel in \[0,1\] selected only inside the nested loop; horizon 1s-5m

lambda_exec\^side(t), lambda_cancel\^side(t), lambda_rep\^side(t) are distinct EWMA quantity intensities

D_side(t)=lambda_exec\^side(t)+eta_cancel lambda_cancel\^side(t)-lambda_rep\^side(t); s_t=D_ask(t)-D_bid(t)

**Causal implementation.** Certification requires sequence-complete ordered updates and separately identified executions, cancellations and additions. Coarse snapshots may support only an explicitly labelled uncertainty proxy, never a certified A22 signal; fit state-dependent intensities on training windows.

evt = typed_book_event_intensities(view.depth_events, half_life=hl)\
D = evt.exec + eta_cancel \* evt.cancel - evt.add\
score = D.ask - D.bid\
return forecast(score \* stable_clock(view), H)

**Falsification / rejection.** Reject on sequence loss, event-type ambiguity, material sensitivity to eta_cancel, or any dependence on assumed queue priority.

## A23 Liquidity-vacuum continuation/reversal classifier

  -----------------------------------------------------------------------------------------------------------------------------
  **Data tier**                 **Natural horizon**     **Output**                      **Primary nuisance**
  ----------------------------- ----------------------- ------------------------------- ---------------------------------------
  T2: trades + depth + quotes   seconds to 15 minutes   probabilistic branch forecast   post-selection between opposite signs

  -----------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** A sharp move through thin depth may continue when replenishment fails and informed flow persists, or reverse when depth rapidly returns. The branch must be learned and validated as one conditional model. **^\[R09\]\ \[R23\]^**

**Estimand.** P(continuation \| depletion, replenishment, OFI, spread, volatility) minus P(reversal \| same state).

**Bounded parameter domain.** low-capacity multinomial/logit family; 5-25 features; ridge grid; horizon 1s-15m; calibration method fixed

p_t = softmax(g_theta\[OFI, depletion, replenishment, spread_z, return_z, session\])

base_t=p_cont E\[y\|cont\]+p_rev E\[y\|rev\]; mu_t=sign(base_t) max(\|base_t\|-uncertainty_penalty_t,0)

**Causal implementation.** Use a predeclared low-capacity classifier with nested tuning; calibrate probabilities and prohibit choosing the winning branch after seeing test P&L.

x = liquidity_state_features(view).lagged()\
p = fold_calibrated_multinomial(x, fold_state)\
base = p.cont\*state_mu.cont + p.rev\*state_mu.rev\
return forecast(shrink_to_zero(base, posterior_se(base)\*kappa), H)

**Falsification / rejection.** Reject if calibration fails, if class definitions change across folds, if the model does not beat simple OFI/imbalance baselines, or if fill stress removes value.

# 7. Tier 3 --- Auction and event families

## A24 Closing-auction imbalance

  ----------------------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                             **Natural horizon**              **Output**                           **Primary nuisance**
  ----------------------------------------- -------------------------------- ------------------------------------ ------------------------------------------
  T3: auction-specific messages and fills   auction phases / clearing only   auction clearing-pressure forecast   special session rules and broker support

  ----------------------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Published or inferable auction imbalance can predict clearing pressure when passive and benchmarked participants have constrained behavior. **^\[D04\]^**

**Estimand.** The conditional clearing-price displacement given time-stamped imbalance, reference price, indicative match and residual continuous-session flow.

**Bounded parameter domain.** auction update 1-10s; imbalance/reference/indicative fields fixed by schema; auction clearing only until post-auction data exists

imb_t=(buy_qty_t-sell_qty_t)/(buy_qty_t+sell_qty_t) ; d_t=(indicative_t-reference_t)/tick

mu_close = E\[log(P_clear/reference)\|imb_t,d_t,time_to_match,liquidity\]

**Causal implementation.** Implement as a distinct auction state machine; record order-acceptance windows, indicative fields and actual auction fills; never simulate from continuous OHLC alone.

state = auction_state(view.auction_messages, exchange_calendar=view.calendar)\
x = \[state.imbalance, state.indicative_displacement, state.time_to_match\]\
return forecast(fold_calibrator.predict(x), horizon=\'auction_clear\')

**Falsification / rejection.** Reject without auction-specific entitlement, broker order support and historical fills; continuous-session backtests cannot certify this alpha.

  -------------------------------------------------------------------------------------------------------------------------
  **RESEARCH BOUNDARY** This family remains disabled until auction data and broker capability are independently verified.
  -------------------------------------------------------------------------------------------------------------------------

  -------------------------------------------------------------------------------------------------------------------------

## A25 Index-rebalance forced-flow

  ---------------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                              **Natural horizon**              **Output**                          **Primary nuisance**
  ------------------------------------------ -------------------------------- ----------------------------------- -----------------------------------
  T3: PIT index files + AUM/flow estimates   30-240 minutes; flat by cutoff   same-session forced-flow pressure   announcement leakage and crowding

  ---------------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Passive funds must trade constituent and weight changes; expected demand relative to available liquidity can create temporary pressure before or at implementation. **^\[R10\]\ \[R11\]^**

**Estimand.** Same-session residual price response to pre-announced required flow scaled by remaining executable liquidity, with no overnight holding.

**Bounded parameter domain.** index event types preregistered; same-session pressure by remaining ADV; hold 30-240m; mandatory intraday flatten; crowding stress

flow_i = linked_AUM \* Delta weight_i ; pressure_i,t = flow_i / expected_remaining_ADV_i,t

mu_i,t = g(pressure_i,t, event_phase_t, crowding_proxy_t) I(time_to_flat\>H+buffer)

**Causal implementation.** Timestamp every announcement and file release; use only information public by decision time; enter only within preregistered same-session windows and flatten before the broker/exchange cutoff.

event = pit_index_change(view.index_files, asof=view.ts)\
pressure = event.delta_weight\*aum_estimate(event.index)/expected_remaining_adv(view)\
return forecast(session_gate(decay_curve(pressure,event.phase),flat_by=cutoff), H)

**Falsification / rejection.** Reject if event timestamps are uncertain, revised files are projected backward, overnight holding is required, price impact precedes usable publication, or liquidity/crowding erases edge.

## A26 Event-surprise and peer diffusion

  ----------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                         **Natural horizon**         **Output**                            **Primary nuisance**
  ------------------------------------- --------------------------- ------------------------------------- --------------------------------------
  T3: timestamped licensed event data   minutes to intraday close   event-conditioned relative forecast   timestamp and text-derived lookahead

  ----------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** A structured surprise may be incorporated gradually into the issuer and economically linked peers. The feature must be available deterministically before the trade and need not use generative AI.

**Estimand.** The conditional issuer/peer residual return given a numeric surprise, first reaction, volume response and peer exposure.

**Bounded parameter domain.** numeric surprises only; observe 1-30m reaction; issuer/peer horizons 5m-close; event-version and receipt-latency mandatory

surprise=(actual-consensus)/scale ; reaction=return\[event_ts, decision_ts\]

mu_i = g(surprise, reaction, RVOL, peer_loading, session) with issuer and peer effects separated

**Causal implementation.** Use vendor release timestamps, structured fields and immutable event versions; latency from release to local receipt is part of the feature and simulation.

event = view.events.latest_received_before(view.ts)\
x = numeric_event_features(event, market_reaction=view.completed_bars)\
return forecast(fold_event_model.predict(x), horizon=H)

**Falsification / rejection.** Reject if only corrected/revised event data are available, if receipt latency is missing, if the edge precedes local availability, or if unlicensed text is required.

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **RESEARCH BOUNDARY** Generative AI is not required or permitted in the trading loop; only deterministic, versioned event transforms may enter a certified bundle.
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 7.1 Advanced structural extensions across tiers

## A27 Jump continuation-versus-reversal mixture

  -----------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                          **Natural horizon**   **Output**                       **Primary nuisance**
  -------------------------------------- --------------------- -------------------------------- -------------------------------------------
  T1+: high-quality minute/second bars   2-30 minutes          mixture-weighted jump forecast   feed spikes and post-hoc branch selection

  -----------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Information jumps tend to persist while liquidity or mechanical jumps can reverse. A single predeclared mixture model estimates the branch probability instead of choosing the profitable sign after inspection. **^\[R33\]^**

**Estimand.** The conditional post-jump return and calibrated probability of continuation versus reversal given jump size, market co-jump, volume and decay state.

**Bounded parameter domain.** jump threshold k=3-6; wait 1-5 bars; bipower window 20-120m; horizon 2-30m; mixture capacity fixed

spotBV_t = BV_t(W)/W ; J_t = 1{\|r_t\| \> k sqrt(spotBV_t)}

mu_t = J_t \[pi(X_t) mu_cont(X_t) + (1-pi(X_t)) mu_rev(X_t)\]

**Causal implementation.** Detect jumps from completed observations, quarantine data-quality spikes, and fit the gate and both conditional means jointly inside each fold.

spot_var = causal_bipower_variation(view, W, normalized_per_bar=True)\
jump = abs(view.ret) \> k \* sqrt(spot_var)\
x = jump_state_features(view).lagged()\
p, mu_c, mu_r = fold_mixture_state.predict(x)\
return forecast(jump \* (p\*mu_c + (1-p)\*mu_r), H)

**Falsification / rejection.** Reject if a one-component model is indistinguishable, leave-one-event-out results are unstable, or the selected branch is not probability-calibrated out of sample.

## A28 Opening efficient-price state model

  ----------------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                            **Natural horizon**   **Output**                              **Primary nuisance**
  ---------------------------------------- --------------------- --------------------------------------- ---------------------------------------------
  T2: opening bars + synchronized quotes   5-30 minutes          filtered efficient-price displacement   smoothing leakage and auction contamination

  ----------------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Observed opening prices mix a latent efficient-price innovation with transient opening noise whose variance changes with participation and clock time. **^\[R07\]\ \[R24\]^**

**Estimand.** The filtered, not smoothed, posterior expectation of the efficient price minus the current executable price.

**Bounded parameter domain.** opening filter 3-15m; 1-3 switching states; synchronized-quote age \<=2s; process/measurement variance nested; horizon 5-30m

S_t in {1..K}; p\*\_t=p\*\_{t-1}+xi_t, Var(xi_t)=Q\_{S_t}; mid_t=p\*\_t+eta_t, Var(eta_t)=R\_{S_t}(volume,clock)

mu_t(h) = E\[p\*\_{t+h}-executable_mid_t \| F_t\], using only filtered P(S_t,p\*\_t \| F_t)

**Causal implementation.** Use only forward filtering p(state_t\|y_1:t); smoothing p(state_t\|y_1:T) is banned for historical signals. Reset and warm up at the session boundary.

state = causal_switching_kalman_filter(view.opening_bars, view.quotes, fold_state)\
score = state.filtered_mean - synchronized_executable_mid(view.quotes)\
return forecast(score / sqrt(state.filtered_var + eps), H)

**Falsification / rejection.** Reject if the static opening-gap baseline is not beaten, if alternative initializations alter the sign, or if filtering delay consumes the edge.

## A29 Cross-sectional dispersion-shock allocation

  ----------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                   **Natural horizon**   **Output**                                  **Primary nuisance**
  ------------------------------- --------------------- ------------------------------------------- --------------------------------------
  T1: synchronized minute panel   5-45 minutes          continuation/reversal probability by name   disguised sector and volatility bets

  ----------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Extreme residual dispersion may represent differentiated information or temporary de-risking pressure. The allocation decision depends on which mechanism is supported by breadth, volume and sector state.

**Estimand.** The future sector-neutral residual return conditional on stock shock and market-wide dispersion state.

**Bounded parameter domain.** dispersion 90-99%; accumulation 5-30m; probability shrinkage fixed/nested; horizon 5-45m

D_t = sqrt(sum_i w_i epsilon_i,t\^2); J_D,t=I(D_t \> Q_train(q_D)); z_i,t=epsilon_i,t/sigma_i,t

mu_i,t = J_D,t \[2 pi_i,t - 1\] z_i,t sigma_i,t ; pi=P(continuation\|X_i,t,D_t)

**Causal implementation.** Build the cross-section at a barrier after all required bars are complete, record the denominator, and shrink branch probabilities toward one-half.

disp = sqrt(weighted_mean(square(view.residual_return), pit_weights(view)))\
shock = disp \> fold_quantile(disp.history, q_D)\
x = \[cs_robust_z(view.residual_return),disp,breadth(view),volume_z(view)\]\
p = fold_calibrated_logit(x)\
return forecast(shock\*(2\*p-1)\*x\[0\]\*causal_vol(view), H)

**Falsification / rejection.** Reject if sector-neutral construction removes the result, if probabilities are uncalibrated, or if dispersion thresholds are isolated spikes.

## A30 Sector-flow rotation

  ------------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                    **Natural horizon**   **Output**                                 **Primary nuisance**
  -------------------------------- --------------------- ------------------------------------------ ----------------------------------------------
  T1: minute OHLCV + PIT sectors   10-60 minutes         sector and constituent relative forecast   target leakage into its own sector aggregate

  ------------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Persistent allocation waves across sectors may predict sector residual returns, while constituents respond with heterogeneous delay. **^\[R24\]^**

**Estimand.** The incremental predictive effect of lagged sector signed participation on future sector and leave-one-out constituent residuals.

**Bounded parameter domain.** sector-flow lags 1-30m; 1-3 states; 20-120 session fit; horizon 10-60m

Q_s,t = sum\_{i in s} sign(epsilon_i,t) V_i,t / E_train\[V_i,t \| same-clock, session type\]

\[R_s,t+1,Q_s,t+1\]\' = A_z \[R_s,t,Q_s,t\]\' + nu_t+1

**Causal implementation.** Exclude the target stock from mapped sector pressure, lag all flow proxies, and estimate any regime/state process solely inside training folds.

q_sector = leave_one_out_sector_flow(view, signed_volume_proxy(view))\
state = fold_markov_var.filter(\[sector_resid(view), q_sector\])\
return forecast(map_sector_to_stock(state.predicted_return, view), H)

**Falsification / rejection.** Reject if Granger-style predictive restrictions fail out of sample, regime labels are unstable, or the static ridge VAR performs as well.

## A31 Quote-revision excitation

  ---------------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**              **Natural horizon**   **Output**                                  **Primary nuisance**
  -------------------------- --------------------- ------------------------------------------- ------------------------------------------------------
  T2: ordered quote events   1-20 seconds          integrated directional revision intensity   batched timestamps create artificial self-excitation

  ---------------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Clusters of upward or downward quote revisions may reveal persistent reassessment of fair value rather than isolated noise. **^\[R09\]\ \[R34\]^**

**Estimand.** The expected imbalance of future up- and down-revision intensities over the executable horizon.

**Bounded parameter domain.** kernel decay 0.1-30s; 2-6 event types; spectral radius \<1; horizon 1-20s

lambda\_+(t)=mu\_+ + sum\_{e_k\<t} phi\_{+,type(k)}(t-e_k) ; similarly lambda\_-(t)

mu_t(h) proportional to integral_t\^{t+h} \[lambda\_+(u)-lambda\_-(u)\] du

**Causal implementation.** Preserve event ordering, define deterministic ties, constrain Hawkes kernels positive and the excitation matrix spectral radius below one.

events = ordered_quote_revisions(view.quotes)\
state = stable_hawkes_filter(events, params=fold_state)\
return forecast(state.integrated_intensity(\'up\',H)-state.integrated_intensity(\'down\',H), H)

**Falsification / rejection.** Reject if time-shift placebos retain the effect, the stability constraint fails, or achievable latency exceeds the excitation decay.

## A32 Flow-toxicity conditional markout

  -------------------------------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                        **Natural horizon**   **Output**                                   **Primary nuisance**
  ------------------------------------ --------------------- -------------------------------------------- -----------------------------------------------------
  T2: synchronized trades and quotes   5-120 seconds         adverse-selection probability / alpha gate   fixed toxicity thresholds treated as universal laws

  -------------------------------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Fast, one-sided aggressive flow can be more informed than balanced flow; the future signed midpoint markout measures toxicity directly. **^\[R08\]\ \[R09\]^**

**Estimand.** E\[q_t(mid_t+h-mid_t)\|imbalance, duration, spread, volatility, depth\], where q_t is aggressor sign.

**Bounded parameter domain.** volume buckets 0.05-0.5% ADV; horizons 5-120s; classifier and calibration grids bounded

tox_t(h) = E\[q_t (mid_t+h-mid_t) \| X_t\]

permit passive liquidity only if posterior P(tox_t(h) \> hurdle) is below the risk threshold

**Causal implementation.** Use quote-matched trade signs with uncertainty, predeclared volume buckets, and strictly future markouts. Deploy first as an execution gate, not necessarily a standalone position.

signed = classify_trades(view.trades, view.quotes)\
x = toxicity_features(signed, view).lagged()\
markout = fold_calibrator.predict(x)\
return forecast_or_gate(markout, mode=params.mode, horizon=H)

**Falsification / rejection.** Reject if toxicity adds nothing beyond ordinary OFI, bucket definitions are unstable, or alternative trade classifiers reverse conclusions.

## A33 Transient-permanent impact propagator

  --------------------------------------------------------------------------------------------------------------------
  **Data tier**                **Natural horizon**   **Output**                       **Primary nuisance**
  ---------------------------- --------------------- -------------------------------- --------------------------------
  T2: signed trades + quotes   1-120 seconds         expected residual impact decay   endogenous raw order flow

  --------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Observed price impact combines a transient component that decays and a permanent informational component. Expected decay can support reversion or warn against fading informed flow. **^\[R25\]\ \[R26\]^**

**Estimand.** The future change in a constrained propagator response to innovations in signed flow.

**Bounded parameter domain.** propagator decay 1-300s; 3-10 nonnegative bases; horizon 1-120s; flow-innovation model nested

qtilde_t=q_t-E\[q_t\|F_t-1\]; p_t=p\*\_t+sum\_{k\>=0}G(k) qtilde\_{t-k}+epsilon_t

G(k)=G_inf+(G_0-G_inf) exp(-k/tau); mu_t(h)=sum_k qtilde\_{t-k}\[G(k+h)-G(k)\]

**Causal implementation.** Fit nonnegative decay bases on flow innovations inside folds; serialize the response curve and condition on liquidity state.

q_innov = signed_flow(view) - fold_flow_model.predict(view)\
G = fold_nonnegative_propagator.response_curve\
score = expected_response_change(q_innov.history, G, horizon=H)\
return forecast(score, H)

**Falsification / rejection.** Reject if transient and permanent components are unidentified, if response curves violate stability/no-arbitrage diagnostics, or if costs dominate expected decay.

## A34 Multi-level depth-shape pressure

  -----------------------------------------------------------------------------------------------------------------------
  **Data tier**                        **Natural horizon**   **Output**                  **Primary nuisance**
  ------------------------------------ --------------------- --------------------------- --------------------------------
  T2: synchronized multi-level depth   1-30 seconds          depth-resistance forecast   stale deeper levels

  -----------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Liquidity asymmetry beyond the best quote changes resistance to directional movement and may add information beyond top-book imbalance. **^\[R09\]^**

**Estimand.** The incremental midpoint forecast from normalized imbalance across depth levels conditional on top-book OFI.

**Bounded parameter domain.** K=5-20 levels; fused-lasso penalty log grid; horizon 1-30s; same-clock depth normalization

I_t(k)=(B_t(k)-A_t(k))/(B_t(k)+A_t(k))

mu_t(h)=sum\_{k=1..K} w_k I_t(k) ; fused penalty sum_k \|w_k-w\_{k-1}\|

**Causal implementation.** Normalize each level by same-clock typical depth, require synchronized snapshots/events, and fit smooth/fused weights inside folds.

shape = normalized_depth_imbalance(view.depth, levels=K, same_clock=True)\
w = fused_lasso_fit(shape.train, target.train, lam_fused)\
return forecast(shape.now @ w, H)

**Falsification / rejection.** Reject if deeper levels add no nested value beyond top-book OFI, if missing updates alter shape materially, or if latency makes levels non-executable.

## A35 Cancellation and placement pressure

  ----------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                             **Natural horizon**   **Output**                              **Primary nuisance**
  ----------------------------------------- --------------------- --------------------------------------- --------------------------------
  T2: ordered add/cancel/execution events   1-20 seconds          displayed-liquidity pressure forecast   ephemeral or spoof-like orders

  ----------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Asymmetric willingness to add or withdraw displayed liquidity may precede price movement, conditional on actual trades and persistence. **^\[R09\]^**

**Estimand.** The incremental markout from side-specific addition-minus-cancellation intensities after trade-flow and OFI controls.

**Bounded parameter domain.** quantity intensity normalized by depth and seconds; resting-time 50ms-5s; decay 0.05-10s; lags 1-20s

lambda_e\^side(t)=EWMA(quantity_e\^side / (prevailing_depth\^side \* second)); psi_t=(lambda_add\^bid-lambda_cancel\^bid)-(lambda_add\^ask-lambda_cancel\^ask)

Delta mid_t:h = theta psi_t + gamma\' \[OFI, trade_flow, spread, volatility\] + e_t:h

**Causal implementation.** Require deterministic message sequencing, minimum resting-time and persistence filters; fit distributed lags or stable multivariate excitation models.

events = classified_book_events(view.depth_events)\
psi = normalized_add_cancel_intensity(events, depth=view.depth, min_rest_ms=R)\
return forecast(fold_model.predict(\[psi, ofi(view), signed_flow(view)\]), H)

**Falsification / rejection.** Reject if cancellations add no information beyond trades/OFI, if minimum-rest filters reverse the sign, or if event identity is incomplete.

## A36 Hidden-liquidity replenishment inference

  ----------------------------------------------------------------------------------------------------------------------------------------
  **Data tier**                             **Natural horizon**   **Output**                              **Primary nuisance**
  ----------------------------------------- --------------------- --------------------------------------- --------------------------------
  T2: sequence-complete book + executions   5-60 seconds          posterior support/resistance forecast   false iceberg inference

  ----------------------------------------------------------------------------------------------------------------------------------------

**Economic mechanism.** Repeated replenishment at one price after executions can indicate reserve liquidity that resists further movement, but hidden size is latent and must remain probabilistic. **^\[R09\]\ \[R10\]^**

**Estimand.** The future markout conditional on the posterior probability and entropy of latent reserve liquidity at bid or ask.

**Bounded parameter domain.** sequence-complete book; 3-10 replenishments over 1-60s; latent-state prior grid; horizon 5-60s; entropy cap

pi_t=P(H_t\>0 \| refill_count, executed_volume, queue_resets)

direction_t=+1 for inferred hidden bid, -1 for inferred hidden ask; mu_t(h)=direction_t theta_h pi_t

**Causal implementation.** Use a hidden-state filter updated only by observed events; never label an iceberg deterministically or infer it from OHLC/depth snapshots.

posterior = hidden_liquidity_filter.update(view.book_events)\
score = posterior.side_sign \* fold_theta\[H\] \* posterior.prob_reserve\
return forecast(score, H, uncertainty=posterior.entropy)

**Falsification / rejection.** Reject without reliable order/event identity, if posterior probability adds no future markout, or if high entropy is not translated into lower/no exposure.

# Part III --- Forecast combination, portfolio and execution mathematics

# 8. From heterogeneous scores to comparable expected returns

mu_hat_k,i,t = g_k,fold(score_k,i,t, session_t, regime_t) ; all g_k are fitted within training folds

mu_hat_i,t = sum_k w_k,t mu_hat_k,i,t ; w_t = argmin \|\|y-Mw\|\|\_2\^2 + lambda_2\|\|w\|\|\_2\^2 + lambda_1\|\|w\|\|\_1

Always compare a candidate ensemble with equal-weight, ridge and best-single-family baselines. Use leave-one-family-out ablation and constrain maximum family weights. Regime-specific weights shrink toward a global vector:

w_g \~ N(w_0, tau\^2 I) ; small regimes imply stronger posterior shrinkage toward w_0

-   Only combine forecasts evaluated on identical outer folds, data snapshots, cost models and capital contexts.

-   Cluster candidates by outer-test daily net returns; nearby parameter variants are one strategy family, not diversification.

-   A second or third family must add incremental net utility after ablation, delay and cost stress.

-   If calibration is unstable, use rank or sign forecasts with wider no-trade bands rather than fabricated precision.

# 9. Small-capital portfolio optimization

max_x mu_hat\' x - (lambda/2) x\' Sigma_hat x - TC(x-x0) - delta \* TailRisk(x)

subject to cash, gross, net, name, sector, beta, participation, order-count, shortability and time-to-flat constraints

x_i = q_i P_i ; q_i in integers ; TC includes fixed per-order costs, so the exact problem is non-convex

1.  Solve a continuous, shrinkage-covariance target with conservative expected returns.

2.  Drop trades whose incremental expected benefit does not exceed stressed marginal cost plus uncertainty.

3.  Apply no-trade bands and net opposing alpha intents before routing.

4.  Round to integer shares and tick-valid prices; recompute all constraints and fees.

5.  Run deterministic add/drop/swap local search; reject any move that reduces robust utility.

## 9.1 Covariance and uncertainty

Sigma_hat = rho F + (1-rho) S, where F is a structured target and rho is fold-estimated shrinkage

mu_robust = mu_hat - kappa_mu \* SE(mu_hat) \* sign(mu_hat)

At capital below INR 10 lakh, exact neutrality can create uneconomic tickets. Treat market/sector neutrality as tolerances with explicit shadow prices rather than absolutes that force churn. **^\[R12\]^**

# 10. Transaction costs, fills and turnover

TC_order = brokerage + statutory + spread + impact + latency + adverse_selection

impact_bps = kappa_session,liq \* (notional / ADV_interval)\^psi ; estimate and stress kappa, psi

implementation_shortfall = side \* (fill_price - decision_mid) + explicit_fees

  ------------------------------------------------------------------------------------------------------------------------
  **Fidelity tier**   **Fill rule**                                                             **Permitted conclusion**
  ------------------- ------------------------------------------------------------------------- --------------------------
  F0 screen           next-bar return minus conservative rough cost                             feature triage only

  F1 event bars       next-event aggressive protected limit; partial/reject/timeout states      T1 candidate comparison

  F2 quote/trade      price-through, participation, latency and adverse-selection calibration   T2 certification

  F3 auction          auction-state rules and observed clearing fills                           T3 auction certification
  ------------------------------------------------------------------------------------------------------------------------

trade Delta x only if Delta expected benefit \> stressed marginal cost + estimation buffer

Turnover is an output of the joint forecast/portfolio/execution problem. Search cadence, holding horizon, hysteresis, minimum ticket, forecast expiry and order netting; do not maximize gross alpha and retrofit fees later.

# Part IV --- Honest validation and anti-voodoo statistics

# 11. Nested chronological research design

1.  Reserve a final lockbox before feature or parameter inspection; make the data layer refuse it below the release stage.

2.  Within development history, use nested chronological walk-forward folds; never randomize rows.

3.  Fit every scaler, factor model, peer set, universe policy, parameter and calibrator inside the training fold.

4.  Purge labels whose horizon overlaps validation and embargo at least the maximum holding horizon plus live order duration.

5.  Choose a stable parameter plateau or posterior region, not the observed argmax.

6.  Freeze one complete selection procedure and evaluate it once on the lockbox. Multiple finalists require simultaneous multiplicity-aware inference; selecting the best lockbox result is forbidden.

outer loss estimates the performance of the complete selection procedure, not merely a model fitted once

# 12. Dependence-aware inference

t_HAC = mean(d_t) / sqrt(HAC_var(mean(d_t))) ; bandwidth predeclared from horizon/decay

stationary/block bootstrap resamples days or weeks, never individual overlapping minute labels

Report confidence intervals for mean daily net return, rank-IC, turnover and cost share, plus bootstrap distributions and sensitivity intervals for path-dependent drawdown. Minute observations are not independent replicates and their Sharpe ratio is never annualized as if they were. **^\[R13\]\ \[R14\]^**

# 13. Search multiplicity and promotion

M_erank = (sum_j lambda_j)\^2 / sum_j lambda_j\^2, an effective-rank sensitivity heuristic---not an exact independent-trial count

Every viewed, failed, abandoned, manually adjusted, alternative-universe, cost and seed variant remains in the registry. Report the literal trial count M, M_erank and a stationary-bootstrap null distribution of the maximum Sharpe that preserves cross-trial dependence. Use family-level false-discovery control for screening and selection-aware tests for finalists.

  -------------------------------------------------------------------------------------------------------------------------------------------------
  **Diagnostic**        **Question**                                                                   **Use**
  --------------------- ------------------------------------------------------------------------------ --------------------------------------------
  Deflated Sharpe       Is the observed Sharpe exceptional after non-normality and number of trials?   selection-adjusted significance diagnostic

  PBO/CSCV              How often does the selected winner rank poorly out of sample?                  selection-instability diagnostic

  SPA / Reality Check   Does any candidate beat a benchmark under dependence and data snooping?        finalist differential test

  FDR                   What expected false-discovery proportion does the procedure control?           family-level screen control

  Null search           What best score appears when features/labels are destroyed coherently?         pipeline sanity check
  -------------------------------------------------------------------------------------------------------------------------------------------------

These diagnostics complement economic and operational evidence; none converts an overfit backtest into a strategy. **^\[R15\]\ \[R16\]\ \[R17\]\ \[R18\]\ \[R20\]^**

## 13.1 Explicit selection-aware statistics

PSR(SR\*) = Phi\[(SR_hat-SR\*) sqrt(T-1) / sqrt(1-gamma_3 SR_hat + ((gamma_4-1)/4) SR_hat\^2)\]

SR\* \~= mu_SR + sigma_SR{(1-gamma_E)Phi\^-1(1-1/N) + gamma_E Phi\^-1(1-1/(eN))}, N\>=2

gamma_4 is raw kurtosis (normal=3); if code stores excess kurtosis kappa, use kappa+2 in place of gamma_4-1. The expected-maximum approximation is evaluated with N=M and N=M_erank as sensitivity cases, never as an exact correlation correction. Non-overlapping periods may still be dependent, so bootstrap/HAC evidence remains primary. **^\[R17\]\ \[R27\]^**

CSCV: split chronology into even S blocks; C=choose(S,S/2); k\*\_c=argmax_k ISperf(k,c); lambda_c=log(r_c/(M+1-r_c)); PBO=C\^-1 sum_c I(lambda_c\<=0)

Each symmetric half-block split is boundary-purged. r_c is the out-of-sample rank of the in-sample winner, ordered 1=worst to M=best. Report the logit-rank distribution and degradation curve. PBO diagnoses selection instability; chronological walk-forward remains the deployment estimate. **^\[R18\]^**

d_k,t=u_k,t\^net-u_0,t\^net; H0: max_k E\[d_k,t\] \<= 0; T_SPA=max(0,max_k sqrt(n) mean(d_k,t)/omega_hat_k)

omega_hat_k estimates the long-run standard deviation of sqrt(n) mean(d_k,t); the SPA p-value uses a stationary bootstrap plus Hansen recentering. Romano-Wolf stepdown or a model-confidence set is used when deciding which survivors remain statistically distinguishable. **^\[R16\]\ \[R29\]\ \[R30\]^**

## 13.2 Hierarchical uncertainty and causal regimes

mu_k \| mu_f,tau_f \~ N(mu_f,tau_f\^2); ybar \| mu \~ N(mu,S_HAC/bootstrap)

E\[mu_k\|y\] = B_k mu_f + (1-B_k)ybar_k; B_k = s_k\^2/(s_k\^2+tau_f\^2)

s_k\^2 is the dependence-robust variance of an estimated mean, not raw return variance. Joint S_HAC/bootstrap or decorrelated family summaries are required for correlated variants. Partial pooling can mitigate noise only when all trials and dependence are modeled; it does not replace selection correction. **^\[R31\]\ \[R32\]^**

p_t(s)=P(S_t=s\|F_t) only if observation t precedes decision; otherwise use P(S_t=s\|F_t-1); mu_hat_i,t=sum_s p_t(s)mu_hat_i,t,s

Any regime-switching alpha or ensemble must serialize the filtered state and transition law. Smoothed P(S_t\|F_T), T\>t, is prohibited from trading, feature selection, hyperparameter tuning and reported causal performance. **^\[R24\]^**

# 14. Mandatory falsification battery

  --------------------------------------------------------------------------------------------------------------------------
  **Axis**        **Perturbation**                                                **Failure interpretation**
  --------------- --------------------------------------------------------------- ------------------------------------------
  Time            one/two-bar delay; start-time jitter; drop best month           fragile timing or event concentration

  Parameters      +/-25%; neighboring plateau; simpler parent                     isolated optimum or redundant complexity

  Universe        N +/- buffer; stable core; leave-sector-out; delisted history   selection/survivorship dependence

  Costs/fills     1.5x/2x variable cost; partial/missed fills; wider spreads      implementation-only edge

  Nulls           block-shuffled labels; randomized ranks; placebo clocks         broken causal or statistical harness

  Concentration   leave-stock/day/session/regime-out                              single-event backtest

  Operations      feed gap, reconnect, broker reject, unknown order, restart      unsafe live state machine
  --------------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **PERMANENT CANARY** Keep one deliberately cheating look-ahead alpha in the test suite. It must look spectacular in an unsafe harness and fail every production research path. If it ever passes, the infrastructure---not the market---has changed.
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# Part V --- Complete repository construction

![BreezeReader emits canonical market events directly to both immutable snapshots and the Rust live engine; Python remains offline, while a separate broker adapter alone can submit orders.](media/image1.png){width="6.35in" height="3.2084208223972004in"}

Figure 1. Breeze is the sole certified signal-data boundary. Python is not in the live path; only Rust may turn a signed bundle into broker order intent.

# 15. Repository tree

alphaforge/\
pyproject.toml Cargo.toml justfile .env.example\
config/ costs/ gates/ search_spaces/ calendars/ live/\
schemas/ alpha_spec/ forecast/ strategy_bundle/ order_intent/ execution_event/\
data/ bronze/ silver/ gold/ quarantine/ snapshots/ universes/\
python/alphaforge/\
core/ time.py asof.py money.py ids.py config.py\
data/ breeze/ raw_store/ qc/ instruments/ corporate_actions/ pit/\
universe/ eligibility.py liquidity.py snapshots.py\
features/ dag.py primitives.py residuals.py microstructure.py\
alphas/ t1/ t2/ t3/ manifest.py\
models/ calibration.py shrinkage.py state_space.py\
sim/ vector.py events.py fills.py accounting.py\
costs/ statutory.py spread.py impact.py adverse_selection.py\
validation/ folds.py purge.py bootstrap.py dsr.py pbo.py spa.py nulls.py\
search/ registry.py budgets.py funnel.py plateaus.py pareto.py\
portfolio/ covariance.py optimizer.py rounding.py netting.py\
certification/ dossiers.py trial_root.py\
bundles/ build.py sign.py validate.py\
rust/crates/\
domain/ math-kernel/ math-python/ market-protocol/ market-breeze/ bars/\
feature-ir/ alpha-ir/ portfolio-ir/ strategy-bundle/ event-reducer/ sim-venue/\
broker-protocol/ broker-flattrade/ broker-zerodha/ oms/ risk/ accounting/\
journal/ replay/ telemetry/ engine/\
apps/ breeze-reader/ live-engine/ shadow-engine/ replay-engine/ backfill/ research-runner/\
fixtures/ bars/ quotes/ orders/ costs/ golden_days/ leakage_canaries/\
tests/ unit/ property/ integration/ parity/ chaos/\
ops/ services/ dashboards/ alerts/ runbooks/\
docs/ STATE.md DECISIONS.md DATA_DICTIONARY.md MODEL_CARDS.md INCIDENTS.md

# 16. Dependency rule and authority boundaries

  ----------------------------------------------------------------------------------------------------------------------
  **Layer**            **May depend on**                                   **Must not depend on**
  -------------------- --------------------------------------------------- ---------------------------------------------
  domain/schemas       standard library, serialization                     network clients, strategy implementations

  data/features        domain, raw/PIT stores                              broker order placement

  alphas/models        AsOf view, feature primitives                       future rows, OMS, live secrets

  sim/validation       alphas, costs, portfolio, registry                  live broker adapter

  Rust engine          signed bundle, deterministic primitives, risk/OMS   Python notebooks or unversioned model state

  BreezeDataAdapter    authentication, subscriptions, raw capture          order intent or portfolio logic

  BrokerOrderAdapter   order/position/fill/reconcile endpoints             alpha estimation or Breeze credentials
  ----------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **SEPARATE APIS** Breeze is a read-only market-data boundary. FlattradeOrderAdapter or ZerodhaOrderAdapter is the only order boundary. The core engine knows neither vendor\'s response shapes; adapters translate to versioned domain events.
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Run BreezeReader and LiveEngine as separate operating-system processes. BreezeReader possesses only Breeze credentials and publishes length-prefixed canonical MarketEvents over a local Unix-domain socket while persisting exact raw payloads. LiveEngine possesses only the selected execution broker\'s credentials. A Breeze outage blocks new risk; broker quotes cannot silently substitute for the certified signal feed.

## 16.1 Bitemporal lineage and immutable evidence

usable(r,t) iff r.valid_from \<= t \< r.valid_to and r.known_from \<= t \< r.known_to; open intervals use +infinity

snapshot_root = MerkleRoot(sort(object_path \|\| SHA256(bytes))); experiment_id = H(code \|\| snapshot_root \|\| config \|\| runtime)

Raw payloads are append-only and content addressed. A correction closes the preceding known_to and creates a new knowledge-time version; it never overwrites what a historical process could have known. Every derived partition carries parent hashes, transformation identity, calendar version, instrument-master version and quality flags. A result without a resolvable snapshot root is not evidence.

MarketRecord { instrument_id, event_type, exchange_ts, receive_ts, source_seq,\
valid_from, valid_to, known_from, known_to, payload_hash, schema_version, quality_flags }\
SnapshotManifest { root_hash, objects\[{path,sha256,bytes,schema_fingerprint}\], parents\[\], created_at,\
calendar_hash, instrument_master_hash, corporate_action_hash, transform_hash, quality_report_hash }

# 17. Versioned schemas

## 17.1 StrategyBundle

StrategyBundle {\
schema_version, bundle_id, strategy_id, parent_experiment_ids, code_hash, build_environment_hash,\
data_snapshot_root, universe_hash, calendar_hash, instrument_master_hash, corporate_action_hash,\
cost_hash, risk_policy_hash, numeric_semantics_version, bar_semantics_version,\
alpha_ir_version, portfolio_ir_version, required_market_data_schema, required_capabilities,\
valid_from, valid_until, broker_context, capital_range, alpha_ir, portfolio_ir, fit_state, calibration,\
session_regime_policy, execution_policy, exit_policy, validation_dossier_hash, trial_registry_root,\
golden_fixture_hashes\[\], content_checksums\[\], signature\
}

During boot, the Rust loader executes the bundle\'s golden fixtures and rejects incompatible semantic versions or unequal quantized output before entering READY.

## 17.2 Order intent and execution truth

OrderIntent { idempotency_key, bundle_id, strategy_id, instrument_id, side, quantity,\
limit_paise, time_in_force, expiry_time, expected_edge_bps, stressed_cost_bps, reason_code, decision_ts }\
ExecutionEvent { broker_order_id, intent_key, broker_update_id, broker_update_seq?, state,\
last_fill_qty, last_fill_price_paise, cumulative_filled_qty, remaining_qty, fees_paise,\
exchange_ts?, receive_ts, reject_code, raw_event_hash }

CREATED -\> RISK_REJECTED \| APPROVED -\> SUBMISSION_PENDING\
SUBMISSION_PENDING -\> ACKNOWLEDGED \| SUBMISSION_UNKNOWN -\> RECONCILING\
ACKNOWLEDGED -\> PARTIALLY_FILLED \| FILLED \| CANCEL_PENDING \| REJECTED \| EXPIRED\
CANCEL_PENDING -\> CANCELLED \| PARTIALLY_FILLED \| FILLED

Cumulative fill is monotone and cannot exceed original quantity; terminal states are absorbing except for an explicit broker-correction event. Network submission is at least once, while logical intent is exactly once through deterministic idempotency keys and reconciliation. Unknown state is never retried blindly, and cross-broker failover is blocked until the original order is positively reconciled.

## 17.3 Canonical event envelope and audit chain

EventEnvelope { schema_version, session_id, run_id, journal_seq, event_id, event_type,\
source, source_priority, source_seq?, exchange_ts?, receive_ts, ingest_ts, correlation_id,\
causation_id, payload, previous_hash, event_hash }\
market_causal_key=(effective_exchange_ts,source_priority,source_seq_or_max,receive_ts,event_id)\
replay_order=journal_seq; event_hash=SHA256(canonical_bytes(journal_seq \|\| header \|\| payload \|\| previous_hash))

The gateway applies the causal key only inside a bounded configured reorder window and advances an explicit watermark. An arrival behind the watermark becomes LateMarketEvent: it is journaled but cannot mutate a finalized bar. Broker/operator events use receipt order. The monotone journal_seq is the sole recovery order; replay never re-sorts the journal. Reducers are deterministic, duplicate IDs are idempotent, and checkpoints bind state hash to the final event hash before new risk is admitted.

# 18. Determinism and Python/Rust parity

-   Canonicalize configs and schemas before SHA-256 hashing; every artifact and log carries config, data, code and runtime identities.

-   Prefer one canonical feature/state engine in Rust exposed to Python through a narrow binding. If implemented twice, require shared golden vectors for every primitive.

-   Replay a recorded day through Python reference execution and Rust production; byte-compare canonical OrderIntent streams.

-   Use deterministic reductions, stable sorting, explicit seeds and controlled numerical tolerances. Any permitted tolerance is part of the schema.

-   The Rust loader rejects unknown nodes, schema mismatch, missing cost/risk versions, bad checksums and parity failure.

def parity_test(day, bundle):\
py = canonical_jsonl(python_reference_replay(day, bundle))\
rs = canonical_jsonl(rust_engine_replay(day, bundle))\
assert sha256(py) == sha256(rs)\
assert py == rs

## 18.1 Typed alpha and portfolio intermediate representation

AlphaIR := DAG\<NodeId, Node{op, typed_inputs, params, warmup, causality_tag,\
missingness_policy, numeric_policy}\>\
PortfolioIR := {forecast_calibration, netting, covariance_state, objective,\
hard_constraints, rounding_policy, exit_policy}\
Only registered operations cross the bundle boundary; arbitrary Python callables cannot be signed.

The canonical mathematical kernel lives in Rust and is exposed to Python through a narrow PyO3 binding for research. This removes semantic drift in rolling windows, tie-breaking, missingness and numeric edge cases. A pure-Python reference remains small and deliberately slow for oracle tests; it is not a second production truth.

semantics(op, fixture, numeric_policy)\_Python == semantics(op, fixture, numeric_policy)\_Rust

Certified boundary types are PricePaise:i64, Quantity:i64, NotionalPaise:i128, RateQ12:i64, ScoreQ8:i64 and TimestampNs:i64. f64 is confined to the canonical math kernel; NaN or infinity cannot cross a schema boundary, invalid division yields explicit null, and overflow rejects the decision. Default rounding is half-to-even unless a declared venue tick rule requires floor or ceiling; equal scores sort by instrument_id.

A floating-point oracle may differ by at most two ULP on designated primitive tests. Tolerance is zero for bar membership, null masks, quantized scores, ranks, target quantities, risk decisions, OrderIntents, fills, fees, cash and state hashes. Release parity is staged from schema through primitive, feature, score, target, intent, accounting and crash recovery.

# 19. Test architecture

  ------------------------------------------------------------------------------------------------------------------
  **Suite**     **Examples**                                                              **Release effect**
  ------------- ------------------------------------------------------------------------- --------------------------
  Unit          closed-form costs, RZ, residuals, covariance, bar boundaries              blocks merge

  Property      no future access, accounting conservation, idempotent state transitions   blocks merge

  Golden        shared Python/Rust bars, features, intents, fees and replay days          blocks bundle release

  Statistical   null-search calibration, DSR/PBO/SPA fixtures, bootstrap coverage         blocks promotion

  Chaos         disconnect, duplicate ack, timeout, restart, stale feed, circuit state    blocks live feature flag

  Shadow        live feed with simulated orders; TCA and parity drift                     blocks capital ramp
  ------------------------------------------------------------------------------------------------------------------

## 19.1 Research invariants

assert feature.max_source_ts \<= decision_ts\
assert fill.ts \> decision_ts\
assert registry.is_append_only\
assert pnl_gross - costs == pnl_net\
assert broker_positions == reconciled_internal_positions\
assert no_open_position_after(flatten_deadline)\
assert shuffled_future_alpha_fails_promotion\
assert repeated_run_hashes_are_equal

# 20. Build sequence and gates

  --------------------------------------------------------------------------------------------------------------------------------------
  **Phase**          **Construction**                                                   **Exit evidence**
  ------------------ ------------------------------------------------------------------ ------------------------------------------------
  P0 Foundation      schemas, config identity, calendar, fixtures, AsOf view, CI        determinism and leakage canary pass

  P1 Data            Breeze raw capture/backfill, QC, PIT masters, universe snapshots   sample days reconcile; gaps explicit

  P2 Research        T1 features/alphas, registry, vector screens, null search          family-balanced signal cards

  P3 Simulation      event engine, costs/fills, nested WFO, stress battery              paise accounting and honest outer reports

  P4 Certification   multiplicity stack, Pareto selection, bundles, signatures          zero to five surviving bundles; lockbox once

  P5 Rust            feature parity, portfolio, risk, OMS, adapters, recovery           golden replay and chaos tests

  P6 Shadow          live data, simulated orders, TCA, incident drills                  operational evidence over predeclared sample

  P7 Limited live    unlevered one-bundle ramp with independent risk                    capital advances by evidence, not elapsed days
  --------------------------------------------------------------------------------------------------------------------------------------

# 21. Operational risk state machine

BOOTSTRAP -\> VERIFYING -\> RECONCILING -\> WARMUP -\> READY -\> ACTIVE -\> DEGRADED

any risk-bearing state -\> HALTED -\> FLATTENING -\> FLAT -\> LOCKED

q_i\^+ = q_i\^broker + sum\_{buy orders}(q_o-f_o); q_i\^- = q_i\^broker - sum\_{sell orders}(q_o-f_o)

e_hat_i=executable_mid_i max(\|q_i\^-\|,\|q_i\^+\|); sum_i e_hat_i/Equity \<= G_max

Cash - sum\_{live buys} q_remaining P_limit - Fees_upper \>= CashFloor

Pre-trade risk is evaluated against every live order as if it fills and against the broker-reconciled position, not merely the optimistic internal target. Pending cancels continue to consume exposure until positively acknowledged.

DEGRADED permits only exposure-reducing actions. A hard halt cannot automatically return to ACTIVE; reactivation requires broker reconciliation, healthy data for a configured stabilization interval and authenticated human approval.

  --------------------------------------------------------------------------------------------------------------------------------
  **Trigger**              **Immediate action**                                      **Invariant**
  ------------------------ --------------------------------------------------------- ---------------------------------------------
  Breeze feed stale/gap    stop new decisions; invalidate affected features          positions remain known and risk-managed

  Broker timeout/unknown   query orders and positions; never resend blindly          at most one live intent per idempotency key

  Position mismatch        cancel new risk; reconcile; require explicit resolution   broker truth is authoritative

  Daily loss/drawdown      cancel entries; controlled flatten                        risk policy cannot be overridden by alpha

  Clock drift              halt timestamp-sensitive decisions                        no event consumed under uncertain ordering

  Flatten deadline         no new risk; repeated bounded exits and alerts            no intended overnight inventory
  --------------------------------------------------------------------------------------------------------------------------------

## 21.1 Deployment, fencing and observability

Deploy one live trading authority. A standby may observe but cannot submit until it acquires a fencing lease and reconciles broker truth. Recommended processes are alphaforge-breeze-reader, alphaforge-live-engine, alphaforge-telemetry, replay/backfill workers and scheduled research/dossier jobs.

Monitor feed age and gaps, watermark lateness, bar latency, feature-null rate, score drift, order/ack/fill latency, rejection rate, unknown-order age, reconciliation differences, projected exposure, P&L, drawdown, implementation shortfall and risk state. Each daily dossier binds bundle, binary, data-snapshot and terminal state-chain hashes.

# Appendix A --- Alpha acceptance checklist

  -----------------------------------------------------------------------------------------------------------------------------
  **Gate**       **Question**
  -------------- --------------------------------------------------------------------------------------------------------------
  Mechanism      Is the predicted behavior tied to a named constraint, information channel, forced flow or liquidity process?

  Causality      Can every input\'s exchange and receipt timestamp be proven \<= decision time?

  Estimator      Are formulas, parameter domains, fit state and regularization versioned?

  Baselines      Does the alpha beat zero, naive sign/rank and its simpler parent on identical folds?

  Economics      Is expected edge positive after broker-specific stressed marginal costs and integer tickets?

  Robustness     Do delay, parameter, universe, cost, concentration and null perturbations pass?

  Multiplicity   Was every viewed trial counted and were family/search corrections applied?

  Operations     Can Rust reproduce the feature, forecast, portfolio and intent from golden fixtures?

  Rejection      Is there a written condition under which the idea will be abandoned?
  -----------------------------------------------------------------------------------------------------------------------------

# Appendix B --- Experiment manifest example

experiment:\
protocol: nested_purged_wfo_v2\
alpha: {id: A04, version: 1.0.0, params: {factor_window: 60d, z_window: 30m}}\
data: {snapshot: nse_cash_1m_2026q3_sha256, tier: T1, asof_policy: strict}\
universe: {policy: liquidity_ranked, n: 150, lookback_days: 60, refresh: weekly}\
session: MID\
broker_context: flattrade\
capital_inr: 500000\
costs: {version: costs_2026_08_28, stress: \[1.0, 1.5, 2.0\]}\
validation: {outer: 21d, inner: 21d, train: 126d, purge: horizon, embargo: 1d}\
seed: 1407\
status: PROPOSED

# Appendix C --- Anti-voodoo rejection list

-   Indicator names without an estimand, economic mechanism or null model.

-   Present-day constituents, eligibility, sector maps or corporate-action knowledge projected backward.

-   Same-bar signal and fill; full-day VWAP/volume used intraday; revised events treated as contemporaneous.

-   Random row train/test splits, reused lockboxes, hidden notebook trials or deleted failures.

-   Sharpe annualized from overlapping minute observations as if independent.

-   Optimization of a full Cartesian grid followed by reporting only the winning path.

-   Passive limit fills assumed from OHLC touches or queue priority inferred from snapshots.

-   Market/sector neutrality imposed without integer, cost and estimation-error consequences.

-   A model accepted because it is mathematically elaborate rather than because it adds robust net value.

-   Automatic live retraining, generative-AI decisions, blind retries or broker failover without reconciliation.

# Appendix D --- Primary research and official interfaces

References provide methodological anchors, not permission to assume transferability to NSE intraday data. Every empirical claim must be re-estimated under the repository\'s point-in-time data, cost, broker and validation contracts.

**\[R01\]** [[Jegadeesh & Titman (1993), Returns to Buying Winners and Selling Losers]{.underline}](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x) --- cross-sectional momentum and delayed price reaction

**\[R02\]** [[Moskowitz, Ooi & Pedersen (2012), Time Series Momentum]{.underline}](https://doi.org/10.1016/j.jfineco.2011.11.003) --- multi-asset time-series momentum methodology

**\[R03\]** [[Lo & MacKinlay (1990), When Are Contrarian Profits Due to Stock Market Overreaction?]{.underline}](https://doi.org/10.1093/rfs/3.2.175) --- cross-sectional contrarian decomposition and microstructure cautions

**\[R04\]** [[Avellaneda & Lee (2010), Statistical Arbitrage in the US Equities Market]{.underline}](https://doi.org/10.1080/14697680903124632) --- PCA/factor residual mean reversion

**\[R05\]** [[Engle & Granger (1987), Co-integration and Error Correction]{.underline}](https://doi.org/10.2307/1913236) --- cointegration representation and testing

**\[R06\]** [[Johansen (1988), Statistical Analysis of Cointegration Vectors]{.underline}](https://doi.org/10.1016/0165-1889(88)90041-3) --- multivariate cointegration rank estimation

**\[R07\]** [[Kalman (1960), A New Approach to Linear Filtering and Prediction Problems]{.underline}](https://doi.org/10.1115/1.3662552) --- state-space filtering

**\[R08\]** [[Hasbrouck (1991), Measuring the Information Content of Stock Trades]{.underline}](https://doi.org/10.1111/j.1540-6261.1991.tb04620.x) --- trade innovations and price impact

**\[R09\]** [[Cont, Kukanov & Stoikov (2014), The Price Impact of Order Book Events]{.underline}](https://doi.org/10.1093/jjfinec/nbt003) --- order-flow imbalance and book events

**\[R10\]** [[Kyle (1985), Continuous Auctions and Insider Trading]{.underline}](https://doi.org/10.2307/1913210) --- liquidity, information and linear price impact

**\[R11\]** [[Almgren & Chriss (2001), Optimal Execution of Portfolio Transactions]{.underline}](https://doi.org/10.21314/JOR.2001.041) --- execution cost/risk trade-off

**\[R12\]** [[Ledoit & Wolf (2004), A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices]{.underline}](https://doi.org/10.1016/S0047-259X(03)00096-4) --- covariance shrinkage

**\[R13\]** [[Newey & West (1987), A Simple Positive Semi-definite HAC Covariance Matrix]{.underline}](https://doi.org/10.2307/1913610) --- serial-correlation robust inference

**\[R14\]** [[Politis & Romano (1994), The Stationary Bootstrap]{.underline}](https://doi.org/10.1080/01621459.1994.10476870) --- dependent-data bootstrap

**\[R15\]** [[White (2000), A Reality Check for Data Snooping]{.underline}](https://doi.org/10.1111/1468-0262.00152) --- selection-bias-aware performance testing

**\[R16\]** [[Hansen (2005), A Test for Superior Predictive Ability]{.underline}](https://doi.org/10.1198/073500105000000063) --- SPA test

**\[R17\]** [[Bailey & Lopez de Prado (2014), The Deflated Sharpe Ratio]{.underline}](https://doi.org/10.3905/jpm.2014.40.5.094) --- Sharpe deflation for selection and non-normality

**\[R18\]** [[Bailey et al. (2017), The Probability of Backtest Overfitting]{.underline}](https://doi.org/10.21314/JCF.2016.322) --- CSCV/PBO selection-instability diagnostic

**\[R19\]** [[Harvey, Liu & Zhu (2016), \... and the Cross-Section of Expected Returns]{.underline}](https://doi.org/10.1093/rfs/hhv059) --- multiple testing in empirical asset pricing

**\[R20\]** [[Benjamini & Hochberg (1995), Controlling the False Discovery Rate]{.underline}](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) --- false-discovery-rate control

**\[R21\]** [[Fama & MacBeth (1973), Risk, Return, and Equilibrium]{.underline}](https://doi.org/10.1086/260061) --- cross-sectional regression and risk adjustment

**\[R22\]** [[Kelly, Pruitt & Su (2019), Characteristics Are Covariances]{.underline}](https://doi.org/10.1016/j.jfineco.2018.12.009) --- instrumented principal-components framework

**\[R23\]** [[Gu, Kelly & Xiu (2020), Empirical Asset Pricing via Machine Learning]{.underline}](https://doi.org/10.1093/rfs/hhaa009) --- high-dimensional prediction with disciplined validation

**\[R24\]** [[Hamilton (1989), A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle]{.underline}](https://doi.org/10.2307/1912559) --- filtered regime probabilities and switching dynamics

**\[R25\]** [[Gatheral (2010), No-Dynamic-Arbitrage and Market Impact]{.underline}](https://doi.org/10.1080/14697680903373692) --- restrictions on transient impact models

**\[R26\]** [[Toth et al. (2011), Anomalous Price Impact and the Critical Nature of Liquidity in Financial Markets]{.underline}](https://doi.org/10.1103/PhysRevX.1.021006) --- latent liquidity and square-root impact

**\[R27\]** [[Lo (2002), The Statistics of Sharpe Ratios]{.underline}](https://doi.org/10.2469/faj.v58.n4.2453) --- serial dependence and Sharpe-ratio inference

**\[R28\]** [[Brown et al. (1992), Survivorship Bias in Performance Studies]{.underline}](https://doi.org/10.1093/rfs/5.4.553) --- survivorship and selection bias

**\[R29\]** [[Romano & Wolf (2005), Stepwise Multiple Testing as Formalized Data Snooping]{.underline}](https://doi.org/10.1111/j.1468-0262.2005.00615.x) --- familywise error control under dependence

**\[R30\]** [[Hansen, Lunde & Nason (2011), The Model Confidence Set]{.underline}](https://doi.org/10.3982/ECTA5771) --- selection among statistically indistinguishable models

**\[R31\]** [[Jorion (1986), Bayes-Stein Estimation for Portfolio Analysis]{.underline}](https://doi.org/10.2307/2331042) --- shrinkage of expected returns

**\[R32\]** [[Carvalho, Polson & Scott (2010), The Horseshoe Estimator for Sparse Signals]{.underline}](https://doi.org/10.1093/biomet/asq017) --- hierarchical shrinkage for sparse effects

**\[R33\]** [[Barndorff-Nielsen & Shephard (2004), Power and Bipower Variation with Stochastic Volatility and Jumps]{.underline}](https://doi.org/10.1016/j.jeconom.2003.10.001) --- realized bipower variation and jump separation

**\[R34\]** [[Hawkes (1971), Spectra of Some Self-Exciting and Mutually Exciting Point Processes]{.underline}](https://doi.org/10.1093/biomet/58.1.83) --- stable self-exciting point-process foundations

**\[D01\]** [[ICICI Direct Breeze API documentation]{.underline}](https://api.icicidirect.com/breezeapi/documents/index.html) --- read-only market-data adapter capability must be verified and snapshotted

**\[D02\]** [[Flattrade Algo Trading / API information]{.underline}](https://flattrade.in/algotrading/) --- separate order adapter and broker capability snapshot

**\[D03\]** [[Zerodha Kite Connect documentation]{.underline}](https://kite.trade/docs/connect/v3/) --- separate order, position and reconciliation adapter

**\[D04\]** [[NSE market data and trading-session documentation]{.underline}](https://www.nseindia.com/static/market-data/market-timings) --- cash-session timing and auction boundaries

# Closing standard

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  **THE PRODUCT** The product is not a strategy list. It is a machine that transforms explicit hypotheses into reproducible evidence, rejects most of them, certifies a small number of costed bundles, and executes only what the independent risk layer can explain and reconcile.
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

This document is an engineering and research specification, not investment, legal, tax or regulatory advice. Confirm current exchange, broker, API and data-entitlement requirements before implementation or trading.
