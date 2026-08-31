# ADR-0001 · Bar timestamp convention

**Status:** accepted · **Date:** 2026-08-31 · **Contract:** `[C-BAR-01]`

## Context
Vendors disagree on whether a bar's timestamp is its open or its close. A silent mismatch
is a one-bar lookahead — the most expensive kind of leakage, because backtests love it.

## Decision
Bars are labelled by **close time** and are measurable at or after that label. A trade
exactly on an interior boundary `t` belongs to the bar **ending** at `t`; the session's
opening instant belongs to the first bar. Breeze's own convention is probed empirically and
**normalized on ingest** — the normalization, not the vendor, is authoritative.

## Probed 2026-08-31: Breeze is OPEN-labelled

Measured, not assumed (`docs/reports/feasibility/breeze-bar-convention.md`). On 2026-08-28 the
daily bar opened at 1285.4 and the **09:15** one-minute bar opened at 1285.4; the daily close
of 1287.0 matched the **15:29** bar's close. A Breeze candle stamped `t` therefore covers
`[t, t+1min)`.

**Ingest adds one interval to every Breeze timestamp.** `BREEZE_BAR_LABELLING` in
`python/pips/data/breeze/probe.py` pins this, and a test asserts it, so a vendor change shows
up as a failure rather than as a silent shift in every bar.

Counting candles could not settle it: a full session returned 370 candles rather than 375
because untraded minutes are omitted, and other days returned 376. The decisive test is the
price identity above.

## Alternatives
- Open-labelled bars: requires every consumer to remember an offset. Rejected.
- Trust the vendor's documented convention: contradicted by the docs themselves. Rejected.

## Consequences
`pips.core.time.bar_label_ns` and the Rust `bars` crate share fixtures that pin the
boundary case. The M4 probe result is recorded as a follow-up ADR if Breeze differs.
