# Breeze feasibility probe — bar convention, history depth, session boundaries

**2026-08-31, from arb-vm** (rule 14: API calls egress from the whitelisted IP, per SAL-0001).
Probe subject: `RELIND`, NSE cash, `get_historical_data_v2`. A handful of calls, not a sweep.

## 1. Breeze is OPEN-LABELLED — ingest must add one interval `[C-BAR-01]`

This is the finding the whole probe existed for, and §3.5 requires it to be established
empirically rather than assumed.

```
daily bar 2026-08-28   open=1285.4  close=1287.0
  09:15 bar open = 1285.4   MATCHES the day's open
  09:16 bar open = 1288.3   does not
  15:29 bar close = 1287.0  MATCHES the day's close
```

The bar carrying the day's opening price is stamped **09:15** — the session open itself. So a
Breeze candle stamped `t` covers `[t, t+1min)`: **labels mark the bar's START.**

pips labels by **close** and treats a bar as usable at or after its label. So every Breeze
timestamp gains one interval on ingest. Getting this backwards would make every bar usable one
interval early — a uniform one-bar lookahead across every backtest, leaving no trace in any
result.

### Counting candles cannot answer this, and I assumed it could

The first version of the inference compared the candle count to the 375 minutes in a session.
Live data refused to cooperate, in two independent ways:

| day | candles | first | last | 15:30 present? |
|---|---|---|---|---|
| 2026-08-28 | **370** | 09:15 | 15:29 | no |
| 2025-08-28 | **376** | 09:15 | 15:30 | yes |
| 2023-08-29 | **376** | 09:15 | 15:30 | yes |
| 2016-08-30 | 375 | 09:15 | 15:29 | no |
| 2021-08-27 | 375 | 09:15 | 15:29 | no |

Neither the count nor the endpoints are stable, so neither can carry the decision. What does
is a price identity — the day's open belongs to exactly one minute bar, and that bar's label
gives the convention directly. The inference was rewritten around it.

## 2. Minutes with no trades are OMITTED, not zero-filled

370 candles where the session has 375 minutes: five minutes are simply absent. §3.4 insists
"a zero-volume bar ≠ a missing bar", and Breeze hands us the *missing* case — so the bar
builder must distinguish an absent minute from a traded-but-flat one, and must never
forward-fill one into the other.

## 3. The vendor returns bars OUTSIDE the continuous session

Widening the request window from 09:15–15:30 to 09:00–16:00:

```
count=372  first=2026-08-28 09:07:00  last=2026-08-28 15:31:00
```

09:07 is inside NSE's **pre-open** (09:00–09:08); 15:31 is past the continuous close. §3.5
excludes pre-open from continuous bars, so ingest must clip to the session rather than trusting
the window it asked for. Note the failure mode: asking for a wider window does not error, it
quietly returns prints from a different market phase.

## 4. History depth: at least 10 years of 1-minute data

§6 M3 records conflicting claims (3y vs 10y). Measured:

| requested | candles |
|---|---|
| 1 year back | 376 |
| 3 years back | 376 |
| 10 years back | 375 |

Ten years of **1-minute** data returns a full session. The 3y-vs-10y question is settled in
favour of 10y for this instrument. (A 5-year probe returned 0 — the date arithmetic landed on
a Sunday, not a depth limit. Recorded so nobody re-reads it as one.)

## 5. Confirmed from SAL-0002: IST wall-clock, and the `Z` is ignored

The donor's note held: `from_date`/`to_date` are read as IST wall-clock and the trailing `Z` is
ignored. Our windows were sent in that form and returned full sessions. Sending real UTC would
have silently clipped the window — again, no error, just fewer bars.

## Still unmeasured

- **Per-minute rate limit.** ADR-0012 records the owner-confirmed 100,000/day and 32 parallel
  fetches; the sustained and burst per-minute rate remains unmeasured, and `config/breeze.yaml`
  keeps a conservative 75/min marked unverified until it is. Measuring it means deliberately
  approaching a limit on a live account, which is worth doing carefully at M4 rather than
  casually here.
- **Websocket subscription capacity** (~2,000 scripts nominal) — belongs with M4's capture work.
- **BSE support ambiguity** — not probed; NSE is the launch surface.
