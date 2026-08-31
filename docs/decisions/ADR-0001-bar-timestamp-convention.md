# ADR-0001 · Bar timestamp convention

**Status:** accepted · **Date:** 2026-08-31 · **Contract:** `[C-BAR-01]`

## Context
Vendors disagree on whether a bar's timestamp is its open or its close. A silent mismatch
is a one-bar lookahead — the most expensive kind of leakage, because backtests love it.

## Decision
Bars are labelled by **close time** and are measurable at or after that label. A trade
exactly on an interior boundary `t` belongs to the bar **ending** at `t`; the session's
opening instant belongs to the first bar. Breeze's own convention is probed empirically at
M3/M4 and **normalized on ingest** — the normalization, not the vendor, is authoritative.

## Alternatives
- Open-labelled bars: requires every consumer to remember an offset. Rejected.
- Trust the vendor's documented convention: contradicted by the docs themselves. Rejected.

## Consequences
`pips.core.time.bar_label_ns` and the Rust `bars` crate share fixtures that pin the
boundary case. The M4 probe result is recorded as a follow-up ADR if Breeze differs.
