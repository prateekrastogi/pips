# ADR-0010 · Single execution venue at launch

**Status:** accepted · **Date:** 2026-08-31 · **Supersedes part of:** ADR-0006

## Context
The plan carried two execution venues from the start: Flattrade and Zerodha/Kite. Two venues
doubles the adapter surface, the capability snapshots, the cost calibration and the shadow
period, and none of that work is on the path to answering the only question that matters
first — whether any edge survives honest costs at all. The owner scoped it down: **Flattrade
only, as of now.**

## Decision
**Flattrade is the sole execution venue.** The `broker-zerodha` crate is removed. M9 calibrates
the Flattrade line, M25 shadows Flattrade alone, and P4 no longer claims cross-broker
robustness — with one venue it is not assessable, and asserting it would be decoration.

Three things are deliberately kept:

1. **`broker-protocol` keeps the venue-agnostic seam.** Adding a second adapter later is an
   addition, not a rewrite. Zerodha is deferred, not rejected.
2. **The Zerodha cost schedule survives as the "high-cost reference line" (§3.7).** It is no
   longer a venue; it is a stress line. The P3 gate's `net SR ≥ 1.0` against it stays at full
   severity — deleting it because we stopped trading there would have made the gate *easier*
   while looking like scope reduction, and weakening a gate is a human conversation plus an
   ADR (rule 10), never a side effect.
3. **Broker facts stay data, not constants.** Square-off times and rate limits still come from
   the daily `broker_capability` snapshot (§3.4), so a second venue is a new row, not a patch.

## Consequences
**GATE-0's escape hatch narrows to one option.** ADR-0006 offered two fallbacks if ICICI's
data-use answer is unfavourable: the Kite Connect entitled feed or Flattrade's API. Only the
second remains. If Flattrade's terms do not permit it, `[G-AUTH-0]` can be cleared only by the
ICICI clarification itself or by reopening a second venue. That is a real cost of this
decision and is recorded in §2.1 rather than discovered at M26.

**Flattrade's constraints now bind alone.** The API is limit-only, which is why protected
marketable-limit is already the portable default order type everywhere (§3.7) — that choice
predates this ADR and is unaffected. Rate limits 10/s and 40/min sit above the engine's own
5/s governor, so the governor still binds first.

**M1's harvest map is unchanged.** SAL-0024 recorded `NONE_FOUND` for a Zerodha client after a
full sweep; that row stays as history, and its need is simply no longer in the coverage set.

## Alternatives
- **Keep both venues:** doubles adapter, calibration and shadow work before any edge is proven.
- **Drop the Zerodha cost line too:** would have weakened the P3 gate under cover of a scope
  cut. Rejected — the stress line costs nothing to keep and is the more conservative test.
- **Delete `broker-protocol`'s abstraction:** would make a second venue a rewrite. Rejected;
  the seam is cheap while there is one implementation and expensive to reintroduce later.
